"""Current market entry facts fail closed without changing the source decision."""
from copy import deepcopy
from datetime import datetime

import pytest


NOW = '2026-10-09T01:00:00Z'  # Friday 10:00 KST.
POLICY = dict(max_market_age_seconds=420, vi_cooldown_seconds=300,
    systemic_cooldown_seconds=900, session_start='09:00', plan_cutoff='15:05')


def row(symbol='005930'):
    return dict(symbol=symbol, opportunity_id='opportunity-'+symbol,
        decision_id='decision-original', source_at='2026-10-08T01:00:00Z')


def state(**changes):
    result = dict(symbol='005930', opportunity_id='opportunity-005930',
        decision_id='decision-original', source='KIS:market-state', source_grade='A',
        source_at=NOW, available_at=NOW, fetched_at=NOW, trading_session='CONTINUOUS',
        vi_active=False, vi_released_at=None, sidecar_active=False,
        sidecar_released_at=None, circuit_active=False, circuit_released_at=None)
    result.update(changes)
    return result


def evaluate(current=None, *, now=NOW, policy=POLICY, candidate=None):
    from app.services.mirofish.alpha_lab.desk_market_guard import evaluate_market_guard
    return evaluate_market_guard(row() if candidate is None else candidate,
        state() if current is None else current, now=now, policy=policy)


def test_fresh_explicit_current_market_facts_pass_without_rewriting_old_alpha():
    candidate, current = row(), state()
    before = deepcopy((candidate, current))
    actual = evaluate(current, candidate=candidate)
    assert actual == dict(status='passed', reasons=[], valid_until='2026-10-09T01:07:00Z')
    assert (candidate, current) == before


@pytest.mark.parametrize('field,value', [
    ('symbol', '000660'), ('opportunity_id', 'another-opportunity'),
    ('decision_id', 'another-decision'), ('symbol', None),
    ('opportunity_id', ''), ('decision_id', True),
])
def test_market_facts_must_bind_all_three_candidate_identity_fields(field, value):
    actual = evaluate(state(**{field: value}))
    assert actual['status'] == 'held'
    assert 'market_identity_mismatch' in actual['reasons']
    assert actual['valid_until'] is None


@pytest.mark.parametrize('field', ['symbol', 'opportunity_id', 'decision_id'])
def test_missing_candidate_identity_does_not_pass_matching_missing_market_fields(field):
    candidate, current = row(), state()
    candidate.pop(field)
    current.pop(field)
    assert evaluate(current, candidate=candidate)['status'] == 'held'


@pytest.mark.parametrize('grade', [None, 'B', 'C', 'D', True, [], float('nan')])
def test_market_state_requires_explicit_trusted_source_grade(grade):
    actual = evaluate(state(source_grade=grade))
    assert actual['status'] == 'held'
    assert 'market_source_grade_invalid' in actual['reasons']


@pytest.mark.parametrize('source', [None, '', '   ', True, [], float('nan')])
def test_market_state_requires_an_explicit_source(source):
    actual = evaluate(state(source=source))
    assert actual['status'] == 'held'
    assert 'market_source_missing' in actual['reasons']


@pytest.mark.parametrize('field', ['source_at', 'available_at', 'fetched_at'])
@pytest.mark.parametrize('bad', [None, 'bad', '2026-10-09T01:00:00', True, float('nan'), []])
def test_missing_malformed_or_naive_market_timestamps_hold(field, bad):
    actual = evaluate(state(**{field: bad}))
    assert actual['status'] == 'held'
    assert 'market_timestamp_invalid' in actual['reasons']


@pytest.mark.parametrize('changes,reason', [
    ({'source_at': '2026-10-09T01:00:01Z'}, 'market_time_order_invalid'),
    ({'available_at': '2026-10-09T00:59:59Z'}, 'market_time_order_invalid'),
    ({'fetched_at': '2026-10-09T00:59:59Z'}, 'market_time_order_invalid'),
    ({'fetched_at': '2026-10-09T01:00:01Z'}, 'market_timestamp_future'),
])
def test_market_timestamp_order_and_future_capture_are_rejected(changes, reason):
    actual = evaluate(state(**changes))
    assert actual['status'] == 'held'
    assert reason in actual['reasons']


@pytest.mark.parametrize('capture,want', [
    ('2026-10-09T00:53:00.001Z', 'passed'),
    ('2026-10-09T00:53:00Z', 'held'),
    ('2026-10-09T00:52:59Z', 'held'),
])
def test_market_freshness_uses_fact_capture_and_expires_at_max_age_endpoint(capture, want):
    actual = evaluate(state(source_at=capture, available_at=NOW, fetched_at=NOW))
    assert actual['status'] == want
    if want == 'held':
        assert 'market_state_stale' in actual['reasons']
    else:
        assert actual['valid_until'] == '2026-10-09T01:00:00.001000Z'


@pytest.mark.parametrize('current', [None, True, [], float('nan')])
def test_invalid_market_state_shapes_hold(current):
    from app.services.mirofish.alpha_lab.desk_market_guard import evaluate_market_guard
    assert evaluate_market_guard(row(), current, now=NOW, policy=POLICY)['status'] == 'held'


@pytest.mark.parametrize('now', [None, 'bad', '2026-10-09T01:00:00', True, float('nan')])
def test_invalid_evaluation_timestamp_holds(now):
    actual = evaluate(now=now)
    assert actual['status'] == 'held'
    assert 'market_now_invalid' in actual['reasons']


@pytest.mark.parametrize('session', [None, '', 'AFTERHOURS', 'CLOSE_AUCTION', 'HOLIDAY', True, []])
def test_supplied_noncontinuous_or_unknown_session_cannot_be_inferred_from_weekday(session):
    assert evaluate(state(trading_session=session))['status'] == 'held'


def test_missing_session_is_held():
    current = state()
    current.pop('trading_session')
    assert evaluate(current)['status'] == 'held'


@pytest.mark.parametrize('now,want', [
    ('2026-10-08T23:59:59Z', 'held'),  # Friday 08:59:59 KST.
    ('2026-10-09T00:00:00Z', 'passed'),
    ('2026-10-09T06:04:59Z', 'passed'),
    ('2026-10-09T06:05:00Z', 'held'),
    ('2026-10-09T15:00:00Z', 'held'),  # Saturday 00:00 KST.
    ('2026-10-10T01:00:00Z', 'held'),
])
def test_plan_session_uses_kst_boundaries_and_weekday(now, want):
    actual = evaluate(state(source_at=now, available_at=now, fetched_at=now), now=now)
    assert actual['status'] == want


def test_offset_equivalent_kst_and_utc_inputs_have_identical_results():
    local = '2026-10-09T10:00:00+09:00'
    assert evaluate(state(source_at=local, available_at=local, fetched_at=local), now=local) == evaluate()
    assert evaluate(now=datetime.fromisoformat(local)) == evaluate()


def test_passed_validity_ends_at_plan_cutoff_even_when_snapshot_is_fresh():
    now = '2026-10-09T06:04:00Z'
    actual = evaluate(state(source_at=now, available_at=now, fetched_at=now), now=now)
    assert actual['valid_until'] == '2026-10-09T06:05:00Z'


@pytest.mark.parametrize('event', ['vi', 'sidecar', 'circuit'])
@pytest.mark.parametrize('flag', [None, 0, 1, 'false', float('nan'), []])
def test_market_event_flags_are_strict_explicit_booleans(event, flag):
    actual = evaluate(state(**{event+'_active': flag}))
    assert actual['status'] == 'held'
    assert 'market_'+event+'_flag_invalid' in actual['reasons']


@pytest.mark.parametrize('event', ['vi', 'sidecar', 'circuit'])
def test_missing_market_event_flag_is_held(event):
    current = state()
    current.pop(event+'_active')
    assert evaluate(current)['status'] == 'held'


@pytest.mark.parametrize('event', ['vi', 'sidecar', 'circuit'])
def test_inactive_event_requires_explicit_release_or_never_active_null(event):
    current = state()
    current.pop(event+'_released_at')
    actual = evaluate(current)
    assert actual['status'] == 'held'
    assert 'market_'+event+'_release_missing' in actual['reasons']


@pytest.mark.parametrize('event', ['vi', 'sidecar', 'circuit'])
def test_active_event_holds_entry(event):
    actual = evaluate(state(**{event+'_active': True}))
    assert actual['status'] == 'held'
    assert 'market_'+event+'_active' in actual['reasons']


@pytest.mark.parametrize('event,released,held_until', [
    ('vi', '2026-10-09T00:55:01Z', '2026-10-09T01:00:01Z'),
    ('sidecar', '2026-10-09T00:45:01Z', '2026-10-09T01:00:01Z'),
    ('circuit', '2026-10-09T00:45:01Z', '2026-10-09T01:00:01Z'),
])
def test_event_cooldown_holds_until_exact_release_plus_wait_endpoint(event, released, held_until):
    assert evaluate(state(**{event+'_released_at': released}))['status'] == 'held'
    current = state(source_at=held_until, available_at=held_until, fetched_at=held_until,
        **{event+'_released_at': released})
    assert evaluate(current, now=held_until)['status'] == 'passed'


@pytest.mark.parametrize('event', ['vi', 'sidecar', 'circuit'])
@pytest.mark.parametrize('released', ['bad', '2026-10-09T00:30:00', '2026-10-09T01:00:01Z', float('nan'), []])
def test_invalid_naive_or_future_event_release_timestamp_holds(event, released):
    assert evaluate(state(**{event+'_released_at': released}))['status'] == 'held'


def test_release_after_fact_capture_cannot_describe_an_already_inactive_event():
    current = state(source_at='2026-10-09T00:59:00Z', vi_released_at='2026-10-09T00:59:30Z')
    assert evaluate(current)['status'] == 'held'


def test_vi_holds_only_its_bound_symbol_without_sticky_global_halt():
    assert evaluate(state(vi_active=True))['status'] == 'held'
    other = row('000660')
    current = state(symbol=other['symbol'], opportunity_id=other['opportunity_id'])
    assert evaluate(current, candidate=other)['status'] == 'passed'
    assert evaluate()['status'] == 'passed'


def test_explicit_market_expiration_shortens_validity_and_cannot_be_extended():
    actual = evaluate(state(valid_until='2026-10-09T01:00:30Z'))
    assert actual['valid_until'] == '2026-10-09T01:00:30Z'
    assert evaluate(state(valid_until=NOW))['status'] == 'held'
    assert evaluate(state(valid_until='bad'))['status'] == 'held'


@pytest.mark.parametrize('field,bad', [
    ('max_market_age_seconds', float('nan')), ('max_market_age_seconds', True),
    ('max_market_age_seconds', -1), ('vi_cooldown_seconds', '300'),
    ('systemic_cooldown_seconds', float('inf')), ('plan_cutoff', 'bad'),
    ('session_start', '15:05'),
])
def test_malformed_policy_holds_instead_of_crashing_or_weakening_checks(field, bad):
    actual = evaluate(policy={**POLICY, field: bad})
    assert actual['status'] == 'held'
    assert 'market_policy_invalid' in actual['reasons']


def test_missing_policy_keys_use_documented_guard_policy_only():
    assert evaluate(policy={}) == evaluate()


def test_explicit_policy_can_shorten_capture_freshness_without_mutation():
    policy = {**POLICY, 'max_market_age_seconds': 60}
    current = state(source_at='2026-10-09T00:58:59Z')
    before = deepcopy(policy)
    assert evaluate(current, policy=policy)['status'] == 'held'
    assert policy == before
