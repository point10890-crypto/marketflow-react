from __future__ import annotations

from flask import Flask

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.routes.admin_mirofish_analysis import admin_mirofish_analysis_bp


def _rows(count: int) -> list[dict]:
    out = []
    for idx in range(count):
        close = 50000 + idx * 110
        out.append({
            'date': f'2026-02-{(idx % 28) + 1:02d}',
            'open': close - 80,
            'high': close + 150,
            'low': close - 180,
            'close': close,
            'volume': 300000 + idx * 5000,
        })
    return out


def test_k_analyst_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_analysis_bp, url_prefix='/api/admin/mirofish')
    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/tech-engine/analyze' in rules
    assert '/api/admin/mirofish/analysis/readiness' in rules
    assert '/api/admin/mirofish/analysis/bayesian-verdict' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/k-analyst' in rules


def test_tech_engine_endpoint_requires_auth_and_returns_contract():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-k-analyst-secret',
    })
    client = app.test_client()

    no_auth = client.post('/api/admin/mirofish/tech-engine/analyze', json={})
    assert no_auth.status_code in (401, 403)

    with app.app_context():
        admin = User(
            email='k-analyst-admin@test.local',
            name='K Analyst Admin',
            role='admin',
            status='approved',
            tier='premium',
        )
        admin.set_password('test-password-1234')
        db.session.add(admin)
        db.session.commit()
        token = generate_token(admin.id)

    response = client.post(
        '/api/admin/mirofish/tech-engine/analyze',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'target': {'symbol': '005930', 'name': 'Samsung Electronics', 'market': 'KOSPI'},
            'rows': _rows(70),
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    data = response.get_json()
    assert data['service'] == 'mirofish-k-analyst-tech-engine'
    assert data['readiness']['status'] == 'PARTIAL'
    assert data['bayesian_verdict']['probability_total'] == 100


def test_aibain_user_can_use_read_only_k_analyst_endpoint():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-k-analyst-aibain-secret',
    })
    client = app.test_client()

    with app.app_context():
        user = User(
            email='k-analyst-aibain@test.local',
            name='K Analyst AI Brain',
            role='user',
            status='approved',
            tier='pro',
            aibain_enabled=True,
        )
        user.set_password('test-password-1234')
        db.session.add(user)
        db.session.commit()
        token = generate_token(user.id)

    response = client.post(
        '/api/admin/mirofish/analysis/readiness',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'target': {'symbol': '005930', 'name': 'Samsung Electronics', 'market': 'KOSPI'},
            'rows': _rows(70),
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    data = response.get_json()
    assert data['service'] == 'mirofish-k-analyst-readiness'
    assert data['readiness']['status'] == 'PARTIAL'
