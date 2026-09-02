# -*- coding: utf-8 -*-
"""심층분석 job+poll — 엣지 100초 한계 해소 경로의 계약."""
import threading
import time

import pytest

import app.services.mirofish.decision_jobs as jobs
from app.services.mirofish import decision_cache as dc


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    monkeypatch.setenv('DECISION_CACHE_DISABLED', '')
    jobs._reset_for_tests()
    yield
    jobs._reset_for_tests()


def _install_runner(monkeypatch, fn):
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for', fn)


def _wait_done(key, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = jobs.status(key)
        if st['state'] in ('done', 'error'):
            return st
        time.sleep(0.02)
    raise AssertionError(f'job not finished: {jobs.status(key)}')


def test_job_lifecycle_and_cache_write(monkeypatch):
    _install_runner(monkeypatch, lambda sym: {'symbol': sym, 'error': None, 'status': 'watch'})
    out = jobs.start('005930', '005930')
    assert out['status'] == 'started' and out['job']['state'] == 'running'
    st = _wait_done('005930')
    assert st['state'] == 'done' and st['payload']['status'] == 'watch'
    hit = dc.cache_get('deep', '005930')
    assert hit and hit['status'] == 'watch'          # 폴링 결과 = 캐시 산출물


def test_duplicate_start_joins_existing_job(monkeypatch):
    gate = threading.Event()
    _install_runner(monkeypatch, lambda sym: (gate.wait(3), {'symbol': sym, 'error': None})[1])
    assert jobs.start('005930', '005930')['status'] == 'started'
    assert jobs.start('005930', '005930')['status'] == 'joined'   # 같은 종목 중복 합류
    gate.set()
    assert _wait_done('005930')['state'] == 'done'


def test_concurrency_cap_returns_busy(monkeypatch):
    gate = threading.Event()
    _install_runner(monkeypatch, lambda sym: (gate.wait(3), {'symbol': sym, 'error': None})[1])
    monkeypatch.setenv('DECISION_JOB_MAX_CONCURRENT', '1')
    assert jobs.start('A', 'A')['status'] == 'started'
    busy = jobs.start('B', 'B')
    assert busy['status'] == 'busy' and busy['max_concurrent'] == 1
    gate.set()
    _wait_done('A')
    assert jobs.start('B', 'B')['status'] == 'started'            # 슬롯이 비면 시작 가능
    _wait_done('B')   # B 를 완주시킨다 — 스레드가 teardown(monkeypatch 원복)과 경합하면
                      # 실제 LLM 러너·운영 캐시 DB 를 칠 수 있다


def test_error_payload_is_not_cached(monkeypatch):
    _install_runner(monkeypatch, lambda sym: {'symbol': sym, 'error': 'LLM down'})
    jobs.start('005930', '005930')
    st = _wait_done('005930')
    assert st['state'] == 'error' and st['error'] == 'LLM down'
    assert dc.cache_get('deep', '005930') is None                 # 실패는 하루 종일 물고 있지 않는다


def test_thread_start_failure_leaves_no_phantom_running_job(monkeypatch):
    """Thread.start() 실패가 유령 'running' 잡으로 남아 종목·슬롯을 영구 점유하면 안 된다."""
    _install_runner(monkeypatch, lambda sym: {'symbol': sym, 'error': None})
    real_start = threading.Thread.start
    calls = {'n': 0}

    def flaky(self):
        if calls['n'] == 0:
            calls['n'] += 1
            raise RuntimeError("can't start new thread")
        return real_start(self)

    monkeypatch.setattr(threading.Thread, 'start', flaky)
    with pytest.raises(RuntimeError):
        jobs.start('005930', '005930')
    assert jobs.status('005930')['state'] == 'error'              # running 이 아니다
    assert jobs.running_count() == 0                              # 동시 슬롯 미점유
    assert jobs.start('005930', '005930')['status'] == 'started'  # 같은 종목 재시작 가능
    _wait_done('005930')


def test_runner_exception_becomes_error(monkeypatch):
    def boom(sym):
        raise RuntimeError('engine crashed')
    _install_runner(monkeypatch, boom)
    jobs.start('005930', '005930')
    st = _wait_done('005930')
    assert st['state'] == 'error' and 'engine crashed' in st['error']


def test_unknown_key_is_none():
    assert jobs.status('999999') == {'state': 'none'}
