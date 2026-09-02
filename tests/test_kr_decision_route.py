# -*- coding: utf-8 -*-
"""GET /api/kr/decision/<symbol> — 종목 판단 브리프 라우트 계약.

읽기전용·인증 필수·mutation 없음. 스캔이나 발송을 트리거하지 않는다.
"""
from types import SimpleNamespace

from flask import Flask

import app.auth.decorators as auth
from app.routes.kr_market import kr_bp
from app.services.mirofish import decision_brief as db


def _app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-only'
    app.register_blueprint(kr_bp, url_prefix='/api/kr')
    return app


def _user(*, aibain: bool):
    # a3810b4: 판단 브리프는 AI Brain 구독자 전용 (@admin_or_aibain_required)
    return SimpleNamespace(status='approved', is_admin=False, is_approved=True,
                           is_pro_expired=False, is_aibain_active=aibain,
                           tier='pro' if aibain else 'free')


def test_route_is_registered_and_get_only():
    rule = next((r for r in _app().url_map.iter_rules()
                 if r.rule == '/api/kr/decision/<symbol>'), None)
    assert rule is not None, '판단 브리프 라우트가 등록되어야 한다'
    assert 'POST' not in rule.methods and 'DELETE' not in rule.methods


def test_requires_authenticated_pro(monkeypatch):
    app = _app()
    monkeypatch.setattr(auth, '_get_current_user', lambda: None)
    assert app.test_client().get('/api/kr/decision/005930').status_code in (401, 403)


def test_returns_brief_without_triggering_scan(monkeypatch):
    app = _app()
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user(aibain=True))

    from marketflow_claw import collectors
    monkeypatch.setattr(
        collectors, 'fetch_leaders',
        lambda *a, **k: (_ for _ in ()).throw(AssertionError('endpoint must not scan')))

    captured = {}

    def fake_build(symbol, **_kw):
        captured['symbol'] = symbol
        return {'schema_version': db.SCHEMA_VERSION, 'symbol': db.normalize_symbol(symbol),
                'status': 'watch', 'signals': [], 'data_gaps': [],
                'confidence_cap': 0.6, 'errors': {}}

    monkeypatch.setattr(db, 'build_decision_brief', fake_build)
    resp = app.test_client().get('/api/kr/decision/5930')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['schema_version'] == db.SCHEMA_VERSION
    assert payload['status'] in db.ALLOWED_STATUS
    assert payload['symbol'] == '005930'
    assert captured['symbol'] == '5930'
    assert 'no-store' in resp.headers.get('Cache-Control', '')


def test_rejects_malformed_symbol(monkeypatch):
    app = _app()
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user(aibain=True))

    def boom(symbol, **_kw):
        raise ValueError('symbol is required')

    monkeypatch.setattr(db, 'build_decision_brief', boom)
    resp = app.test_client().get('/api/kr/decision/%20%20')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'invalid_symbol'
