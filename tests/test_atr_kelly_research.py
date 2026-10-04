"""Actual OHLC limit/barrier outcomes, phase evidence and ATR Kelly research."""
import copy
import importlib.util
import json
import sys
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from pathlib import Path
from functools import lru_cache

import pytest


@lru_cache(maxsize=1)
def engine():
    path = Path(__file__).resolve().parents[1]/'app/services/mirofish/atr_kelly_research.py'
    assert path.exists(), 'ATR barrier backtest engine is not implemented'
    spec = importlib.util.spec_from_file_location('atr_kelly_research_test_engine', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def row(index, open, high, low, close, volume=1000., code='005930', name='Samsung'):
    return dict(code=code, name=name, date=(date(2024,1,1)+timedelta(days=index)).isoformat(),
                open=float(open), high=float(high), low=float(low), close=float(close), volume=float(volume))


def seed():
    return [row(0,100,101,99,100), row(1,100,101,89,90)]


def cfg(**changes):
    settings = dict(train_end='2024-01-10', validation_end='2024-01-20',
                    atr_period=1, band_period=2, sigma=.5, atr_multiplier=.5,
                    fee_bps=0., slippage_bps=0., tax_bps=0.)
    settings.update(changes)
    return engine().ATRKellyConfig(**settings)


def run(rows, **changes):
    return engine().run_atr_kelly_backtest(rows, config=cfg(**changes))


def symbol(report):
    return report['symbols'][0]


def cycles(count=30, all_win=False):
    rows=[]
    for cycle in range(count):
        index=cycle*3
        rows.extend([row(index,100,100,100,100), row(index+1,100,101,89,90),
                     row(index+2,90,103,89 if all_win or cycle%5!=4 else 83,100)])
    return rows


def cycle_report(rows=None, **changes):
    return run(rows if rows is not None else cycles(), train_end='2024-01-30',
               validation_end='2024-02-29', **changes)


def test_signal_close_freezes_plan_but_cannot_fill_on_its_own_bar():
    report=run(seed())
    stock=symbol(report)
    assert stock['bars'][-1]['signal'] is True
    assert stock['signals'][0]['signal_date']=='2024-01-02'
    assert stock['signals'][0]['entry_price']==90.
    assert stock['signals'][0]['stop_price']==84.
    assert stock['signals'][0]['target_price']==102.
    assert stock['trades']==[]
    assert stock['production_eligible'] is False
    assert stock['research_weight']==0.


def test_next_session_open_limit_fill_and_actual_costed_target_outcome():
    report=run(seed()+[row(2,90,103,89,100)], fee_bps=5., slippage_bps=5., tax_bps=20.)
    trade=symbol(report)['trades'][0]
    assert trade['signal_date']=='2024-01-02'
    assert trade['entry_date']==trade['exit_date']=='2024-01-03'
    assert trade['entry_kind']=='open'
    assert trade['entry_price']==90.
    assert trade['exit_price']==102.
    assert trade['exit_reason']=='target'
    assert trade['gross_return']==pytest.approx(102/90-1)
    assert trade['net_return']==pytest.approx(102*.997/(90*1.001)-1)
    assert symbol(report)['price_study_equity'][-1]['equity']==pytest.approx(102*.997/(90*1.001))


def test_improved_open_entry_keeps_original_stop_and_target_prices():
    stock=symbol(run(seed()+[row(2,88,103,87,100)]))
    trade=stock['trades'][0]
    assert trade['entry_price']==88.
    assert trade['stop_price']==84.
    assert trade['target_price']==trade['exit_price']==102.
    assert trade['net_return']==pytest.approx(102/88-1)


@pytest.mark.parametrize('bar,reason,price', [
    (row(3,80,83,78,81),'stop_gap',80.),
    (row(3,110,112,109,111),'target_gap',110.),
])
def test_barrier_gap_fills_at_actual_open_not_frozen_barrier(bar,reason,price):
    stock=symbol(run(seed()+[row(2,90,95,89,94),bar]))
    trade=stock['trades'][0]
    assert trade['entry_date']=='2024-01-03'
    assert trade['exit_date']=='2024-01-04'
    assert trade['exit_reason']==reason
    assert trade['exit_price']==price
    assert trade['net_return']==pytest.approx(price/90-1)


def test_open_entry_below_frozen_stop_cannot_create_a_fictitious_stop_profit():
    trade=symbol(run(seed()+[row(2,80,83,78,81)]))['trades'][0]
    assert trade['entry_price']==trade['exit_price']==80.
    assert trade['exit_reason']=='stop_gap'
    assert trade['net_return']==0.


@pytest.mark.parametrize('open', [90.,95.])
def test_both_barriers_touched_are_stop_first_even_on_intraday_entry(open):
    trade=symbol(run(seed()+[row(2,open,105,83,91)]))['trades'][0]
    assert trade['entry_price']==90.
    assert trade['exit_price']==84.
    assert trade['exit_reason']=='stop'
    assert trade['ambiguous_bar'] is True
    assert trade['net_return']==pytest.approx(-6/90)


def test_intraday_entry_cannot_claim_target_that_may_have_preceded_entry():
    stock=symbol(run(seed()+[row(2,95,103,89,100), row(3,100,103,99,102)]))
    trade=stock['trades'][0]
    assert trade['entry_kind']=='limit'
    assert trade['entry_date']=='2024-01-03'
    assert trade['exit_date']=='2024-01-04'
    assert trade['exit_price']==102.
    assert trade['intraday_entry_target_deferred'] is True


def test_limit_order_expires_after_exactly_three_observed_sessions():
    bars=seed()+[row(2,95,98,91,97),row(3,98,101,95,100),row(4,101,104,95,103),
                 row(5,90,105,89,104)]
    stock=symbol(run(bars))
    assert stock['signals'][0]['status']=='expired'
    assert stock['signals'][0]['expiry_date']=='2024-01-05'
    assert stock['trades']==[]


def test_an_unfilled_order_stays_exclusive_until_it_expires():
    stock=symbol(run(seed()+[row(2,95,96,88,89,volume=0),row(3,96,97,91,94),row(4,98,101,94,100)]))
    assert stock['signals'][0]['status']=='expired'
    assert any(plan['status']=='skipped_open_order' for plan in stock['signals'][1:])
    assert stock['trades']==[]


def test_active_position_prevents_another_order_even_if_close_signals_again():
    stock=symbol(run(seed()+[row(2,90,91,88,89),row(3,89,90,87,88),row(4,110,112,109,111)]))
    assert len(stock['trades'])==1
    assert stock['signals'][1]['status']=='skipped_open_position'
    assert stock['trades'][0]['exit_reason']=='target_gap'


def test_zero_volume_prevents_pending_entry_without_erasing_the_plan():
    stock=symbol(run(seed()+[row(2,90,103,89,100,volume=0),row(3,90,103,89,100)]))
    assert stock['trades'][0]['entry_date']=='2024-01-04'
    assert stock['signals'][0]['entry_date']=='2024-01-04'


def test_zero_volume_prevents_exit_and_next_executable_gap_is_charged():
    stock=symbol(run(seed()+[row(2,90,95,89,94),row(3,80,83,78,81,volume=0),row(4,75,80,70,77)]))
    trade=stock['trades'][0]
    assert trade['exit_date']=='2024-01-05'
    assert trade['exit_price']==75.
    assert trade['exit_reason']=='stop_gap'


def test_horizon_is_entry_inclusive_and_exits_at_the_actual_session_close():
    stock=symbol(run(seed()+[row(2,90,95,89,94),row(3,94,97,92,96)],max_holding_sessions=2))
    trade=stock['trades'][0]
    assert trade['entry_date']=='2024-01-03'
    assert trade['exit_date']=='2024-01-04'
    assert trade['exit_reason']=='time_exit'
    assert trade['holding_sessions']==2
    assert trade['exit_price']==96.


def test_cross_partition_trade_is_not_force_closed_or_borrowed_into_validation():
    stock=symbol(run(seed()+[row(2,90,95,89,94),row(3,110,112,109,111)],
                     train_end='2024-01-03',validation_end='2024-01-05'))
    trade=stock['trades'][0]
    assert trade['phase']=='train'
    assert trade['exit_date']=='2024-01-04'
    assert trade['calibration_included'] is False
    assert stock['phase_metrics']['train']['completed_count']==0
    assert stock['phase_metrics']['train']['closed_count']==0
    assert stock['phase_metrics']['train']['excluded_crossing_count']==1
    assert stock['phase_metrics']['validation']['completed_count']==0


def test_validation_label_completed_in_test_does_not_enter_frozen_kelly():
    stock=symbol(run(seed()+[row(2,90,95,89,94),row(3,110,112,109,111)],
                     train_end='2024-01-01',validation_end='2024-01-03'))
    assert stock['trades'][0]['phase']=='validation'
    assert stock['trades'][0]['calibration_included'] is False
    assert stock['phase_metrics']['validation']['completed_count']==0
    assert stock['kelly_calculation']['raw_fraction'] is None
    assert stock['research_weight']==0.
    assert stock['kelly_test_equity'][0]['equity']==1.
    assert stock['kelly_test_equity'][0]['cash']==1.


def test_open_trade_is_reported_without_inventing_a_final_liquidation():
    stock=symbol(run(seed()+[row(2,90,95,89,94)]))
    trade=stock['trades'][0]
    assert trade['status']=='open'
    assert trade['exit_date'] is None
    assert trade['net_return'] is None
    assert stock['phase_metrics']['train']['unresolved_count']==1
    assert stock['price_study_equity'][-1]['equity']==pytest.approx(94/90)


def test_kelly_uses_actual_barrier_net_distribution_not_close_horizon_or_assumed_probability():
    report=cycle_report(fee_bps=5.,slippage_bps=5.,tax_bps=20.)
    stock=symbol(report)
    metrics=stock['phase_metrics']['validation']
    gain=102*.997/(90*1.001)-1
    loss=1-84*.997/(90*1.001)
    raw=.8/loss-.2/gain
    assert stock['phase_metrics']['train']['completed_count']==10
    assert metrics['completed_count']==10
    assert metrics['wins']==8 and metrics['losses']==2
    assert metrics['p']==pytest.approx(.8)
    assert metrics['payoff_ratio']==pytest.approx(gain/loss)
    assert stock['kelly_calculation']['two_point']['gain_fraction']==pytest.approx(gain)
    assert stock['kelly_calculation']['two_point']['loss_fraction']==pytest.approx(loss)
    assert stock['kelly_calculation']['raw_fraction']==pytest.approx(raw)
    assert stock['evidence_qualified'] is True
    assert stock['research_weight']==pytest.approx(.2)
    assert stock['production_eligible'] is False
    assert stock['kelly_calculation']['vix_index'] is None
    assert stock['kelly_calculation']['approval_status']=='held'
    json.dumps(report,allow_nan=False)


def test_few_trades_keep_real_probability_and_signed_kelly_diagnostics_but_zero_allocation():
    report=cycle_report(min_train_trades=11)
    stock=symbol(report)
    assert stock['phase_metrics']['validation']['p']==pytest.approx(.8)
    assert stock['kelly_calculation']['raw_fraction'] is not None
    assert 'train_insufficient_trades' in stock['kelly_calculation']['held_reasons']
    assert stock['evidence_qualified'] is False
    assert stock['research_weight']==0.
    assert all(point['equity']==point['cash']==1. for point in stock['kelly_test_equity'])


def test_all_wins_cannot_invent_loss_payoff_or_approved_sizing():
    stock=symbol(cycle_report(rows=cycles(all_win=True)))
    assert stock['phase_metrics']['validation']['p']==1.
    assert stock['phase_metrics']['validation']['payoff_ratio'] is None
    assert stock['kelly_calculation']['raw_fraction'] is None
    assert stock['research_weight']==0.
    assert stock['production_eligible'] is False


def test_oos_changes_cannot_rewrite_completed_train_validation_or_frozen_sizing():
    original=cycle_report()
    altered=cycles()
    for bar in altered:
        if bar['date']>'2024-02-29' and bar['open']==90.:
            bar['low']=83.
    changed=cycle_report(rows=altered)
    first, second=symbol(original),symbol(changed)
    assert first['phase_metrics']['train']==second['phase_metrics']['train']
    assert first['phase_metrics']['validation']==second['phase_metrics']['validation']
    assert first['kelly_calculation']==second['kelly_calculation']
    assert first['research_weight']==second['research_weight']
    assert first['phase_metrics']['test']['p']!=second['phase_metrics']['test']['p']
    assert first['kelly_test_equity'][-1]['equity']!=second['kelly_test_equity'][-1]['equity']


def test_kelly_test_curve_starts_flat_and_charges_real_costs_at_the_frozen_weight():
    stock=symbol(cycle_report(fee_bps=5.,slippage_bps=5.,tax_bps=20.))
    curve=stock['kelly_test_equity']
    assert curve[0]['date']=='2024-03-01'
    assert curve[0]['equity']==curve[0]['cash']==1.
    first=stock['kelly_test_trades'][0]
    assert first['signal_date']>'2024-02-29'
    assert first['allocated_quantity']>0.
    assert first['allocated_entry_cost']>0.
    assert first['allocated_exit_cost']>0.
    assert first['entry_weight']<=.2+1e-12
    assert stock['price_study_equity'][0]['date']=='2024-01-01'
    assert stock['curve_basis']['price_study_equity']=='full_single_symbol_notional_not_kelly_or_portfolio'


def test_vix_is_an_explicit_static_scenario_not_a_fabricated_observed_series():
    stock=symbol(cycle_report(vix_index=30.))
    assert stock['kelly_calculation']['vix_basis']=='static_scenario'
    assert stock['kelly_calculation']['kelly_fraction']==.25
    assert stock['kelly_calculation']['vix_index']==30.


def test_deterministic_grouping_keeps_exact_stock_identity_and_does_not_mutate_input():
    a=cycles(2)
    b=[dict(bar,code='000660',name='SK Hynix') for bar in a]
    mixed=list(reversed(a+b))
    before=copy.deepcopy(mixed)
    report=run(mixed)
    assert [stock['code'] for stock in report['symbols']]==['000660','005930']
    assert report['symbols'][0]['name']=='SK Hynix'
    assert mixed==before
    assert report==run(mixed)


@pytest.mark.parametrize('changes', [
    {'train_end':'2024-1-1'}, {'train_end':'2024-02-01'}, {'atr_period':True},
    {'atr_period':0}, {'band_period':1}, {'sigma':0.}, {'atr_multiplier':float('nan')},
    {'max_stop_fraction':1.}, {'reward_risk':0.}, {'order_expiry_sessions':0},
    {'max_holding_sessions':0}, {'fee_bps':-1.}, {'tax_bps':10000.},
    {'min_train_trades':0}, {'min_validation_trades':True}, {'min_win_rate':1.1},
    {'min_payoff_ratio':-1.}, {'kelly_fraction':0.}, {'cap_limit':.21}, {'vix_index':True},
])
def test_invalid_configuration_fails_before_running_price_research(changes):
    with pytest.raises(ValueError):
        cfg(**changes)


def test_config_is_frozen_after_validation():
    config=cfg()
    with pytest.raises(FrozenInstanceError):
        config.atr_period=2


@pytest.mark.parametrize('mutation', ['duplicate','negative','nan','missing_volume','bad_identity'])
def test_malformed_ohlcv_or_identity_is_not_silently_dropped(mutation):
    bars=seed()
    if mutation=='duplicate': bars.append(dict(bars[0]))
    if mutation=='negative': bars[0]['open']=-1.
    if mutation=='nan': bars[0]['high']=float('nan')
    if mutation=='missing_volume': del bars[0]['volume']
    if mutation=='bad_identity': bars[0]['code']=1234
    with pytest.raises(ValueError):
        run(bars)


def test_zero_realized_outcomes_are_disclosed_and_not_misclassified_as_losses():
    bars=cycles()
    for cycle in range(30):
        if cycle%5==3:
            bars[cycle*3+2]=row(cycle*3+2,80,103,78,100)
    stock=symbol(cycle_report(rows=bars))
    metrics=stock['phase_metrics']['validation']
    assert metrics['completed_count']==10
    assert metrics['wins']==6 and metrics['losses']==2 and metrics['zeros']==2
    assert metrics['p']==pytest.approx(.75)
    assert stock['kelly_calculation']['two_point']['p']==pytest.approx(.75)
    assert stock['kelly_calculation']['raw_fraction']==pytest.approx(9.375)


def test_exit_after_validation_cutoff_cannot_rewrite_any_frozen_phase_metric():
    prefix=seed()+[row(2,90,95,89,94)]
    closed=run(prefix+[row(3,110,112,109,111)],train_end='2024-01-01',validation_end='2024-01-03')
    open_report=run(prefix+[row(3,94,97,92,96)],train_end='2024-01-01',validation_end='2024-01-03')
    a,b=symbol(closed),symbol(open_report)
    assert a['trades'][0]['status']=='closed'
    assert b['trades'][0]['status']=='open'
    assert a['phase_metrics']['validation']==b['phase_metrics']['validation']
    assert a['kelly_calculation']==b['kelly_calculation']


def test_qualified_kelly_oos_starts_with_cash_even_when_price_study_carries_validation_position():
    bars=cycles()
    bars[65]=row(65,90,95,89,94)
    report=run(bars,train_end='2024-01-30',validation_end=bars[65]['date'])
    stock=symbol(report)
    assert stock['evidence_qualified']
    assert stock['phase_metrics']['validation']['completed_count']==11
    assert stock['phase_metrics']['validation']['unresolved_count']==1
    first=stock['kelly_test_equity'][0]
    assert first['date']==bars[66]['date']
    assert first['equity']==first['cash']==1.
    assert first['holding_quantity']==0.
    study=next(point for point in stock['price_study_equity'] if point['date']==bars[66]['date'])
    assert study['holding_quantity']>0.
    assert stock['kelly_test_trades'][0]['signal_date']>bars[65]['date']
