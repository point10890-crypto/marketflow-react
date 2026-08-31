# -*- coding: utf-8 -*-
"""판단 파이프라인 성능 근본 수정 — 2026-08-31 프로덕션 실측 장애의 회귀 방지.

실측: 첫 브리프 74.9초(무부하 일요일) vs 로컬 1.6초. 원인 두 가지:
  1) _latest_scanner_run_paths 가 요청마다 scanner_runs 4,100개 디렉토리를 전수 스캔
  2) omni news_events 를 published_ts 인덱스 없이 LIKE 풀스캔
여기에 소스별 timings_ms 계측을 붙여 프로덕션이 스스로 병목을 말하게 한다.
"""
import os
import time

import pytest

import app.services.mirofish.alpha_scanner as alpha_scanner
import app.services.omni.ledger as omni_ledger
from app.services.mirofish import decision_brief


# ─── 1. 런 경로 스캔 TTL 메모 ────────────────────────────────

@pytest.fixture()
def runs_root(tmp_path, monkeypatch):
    root = tmp_path / 'scanner_runs'
    for rid in ('mfas_20260830120000_aaaaaaaaaaaa', 'mfas_20260831120000_bbbbbbbbbbbb'):
        d = root / rid
        d.mkdir(parents=True)
        (d / 'run.json').write_text('{"id": "%s"}' % rid, encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(root))
    alpha_scanner._invalidate_run_paths_cache()
    yield str(root)
    alpha_scanner._invalidate_run_paths_cache()


def test_run_paths_scan_is_memoized_within_ttl(runs_root, monkeypatch):
    calls = {'n': 0}
    real = alpha_scanner._scan_latest_run_paths

    def counting(root):
        calls['n'] += 1
        return real(root)

    monkeypatch.setattr(alpha_scanner, '_scan_latest_run_paths', counting)
    first = alpha_scanner._latest_scanner_run_paths()
    second = alpha_scanner._latest_scanner_run_paths()
    assert first == second and len(first) == 2
    assert first[0].endswith(os.path.join('mfas_20260831120000_bbbbbbbbbbbb', 'run.json'))
    assert calls['n'] == 1                      # TTL 안에서는 재스캔 없음


def test_run_paths_cache_expires_and_invalidates(runs_root, monkeypatch):
    calls = {'n': 0}
    real = alpha_scanner._scan_latest_run_paths
    monkeypatch.setattr(alpha_scanner, '_scan_latest_run_paths',
                        lambda root: (calls.__setitem__('n', calls['n'] + 1) or real(root)))

    alpha_scanner._latest_scanner_run_paths()
    alpha_scanner._invalidate_run_paths_cache()   # 새 런 저장 시와 같은 경로
    alpha_scanner._latest_scanner_run_paths()
    assert calls['n'] == 2

    monkeypatch.setenv('MIROFISH_RUN_PATHS_TTL_SECONDS', '0')
    alpha_scanner._latest_scanner_run_paths()
    alpha_scanner._latest_scanner_run_paths()
    assert calls['n'] == 4                      # TTL 0 → 매번 스캔 (킬스위치)


def test_run_paths_cache_is_keyed_by_root(runs_root, tmp_path, monkeypatch):
    """다른 테스트/호출자가 SCANNER_RUNS_ROOT 를 바꿔도 캐시가 새지 않는다 (claw memory.py 교훈)."""
    a = alpha_scanner._latest_scanner_run_paths()
    other = tmp_path / 'other_runs'
    (other / 'mfas_20260831130000_cccccccccccc').mkdir(parents=True)
    (other / 'mfas_20260831130000_cccccccccccc' / 'run.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(other))
    b = alpha_scanner._latest_scanner_run_paths()
    assert a != b and len(b) == 1


def test_create_scanner_run_invalidates_cache_source():
    """저장 직후 새 런이 보여야 한다 — create_scanner_run 이 무효화를 호출한다."""
    import inspect

    src = inspect.getsource(alpha_scanner.create_scanner_run)
    assert '_invalidate_run_paths_cache' in src


# ─── 2. omni 뉴스 원장 인덱스 ────────────────────────────────

def test_omni_ledger_has_published_ts_index(tmp_path, monkeypatch):
    monkeypatch.setattr(omni_ledger, 'DB_PATH', str(tmp_path / 'omni.db'))
    with omni_ledger.connect() as con:
        names = {r[1] for r in con.execute("PRAGMA index_list('news_events')").fetchall()}
    assert any('published' in n for n in names), names


# ─── 3. 브리프 timings 계측 ──────────────────────────────────

def test_brief_reports_per_source_timings(monkeypatch):
    monkeypatch.setattr(decision_brief, 'resolve_symbol', lambda raw: ('005930', '삼성전자'))
    monkeypatch.setattr(decision_brief, 'SOURCE_READERS', {
        'fast': lambda code: {'stance': 'positive', 'grade': 'A', 'as_of': 'x', 'detail': {}},
        'slow': lambda code: time.sleep(0.02) or None,
    })
    monkeypatch.setattr(decision_brief, '_read_news', lambda code: {'count': 0, 'items': []})
    monkeypatch.setattr(decision_brief, '_read_regime', lambda: {})

    out = decision_brief.build_decision_brief('005930')
    t = out.get('timings_ms')
    assert isinstance(t, dict)
    for key in ('fast', 'slow', 'news', 'regime', 'total'):
        assert key in t and isinstance(t[key], int), (key, t)
    assert t['slow'] >= 15 and t['total'] >= t['slow']
