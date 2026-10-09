"""Evidence cannot promote retrospective research or reissue frozen decisions."""
from copy import deepcopy
import hashlib
import importlib
import json

import pytest


NOW = '2026-10-08T02:00:00Z'
ORIGIN = '2026-10-08T01:00:00Z'
UNTIL = '2026-10-08T06:30:00Z'
ROLE_IDS = ['regime', 'fx_liquidity', 'flow', 'disclosure', 'sector', 'event',
            'micro', 'sentiment', 'auditor', 'leader', 'risk_guard', 'review']


def contract():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.decision_contract')
    except ModuleNotFoundError:
        pytest.fail('the read-only evidence-aware agent desk is not implemented')


def status():
    decision = 'a'*64
    candidates = []
    for rank, symbol in enumerate(['000001', '000003', '000002'], 1):
        identity = dict(decision_id=decision, symbol=symbol, strategy_id='momentum')
        opportunity = hashlib.sha256(json.dumps(identity, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        candidates.append(dict(opportunity_id=opportunity, decision_id=decision,
            input_fingerprint='b'*64, source_audit_hash='c'*64, symbol=symbol,
            name='종목'+symbol, market='KR', strategy_id='momentum', rank=rank,
            action='entry_candidate', current_price=101., quote_at='2026-10-08T01:59:00Z',
            fetched_at='2026-10-08T01:59:20Z', quote_source='KIS:J:FHKST03010200+FHKST01010100',
            valid_until=UNTIL, reference_weight=.05, plan=dict(basis='observed_quote_reference',
                entry_low=101., entry_high=102., stop_price=92., target_price=116., horizon_sessions=10),
            ranking=dict(score=.012, calibration_samples=40, confirmation_samples=12),
            audit=dict(status='passed', independent_validation=False), reasons=[]))
    board = dict(schema_version=1, policy_version='profit-opportunity-v1',
        decision_id=decision, input_fingerprint='b'*64, source_audit_hash='c'*64,
        generated_at=ORIGIN, latest_session='2026-10-07', entry_session='2026-10-08',
        valid_until=UNTIL, status='ready', research_only=True, live_orders=False,
        candidates=candidates, reasons=[])
    return dict(state='held', opportunity_engine=board,
        report=dict(decision_at=ORIGIN, opportunity_board=deepcopy(board),
            approval=dict(status='held', approved_exposure=0., live_orders=False),
            forward=dict(matured=90, win_rate=.9)))


def record(row, origin, *, role='disclosure', claim='direction', kind='market'):
    return dict(symbol=row['symbol'], opportunity_id=row['opportunity_id'],
        role=role, claim_id=claim, core=claim in {'direction', 'risk'},
        kind=kind, source_grade='A', lineage_id=origin, origin_ids=[origin], source=origin,
        source_at='2026-10-08T00:50:00Z', available_at='2026-10-08T00:51:00Z',
        fetched_at='2026-10-08T00:55:00Z', valid_until=UNTIL,
        status='ready', confidence=.8)


def usable_evidence(row):
    return [record(row, 'exchange', claim='direction'),
            record(row, 'filing', claim='direction'),
            record(row, 'exchange', claim='risk'),
            record(row, 'filing', claim='risk'),
            record(row, 'fx-provider', role='fx_liquidity', claim='fx')]


def first(*, evidence=None, fixture=None, now=NOW):
    return contract().build_agent_desk(fixture or status(), now=now, evidence=evidence)['candidates'][0]


def test_saved_top3_identity_order_and_frozen_board_are_unchanged():
    fixture = status()
    original = deepcopy(fixture)
    desk = contract().build_agent_desk(fixture, now=NOW)
    assert fixture == original
    assert [row['symbol'] for row in desk['candidates']] == ['000001', '000003', '000002']
    assert [row['opportunity_id'] for row in desk['candidates']] == [
        row['opportunity_id'] for row in original['opportunity_engine']['candidates']]
    desk['candidates'][0]['missing'].append('modified_view')
    assert fixture == original
    assert desk['schema_version'] == 1
    assert desk['policy_version'] == 'evidence-account-v1'
    assert desk['generated_at'] == NOW
    assert desk['order_allowed'] is False
    assert [role['id'] for role in desk['roles']] == ROLE_IDS


def test_no_extra_sources_never_certifies_existing_research_audit_or_forecast():
    desk = contract().build_agent_desk(status(), now=NOW)
    for row in desk['candidates']:
        assert row['state'] == 'Watch'
        assert row['audit']['status'] == 'held'
        assert row['audit']['independent_sources'] == 0
        assert 'fx_and_flow_missing' in row['audit']['reasons']
        assert row['probability']['kind'] == 'unavailable'
        assert row['probability']['bull'] is row['probability']['base'] is row['probability']['bear'] is None
        assert {'fx_liquidity', 'flow', 'calibrated_probability'} <= set(row['missing'])
    assert desk['promotion']['stage'] == 'M0'
    assert {'predeclared_oos_pending', 'calibration_pending', 'manual_approval_required'} <= set(desk['promotion']['reasons'])
    assert all(role['status'] == 'unavailable' for role in desk['roles'][:6])
    assert next(role for role in desk['roles'] if role['id'] == 'sentiment')['status'] == 'unavailable'


def test_two_websites_copying_one_origin_are_one_independent_source():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence['lineage_id'] = 'site-a' if evidence['lineage_id'] == 'exchange' else 'site-b'
        evidence['origin_ids'] = ['same-primary-feed']
        evidence['source'] = 'https://a.example/news' if evidence['lineage_id'] == 'site-a' else 'https://b.example/news'
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 1
    assert 'direction_independent_sources_missing' in actual['audit']['reasons']
    assert 'risk_independent_sources_missing' in actual['audit']['reasons']


def test_overlapping_origin_chains_do_not_create_transitive_independence():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[0]['origin_ids'] = ['primary-a', 'aggregator']
    records[1]['origin_ids'] = ['aggregator', 'primary-b']
    records[2]['origin_ids'] = ['primary-a']
    records[3]['origin_ids'] = ['primary-b']
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['independent_sources'] == 1
    assert actual['audit']['status'] == 'held'


def test_social_only_core_claims_cannot_authorize_even_with_fx():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence.update(kind='social', role='sentiment')
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['independent_sources'] == 0
    assert actual['audit']['status'] == 'held'
    assert 'social_only_core_claims' in actual['audit']['reasons']


@pytest.mark.parametrize('changes,reason', [
    ({'source_at': '2026-10-08T01:01:00Z'}, 'evidence_after_decision'),
    ({'available_at': '2026-10-08T01:01:00Z'}, 'evidence_after_decision'),
    ({'fetched_at': '2026-10-08T01:01:00Z'}, 'evidence_after_decision'),
    ({'source_at': '2026-10-08T03:00:00Z'}, 'evidence_after_decision'),
    ({'available_at': '2026-10-08T00:49:00Z'}, 'evidence_time_order_invalid'),
    ({'fetched_at': '2026-10-08T00:50:00Z'}, 'evidence_time_order_invalid'),
    ({'source_at': '2026-10-08T00:50:00'}, 'evidence_timestamp_invalid'),
    ({'source_at': 'bad'}, 'evidence_timestamp_invalid'),
    ({'valid_until': NOW}, 'evidence_expired'),
    ({'valid_until': '2026-10-08T00:49:00Z'}, 'evidence_time_order_invalid'),
    ({'status': 'unavailable'}, 'evidence_unavailable'),
    ({'confidence': True}, 'evidence_confidence_invalid'),
    ({'confidence': float('nan')}, 'evidence_confidence_invalid'),
    ({'confidence': float('inf')}, 'evidence_confidence_invalid'),
    ({'confidence': 1.1}, 'evidence_confidence_invalid'),
    ({'confidence': 0}, 'evidence_confidence_invalid'),
    ({'core': 'true'}, 'evidence_claim_invalid'),
    ({'claim_id': 'risk', 'core': False}, 'evidence_claim_invalid'),
    ({'claim_id': ''}, 'evidence_claim_invalid'),
    ({'origin_ids': []}, 'evidence_lineage_missing'),
    ({'lineage_id': ''}, 'evidence_lineage_missing'),
    ({'origin_ids': ['']}, 'evidence_lineage_missing'),
    ({'source': ''}, 'evidence_source_missing'),
    ({'source_grade': None}, 'evidence_source_grade_invalid'),
    ({'source_grade': True}, 'evidence_source_grade_invalid'),
    ({'source_grade': 'unknown'}, 'evidence_source_grade_invalid'),
    ({'opportunity_id': 'f'*64}, 'evidence_identity_mismatch'),
    ({'symbol': '999999'}, 'evidence_identity_mismatch'),
    ({'role': 'not_a_role'}, 'evidence_role_invalid'),
    ({'kind': 'unknown'}, 'evidence_kind_invalid'),
])
def test_invalid_record_is_rejected_and_cannot_supply_independence(changes, reason):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence.update(changes)
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 0
    assert reason in actual['audit']['reasons']


def test_missing_explicit_origins_does_not_default_to_distinct_urls():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records:
        evidence.pop('origin_ids')
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['independent_sources'] == 0
    assert 'evidence_lineage_missing' in actual['audit']['reasons']
    assert 'fx_and_flow_missing' in actual['audit']['reasons']


def test_fresh_explicit_non_social_claims_pass_sources_only_and_remain_m0_watch():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    evidence = {row['symbol']: usable_evidence(row)}
    before = deepcopy(evidence)
    desk = contract().build_agent_desk(fixture, now=NOW, evidence=evidence)
    actual = desk['candidates'][0]
    assert evidence == before
    assert actual['audit'] == dict(status='passed', reasons=[], independent_sources=2)
    assert actual['state'] == 'Watch'
    assert desk['promotion']['stage'] == 'M0'
    assert desk['order_allowed'] is False
    assert 'flow' in actual['missing']
    assert 'fx_liquidity' not in actual['missing']
    assert actual['invalidation']['price_below'] == 92.
    assert actual['invalidation']['price_above'] == 102.
    assert actual['invalidation']['valid_until'] == '2026-10-08T02:06:00Z'


def test_social_fx_record_cannot_satisfy_hard_market_data_gate():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[-1]['kind'] = 'social'
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert 'fx_and_flow_missing' in actual['audit']['reasons']


@pytest.mark.parametrize('changes', [
    {'kind': 'news'}, {'claim_id': 'interest'},
    {'claim_id': 'direction', 'core': True},
])
def test_role_tag_alone_cannot_certify_usable_fx_or_flow(changes):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[-1].update(changes)
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert 'fx_and_flow_missing' in actual['audit']['reasons']
    assert 'fx_liquidity' in actual['missing']


def test_explicit_foreign_flow_can_satisfy_hard_gate_without_fx():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[-1].update(role='flow', claim_id='foreign_flow')
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'passed'
    assert 'fx_liquidity' in actual['missing']
    assert 'flow' not in actual['missing']


def test_origin_matching_another_lineage_is_not_counted_independently():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence['origin_ids'] = ['document-a'] if evidence['lineage_id'] == 'exchange' else ['exchange']
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 1


def test_sentiment_tag_cannot_supply_core_claims_even_if_disguised_as_market():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence['role'] = 'sentiment'
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 0


@pytest.mark.parametrize('kind,grade', [('market', 'C'), ('disclosure', 'B'),
    ('news', 'B'), ('news', 'A'), ('official_news', 'B')])
def test_unqualified_grade_or_general_news_cannot_authorize_core_claims(kind, grade):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence.update(kind=kind, source_grade=grade)
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 0
    assert 'direction_independent_sources_missing' in actual['audit']['reasons']


def test_grade_is_never_inferred_from_source_label_or_kind():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records:
        evidence.pop('source_grade')
        evidence['source'] = 'official KRX'
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['independent_sources'] == 0
    assert 'evidence_source_grade_invalid' in actual['audit']['reasons']
    assert 'fx_and_flow_missing' in actual['audit']['reasons']


@pytest.mark.parametrize('grade', ['B', 'C'])
def test_unqualified_grade_cannot_satisfy_fx_or_flow_even_when_core_is_available(grade):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[-1]['source_grade'] = grade
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert 'fx_and_flow_missing' in actual['audit']['reasons']


def test_explicit_authoritative_official_news_can_support_core_with_market_fx():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence.update(kind='official_news', source_grade='S')
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'passed'
    assert actual['audit']['independent_sources'] == 2


def test_supporting_grade_does_not_mark_required_source_role_as_passed():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence['source_grade'] = 'B'
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert 'disclosure' in actual['missing']


def test_projection_validity_cannot_outlive_an_accepted_evidence_record():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[0]['valid_until'] = '2026-10-08T02:00:30Z'
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'passed'
    assert actual['invalidation']['valid_until'] == '2026-10-08T02:00:30Z'


def test_source_age_expiry_bounds_plan_and_holds_at_equality():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[-1].update(source_at='2026-10-07T02:00:30Z',
        available_at='2026-10-07T02:00:40Z', fetched_at='2026-10-07T02:00:50Z')
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'passed'
    assert actual['invalidation']['valid_until'] == '2026-10-08T02:00:30Z'
    expired = first(fixture=fixture, evidence={row['symbol']: records}, now='2026-10-08T02:00:30Z')
    assert expired['audit']['status'] == 'held'
    assert 'evidence_stale' in expired['audit']['reasons']
    assert 'fx_and_flow_missing' in expired['audit']['reasons']


@pytest.mark.parametrize('field,value', [('rank', 1.0), ('rank', True),
    ('market', ['KR']), ('strategy_id', {'momentum': True})])
def test_malformed_existing_identity_types_fail_closed(field, value):
    fixture = status()
    fixture['opportunity_engine']['candidates'][0][field] = value
    assert contract().build_agent_desk(fixture, now=NOW)['candidates'] == []


def test_actual_closed_net_array_cvar_is_empirical_and_does_not_supply_forecast():
    actual = contract().empirical_cvar([-.2, -.1, .1, .2], confidence=.5)
    assert actual['status'] == 'available'
    assert actual['basis'] == 'observed_net_returns_not_forecast'
    assert actual['samples'] == 4
    assert actual['tail_mean_net_return'] == pytest.approx(-.15)
    assert actual['cvar_loss'] == pytest.approx(.15)
    # With 1.5 sample mass in the lower tail, -.2 plus half of -.1 averages -1/6.
    fractional = contract().empirical_cvar([-.2, -.1, .1], confidence=.5)
    assert fractional['tail_mean_net_return'] == pytest.approx(-1/6)
    assert first()['probability']['bull'] is None


@pytest.mark.parametrize('values', [None, [], [True, -.1], [float('nan')],
    [float('inf')], ['-.1'], {'net_returns': [-.1]}, [-1.1], [10**400]])
def test_cvar_never_fabricates_a_distribution_from_missing_or_bad_net_arrays(values):
    actual = contract().empirical_cvar(values)
    assert actual['status'] == 'unavailable'
    assert actual['cvar_loss'] is actual['tail_mean_net_return'] is None


@pytest.mark.parametrize('confidence', [True, None, 0, 1, float('nan'), .1])
def test_cvar_invalid_confidence_is_unknown(confidence):
    actual = contract().empirical_cvar([-.1, .1], confidence=confidence)
    assert actual['status'] == 'unavailable'


def test_stale_market_flow_cannot_satisfy_hard_gate_even_with_long_expiry():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    records[-1].update(role='flow', source_at='2026-10-06T00:50:00Z',
        available_at='2026-10-06T00:51:00Z', fetched_at='2026-10-06T00:55:00Z')
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert 'evidence_stale' in actual['audit']['reasons']
    assert 'fx_and_flow_missing' in actual['audit']['reasons']


def test_bound_current_quote_is_observed_micro_without_becoming_independent():
    desk = contract().build_agent_desk(status(), now=NOW)
    micro = next(role for role in desk['roles'] if role['id'] == 'micro')
    assert micro['status'] == 'passed'
    assert desk['candidates'][0]['audit']['independent_sources'] == 0


@pytest.mark.parametrize('changes,reason,state', [
    ({'valid_until': NOW}, 'entry_window_expired', 'No-trade'),
    ({'quote_at': '2026-10-08T02:01:00Z'}, 'quote_stale_or_future', 'Watch'),
    ({'quote_at': '2026-10-08T01:00:00Z'}, 'quote_stale_or_future', 'Watch'),
    ({'quote_at': '2026-10-08T01:53:00Z', 'fetched_at': '2026-10-08T01:54:00Z'}, 'quote_stale_or_future', 'Watch'),
    ({'current_price': float('nan')}, 'quote_unavailable', 'Watch'),
    ({'action': 'skip', 'reasons': ['below_stop']}, 'entry_not_current', 'No-trade'),
])
def test_current_entry_conditions_cannot_be_authorized_by_external_records(changes, reason, state):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    row.update(changes)
    actual = first(fixture=fixture, evidence={row['symbol']: usable_evidence(row)})
    assert actual['audit']['status'] == 'held'
    assert reason in actual['audit']['reasons']
    assert actual['state'] == state


def test_fabricated_probabilities_and_client_style_extra_desk_cannot_cross_projection():
    fixture = status()
    fixture['agent_desk'] = dict(promotion=dict(stage='M9'), order_allowed=True)
    fixture['opportunity_engine']['candidates'][0]['probability'] = dict(bull=.99, base=.01, bear=0)
    actual = first(fixture=fixture)
    assert actual['probability']['kind'] == 'unavailable'
    assert actual['probability']['bull'] is actual['probability']['base'] is actual['probability']['bear'] is None
    assert set(actual) == {'opportunity_id', 'symbol', 'name', 'state', 'audit', 'probability', 'invalidation', 'missing'}


def test_raw_unprojected_report_and_mismatched_identity_cannot_create_new_candidate():
    fixture = status()
    fixture.pop('opportunity_engine')
    assert contract().build_agent_desk(fixture, now=NOW)['candidates'] == []
    fixture = status()
    fixture['opportunity_engine']['candidates'][0]['opportunity_id'] = 'f'*64
    assert contract().build_agent_desk(fixture, now=NOW)['candidates'] == []


def test_extra_candidates_and_duplicate_symbols_fail_closed_instead_of_truncating():
    fixture = status()
    fixture['opportunity_engine']['candidates'].append(deepcopy(fixture['opportunity_engine']['candidates'][0]))
    assert contract().build_agent_desk(fixture, now=NOW)['candidates'] == []
    fixture = status()
    fixture['opportunity_engine']['candidates'][1] = deepcopy(fixture['opportunity_engine']['candidates'][0])
    assert contract().build_agent_desk(fixture, now=NOW)['candidates'] == []


def test_malformed_status_and_records_are_bounded_unknown_not_exceptions():
    assert contract().build_agent_desk(None, now=NOW)['candidates'] == []
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    actual = first(fixture=fixture, evidence={row['symbol']: [None, 'bad', 3]})
    assert actual['audit']['status'] == 'held'
    assert 'evidence_record_invalid' in actual['audit']['reasons']
    actual = first(fixture=fixture, evidence={row['symbol']: {'confidence': .99}})
    assert 'evidence_records_invalid' in actual['audit']['reasons']
    actual = first(fixture=fixture, evidence={row['symbol']: usable_evidence(row)*30})
    assert actual['audit']['status'] == 'held'
    assert 'evidence_records_limit' in actual['audit']['reasons']


def test_naive_evaluation_clock_is_rejected():
    with pytest.raises(ValueError, match='timezone_required'):
        contract().build_agent_desk(status(), now='2026-10-08T02:00:00')


def semantic_evidence(row):
    records = usable_evidence(row)
    for evidence in records[:4]:
        evidence.update(direction='up', figure=100., unit='KRW_bn',
            conflict_group='caller-group', missing_reason=None)
    return records


def test_legacy_source_pass_does_not_certify_directional_semantics():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    actual = first(fixture=fixture, evidence={row['symbol']: usable_evidence(row)})
    assert actual['audit'] == dict(status='passed', reasons=[], independent_sources=2)
    assert 'directional_semantics' in actual['missing']


def test_complete_semantics_pass_sources_without_forecast_or_orders():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    original = deepcopy(records)
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert records == original
    assert actual['audit'] == dict(status='passed', reasons=[], independent_sources=2)
    assert 'directional_semantics' not in actual['missing']
    assert actual['state'] == 'Watch'
    assert actual['probability']['bull'] is None
    assert set(actual) == {'opportunity_id', 'symbol', 'name', 'state', 'audit',
                           'probability', 'invalidation', 'missing'}


@pytest.mark.parametrize('field,value', [
    ('direction', ['up']), ('direction', {}), ('direction', None),
    ('direction', 'buy'), ('figure', True), ('figure', float('nan')),
    ('figure', float('inf')), ('figure', float('-inf')), ('figure', '100'),
    ('figure', []), ('figure', {}), ('figure', 10**400),
    ('unit', None), ('unit', []), ('unit', ''), ('unit', 'x'*65),
    ('unit', 'KRW\nforged'), ('conflict_group', []), ('conflict_group', {}),
    ('conflict_group', None), ('conflict_group', 'bad group'),
    ('conflict_group', 'x'*161), ('missing_reason', []),
    ('missing_reason', {}), ('missing_reason', False),
    ('missing_reason', ''), ('missing_reason', 'x'*161),
    ('missing_reason', 'missing\nforged'),
])
def test_malformed_semantics_are_held_and_cannot_supply_core_sources(field, value):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    for evidence in records[:4]:
        evidence[field] = value
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 0
    assert 'evidence_semantics_invalid' in actual['audit']['reasons']


@pytest.mark.parametrize('field', ['direction', 'figure', 'unit',
                                 'conflict_group', 'missing_reason'])
def test_one_semantic_field_requires_the_complete_contract(field):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = usable_evidence(row)
    values = dict(direction='up', figure=1., unit='KRW',
                  conflict_group='group', missing_reason=None)
    for evidence in records[:4]:
        evidence[field] = values[field]
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 0
    assert 'evidence_semantics_invalid' in actual['audit']['reasons']


@pytest.mark.parametrize('changes', [
    dict(direction='unknown', figure=None, missing_reason='unavailable'),
    dict(direction='unknown'), dict(figure=None, missing_reason='not_measured'),
    dict(missing_reason='unverified'),
])
def test_unknown_or_missing_semantics_cannot_certify_core_claims(changes):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    for evidence in records[:4]:
        evidence.update(changes)
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 0
    assert 'evidence_semantics_invalid' not in actual['audit']['reasons']
    assert 'direction_independent_sources_missing' in actual['audit']['reasons']
    assert 'directional_semantics' in actual['missing']


@pytest.mark.parametrize('claim', ['direction', 'risk'])
def test_authoritative_opposite_claims_are_held_despite_split_caller_groups(claim):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    matching = [evidence for evidence in records if evidence['claim_id'] == claim]
    matching[0].update(direction='up', source_grade='S', conflict_group='first-label')
    matching[1].update(direction='down', source_grade='A', conflict_group='second-label')
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert 'evidence_direction_conflict' in actual['audit']['reasons']
    assert actual['probability']['bull'] is None


def test_same_caller_group_cannot_merge_different_claims_into_a_conflict():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    for evidence in records[:4]:
        if evidence['claim_id'] == 'risk':
            evidence['direction'] = 'down'
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'passed'
    assert 'evidence_direction_conflict' not in actual['audit']['reasons']


@pytest.mark.parametrize('changes', [
    dict(source_grade='C'), dict(source_grade='B'), dict(kind='social'),
    dict(kind='news'), dict(role='sentiment'),
])
def test_supporting_opposite_direction_cannot_force_authoritative_conflict(changes):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    supporting = deepcopy(records[0])
    supporting.update(direction='down', lineage_id='supporting', origin_ids=['supporting'])
    supporting.update(changes)
    records.append(supporting)
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'passed'
    assert actual['audit']['independent_sources'] == 2
    assert 'evidence_direction_conflict' not in actual['audit']['reasons']


@pytest.mark.parametrize('changes', [
    dict(direction='down'), dict(figure=200.), dict(source_grade='S'),
    dict(lineage_id='another', origin_ids=['another']),
    dict(source='another-source'), dict(confidence=.9),
    dict(fetched_at='2026-10-08T00:56:00Z'),
])
def test_reused_evidence_id_with_mismatched_record_is_held(changes):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    records[0]['evidence_id'] = 'evidence-one'
    duplicate = deepcopy(records[0]); duplicate.update(changes)
    records.append(duplicate)
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert 'evidence_id_conflict' in actual['audit']['reasons']


@pytest.mark.parametrize('value', [None, True, [], {}, '', 'bad id', 'x'*161])
def test_optional_evidence_id_must_be_a_bounded_token(value):
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    for evidence in records[:4]:
        evidence['evidence_id'] = value
    actual = first(fixture=fixture, evidence={row['symbol']: records})
    assert actual['audit']['status'] == 'held'
    assert actual['audit']['independent_sources'] == 0
    assert 'evidence_id_invalid' in actual['audit']['reasons']


def test_exact_repeated_evidence_id_does_not_add_independent_sources():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    records[0]['evidence_id'] = 'evidence-one'
    expected = first(fixture=fixture, evidence={row['symbol']: records})
    repeated = first(fixture=fixture, evidence={row['symbol']: records+[deepcopy(records[0])]*10})
    assert repeated == expected


def test_reused_id_cannot_swap_lineage_with_origin_even_when_union_is_identical():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    records = semantic_evidence(row)
    records[0].update(evidence_id='evidence-one', origin_ids=['filing'])
    swapped = deepcopy(records[0]); swapped.update(lineage_id='filing', origin_ids=['exchange'])
    actual = first(fixture=fixture, evidence={row['symbol']: records+[swapped]})
    assert 'evidence_id_conflict' in actual['audit']['reasons']


def test_validated_semantics_are_immutable_and_detached_from_raw_record():
    fixture = status(); row = fixture['opportunity_engine']['candidates'][0]
    raw = semantic_evidence(row)[0]
    module = contract()
    normalized, reason = module._record(raw, row, module._timestamp(ORIGIN), module._timestamp(NOW))
    assert reason is None
    raw.update(direction='down', figure=float('nan'), unit='changed', conflict_group='changed')
    semantics = normalized['semantics']
    assert semantics.direction == 'up'
    assert semantics.figure == 100.
    assert semantics.unit == 'KRW_bn'
    assert semantics.conflict_group == row['symbol']+':'+row['opportunity_id']+':direction'
    with pytest.raises(AttributeError):
        semantics.direction = 'down'
