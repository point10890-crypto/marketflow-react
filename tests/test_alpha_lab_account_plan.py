"""Request-only account validation and hand-checked portfolio allocation."""
from copy import deepcopy
import hashlib
import importlib
import json

import pytest


NOW = '2026-10-08T01:05:00Z'


def risk():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.account_plan')
    except ModuleNotFoundError:
        pytest.fail('the pure account risk contract is not implemented')


def account(**changes):
    return dict(equity=1_000_000., available_cash=1_000_000., daily_pnl=0.,
                weekly_pnl=0., positions_confirmed=True, positions=[], **changes)


def candidate(symbol='000001', opportunity_id='1'*64, **changes):
    value = dict(opportunity_id=opportunity_id, symbol=symbol, name='종목 '+symbol,
        decision_id='a'*64, input_fingerprint='b'*64, source_audit_hash='c'*64,
        market='KR', strategy_id='momentum', rank=1, action='entry_candidate',
        current_price=100., quote_at='2026-10-08T01:04:30Z', fetched_at=NOW,
        quote_source='KIS:J:FHKST03010200+FHKST01010100',
        valid_until='2026-10-08T06:30:00Z', reference_weight=.05,
        plan=dict(basis='observed_quote_reference', entry_low=100., entry_high=100.,
                  stop_price=90., target_price=120., horizon_sessions=10),
        kelly=dict(raw_fraction=.4, fraction=.25, cap=.05, account_risk_cap=.01),
        audit=dict(status='passed', independent_validation=False, reasons=[]), reasons=[])
    value.update(changes)
    return value


def status():
    row = candidate()
    return dict(state='held',
        report=dict(buy_candidates=[dict(symbol='000001', theme='반도체')]),
        opportunity_engine=dict(schema_version=1, policy_version='profit-opportunity-v1',
            status='ready', decision_id='a'*64, input_fingerprint='b'*64,
            source_audit_hash='c'*64, generated_at='2026-10-07T09:45:00Z',
            entry_session='2026-10-08', valid_until='2026-10-08T06:30:00Z',
            research_only=True, live_orders=False, candidates=[row], reasons=[]),
        agent_desk=dict(schema_version=1, policy_version='evidence-account-v1',
            generated_at=NOW, order_allowed=False, roles=[],
            candidates=[dict(opportunity_id='1'*64, symbol='000001', name='종목 000001',
                state='Watch', audit=dict(status='passed', independent_sources=2, reasons=[]),
                probability=dict(kind='unavailable', bull=None, base=None, bear=None,
                    reason='calibration_pending'),
                invalidation=dict(price_below=90., price_above=100.,
                    valid_until='2026-10-08T06:30:00Z', detail=''), missing=[])],
            promotion=dict(stage='M0', reasons=['predeclared_oos_pending',
                'calibration_pending', 'manual_approval_required'])))


def test_m0_unknown_forecast_can_calculate_reference_quantity_without_strategy_approval():
    result = risk().build_account_plan(status(), account(), now=NOW)
    assert result['status'] == 'ready'
    assert result['order_allowed'] is False
    assert {'strategy_promotion_held', 'forecast_unavailable'} <= set(result['reasons'])
    assert result['plans'][0]['quantity'] == 500
    assert result['plans'][0]['budget'] == 50_000
    assert result['plans'][0]['entry_price'] == 100
    assert set(result) == {'schema_version', 'policy_version', 'status', 'reasons',
                           'generated_at', 'valid_until', 'order_allowed', 'limits', 'plans'}
    assert set(result['plans'][0]) == {'opportunity_id', 'symbol', 'name', 'status', 'reasons',
        'quantity', 'weight', 'budget', 'planned_loss', 'entry_price', 'stop_price', 'target_price'}
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('field', ['equity', 'available_cash', 'daily_pnl', 'weekly_pnl',
                                  'positions_confirmed', 'positions'])
def test_missing_account_values_are_held_without_implicit_zero(field):
    values = account()
    values.pop(field)
    result = risk().build_account_plan(status(), values, now=NOW)
    assert result['status'] == 'held'
    assert 'account_'+field+'_required' in result['reasons']
    assert all(row['quantity'] is None for row in result['plans'])


@pytest.mark.parametrize(('field', 'value'), [('equity', True), ('equity', 0),
    ('equity', -1), ('equity', 10**500), ('equity', 2**53), ('available_cash', float('nan')),
    ('available_cash', -1), ('available_cash', 1_000_001), ('daily_pnl', False),
    ('daily_pnl', float('inf')), ('daily_pnl', -(2**53)), ('weekly_pnl', '0'), ('weekly_pnl', None),
    ('positions_confirmed', 1)])
def test_invalid_account_numbers_do_not_become_balances(field, value):
    values = account()
    values[field] = value
    result = risk().build_account_plan(status(), values, now=NOW)
    assert result['status'] == 'held'
    assert any(reason.startswith('account_') for reason in result['reasons'])
    assert result['plans'][0]['quantity'] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('positions', [None, {}, [None],
    [dict(symbol='000002', theme='반도체', market_value=True)],
    [dict(symbol='000002', theme='반도체', market_value=float('nan'))],
    [dict(symbol='000002', theme='반도체', market_value=-1)],
    [dict(symbol='000002', theme='반도체', market_value=0)],
    [dict(symbol='000002', market_value=100)],
    [dict(symbol='000002', theme=' ', market_value=100)],
    [dict(symbol='000000', theme='반도체', market_value=100)],
    [dict(symbol='000002', theme='반도체', market_value=100, entry_price=1)],
    [dict(symbol='000002', theme='반도체', market_value=100)]*2])
def test_invalid_holdings_do_not_claim_confirmed_portfolio(positions):
    values = account()
    values['available_cash'] = 800_000
    values['positions'] = positions
    result = risk().build_account_plan(status(), values, now=NOW)
    assert result['status'] == 'held'
    assert 'account_positions_invalid' in result['reasons']
    assert result['plans'][0]['quantity'] is None


@pytest.mark.parametrize(('field', 'value', 'reason'), [
    ('daily_pnl', -15_000., 'daily_loss_limit'),
    ('daily_pnl', -15_001., 'daily_loss_limit'),
    ('weekly_pnl', -40_000., 'weekly_loss_limit'),
    ('weekly_pnl', -40_001., 'weekly_loss_limit')])
def test_loss_stop_equality_halts_all_plans(field, value, reason):
    values = account()
    values[field] = value
    result = risk().build_account_plan(status(), values, now=NOW)
    assert result['status'] == 'halt'
    assert reason in result['reasons']
    assert all(row['status'] == 'halt' and row['quantity'] is None for row in result['plans'])


@pytest.mark.parametrize('mutation', ['expired_board', 'expired_candidate', 'expired_desk',
    'stale_quote', 'future_quote', 'future_fetch', 'future_desk', 'action', 'board_held',
    'mismatched_symbol', 'mismatched_identity', 'missing_quote', 'audit_held',
    'missing_flow_fx', 'missing_theme', 'unknown_theme', 'unapproved_promotion'])
def test_current_server_identity_evidence_and_expiry_are_required(mutation):
    source = status()
    row = source['opportunity_engine']['candidates'][0]
    desk = source['agent_desk']['candidates'][0]
    if mutation == 'expired_board': source['opportunity_engine']['valid_until'] = NOW
    elif mutation == 'expired_candidate': row['valid_until'] = NOW
    elif mutation == 'expired_desk': desk['invalidation']['valid_until'] = NOW
    elif mutation == 'stale_quote': row['quote_at'] = '2026-10-08T00:57:59Z'
    elif mutation == 'future_quote': row['quote_at'] = '2026-10-08T01:05:01Z'
    elif mutation == 'future_fetch': row['fetched_at'] = '2026-10-08T01:05:01Z'
    elif mutation == 'future_desk': source['agent_desk']['generated_at'] = '2026-10-08T01:05:01Z'
    elif mutation == 'action': row['action'] = 'wait_next_session'
    elif mutation == 'board_held': source['opportunity_engine']['status'] = 'held'
    elif mutation == 'mismatched_symbol': desk['symbol'] = '999999'
    elif mutation == 'mismatched_identity': row['decision_id'] = 'f'*64
    elif mutation == 'missing_quote': row['current_price'] = None
    elif mutation == 'audit_held': desk['audit']['status'] = 'held'
    elif mutation == 'missing_flow_fx': desk['missing'] = ['foreign_flow', 'fx']
    elif mutation == 'missing_theme': source['report']['buy_candidates'][0].pop('theme')
    elif mutation == 'unknown_theme': source['report']['buy_candidates'][0]['theme'] = 'unknown'
    else: source['agent_desk']['promotion'] = dict(stage='M3', reasons=[])
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == ('halt' if mutation == 'missing_flow_fx' else 'held')
    assert result['plans'][0]['quantity'] is None
    assert result['plans'][0]['reasons']


def test_no_trusted_theme_is_not_inferred_from_caller_holdings_or_candidate_name():
    source = status()
    source['report'] = {}
    source['opportunity_engine']['candidates'][0]['name'] = '반도체 대표주'
    values = account()
    values.update(available_cash=950_000, positions=[dict(symbol='000001', theme='반도체', market_value=50_000)])
    result = risk().build_account_plan(source, values, now=NOW)
    assert 'theme_unavailable' in result['plans'][0]['reasons']
    assert result['plans'][0]['quantity'] is None


def test_unknown_caller_fields_cannot_supply_price_or_source_evidence():
    values = account()
    values.update(entry_price=1, theme='반도체', evidence={'audit': 'passed'})
    result = risk().build_account_plan(status(), values, now=NOW)
    assert 'account_unknown_fields' in result['reasons']
    assert result['plans'][0]['entry_price'] == 100
    assert result['plans'][0]['quantity'] is None


def test_contract_is_pure_and_exposes_no_account_snapshot():
    source, values = status(), account()
    before = deepcopy((source, values))
    result = risk().build_account_plan(source, values, now=NOW)
    assert (source, values) == before
    assert 'equity' not in result and 'positions' not in result
    result['plans'][0]['reasons'].append('caller_mutation')
    assert (source, values) == before


def test_public_top_three_share_holdings_theme_cash_and_position_limits():
    source, values = status(), account()
    first = deepcopy(source['agent_desk']['candidates'][0])
    rows = [candidate(), candidate('000002', '2'*64), candidate('000003', '3'*64)]
    source['opportunity_engine']['candidates'] = rows
    source['agent_desk']['candidates'] = []
    for row in rows:
        desk = deepcopy(first)
        desk.update({key: row[key] for key in ('opportunity_id', 'symbol', 'name')})
        source['agent_desk']['candidates'].append(desk)
    source['report']['buy_candidates'] = [dict(symbol='000001', theme='반도체'),
        dict(symbol='000002', theme='반도체'), dict(symbol='000003', theme='바이오')]
    values.update(available_cash=410_050, positions=[
        dict(symbol='000099', theme='반도체', market_value=295_000)])
    result = risk().build_account_plan(source, values, now=NOW)
    assert [row['quantity'] for row in result['plans']] == [50, None, 50]
    assert sum(row['budget'] for row in result['plans']) == 10_000
    assert result['valid_until'] == '2026-10-08T01:11:30Z'
    assert result['order_allowed'] is False


@pytest.mark.parametrize('mutation', ['fabricated_probability', 'forecast_kind',
    'exit_state', 'unknown_state', 'missing_probability', 'missing_expiry',
    'quote_exact_expiry', 'quote_closed_market', 'quote_reference_changed',
    'missing_identity', 'missing_opportunity_id', 'missing_schema', 'bool_schema',
    'missing_missing_list', 'missing_promotion'])
def test_invalid_server_contract_cannot_expose_reference_quantity(mutation):
    source = status()
    board, desk = source['opportunity_engine'], source['agent_desk']
    row, agent = board['candidates'][0], desk['candidates'][0]
    if mutation == 'fabricated_probability': agent['probability']['bull'] = .9
    elif mutation == 'forecast_kind': agent['probability']['kind'] = 'calibrated'
    elif mutation == 'exit_state': agent['state'] = 'Exit review'
    elif mutation == 'unknown_state': agent['state'] = 'Ready'
    elif mutation == 'missing_probability': agent.pop('probability')
    elif mutation == 'missing_expiry': row.pop('valid_until')
    elif mutation == 'quote_exact_expiry': row['quote_at'] = '2026-10-08T00:58:00Z'
    elif mutation == 'quote_closed_market': row['quote_at'] = '2026-10-07T23:59:00Z'
    elif mutation == 'quote_reference_changed': row['plan']['entry_low'] = 95
    elif mutation == 'missing_identity':
        for key in ('decision_id', 'input_fingerprint', 'source_audit_hash'):
            row.pop(key)
            board.pop(key)
    elif mutation == 'missing_opportunity_id':
        row.pop('opportunity_id')
        agent.pop('opportunity_id')
    elif mutation == 'missing_schema': desk.pop('schema_version')
    elif mutation == 'bool_schema': board['schema_version'] = True
    elif mutation == 'missing_missing_list': agent.pop('missing')
    else: desk.pop('promotion')
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'held'
    assert result['plans'][0]['quantity'] is None


def test_positions_and_cash_cannot_exceed_equity_even_with_tiny_positive_holding():
    values = account()
    values['positions'] = [dict(symbol='000099', theme='반도체', market_value=1e-300)]
    result = risk().build_account_plan(status(), values, now=NOW)
    assert result['status'] == 'held'
    assert 'account_exposure_inconsistent' in result['reasons']


def test_portfolio_already_over_three_stocks_cannot_add_to_a_current_stock():
    values = account()
    values.update(available_cash=900_000, positions=[
        dict(symbol=symbol, theme='반도체', market_value=10_000)
        for symbol in ('000001', '000002', '000003', '000004')])
    result = risk().build_account_plan(status(), values, now=NOW)
    assert result['status'] == 'held'
    assert 'position_limit_reached' in result['plans'][0]['reasons']


def test_holding_theme_disagreement_does_not_approve_an_optimistic_exposure():
    values = account()
    values.update(available_cash=990_000, positions=[
        dict(symbol='000001', theme='바이오', market_value=10_000)])
    result = risk().build_account_plan(status(), values, now=NOW)
    assert result['status'] == 'held'
    assert 'holding_theme_mismatch' in result['plans'][0]['reasons']


@pytest.mark.parametrize(('field', 'value'), [('symbol', []), ('symbol', {}), ('name', None),
    ('opportunity_id', []), ('plan', []), ('current_price', True), ('audit', None)])
def test_malformed_saved_candidates_are_held_instead_of_crashing_or_sizing(field, value):
    source = status()
    source['opportunity_engine']['candidates'][0][field] = value
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'held'
    assert result['plans'][0]['quantity'] is None
    json.dumps(result, allow_nan=False)


def test_public_no_server_opportunities_produces_bounded_held_contract():
    result = risk().build_account_plan({}, account(), now=NOW)
    assert result['status'] == 'held'
    assert result['plans'] == []
    assert result['valid_until'] is None
    assert result['order_allowed'] is False


@pytest.mark.parametrize(('field', 'value'), [('price_below', 89), ('price_below', None),
    ('price_above', 101), ('price_above', True)])
def test_agent_invalidation_must_bind_exactly_to_server_stop_and_max_entry(field, value):
    source = status()
    source['agent_desk']['candidates'][0]['invalidation'][field] = value
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'held'
    assert 'invalidation_identity_mismatch' in result['plans'][0]['reasons']


def test_quantity_beyond_browser_safe_integer_is_held_instead_of_overflowing():
    source = status()
    row, agent = source['opportunity_engine']['candidates'][0], source['agent_desk']['candidates'][0]
    row.update(current_price=1e-20,
        plan=dict(basis='observed_quote_reference', entry_low=1e-20, entry_high=1e-20,
                  stop_price=9e-21, target_price=1.2e-20))
    agent['invalidation'].update(price_below=9e-21, price_above=1e-20)
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'held'
    assert result['plans'][0]['quantity'] is None
    assert 'quantity_not_representable' in result['plans'][0]['reasons']
    json.dumps(result, allow_nan=False)


def test_account_plan_expires_at_the_earliest_desk_or_quote_deadline():
    source = status()
    source['agent_desk']['generated_at'] = '2026-10-08T00:58:20Z'
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'ready'
    assert result['valid_until'] == '2026-10-08T01:05:20Z'


def _real_agent_status(*, include_fx=False):
    source = status()
    row = source['opportunity_engine']['candidates'][0]
    identity = dict(decision_id=row['decision_id'], symbol=row['symbol'], strategy_id=row['strategy_id'])
    row['opportunity_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    source['opportunity_engine']['generated_at'] = '2026-10-08T01:00:00Z'
    records = []
    for claim in ('direction', 'risk'):
        for lineage in ('exchange', 'filing'):
            records.append(dict(symbol=row['symbol'], opportunity_id=row['opportunity_id'],
                role='disclosure', claim_id=claim, core=True, kind='market', source_grade='A',
                lineage_id=lineage, origin_ids=[lineage], source=lineage,
                source_at='2026-10-08T00:50:00Z', available_at='2026-10-08T00:51:00Z',
                fetched_at='2026-10-08T00:55:00Z', valid_until='2026-10-08T06:30:00Z',
                status='ready', confidence=.8))
    if include_fx:
        record = deepcopy(records[0])
        record.update(role='fx_liquidity', claim_id='fx', core=False,
                      lineage_id='fx-provider', origin_ids=['fx-provider'], source='fx-provider')
        records.append(record)
    contract = importlib.import_module('app.services.mirofish.alpha_lab.decision_contract')
    source['agent_desk'] = contract.build_agent_desk(source, now=NOW, evidence={row['symbol']: records})
    return source


def test_real_agent_desk_missing_fx_and_foreign_flow_halts_every_new_plan():
    source = _real_agent_status()
    audit = source['agent_desk']['candidates'][0]['audit']
    assert audit['independent_sources'] == 2
    assert 'fx_and_flow_missing' in audit['reasons']
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'halt'
    assert 'flow_and_fx_unavailable' in result['reasons']
    assert all(row['status'] == 'halt' and row['quantity'] is None for row in result['plans'])


def test_real_agent_desk_with_passed_sources_calculates_research_quantity_only():
    source = _real_agent_status(include_fx=True)
    assert source['agent_desk']['candidates'][0]['audit']['status'] == 'passed'
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'ready'
    assert result['plans'][0]['quantity'] == 500
    assert source['agent_desk']['promotion']['stage'] == 'M0'
    assert result['order_allowed'] is False


def test_any_top_three_candidate_missing_flow_fx_halts_other_ready_candidates():
    source = status()
    source['opportunity_engine']['candidates'].append(candidate('000002', '2'*64))
    other = deepcopy(source['agent_desk']['candidates'][0])
    other.update(opportunity_id='2'*64, symbol='000002', name='종목 000002',
                 missing=['fx_liquidity', 'flow'])
    source['agent_desk']['candidates'].append(other)
    source['report']['buy_candidates'].append(dict(symbol='000002', theme='바이오'))
    result = risk().build_account_plan(source, account(), now=NOW)
    assert result['status'] == 'halt'
    assert [row['quantity'] for row in result['plans']] == [None, None]
    assert [row['status'] for row in result['plans']] == ['halt', 'halt']


def test_private_allocator_floors_500_shares_at_reference_and_half_percent_risk_cap():
    # 5% of 1M buys 500 at 100; 500*(100-90) is exactly the 5,000 risk cap.
    result = risk()._allocate_plans([candidate()], account(), {'000001': '반도체'})
    assert result[0]['status'] == 'ready'
    assert result[0]['quantity'] == 500
    assert result[0]['weight'] == .05
    assert result[0]['budget'] == 50_000
    assert result[0]['planned_loss'] == 5_000


def test_private_allocator_preserves_quarter_kelly_and_uses_maximum_entry_price():
    row = candidate(reference_weight=.08,
        kelly=dict(raw_fraction=.04, fraction=.25, cap=.05, account_risk_cap=.01),
        plan=dict(entry_low=95., entry_high=100., stop_price=90., target_price=120.))
    result = risk()._allocate_plans([row], account(), {'000001': '반도체'})
    assert result[0]['entry_price'] == 100
    assert result[0]['quantity'] == 100  # quarter Kelly .01 => 10,000 budget.
    assert result[0]['budget'] == 10_000
    assert result[0]['planned_loss'] == 1_000


def test_private_allocator_reduces_quantity_when_stop_distance_dominates():
    row = candidate(plan=dict(entry_low=100., entry_high=100., stop_price=80., target_price=140.))
    result = risk()._allocate_plans([row], account(), {'000001': '반도체'})
    assert result[0]['quantity'] == 250  # 5,000 / 20 loss per share.
    assert result[0]['budget'] == 25_000
    assert result[0]['planned_loss'] == 5_000


def test_private_allocator_consumes_same_theme_and_cash_jointly_across_top_three():
    values = account()
    values.update(available_cash=600_000, positions=[
        dict(symbol='000099', theme='반도체', market_value=275_000)])
    rows = [candidate(), candidate('000002', '2'*64), candidate('000003', '3'*64)]
    result = risk()._allocate_plans(rows, values,
        {'000001': '반도체', '000002': '반도체', '000003': '바이오'})
    assert [row['quantity'] for row in result] == [250, None, 500]
    assert result[1]['reasons'] == ['theme_cap_reached']
    assert sum(row['budget'] for row in result) == 75_000


def test_private_allocator_shared_cash_budget_preserves_40_percent_floor():
    values = account()
    values['available_cash'] = 420_050
    rows = [candidate(), candidate('000002', '2'*64), candidate('000003', '3'*64)]
    result = risk()._allocate_plans(rows, values,
        {'000001': '반도체', '000002': '바이오', '000003': '전력'})
    assert [row['quantity'] for row in result] == [200, None, None]
    assert result[0]['budget'] == 20_000  # 20,050 available beyond the cash floor.
    assert values['available_cash'] - sum(row['budget'] for row in result) == 400_050


def test_private_allocator_current_positions_and_symbol_exposure_consume_caps():
    values = account()
    values.update(available_cash=850_000, positions=[
        dict(symbol='000001', theme='반도체', market_value=49_950),
        dict(symbol='000090', theme='바이오', market_value=50_000),
        dict(symbol='000099', theme='전력', market_value=50_000)])
    result = risk()._allocate_plans([candidate(), candidate('000002', '2'*64)], values,
        {'000001': '반도체', '000002': '반도체'})
    assert [row['quantity'] for row in result] == [None, None]
    assert 'minimum_quantity_unavailable' in result[0]['reasons']
    assert 'position_limit_reached' in result[1]['reasons']


def test_private_allocator_new_positions_exhaust_three_stock_limit():
    values = account()
    values.update(available_cash=900_000, positions=[
        dict(symbol='000090', theme='바이오', market_value=50_000),
        dict(symbol='000099', theme='전력', market_value=50_000)])
    result = risk()._allocate_plans([candidate(), candidate('000002', '2'*64)], values,
        {'000001': '반도체', '000002': '반도체'})
    assert [row['quantity'] for row in result] == [500, None]
    assert result[1]['reasons'] == ['position_limit_reached']
