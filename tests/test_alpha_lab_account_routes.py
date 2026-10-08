"""The member risk calculator uses only current saved decisions, with no account writes."""
from types import SimpleNamespace

import pytest

import app.auth.decorators as auth
from tests.test_alpha_lab_routes import client, provider, assert_private

PATH = '/api/admin/mirofish/alpha-lab/account-plan'


def request_body():
    return {'opportunity_ids': ['decision-1'], 'account': {
        'equity': 1000000, 'available_cash': 1000000, 'daily_pnl': 0,
        'weekly_pnl': 0, 'positions_confirmed': True, 'positions': [],
    }}


@pytest.mark.parametrize('user,expected', [
    (None, 401),
    (SimpleNamespace(id=2, status='approved', is_admin=False, is_aibain_active=False), 403),
])
def test_account_plan_requires_existing_member_gate(client, provider, monkeypatch, user, expected):
    monkeypatch.setattr(auth, '_get_current_user', lambda: user)
    response = client.post(PATH, json=request_body())
    assert response.status_code == expected
    assert_private(response)
    provider.read_status.assert_not_called()


@pytest.mark.parametrize('kwargs', [
    {'json': {}}, {'json': []}, {'json': {**request_body(), 'price': 123}},
    {'json': {**request_body(), 'opportunity_ids': ['same', 'same']}},
    {'json': {**request_body(), 'opportunity_ids': ['x'] * 4}},
    {'json': {**request_body(), 'account': None}},
    {'json': {**request_body(), 'account': {**request_body()['account'], 'equity': True}}},
    {'json': {**request_body(), 'account': {**request_body()['account'], 'daily_pnl': None}}},
    {'json': {**request_body(), 'account': {**request_body()['account'], 'positions_confirmed': False}}},
    {'json': request_body(), 'query_string': {'symbol': '042700'}},
    {'data': '{broken', 'content_type': 'application/json'},
    {'data': 'x' * 16385, 'content_type': 'application/json'},
])
def test_rejects_body_overrides_before_reading_saved_report(client, provider, kwargs):
    response = client.post(PATH, **kwargs)
    assert response.status_code == 400
    assert response.json == {'error': 'invalid_account_plan_request'}
    assert_private(response)
    provider.read_status.assert_not_called()
    provider.start_scan.assert_not_called()


def test_stale_display_ids_cannot_choose_other_prices(client, provider):
    provider.read_status.return_value = {'state': 'ready', 'opportunity_engine': {
        'candidates': [{'opportunity_id': 'new-decision'}]}, 'agent_desk': {'candidates': []}}
    response = client.post(PATH, json=request_body())
    assert response.status_code == 409
    assert response.json == {'error': 'account_plan_identity_changed'}
    assert_private(response)
    provider.start_scan.assert_not_called()


def test_missing_saved_report_is_unavailable_without_refitting(client, provider):
    provider.read_status.return_value = {'state': 'missing', 'report': None}
    response = client.post(PATH, json=request_body())
    assert response.status_code == 503
    assert response.json == {'error': 'account_plan_unavailable'}
    provider.start_scan.assert_not_called()


@pytest.mark.parametrize('failure', [OSError, ValueError, RuntimeError, TypeError])
def test_saved_provider_failure_cannot_leak_account_or_paths(client, provider, failure):
    provider.read_status.side_effect = failure('private-secret-account-path')
    response = client.post(PATH, json=request_body())
    assert response.status_code == 503
    assert response.json == {'error': 'account_plan_unavailable'}
    assert_private(response)
    assert 'private-secret' not in response.get_data(as_text=True)


def test_duplicate_account_properties_are_not_silently_overwritten(client, provider):
    body = ('{"opportunity_ids":["decision-1"],"account":{"equity":1000000,"equity":9999999,'
            '"available_cash":1000000,"daily_pnl":0,"weekly_pnl":0,"positions_confirmed":true,"positions":[]}}')
    assert client.post(PATH, data=body, content_type='application/json').status_code == 400
    provider.read_status.assert_not_called()


def test_existing_ai_brain_member_can_access_saved_calculator(client, provider, monkeypatch):
    monkeypatch.setattr(auth, '_get_current_user', lambda: SimpleNamespace(
        id=3, email='fixture@example.test', status='approved', is_admin=False, is_aibain_active=True))
    response = client.post(PATH, json=request_body())
    assert response.status_code == 503  # Missing fixture data, not a denied membership.
    provider.read_status.assert_called_once_with()


@pytest.mark.parametrize('method', ['GET', 'PUT', 'PATCH', 'DELETE'])
def test_account_calculator_does_not_allow_other_methods(client, provider, method):
    assert client.open(PATH, method=method).status_code == 405
    provider.read_status.assert_not_called()
