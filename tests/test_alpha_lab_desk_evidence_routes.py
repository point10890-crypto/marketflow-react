"""Evidence writes are admin-only and cannot be supplied via member actions."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.auth.decorators as auth
from tests.test_alpha_lab_routes import client, provider, assert_private

PATH = '/api/admin/mirofish/alpha-lab/evidence'


def payload():
    return dict(schema_version=1, decision_id='a'*64, input_fingerprint='b'*64,
        source_audit_hash='c'*64, policy_hash='d'*64, evidence={}, market_states={})


@pytest.mark.parametrize('user,expected', [
    (None, 401),
    (SimpleNamespace(id=2, status='approved', is_admin=False, is_aibain_active=True), 403),
    (SimpleNamespace(id=3, status='approved', is_admin=False, is_aibain_active=False), 403),
])
def test_only_admin_can_publish_evidence(client, provider, monkeypatch, user, expected):
    provider.save_desk_evidence = Mock()
    monkeypatch.setattr(auth, '_get_current_user', lambda: user)
    response = client.post(PATH, json=payload())
    assert response.status_code == expected
    assert_private(response)
    provider.save_desk_evidence.assert_not_called()


def test_admin_publication_returns_bounded_receipt_without_starting_scan(client, provider):
    receipt = dict(schema_version=1, status='stored', decision_id='a'*64,
        snapshot_id='e'*64, policy_hash='d'*64, evidence_records=5)
    provider.save_desk_evidence = Mock(return_value=receipt)
    response = client.post(PATH, json=payload())
    assert response.status_code == 200 and response.json == receipt
    assert_private(response)
    provider.save_desk_evidence.assert_called_once_with(payload())
    provider.start_scan.assert_not_called()


@pytest.mark.parametrize('kwargs', [
    {'json': {}}, {'json': []}, {'json': {**payload(), 'account': {}}},
    {'json': payload(), 'query_string': {'force': '1'}},
    {'data': '{broken', 'content_type': 'application/json'},
    {'data': '{"schema_version":1,"schema_version":2}', 'content_type': 'application/json'},
    {'data': '{"evidence":NaN}', 'content_type': 'application/json'},
    {'data': 'x'*262145, 'content_type': 'application/json'},
])
def test_invalid_body_cannot_reach_saved_service(client, provider, kwargs):
    provider.save_desk_evidence = Mock()
    response = client.post(PATH, **kwargs)
    assert response.status_code == 400
    assert response.json == {'error': 'invalid_desk_evidence_request'}
    assert_private(response)
    provider.save_desk_evidence.assert_not_called()


@pytest.mark.parametrize('exc,code', [(ValueError, 409), (OSError, 503), (RuntimeError, 503)])
def test_service_failure_is_bounded_and_does_not_leak_evidence(client, provider, exc, code):
    provider.save_desk_evidence = Mock(side_effect=exc('sensitive-source-path'))
    response = client.post(PATH, json=payload())
    assert response.status_code == code
    assert 'sensitive' not in response.get_data(as_text=True)
    assert_private(response)


@pytest.mark.parametrize('method', ['GET', 'PUT', 'PATCH', 'DELETE'])
def test_evidence_route_has_no_member_read_or_alternative_mutation(client, provider, method):
    assert client.open(PATH, method=method).status_code == 405
