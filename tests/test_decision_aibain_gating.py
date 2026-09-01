# -*- coding: utf-8 -*-
"""종목판단 서비스는 AI Brain 구독자 전용 — Pro 단독 토큰은 403 (2026-09-01 정책)."""
from types import SimpleNamespace

import pytest


def _user(*, aibain: bool, admin: bool = False):
    return SimpleNamespace(
        id=42, status='approved', is_admin=admin, is_aibain_active=aibain,
        is_approved=True, tier='pro', is_pro_expired=False,
        email='t@example.com', role='admin' if admin else 'user')


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from app.services.mirofish import decision_cache as dc
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'cache.db'))
    from app import create_app
    flask_app = create_app()
    flask_app.config['TESTING'] = True
    return flask_app


DECISION_PATHS = [
    ('GET', '/api/kr/rag/status'),
    ('GET', '/api/kr/decision/search?q=sk'),
    ('GET', '/api/kr/decision/005930'),
    ('POST', '/api/kr/decision/005930/analyze'),
    ('GET', '/api/kr/decision/005930/analyze/status'),
]


def _call(app, monkeypatch, user, method, path):
    import app.auth.decorators as deco
    monkeypatch.setattr(deco, '_get_current_user', lambda: user)
    client = app.test_client()
    return client.open(path, method=method, json={} if method == 'POST' else None)


@pytest.mark.parametrize('method,path', DECISION_PATHS)
def test_pro_without_aibain_is_rejected(app, monkeypatch, method, path):
    resp = _call(app, monkeypatch, _user(aibain=False), method, path)
    assert resp.status_code == 403
    assert 'AI Brain' in (resp.get_json() or {}).get('error', '')


def test_aibain_subscriber_passes_the_gate(app, monkeypatch):
    """구독자는 게이트를 통과해 실제 핸들러에 도달한다 (403 이 아니어야 한다)."""
    from app.services.mirofish import decision_brief
    monkeypatch.setattr(decision_brief, 'search_symbols',
                        lambda q, limit=8: {'query': q, 'candidates': []})
    resp = _call(app, monkeypatch, _user(aibain=True), 'GET', '/api/kr/decision/search?q=sk')
    assert resp.status_code == 200


def test_leading_stocks_stays_pro(app, monkeypatch):
    """주도주LIVE 등 KR 메뉴는 Pro 정책 유지 — AI Brain 게이트에 걸리면 안 된다."""
    resp = _call(app, monkeypatch, _user(aibain=False), 'GET', '/api/kr/screener/leading/status')
    assert resp.status_code != 403 or 'AI Brain' not in (resp.get_json() or {}).get('error', '')
