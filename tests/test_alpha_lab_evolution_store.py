"""Evolution persistence must not reset first decisions or successful stages."""
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.mirofish.alpha_lab import evolution, evolution_store, store

DECLARED = '2026-10-14T10:00:00Z'
DECISION = '2026-10-15T11:31:00Z'


def context(day='2026-10-15', decision=DECISION, marker='a'):
    binding = dict(decision_id=marker*64, input_fingerprint='b'*64, source_audit_hash='c'*64)
    board = dict(binding, generated_at=decision, latest_session=day, candidates=[])
    report = dict(decision_at=decision, latest_session=day, input_fingerprint=binding['input_fingerprint'],
                  opportunity_board=board, opportunity_scan={'audit_hash': binding['source_audit_hash']})
    inputs = dict(latest_session=day, input_fingerprint=binding['input_fingerprint'], names={}, prices_by_symbol={})
    return inputs, report, {'candidates': []}


def fake_engine(monkeypatch, calls, *, failure_at=None):
    summarize_empty = evolution.summarize
    def build(inputs, report, discovery, *, protocol, now):
        calls.append(('build', report['latest_session']))
        body = dict(schema_version=1, protocol_hash=protocol['protocol_hash'], decision_at=report['decision_at'],
                    decision_session=report['latest_session'], latest_session=report['latest_session'],
                    binding={key: report['opportunity_board'][key] for key in ('decision_id', 'input_fingerprint', 'source_audit_hash')},
                    arms=[], observation={'observed_at': None})
        body['cohort_id'] = store._hash(body)
        return body

    def observe(cohort, prices, *, now):
        calls.append(('observe', cohort['decision_session']))
        if cohort['decision_session'] == failure_at:
            raise ValueError('private source details must never be exposed')
        result = deepcopy(cohort)
        result['observation'] = dict(observed_at=now)
        return result

    def summary(protocol, cohorts):
        value = summarize_empty(protocol, [])
        value['binding'] = deepcopy(cohorts[-1]['binding']) if cohorts else None
        return value

    monkeypatch.setattr(evolution, 'build_cohort', build)
    monkeypatch.setattr(evolution, 'observe_cohort', observe)
    monkeypatch.setattr(evolution, 'summarize', summary)


def json_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*.json')}


def test_protocol_declaration_is_immutable_on_restart(tmp_path):
    first = evolution_store.initialize(tmp_path, now=DECLARED)
    before = json_bytes(tmp_path)
    second = evolution_store.initialize(tmp_path, now=DECISION)
    assert first == second
    assert second['declared_at'] == DECLARED
    assert before == json_bytes(tmp_path)


def test_changed_protocol_does_not_overwrite_existing_manifest(tmp_path, monkeypatch):
    evolution_store.initialize(tmp_path, now=DECLARED)
    before = json_bytes(tmp_path)
    original = evolution.protocol_spec()
    monkeypatch.setattr(evolution, 'protocol_spec', lambda: {**original, 'protocol_hash': 'e'*64})
    with pytest.raises(ValueError):
        evolution_store.initialize(tmp_path, now=DECISION)
    assert before == json_bytes(tmp_path)


def test_first_same_day_cohort_survives_reselection_and_get_is_pure(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    evolution_store.initialize(tmp_path, now=DECLARED)
    inputs, report, discovery = context()
    result = evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:32:00Z')
    assert result['status'] == 'ready'
    cohort_path = tmp_path/'evolution'/'cohorts'/'2026-10-15.json'
    first = cohort_path.read_bytes()
    inputs2, report2, discovery2 = context(marker='d')
    evolution_store.refresh(tmp_path, inputs2, report2, discovery2, now='2026-10-15T11:33:00Z')
    assert cohort_path.read_bytes() == first
    assert [row for row in calls if row[0] == 'build'] == [('build', '2026-10-15')]
    before = json_bytes(tmp_path)
    status = evolution_store.read_status(tmp_path, report2['opportunity_board'], now='2026-10-15T11:34:00Z')
    assert status['status'] == 'ready'
    assert 'current_selection_unavailable' in status['reasons']
    assert before == json_bytes(tmp_path)


def test_decision_before_declaration_is_never_backfilled(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    evolution_store.initialize(tmp_path, now=DECLARED)
    inputs, report, discovery = context('2026-10-13', '2026-10-13T11:31:00Z')
    result = evolution_store.refresh(tmp_path, inputs, report, discovery, now=DECLARED)
    assert result['status'] == 'ready'
    assert not list((tmp_path/'evolution'/'cohorts').glob('*.json'))
    assert calls == []


def test_current_identity_mismatch_cannot_show_previous_stocks_or_metrics(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    evolution_store.initialize(tmp_path, now=DECLARED)
    inputs, report, discovery = context()
    evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:32:00Z')
    _, other, _ = context(marker='d')
    before = json_bytes(tmp_path)
    result = evolution_store.read_status(tmp_path, other['opportunity_board'], now='2026-10-15T11:34:00Z')
    assert result['status'] == 'held'
    assert 'current_identity_mismatch' in result['reasons']
    assert all(not arm['selected'] for arm in result['arms'])
    assert before == json_bytes(tmp_path)


def test_corrupt_status_does_not_reset_any_saved_stage(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    evolution_store.initialize(tmp_path, now=DECLARED)
    inputs, report, discovery = context()
    evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:32:00Z')
    path = tmp_path/'evolution'/'status.json'
    path.write_text('{broken', encoding='utf-8')
    before = json_bytes(tmp_path)
    assert evolution_store.read_status(tmp_path, report['opportunity_board'], now='2026-10-15T11:34:00Z') is None
    assert before == json_bytes(tmp_path)


def test_optional_failure_preserves_successful_observation_and_original_files(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    for filename in ('status.json', 'forward.json', 'inputs/current.json'):
        path = tmp_path/filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'original immutable source')
    originals = {name: (tmp_path/name).read_bytes() for name in ('status.json', 'forward.json', 'inputs/current.json')}
    evolution_store.initialize(tmp_path, now=DECLARED)
    first = context()
    evolution_store.refresh(tmp_path, *first, now='2026-10-15T11:32:00Z')
    existing = next((tmp_path/'evolution'/'observations').glob('*.json'))
    completed = existing.read_bytes()
    fake_engine(monkeypatch, calls, failure_at='2026-10-16')
    second = context('2026-10-16', '2026-10-16T11:31:00Z', 'd')
    result = evolution_store.refresh(tmp_path, *second, now='2026-10-16T11:32:00Z')
    assert result['status'] == 'held'
    # The unchanged first stage is reusable, not rebuilt from source.
    assert existing.read_bytes() == completed
    assert all((tmp_path/name).read_bytes() == raw for name, raw in originals.items())


def test_future_or_wrong_source_session_refuses_enrollment(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    evolution_store.initialize(tmp_path, now=DECLARED)
    inputs, report, discovery = context()
    result = evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:30:00Z')
    assert result['status'] == 'held'
    assert calls == []
    inputs['latest_session'] = '2026-10-14'
    result = evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:32:00Z')
    assert result['status'] == 'held'
    assert calls == []


def test_failed_refresh_holds_same_binding_until_success_without_erasing_status(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    evolution_store.initialize(tmp_path, now=DECLARED)
    inputs, report, discovery = context()
    evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:32:00Z')
    original = (tmp_path/'evolution'/'status.json').read_bytes()
    inputs['prices_by_symbol'] = {'005930': []}
    fake_engine(monkeypatch, calls, failure_at='2026-10-15')
    assert evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:33:00Z')['status'] == 'held'
    assert (tmp_path/'evolution'/'status.json').read_bytes() == original
    saved = evolution_store.read_status(tmp_path, report['opportunity_board'], now='2026-10-15T11:34:00Z')
    assert saved['status'] == 'held' and 'last_refresh_failed' in saved['reasons']
    before = json_bytes(tmp_path)
    assert evolution_store.read_status(tmp_path, report['opportunity_board'], now='2026-10-15T11:34:00Z') == saved
    assert before == json_bytes(tmp_path)
    fake_engine(monkeypatch, calls)
    assert evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:35:00Z')['status'] == 'ready'
    assert evolution_store.read_status(tmp_path, report['opportunity_board'], now='2026-10-15T11:36:00Z')['status'] == 'ready'


def test_corrupt_operational_marker_can_recover_without_resetting_sealed_cohort(tmp_path, monkeypatch):
    calls = []
    fake_engine(monkeypatch, calls)
    evolution_store.initialize(tmp_path, now=DECLARED)
    inputs, report, discovery = context()
    evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:32:00Z')
    cohort = (tmp_path/'evolution'/'cohorts'/'2026-10-15.json').read_bytes()
    (tmp_path/'evolution'/'last_attempt.json').write_text('{broken', encoding='utf-8')
    assert evolution_store.read_status(tmp_path, report['opportunity_board'], now='2026-10-15T11:33:00Z') is None
    assert evolution_store.refresh(tmp_path, inputs, report, discovery, now='2026-10-15T11:34:00Z')['status'] == 'ready'
    assert evolution_store.read_status(tmp_path, report['opportunity_board'], now='2026-10-15T11:35:00Z')['status'] == 'ready'
    assert (tmp_path/'evolution'/'cohorts'/'2026-10-15.json').read_bytes() == cohort


def test_nomination_receipt_is_bound_to_protocol_and_ordered_first_cohorts():
    protocol = dict(evolution.protocol_spec(), protocol_id='a'*64)
    cohorts = [{'cohort_id': f'{index:064x}'} for index in range(36)]
    nomination = dict(status='fixed', arm_id='entry-band-v1', session_count=36,
                      reason='fixed_nomination_paired_stress_mean')
    receipt = evolution_store._nomination_receipt(protocol, cohorts, nomination)
    assert evolution_store._bound_nomination(receipt, protocol, cohorts) == nomination
    with pytest.raises(ValueError):
        evolution_store._bound_nomination(receipt, {**protocol, 'protocol_id': 'b'*64}, cohorts)
    with pytest.raises(ValueError):
        evolution_store._bound_nomination(receipt, protocol, cohorts[::-1])
    with pytest.raises(ValueError):
        evolution_store._bound_nomination(receipt, protocol, cohorts[:35])
