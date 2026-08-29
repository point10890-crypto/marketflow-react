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


# ─── 심층 분석 ──────────────────────────────────────────────

def test_deep_second_call_same_day_skips_the_llm(client, monkeypatch):
    """LLM 토론은 ~2분에 유료다. 하루에 한 번이면 충분하다."""
    from app.services.mirofish import decision_brief
    calls = []
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: calls.append(s) or {'symbol': s, 'verdict': {'verdict': 'HOLD'}})

    _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    out = _json(_call(client, monkeypatch, '/api/kr/decision/005930/analyze',
                      method='POST', json={}))
    assert len(calls) == 1
    assert out['cached'] is True


def test_deep_force_reruns_the_analysis(client, monkeypatch):
    from app.services.mirofish import decision_brief
    calls = []
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: calls.append(s) or {'symbol': s, 'verdict': {}})

    _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    _call(client, monkeypatch, '/api/kr/decision/005930/analyze',
          method='POST', json={'force': True})
    assert len(calls) == 2


def test_deep_error_payload_is_not_cached(client, monkeypatch):
    """분석이 실패한 결과를 하루 종일 물고 있으면 안 된다."""
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for',
                        lambda s, **kw: {'symbol': s, 'error': 'LLM down'})

    _call(client, monkeypatch, '/api/kr/decision/005930/analyze', method='POST', json={})
    assert dc.cache_get('deep', '005930') is None


def test_deep_exception_is_not_cached(client, monkeypatch):
    from app.services.mirofish import decision_brief

    def boom(_s, **_kw):
        raise RuntimeError('llm down')

    monkeypatch.setattr(decision_brief, 'run_deep_analysis_for', boom)
    resp = _call(client, monkeypatch, '/api/kr/decision/005930/analyze',
                 method='POST', json={})
    assert resp[1] == 500
    assert dc.cache_get('deep', '005930') is None


# ─── 종목 검색 (자동완성) ───────────────────────────────────

def _search(app, path):
    with app.test_request_context(path):
        from app.routes import kr_market
        return kr_market.kr_decision_search.__wrapped__()


def test_search_route_returns_candidates(client, monkeypatch):
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(decision_brief, 'search_symbols',
                        lambda q, limit=8: {'query': q, 'candidates': [
                            {'symbol': '005930', 'name': '삼성전자',
                             'confidence': 0.85, 'reason': 'chosung_exact'}]})
    out = _json(_search(client, '/api/kr/decision/search?q=%E3%85%85%E3%85%85%E3%85%88%E3%85%88'))
    assert out['candidates'][0]['symbol'] == '005930'


def test_search_route_without_query_is_empty_not_an_error(client, monkeypatch):
    out = _json(_search(client, '/api/kr/decision/search'))
    assert out['candidates'] == []


def test_search_route_survives_a_resolver_failure(client, monkeypatch):
    from app.services.mirofish import decision_brief

    def boom(_q, limit=8):
        raise RuntimeError('resolver down')

    monkeypatch.setattr(decision_brief, 'search_symbols', boom)
    resp = _search(client, '/api/kr/decision/search?q=삼성')
    assert _json(resp)['candidates'] == []
