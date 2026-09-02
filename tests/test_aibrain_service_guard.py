# -*- coding: utf-8 -*-
"""AI Brain 서비스 가드 — 체커 판정·상태전이 알림·프리웜·쿼터 계약 (2026-09-01 서비스화)."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

import app.services.mirofish.service_guard as sg
from app.services.mirofish import decision_cache as dc

KST = timezone(timedelta(hours=9))
MONDAY_1030 = datetime(2026, 8, 31, 10, 30, tzinfo=KST)   # 평일 장중
MONDAY_1400 = datetime(2026, 8, 31, 14, 0, tzinfo=KST)    # 평일 장중 (세션 경과 5h)
SUNDAY_2300 = datetime(2026, 8, 30, 23, 0, tzinfo=KST)    # 장외
HOLIDAY_1030 = datetime(2026, 5, 1, 10, 30, tzinfo=KST)   # 근로자의 날(금) — KRX 휴장


@pytest.fixture()
def guard_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, 'GUARD_ROOT', str(tmp_path))
    monkeypatch.setattr(sg, 'LATEST_PATH', str(tmp_path / 'latest.json'))
    monkeypatch.setattr(sg, 'HISTORY_PATH', str(tmp_path / 'history.jsonl'))
    monkeypatch.setattr(sg, 'STATE_PATH', str(tmp_path / 'state.json'))
    return tmp_path


# ─── 스캐너 체커 ─────────────────────────────────────────────

def _fake_run(tmp_path, age_hours, now):
    import app.services.mirofish.alpha_scanner as alpha_scanner
    d = tmp_path / 'runs' / 'mfas_20260831093000_aaaaaaaaaaaa'
    d.mkdir(parents=True)
    p = d / 'run.json'
    p.write_text('{}', encoding='utf-8')
    ts = now.timestamp() - age_hours * 3600
    os.utime(p, (ts, ts))
    return alpha_scanner, str(tmp_path / 'runs')


def test_scanner_fresh_in_session_is_ok(tmp_path, monkeypatch):
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    alpha_scanner._invalidate_run_paths_cache()
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {})
    assert sg.check_scanner(MONDAY_1030)['status'] == 'ok'


def test_scanner_stale_in_session_warns_then_fails(tmp_path, monkeypatch):
    alpha_scanner, root = _fake_run(tmp_path, age_hours=2.5, now=MONDAY_1400)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    alpha_scanner._invalidate_run_paths_cache()
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {})
    assert sg.check_scanner(MONDAY_1400)['status'] == 'warn'
    # 같은 나이라도 장외(일요일) 기준으로는 ok
    assert sg.check_scanner(SUNDAY_2300)['status'] == 'ok'
    # fail 임계(4h) 초과 — 장중 스캐너 침묵이 warn 에서 실제 fail 로 승격되는지
    run_file = tmp_path / 'runs' / 'mfas_20260831093000_aaaaaaaaaaaa' / 'run.json'
    ts = MONDAY_1400.timestamp() - 8 * 3600
    os.utime(run_file, (ts, ts))
    assert sg.check_scanner(MONDAY_1400)['status'] == 'fail'


def test_scanner_overnight_age_at_open_is_ok(tmp_path, monkeypatch):
    """개장 직후엔 전일(또는 금요일) 산출물이 최신인 게 정상 — false FAIL 금지."""
    monday_0930 = MONDAY_1030.replace(hour=9, minute=30)
    alpha_scanner, root = _fake_run(tmp_path, age_hours=65, now=monday_0930)  # 금요일 산출물
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    alpha_scanner._invalidate_run_paths_cache()
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {})
    out = sg.check_scanner(monday_0930)
    assert out['status'] == 'ok'
    assert out['detail']['stale_h'] == 0.5  # 지연은 세션 시작(09:00) 기준으로 잰다


def test_scanner_krx_holiday_uses_offhours_thresholds(tmp_path, monkeypatch):
    """평일 KRX 휴장일(근로자의 날 등)은 주말과 동일하게 장외 임계를 쓴다."""
    assert sg._market_session(HOLIDAY_1030) is False
    alpha_scanner, root = _fake_run(tmp_path, age_hours=6, now=HOLIDAY_1030)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    alpha_scanner._invalidate_run_paths_cache()
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {})
    assert sg.check_scanner(HOLIDAY_1030)['status'] == 'ok'  # 장중이면 fail 이었을 나이


def test_scanner_without_runs_fails(tmp_path, monkeypatch):
    import app.services.mirofish.alpha_scanner as alpha_scanner
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'empty'))
    alpha_scanner._invalidate_run_paths_cache()
    assert sg.check_scanner(MONDAY_1030)['status'] == 'fail'


# ─── 판단 프로브 ─────────────────────────────────────────────

def test_decision_probe_budget_and_slowest_source(tmp_path, monkeypatch):
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    monkeypatch.setattr(sg, 'hot_symbols', lambda limit=1: ['005930'])
    monkeypatch.setattr(decision_brief, 'build_decision_brief',
                        lambda s: {'timings_ms': {'scanner': 120, 'news': 30, 'total': 150}})
    out = sg.check_decision(MONDAY_1030)
    assert out['status'] == 'ok' and out['detail']['slowest_source'] == 'scanner'
    assert out['detail']['cache_write'] is True

    monkeypatch.setenv('AIBRAIN_DECISION_PROBE_FAIL_S', '0')
    assert sg.check_decision(MONDAY_1030)['status'] == 'fail'

    def boom(s):
        raise RuntimeError('db locked')
    monkeypatch.setattr(decision_brief, 'build_decision_brief', boom)
    monkeypatch.delenv('AIBRAIN_DECISION_PROBE_FAIL_S')
    out = sg.check_decision(MONDAY_1030)
    assert out['status'] == 'fail' and 'db locked' in out['detail']['probe_error']


# ─── 상태전이 알림 ───────────────────────────────────────────

def test_run_guard_alerts_only_on_transition(guard_paths, monkeypatch):
    state = {'v': 'fail'}
    monkeypatch.setattr(sg, 'CHECKERS', {
        'scanner': lambda now: {'status': state['v'], 'detail': {'reason': 'x'}},
    })
    sent: list[str] = []

    out1 = sg.run_guard(send_fn=sent.append, now=MONDAY_1030)
    assert out1['overall'] == 'fail' and len(sent) == 1 and '알파 스캐너' in sent[0]

    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert len(sent) == 1                                    # 쿨다운 안 재알림 없음

    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=40))
    assert len(sent) == 2                                    # 쿨다운 경과 후 1회 상기

    state['v'] = 'ok'
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=50))
    assert len(sent) == 3 and '복구' in sent[-1]             # 복구 1회

    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=60))
    assert len(sent) == 3                                    # 정상 지속은 침묵
    assert (guard_paths / 'latest.json').exists() and (guard_paths / 'history.jsonl').exists()


def test_silent_run_does_not_consume_transition_alert(guard_paths, monkeypatch):
    """send_fn=None 실행(관리자 조회 등)이 1회성 전이 알림을 소모하면 안 된다."""
    monkeypatch.setattr(sg, 'CHECKERS', {
        'scanner': lambda now: {'status': 'fail', 'detail': {'reason': 'x'}},
    })
    sg.run_guard(send_fn=None, now=MONDAY_1030)              # 무발송 실행이 전이를 먼저 관측
    sent: list[str] = []
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert len(sent) == 1                                    # 쿨다운에 눌리지 않고 발송된다
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=15))
    assert len(sent) == 1                                    # 발송 후에는 쿨다운 정상 적용


def test_silent_run_recovery_stays_silent_later(guard_paths, monkeypatch):
    """알린 적 없는 장애가 무발송 실행 중 복구되면 이후 '복구' 알림도 내지 않는다."""
    state = {'v': 'fail'}
    monkeypatch.setattr(sg, 'CHECKERS', {
        'scanner': lambda now: {'status': state['v'], 'detail': {'reason': 'x'}},
    })
    sg.run_guard(send_fn=None, now=MONDAY_1030)
    state['v'] = 'ok'
    sent: list[str] = []
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert sent == []                                        # 유령 복구 알림 없음


def test_send_failure_does_not_mark_alerted(guard_paths, monkeypatch):
    """발송 자체가 실패하면 alerted_at 을 남기지 않아 다음 실행이 재시도한다."""
    monkeypatch.setattr(sg, 'CHECKERS', {
        'scanner': lambda now: {'status': 'fail', 'detail': {'reason': 'x'}},
    })

    def boom(msg):
        raise RuntimeError('telegram down')

    with pytest.raises(RuntimeError):
        sg.run_guard(send_fn=boom, now=MONDAY_1030)
    sent: list[str] = []
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert len(sent) == 1                                    # 실패한 알림은 소모되지 않았다


def test_checker_exception_becomes_service_fail(guard_paths, monkeypatch):
    def boom(now):
        raise RuntimeError('broken checker')
    monkeypatch.setattr(sg, 'CHECKERS', {'decision': boom})
    out = sg.run_guard(send_fn=None, now=MONDAY_1030)
    assert out['services']['decision']['status'] == 'fail'
    assert 'broken checker' in out['services']['decision']['detail']['checker_error']


# ─── 프리웜 ─────────────────────────────────────────────────

def test_prewarm_skips_cached_and_survives_errors(tmp_path, monkeypatch):
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    monkeypatch.setenv('DECISION_CACHE_DISABLED', '')
    monkeypatch.setattr(sg, 'hot_symbols', lambda limit=12: ['005930', '000660', '035420'])
    dc.cache_put('brief', '005930', {'cached': True})

    def build(sym):
        if sym == '000660':
            raise RuntimeError('source down')
        return {'symbol': sym}
    monkeypatch.setattr(decision_brief, 'build_decision_brief', build)

    out = sg.prewarm_decision_cache()
    assert [w['symbol'] for w in out['warmed']] == ['035420']
    assert out['skipped'] == ['005930'] and '000660' in out['errors']
    hit = dc.cache_get('brief', '035420')
    assert hit and hit['symbol'] == '035420'   # 캐시 계층이 cached/cached_at 메타를 덧붙인다


# ─── 심층분석 쿼터 ──────────────────────────────────────────

def test_deep_quota_counts_and_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    monkeypatch.setenv(dc.DEEP_QUOTA_ENV, '2')
    assert dc.consume_deep_quota(7) == (True, 1, 2)
    assert dc.consume_deep_quota(7) == (True, 0, 2)
    assert dc.consume_deep_quota(7) == (False, 0, 2)
    assert dc.consume_deep_quota(8)[0] is True               # 사용자별 독립
    monkeypatch.setenv(dc.DEEP_QUOTA_ENV, '0')
    assert dc.consume_deep_quota(7) == (True, -1, 0)          # 0 = 무제한


def test_deep_quota_fails_open(monkeypatch):
    monkeypatch.setenv(dc.DEEP_QUOTA_ENV, '2')
    monkeypatch.setattr(dc, '_connect', lambda: (_ for _ in ()).throw(RuntimeError('disk full')))
    allowed, remaining, _ = dc.consume_deep_quota(7)
    assert allowed is True and remaining == -1                # 가용성 우선(fail-open)
