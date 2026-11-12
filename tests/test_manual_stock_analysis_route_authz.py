"""manual-stock-analysis: 변경 라우트는 관리자만, 조회 라우트는 Pro 유지."""
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
import app.routes.manual_stock_analysis as routes

MUTATING = [
    '/api/manual-stock-analysis/runs/source',
    '/api/manual-stock-analysis/runs/scrape',
    '/api/manual-stock-analysis/scraper-loop/start',
    '/api/manual-stock-analysis/scraper-loop/stop',
    '/api/manual-stock-analysis/runs/upload',
]


@pytest.fixture
def ctx(monkeypatch):
    fake_run = {'id': 'run-1', 'records': []}
    monkeypatch.setattr(routes.service, 'create_pending_run_from_source', lambda **k: dict(fake_run))
    monkeypatch.setattr(routes.service, 'scrape_source_run', lambda **k: dict(fake_run))
    monkeypatch.setattr(routes.service, 'start_scraper_loop', lambda **k: {'running': True})
    monkeypatch.setattr(routes.service, 'stop_scraper_loop', lambda: {'running': False})
    monkeypatch.setattr(routes.service, 'save_uploaded_result', lambda f: dict(fake_run))
    monkeypatch.setattr(routes.service, 'list_runs', lambda: [])

    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'manual-authz-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=20)
        pro = User(email='pro@example.com', name='구독자', status='approved', tier='pro',
                   role='user', pro_expires_at=expiry)
        pro.set_password('Pass1234!')
        admin = User(email='admin@example.com', name='관리자', status='approved', role='admin')
        admin.set_password('Pass1234!')
        db.session.add_all([pro, admin])
        db.session.commit()
        headers = {
            'pro': {'Authorization': f'Bearer {generate_token(pro.id)}'},
            'admin': {'Authorization': f'Bearer {generate_token(admin.id)}'},
        }
    return app.test_client(), headers


@pytest.mark.parametrize('path', MUTATING)
def test_mutating_routes_require_auth(ctx, path):
    client, _ = ctx
    assert client.post(path, json={}).status_code == 401


@pytest.mark.parametrize('path', MUTATING)
def test_mutating_routes_reject_pro_subscriber(ctx, path):
    client, headers = ctx
    res = client.post(path, json={}, headers=headers['pro'])
    assert res.status_code == 403
    assert res.get_json()['error'] == 'Admin access denied'


@pytest.mark.parametrize('path', MUTATING[:4])
def test_mutating_routes_allow_admin(ctx, path):
    client, headers = ctx
    assert client.post(path, json={}, headers=headers['admin']).status_code == 200


def test_upload_reaches_handler_for_admin(ctx):
    client, headers = ctx
    # 파일 없이 보내면 핸들러의 400 검증에 도달한다 = 인가를 통과했다.
    res = client.post('/api/manual-stock-analysis/runs/upload', headers=headers['admin'])
    assert res.status_code == 400


def test_read_routes_still_open_to_pro(ctx):
    client, headers = ctx
    assert client.get('/api/manual-stock-analysis/runs', headers=headers['pro']).status_code == 200
