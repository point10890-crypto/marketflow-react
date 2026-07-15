import pandas as pd

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
import app.routes.common as common_routes


def _app_and_token():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'common-market-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        user = User(
            email='pro@example.com',
            password_hash='not-used',
            name='Pro User',
            status='approved',
            tier='premium',
        )
        db.session.add(user)
        db.session.commit()
        token = generate_token(user.id)
    return app, token


def test_common_market_endpoints_require_pro_authentication():
    app, _token = _app_and_token()
    client = app.test_client()

    assert client.get('/api/portfolio-summary').status_code == 401
    assert client.get('/api/market-indices').status_code == 401
    assert client.get('/api/stock/AAPL').status_code == 401
    assert client.post('/api/realtime-prices', json={'tickers': ['AAPL']}).status_code == 401


def test_shared_economic_sector_score_mutation_requires_admin():
    app, token = _app_and_token()

    response = app.test_client().post(
        '/api/econ/kr/sectors/score',
        json={'technology': 99},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 403
    assert response.get_json()['error'] == 'Admin access denied'


def test_realtime_prices_rejects_oversized_or_malformed_requests(monkeypatch):
    app, token = _app_and_token()
    client = app.test_client()
    headers = {'Authorization': f'Bearer {token}'}

    def should_not_fetch(*_args, **_kwargs):
        raise AssertionError('invalid requests must not reach yfinance')

    monkeypatch.setattr(common_routes, 'yf_download_safe', should_not_fetch)

    too_many = client.post(
        '/api/realtime-prices',
        json={'tickers': [f'T{i}' for i in range(51)], 'market': 'us'},
        headers=headers,
    )
    assert too_many.status_code == 400
    assert too_many.get_json()['error'] == 'Too many tickers (max 50)'

    not_a_list = client.post(
        '/api/realtime-prices',
        json={'tickers': 'AAPL', 'market': 'us'},
        headers=headers,
    )
    assert not_a_list.status_code == 400

    invalid_symbol = client.post(
        '/api/realtime-prices',
        json={'tickers': ['AAPL;DROP'], 'market': 'us'},
        headers=headers,
    )
    assert invalid_symbol.status_code == 400


def test_realtime_prices_uses_bounded_safe_fetch_and_deduplicates(monkeypatch):
    app, token = _app_and_token()
    calls = []

    def fake_fetch(tickers, timeout, **kwargs):
        calls.append((tickers, timeout, kwargs))
        return pd.DataFrame()

    monkeypatch.setattr(common_routes, 'yf_download_safe', fake_fetch)

    response = app.test_client().post(
        '/api/realtime-prices',
        json={'tickers': ['aapl', 'AAPL', 'MSFT'], 'market': 'us'},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200
    assert response.get_json() == {'prices': {}}
    assert calls == [(['AAPL', 'MSFT'], 8.0, {'period': '1d', 'interval': '1m'})]
