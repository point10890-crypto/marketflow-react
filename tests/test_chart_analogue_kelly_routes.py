"""Member KELLY routes expose saved scans without allowing ranking overrides."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

import app.auth.decorators as auth
import app.routes.admin_mirofish as routes
from app.models import db


KELLY_PATH = '/api/admin/mirofish/chart-analogue/kelly'
REPORT = {'status': 'ready', 'candidates': [{'symbol': '042700', 'target': '한미반도체', 'score': 3.25}]}


def envelope(state='none'):
    return {
        'state': state,
        'processed': 12 if state == 'done' else 0,
        'total': 12 if state in ('running', 'done') else 0,
        'started_at': '2026-10-01T09:30:00Z' if state != 'none' else None,
        'error': 'scan_unavailable' if state == 'error' else None,
        'freshness': 'current' if state == 'done' else 'missing',
        'report': REPORT if state == 'done' else None,
    }


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SECRET_KEY='chart-kelly-route-test',
    )
    db.init_app(app)
    app.register_blueprint(routes.admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    monkeypatch.setattr(auth, '_get_current_user', lambda: SimpleNamespace(
        id=1, email='fixture@example.test', status='approved', is_admin=True, is_aibain_active=False,
    ))
    return app.test_client()


@pytest.fixture
def provider(monkeypatch):
    provider = SimpleNamespace(
        read_status=Mock(return_value=envelope()),
        start_scan=Mock(return_value=envelope('running')),
    )
    monkeypatch.setattr(routes, '_chart_analogue_kelly_store_service', lambda: provider, raising=False)
    return provider


def assert_private(response):
    assert 'private' in response.headers.get('Cache-Control', '')
    assert 'no-store' in response.headers.get('Cache-Control', '')


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('user, expected', [
    (None, 401),
    (SimpleNamespace(id=2, email='fixture@example.test', status='approved', is_admin=False, is_aibain_active=False), 403),
    (SimpleNamespace(id=3, email='fixture@example.test', status='approved', is_admin=False, is_aibain_active=True), 200),
    (SimpleNamespace(id=4, email='fixture@example.test', status='approved', is_admin=True, is_aibain_active=False), 200),
], ids=['unauthenticated', 'no_ai_brain', 'active_ai_brain', 'admin'])
def test_kelly_uses_existing_ai_brain_gate(client, provider, monkeypatch, method, user, expected):
    monkeypatch.setattr(auth, '_get_current_user', lambda: user)
    provider.start_scan.return_value = envelope('done')

    response = client.open(KELLY_PATH, method=method)

    assert response.status_code == expected
    assert_private(response)
    if expected != 200:
        provider.read_status.assert_not_called()
        provider.start_scan.assert_not_called()
    else:
        assert response.json['state'] == ('none' if method == 'GET' else 'done')


@pytest.mark.parametrize('state', ['none', 'running', 'done', 'error'])
def test_get_kelly_returns_saved_status_without_starting_collection(client, provider, state):
    provider.read_status.return_value = envelope(state)

    response = client.get(KELLY_PATH)

    assert response.status_code == 200
    assert response.json == envelope(state)
    provider.read_status.assert_called_once_with()
    provider.start_scan.assert_not_called()
    assert_private(response)


@pytest.mark.parametrize('state, expected', [('running', 202), ('done', 200), ('error', 200)])
@pytest.mark.parametrize('body', [None, {}], ids=['no_body', 'empty_json'])
def test_post_kelly_uses_the_fixed_scan_and_marks_only_running_as_accepted(client, provider, state, expected, body):
    provider.start_scan.return_value = envelope(state)
    kwargs = {} if body is None else {'json': body}

    response = client.post(KELLY_PATH, **kwargs)

    assert response.status_code == expected
    assert response.json == envelope(state)
    provider.start_scan.assert_called_once_with()
    provider.read_status.assert_not_called()
    assert_private(response)


@pytest.mark.parametrize('method, kwargs', [
    ('GET', {'query_string': {'horizon': 20}}),
    ('GET', {'query_string': {'limit': 3}}),
    ('GET', {'query_string': {'options': ''}}),
    ('GET', {'json': {}}),
    ('GET', {'json': {'symbol': '042700'}}),
    ('POST', {'query_string': {'horizon': 20}}),
    ('POST', {'json': {'limit': 3}}),
    ('POST', {'json': {'options': {}}}),
    ('POST', {'json': []}),
    ('POST', {'data': 'null', 'content_type': 'application/json'}),
    ('POST', {'data': 'not-json', 'content_type': 'text/plain'}),
    ('POST', {'data': '{broken', 'content_type': 'application/json'}),
])
def test_kelly_rejects_parameters_before_accessing_service(client, provider, method, kwargs):
    response = client.open(KELLY_PATH, method=method, **kwargs)

    assert response.status_code == 400
    assert response.json == {'error': 'invalid_chart_analogue_kelly_request'}
    provider.read_status.assert_not_called()
    provider.start_scan.assert_not_called()
    assert_private(response)


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('failure', [OSError, ValueError, RuntimeError, KeyError, TypeError])
def test_kelly_service_failures_are_private_generic_503_responses(client, provider, method, failure):
    operation = provider.read_status if method == 'GET' else provider.start_scan
    operation.side_effect = failure('secret-provider-path-or-token')

    response = client.open(KELLY_PATH, method=method)

    assert response.status_code == 503
    assert response.json == {'error': 'chart_analogue_kelly_unavailable'}
    assert 'secret-provider-path-or-token' not in response.get_data(as_text=True)
    assert_private(response)


@pytest.mark.parametrize('method', ['PUT', 'PATCH', 'DELETE'])
def test_kelly_does_not_expose_other_mutation_methods(client, provider, method):
    response = client.open(KELLY_PATH, method=method)

    assert response.status_code == 405
    provider.read_status.assert_not_called()
    provider.start_scan.assert_not_called()
