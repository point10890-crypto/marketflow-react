"""Frozen chronological net-outcome research without holdout selection leakage."""
import copy
import importlib
import math
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def engine():
    assert (ROOT / 'app/services/mirofish/alpha_lab/research.py').exists(), 'AlphaLab research is not implemented'
    return importlib.import_module('app.services.mirofish.alpha_lab.research')


def panel(n=250, count=4):
    result = {}
    for k in range(count):
        symbol = f'{k + 1:06d}'
        rows = []
        last = 100.
        for i in range(n):
            close = 100. * math.exp(.0015 * i + .06 * math.sin((i + k * 3) / 7))
            rows.append(dict(symbol=symbol, date=(date(2024, 1, 1) + timedelta(days=i)).isoformat(),
                             open=last, high=max(last, close) * 1.005,
                             low=min(last, close) * .995, close=close,
                             volume=1000. * (2. if i % 17 < 3 else 1.)))
            last = close
        result[symbol] = rows
    return result


def cfg(module):
    from app.services.mirofish.alpha_lab.execution import ExecutionPolicy
    return module.ResearchConfig(train_sessions=120, validation_sessions=50, test_sessions=50,
                                 step_sessions=5, policy=ExecutionPolicy(horizon=3))


def test_protocol_defaults_are_frozen_and_four_strategies_preregistered():
    module = engine()
    config = module.ResearchConfig()
    assert (config.train_sessions, config.validation_sessions, config.test_sessions, config.step_sessions) == (504, 126, 126, 5)
    with pytest.raises(FrozenInstanceError):
        config.step_sessions = 1
    report = module.run_research(panel(80), config=cfg(module))
    assert report['champion'] is None and report['candidates'] == []
    assert report['diagnostics']['held_reasons'] == ['insufficient_calendar_history']


def test_model_fit_uses_only_matured_training_net_bracket_labels():
    module = engine()
    prices = panel()
    cutoff = prices['000001'][120]['date']
    model, metadata = module.fit_training_model(prices, cutoff, step_sessions=5, policy=cfg(module).policy)
    changed = copy.deepcopy(prices)
    for rows in changed.values():
        for row in rows:
            if row['date'] > cutoff:
                row['close'] = float('nan')
    other, other_metadata = module.fit_training_model(changed, cutoff, step_sessions=5, policy=cfg(module).policy)
    assert model == other and metadata == other_metadata
    assert metadata['fit_cutoff'] == cutoff
    assert metadata['label_exit_dates'] and max(metadata['label_exit_dates']) <= cutoff
    assert metadata['label_basis'] == 'actual_costed_future_bracket_outcomes'
    assert metadata['training_samples'] == model['training_samples']
    assert metadata['unresolved_labels_ignored'] > 0


def test_champion_and_validation_are_independent_of_test_outcomes():
    module = engine()
    prices = panel()
    original = module.run_research(prices, config=cfg(module))
    changed = copy.deepcopy(prices)
    test_start = original['protocol']['periods']['test']['start']
    for rows in changed.values():
        for i, row in enumerate(rows):
            if row['date'] >= test_start:
                for key in ('open', 'high', 'low', 'close'):
                    row[key] *= 1. + .01 * i
    altered = module.run_research(changed, config=cfg(module))
    assert original['champion'] == altered['champion']
    assert original['selection'] == altered['selection']
    assert original['diagnostics']['training'] == altered['diagnostics']['training']
    assert [row['validation']['metrics'] for row in original['strategies']] == [row['validation']['metrics'] for row in altered['strategies']]
    assert any(a['test']['metrics'] != b['test']['metrics'] for a, b in zip(original['strategies'], altered['strategies']))


def test_report_discloses_one_fixed_split_and_stressed_costs_do_not_refit():
    module = engine()
    report = module.run_research(panel(), config=cfg(module))
    assert len(report['strategies']) == 4
    assert report['protocol']['evaluation'] == 'recent_frozen_chronological_split'
    assert report['protocol']['champion_selection'] == 'validation_only'
    assert report['protocol']['normalization'] == 'training_only'
    assert report['protocol']['embargo_sessions'] == 3
    assert len(report['walkforward_folds']) == 1
    for row in report['strategies']:
        assert row['diagnostic_allocation_weight'] == .1
        assert row['diagnostic_approval'] == 'unapproved_research_comparison'
        assert row['stress']['cost_multiplier'] == 2.
        assert row['stress']['model_refitted'] is False
        assert row['calibration']['approval_status'] == 'held'
    assert report['production_eligible'] is False
    assert report['baseline']['basis'] == 'same_current_cohort_equal_weight_price_basket_descriptive'


def test_latest_watchlist_retains_only_current_quotes_and_zero_unapproved_weight():
    module = engine()
    prices = panel()
    prices['000004'] = prices['000004'][:-1]
    names = {s: f'주식 {s}' for s in prices}
    report = module.run_research(prices, names=names, config=cfg(module))
    assert len(report['candidates']) <= 3
    for row in report['candidates']:
        assert row['symbol'] != '000004'
        assert row['name'] == names[row['symbol']]
        assert row['as_of'] == report['as_of']
        assert row['last_close'] == prices[row['symbol']][-1]['close']
        assert row['approved_weight'] == 0.
        assert row['risk']['approval_status'] == 'held'
        assert row['plan']['stop_price'] < row['plan']['entry_price'] < row['plan']['target_price']
    assert any('stale_latest_quote:000004' == reason for reason in report['diagnostics']['held_reasons'])


def test_invalid_split_or_policy_configuration_fails_before_research():
    module = engine()
    for changes in ({'train_sessions': 60}, {'validation_sessions': 0}, {'step_sessions': True}):
        with pytest.raises(ValueError):
            module.ResearchConfig(**changes)

def test_explicit_asof_freezes_recent_window_when_future_rows_are_appended():
    module = engine()
    from dataclasses import replace
    prices = panel()
    configuration = replace(cfg(module), as_of=prices['000001'][-1]['date'])
    original = module.run_research(prices, config=configuration)
    extended = panel(270)
    for rows in extended.values():
        rows[-1]['close'] = float('nan')
    replay = module.run_research(extended, config=configuration)
    assert original == replay
    assert original['protocol']['periods']['train']['start'] > prices['000001'][0]['date']


def test_sparse_global_calendar_labels_cannot_defer_missing_next_session_entry():
    module = engine()
    prices = panel()
    prices['000001'] = [row for i, row in enumerate(prices['000001']) if i != 61]
    cutoff = prices['000002'][120]['date']
    model, metadata = module.fit_training_model(prices, cutoff, step_sessions=5, policy=cfg(module).policy)
    assert dict(symbol='000001', signal_date=prices['000002'][60]['date']) in metadata.get('sparse_label_rejections', [])
    assert model is not None


def test_latest_serving_refit_is_separate_from_frozen_evaluation():
    module = engine()
    report = module.run_research(panel(), config=cfg(module))
    serving = report['diagnostics']['serving_training']
    assert serving['fit_cutoff'] == report['as_of']
    assert max(serving['label_exit_dates']) <= report['as_of']
    assert report['diagnostics']['training']['fit_cutoff'] < serving['fit_cutoff']
    assert report['protocol']['latest_model'] == 'separate_serving_refit_after_frozen_evaluation'
    assert report['protocol']['test_model'] == 'frozen_training_model'


@pytest.mark.parametrize('atr_period', [14, 90])
def test_period_replay_bounds_warmup_and_matches_full_history_with_sparse_quotes(monkeypatch, atr_period):
    module = engine()
    prices = panel(1000, count=3)
    days = [row['date'] for row in prices['000001']]
    period = dict(start=days[900], end=days[980])
    # Missing next-session entry cancels the first order; later decisions can fill.
    prices['000001'] = [row for row in prices['000001'] if row['date'] != days[901]]
    prices['000002'][925]['volume'] = 0.
    decisions = {days[i]: [dict(symbol=symbol, weight=.1) for symbol in prices]
                 for i in (900, 910, 920, 930, 978)}
    from dataclasses import replace
    policy = replace(cfg(module).policy, atr_period=atr_period)
    observed = {symbol: [row for row in rows if row['date'] <= period['end']]
                for symbol, rows in prices.items()}
    replay = module.simulate_portfolio(observed, decisions, policy=policy, initial_cash=1.,
                                       cash_buffer=.4, max_positions=3, position_cap=.2)
    full_curve = [row for row in replay['equity'] if period['start'] <= row['date'] <= period['end']]
    full_trades = [row for row in replay['trades'] if period['start'] <= row['entry_date'] <= period['end']]
    closed = [row for row in full_trades if row['status'] == 'closed']
    original_simulator = module.simulate_portfolio
    captured = {}
    def capture(trimmed, *args, **kwargs):
        captured.update(trimmed)
        return original_simulator(trimmed, *args, **kwargs)
    monkeypatch.setattr(module, 'simulate_portfolio', capture)
    result = module._run_period(prices, decisions, period, policy)
    assert result['equity'] == full_curve
    assert result['trades'] == full_trades
    assert result['metrics'] == module._metrics(full_curve)
    assert result['closed_net_returns'] == [row['net_return'] for row in closed]
    assert result['observed_limit_drift'] == replay['observed_limit_drift']
    assert not any(row['symbol'] == '000001' and row['entry_date'] == days[901] for row in full_trades)
    for symbol, rows in captured.items():
        assert len([row for row in rows if row['date'] < period['start']]) <= max(61, atr_period + 1)
        assert [row for row in rows if period['start'] <= row['date'] <= period['end']] == [
            row for row in prices[symbol] if period['start'] <= row['date'] <= period['end']]
