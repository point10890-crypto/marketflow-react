"""Prospective fixed-arm experiments; fixtures are never profitability evidence."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import importlib
import json
import math

import pytest


def engine():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.evolution')
    except ModuleNotFoundError:
        pytest.fail('the fixed prospective evolution engine is not implemented')


def phase(values, start, end):
    first = date.fromisoformat(start)
    trades = [dict(status='closed', signal_date=(first+timedelta(days=3*i)).isoformat(),
                   entry_date=(first+timedelta(days=3*i+1)).isoformat(),
                   exit_date=(first+timedelta(days=3*i+2)).isoformat(),
                   net_return=value+.004, stress_net_return=value)
              for i, value in enumerate(values)]
    return dict(summary=dict(start=start, end=end, samples=len(trades)), trades=trades)


def fixture():
    first = date(2026, 8, 4)
    prices, raw, audits = {}, [], []
    for index in range(1, 6):
        symbol = f'{index:06d}'
        values = [100.*(1+.01*math.sin(i*(.5 if index < 4 else .8))) for i in range(71)]
        values[-2:] = [99., 100.]
        prices[symbol] = [dict(symbol=symbol, date=(first+timedelta(days=i)).isoformat(),
                              open=c-.1, high=c+1., low=c-1., close=c, volume=1000.)
                          for i, c in enumerate(values)]
        calibration = phase([.05-index*.002, -.006]*20, '2022-01-03', '2025-01-02')
        confirmation = phase([.025, -.006]*6, '2025-01-03', '2026-10-13')
        raw.append(dict(symbol=symbol, name='시험'+symbol, strategy_id='momentum', setup_active=True,
                        last_close=100., quote_session='2026-10-13',
                        plan=dict(status='ready', entry_price=100., stop_price=92., target_price=116.,
                                  atr=4., loss_fraction=.08, gain_fraction=.16),
                        evidence=dict(retrospective=True, independent_validation=False)))
        audits.append(dict(symbol=symbol, strategy_id='momentum', selected=True, eligible=True,
                           calibration=calibration, confirmation=confirmation))
    discovery = dict(policy_version='quality-setup-opportunity-v1',
                     selection_basis='calibration_stress_mean_then_confirmation',
                     latest_session='2026-10-13', inspected_count=5, eligible_count=5,
                     candidates=raw, audit=audits, horizon_sessions=10, cost_stress_multiplier=2.)
    provenance = dict(price_source='KIS', captured_at='2026-10-13T11:35:00Z',
                      source_hash='c'*64, manifest_hash='d'*64, scope_hash='e'*64,
                      historical_vintage_verified=False, point_in_time_universe_verified=False,
                      price_adjustment_verified=False, current_cohort_bias=True, analysis_ready=False)
    report = dict(schema_version=1, mode='research', latest_session='2026-10-13',
                  decision_at='2026-10-13T11:40:00Z', input_fingerprint='a'*64,
                  provenance=provenance, universe=dict(scope_date='2026-10-13'), diagnostics={},
                  opportunity_scan=dict(status='ready', audit_hash='b'*64, reasons=[]))
    ranking = importlib.import_module('app.services.mirofish.alpha_lab.decision_engine')
    report['opportunity_board'] = ranking.build_opportunity_board(discovery, prices, report,
                                                                 now=report['decision_at'])
    inputs = dict(status='ready', latest_session='2026-10-13', prices_by_symbol=prices,
                  names={symbol:'시험'+symbol for symbol in prices}, provenance=provenance,
                  universe=dict(scope_date='2026-10-13', quality_count=5), input_fingerprint='a'*64,
                  capture_audit={symbol:dict(first='2026-10-13T11:31:00Z', last='2026-10-13T11:35:00Z') for symbol in prices})
    return inputs, report, discovery


def protocol():
    return dict(engine().protocol_spec(), declared_at='2026-10-12T11:00:00Z')


def cohort():
    inputs, report, discovery = fixture()
    return engine().build_cohort(inputs, report, discovery, protocol=protocol(),
                                 now='2026-10-13T11:40:00Z')


def arm(value, identifier):
    return next(row for row in value['arms'] if row['id'] == identifier)


def observation_arm(value, identifier):
    return arm(value['observation'], identifier)


def future_prices(opening=100., *, count=10, winner=False):
    prices = deepcopy(fixture()[0]['prices_by_symbol'])
    for symbol in prices:
        for offset in range(count):
            day = (date(2026, 10, 14)+timedelta(days=offset)).isoformat()
            # The synthetic calendar is explicit observed rows, not weekday inference.
            prices[symbol].append(dict(symbol=symbol, date=day, open=opening,
                high=opening+(17. if winner and offset == 0 else 1.), low=opening-1.,
                close=opening, volume=1000.))
    return prices


def test_fixed_manifest_drives_four_arms_same_fills_and_doubled_costs():
    spec = engine().protocol_spec()
    assert [row['id'] for row in spec['arms']] == [
        'control', 'entry-band-v1', 'recovery-confirmed-v1', 'positive-rank-v1']
    observed = engine().observe_cohort(cohort(), future_prices(winner=True, count=1),
                                       now='2026-10-14T11:30:00Z')
    result = observation_arm(observed, 'control')['slots'][0]
    assert result['entry_price'] == 100.
    # ATR from the closed prefix is independently bounded to the original 8% stop cap.
    assert result['exit_price'] == pytest.approx(result['target_price'])
    assert result['net_return'] == pytest.approx(result['exit_price']*.997/100.1-1)
    assert result['stress_net_return'] == pytest.approx(result['exit_price']*.994/100.2-1)
    assert result['stress_net_return'] < result['net_return']
    assert spec['live_orders'] is False and spec['approved_exposure'] == 0
    json.dumps(observed, allow_nan=False)


def test_recovery_filters_closed_candle_and_strict_breakout_then_refills_from_pool():
    inputs, report, discovery = fixture()
    selected = [row['symbol'] for row in report['opportunity_board']['candidates']]
    first, second = selected[:2]
    inputs['prices_by_symbol'][first][-1]['open'] = 100.5  # red candle
    inputs['prices_by_symbol'][second][-1]['close'] = 99.  # no close recovery
    breakout = next(symbol for symbol in ('000002', '000003', '000004') if symbol not in {first, second})
    raw = next(row for row in discovery['candidates'] if row['symbol'] == breakout)
    raw['strategy_id'] = 'liquidity_breakout'
    next(row for row in discovery['audit'] if row['symbol'] == breakout)['strategy_id'] = 'liquidity_breakout'
    built = engine().build_cohort(inputs, report, discovery, protocol=protocol(),
                                  now=report['decision_at'])
    recovery = arm(built, 'recovery-confirmed-v1')
    assert '000005' in [row['symbol'] for row in recovery['selections']]
    assert set(row['symbol'] for row in recovery['selections']).isdisjoint({first, second, breakout})
    assert any(row['reason'] == 'breakout_not_cleared' for row in recovery['rejections'])
    assert [row['symbol'] for row in arm(built, 'control')['selections']] == selected


def test_nonpositive_final_rank_preserves_three_explicit_cash_slots():
    inputs, report, discovery = fixture()
    for row in discovery['audit']:
        row['calibration'] = phase([.19, -.11]*15, '2022-01-03', '2025-01-02')
    ranking = importlib.import_module('app.services.mirofish.alpha_lab.decision_engine')
    report['opportunity_board'] = ranking.build_opportunity_board(discovery, inputs['prices_by_symbol'], report,
                                                                 now=report['decision_at'])
    built = engine().build_cohort(inputs, report, discovery, protocol=protocol(), now=report['decision_at'])
    assert len(arm(built, 'control')['selections']) == 3
    assert arm(built, 'positive-rank-v1')['selections'] == []
    slots = observation_arm(built, 'positive-rank-v1')['slots']
    assert len(slots) == 3 and all(row['status'] == 'cash' and row['net_return'] == 0 for row in slots)


def test_positive_rank_applies_penalty_before_skip_and_reaches_fourth_pool_symbol():
    inputs, report, discovery = fixture()
    values = {'000001':.04, '000002':.038, '000003':.036, '000004':.035, '000005':.034}
    for row in discovery['audit']:
        row['calibration'] = phase([values[row['symbol']], -.006]*20, '2022-01-03', '2025-01-02')
    built = engine().build_cohort(inputs, report, discovery, protocol=protocol(), now=report['decision_at'])
    positive = arm(built, 'positive-rank-v1')
    assert [row['symbol'] for row in positive['selections']] == ['000001', '000004']
    assert any(row['symbol'] == '000002' and row['score'] < 0 for row in positive['rejections'])
    assert all(row['ranking']['score'] > 0 for row in positive['selections'])
    assert observation_arm(built, 'positive-rank-v1')['slots'][2]['status'] == 'cash'


def test_future_rows_never_affect_frozen_64_bar_all_quality_prefixes():
    inputs, report, discovery = fixture()
    expected = engine().build_cohort(inputs, report, discovery, protocol=protocol(), now=report['decision_at'])
    for rows in inputs['prices_by_symbol'].values():
        rows.append(dict(date='2026-10-14', close=float('nan')))
    actual = engine().build_cohort(inputs, report, discovery, protocol=protocol(), now=report['decision_at'])
    assert actual == expected
    assert set(actual['frozen_prices']) == {'000001','000002','000003','000004','000005'}
    assert all(len(rows) == 64 and rows[-1]['date'] == '2026-10-13' for rows in actual['frozen_prices'].values())


@pytest.mark.parametrize('failure', ['predeclaration', 'late_source', 'nonfinite', 'unbound'])
def test_old_future_or_unbound_decisions_cannot_enroll(failure):
    inputs, report, discovery = fixture()
    spec = protocol()
    if failure == 'predeclaration':
        spec['declared_at'] = report['decision_at']
    elif failure == 'late_source':
        report['decision_at'] = '2026-10-14T11:30:00Z'
        report['opportunity_board']['generated_at'] = report['decision_at']
        report['opportunity_board']['origin_at'] = report['decision_at']
    elif failure == 'nonfinite':
        inputs['prices_by_symbol']['000005'][-2]['volume'] = float('inf')
    else:
        report['opportunity_board']['input_fingerprint'] = 'f'*64
    with pytest.raises(ValueError):
        engine().build_cohort(inputs, report, discovery, protocol=spec, now=report['decision_at'])


@pytest.mark.parametrize('capture', ['2026-10-13T11:29:59Z', '2026-10-13T11:41:00Z', '2026-10-13T20:35:00'])
def test_capture_before_2030_buffer_future_or_without_timezone_cannot_enroll(capture):
    inputs, report, discovery = fixture()
    inputs['provenance']['captured_at'] = capture
    with pytest.raises(ValueError):
        engine().build_cohort(inputs, report, discovery, protocol=protocol(), now=report['decision_at'])


@pytest.mark.parametrize('location', ['symbol_manifest', 'latest_bar'])
def test_explicit_symbol_capture_cannot_be_hidden_by_later_global_capture(location):
    inputs, report, discovery = fixture()
    if location == 'symbol_manifest':
        inputs['provenance']['captured_at_by_symbol'] = {symbol:'2026-10-13T11:35:00Z' for symbol in inputs['names']}
        inputs['provenance']['captured_at_by_symbol']['000005'] = '2026-10-13T11:29:59Z'
    else:
        inputs['prices_by_symbol']['000005'][-1]['captured_at'] = '2026-10-13T11:41:00Z'
    with pytest.raises(ValueError):
        engine().build_cohort(inputs, report, discovery, protocol=protocol(), now=report['decision_at'])


@pytest.mark.parametrize('failure', ['early_first', 'late_last', 'missing_symbol', 'naive_first'])
def test_capture_audit_covers_every_quality_symbol_in_the_same_frozen_buffer(failure):
    inputs, report, discovery = fixture()
    if failure == 'early_first':
        inputs['capture_audit']['000005']['first'] = '2026-10-13T11:29:59Z'
    elif failure == 'late_last':
        inputs['capture_audit']['000005']['last'] = '2026-10-13T11:41:00Z'
    elif failure == 'missing_symbol':
        inputs['capture_audit'].pop('000005')
    else:
        inputs['capture_audit']['000005']['first'] = '2026-10-13T20:31:00'
    with pytest.raises(ValueError):
        engine().build_cohort(inputs, report, discovery, protocol=protocol(), now=report['decision_at'])


@pytest.mark.parametrize('opening', [99., 103.])
def test_lower_band_and_gap_skip_first_next_open_without_later_retry(opening):
    built = cohort()
    observed = engine().observe_cohort(built, future_prices(opening, count=2), now='2026-10-15T11:30:00Z')
    skipped = observation_arm(observed, 'entry-band-v1')['slots'][0]
    assert skipped['status'] == 'skipped' and skipped['net_return'] == skipped['stress_net_return'] == 0
    assert skipped['entry_date'] is None
    assert skipped['reason'] == 'next_open_outside_frozen_band'
    assert observation_arm(observed, 'control')['slots'][0]['entry_date'] == '2026-10-14'


@pytest.mark.parametrize('missing', [True, False])
def test_union_session_missing_or_zero_volume_entry_is_cash_not_delayed(missing):
    built = cohort()
    symbol = arm(built, 'control')['selections'][0]['symbol']
    prices = future_prices(count=2)
    if missing:
        prices[symbol] = [row for row in prices[symbol] if row['date'] != '2026-10-14']
    else:
        prices[symbol][-2]['volume'] = 0.
    observed = engine().observe_cohort(built, prices, now='2026-10-15T11:30:00Z')
    result = observation_arm(observed, 'control')['slots'][0]
    assert result['status'] == 'unfilled' and result['net_return'] == 0
    assert result['entry_date'] is None
    assert result['next_session'] == '2026-10-14'


def test_current_canonical_union_calendar_includes_new_quality_symbols():
    built = cohort()
    prices = deepcopy(fixture()[0]['prices_by_symbol'])
    prices['000006'] = [dict(symbol='000006',date='2026-10-14',open=100.,high=101.,low=99.,close=100.,volume=1000.)]
    observed = engine().observe_cohort(built,prices,now='2026-10-14T11:30:00Z')
    result = observation_arm(observed,'control')['slots'][0]
    assert result['status'] == 'unfilled'
    assert result['next_session'] == '2026-10-14'


def test_current_intraday_candle_cannot_enter_or_resolve_horizon():
    built = cohort()
    intraday = engine().observe_cohort(built, future_prices(count=1, winner=True), now='2026-10-14T03:00:00Z')
    assert observation_arm(intraday, 'control')['slots'][0]['status'] == 'pending'
    nine = engine().observe_cohort(built, future_prices(count=10), now='2026-10-23T03:00:00Z')
    assert observation_arm(nine, 'control')['slots'][0]['status'] == 'open'
    closed = engine().observe_cohort(nine, future_prices(count=10), now='2026-10-23T11:30:00Z')
    assert observation_arm(closed, 'control')['slots'][0]['exit_reason'] == 'time'
    assert observation_arm(closed, 'control')['slots'][0]['holding_sessions'] == 10


def test_stop_first_ambiguity_and_missing_holding_quote_cannot_be_wins():
    built = cohort()
    prices = future_prices(count=10)
    symbol = arm(built, 'control')['selections'][0]['symbol']
    prices[symbol][-10].update(high=125., low=80.)
    observed = engine().observe_cohort(built, prices, now='2026-10-23T11:30:00Z')
    result = observation_arm(observed, 'control')['slots'][0]
    assert result['exit_reason'] == 'stop' and result['ambiguous_bar'] is True
    assert result['net_return'] < 0
    prices = future_prices(count=10)
    prices[symbol] = [row for row in prices[symbol] if row['date'] != '2026-10-18']
    missing = engine().observe_cohort(built, prices, now='2026-10-23T11:30:00Z')
    assert observation_arm(missing, 'control')['slots'][0]['status'] == 'missing'
    assert observation_arm(missing, 'control')['slots'][0]['net_return'] is None


def test_terminal_bodies_are_sealed_while_numeric_and_calendar_revisions_are_audited():
    built = cohort()
    prices = future_prices(103., count=1, winner=True)
    observed = engine().observe_cohort(built, prices, now='2026-10-14T11:30:00Z')
    before = deepcopy(observed)
    prices['000001'][-1]['volume'] += 100.
    prices['000005'][-2]['high'] += .5
    revised = engine().observe_cohort(observed, prices, now='2026-10-15T11:30:00Z')
    assert observed == before
    for identifier in ('control', 'entry-band-v1'):
        assert observation_arm(revised, identifier)['slots'] == observation_arm(before, identifier)['slots']
    assert revised['observation']['revision_evidence']
    status = engine().summarize(protocol(), [revised])
    assert arm(status, 'entry-band-v1')['counts']['paired_sessions'] == 0
    assert arm(status, 'entry-band-v1')['metrics']['mean_net_return'] is None


def test_later_calendar_removal_is_revision_not_a_new_entry_or_terminal_rewrite():
    built = cohort()
    prices = future_prices(103., count=2, winner=True)
    first = engine().observe_cohort(built, prices, now='2026-10-15T11:30:00Z')
    for symbol in prices:
        prices[symbol] = [row for row in prices[symbol] if row['date'] != '2026-10-14']
    later = engine().observe_cohort(first, prices, now='2026-10-16T11:30:00Z')
    assert observation_arm(first, 'entry-band-v1')['slots'] == observation_arm(later, 'entry-band-v1')['slots']
    assert later['observation']['calendar'][0] == '2026-10-14'
    assert any(row['reason'] == 'observed_union_calendar_changed' for row in later['observation']['revision_evidence'])


def test_prices_after_ten_session_horizon_cannot_revise_past_results_or_grow_memory():
    built = cohort()
    prices = future_prices(count=11)
    first = engine().observe_cohort(built,prices,now='2026-10-24T11:30:00Z')
    assert len(first['observation']['calendar']) == 10
    assert all(len(rows) == 10 for rows in first['observation']['prices'].values())
    prices['000001'][-1]['volume'] = float('nan')
    later = engine().observe_cohort(first,prices,now='2026-10-25T11:30:00Z')
    assert later['observation']['revision_evidence'] == []
    assert observation_arm(first,'control')['slots'] == observation_arm(later,'control')['slots']


def summary_fixture(count=106, *, rejection=False, all_cash=False):
    base = cohort()
    cohorts = []
    for index in range(count):
        saved = deepcopy(base)
        day = (date(2026, 10, 13)+timedelta(days=index)).isoformat()
        saved['decision_session'] = saved['latest_session'] = day
        saved['decision_at'] = day+'T11:40:00Z'
        saved['provenance']['captured_at'] = day+'T11:35:00Z'
        saved['capture_audit'] = {symbol:dict(first=day+'T11:31:00Z',last=day+'T11:35:00Z') for symbol in saved['names']}
        saved['cohort_id'] = f'{index+1:064x}'
        saved['observation']['calendar'] = [(date.fromisoformat(day)+timedelta(days=i+1)).isoformat() for i in range(10)]
        saved['observation']['observed_at'] = saved['observation']['calendar'][-1]+'T11:30:00Z'
        for row in saved['observation']['arms']:
            normal = {'control':.01, 'entry-band-v1':.015, 'recovery-confirmed-v1':.03, 'positive-rank-v1':.02}[row['id']]
            if rejection and index >= 46:
                normal = -.04 if row['id'] == 'recovery-confirmed-v1' else .08 if row['id'] == 'positive-rank-v1' else normal
            row['slots'] = [dict(slot=slot, symbol=f'{slot:06d}' if not all_cash else None,
                                 name='검증', status='closed' if not all_cash else 'cash',
                                 reason=None, entry_date=(date.fromisoformat(day)+timedelta(days=1)).isoformat() if not all_cash else None,
                                 exit_date=(date.fromisoformat(day)+timedelta(days=10)).isoformat() if not all_cash else None,
                                 net_return=normal if not all_cash else 0.,
                                 stress_net_return=normal-.002 if not all_cash else 0.) for slot in range(1, 4)]
        cohorts.append(saved)
    return cohorts


def test_equal_slot_paired_cash_days_remain_zero_without_score_win_rates():
    values = summary_fixture(2, all_cash=True)
    status = engine().summarize(protocol(), values)
    for row in status['arms']:
        assert row['metrics']['mean_net_return'] == 0.
        assert row['counts']['paired_sessions'] == 2
        assert row['counts']['entered'] == 0 and row['counts']['cash'] == 6
    assert 'win_rate' not in json.dumps(status) and 'probability' not in json.dumps(status)
    assert status['review']['status'] == 'collecting'


def test_first_36_nominate_after_embargo_last_60_only_reject_and_never_replace():
    values = summary_fixture(rejection=True)
    status = engine().summarize(protocol(), values)
    assert status['nomination']['arm_id'] == 'recovery-confirmed-v1'
    assert status['review']['arm_id'] == 'recovery-confirmed-v1'
    assert status['review']['status'] == 'rejected'
    assert 'confirmation_nonpositive_paired_stress_advantage' in status['review']['reasons']
    assert status['phase'] == 'incumbent_retained'


def test_full_window_six_blocks_and_lower_bound_qualify_only_for_human_research_review():
    values = summary_fixture()
    status = engine().summarize(protocol(), values)
    assert status['window']['enrolled_sessions'] == status['window']['resolved_sessions'] == 106
    assert status['window']['confirmation_sessions'] == 60
    assert status['window']['embargo_sessions'] == 10
    assert status['nomination']['arm_id'] == 'recovery-confirmed-v1'
    assert status['review']['status'] == status['phase'] == 'awaiting_review'
    assert status['review']['block_lower_bound'] == pytest.approx(.02)
    assert status['review']['downside_tail_delta'] <= 0
    assert status['live_orders'] is False and status['approved_exposure'] == 0
    spec = dict(protocol(), nomination=deepcopy(status['nomination']))
    values[0]['observation']['revision_evidence'].append(dict(reason='source_bar_changed'))
    revised = engine().summarize(spec, values)
    assert revised['nomination']['arm_id'] == 'recovery-confirmed-v1'
    assert revised['review']['status'] == 'rejected'
    assert 'revised_coverage' in revised['review']['reasons']


def test_embargo_performance_cannot_nominate_or_improve_confirmation_bound():
    values = summary_fixture()
    for saved in values[36:46]:
        for slot in observation_arm(saved, 'positive-rank-v1')['slots']:
            slot.update(net_return=5., stress_net_return=4.)
    result = engine().summarize(protocol(), values)
    assert result['nomination']['arm_id'] == 'recovery-confirmed-v1'
    assert result['review']['normal_mean'] == pytest.approx(.03)
    assert result['review']['block_lower_bound'] == pytest.approx(.02)
    assert engine().summarize(protocol(), values[:40])['phase'] == 'embargo'


def test_nomination_deadline_and_fixed_maturation_deadline_never_extend():
    values = summary_fixture()
    observation_arm(values[0], 'entry-band-v1')['slots'][0].update(status='pending', net_return=None, stress_net_return=None)
    boundary = engine().summarize(protocol(), values[:46])
    assert boundary['nomination']['status'] == 'none'
    result = engine().summarize(protocol(), values)
    assert result['review']['status'] == 'rejected'
    assert result['window']['maturation_observed'] == 10
    assert 'no_fixed_nominated_challenger' in result['review']['reasons']


def test_unresolved_embargo_day_cannot_qualify_when_confirmation_is_complete():
    values = summary_fixture()
    observation_arm(values[40], 'entry-band-v1')['slots'][0].update(status='open',net_return=None,stress_net_return=None)
    result = engine().summarize(protocol(),values)
    assert result['review']['status'] == 'rejected'
    assert 'declared_window_coverage_unresolved' in result['review']['reasons']


def test_missing_pairs_and_insufficient_entered_outcomes_cannot_qualify():
    values = summary_fixture()
    observation_arm(values[-1], 'recovery-confirmed-v1')['slots'][0].update(status='open', net_return=None, stress_net_return=None)
    values[-1]['observation']['calendar'] = values[-1]['observation']['calendar'][:9]
    waiting = engine().summarize(protocol(), values)
    assert waiting['review']['status'] == 'collecting'
    assert waiting['phase'] == 'maturing'
    cash = engine().summarize(protocol(), summary_fixture(all_cash=True))
    assert cash['review']['status'] == 'rejected'
    assert 'insufficient_entered_outcomes' in cash['review']['reasons']


def test_unverifiable_input_provenance_is_explicitly_held_without_vintage_certification():
    values = summary_fixture()
    values[10]['provenance']['manifest_hash'] = None
    result = engine().summarize(protocol(), values)
    assert result['review']['status'] == 'rejected'
    assert 'unverifiable_input_provenance' in result['review']['reasons']
    assert 'grade' not in result and 'historical_vintage_verified' not in result


@pytest.mark.parametrize('bad_label', ['future_exit', 'stress_better', 'missing_entry', 'pending_value'])
def test_malformed_or_future_closed_labels_never_count_as_completed_pairs(bad_label):
    values = summary_fixture(1)
    slot = observation_arm(values[0], 'recovery-confirmed-v1')['slots'][0]
    if bad_label == 'future_exit':
        slot['exit_date'] = '2029-01-01'
    elif bad_label == 'stress_better':
        slot['stress_net_return'] = slot['net_return']+.01
    elif bad_label == 'missing_entry':
        slot['entry_date'] = None
    else:
        slot['status'] = 'pending'
    result = engine().summarize(protocol(), values)
    assert arm(result, 'recovery-confirmed-v1')['counts']['paired_sessions'] == 0
    assert arm(result, 'recovery-confirmed-v1')['metrics']['mean_net_return'] is None


@pytest.mark.parametrize('foreign', ['new_declaration', 'other_experiment'])
def test_saved_cohorts_cannot_be_reused_under_a_later_or_other_experiment(foreign):
    values = summary_fixture(1)
    spec = protocol()
    if foreign == 'new_declaration':
        spec['declared_at'] = '2026-10-14T11:00:00Z'
    else:
        spec['protocol_id'] = 'f'*64
    with pytest.raises(ValueError):
        engine().summarize(spec, values)
