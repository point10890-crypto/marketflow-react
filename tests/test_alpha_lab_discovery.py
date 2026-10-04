"""Causal setup discovery is separate from the frozen strategy tournament."""
from copy import deepcopy
from datetime import date, timedelta
import math

import pytest


def module():
    from app.services.mirofish.alpha_lab import discovery
    return discovery


def bars(count=1320, symbol='005930'):
    start = date(2021, 1, 1)
    return [dict(symbol=symbol, date=(start+timedelta(days=i)).isoformat(), open=100., high=101.,
                 low=99., close=100., volume=1000.) for i in range(count)]


def factor_values():
    return dict(momentum_20=.1, momentum_60=.1, momentum_5=.01, range_position_20=.5,
                breakout_20=-.1, volume_ratio_20=1.)


def fake_execution(rows, signal_index, policy=None):
    if signal_index+1 >= len(rows) or rows[signal_index+1]['volume'] <= 0:
        return None
    entry = rows[signal_index+1]
    trade = dict(symbol=entry['symbol'], signal_date=rows[signal_index]['date'], entry_date=entry['date'],
                 entry_price=entry['open'], status='open', exit_date=None, exit_price=None, net_return=None)
    if signal_index+2 >= len(rows):
        return trade
    exit_price = entry['open']*(1.06 if signal_index//2 % 2 == 0 else .99)
    trade.update(status='closed', exit_date=rows[signal_index+2]['date'], exit_price=exit_price,
                 net_return=exit_price*(1-policy.exit_cost)/(entry['open']*(1+policy.entry_cost))-1)
    return trade


def controlled(monkeypatch):
    mod = module()
    monkeypatch.setattr(mod, 'features_at', lambda _rows, _index: factor_values())
    monkeypatch.setattr(mod, 'simulate_trade', fake_execution)
    return mod


def test_future_bars_cannot_change_phase_labels_selection_or_diagnostics(monkeypatch):
    mod = controlled(monkeypatch); rows = bars(); cutoff = rows[-1]['date']; seen = []
    def audited(rows, index, policy=None):
        seen.append(rows[-1]['date'])
        assert rows[-1]['date'] <= cutoff
        return fake_execution(rows, index, policy)
    monkeypatch.setattr(mod, 'simulate_trade', audited)
    expected = mod.discover_opportunities({'005930': rows}, names={'005930': '삼성전자'}, as_of=cutoff)
    later = dict(symbol='005930', date=(date.fromisoformat(cutoff)+timedelta(days=1)).isoformat(),
                 open=-999999., close=float('nan'), volume=-1.)
    assert mod.discover_opportunities({'005930': rows+[later]}, names={'005930': '삼성전자'}, as_of=cutoff) == expected
    assert set(seen) == {rows[-253]['date'], cutoff}


def test_split_is_exactly_last_union_1260_and_confirmation_starts_flat(monkeypatch):
    mod = controlled(monkeypatch); rows = bars()
    result = mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date'])
    candidate = result['candidates'][0]; cal, confirm = (candidate['evidence'][key] for key in ('calibration', 'confirmation'))
    assert (cal['start'], cal['end']) == (rows[-1260]['date'], rows[-253]['date'])
    assert (confirm['start'], confirm['end']) == (rows[-252]['date'], rows[-1]['date'])
    assert cal['end'] < confirm['start']
    audit = next(row for row in result['audit'] if row['selected'])
    assert all(t['exit_date'] <= cal['end'] for t in audit['calibration']['trades'])
    assert all(confirm['start'] <= t['signal_date'] < t['entry_date'] <= t['exit_date'] <= confirm['end']
               for t in audit['confirmation']['trades'])
    assert result['horizon_sessions'] == 10
    assert result['lookback_sessions'] == 1260


def test_phase_stops_after_unresolved_entry_instead_of_overlapping_later_closed_labels(monkeypatch):
    mod = controlled(monkeypatch); rows = bars(); first_signal = rows[-1260]['date']; attempted = []
    def unresolved(rows, index, policy=None):
        day = rows[index]['date']; attempted.append(day)
        if day == first_signal:
            return dict(status='open', signal_date=day, entry_date=rows[index+1]['date'],
                        entry_price=100., exit_date=None, exit_price=None, net_return=None)
        return fake_execution(rows, index, policy)
    monkeypatch.setattr(mod, 'simulate_trade', unresolved)
    result = mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date'])
    assert result['candidates'] == []
    assert attempted == [first_signal]
    audit = next(row for row in result['audit'] if row['setup_active'])
    assert audit['calibration']['summary']['samples'] == 0
    assert len(audit['calibration']['open_trades']) == 1


def test_union_next_session_ioc_and_sparse_holding_intervals_are_excluded(monkeypatch):
    mod = controlled(monkeypatch); dense = bars(symbol='000660'); sparse = bars()
    missing = sparse[-1260+1]['date']; sparse = [row for row in sparse if row['date'] != missing]
    seen = []
    def audit(rows, index, policy=None):
        seen.append((rows[index]['symbol'], rows[index]['date']))
        return fake_execution(rows, index, policy)
    monkeypatch.setattr(mod, 'simulate_trade', audit)
    result = mod.discover_opportunities({'005930': sparse, '000660': dense}, as_of=dense[-1]['date'])
    assert ('005930', dense[-1260]['date']) not in seen
    assert result['diagnostics']['missing_next_union_quote'] >= 1
    # A missed union session anywhere in the 61-bar factor window is held.
    assert result['diagnostics']['sparse_factor_window'] >= 1


def test_closed_trades_never_overlap_and_stress_uses_same_fills_with_double_costs(monkeypatch):
    mod = controlled(monkeypatch); rows = bars()
    result = mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date'])
    audit = next(row for row in result['audit'] if row['selected'])
    for phase in ('calibration', 'confirmation'):
        trades = audit[phase]['trades']
        assert all(a['exit_date'] < b['entry_date'] for a, b in zip(trades, trades[1:]))
        for trade in trades:
            expected = trade['exit_price']*(1-.006)/(trade['entry_price']*(1+.002))-1
            assert trade['stress_net_return'] == pytest.approx(expected)
            assert trade['entry_cost_per_share'] == pytest.approx(trade['entry_price']*.001)
            assert trade['exit_cost_per_share'] == pytest.approx(trade['exit_price']*.003)
            assert trade['stress_entry_cost_per_share'] == pytest.approx(trade['entry_price']*.002)
            assert trade['stress_exit_cost_per_share'] == pytest.approx(trade['exit_price']*.006)


def test_latest_zero_volume_never_becomes_a_buy_candidate(monkeypatch):
    mod = controlled(monkeypatch); rows = bars(); rows[-1]['volume'] = 0.
    result = mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date'])
    assert result['candidates'] == [] and result['active_setup_count'] == 0
    assert 'latest_quote_nontradable' in result['audit'][0]['reasons']


def test_calibration_only_selection_has_no_confirmation_runner_up_retry(monkeypatch):
    mod = controlled(monkeypatch); rows = bars(); current = factor_values(); current['momentum_5'] = -.03
    monkeypatch.setattr(mod, 'features_at', lambda _rows, _index: current)
    original = mod._collect_phase; confirmation_calls = []
    def phases(*args, **kwargs):
        result = original(*args, **kwargs)
        strategy, start = args[1], args[2]
        if start == rows[-1260]['date']:
            result['summary']['stress_mean_net_return'] = .05 if strategy == 'momentum' else .04
        else:
            confirmation_calls.append(strategy)
            if strategy == 'momentum': result['summary']['stress_compounded_trade_return'] = -.1
        return result
    monkeypatch.setattr(mod, '_collect_phase', phases)
    result = mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date'])
    assert result['candidates'] == []
    assert confirmation_calls == ['momentum']


def test_final_rank_uses_calibration_stress_mean_not_current_factors_or_confirmation(monkeypatch):
    mod = controlled(monkeypatch); first, second = bars(), bars(symbol='000660'); original = mod._collect_phase
    def phases(*args, **kwargs):
        result = original(*args, **kwargs); symbol = args[0][0]['symbol']; start = args[2]
        if start == first[-1260]['date']:
            result['summary']['stress_mean_net_return'] = .02 if symbol == '005930' else .01
        else:
            result['summary']['stress_mean_net_return'] = .01 if symbol == '005930' else .5
        return result
    monkeypatch.setattr(mod, '_collect_phase', phases)
    result = mod.discover_opportunities({'005930': first, '000660': second}, as_of=first[-1]['date'])
    assert [row['symbol'] for row in result['candidates']] == ['005930', '000660']
    assert [row['score'] for row in result['candidates']] == [.02, .01]


def test_quarter_kelly_is_from_actual_calibration_net_returns_and_not_approved_weight(monkeypatch):
    mod = controlled(monkeypatch); rows = bars(); before = deepcopy(rows)
    result = mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date']); candidate = result['candidates'][0]
    risk = candidate['risk']; evidence = candidate['evidence']
    assert risk['quarter_kelly_fraction'] == pytest.approx(.25*risk['kelly_raw'])
    assert risk['research_weight'] == min(.05, risk['quarter_kelly_fraction'], .01/candidate['plan']['loss_fraction'])
    assert risk['planned_account_risk'] == pytest.approx(risk['research_weight']*candidate['plan']['loss_fraction'])
    assert risk['weight'] == 0. and risk['status'] == 'held'
    assert evidence['retrospective'] is True and evidence['independent_validation'] is False
    assert rows == before


def test_geometric_loss_is_held_even_when_arithmetic_mean_is_positive(monkeypatch):
    mod = controlled(monkeypatch); rows = bars(); original = mod._collect_phase
    def phases(*args, **kwargs):
        result = original(*args, **kwargs)
        result['summary']['stress_compounded_trade_return'] = -.01
        return result
    monkeypatch.setattr(mod, '_collect_phase', phases)
    assert mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date'])['candidates'] == []


def test_empty_or_short_histories_are_honest_zero_candidate_results():
    mod = module()
    assert mod.discover_opportunities({}, as_of='2026-10-02')['candidates'] == []
    result = mod.discover_opportunities({'005930': bars(100)})
    assert result['eligible_count'] == 0 and 'insufficient_union_history' in result['reasons']


def test_real_execution_labels_preserve_next_open_horizon_and_actual_costs():
    mod = module(); rows = bars(); result = mod.discover_opportunities({'005930': rows}, as_of=rows[-1]['date'])
    assert result['candidates'] == []
    # Flat prices have no active fixed setup; they are not filled merely to fabricate samples.
    assert result['active_setup_count'] == 0
