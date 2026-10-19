"""Explicit v2 economic gates; legacy control identities remain unchanged."""
from copy import deepcopy

import pytest

from app.services.mirofish.alpha_lab import decision_engine as engine, opportunity_store, telegram_alerts
from tests.test_alpha_lab_decision_engine import fixture, phase, saved

NOW = '2026-10-02T10:00:00Z'
POLICY = 'profit-opportunity-v2'
BASIS = 'causal_recovery_recent_stress_then_confirmation'


def v2_fixture():
    discovery, prices, report = fixture()
    discovery.update(policy_version='quality-setup-opportunity-v2', selection_basis=BASIS,
                     recent_sessions=126, recent_start_session='2026-06-01')
    for raw, audit in zip(discovery['candidates'], discovery['audit']):
        audit['confirmation'] = phase([.025, -.006]*6, '2026-05-14', '2026-10-02')
        audit['recent'] = phase([.025, -.006]*3, '2026-06-01', '2026-10-02')
        raw['evidence'].update(selection_basis=BASIS, recent=deepcopy(audit['recent']['summary']))
    return discovery, prices, report


def build(discovery=None, prices=None, report=None):
    if discovery is None:
        discovery, prices, report = v2_fixture()
    return engine.build_opportunity_board_v2(discovery, prices, report, now=NOW)


def test_v2_rejects_uncertainty_dominated_positive_mean_instead_of_filling_slots():
    discovery, prices, report = v2_fixture()
    for audit in discovery['audit']:
        audit['calibration'] = phase([.19, -.11]*15, '2022-01-03', '2025-01-02')
    value = build(discovery, prices, report)
    assert value['candidates'] == []
    assert value['policy_version'] == POLICY and value['live_orders'] is False
    assert {r['reason'] for r in value['alternatives']} == {'uncertainty_adjusted_score_nonpositive'}


def test_v2_rejects_after_correlation_and_keeps_empty_slot_cash():
    value = build()
    assert [r['symbol'] for r in value['candidates']] == ['000001', '000003']
    assert any(r['symbol'] == '000002' and r['reason'] == 'diversification_adjusted_score_nonpositive'
               for r in value['alternatives'])
    for row in value['candidates']:
        assert row['ranking']['score'] > 0 and row['reference_weight'] <= .05
        assert row['ranking']['recent_samples'] == 6
        assert row['ranking']['conservative_score'] == pytest.approx(min(
            row['ranking']['stress_mean_net_return']-1.96*row['ranking']['standard_error'],
            row['ranking']['recent_stress_mean_net_return']))


@pytest.mark.parametrize('mutation', ['negative', 'insufficient', 'future', 'summary_only'])
def test_v2_recent_phase_must_have_real_completed_positive_outcomes(mutation):
    discovery, prices, report = v2_fixture()
    for audit in discovery['audit']:
        if mutation == 'negative': audit['recent'] = phase([.005, -.02]*3, '2026-06-01', '2026-10-02')
        elif mutation == 'insufficient': audit['recent'] = phase([.025, -.006]*2, '2026-06-01', '2026-10-02')
        elif mutation == 'future': audit['recent']['trades'][-1]['exit_date'] = '2026-10-03'
        else: audit['recent'].pop('trades')
    assert build(discovery, prices, report)['candidates'] == []


def test_v2_future_price_values_do_not_change_decisions_and_identity_is_policy_bound():
    discovery, prices, report = v2_fixture()
    expected = build(discovery, prices, report)
    for symbol, rows in prices.items(): rows.append(dict(date='2026-10-03', close=float('nan'), symbol=symbol))
    assert build(discovery, prices, report) == expected
    old_discovery, old_prices, old_report = fixture()
    legacy = engine.build_opportunity_board(old_discovery, old_prices, old_report, now=NOW)
    assert engine.POLICY == 'profit-opportunity-v1'
    assert legacy['decision_id'] == '269e78db63ed79d6276c3efa2430b5ed09fdd1fe1c10b4b986f6493df0b1bc3f'
    assert engine._stable_identity(legacy['input_fingerprint'], legacy['source_audit_hash'],
        legacy['latest_session'], legacy['candidates']) == legacy['decision_id']
    assert engine._stable_identity(expected['input_fingerprint'], expected['source_audit_hash'],
        expected['latest_session'], expected['candidates'], policy=POLICY) == expected['decision_id']


def test_known_policy_mixed_journal_preserves_first_issued_records(tmp_path):
    old_discovery, old_prices, old_report = fixture()
    legacy = engine.build_opportunity_board(old_discovery, old_prices, old_report, now=NOW)
    current = build()
    opportunity_store.register_board(tmp_path, legacy)
    before = opportunity_store.read_journal(tmp_path)['issued'][0]
    opportunity_store.register_board(tmp_path, current)
    newer = deepcopy(current); newer['generated_at'] = '2026-10-02T11:00:00Z'
    assert opportunity_store.register_board(tmp_path, newer) == current
    rows = opportunity_store.read_journal(tmp_path)['issued']
    assert rows[0] == before and len(rows) == 2
    assert telegram_alerts._valid_board(legacy) and telegram_alerts._valid_board(current)
    unknown = deepcopy(current); unknown['policy_version'] = 'profit-opportunity-v999'
    assert not telegram_alerts._valid_board(unknown)
    with pytest.raises(ValueError, match='identity'): opportunity_store.register_board(tmp_path, unknown)


def test_v2_bad_economic_score_cannot_be_promoted_by_fresh_quote():
    source, quotes = saved()
    current = build()
    source['report']['opportunity_board'] = current
    quotes['decision_id'] = current['decision_id']
    projected = engine.project_opportunity_board(source, now='2026-10-05T01:05:00Z', quote_snapshot=quotes)
    assert projected['opportunity_engine']['status'] == 'ready'
    assert all(r['action'] == 'entry_candidate' for r in projected['opportunity_engine']['candidates'])
    current['candidates'][0]['ranking']['recent_stress_mean_net_return'] = -.01
    current['candidates'][0]['ranking']['conservative_score'] = -.01
    current['candidates'][0]['ranking']['score'] = -.01
    current['decision_id'] = engine._stable_identity(current['input_fingerprint'], current['source_audit_hash'],
        current['latest_session'], current['candidates'], policy=POLICY)
    for row in current['candidates']:
        row['decision_id'] = current['decision_id']
        row['opportunity_id'] = engine._hash(dict(decision_id=current['decision_id'], symbol=row['symbol'], strategy_id=row['strategy_id']))
    quotes['decision_id'] = current['decision_id']
    held = engine.project_opportunity_board(source, now='2026-10-05T01:05:00Z', quote_snapshot=quotes)['opportunity_engine']
    assert held['status'] == 'held' and not held['candidates']


def test_v2_opinion_requires_recent_validation_and_preserves_zero_order_contract():
    from app.services.mirofish.alpha_lab.proposals import present_status
    from tests.test_alpha_lab_opportunities import status
    source = status()
    report = source['report']; scan = report['opportunity_scan']; row = report['buy_candidates'][0]
    scan.update(policy_version='quality-setup-opportunity-v2', selection_basis=BASIS, recent_sessions=126)
    row['evidence'].update(selection_basis=BASIS, recent=deepcopy(row['evidence']['confirmation']))
    row['evidence']['recent']['start'] = '2026-06-01'
    row.update(symbol='000001', strategy_id='momentum')
    report['input_fingerprint'] = 'a'*64; scan['audit_hash'] = 'b'*64
    report['opportunity_board'] = build()
    value = present_status(source, now='2026-10-04T06:00:00Z')
    assert value['report']['buy_candidates'][0]['proposal']['action'] == 'buy'
    assert value['report']['buy_candidates'][0]['proposal']['order_allowed'] is False
    assert value['report']['approval']['approved_exposure'] == 0
    row['evidence']['recent']['stress_mean_net_return'] = -.001
    assert present_status(source, now='2026-10-04T06:00:00Z')['report']['buy_candidates'][0]['proposal']['action'] == 'wait'


@pytest.mark.parametrize('mutation', ['missing_board', 'wrong_policy', 'not_selected', 'nonpositive', 'foreign_source'])
def test_v2_opinion_cannot_bypass_selected_board_economic_gate(mutation):
    from app.services.mirofish.alpha_lab.proposals import present_status
    from tests.test_alpha_lab_opportunities import status
    source = status(); report = source['report']; scan = report['opportunity_scan']; row = report['buy_candidates'][0]
    scan.update(policy_version='quality-setup-opportunity-v2', selection_basis=BASIS, recent_sessions=126, audit_hash='b'*64)
    row['evidence'].update(selection_basis=BASIS, recent=deepcopy(row['evidence']['confirmation']))
    row['evidence']['recent']['start'] = '2026-06-01'
    row.update(symbol='000001', strategy_id='momentum'); report['input_fingerprint'] = 'a'*64
    report['opportunity_board'] = build()
    if mutation == 'missing_board': report.pop('opportunity_board')
    elif mutation == 'wrong_policy': report['opportunity_board']['policy_version'] = engine.POLICY
    elif mutation == 'not_selected': row['symbol'] = '000002'
    elif mutation == 'nonpositive': report['opportunity_board']['candidates'][0]['ranking']['score'] = -.01
    else: report['input_fingerprint'] = 'f'*64
    assert present_status(source, now='2026-10-04T06:00:00Z')['report']['buy_candidates'][0]['proposal']['action'] == 'wait'


def test_recent_evidence_is_exact_confirmation_tail_not_borrowed_labels():
    discovery, prices, report = v2_fixture()
    for audit in discovery['audit']:
        audit['recent']['trades'] = audit['recent']['trades'][:5]
        audit['recent']['summary']['samples'] = 5
    assert build(discovery, prices, report)['candidates'] == []


def test_recent_all_positive_outcomes_are_valid_without_changing_old_phase_gates():
    discovery, prices, report = v2_fixture()
    for audit in discovery['audit']:
        audit['confirmation'] = phase([.025, -.006]*3+[.015]*6, '2026-05-14', '2026-10-02')
        audit['recent'] = phase([.015]*6, '2026-06-01', '2026-10-02')
    assert build(discovery, prices, report)['candidates']


@pytest.mark.parametrize('bad_current', ['missing', 'negative', 'future_label'])
def test_v2_invalid_current_price_cannot_supply_a_plan(bad_current):
    discovery, prices, report = v2_fixture()
    for rows in prices.values():
        if bad_current == 'missing': rows.pop()
        elif bad_current == 'negative': rows[-1]['close'] = -100.
        else: rows[-1]['date'] = '2026-10-03'
    assert build(discovery, prices, report)['candidates'] == []


@pytest.mark.parametrize('policy', ['profit-opportunity-v2', 'profit-opportunity-v999'])
def test_desk_and_account_accept_only_explicit_known_board_policies(policy):
    from app.services.mirofish.alpha_lab import account_plan, decision_contract
    from tests.test_alpha_lab_account_plan import status as account_status, account, NOW as account_now
    from tests.test_alpha_lab_decision_contract import status as desk_status, NOW as desk_now
    source = desk_status(); source['opportunity_engine']['policy_version'] = policy
    desk = decision_contract.build_agent_desk(source, now=desk_now)
    assert bool(desk['candidates']) is (policy == POLICY)
    assert desk['order_allowed'] is False
    source = account_status(); source['opportunity_engine']['policy_version'] = policy
    plan = account_plan.build_account_plan(source, account(), now=account_now)
    assert plan['status'] == ('ready' if policy == POLICY else 'held')
    assert plan['order_allowed'] is False


@pytest.mark.parametrize('mutation', ['unknown_policy', 'legacy_policy_on_v2_identity', 'bool_recent_count', 'nan_recent_mean'])
def test_v2_saved_policy_and_recent_metadata_are_validated_before_quote_promotion(mutation):
    source, quotes = saved()
    current = build(); source['report']['opportunity_board'] = current; quotes['decision_id'] = current['decision_id']
    if mutation == 'unknown_policy': current['policy_version'] = 'profit-opportunity-v999'
    elif mutation == 'legacy_policy_on_v2_identity': current['policy_version'] = engine.POLICY
    elif mutation == 'bool_recent_count': current['candidates'][0]['ranking']['recent_samples'] = True
    else: current['candidates'][0]['ranking']['recent_stress_mean_net_return'] = float('nan')
    projected = engine.project_opportunity_board(source, now='2026-10-05T01:05:00Z', quote_snapshot=quotes)
    assert not any(row['action'] == 'entry_candidate' for row in projected.get('opportunity_engine', {}).get('candidates', []))


def test_v2_public_recent_fields_are_scalar_bounded_and_internal_extensions_stay_private():
    import json
    source, quotes = saved()
    current = build(); source['report']['opportunity_board'] = current; quotes['decision_id'] = current['decision_id']
    current['candidates'][0]['ranking']['private_path'] = 'C:/private/inputs.json'
    projected = engine.project_opportunity_board(source, now='2026-10-05T01:05:00Z', quote_snapshot=quotes)
    assert 'C:/private' not in json.dumps(projected, allow_nan=False)
    assert projected['opportunity_engine']['candidates'][0]['ranking']['recent_samples'] == 6
