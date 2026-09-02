"""Task 7 — admin endpoints for TradingAgents deep verification.

Endpoints (prefix /api/admin/mirofish, guard admin_or_aibain_required):
  POST /tradingagents/analyze
  GET  /tradingagents/runs
  GET  /tradingagents/runs/<run_id>
  GET  /tradingagents/status
"""

from __future__ import annotations

import pytest
from flask import Flask

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.routes.admin_mirofish_tradingagents import admin_mirofish_tradingagents_bp


@pytest.fixture
def admin_client():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-tradingagents-secret',
    })
    client = app.test_client()
    with app.app_context():
        admin = User(
            email='ta-admin@test.local',
            name='TA Admin',
            role='admin',
            status='approved',
            tier='premium',
        )
        admin.set_password('test-password-1234')
        db.session.add(admin)
        db.session.commit()
        token = generate_token(admin.id)
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


def test_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_tradingagents_bp, url_prefix='/api/admin/mirofish')
    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/tradingagents/analyze' in rules
    assert '/api/admin/mirofish/tradingagents/runs' in rules
    assert '/api/admin/mirofish/tradingagents/runs/<run_id>' in rules
    assert '/api/admin/mirofish/tradingagents/status' in rules
    assert '/api/admin/mirofish/tradingagents/multi-mcp/architecture' in rules
    assert '/api/admin/mirofish/tradingagents/multi-mcp/analyze' in rules
    assert '/api/admin/mirofish/scanner/tradingagents/history' in rules


def test_analyze_endpoint(admin_client, monkeypatch):
    import app.routes.admin_mirofish_tradingagents as mod
    monkeypatch.setattr(mod.engine, 'run_deep_analysis',
                        lambda target, **kw: {'id': 'ta_x', 'verdict': {'verdict': 'BUY'}})
    resp = admin_client.post('/api/admin/mirofish/tradingagents/analyze', json={'symbol': '005930', 'name': '삼성전자'})
    assert resp.status_code == 200 and resp.get_json()['verdict']['verdict'] == 'BUY'


def test_analyze_requires_target(admin_client):
    assert admin_client.post('/api/admin/mirofish/tradingagents/analyze', json={}).status_code == 400


def test_runs_and_status(admin_client, monkeypatch):
    import app.routes.admin_mirofish_tradingagents as mod
    monkeypatch.setattr(mod.engine, 'list_runs', lambda limit=20: [{'id': 'ta_x'}])
    monkeypatch.setattr(mod.engine, 'get_run', lambda rid: {'id': rid} if rid == 'ta_x' else None)
    monkeypatch.setattr(mod.engine, 'get_status', lambda: {'enabled': True})
    assert admin_client.get('/api/admin/mirofish/tradingagents/runs').get_json()['runs'][0]['id'] == 'ta_x'
    assert admin_client.get('/api/admin/mirofish/tradingagents/runs/ta_x').status_code == 200
    assert admin_client.get('/api/admin/mirofish/tradingagents/runs/nope').status_code == 404
    assert admin_client.get('/api/admin/mirofish/tradingagents/status').get_json()['enabled'] is True


def test_multi_mcp_endpoints(admin_client, monkeypatch):
    import app.routes.admin_mirofish_tradingagents as mod

    monkeypatch.setattr(
        mod.multi_mcp_orchestrator,
        'run_multi_mcp_analysis',
        lambda candidates, **kwargs: {
            'status': 'selective_portfolio',
            'selected': candidates[:1],
        },
    )
    architecture = admin_client.get(
        '/api/admin/mirofish/tradingagents/multi-mcp/architecture'
    )
    result = admin_client.post(
        '/api/admin/mirofish/tradingagents/multi-mcp/analyze',
        json={
            'candidates': [
                {'symbol': '005930', 'name': '삼성전자'},
            ],
            'use_llm': False,
        },
    )

    assert architecture.status_code == 200
    assert architecture.get_json()['numeric_authority'] == (
        'deterministic_mcp_tools_only'
    )
    assert result.status_code == 200
    assert result.get_json()['status'] == 'selective_portfolio'


def test_endpoints_require_auth():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-tradingagents-noauth-secret',
    })
    client = app.test_client()

    assert client.post('/api/admin/mirofish/tradingagents/analyze', json={'symbol': '005930'}).status_code in (401, 403)
    assert client.get('/api/admin/mirofish/tradingagents/runs').status_code in (401, 403)
    assert client.get('/api/admin/mirofish/tradingagents/status').status_code in (401, 403)
    assert client.get(
        '/api/admin/mirofish/tradingagents/multi-mcp/architecture'
    ).status_code in (401, 403)
    assert client.post(
        '/api/admin/mirofish/tradingagents/multi-mcp/analyze',
        json={'candidates': []},
    ).status_code in (401, 403)
    assert client.get('/api/admin/mirofish/scanner/tradingagents/history').status_code in (401, 403)


def test_run_scoped_tradingagents_attaches(monkeypatch, admin_client):
    import app.routes.admin_mirofish_tradingagents as rt
    fake_run = {'id': 'mf_x_005930', 'target': '삼성전자', 'display_name': '삼성전자',
                'symbol': '005930', 'brain_summary': {'regime': 'constructive_bullish',
                                                       'alignment_score': 0.8}}
    monkeypatch.setattr(rt.mirofish_store, 'read_run', lambda rid: fake_run)
    captured = {}

    def fake_deep(target, *, symbol=None, brain=None, **kw):
        captured['brain'] = brain
        return {'id': 'ta_9', 'method': 'rule',
                'verdict': {'verdict': 'BUY', 'confidence': 70, 'strong_buy': False,
                            'regime': 'constructive_bullish',
                            'regime_adjustment': {'direction': 'bull', 'applied': 5.0}}}
    monkeypatch.setattr(rt.engine, 'run_deep_analysis', fake_deep)
    attached = {}
    monkeypatch.setattr(rt.mirofish_store, 'attach_tradingagents',
                        lambda rid, ta: attached.setdefault('ta', ta) or {'verdict': 'BUY'})
    resp = admin_client.post('/api/admin/mirofish/runs/mf_x_005930/tradingagents')
    assert resp.status_code == 200
    assert captured['brain']['regime'] == 'constructive_bullish'
    assert attached['ta']['id'] == 'ta_9'


def test_run_scoped_tradingagents_404(monkeypatch, admin_client):
    import app.routes.admin_mirofish_tradingagents as rt
    monkeypatch.setattr(rt.mirofish_store, 'read_run', lambda rid: None)
    resp = admin_client.post('/api/admin/mirofish/runs/mf_nope/tradingagents')
    assert resp.status_code == 404


def test_scanner_ta_history_endpoint(monkeypatch, admin_client):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'history', lambda limit=50: [{'event_key': 'k1', 'symbol': '005930', 'verdict': 'BUY'}])
    resp = admin_client.get('/api/admin/mirofish/scanner/tradingagents/history?limit=10')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['count'] == 1 and body['records'][0]['symbol'] == '005930'


def test_scanner_ta_history_rejects_invalid_limit(admin_client):
    resp = admin_client.get('/api/admin/mirofish/scanner/tradingagents/history?limit=invalid')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'limit must be an integer'


def test_scanner_ta_history_clamps_limit(monkeypatch, admin_client):
    import app.routes.admin_mirofish_tradingagents as rt
    captured = {}
    monkeypatch.setattr(rt.scanner_deepverify, 'history',
                        lambda limit=50: captured.setdefault('limit', limit) and [])

    resp = admin_client.get('/api/admin/mirofish/scanner/tradingagents/history?limit=999')

    assert resp.status_code == 200
    assert captured['limit'] == 200


# ─── 쿼터/동시상한 — admin 접두 경로가 우회로가 되면 안 된다 (2026-09-02) ──

def _subscriber():
    from types import SimpleNamespace
    return SimpleNamespace(id=77, status='approved', is_admin=False,
                           is_aibain_active=True, is_approved=True,
                           tier='pro', is_pro_expired=False,
                           email='sub@test.local', role='user')


def _subscriber_client(monkeypatch):
    import app.auth.decorators as deco
    monkeypatch.setattr(deco, '_get_current_user', lambda: _subscriber())
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-tradingagents-quota-secret',
    })
    return app.test_client()


def test_subscriber_analyze_consumes_shared_deep_quota(monkeypatch):
    """비관리자 구독자는 /api/kr/decision/*/analyze 와 같은 일일 쿼터를 소모한다."""
    import app.routes.admin_mirofish_tradingagents as mod
    from app.services.mirofish import decision_cache as dc

    monkeypatch.setenv(dc.DEEP_QUOTA_ENV, '1')
    monkeypatch.setattr(mod.engine, 'run_deep_analysis', lambda target, **kw: {'id': 'ta_q'})
    client = _subscriber_client(monkeypatch)

    first = client.post('/api/admin/mirofish/tradingagents/analyze', json={'symbol': '005930'})
    assert first.status_code == 200
    second = client.post('/api/admin/mirofish/tradingagents/analyze', json={'symbol': '005930'})
    assert second.status_code == 429
    assert second.get_json()['error'] == 'quota_exceeded'


def test_subscriber_analyze_busy_when_deep_slots_full(monkeypatch):
    """비관리자 동기 실행은 백그라운드 심층 잡과 동시 상한을 공유한다 — 초과는 429."""
    import app.routes.admin_mirofish_tradingagents as mod
    from app.services.mirofish import decision_cache as dc

    monkeypatch.setenv(dc.DEEP_QUOTA_ENV, '5')
    monkeypatch.setenv('DECISION_JOB_MAX_CONCURRENT', '1')
    monkeypatch.setattr(mod.decision_jobs, 'running_count', lambda: 1)
    monkeypatch.setattr(mod.engine, 'run_deep_analysis', lambda target, **kw: {'id': 'ta_q'})
    client = _subscriber_client(monkeypatch)

    resp = client.post('/api/admin/mirofish/tradingagents/analyze', json={'symbol': '005930'})
    assert resp.status_code == 429
    assert resp.get_json()['error'] == 'busy'
    # busy 는 무료 — 쿼터가 차감되지 않았어야 한다.
    assert dc.consume_deep_quota(77)[0] is True


def test_admin_analyze_is_not_metered(admin_client, monkeypatch):
    """관리자는 종전대로 무제한 — 운영 사용을 깨지 않는다."""
    import app.routes.admin_mirofish_tradingagents as mod
    from app.services.mirofish import decision_cache as dc

    monkeypatch.setenv(dc.DEEP_QUOTA_ENV, '1')
    monkeypatch.setattr(mod.engine, 'run_deep_analysis', lambda target, **kw: {'id': 'ta_x'})
    for _ in range(3):
        resp = admin_client.post('/api/admin/mirofish/tradingagents/analyze',
                                 json={'symbol': '005930'})
        assert resp.status_code == 200
