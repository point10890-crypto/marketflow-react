from dataclasses import FrozenInstanceError, replace

import pytest


def api():
    from app.services.mirofish.alpha_lab import execution
    return execution


def bars(symbol='A', count=18):
    from datetime import date, timedelta
    return [dict(symbol=symbol, date=(date(2024, 1, 1)+timedelta(days=i)).isoformat(),
                 open=100., high=101., low=99., close=100., volume=1000.) for i in range(count)]


def test_frozen_policy_and_prefix_plan_ignore_future_rows():
    mod = api()
    policy = mod.ExecutionPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.horizon = 3
    rows = bars()
    plan = mod.build_bracket_plan(rows, 13)
    rows[14]['high'] = float('nan')
    assert mod.build_bracket_plan(rows, 13) == plan
    assert plan['atr'] == pytest.approx(2.)
    assert plan['stop_price'] == pytest.approx(96.)
    assert plan['target_price'] == pytest.approx(108.)
    assert mod.build_bracket_plan(rows[:10])['status'] == 'warmup'


def test_next_open_entry_can_take_same_session_target():
    mod = api()
    rows = bars()
    rows[14].update(high=109., low=97., close=103.)
    trade = mod.simulate_trade(rows, 13)
    assert trade['entry_date'] == rows[14]['date']
    assert trade['exit_date'] == rows[14]['date']
    assert trade['exit_reason'] == 'target'
    assert trade['exit_price'] == pytest.approx(108.)
    assert trade['holding_sessions'] == 1
    assert trade['net_return'] == pytest.approx(108.*.997/(100.*1.001)-1)


def test_zero_volume_next_session_does_not_fill():
    mod = api()
    rows = bars()
    rows[14]['volume'] = 0.
    assert mod.simulate_trade(rows, 13) is None
    out = mod.simulate_portfolio({'A': rows}, {rows[13]['date']: [{'symbol': 'A', 'weight': .2}]})
    assert not out['fills']


def test_both_barriers_touch_stop_first_and_open_gap_uses_executable_price():
    mod = api()
    rows = bars()
    rows[14].update(high=109., low=95., close=100.)
    trade = mod.simulate_trade(rows, 13)
    assert trade['exit_reason'] == 'stop'
    assert trade['exit_price'] == 96.
    rows = bars()
    rows[15].update(open=90., high=92., low=89., close=91.)
    trade = mod.simulate_trade(rows, 13)
    assert trade['exit_reason'] == 'stop_gap'
    assert trade['exit_price'] == 90.
    rows[15].update(open=112., high=114., low=111., close=113.)
    trade = mod.simulate_trade(rows, 13)
    assert trade['exit_reason'] == 'target_gap'
    assert trade['exit_price'] == 112.


def test_actual_fill_caps_stop_distance_and_preserves_frozen_atr():
    mod = api()
    rows = bars()
    rows[14].update(open=50., high=52., low=49., close=50.)
    trade = mod.simulate_trade(rows[:15], 13)
    assert trade['entry_price'] == 50.
    assert trade['atr'] == 2.
    assert trade['stop_price'] == 46.
    assert trade['target_price'] == 58.
    assert trade['status'] == 'open'
    assert trade['net_return'] is None


def test_horizon_counts_entry_and_zero_volume_exit_defers():
    mod = api()
    rows = bars()
    rows[15]['volume'] = 0.
    trade = mod.simulate_trade(rows, 13, replace(mod.ExecutionPolicy(), horizon=2))
    assert trade['exit_date'] == rows[16]['date']
    assert trade['holding_sessions'] == 3
    assert trade['exit_reason'] == 'time'


def test_intraday_exit_cannot_free_a_slot_for_an_earlier_open_buy():
    mod = api()
    universe = {s: bars(s) for s in 'ABCD'}
    universe['A'][15].update(high=109., low=99., close=104.)
    decisions = {universe['A'][13]['date']: [{'symbol': s, 'weight': .2} for s in 'ABC'],
                 universe['A'][14]['date']: [{'symbol': 'D', 'weight': .2}]}
    out = mod.simulate_portfolio(universe, decisions)
    assert any(x['symbol'] == 'A' and x['side'] == 'SELL' for x in out['fills'])
    assert not any(x['symbol'] == 'D' and x['side'] == 'BUY' for x in out['fills'])


def test_open_gap_exit_may_fund_open_fill_and_costs_preserve_cash_buffer():
    mod = api()
    universe = {s: bars(s) for s in 'ABCD'}
    universe['A'][15].update(open=112., high=114., low=111., close=113.)
    decisions = {universe['A'][13]['date']: [{'symbol': s, 'weight': .9} for s in 'ABC'],
                 universe['A'][14]['date']: [{'symbol': 'D', 'weight': .2}]}
    out = mod.simulate_portfolio(universe, decisions)
    assert any(x['symbol'] == 'D' and x['side'] == 'BUY' for x in out['fills'])
    entry_mark = out['equity'][14]
    assert entry_mark['cash'] / entry_mark['equity'] >= .4-1e-12
    assert entry_mark['exposure'] <= .6+1e-12
    assert all(x['allocation_weight'] <= .2+1e-12 for x in out['fills'] if x['side'] == 'BUY')


def test_missing_quote_keeps_last_mark_and_never_fills_missing_symbol():
    mod = api()
    a, b = bars('A'), bars('B')
    a[14].update(high=102., close=101.)
    missing_date = a[15]['date']
    a = [row for row in a if row['date'] != missing_date]
    decisions = {b[13]['date']: [{'symbol': 'A', 'weight': .2}],
                 b[14]['date']: [{'symbol': 'A', 'weight': .2}]}
    out = mod.simulate_portfolio({'A': a, 'B': b}, decisions)
    marks = {row['date']: row for row in out['equity']}
    assert marks[missing_date]['equity'] == pytest.approx(marks[b[14]['date']]['equity'])
    assert not any(x['date'] == missing_date for x in out['fills'])
    assert out['mark_policy']


def test_final_position_is_open_with_null_return_and_no_forced_sell():
    mod = api()
    rows = bars(count=15)
    out = mod.simulate_portfolio({'A': rows}, {rows[13]['date']: [{'symbol': 'A', 'weight': .1}]})
    assert len(out['open_positions']) == 1
    assert out['trades'][0]['status'] == 'open'
    assert out['trades'][0]['net_return'] is None
    assert [x['side'] for x in out['fills']] == ['BUY']
    assert out['metrics']['net_total_return'] < 0


@pytest.mark.parametrize('kwargs', [{'horizon': 0}, {'max_stop_fraction': 1}, {'fee_bps': -1}])
def test_policy_rejects_invalid_execution_assumptions(kwargs):
    with pytest.raises(ValueError):
        api().ExecutionPolicy(**kwargs)
