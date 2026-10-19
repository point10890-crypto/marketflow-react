"""Fixed causal recovery research; v1 remains the frozen evolution control.

Every current and historical setup uses the same dated trend, cohort-relative
strength, traded-value and recovery gate. Labels are recomputed with the shared
next-session execution engine; recent evidence is a subset of those labels.
No market calls, model calls, order approval or parameter search occurs here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import math
from statistics import fmean, median

from . import discovery as v1
from .execution import ExecutionPolicy, build_bracket_plan
from .risk import size_from_returns
from ..kelly_position import two_point_kelly

POLICY_VERSION = 'quality-setup-opportunity-v2'
SELECTION_BASIS = 'causal_recovery_recent_stress_then_confirmation'
RECENT_SESSIONS, RECENT_MINIMUM = 126, 5
MIN_AVERAGE_TRADED_VALUE = 1_000_000_000.


def _positive_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


class _CausalSetupGate:
    """Memoize only same-session or earlier facts in the supplied quality cohort."""

    def __init__(self, groups, calendar, global_index):
        self.groups, self.calendar, self.global_index = groups, calendar, global_index
        self.indices = {symbol: {row['date']: index for index, row in enumerate(rows)}
                        for symbol, rows in groups.items()}
        self.medians, self.metrics = {}, {}

    def _cohort(self, day):
        if day not in self.medians:
            global_at = self.global_index[day]
            expected = self.calendar[max(0, global_at-20):global_at+1]
            returns = []
            for symbol, rows in self.groups.items():
                at = self.indices[symbol].get(day)
                if at is None or at < 20 or global_at < 20:
                    continue
                prefix = rows[at-20:at+1]
                if ([row['date'] for row in prefix] != expected
                        or any(row.get('quality_flags') or not _positive_number(row.get('close')) for row in prefix)
                        or not _positive_number(prefix[-1].get('volume'))):
                    continue
                value = prefix[-1]['close']/prefix[0]['close']-1
                if math.isfinite(value):
                    returns.append(value)
            self.medians[day] = (median(returns) if returns else None, len(returns))
        return self.medians[day]

    def assessment(self, rows, index, strategy, values):
        bar = rows[index]
        key = (bar['symbol'], bar['date'])
        if key not in self.metrics:
            window = rows[max(0, index-60):index+1]
            global_at = self.global_index[bar['date']]
            reasons = []
            if len(window) < 61 or global_at < 60:
                reasons.append('insufficient_factor_warmup')
            elif [row['date'] for row in window] != self.calendar[global_at-60:global_at+1]:
                reasons.append('sparse_factor_window')
            if any(row.get('quality_flags') for row in window):
                reasons.append('quality_flagged_factor_window')
            metrics = dict(session=bar['date'], reference='same_dated_quality_cohort_median_not_official_index')
            if not reasons:
                closes = [row['close'] for row in window]
                sma20, sma60 = fmean(closes[-20:]), fmean(closes[-60:])
                value20 = fmean(row['close']*row['volume'] for row in window[-20:])
                return20 = closes[-1]/closes[-21]-1
                reference, count = self._cohort(bar['date'])
                excess = return20-reference if reference is not None else None
                metrics.update(close=closes[-1], sma20=sma20, sma60=sma60,
                    return20=return20, cohort_median_return20=reference,
                    relative_return20=excess, cohort_samples=count, average_traded_value20=value20)
                if not _positive_number(bar.get('volume')):
                    reasons.append('latest_quote_nontradable')
                if closes[-1] <= sma60:
                    reasons.append('close_not_above_sma60')
                if sma20 <= sma60:
                    reasons.append('sma20_not_above_sma60')
                if excess is None or not math.isfinite(excess) or excess <= 0:
                    reasons.append('relative_strength_not_positive')
                if not math.isfinite(value20) or value20 < MIN_AVERAGE_TRADED_VALUE:
                    reasons.append('insufficient_average_traded_value')
            self.metrics[key] = (metrics, reasons)
        metrics, base_reasons = self.metrics[key]
        reasons = list(base_reasons)
        if not v1._active_setup(strategy, values):
            reasons.append('setup_inactive')
        if (strategy == 'mean_reversion' and index > 0
                and not (bar['close'] > rows[index-1]['high'] and bar['close'] > bar['open'])):
            reasons.append('recovery_confirmation_missing')
        return dict(metrics, qualified=not reasons, reasons=reasons)

    def __call__(self, rows, index, strategy, values):
        return self.assessment(rows, index, strategy, values)['qualified']


def _recent_phase(confirmation, start, end):
    # Keep the actual nonoverlapping confirmation path. Restarting at the tail
    # boundary would create different positions and discard boundary exposure.
    trades = [dict(row) for row in confirmation['trades'] if row['entry_date'] >= start]
    open_trades = [dict(row) for row in confirmation['open_trades'] if row.get('entry_date', '') >= start]
    return dict(summary=v1._summarize(trades, start, end), trades=trades, open_trades=open_trades,
                diagnostics={}, selection='confirmation_completed_trades_with_entry_in_recent_sessions')


def _recent_reasons(summary):
    reasons = []
    if summary['samples'] < RECENT_MINIMUM:
        reasons.append('recent_insufficient_completed_outcomes')
    for key in ('mean_net_return', 'stress_mean_net_return', 'compounded_trade_return', 'stress_compounded_trade_return'):
        if summary[key] is None or not math.isfinite(summary[key]) or summary[key] <= 0:
            reasons.append('recent_nonpositive_'+key)
    return reasons


def discover_opportunities_v2(prices_by_symbol, *, names=None, as_of=None, reference_calendar=None, candidate_limit=3):
    """Find recoveries with historically identical gates and a positive recent tail.

    Strategy selection remains calibration-only; confirmation/recent tests are
    pass/fail with no runner-up retry. Statistical strength is not independent
    validation, and reference weights never grant investment approval.
    """
    if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int) or not 1 <= candidate_limit <= 100:
        raise ValueError('candidate_limit must be an integer from one through 100')
    if as_of is not None:
        v1._day(as_of)
    groups = v1._prepared(prices_by_symbol, as_of)
    observed_dates = {row['date'] for rows in groups.values() for row in rows}
    calendar = sorted(observed_dates)
    if reference_calendar is not None:
        if not isinstance(reference_calendar, list) or len(reference_calendar) > 20000:
            raise ValueError('Reference calendar requires a bounded ordered session list')
        calendar = [v1._day(day) for day in reference_calendar]
        if any(a >= b for a, b in zip(calendar, calendar[1:])):
            raise ValueError('Reference calendar sessions must be unique and increasing')
        if as_of is not None:
            calendar = [day for day in calendar if day <= as_of]
        if not observed_dates.issubset(calendar):
            raise ValueError('Reference calendar must cover every observed price session')
    latest = as_of or (calendar[-1] if calendar else None)
    policy = ExecutionPolicy()
    result = dict(policy_version=POLICY_VERSION, selection_basis=SELECTION_BASIS, latest_session=latest,
        lookback_sessions=v1.LOOKBACK, calibration_sessions=v1.CALIBRATION, confirmation_sessions=v1.CONFIRMATION,
        recent_sessions=RECENT_SESSIONS, recent_minimum_completed=RECENT_MINIMUM,
        horizon_sessions=policy.horizon, inspected_count=len(groups), eligible_count=0, active_setup_count=0,
        candidates=[], reasons=[], audit=[], diagnostics={}, policy=asdict(policy),
        cost_stress_multiplier=2., warnings=['new_retrospective_policy_not_untouched_validation',
            'current_quality_cohort_survivorship_bias', 'multiple_symbol_and_setup_screening',
            'source_vintage_and_corporate_action_adjustment_not_certified', 'research_weights_not_order_approval'])
    if len(calendar) < v1.LOOKBACK:
        result['reasons'].append('insufficient_union_history')
        return result
    window = calendar[-v1.LOOKBACK:]
    cal_start, cal_end = window[0], window[v1.CALIBRATION-1]
    confirmation_start, confirmation_end = window[v1.CALIBRATION], window[-1]
    recent_start = window[-RECENT_SESSIONS]
    result['recent_start_session'] = recent_start
    global_index, cache, diagnostics, survivors = {day: index for index, day in enumerate(calendar)}, {}, Counter(), []
    gate = _CausalSetupGate(groups, calendar, global_index)
    for symbol, rows in sorted(groups.items()):
        name = (names or {}).get(symbol, symbol)
        if isinstance(name, dict):
            name = name.get('name', symbol)
        if not isinstance(name, str) or not name.strip():
            name = symbol
        if rows[-1]['date'] != latest or not _positive_number(rows[-1].get('volume')):
            result['audit'].append(dict(symbol=symbol, strategy_id=None, setup_active=False, selected=False,
                                       eligible=False, reasons=['latest_quote_nontradable']))
            continue
        values = v1._features(rows, len(rows)-1, calendar, global_index, cache, diagnostics)
        plan = build_bracket_plan(rows)
        if values is None or plan['status'] != 'ready':
            global_at = global_index[rows[-1]['date']]
            current_window = [row['date'] for row in rows[-61:]]
            sparse = (len(current_window) == 61 and global_at >= 60
                      and current_window != calendar[global_at-60:global_at+1])
            reason = 'sparse_factor_window' if sparse else 'latest_features_or_plan_unavailable'
            result['audit'].append(dict(symbol=symbol, strategy_id=None, setup_active=False, selected=False,
                                       eligible=False, reasons=[reason]))
            continue
        choices = []
        for strategy in v1.STRATEGIES:
            setup = gate.assessment(rows, len(rows)-1, strategy, values)
            active = setup['qualified']
            audit = dict(symbol=symbol, name=name, strategy_id=strategy, setup_active=active, selected=False,
                eligible=False, calibration=None, confirmation=None, recent=None, current_setup=setup,
                reasons=list(setup['reasons']))
            result['audit'].append(audit)
            if not active:
                continue
            result['active_setup_count'] += 1
            phase = v1._collect_phase(rows, strategy, cal_start, cal_end, calendar=calendar,
                global_index=global_index, cache=cache, policy=policy, setup_predicate=gate)
            audit['calibration'] = phase
            diagnostics.update(phase['diagnostics'])
            audit['reasons'] = v1._phase_reasons(phase['summary'], 30)
            if not audit['reasons']:
                choices.append(audit)
        if not choices:
            diagnostics['no_calibration_qualified_setup'] += 1
            continue
        choices.sort(key=lambda item: (-item['calibration']['summary']['stress_mean_net_return'], item['strategy_id']))
        selected = choices[0]
        selected['selected'] = True
        phase = v1._collect_phase(rows, selected['strategy_id'], confirmation_start, confirmation_end,
            calendar=calendar, global_index=global_index, cache=cache, policy=policy, setup_predicate=gate)
        selected['confirmation'] = phase
        recent = _recent_phase(phase, recent_start, confirmation_end)
        selected['recent'] = recent
        diagnostics.update(phase['diagnostics'])
        selected['reasons'] = v1._phase_reasons(phase['summary'], 10) + _recent_reasons(recent['summary'])
        if selected['reasons']:
            diagnostics['selected_confirmation_or_recent_failed'] += 1
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
                calibration=dict(cal['summary']), confirmation=dict(phase['summary']), recent=dict(recent['summary']),
                current_setup=selected['current_setup'], retrospective=True, independent_validation=False)))
    survivors.sort(key=lambda row: (-row['score'], row['symbol']))
    result['eligible_count'], result['candidates'], result['diagnostics'] = len(survivors), survivors[:candidate_limit], dict(diagnostics)
    if not survivors:
        result['reasons'].append('no_positive_current_setup_evidence')
    return result
