import requests
import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.services.mirofish import goodrich_client


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            'status': 'monitoring',
            'picks': [
                {'rank': 1, 'symbol': '005930', 'name': '삼성전자'},
                {'rank': 2, 'symbol': '000660', 'name': 'SK하이닉스'},
                {'rank': 3, 'symbol': '035420', 'name': 'NAVER'},
            ],
        }


def test_goodrich_client_adds_safe_integration_metadata(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return FakeResponse()

    monkeypatch.setattr(goodrich_client.requests, 'request', fake_request)
    result = goodrich_client.get_fund_manager()

    assert captured['method'] == 'GET'
    assert captured['url'].endswith('/v1/fund-manager')
    assert result['integration']['universe_size'] == 6
    assert result['integration']['ordering_enabled'] is False
    assert [pick['symbol'] for pick in result['picks']] == ['005930', '000660', '035420']


def test_goodrich_client_rejects_missing_pick_identity(monkeypatch):
    class BadResponse(FakeResponse):
        def json(self):
            return {'picks': [{'symbol': '', 'name': '누락'}]}

    monkeypatch.setattr(goodrich_client.requests, 'request', lambda *args, **kwargs: BadResponse())

    try:
        goodrich_client.get_fund_manager()
    except goodrich_client.GoodrichServiceError as exc:
        assert '식별 정보' in str(exc)
    else:
        raise AssertionError('invalid payload must be rejected')


def test_goodrich_client_maps_timeout_without_upstream_details(monkeypatch):
    monkeypatch.setattr(
        goodrich_client.requests,
        'request',
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout('secret upstream detail')),
    )

    try:
        goodrich_client.run_research()
    except goodrich_client.GoodrichServiceError as exc:
        assert exc.status_code == 504
        assert 'secret' not in str(exc)
    else:
        raise AssertionError('timeout must become a safe service error')


@pytest.fixture
def admin_client():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-goodrich-secret',
    })
    client = app.test_client()
    with app.app_context():
        admin = User(
            email='goodrich-admin@test.local',
            name='Goodrich Admin',
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


def test_goodrich_routes_require_auth():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-goodrich-noauth-secret',
    })
    client = app.test_client()

    assert client.get('/api/admin/mirofish/goodrich/fund-manager').status_code == 401
    assert client.post('/api/admin/mirofish/goodrich/fund-manager/research').status_code == 401


def test_goodrich_routes_forward_safe_payload(admin_client, monkeypatch):
    import app.routes.admin_mirofish_goodrich as route

    snapshot = {'picks': [{'symbol': '005930', 'name': '삼성전자'}]}
    monkeypatch.setattr(route.goodrich_client, 'get_fund_manager', lambda: snapshot)
    monkeypatch.setattr(route.goodrich_client, 'run_research', lambda: snapshot)

    assert admin_client.get('/api/admin/mirofish/goodrich/fund-manager').get_json() == snapshot
    assert admin_client.post('/api/admin/mirofish/goodrich/fund-manager/research').get_json() == snapshot


def test_goodrich_route_maps_upstream_failure(admin_client, monkeypatch):
    import app.routes.admin_mirofish_goodrich as route

    def fail():
        raise route.goodrich_client.GoodrichServiceError('연결 실패', status_code=503)

    monkeypatch.setattr(route.goodrich_client, 'get_fund_manager', fail)
    response = admin_client.get('/api/admin/mirofish/goodrich/fund-manager')

    assert response.status_code == 503
    assert response.get_json() == {
        'error': '연결 실패',
        'service': 'goodrich-tradingos',
        'upstream_available': False,
    }
