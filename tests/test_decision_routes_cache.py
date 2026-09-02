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
    # TESTING 은 팩토리 안의 워커 게이트가 읽는다 — 반환 후 설정하면 운영 워커 6개가
    # 이미 떠 있고, 기본 DB URI(실제 data/users.db)로 마이그레이션까지 돈다.
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-only',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })

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


def test_brief_fully_degraded_result_is_not_cached(client, monkeypatch):
    """전 소스 장애(신호 0 + errors)는 일간 캐시에 넣지 않는다 — 일시 장애 고착 방지."""
    from app.services.mirofish import decision_brief
    calls = []

    def degraded(s):
        calls.append(s)
        return {'symbol': s, 'status': 'avoid_data_gap', 'signals': [],
                'data_gaps': ['claw'], 'errors': {'claw': 'OperationalError: locked'}}

    monkeypatch.setattr(decision_brief, 'build_decision_brief', degraded)
    _call(client, monkeypatch, '/api/kr/decision/005930')
    _call(client, monkeypatch, '/api/kr/decision/005930')
    assert len(calls) == 2, '완전 열화 브리프가 캐시에서 서빙되면 안 된다'
    assert dc.cache_get('brief', '005930') is None


def test_brief_with_partial_errors_but_signals_is_still_cached(client, monkeypatch):
    """일부 소스만 죽고 신호가 있으면 정상 산출물 — 캐시한다."""
    from app.services.mirofish import decision_brief
    calls = []

    def partial(s):
        calls.append(s)
        return {'symbol': s, 'status': 'watch',
                'signals': [{'source': 'claw', 'stance': 'positive'}],
                'errors': {'jongga': 'RuntimeError: down'}}

    monkeypatch.setattr(decision_brief, 'build_decision_brief', partial)
    _call(client, monkeypatch, '/api/kr/decision/005930')
    _call(client, monkeypatch, '/api/kr/decision/005930')
    assert len(calls) == 1


def test_deep_busy_rejection_does_not_burn_quota(client, monkeypatch):
    """계약: 캐시 적중·합류·busy 는 무료 — busy 429 가 쿼터를 태우면 안 된다."""
    import threading
    from types import SimpleNamespace
    from flask import request as flask_request
    from app.services.mirofish import decision_brief

    monkeypatch.setenv(dc.DEEP_QUOTA_ENV, '2')
    monkeypatch.setenv('DECISION_JOB_MAX_CONCURRENT', '1')
    gate = threading.Event()
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: (gate.wait(3), {'symbol': s, 'error': None})[1])
    user = SimpleNamespace(id=7, is_admin=False)

    def post(symbol):
        from app.routes import kr_market
        with client.test_request_context(f'/api/kr/decision/{symbol}/analyze',
                                         method='POST', json={}):
            flask_request.current_user = user
            return kr_market.kr_decision_deep_analysis.__wrapped__(symbol)

    first = post('005930')                            # 시작 — 쿼터 1 차감 (유료)
    assert first[1] == 202
    busy = post('000660')                             # 동시 상한 초과 — 무료여야 한다
    assert busy[1] == 429 and busy[0].get_json()['error'] == 'busy'
    gate.set()
    _wait_deep('005930')
    # busy 가 환불됐다면 한도 2 중 1회만 쓴 상태 — 다음 소비가 마지막 1회로 성공한다.
    assert dc.consume_deep_quota(7) == (True, 0, 2)
