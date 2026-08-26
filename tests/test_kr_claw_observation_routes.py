"""Observation endpoints remain authenticated, read-only projections."""
from __future__ import annotations

from types import SimpleNamespace

from flask import Flask

import app.auth.decorators as auth
from app.routes.kr_claw import kr_claw_bp
from marketflow_claw import collectors
from marketflow_claw import observation as obs


def _user(*, active: bool):
    return SimpleNamespace(
        status='approved', is_admin=False, is_aibain_active=active,
    )


def test_observation_routes_require_aibain_and_do_not_scan(monkeypatch):
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-only'
    app.register_blueprint(kr_claw_bp, url_prefix='/api/kr/claw')
    monkeypatch.setattr(
        collectors, 'fetch_leaders',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('endpoint must not scan')),
    )
    monkeypatch.setattr(obs, 'build_scorecards', lambda **kwargs: {
        'schema_version': 'marketflow.claw.scorecards.v1', 'recent_instances': [],
    })
    monkeypatch.setattr(obs, 'build_quality', lambda **kwargs: {
        'schema_version': 'marketflow.claw.quality.v1', 'status': 'ok',
    })

    monkeypatch.setattr(auth, '_get_current_user', lambda: _user(active=False))
    denied = app.test_client().get('/api/kr/claw/quality')
    assert denied.status_code == 403

    monkeypatch.setattr(auth, '_get_current_user', lambda: _user(active=True))
    client = app.test_client()
    scorecards = client.get('/api/kr/claw/scorecards?window_days=20')
    quality = client.get('/api/kr/claw/quality')
    assert scorecards.status_code == quality.status_code == 200
    assert scorecards.get_json()['schema_version'] == 'marketflow.claw.scorecards.v1'
    assert quality.get_json()['schema_version'] == 'marketflow.claw.quality.v1'
    assert scorecards.headers['Cache-Control'] == 'no-cache, no-store, must-revalidate'
    assert quality.headers['Cache-Control'] == 'no-cache, no-store, must-revalidate'
