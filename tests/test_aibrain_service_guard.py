# -*- coding: utf-8 -*-
"""AI Brain 서비스 가드 — 체커 판정·실패 진입 알림·프리웜·쿼터 계약 (2026-09-01 서비스화)."""
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
    p.write_text(json.dumps({'id': d.name, 'status': 'completed', 'candidates': []}), encoding='utf-8')
    ts = now.timestamp() - age_hours * 3600
    os.utime(p, (ts, ts))
    return alpha_scanner, str(tmp_path / 'runs')


def test_scanner_fresh_in_session_is_ok(tmp_path, monkeypatch):
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    alpha_scanner._invalidate_run_paths_cache()
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': 'mfas_20260831093000_aaaaaaaaaaaa'})
    assert sg.check_scanner(MONDAY_1030)['status'] == 'ok'


def test_scanner_stale_in_session_warns_then_fails(tmp_path, monkeypatch):
    alpha_scanner, root = _fake_run(tmp_path, age_hours=2.5, now=MONDAY_1400)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    alpha_scanner._invalidate_run_paths_cache()
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': 'mfas_20260831093000_aaaaaaaaaaaa'})
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
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': 'mfas_20260831093000_aaaaaaaaaaaa'})
    out = sg.check_scanner(monday_0930)
    assert out['status'] == 'ok'
    assert out['detail']['stale_h'] == 0.5  # 지연은 세션 시작(09:00) 기준으로 잰다


def test_scanner_krx_holiday_uses_offhours_thresholds(tmp_path, monkeypatch):
    """평일 KRX 휴장일(근로자의 날 등)은 주말과 동일하게 장외 임계를 쓴다."""
    assert sg._market_session(HOLIDAY_1030) is False
    alpha_scanner, root = _fake_run(tmp_path, age_hours=6, now=HOLIDAY_1030)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    alpha_scanner._invalidate_run_paths_cache()
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': 'mfas_20260831093000_aaaaaaaaaaaa'})
    assert sg.check_scanner(HOLIDAY_1030)['status'] == 'ok'  # 장중이면 fail 이었을 나이


def test_scanner_without_runs_fails(tmp_path, monkeypatch):
    import app.services.mirofish.alpha_scanner as alpha_scanner
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'empty'))
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {})
    alpha_scanner._invalidate_run_paths_cache()
    assert sg.check_scanner(MONDAY_1030)['status'] == 'fail'


def test_scanner_guard_reads_only_the_completed_monitor_reference(tmp_path, monkeypatch):
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, '_latest_scanner_run_paths', lambda: pytest.fail('archive enumeration forbidden'))
    monitor_calls, run_calls = [], []
    reader = alpha_scanner.read_scanner_run
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: monitor_calls.append(1) or {'last_run_id': run_id, 'last_status': 'unchanged'})
    monkeypatch.setattr(alpha_scanner, 'read_scanner_run', lambda ref: run_calls.append(ref) or reader(ref))
    result = sg.check_scanner(MONDAY_1030)
    assert result['status'] == 'ok'
    assert result['detail']['lookup_basis'] == 'monitor_reference'
    assert result['detail']['run_id'] == run_id
    assert result['detail']['latest_run_age_h'] == 0.5
    assert result['detail']['monitor']['last_status'] == 'unchanged'
    assert monitor_calls == [1] and run_calls == [run_id]


@pytest.mark.parametrize('case', ['missing_reference', 'unsafe', 'missing_run', 'corrupt', 'running', 'identity_mismatch', 'incomplete'])
def test_scanner_guard_bad_reference_never_falls_back_to_the_archive(tmp_path, monkeypatch, case):
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, '_latest_scanner_run_paths', lambda: pytest.fail('archive enumeration forbidden'))
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    reference = run_id
    header = tmp_path / 'runs' / run_id / 'run.json'
    if case == 'missing_reference':
        reference = None
    elif case == 'unsafe':
        reference = '../outside'
    elif case == 'missing_run':
        reference = 'mfas_20260831103000_bbbbbbbbbbbb'
    elif case == 'corrupt':
        header.write_text('{bad json', encoding='utf-8')
    elif case == 'running':
        header.write_text(json.dumps({'id': run_id, 'status': 'running', 'candidates': []}), encoding='utf-8')
    elif case == 'identity_mismatch':
        header.write_text(json.dumps({'id': 'mfas_20260831103000_bbbbbbbbbbbb', 'status': 'completed', 'candidates': []}), encoding='utf-8')
    else:
        header.write_text(json.dumps({'id': run_id, 'status': 'completed'}), encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': reference})
    result = sg.check_scanner(MONDAY_1030)
    assert result['status'] == 'fail'
    assert result['detail']['reason'] == 'reference_unavailable'
    assert result['detail']['lookup_basis'] == 'monitor_reference'


def test_hot_symbols_uses_monitor_reference_without_latest_lookup(tmp_path, monkeypatch):
    from app.services.mirofish import goodrich_ledger
    from app.services import kis_screener
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    header = tmp_path / 'runs' / run_id / 'run.json'
    header.write_text(json.dumps({'id': run_id, 'status': 'completed', 'candidates': [{'symbol': '005930', 'rank': 1}]}), encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': run_id})
    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', lambda **kwargs: pytest.fail('archive enumeration forbidden'))
    monkeypatch.setattr(goodrich_ledger, 'read_ledger', lambda: [])
    monkeypatch.setattr(kis_screener, 'load_latest', lambda: {})
    assert sg.hot_symbols() == ['005930']


# ─── 판단 프로브 ─────────────────────────────────────────────

def test_decision_probe_budget_and_slowest_source(tmp_path, monkeypatch):
    from app.services.mirofish import decision_brief
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': run_id})
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    monkeypatch.setattr(sg, 'hot_symbols', lambda limit=1: ['005930'])
    monkeypatch.setattr(decision_brief, 'build_decision_brief',
                        lambda s, **kwargs: {'timings_ms': {'scanner': 120, 'news': 30, 'total': 150}})
    out = sg.check_decision(MONDAY_1030)
    assert out['status'] == 'ok' and out['detail']['slowest_source'] == 'scanner'
    assert out['detail']['cache_write'] is False
    assert out['detail']['probe_cache_policy'] == 'monitor_reference_no_warm'

    monkeypatch.setenv('AIBRAIN_DECISION_PROBE_FAIL_S', '0')
    assert sg.check_decision(MONDAY_1030)['status'] == 'fail'

    def boom(s, **kwargs):
        raise RuntimeError('db locked')
    monkeypatch.setattr(decision_brief, 'build_decision_brief', boom)
    monkeypatch.delenv('AIBRAIN_DECISION_PROBE_FAIL_S')
    out = sg.check_decision(MONDAY_1030)
    assert out['status'] == 'fail' and 'db locked' in out['detail']['probe_error']


def test_decision_probe_binds_monitor_reference_without_replacing_normal_cache(tmp_path, monkeypatch):
    from app.services.mirofish import decision_brief
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': run_id})
    monkeypatch.setattr(alpha_scanner, '_latest_scanner_run_paths', lambda: pytest.fail('archive enumeration forbidden'))
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    monkeypatch.setenv('DECISION_CACHE_DISABLED', '')
    dc.cache_put('brief', '005930', {'snapshot': 'normal_latest'})
    original = dc.cache_get('brief', '005930')
    calls = []

    def build(symbol, *, scanner_run_id):
        calls.append((symbol, scanner_run_id))
        return {'snapshot': 'monitor_reference', 'timings_ms': {'scanner': 1, 'total': 2}}

    monkeypatch.setattr(decision_brief, 'build_decision_brief', build)
    monkeypatch.setattr(dc, 'cache_put', lambda *args: pytest.fail('guard must not warm normal cache'))
    result = sg.check_decision(MONDAY_1030, probe_symbol='005930')
    assert result['status'] == 'ok'
    assert calls == [('005930', run_id)]
    assert result['detail']['run_id'] == run_id
    assert result['detail']['lookup_basis'] == 'monitor_reference'
    assert result['detail']['cache_write'] is False
    assert dc.cache_get('brief', '005930') == original


@pytest.mark.parametrize('reference', [None, '../outside'])
def test_decision_probe_defers_without_a_valid_monitor_reference(tmp_path, monkeypatch, reference):
    from app.services.mirofish import alpha_scanner, decision_brief
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': reference})
    monkeypatch.setattr(alpha_scanner, '_latest_scanner_run_paths', lambda: pytest.fail('archive enumeration forbidden'))
    monkeypatch.setattr(decision_brief, 'build_decision_brief', lambda *args, **kwargs: pytest.fail('probe should be deferred'))
    monkeypatch.setattr(dc, 'cache_put', lambda *args: pytest.fail('guard must not warm normal cache'))
    result = sg.check_decision(MONDAY_1030, probe_symbol='005930')
    assert result['status'] == 'warn'
    assert result['detail']['reason'] == 'reference_unavailable'
    assert result['detail']['probe_deferred'] is True
    assert result['detail']['cache_write'] is False


def test_guard_scanner_and_decision_never_enumerate_or_warm_normal_cache(tmp_path, monkeypatch, guard_paths):
    from app.services.mirofish import decision_brief, goodrich_ledger
    from app.services import kis_screener
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    header = tmp_path / 'runs' / run_id / 'run.json'
    header.write_text(json.dumps({'id': run_id, 'status': 'completed',
                                 'candidates': [{'symbol': '005930', 'rank': 1, 'action': 'BUY'}]}), encoding='utf-8')
    os.utime(header, (MONDAY_1030.timestamp() - 1800,) * 2)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': run_id})
    monkeypatch.setattr(alpha_scanner, '_latest_scanner_run_paths', lambda: pytest.fail('archive enumeration forbidden'))
    monkeypatch.setattr(dc, 'cache_put', lambda *args: pytest.fail('guard must not warm normal cache'))
    monkeypatch.setattr(goodrich_ledger, 'read_ledger', lambda: [])
    monkeypatch.setattr(kis_screener, 'load_latest', lambda: {})
    for name in decision_brief.SOURCE_READERS:
        if name != 'scanner':
            monkeypatch.setitem(decision_brief.SOURCE_READERS, name, lambda symbol: None)
    monkeypatch.setattr(decision_brief, '_read_news', lambda symbol: {'count': 0, 'items': []})
    monkeypatch.setattr(decision_brief, '_read_regime', lambda: {})
    monkeypatch.setattr(sg, 'CHECKERS', {'scanner': sg.check_scanner, 'decision': sg.check_decision})
    result = sg.run_guard(now=MONDAY_1030)
    assert result['overall'] == 'ok'
    assert result['services']['scanner']['detail']['run_id'] == run_id
    assert result['services']['decision']['detail']['run_id'] == run_id
    assert result['services']['decision']['detail']['probe_symbol'] == '005930'
    assert (guard_paths / 'latest.json').is_file()


def test_decision_probe_symbol_is_bound_to_the_already_validated_run(tmp_path, monkeypatch):
    from app.services.mirofish import decision_brief
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    header = tmp_path / 'runs' / run_id / 'run.json'
    header.write_text(json.dumps({'id': run_id, 'status': 'completed',
                                 'candidates': [{'code': '005930', 'rank': 2}, {'symbol': '000660', 'rank': 1}]}), encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monitor_reads = []
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: monitor_reads.append(1) or {'last_run_id': run_id})
    monkeypatch.setattr(sg, 'hot_symbols', lambda **kwargs: pytest.fail('do not resolve a second monitor snapshot'))
    calls = []
    monkeypatch.setattr(decision_brief, 'build_decision_brief',
                        lambda symbol, **kwargs: calls.append((symbol, kwargs)) or {'timings_ms': {}})
    result = sg.check_decision(MONDAY_1030)
    assert result['status'] == 'ok'
    assert calls == [('000660', {'scanner_run_id': run_id})]
    assert monitor_reads == [1]


@pytest.mark.parametrize('errors,fail_threshold,expected_status', [
    ({'scanner': 'ValueError: scanner_reference_unavailable'}, '20', 'warn'),
    ({'scanner': 'ValueError: scanner_reference_unavailable'}, '0', 'fail'),
    ({}, '20', 'ok'),
    ({'news': 'RuntimeError: source unavailable'}, '20', 'ok'),
])
def test_decision_probe_reports_scanner_errors_without_promoting_latency_failure(tmp_path, monkeypatch, errors, fail_threshold, expected_status):
    from app.services.mirofish import decision_brief
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': run_id})
    monkeypatch.setenv('AIBRAIN_DECISION_PROBE_FAIL_S', fail_threshold)
    monkeypatch.setattr(decision_brief, 'build_decision_brief', lambda *args, **kwargs:
                        {'timings_ms': {'scanner': 1}, 'errors': errors, 'data_gaps': ['scanner']})
    result = sg.check_decision(MONDAY_1030, probe_symbol='005930')
    assert result['status'] == expected_status
    assert result['detail']['probe_error_sources'] == sorted(errors)
    assert result['detail']['cache_write'] is False


def test_decision_probe_warns_when_reference_changes_after_initial_validation(tmp_path, monkeypatch):
    from app.services.mirofish import decision_brief
    alpha_scanner, root = _fake_run(tmp_path, age_hours=0.5, now=MONDAY_1030)
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', root)
    monkeypatch.setattr(alpha_scanner, 'read_scanner_monitor_state', lambda: {'last_run_id': run_id})
    run_reads = []

    def read_run(reference):
        run_reads.append(reference)
        return {'id': reference, 'status': 'completed' if len(run_reads) == 1 else 'running',
                'candidates': [{'symbol': '005930', 'action': 'BUY'}]}

    monkeypatch.setattr(alpha_scanner, 'read_scanner_run', read_run)
    monkeypatch.setattr(alpha_scanner, '_latest_scanner_run_paths', lambda: pytest.fail('archive enumeration forbidden'))
    for name in decision_brief.SOURCE_READERS:
        if name != 'scanner':
            monkeypatch.setitem(decision_brief.SOURCE_READERS, name, lambda symbol: None)
    monkeypatch.setattr(decision_brief, '_read_news', lambda symbol: {'count': 0, 'items': []})
    monkeypatch.setattr(decision_brief, '_read_regime', lambda: {})
    result = sg.check_decision(MONDAY_1030, probe_symbol='005930')
    assert result['status'] == 'warn'
    assert result['detail']['probe_error_sources'] == ['scanner']
    assert run_reads == [run_id, run_id]


# ─── 실패 진입 알림 ─────────────────────────────────────────

def test_run_guard_alerts_only_when_failure_starts(guard_paths, monkeypatch):
    state = {'v': 'fail'}
    monkeypatch.setattr(sg, 'CHECKERS', {
        'scanner': lambda now: {'status': state['v'], 'detail': {'reason': 'x'}},
    })
    sent: list[str] = []

    out1 = sg.run_guard(send_fn=sent.append, now=MONDAY_1030)
    assert out1['overall'] == 'fail' and len(sent) == 1 and '알파 스캐너' in sent[0]

    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert len(sent) == 1                                    # 동일 장애 지속은 침묵

    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=40))
    assert len(sent) == 1                                    # 시간이 지나도 반복 발송 없음

    state['v'] = 'ok'
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=50))
    assert len(sent) == 1                                    # 복구 OK 는 상태 기록만

    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=60))
    assert len(sent) == 1                                    # 정상 지속은 침묵

    state['v'] = 'fail'
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=70))
    assert len(sent) == 2                                    # 복구 후 새 장애는 다시 알림
    assert (guard_paths / 'latest.json').exists() and (guard_paths / 'history.jsonl').exists()


def test_warn_is_recorded_without_telegram_until_it_becomes_fail(guard_paths, monkeypatch):
    """warn 과 ok 는 발송하지 않고, 실제 fail 로 승격될 때만 알린다."""
    state = {'v': 'warn'}
    monkeypatch.setattr(sg, 'CHECKERS', {
        'decision': lambda now: {'status': state['v'], 'detail': {'probe_s': 8.1}},
    })
    sent: list[str] = []

    out1 = sg.run_guard(send_fn=sent.append, now=MONDAY_1030)
    assert out1['overall'] == 'warn'
    assert sent == []

    state['v'] = 'ok'
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert sent == []

    state['v'] = 'warn'
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=20))
    assert sent == []

    state['v'] = 'fail'
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=30))
    assert len(sent) == 1
    assert '판단 조회: FAIL' in sent[0]


def test_silent_run_does_not_consume_transition_alert(guard_paths, monkeypatch):
    """send_fn=None 실행(관리자 조회 등)이 1회성 전이 알림을 소모하면 안 된다."""
    monkeypatch.setattr(sg, 'CHECKERS', {
        'scanner': lambda now: {'status': 'fail', 'detail': {'reason': 'x'}},
    })
    sg.run_guard(send_fn=None, now=MONDAY_1030)              # 무발송 실행이 전이를 먼저 관측
    sent: list[str] = []
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert len(sent) == 1                                    # 무발송 관측에 눌리지 않고 발송된다
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=15))
    assert len(sent) == 1                                    # 발송 후 동일 장애 지속은 침묵


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


def test_false_send_result_does_not_mark_alerted(guard_paths, monkeypatch):
    """스케줄러의 텔레그램 발송 실패(False)는 성공 발송으로 기록하지 않는다."""
    monkeypatch.setattr(sg, 'CHECKERS', {
        'decision': lambda now: {'status': 'fail', 'detail': {'probe_s': 35.69}},
    })

    assert sg.run_guard(send_fn=lambda msg: False, now=MONDAY_1030)['overall'] == 'fail'
    sent: list[str] = []
    sg.run_guard(send_fn=sent.append, now=MONDAY_1030 + timedelta(minutes=10))
    assert len(sent) == 1


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
