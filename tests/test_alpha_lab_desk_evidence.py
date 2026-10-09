"""Decision-bound source snapshots cannot rewrite research or enable orders."""
from copy import deepcopy
import importlib
import json

import pytest

from tests.test_alpha_lab_decision_contract import NOW, status, usable_evidence, record


def module():
    return importlib.import_module('app.services.mirofish.alpha_lab.desk_evidence')


def bundle(fixture=None):
    fixture = fixture or status()
    board = fixture['opportunity_engine']
    evidence, states = {}, {}
    for row in board['candidates']:
        records = usable_evidence(row)
        records.append(record(row, 'exchange', role='flow', claim='foreign_flow'))
        for index, item in enumerate(records):
            item.update(evidence_id=f"e{index}", direction='up', figure=1.,
                        unit='observed_score', conflict_group=item['claim_id'], missing_reason=None)
        evidence[row['symbol']] = records
        states[row['symbol']] = dict(symbol=row['symbol'], opportunity_id=row['opportunity_id'],
            decision_id=board['decision_id'], source='KRX:event-feed', source_grade='S',
            source_at='2026-10-08T01:59:00Z', available_at='2026-10-08T01:59:10Z',
            fetched_at='2026-10-08T01:59:20Z', trading_session='CONTINUOUS',
            vi_active=False, sidecar_active=False, circuit_active=False,
            vi_released_at=None, sidecar_released_at=None, circuit_released_at=None)
    return dict(schema_version=1, decision_id=board['decision_id'],
        input_fingerprint=board['input_fingerprint'], source_audit_hash=board['source_audit_hash'],
        policy_hash=module().policy_snapshot()['policy_hash'], evidence=evidence, market_states=states)


def test_saved_sources_reach_current_desk_without_network_or_writes(tmp_path, monkeypatch):
    from app.services.mirofish.alpha_lab import service
    fixture = status(); original = deepcopy(fixture)
    payload = bundle(fixture)
    before = deepcopy(payload)
    receipt = module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    assert payload == before and fixture == original
    files = {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    result = service._with_agent_desk(fixture, now=NOW)
    assert fixture == original
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
    desk = result['agent_desk']
    assert desk['contract']['evidence_status'] == 'ready'
    assert desk['contract']['evidence_snapshot_id'] == receipt['snapshot_id']
    assert all(row['audit']['status'] == 'passed' for row in desk['candidates'])
    assert all(row['status'] == 'passed' for row in desk['contract']['market_checks'])
    assert desk['order_allowed'] is False and desk['promotion']['stage'] == 'M0'


def test_missing_market_facts_hold_account_eligibility_without_removing_stocks(tmp_path, monkeypatch):
    from app.services.mirofish.alpha_lab import service
    fixture = status(); payload = bundle(fixture)
    payload['market_states'] = {}
    module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    desk = service._with_agent_desk(fixture, now=NOW)['agent_desk']
    assert len(desk['candidates']) == 3
    assert all(row['audit']['status'] == 'held' for row in desk['candidates'])
    assert all(row['status'] == 'held' for row in desk['contract']['market_checks'])


def test_market_vi_is_bound_to_one_candidate_and_first_snapshot_is_preserved(tmp_path, monkeypatch):
    from app.services.mirofish.alpha_lab import service
    fixture = status(); payload = bundle(fixture)
    first = module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    original = (tmp_path/'desk-evidence'/'runs'/f"{first['snapshot_id']}.json").read_bytes()
    payload['market_states']['000001'].update(vi_active=True,
        source_at='2026-10-08T01:59:30Z', available_at='2026-10-08T01:59:40Z', fetched_at='2026-10-08T01:59:50Z')
    second = module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    assert first['snapshot_id'] != second['snapshot_id']
    assert (tmp_path/'desk-evidence'/'runs'/f"{first['snapshot_id']}.json").read_bytes() == original
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    desk = service._with_agent_desk(fixture, now=NOW)['agent_desk']
    assert desk['candidates'][0]['audit']['status'] == 'held'
    assert desk['candidates'][1]['audit']['status'] == 'passed'
    assert any('vi' in reason for reason in desk['candidates'][0]['audit']['reasons'])


def test_identical_bundle_is_idempotent_and_does_not_refresh_observation(tmp_path):
    fixture = status(); payload = bundle(fixture)
    first = module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    files = {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
    second = module().publish_bundle(tmp_path, fixture, payload, now='2026-10-08T02:00:10Z')
    assert first['snapshot_id'] == second['snapshot_id']
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}


@pytest.mark.parametrize('remove_all', [True, False])
def test_market_observation_cannot_be_cleared_to_replay_pre_vi_snapshot(tmp_path, remove_all):
    fixture = status(); safe = bundle(fixture)
    module().publish_bundle(tmp_path, fixture, safe, now=NOW)
    active = deepcopy(safe)
    active['market_states']['000001'].update(vi_active=True,
        source_at='2026-10-08T01:59:30Z', available_at='2026-10-08T01:59:40Z', fetched_at='2026-10-08T01:59:50Z')
    receipt = module().publish_bundle(tmp_path, fixture, active, now=NOW)
    omitted = deepcopy(active)
    if remove_all:
        omitted['market_states'] = {}
    else:
        omitted['market_states'].pop('000001')
    with pytest.raises(ValueError, match='desk_market_observation_regression'):
        module().publish_bundle(tmp_path, fixture, omitted, now=NOW)
    with pytest.raises(ValueError, match='desk_market_observation_regression'):
        module().publish_bundle(tmp_path, fixture, safe, now=NOW)
    assert module().read_bundle(tmp_path, fixture['opportunity_engine'])['snapshot_id'] == receipt['snapshot_id']


@pytest.mark.parametrize('event', ['vi', 'sidecar', 'circuit'])
def test_observed_activation_cannot_be_released_without_history(tmp_path, event):
    fixture = status(); payload = bundle(fixture)
    state = payload['market_states']['000001']
    state[event+'_active'] = True
    module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    state.update(source_at='2026-10-08T01:59:30Z', available_at='2026-10-08T01:59:40Z', fetched_at='2026-10-08T01:59:50Z')
    state[event+'_active'] = False
    with pytest.raises(ValueError, match='desk_market_event_history_invalid'):
        module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    state[event+'_released_at'] = '2026-10-08T01:59:20Z'
    module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    state.update(source_at='2026-10-08T01:59:40Z', available_at='2026-10-08T01:59:45Z', fetched_at='2026-10-08T01:59:55Z')
    state[event+'_released_at'] = None
    with pytest.raises(ValueError, match='desk_market_event_history_invalid'):
        module().publish_bundle(tmp_path, fixture, payload, now=NOW)


@pytest.mark.parametrize('event', ['vi', 'sidecar', 'circuit'])
def test_missing_event_flag_cannot_erase_activation_history(tmp_path, event):
    fixture = status(); payload = bundle(fixture)
    state = payload['market_states']['000001']
    state[event+'_active'] = True
    module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    state.update(source_at='2026-10-08T01:59:30Z', available_at='2026-10-08T01:59:40Z', fetched_at='2026-10-08T01:59:50Z')
    state.pop(event+'_active')
    with pytest.raises(ValueError, match='desk_market_event_history_invalid'):
        module().publish_bundle(tmp_path, fixture, payload, now=NOW)


@pytest.mark.parametrize('field', ['decision_id', 'input_fingerprint', 'source_audit_hash', 'policy_hash'])
def test_bundle_cannot_rebind_sources_to_different_identity_or_policy(tmp_path, field):
    fixture = status(); payload = bundle(fixture)
    payload[field] = 'f'*64
    with pytest.raises(ValueError):
        module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    assert not list(tmp_path.rglob('*.json'))


@pytest.mark.parametrize('changes', [
    {'fetched_at': '2026-10-08T01:00:01Z'}, {'figure': float('nan')},
    {'direction': 'buy'}, {'unit': None}, {'symbol': '999999'},
])
def test_invalid_evidence_is_rejected_before_publication(tmp_path, changes):
    fixture = status(); payload = bundle(fixture)
    payload['evidence']['000001'][0].update(changes)
    with pytest.raises(ValueError):
        module().publish_bundle(tmp_path, fixture, payload, now=NOW)
    assert not list(tmp_path.rglob('*.json'))


def test_legacy_claim_without_structured_direction_cannot_be_imported_as_certified(tmp_path):
    fixture = status(); payload = bundle(fixture)
    payload['evidence']['000001'] = usable_evidence(fixture['opportunity_engine']['candidates'][0])
    with pytest.raises(ValueError):
        module().publish_bundle(tmp_path, fixture, payload, now=NOW)


def test_corrupt_snapshot_is_held_and_never_overwritten_on_get(tmp_path, monkeypatch):
    from app.services.mirofish.alpha_lab import service
    fixture = status(); receipt = module().publish_bundle(tmp_path, fixture, bundle(fixture), now=NOW)
    path = tmp_path/'desk-evidence'/'runs'/f"{receipt['snapshot_id']}.json"
    document = json.loads(path.read_text(encoding='utf8'))
    document['body']['evidence']['000001'][0]['figure'] = 999
    path.write_text(json.dumps(document), encoding='utf8')
    original = path.read_bytes()
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    desk = service._with_agent_desk(fixture, now=NOW)['agent_desk']
    assert desk['contract']['evidence_status'] == 'held'
    assert all(row['audit']['status'] == 'held' for row in desk['candidates'])
    assert path.read_bytes() == original


def test_policy_snapshot_cannot_be_mutated_through_a_returned_object():
    first = module().policy_snapshot()
    first['policy']['market']['vi_cooldown_seconds'] = 0
    second = module().policy_snapshot()
    assert second['policy']['market']['vi_cooldown_seconds'] == 300
    assert first['policy_hash'] == second['policy_hash']


def test_absent_snapshot_is_explicit_and_never_loads_other_decision(tmp_path, monkeypatch):
    from app.services.mirofish.alpha_lab import service
    fixture = status(); module().publish_bundle(tmp_path, fixture, bundle(fixture), now=NOW)
    other = status(); other['opportunity_engine']['decision_id'] = 'd'*64
    loaded = module().read_bundle(tmp_path, other['opportunity_engine'])
    assert loaded['status'] == 'missing' and loaded['evidence'] == {}
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    missing = service._with_agent_desk(status(), now=NOW)
    assert missing['agent_desk']['contract']['evidence_status'] == 'ready'
