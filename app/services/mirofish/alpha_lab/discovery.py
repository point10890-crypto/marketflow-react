"""Separate retrospective setup evidence, never a replacement tournament test.

The caller supplies its audited current financial-quality cohort. This fixed
policy selects one active setup per symbol on calibration evidence only, then
requires positive confirmation. Newly screened survivors remain exploratory;
current-cohort, corporate-action and source-vintage limitations still apply.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from datetime import date
import math
from statistics import fmean, stdev

from .execution import ExecutionPolicy, build_bracket_plan, simulate_trade
from .features import features_at
from .risk import size_from_returns
from ..kelly_position import two_point_kelly

POLICY_VERSION = 'quality-setup-opportunity-v1'
SELECTION_BASIS = 'calibration_stress_mean_then_confirmation'
STRATEGIES = ('momentum', 'liquidity_breakout', 'mean_reversion')
LOOKBACK, CALIBRATION, CONFIRMATION = 1260, 1008, 252


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('Discovery requires canonical session dates')
    return value


def _active_setup(strategy, values):
    if strategy == 'momentum':
        return values['momentum_20'] > 0 and values['momentum_60'] > 0
    if strategy == 'liquidity_breakout':
        return values['breakout_20'] >= -.02 and values['volume_ratio_20'] >= 1.2
    return values['momentum_5'] < -.02 or values['range_position_20'] < .25


def _features(rows, index, calendar, global_index, cache, diagnostics):
    key = (rows[index].get('symbol'), rows[index]['date'])
    if key not in cache:
        global_at = global_index[rows[index]['date']]
        window = [row['date'] for row in rows[max(0, index-60):index+1]]
        if global_at < 60 or len(window) < 61:
            cache[key] = None
            diagnostics['insufficient_factor_warmup'] += 1
        elif window != calendar[global_at-60:global_at+1]:
            cache[key] = None
            diagnostics['sparse_factor_window'] += 1
        else:
            cache[key] = features_at(rows, index)
    return cache[key]


def _summarize(trades, start, end):
    values = [row['net_return'] for row in trades]
    stressed = [row['stress_net_return'] for row in trades]
    if any(not math.isfinite(value) or value <= -1 for value in values+stressed):
        raise ValueError('Discovery outcomes must be finite realized net returns above minus one')
    n = len(values)
    mean = fmean(values) if values else None
    deviation = stdev(values) if n > 1 else 0.
    return dict(samples=n, wins=sum(value > 0 for value in values), losses=sum(value < 0 for value in values),
        zeros=sum(value == 0 for value in values), win_rate=sum(value > 0 for value in values)/n if n else None,
        mean_net_return=mean, stress_mean_net_return=fmean(stressed) if stressed else None,
        compounded_trade_return=math.prod(1+value for value in values)-1,
        stress_compounded_trade_return=math.prod(1+value for value in stressed)-1,
        return_basis='compounded_nonoverlapping_unit_notional_trades_not_account_allocation',
        start=start, end=end, last_exit_session=max((row['exit_date'] for row in trades), default=None),
        t_stat=mean/(deviation/math.sqrt(n)) if deviation > 0 else None)


def _collect_phase(rows, strategy, start, end, *, calendar, global_index, cache, policy):
    # Physical truncation prevents even excluded/open-label diagnostics from
    # reading the later phase. Each phase starts flat with causal warmup only.
    observed = [row for row in rows if row['date'] <= end]
    local_index = {row['date']: index for index, row in enumerate(observed)}
    diagnostics, trades, open_trades = Counter(), [], []
    stressed = replace(policy, fee_bps=2*policy.fee_bps, slippage_bps=2*policy.slippage_bps,
                       sell_tax_bps=2*policy.sell_tax_bps)
    index = next((index for index, row in enumerate(observed) if row['date'] >= start), len(observed))
    while index < len(observed):
        bar = observed[index]
        values = _features(observed, index, calendar, global_index, cache, diagnostics)
        if values is None or bar['volume'] <= 0 or not _active_setup(strategy, values):
            index += 1
            continue
        global_at = global_index[bar['date']]
        if (index+1 >= len(observed) or global_at+1 >= len(calendar)
                or observed[index+1]['date'] != calendar[global_at+1]):
            diagnostics['missing_next_union_quote'] += 1
            index += 1
            continue
        trade = simulate_trade(observed, index, policy)
        if not trade:
            diagnostics['unfilled_signal'] += 1
            index += 1
            continue
        if trade['status'] != 'closed' or not trade.get('exit_date') or trade['exit_date'] > end:
            open_trades.append(dict(trade))
            diagnostics['unresolved_phase_end'] += 1
            # This position is still open; later signals cannot overlap it.
            break
        exit_at = local_index[trade['exit_date']]
        exit_global = global_index[trade['exit_date']]
        if [row['date'] for row in observed[index+1:exit_at+1]] != calendar[global_at+1:exit_global+1]:
            diagnostics['sparse_holding_interval'] += 1
            index = max(index+1, exit_at)
            continue
        entry, exit_price = trade['entry_price'], trade['exit_price']
        trades.append(dict(trade,
            entry_cost_per_share=entry*policy.entry_cost, exit_cost_per_share=exit_price*policy.exit_cost,
            stress_entry_cost_per_share=entry*stressed.entry_cost,
            stress_exit_cost_per_share=exit_price*stressed.exit_cost,
            stress_net_return=exit_price*(1-stressed.exit_cost)/(entry*(1+stressed.entry_cost))-1))
        # An exit at today's close permits a fresh signal at that close, whose
        # next open is strictly after the completed position's exit session.
        index = max(index+1, exit_at)
    return dict(summary=_summarize(trades, start, end), trades=trades, open_trades=open_trades,
                diagnostics=dict(diagnostics))


def _phase_reasons(summary, minimum):
    reasons = []
    if summary['samples'] < minimum:
        reasons.append('insufficient_completed_outcomes')
    if summary['wins'] == 0 or summary['losses'] == 0:
        reasons.append('both_return_signs_required')
    for key in ('mean_net_return', 'stress_mean_net_return', 'compounded_trade_return', 'stress_compounded_trade_return'):
        if summary[key] is None or not math.isfinite(summary[key]) or summary[key] <= 0:
            reasons.append('nonpositive_'+key)
    return reasons


def _prepared(prices_by_symbol, as_of):
    if not isinstance(prices_by_symbol, dict) or len(prices_by_symbol) > 100:
        raise ValueError('Discovery requires at most TOP100 audited quality symbols')
    groups = {}
    for symbol, raw_rows in sorted(prices_by_symbol.items()):
        if not isinstance(symbol, str) or not isinstance(raw_rows, list):
            raise ValueError('Discovery requires symbol to ordered OHLCV-list input')
        rows, previous = [], None
        for raw in raw_rows:
            day = _day(raw['date'])
            if as_of is not None and day > as_of:
                continue
            if previous is not None and day <= previous:
                raise ValueError('Discovery price dates must be unique and increasing')
            if raw.get('symbol', symbol) != symbol:
                raise ValueError('Discovery symbol differs from price row')
            rows.append(dict(raw, symbol=symbol))
            previous = day
        if rows:
            groups[symbol] = rows
    return groups


def discover_opportunities(prices_by_symbol, *, names=None, as_of=None, reference_calendar=None):
    """Inspect current setups with one fixed conditional evidence policy.

    Rank/choose on calibration stress mean only; confirmation is pass/fail.
    Quarter net-Kelly is capped at 5%, and grants no automated approval.
    """
    if as_of is not None:
        _day(as_of)
    groups = _prepared(prices_by_symbol, as_of)
    observed_dates = {row['date'] for rows in groups.values() for row in rows}
    calendar = sorted(observed_dates)
    if reference_calendar is not None:
        if not isinstance(reference_calendar, list) or len(reference_calendar) > 20000:
            raise ValueError('Reference calendar requires a bounded ordered session list')
        calendar = [_day(day) for day in reference_calendar]
        if any(a >= b for a, b in zip(calendar, calendar[1:])):
            raise ValueError('Reference calendar sessions must be unique and increasing')
        if as_of is not None:
            calendar = [day for day in calendar if day <= as_of]
        if not observed_dates.issubset(calendar):
            raise ValueError('Reference calendar must cover every observed price session')
    latest = as_of or (calendar[-1] if calendar else None)
    policy = ExecutionPolicy()
    result = dict(policy_version=POLICY_VERSION, selection_basis=SELECTION_BASIS, latest_session=latest,
        lookback_sessions=LOOKBACK, calibration_sessions=CALIBRATION, confirmation_sessions=CONFIRMATION,
        horizon_sessions=policy.horizon, inspected_count=len(groups), eligible_count=0, active_setup_count=0,
        candidates=[], reasons=[], audit=[], diagnostics={}, policy=asdict(policy),
        cost_stress_multiplier=2., warnings=['new_retrospective_policy_not_untouched_validation',
            'current_quality_cohort_survivorship_bias', 'multiple_symbol_and_setup_screening',
            'source_vintage_and_corporate_action_adjustment_not_certified', 'research_weights_not_order_approval'])
    if len(calendar) < LOOKBACK:
        result['reasons'].append('insufficient_union_history')
        return result
    window = calendar[-LOOKBACK:]
    cal_start, cal_end, confirmation_start, confirmation_end = window[0], window[CALIBRATION-1], window[CALIBRATION], window[-1]
    global_index, cache, diagnostics, survivors = {day: index for index, day in enumerate(calendar)}, {}, Counter(), []
    for symbol, rows in sorted(groups.items()):
        name = (names or {}).get(symbol, symbol)
        if isinstance(name, dict):
            name = name.get('name', symbol)
        if not isinstance(name, str) or not name.strip():
            name = symbol
        if rows[-1]['date'] != latest or rows[-1]['volume'] <= 0:
            result['audit'].append(dict(symbol=symbol, strategy_id=None, setup_active=False, selected=False,
                                       eligible=False, reasons=['latest_quote_nontradable']))
            continue
        values = _features(rows, len(rows)-1, calendar, global_index, cache, diagnostics)
        plan = build_bracket_plan(rows)
        if values is None or plan['status'] != 'ready':
            result['audit'].append(dict(symbol=symbol, strategy_id=None, setup_active=False, selected=False,
                                       eligible=False, reasons=['latest_features_or_plan_unavailable']))
            continue
        choices = []
        for strategy in STRATEGIES:
            active = _active_setup(strategy, values)
            audit = dict(symbol=symbol, name=name, strategy_id=strategy, setup_active=active, selected=False,
                         eligible=False, calibration=None, confirmation=None, reasons=[] if active else ['setup_inactive'])
            result['audit'].append(audit)
            if not active:
                continue
            result['active_setup_count'] += 1
            phase = _collect_phase(rows, strategy, cal_start, cal_end, calendar=calendar,
                                   global_index=global_index, cache=cache, policy=policy)
            audit['calibration'] = phase
            diagnostics.update(phase['diagnostics'])
            audit['reasons'] = _phase_reasons(phase['summary'], 30)
            if not audit['reasons']:
                choices.append(audit)
        if not choices:
            diagnostics['no_calibration_qualified_setup'] += 1
            continue
        choices.sort(key=lambda item: (-item['calibration']['summary']['stress_mean_net_return'], item['strategy_id']))
        selected = choices[0]
        selected['selected'] = True
        phase = _collect_phase(rows, selected['strategy_id'], confirmation_start, confirmation_end,
                               calendar=calendar, global_index=global_index, cache=cache, policy=policy)
        selected['confirmation'] = phase
        diagnostics.update(phase['diagnostics'])
        selected['reasons'] = _phase_reasons(phase['summary'], 10)
        if selected['reasons']:
            diagnostics['selected_confirmation_failed'] += 1
            continue
        cal = selected['calibration']
        values_cal = [trade['net_return'] for trade in cal['trades']]
        diagnostic = two_point_kelly(values_cal)
        raw = diagnostic['raw_fraction']
        if diagnostic['status'] != 'ready' or raw is None or not math.isfinite(raw) or raw <= 0:
            selected['reasons'] = ['nonpositive_calibration_net_kelly']
            continue
        quarter = .25*raw
        weight = min(.05, quarter, .01/plan['loss_fraction'])
        strict_cal = size_from_returns(values_cal, plan['loss_fraction'],
            stress_returns=[trade['stress_net_return'] for trade in cal['trades']])
        strict_confirmation = size_from_returns([trade['net_return'] for trade in phase['trades']], plan['loss_fraction'],
            stress_returns=[trade['stress_net_return'] for trade in phase['trades']])
        stronger = strict_cal['qualified'] and strict_confirmation['qualified']
        reasons = ['manual_exploratory_research_only', 'source_and_cio_approval_required']
        if not stronger:
            reasons.append('stronger_statistical_evidence_not_met')
        selected['eligible'] = True
        survivors.append(dict(symbol=symbol, name=name, strategy_id=selected['strategy_id'],
            score=cal['summary']['stress_mean_net_return'], score_interpretation='calibration_stress_mean_not_probability',
            last_close=rows[-1]['close'], quote_session=rows[-1]['date'], setup_active=True, plan=plan,
            risk=dict(weight=0., status='held', research_weight=weight, p=diagnostic['p'], kelly_raw=raw,
                quarter_kelly_fraction=quarter, planned_account_risk=weight*plan['loss_fraction'], reasons=list(reasons)),
            reasons=reasons, evidence=dict(selection_basis=SELECTION_BASIS, stronger_evidence=stronger,
                calibration=dict(cal['summary']), confirmation=dict(phase['summary']),
                retrospective=True, independent_validation=False)))
    survivors.sort(key=lambda row: (-row['score'], row['symbol']))
    result['eligible_count'], result['candidates'], result['diagnostics'] = len(survivors), survivors[:3], dict(diagnostics)
    if not survivors:
        result['reasons'].append('no_positive_current_setup_evidence')
    return result
