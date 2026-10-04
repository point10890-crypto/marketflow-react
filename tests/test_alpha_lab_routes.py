"""Member AlphaLab routes expose saved scans without allowing ranking overrides."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

import app.auth.decorators as auth
import app.routes.admin_mirofish as routes
from app.models import db


ALPHA_LAB_PATH = '/api/admin/mirofish/alpha-lab'
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
    monkeypatch.setattr(routes, '_alpha_lab_service', lambda: provider, raising=False)
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
def test_alpha_lab_uses_existing_ai_brain_gate(client, provider, monkeypatch, method, user, expected):
    monkeypatch.setattr(auth, '_get_current_user', lambda: user)
    provider.start_scan.return_value = envelope('done')

    response = client.open(ALPHA_LAB_PATH, method=method)

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

    response = client.get(ALPHA_LAB_PATH)

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

    response = client.post(ALPHA_LAB_PATH, **kwargs)

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
def test_alpha_lab_rejects_parameters_before_accessing_service(client, provider, method, kwargs):
    response = client.open(ALPHA_LAB_PATH, method=method, **kwargs)

    assert response.status_code == 400
    assert response.json == {'error': 'invalid_alpha_lab_request'}
    provider.read_status.assert_not_called()
    provider.start_scan.assert_not_called()
    assert_private(response)


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('failure', [OSError, ValueError, RuntimeError, KeyError, TypeError])
def test_alpha_lab_service_failures_are_private_generic_503_responses(client, provider, method, failure):
    operation = provider.read_status if method == 'GET' else provider.start_scan
    operation.side_effect = failure('secret-provider-path-or-token')

    response = client.open(ALPHA_LAB_PATH, method=method)

    assert response.status_code == 503
    assert response.json == {'error': 'alpha_lab_unavailable'}
    assert 'secret-provider-path-or-token' not in response.get_data(as_text=True)
    assert_private(response)


@pytest.mark.parametrize('method', ['PUT', 'PATCH', 'DELETE'])
def test_alpha_lab_does_not_expose_other_mutation_methods(client, provider, method):
    response = client.open(ALPHA_LAB_PATH, method=method)

    assert response.status_code == 405
    provider.read_status.assert_not_called()
    provider.start_scan.assert_not_called()


def full_research_status(state='held'):
    return dict(schema_version=1, state=state, error=None, report=dict(schema_version=1, mode='research',
        champion=dict(strategy_id=None), candidates=[dict(symbol='042700', name='한미반도체', strategy_id='momentum')],
        strategies=[dict(strategy_id='momentum', test=dict(net_total_return=-.1))],
        approval=dict(status='held', approved_exposure=0., live_orders=False)))


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_routes_add_manual_opinions_without_mutating_retained_report(client, provider, method):
    from copy import deepcopy
    saved = full_research_status(); original = deepcopy(saved)
    operation = provider.read_status if method == 'GET' else provider.start_scan
    operation.return_value = saved
    response = client.open(ALPHA_LAB_PATH, method=method)
    assert response.status_code == 200
    proposal = response.json['report']['candidates'][0]['proposal']
    assert proposal['action'] == 'avoid'
    assert proposal['order_allowed'] is False
    assert response.json['report']['proposal_summary']['avoid_count'] == 1
    assert response.json['report']['approval'] == original['report']['approval']
    assert saved == original
    assert_private(response)


@pytest.mark.parametrize('method, state, code', [('GET', 'failed', 200), ('GET', 'running', 200), ('POST', 'running', 202)])
def test_routes_never_reuse_retained_buy_when_scan_running_or_failed(client, provider, method, state, code):
    saved = full_research_status(state)
    saved['report']['candidates'][0]['proposal'] = dict(action='buy')
    operation = provider.read_status if method == 'GET' else provider.start_scan
    operation.return_value = saved
    response = client.open(ALPHA_LAB_PATH, method=method)
    assert response.status_code == code
    assert response.json['report']['candidates'][0]['proposal']['action'] == 'wait'
    assert response.json['report']['candidates'][0]['proposal']['proposed_weight'] == 0.


def test_repeated_get_never_changes_the_forward_journal(client, provider, monkeypatch, tmp_path):
    from app.services.mirofish.alpha_lab import store
    journal = tmp_path/'forward.json'; journal.write_text('{"immutable":"decision"}')
    before = journal.read_bytes()
    def forbidden(*_args, **_kwargs): raise AssertionError('GET must not write or observe future outcomes')
    monkeypatch.setattr(store, '_write', forbidden)
    monkeypatch.setattr(store, 'observe_and_freeze', forbidden)
    provider.read_status.return_value = full_research_status()
    for _ in range(2):
        response = client.get(ALPHA_LAB_PATH)
        assert response.status_code == 200
        assert response.json['report']['candidates'][0]['proposal']['action'] == 'avoid'
    assert journal.read_bytes() == before
    assert provider.read_status.call_count == 2
    provider.start_scan.assert_not_called()
