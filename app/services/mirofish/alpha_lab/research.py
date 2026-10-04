"""Recent frozen strategy comparison; completed net labels, never holdout selection."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from statistics import fmean, stdev

from .execution import ExecutionPolicy, build_bracket_plan, simulate_portfolio, simulate_trade
from .features import SOURCE_ACKNOWLEDGEMENT, STRATEGIES, features_at, fit_ridge, score_strategy
from .risk import size_from_returns


@dataclass(frozen=True)
class ResearchConfig:
    train_sessions: int = 504
    validation_sessions: int = 126
    test_sessions: int = 126
    step_sessions: int = 5
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    as_of: str | None = None

    def __post_init__(self):
        for key, minimum in (('train_sessions', 61), ('validation_sessions', 1),
                             ('test_sessions', 1), ('step_sessions', 1)):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError('Invalid chronological research configuration: ' + key)
        if not isinstance(self.policy, ExecutionPolicy):
            raise ValueError('Research requires a frozen execution policy')
        if self.as_of is not None and (not isinstance(self.as_of, str) or date.fromisoformat(self.as_of).isoformat() != self.as_of):
            raise ValueError('Research as_of requires a canonical date')


def fit_training_model(prices_by_symbol, cutoff, *, start_date=None, step_sessions=5, policy=None):
    """Label only the supplied observed training prefix; unresolved trades are excluded."""
    policy = policy or ExecutionPolicy()
    if date.fromisoformat(cutoff).isoformat() != cutoff or step_sessions < 1:
        raise ValueError('Invalid training cutoff or sample interval')
    samples, labels, exits = [], [], []
    ignored = 0
    sparse = []
    calendar = sorted({row['date'] for rows in prices_by_symbol.values() for row in rows if row['date'] <= cutoff})
    sampled = [day for day in calendar if start_date is None or day >= start_date][::step_sessions]
    calendar_index = {day: i for i, day in enumerate(calendar)}
    for symbol, raw_rows in sorted(prices_by_symbol.items()):
        rows = [row for row in raw_rows if row['date'] <= cutoff]
        indices = {row['date']: i for i, row in enumerate(rows)}
        for day in sampled:
            index = indices.get(day)
            if index is None or index < 60:
                continue
            features = features_at(rows, index)
            if features is None or rows[index]['volume'] <= 0:
                continue
            global_index = calendar_index[day]
            if global_index + 1 < len(calendar) and (index + 1 >= len(rows) or rows[index + 1]['date'] != calendar[global_index + 1]):
                sparse.append(dict(symbol=symbol, signal_date=day))
                continue
            trade = simulate_trade(rows, index, policy=policy)
            if not trade or trade['status'] != 'closed' or trade.get('exit_date') is None or trade['exit_date'] > cutoff:
                ignored += 1
                continue
            expected = [known for known in calendar[global_index + 1:] if known <= trade['exit_date']]
            actual = [row['date'] for row in rows[index + 1:] if row['date'] <= trade['exit_date']]
            if actual != expected:
                sparse.append(dict(symbol=symbol, signal_date=day))
                continue
            net = trade['net_return']
            if net is None or not math.isfinite(net):
                raise ValueError('Training labels must be actual finite net returns')
            samples.append(features)
            labels.append(net)
            exits.append(trade['exit_date'])
    model = fit_ridge(samples, labels) if len(labels) >= 30 else None
    metadata = dict(fit_cutoff=cutoff, training_start=start_date, training_samples=len(labels),
                    label_exit_dates=sorted(set(exits)), unresolved_labels_ignored=ignored,
                    label_basis='actual_costed_future_bracket_outcomes', normalization='training_only',
                    sparse_label_rejections=sparse, ridge_lambda=1., model_status='fitted' if model is not None else 'insufficient_matured_labels')
    metadata['model_sha256'] = hashlib.sha256(json.dumps(model, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return model, metadata


def _setup(strategy, values, score):
    if strategy == 'momentum':
        return values['momentum_20'] > 0 and values['momentum_60'] > 0
    if strategy == 'liquidity_breakout':
        return values['breakout_20'] >= -.02 and values['volume_ratio_20'] >= 1.2
    if strategy == 'mean_reversion':
        return values['momentum_5'] < -.02 or values['range_position_20'] < .25
    return score > 0


def _metrics(curve):
    if not curve:
        return dict(net_total_return=0., cagr=0., max_drawdown=0., sharpe=0.)
    values = [row['equity'] for row in curve]
    returns = [values[i] / values[i - 1] - 1. for i in range(1, len(values)) if values[i - 1] > 0]
    peak, drawdown = values[0], 0.
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1. if peak > 0 else 0.)
    total = values[-1] / values[0] - 1. if values[0] > 0 else 0.
    years = max((date.fromisoformat(curve[-1]['date']) - date.fromisoformat(curve[0]['date'])).days / 365.25, 1 / 365.25)
    deviation = stdev(returns) if len(returns) > 1 else 0.
    cagr = math.expm1(math.log1p(total) / years) if total > -1 else -1.
    return dict(net_total_return=total, cagr=cagr, max_drawdown=drawdown,
                sharpe=fmean(returns) / deviation * math.sqrt(252) if deviation > 0 else 0.)


def _run_period(prices, decisions, period, policy):
    # The period starts in cash. Retain only causal indicator warmup plus
    # the evaluated sessions instead of replaying decades of inactive history.
    warmup = max(61, policy.atr_period + 1)
    observed = {symbol: [row for row in rows if row['date'] < period['start']][-warmup:]
                       + [row for row in rows if period['start'] <= row['date'] <= period['end']]
                for symbol, rows in prices.items()}
    observed = {symbol: rows for symbol, rows in observed.items() if rows}
    result = simulate_portfolio(observed, decisions, policy=policy, initial_cash=1.,
                                cash_buffer=.4, max_positions=3, position_cap=.2)
    curve = [row for row in result['equity'] if period['start'] <= row['date'] <= period['end']]
    trades = [row for row in result['trades'] if period['start'] <= row['entry_date'] <= period['end']]
    closed = [row for row in trades if row['status'] == 'closed' and row['exit_date'] <= period['end']]
    return dict(metrics=_metrics(curve), equity=curve, trades=trades,
                closed_net_returns=[row['net_return'] for row in closed], closed_trades=len(closed),
                open_trades=len(trades) - len(closed),
                observed_limit_drift=result.get('observed_limit_drift', {}))


def _decisions(prices, calendar, period, config, strategy, model, weight, cached):
    days = [day for day in calendar if period['start'] <= day <= period['end']]
    # Label/position maturity guard: no new signal in the final holding window.
    sampled = days[:max(0, len(days) - config.policy.horizon):config.step_sessions]
    decisions = {}
    indices = {symbol: {row['date']: i for i, row in enumerate(rows)} for symbol, rows in prices.items()}
    for day in sampled:
        ranked = []
        for symbol, rows in sorted(prices.items()):
            index = indices[symbol].get(day)
            if index is None or rows[index]['volume'] <= 0:
                continue
            key = (symbol, index)
            if key not in cached:
                cached[key] = features_at(rows, index)
            values = cached[key]
            if values is None:
                continue
            score = score_strategy(strategy, values, model)
            if _setup(strategy, values, score):
                ranked.append((score, symbol))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        decisions[day] = [dict(symbol=symbol, weight=weight) for _, symbol in ranked[:3]]
    return decisions


def _baseline(prices, calendar, period):
    curve = []
    entry = {}
    last = {}
    by_day = {symbol: {row['date']: row['close'] for row in rows} for symbol, rows in prices.items()}
    for day in calendar:
        if not period['start'] <= day <= period['end']:
            continue
        for symbol, mapping in by_day.items():
            if day in mapping:
                last[symbol] = mapping[day]
                if symbol not in entry:
                    entry[symbol] = mapping[day]
        values = [last[symbol] / price for symbol, price in entry.items()]
        curve.append(dict(date=day, equity=fmean(values) if values else 1.))
    return dict(basis='same_current_cohort_equal_weight_price_basket_descriptive',
                metrics=_metrics(curve), equity=curve, cash_return=0.,
                caveats=['current_cohort_survivorship_bias', 'descriptive_unadjusted_price_basket_not_tradable_benchmark'])


def run_research(prices_by_symbol, *, names=None, config=None):
    config, names = config or ResearchConfig(), names or {}
    prices = {symbol: [row for row in rows if config.as_of is None or row['date'] <= config.as_of]
              for symbol, rows in sorted(prices_by_symbol.items())}
    prices = {symbol: rows for symbol, rows in prices.items() if rows}
    calendar = sorted({row['date'] for rows in prices.values() for row in rows})
    as_of = config.as_of or (calendar[-1] if calendar else None)
    protocol = dict(evaluation='recent_frozen_chronological_split', normalization='training_only',
                    champion_selection='validation_only', embargo_sessions=config.policy.horizon,
                    score_interpretation='ranking_score_not_probability', ridge_lambda=1.,
                    diagnostic_weight=.1, production_approval='held', strategy_ids=[row['strategy_id'] for row in STRATEGIES],
                    configuration=asdict(config), periods={}, feature_source=SOURCE_ACKNOWLEDGEMENT,
                    label='completed_actual_net_bracket_return', latest_model='frozen_evaluation_training_model')
    report = dict(as_of=as_of, champion=None, selection={}, strategies=[], candidates=[],
                  protocol=protocol, walkforward_folds=[], diagnostics=dict(held_reasons=[], training={}),
                  production_eligible=False, paper_only=True, live_orders=False, baseline={})
    needed = config.train_sessions + config.validation_sessions + config.test_sessions + 2 * config.policy.horizon
    if len(calendar) < needed:
        report['diagnostics']['held_reasons'] = ['insufficient_calendar_history']
        return report
    window = calendar[-needed:]
    train_end = config.train_sessions - 1
    validation_start = config.train_sessions + config.policy.horizon
    validation_end = validation_start + config.validation_sessions - 1
    test_start = validation_end + 1 + config.policy.horizon
    periods = dict(train=dict(start=window[0], end=window[train_end]),
                   validation=dict(start=window[validation_start], end=window[validation_end]),
                   test=dict(start=window[test_start], end=window[-1]))
    protocol['periods'] = periods
    model, training = fit_training_model(prices, periods['train']['end'], start_date=periods['train']['start'],
                                         step_sessions=config.step_sessions, policy=config.policy)
    report['diagnostics']['training'] = training
    report['walkforward_folds'] = [dict(fold=1, periods=periods, fit_cutoff=training['fit_cutoff'],
                                        model_sha256=training['model_sha256'], interpretation='one_recent_fixed_split_not_full_walkforward')]
    stress_policy = replace(config.policy, fee_bps=2 * config.policy.fee_bps,
                            slippage_bps=2 * config.policy.slippage_bps, sell_tax_bps=2 * config.policy.sell_tax_bps)
    cached = {}
    for catalogue in STRATEGIES:
        strategy = catalogue['strategy_id']
        decisions = {phase: _decisions(prices, calendar, periods[phase], config, strategy, model, .1, cached)
                     for phase in ('validation', 'test')}
        validation = _run_period(prices, decisions['validation'], periods['validation'], config.policy)
        test = _run_period(prices, decisions['test'], periods['test'], config.policy)
        stress = {phase: _run_period(prices, decisions[phase], periods[phase], stress_policy)
                  for phase in ('validation', 'test')}
        stops = [row['loss_fraction'] for row in validation['trades'] if row['status'] == 'closed']
        calibration = size_from_returns(validation['closed_net_returns'], max(stops, default=.08),
                                        stress_returns=stress['validation']['closed_net_returns'])
        weight = calibration['weight'] if calibration['qualified'] else 0.
        calibrated = {day: [dict(order, weight=weight) for order in orders] for day, orders in decisions['test'].items()}
        report['strategies'].append(dict(catalogue, diagnostic_allocation_weight=.1,
             diagnostic_approval='unapproved_research_comparison', validation=validation, test=test,
             calibration=calibration, calibrated_test=_run_period(prices, calibrated, periods['test'], config.policy),
             stress=dict(cost_multiplier=2., model_refitted=False, **stress)))
    ranked = sorted(report['strategies'], key=lambda row: (
        -(row['validation']['metrics']['net_total_return'] + .25 * row['validation']['metrics']['max_drawdown']), row['strategy_id']))
    qualified = [row for row in ranked if row['calibration']['qualified']
                 and row['validation']['metrics']['net_total_return'] > 0
                 and row['stress']['validation']['metrics']['net_total_return'] > 0]
    report['selection'] = dict(validation_ranking=[row['strategy_id'] for row in ranked],
                               objective='validation_net_return_plus_0.25_max_drawdown',
                               qualification='minimum_30_completed_net_outcomes_positive_t_and_cost_stress',
                               selected_strategy=qualified[0]['strategy_id'] if qualified else None)
    if qualified:
        report['champion'] = dict(strategy_id=qualified[0]['strategy_id'], name=qualified[0]['name'], selected_by='validation_only')
    else:
        report['diagnostics']['held_reasons'].append('no_validation_qualified_champion')
    chosen = qualified[0] if qualified else ranked[0]
    # Serving learns newly matured observations only after the frozen experiment
    # has been evaluated. It cannot rewrite comparison curves or select a winner.
    serving_model, serving_training = fit_training_model(prices, as_of,
        start_date=calendar[max(0, len(calendar) - config.train_sessions)],
        step_sessions=config.step_sessions, policy=config.policy)
    report['diagnostics']['serving_training'] = serving_training
    protocol.update(latest_model='separate_serving_refit_after_frozen_evaluation',
                    test_model='frozen_training_model')
    watch = []
    for symbol, rows in prices.items():
        if rows[-1]['date'] != as_of:
            report['diagnostics']['held_reasons'].append('stale_latest_quote:' + symbol)
            continue
        if rows[-1]['volume'] <= 0:
            report['diagnostics']['held_reasons'].append('nontradable_latest_quote:' + symbol)
            continue
        values = features_at(rows, len(rows) - 1)
        plan = build_bracket_plan(rows, policy=config.policy)
        if values is None or plan['status'] != 'ready':
            continue
        score = score_strategy(chosen['strategy_id'], values, serving_model)
        risk = size_from_returns(chosen['validation']['closed_net_returns'], plan['loss_fraction'],
                                 stress_returns=chosen['stress']['validation']['closed_net_returns'])
        name = names.get(symbol, symbol)
        if isinstance(name, dict):
            name = name.get('name', symbol)
        watch.append(dict(symbol=symbol, name=name, as_of=as_of, strategy=chosen['strategy_id'], strategy_id=chosen['strategy_id'], score=score,
                          score_interpretation='ranking_score_not_probability', last_close=rows[-1]['close'],
                          plan=plan, calibration=chosen['calibration'], risk=risk, approved_weight=0.,
                          proposed_weight=risk['weight'], setup_active=_setup(chosen['strategy_id'], values, score),
                          reasons=['research_only_cio_approval_required', *risk.get('held_reasons', [])]))
    report['candidates'] = sorted(watch, key=lambda row: (-row['score'], row['symbol']))[:3]
    report['baseline'] = _baseline(prices, calendar, periods['test'])
    return report
