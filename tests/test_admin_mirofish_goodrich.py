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
    assert result['integration']['universe_size'] == 3
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


def test_goodrich_history_and_performance_clients_forward_bounded_queries(monkeypatch):
    urls = []

    class RawResponse:
        status_code = 200

        def json(self):
            return {'items': []} if '/history?' in urls[-1] else {'window_days': 365}

    def fake_request(method, url, **kwargs):
        urls.append(url)
        return RawResponse()

    monkeypatch.setattr(goodrich_client.requests, 'request', fake_request)

    assert goodrich_client.get_detection_history(limit=999, offset=-2) == {'items': []}
    assert goodrich_client.get_performance(window_days=999) == {'window_days': 365}
    assert urls[0].endswith('/v1/fund-manager/history?limit=100&offset=0')
    assert urls[1].endswith('/v1/fund-manager/performance?window_days=365')


def test_goodrich_client_maps_timeout_without_upstream_details(monkeypatch):
    monkeypatch.setattr(
        'app.services.kis_screener.run_screening',
        lambda force=True: {
            'results': [
                {'code': '005930', 'name': '삼성전자', 'change_pct': 2.1, 'score': {'total': 70}},
                {'code': '000660', 'name': 'SK하이닉스', 'change_pct': 1.8, 'score': {'total': 68}},
                {'code': '035420', 'name': 'NAVER', 'change_pct': 1.2, 'score': {'total': 63}},
            ],
        },
    )
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


def test_goodrich_research_keeps_relative_leaders_and_excludes_crashers(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        'app.services.kis_screener.run_screening',
        lambda force=True: {
            'timestamp': '2026-07-28T15:30:00+09:00',
            'market_status': 'closed',
            'results': [
                {'code': '413630', 'name': '씨피시스템', 'change_pct': 3.32, 'score': {'total': 73}},
                {'code': '068270', 'name': '셀트리온', 'change_pct': -0.73, 'score': {'total': 51}},
                {'code': '207940', 'name': '삼성바이오로직스', 'change_pct': 0.26, 'score': {'total': 48}},
                {'code': '000660', 'name': 'SK하이닉스', 'change_pct': -14.65, 'score': {'total': 51}},
                {'code': '005935', 'name': '삼성전자우', 'change_pct': -1.0, 'score': {'total': 60}},
            ],
        },
    )

    def fake_request(method, url, **kwargs):
        captured['json'] = kwargs['json']
        return FakeResponse()

    monkeypatch.setattr(goodrich_client.requests, 'request', fake_request)
    result = goodrich_client.run_research()

    assert [row['symbol'] for row in captured['json']['candidates']] == [
        '413630', '068270', '207940',
    ]
    assert result['integration']['universe_size'] == 3
    assert result['integration']['market_status'] == 'closed'


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
    assert client.get('/api/admin/mirofish/goodrich/fund-manager/history').status_code == 401
    assert client.get('/api/admin/mirofish/goodrich/fund-manager/performance').status_code == 401


def test_goodrich_routes_forward_safe_payload(admin_client, monkeypatch):
    import app.routes.admin_mirofish_goodrich as route

    snapshot = {'picks': [{'symbol': '005930', 'name': '삼성전자'}]}
    monkeypatch.setattr(route.goodrich_client, 'get_fund_manager', lambda: snapshot)
    monkeypatch.setattr(route.goodrich_client, 'run_research', lambda: snapshot)
    monkeypatch.setattr(
        route.goodrich_client,
        'get_detection_history',
        lambda limit, offset: {'items': [], 'limit': limit, 'offset': offset},
    )
    monkeypatch.setattr(
        route.goodrich_client,
        'get_performance',
        lambda window_days: {'window_days': window_days, 'total_picks': 0},
    )

    assert admin_client.get('/api/admin/mirofish/goodrich/fund-manager').get_json() == snapshot
    assert admin_client.post('/api/admin/mirofish/goodrich/fund-manager/research').get_json() == snapshot
    assert admin_client.get(
        '/api/admin/mirofish/goodrich/fund-manager/history?limit=7&offset=2'
    ).get_json() == {'items': [], 'limit': 7, 'offset': 2}
    assert admin_client.get(
        '/api/admin/mirofish/goodrich/fund-manager/performance?window_days=90'
    ).get_json() == {'window_days': 90, 'total_picks': 0}


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
