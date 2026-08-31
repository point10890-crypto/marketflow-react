# -*- coding: utf-8 -*-
"""판단 라우트의 캐시 배선 — 같은 날 같은 종목은 다시 계산하지 않는다.

계산 계층(decision_brief)은 캐시를 모른다. 라우트가 캐시를 조회하고 채운다.
강제 재계산 경로(force)를 항상 열어 둔다 — 사용자가 캐시본에 갇히면 안 된다.
"""
import pytest

from app.services.mirofish import decision_cache as dc


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    monkeypatch.setenv('DECISION_CACHE_DISABLED', '')

    from app import create_app
    app = create_app()
    app.config['TESTING'] = True

    # 인증은 이 테스트의 관심사가 아니다 — 라우트 함수를 직접 호출한다.
    return app


def _call(app, monkeypatch, path, method='GET', **kw):
    with app.test_request_context(path, method=method, **kw):
        from app.routes import kr_market
        if method == 'GET':
            return kr_market.kr_decision_brief.__wrapped__('005930')
        return kr_market.kr_decision_deep_analysis.__wrapped__('005930')


def _json(resp):
    body = resp[0] if isinstance(resp, tuple) else resp
    return body.get_json()


# ─── 브리프 ─────────────────────────────────────────────────

def test_brief_computes_on_first_call(client, monkeypatch):
    from app.services.mirofish import decision_brief
    calls = []
    monkeypatch.setattr(decision_brief, 'build_decision_brief',
                        lambda s: calls.append(s) or {'symbol': s, 'status': 'neutral'})

    out = _json(_call(client, monkeypatch, '/api/kr/decision/005930'))
    assert out['status'] == 'neutral'
    assert calls == ['005930']


def test_brief_second_call_same_day_is_served_from_cache(client, monkeypatch):
    from app.services.mirofish import decision_brief
    calls = []
    monkeypatch.setattr(decision_brief, 'build_decision_brief',
                        lambda s: calls.append(s) or {'symbol': s, 'status': 'neutral'})

    _call(client, monkeypatch, '/api/kr/decision/005930')
    out = _json(_call(client, monkeypatch, '/api/kr/decision/005930'))
    assert len(calls) == 1, '두 번째 조회는 재계산하면 안 된다'
    assert out['cached'] is True
    assert out['cached_at']


def test_brief_force_bypasses_the_cache(client, monkeypatch):
    from app.services.mirofish import decision_brief
    calls = []
    monkeypatch.setattr(decision_brief, 'build_decision_brief',
                        lambda s: calls.append(s) or {'symbol': s, 'status': 'neutral'})

    _call(client, monkeypatch, '/api/kr/decision/005930')
    out = _json(_call(client, monkeypatch, '/api/kr/decision/005930?force=1'))
    assert len(calls) == 2
    assert not out.get('cached')


def test_brief_failure_is_not_cached(client, monkeypatch):
    from app.services.mirofish import decision_brief

    def boom(_s):
        raise RuntimeError('source down')

    monkeypatch.setattr(decision_brief, 'build_decision_brief', boom)
    resp = _call(client, monkeypatch, '/api/kr/decision/005930')
    assert resp[1] == 500
    assert dc.cache_get('brief', '005930') is None


# --- 심층 분석 (job+poll, 2026-09-01 전환) -----------------------

def _wait_deep(key='005930', timeout=5.0):
    import time
    from app.services.mirofish import decision_jobs
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = decision_jobs.status(key)
        if st['state'] in ('done', 'error', 'none'):
            return st
        time.sleep(0.02)
    raise AssertionError(f'job stuck: {decision_jobs.status(key)}')


@pytest.fixture(autouse=True)
def _jobs_clean():
    from app.services.mirofish import decision_jobs
    decision_jobs._reset_for_tests()
    yield
    decision_jobs._reset_for_tests()


def test_deep_starts_job_then_serves_cache_same_day(client, monkeypatch):
    """LLM 토론은 ~1분+에 유료다. 첫 호출=202 잡 시작, 같은 날 재호출=캐시 200."""
    from app.services.mirofish import decision_brief
    calls = []
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: calls.append(s) or {'symbol': s, 'error': None,
                                                            'verdict': {'verdict': 'HOLD'}})

    first = _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    assert first[1] == 202 and _json(first)['state'] == 'running'
    assert _wait_deep()['state'] == 'done'

    out = _json(_call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={}))
    assert len(calls) == 1 and out['cached'] is True


def test_deep_status_endpoint_serves_done_payload(client, monkeypatch):
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: {'symbol': s, 'error': None, 'verdict': {'verdict': 'HOLD'}})

    _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    _wait_deep()
    with client.test_request_context('/api/kr/decision/005930/analyze/status'):
        from app.routes import kr_market
        st = kr_market.kr_decision_deep_status.__wrapped__('005930').get_json()
    assert st['state'] == 'done' and st['payload']['verdict']['verdict'] == 'HOLD'


def test_deep_duplicate_post_joins_running_job(client, monkeypatch):
    import threading
    from app.services.mirofish import decision_brief
    gate = threading.Event()
    calls = []

    def slow(s, **kw):
        calls.append(s)
        gate.wait(3)
        return {'symbol': s, 'error': None}

    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for', slow)
    _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    second = _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    assert second[1] == 202 and _json(second)['state'] == 'running'
    gate.set()
    _wait_deep()
    assert len(calls) == 1                                   # 잡은 하나만 돌았다


def test_deep_force_reruns_the_analysis(client, monkeypatch):
    from app.services.mirofish import decision_brief
    calls = []
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: calls.append(s) or {'symbol': s, 'error': None, 'verdict': {}})

    _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    _wait_deep()
    resp = _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST',
                 json={'force': True})
    assert resp[1] == 202                                    # 캐시가 있어도 재실행 시작
    _wait_deep()
    assert len(calls) == 2


def test_deep_error_payload_is_not_cached(client, monkeypatch):
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: {'symbol': s, 'error': 'LLM down'})

    _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    st = _wait_deep()
    assert st['state'] == 'error'
    assert dc.cache_get('deep', '005930') is None
