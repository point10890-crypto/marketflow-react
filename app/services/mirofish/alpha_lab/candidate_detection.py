"""Fixed, causal cross-sectional research proposals; no I/O or order access.

The latest 756 union sessions contain 116 warmup, 504 formation, ten embargo
and 126 confirmation sessions. Both phases select the identical top-three
closing setups before inspecting their subsequent labels. Pooled events are
unit-notional trade observations, never an account equity curve. Ten-session
signal-date blocks describe shared calendar exposure, not IID stock samples.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
import math
import re
from statistics import fmean, median, stdev

from .execution import ExecutionPolicy
from .candidate_execution import build_candidate_reference_plan, simulate_candidate_trade

POLICY_VERSION = 'cross-sectional-candidates-v3'
LOOKBACK, FORMATION, EMBARGO, CONFIRMATION = 756, 504, 10, 126
MIN_TRADED_VALUE = 1_000_000_000.
SCORE_WEIGHT_POINTS = {'relative_return20': 45, 'momentum60': 30,
                       'prior_high_proximity': 15, 'volume_ratio': 10}
SCORE_WEIGHTS = {key: value/100 for key, value in SCORE_WEIGHT_POINTS.items()}
WARNINGS = ['retrospective_current_quality_cohort_not_point_in_time_universe',
            'historical_vintage_and_corporate_actions_unverified',
            'cohort_median_is_not_an_official_market_benchmark',
            'pooled_events_are_not_independent_market_alpha_or_account_pnl',
            'calendar_blocks_are_descriptive_not_calibrated_confidence',
            'research_reference_weight_does_not_approve_orders',
            'planned_stop_loss_can_be_exceeded_by_gaps']


def _day(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Candidate prices require canonical session dates') from None
    return value


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be a finite numeric value')
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f'{label} must be finite') from None
    if not math.isfinite(value) or value < 0 or positive and value == 0:
        raise ValueError(f'{label} is outside allowed bounds')
    return value


def _flags(raw):
    """Warning severity preserves source uncertainty without cancelling trades.

    Unknown/unstructured flags are conservative blockers; explicit warning/info
    severities remain auditable. Frozen execution rejects any quality_flags, so
    only these benign flags are removed from our private normalized copies.
    """
    if raw is None or raw == '' and isinstance(raw, str):
        return [], []
    if isinstance(raw, str):
        raw = re.split(r'[;|]', raw)
    if not isinstance(raw, list):
        raise ValueError('OHLCV quality_flags must be a list or string')
    blocked, warnings = [], []
    for flag in raw:
        if isinstance(flag, dict):
            code, severity = flag.get('code'), flag.get('severity')
            if not isinstance(code, str) or not code.strip() or not isinstance(severity, str):
                raise ValueError('OHLCV quality flag code and severity are required')
            (warnings if severity.lower() in {'warning', 'info'} else blocked).append(code[:160])
        elif isinstance(flag, str) and flag.strip():
            blocked.append(flag.strip()[:160])
        else:
            raise ValueError('OHLCV quality flag is malformed')
    return blocked, warnings


def _prepare(prices_by_symbol, as_of):
    if not isinstance(prices_by_symbol, dict) or len(prices_by_symbol) > 100:
        raise ValueError('Candidate detection requires at most 100 quality-cohort symbols')
    groups, warnings = {}, Counter()
    for symbol, raw_rows in sorted(prices_by_symbol.items()):
        if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}', symbol) or not isinstance(raw_rows, list):
            raise ValueError('Candidate detection requires six-digit symbols and OHLCV lists')
        rows, previous = [], None
        for raw in raw_rows:
            if not isinstance(raw, dict):
                raise ValueError('OHLCV observations must be objects')
            day = _day(raw.get('date'))
            # No numeric, identity or flag detail after the requested cutoff is
            # consulted; even malformed future peer rows cannot affect a run.
            if as_of is not None and day > as_of:
                continue
            if previous is not None and day <= previous:
                raise ValueError('OHLCV sessions must be unique and increasing')
            if raw.get('symbol', symbol) != symbol:
                raise ValueError('OHLCV symbol identity differs from its cohort key')
            row = dict(symbol=symbol, date=day)
            for key in ('open', 'high', 'low', 'close', 'volume'):
                row[key] = _number(raw.get(key), 'OHLCV '+key, positive=key != 'volume')
            if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
                raise ValueError('OHLCV extrema are inconsistent')
            row['traded_value'] = _number(raw.get('traded_value', row['close']*row['volume']), 'traded_value')
            blocked, benign = _flags(raw.get('quality_flags'))
            warnings.update(benign)
            if raw.get('tradable') is False:
                blocked.append('source_nontradable')
            if blocked:
                row['quality_flags'] = blocked
            rows.append(row)
            previous = day
        if rows:
            groups[symbol] = rows
    calendar = sorted({row['date'] for rows in groups.values() for row in rows})[-LOOKBACK:]
    if calendar:
        groups = {symbol: [row for row in rows if row['date'] >= calendar[0]]
                  for symbol, rows in groups.items()}
        groups = {symbol: rows for symbol, rows in groups.items() if rows}
    return groups, calendar, dict(sorted(warnings.items()))


def _valid(row):
    return not row.get('quality_flags') and row['volume'] > 0


def _strength_score(item, cohort):
    """Accumulate exact integer midrank points before one final division.

    This is the declared 45/30/15/10 percentile score on a 0..100 scale.
    Integer accumulation makes mathematically equal factor-rank combinations
    exact ties across Python's different floating summation implementations.
    """
    if len(cohort) <= 1:
        return 50.
    numerator = sum(weight*(2*sum(other[key] < item[key] for other in cohort)
                           + sum(other[key] == item[key] for other in cohort)-1)
                    for key, weight in SCORE_WEIGHT_POINTS.items())
    return numerator/(2*(len(cohort)-1))


class _Snapshots:
    def __init__(self, groups, calendar):
        self.groups, self.calendar = groups, calendar
        self.indices = {symbol: {row['date']: at for at, row in enumerate(rows)}
                        for symbol, rows in groups.items()}
        self.cache = {}

    def at(self, global_at):
        if global_at in self.cache:
            return self.cache[global_at]
        day, raw, returns = self.calendar[global_at], {}, []
        for symbol, rows in self.groups.items():
            at = self.indices[symbol].get(day)
            if at is None:
                raw[symbol] = dict(symbol=symbol, qualified=False, reasons=['latest_quote_missing'])
                continue
            window = rows[max(0, at-60):at+1]
            # The relative reference uses the same-date, contiguous, tradable
            # 21-bar cohort, including stocks that fail the trend setup.
            short = rows[max(0, at-20):at+1]
            if (global_at >= 20 and len(short) == 21
                    and [row['date'] for row in short] == self.calendar[global_at-20:global_at+1]
                    and all(_valid(row) for row in short)):
                returns.append(short[-1]['close']/short[0]['close']-1)
            reasons = []
            if global_at < 60 or len(window) < 61:
                reasons.append('insufficient_factor_warmup')
            elif [row['date'] for row in window] != self.calendar[global_at-60:global_at+1]:
                reasons.append('sparse_factor_window')
            if any(row.get('quality_flags') for row in window):
                reasons.append('quality_flagged_factor_window')
            if not _valid(rows[at]):
                reasons.append('latest_quote_nontradable')
            item = dict(symbol=symbol, qualified=False, reasons=reasons)
            if not reasons:
                closes = [row['close'] for row in window]
                previous_volume = fmean(row['volume'] for row in window[-21:-1])
                item.update(close=closes[-1], sma20=fmean(closes[-20:]), sma60=fmean(closes[-60:]),
                            return20=closes[-1]/closes[-21]-1, momentum60=closes[-1]/closes[0]-1,
                            average_traded_value20=fmean(row['traded_value'] for row in window[-20:]),
                            prior_high_proximity=closes[-1]/max(row['high'] for row in window[-21:-1]),
                            volume_ratio=min(3., rows[at]['volume']/previous_volume) if previous_volume > 0 else 0.)
            raw[symbol] = item
        reference = median(returns) if returns else None
        metric_items = [item for item in raw.values() if 'return20' in item]
        for item in metric_items:
            item.update(cohort_median_return20=reference, cohort_samples=len(returns),
                        relative_return20=item['return20']-reference if reference is not None else None)
            for condition, reason in (
                (item['close'] > item['sma60'], 'close_not_above_sma60'),
                (item['sma20'] > item['sma60'], 'sma20_not_above_sma60'),
                (item['return20'] > 0, 'nonpositive_return20'),
                (item['momentum60'] > 0, 'nonpositive_return60'),
                (reference is not None and item['return20'] > reference, 'relative_strength_not_positive'),
                (item['average_traded_value20'] >= MIN_TRADED_VALUE, 'insufficient_average_traded_value'),
                (item['close'] <= item['sma20']*1.12, 'extension_above_sma20'),
            ):
                if not condition:
                    item['reasons'].append(reason)
            item['qualified'] = not item['reasons']
        # Score current structure only. Outcomes and symbol-level historical
        # profits never enter these same-date, prefix-valid cohort percentiles.
        rank_cohort = [item for item in metric_items if item['relative_return20'] is not None]
        for item in rank_cohort:
            item['strength_score'] = _strength_score(item, rank_cohort)
        ranked = sorted((item for item in metric_items if item['qualified']),
                        key=lambda item: (-item['strength_score'], item['symbol']))
        for rank, item in enumerate(ranked, 1):
            item['rank'] = rank
        self.cache[global_at] = ranked, [raw[symbol] for symbol in sorted(raw)]
        return self.cache[global_at]


def _summary(trades, calendar, start_at, end_at):
    start = calendar[start_at] if start_at is not None else None
    end = calendar[end_at] if end_at is not None else None
    blocks, indices = defaultdict(list), {day: at for at, day in enumerate(calendar)}
    for trade in trades:
        block = (indices[trade['signal_date']]-start_at)//10
        blocks[block].append(trade)
    values, stressed = [trade['net_return'] for trade in trades], [trade['stress_net_return'] for trade in trades]
    block_rows = [dict(block=index, start=calendar[start_at+index*10],
                       end=calendar[min(end_at, start_at+index*10+9)], samples=len(events),
                       unique_symbols=len({event['symbol'] for event in events}),
                       mean_net_return=fmean(event['net_return'] for event in events),
                       stress_mean_net_return=fmean(event['stress_net_return'] for event in events))
                  for index, events in sorted(blocks.items())]
    block_values = [block['stress_mean_net_return'] for block in block_rows]
    return dict(start=start, end=end, samples=len(trades), wins=sum(value > 0 for value in values),
                win_rate=sum(value > 0 for value in values)/len(values) if values else None,
                mean_net_return=fmean(values) if values else None,
                stress_mean_net_return=fmean(stressed) if stressed else None,
                unique_symbols=len({trade['symbol'] for trade in trades}), block_count=len(block_rows),
                blocks=block_rows, block_stress_stats=dict(samples=len(block_values),
                    mean=fmean(block_values) if block_values else None,
                    standard_deviation=stdev(block_values) if len(block_values) > 1 else None,
                    minimum=min(block_values) if block_values else None,
                    maximum=max(block_values) if block_values else None,
                    positive_blocks=sum(value > 0 for value in block_values)),
                return_basis='pooled_selected_unit_notional_trade_returns_not_account_pnl',
                uncertainty_basis='nonoverlapping_10_session_signal_date_blocks_not_iid_peers')


def _phase(snapshots, calendar, start_at, end_at, policy):
    end, blocked_until, trades, diagnostics = calendar[end_at], {}, [], Counter()
    observed = {symbol: [row for row in rows if row['date'] <= end]
                for symbol, rows in snapshots.groups.items()}
    for global_at in range(start_at, end_at+1):
        day = calendar[global_at]
        # Top three is determined before holdings, execution or outcome labels.
        selected = snapshots.at(global_at)[0][:3]
        for item in selected:
            symbol = item['symbol']
            if blocked_until.get(symbol, '') > day:
                diagnostics['same_symbol_position_open'] += 1
                continue
            rows, at = observed[symbol], snapshots.indices[symbol][day]
            if (at+1 >= len(rows) or global_at+1 >= len(calendar)
                    or rows[at+1]['date'] != calendar[global_at+1]):
                diagnostics['missing_next_union_quote'] += 1
                continue
            trade = simulate_candidate_trade(rows, at, policy)
            if not trade:
                diagnostics['unfilled_signal'] += 1
                continue
            if trade['status'] != 'closed' or not trade.get('exit_date') or trade['exit_date'] > end:
                blocked_until[symbol] = end+'~'
                diagnostics['unresolved_phase_end'] += 1
                continue
            blocked_until[symbol] = trade['exit_date']
            exit_at = snapshots.indices[symbol][trade['exit_date']]
            expected = calendar[global_at+1:global_at+1+trade['holding_sessions']]
            interval = rows[at+1:exit_at+1]
            if [row['date'] for row in interval] != expected or any(not _valid(row) for row in interval):
                diagnostics['sparse_or_nontradable_holding_interval'] += 1
                continue
            entry, exit_price = trade['entry_price'], trade['exit_price']
            stress_return = exit_price*(1-2*policy.exit_cost)/(entry*(1+2*policy.entry_cost))-1
            trades.append(dict(trade, selection_rank=item['rank'], strength_score=item['strength_score'],
                               stress_net_return=stress_return))
    return dict(summary=_summary(trades, calendar, start_at, end_at), trades=trades,
                diagnostics=dict(sorted(diagnostics.items())))


def _phase_reasons(summary, prefix, minimum, blocks, *, unique=0):
    reasons = []
    if summary['samples'] < minimum:
        reasons.append(prefix+'_insufficient_completed_events')
    if summary['block_count'] < blocks:
        reasons.append(prefix+'_insufficient_calendar_blocks')
    if summary['unique_symbols'] < unique:
        reasons.append(prefix+'_insufficient_unique_symbols')
    for key in ('mean_net_return', 'stress_mean_net_return'):
        if summary[key] is None or summary[key] <= 0:
            reasons.append(prefix+'_nonpositive_'+key)
    return reasons


def empirical_long_only_kelly(returns):
    """Maximize mean log(1+f*r) over 0<=f<=1 using formation net returns.

    This is an empirical long-only optimum, with no leverage or probability
    calibration. The final reference allocation uses one quarter of this raw
    value and its independent allocation/stop-risk caps.
    """
    values = list(returns)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value < -1 for value in values):
        raise ValueError('Kelly requires finite net returns at least minus one')
    if not values or fmean(values) <= 0:
        return 0.
    def derivative(fraction):
        return fmean(value/(1+fraction*value) for value in values)
    if min(values) > -1 and derivative(1.) >= 0:
        return 1.
    low, high = 0., 1.
    for _ in range(64):
        middle = (low+high)/2
        if derivative(middle) > 0:
            low = middle
        else:
            high = middle
    return (low+high)/2


def discover_candidates(prices_by_symbol, *, names=None, as_of=None):
    """Return up to three conditional proposals under the fixed v3 policy."""
    if as_of is not None:
        _day(as_of)
    if names is not None and not isinstance(names, dict):
        raise ValueError('Candidate names must be a symbol mapping')
    groups, calendar, warnings = _prepare(prices_by_symbol, as_of)
    policy = ExecutionPolicy()
    empty = _summary([], calendar, None, None)
    result = dict(policy_version=POLICY_VERSION, latest_session=calendar[-1] if calendar else None,
                  inspected_count=len(groups), eligible_count=0, candidates=[], funnel=[], reasons=[],
                  rejection_counts={}, evidence=dict(formation=empty, confirmation=dict(empty), embargo=None),
                  audit=dict(current=[], current_ranking=[], phases={}, source_warnings=warnings),
                  policy=dict(execution=asdict(policy), lookback_sessions=LOOKBACK, formation_sessions=FORMATION,
                              embargo_sessions=EMBARGO, confirmation_sessions=CONFIRMATION,
                              score_weights=dict(SCORE_WEIGHTS), score_interpretation='current_structure_rank_not_probability',
                              entry_policy='frozen_signal_upper_and_barriers_gate_next_open_then_actual_open_atr_bracket',
                              cost_stress_multiplier=2., kelly_model='empirical_log_growth_long_only_0_to_1'),
                  warnings=list(WARNINGS))
    snapshots = _Snapshots(groups, calendar)
    ranked, current = snapshots.at(len(calendar)-1) if calendar else ([], [])
    result['audit'].update(current=current, current_ranking=ranked)
    current_plans = {item['symbol']: build_candidate_reference_plan(groups[item['symbol']], policy=policy)
                     for item in ranked}
    reasons = result['reasons']
    if len(calendar) < LOOKBACK:
        reasons.append('insufficient_union_history')
    else:
        formation_start = LOOKBACK-FORMATION-EMBARGO-CONFIRMATION
        formation_end = formation_start+FORMATION-1
        confirmation_start = formation_end+EMBARGO+1
        result['evidence']['embargo'] = dict(start=calendar[formation_end+1],
                                            end=calendar[confirmation_start-1], sessions=EMBARGO)
        for key, start, end in (('formation', formation_start, formation_end),
                                ('confirmation', confirmation_start, LOOKBACK-1)):
            phase = _phase(snapshots, calendar, start, end, policy)
            result['audit']['phases'][key] = dict(trades=phase['trades'], diagnostics=phase['diagnostics'])
            result['evidence'][key] = phase['summary']
        reasons.extend(_phase_reasons(result['evidence']['formation'], 'formation', 30, 5, unique=5))
        reasons.extend(_phase_reasons(result['evidence']['confirmation'], 'confirmation', 10, 3))
    rejection_counts = Counter(reason for row in current for reason in row['reasons'])
    rejection_counts.update({reason: max(1, len(ranked)) for reason in reasons})
    invalid_plans = sum(plan['status'] != 'ready' for plan in current_plans.values())
    if invalid_plans:
        rejection_counts['current_entry_band_invalid'] = invalid_plans
    if not ranked:
        reasons.append('no_current_setup')
        rejection_counts['no_current_setup'] += 1
    if not reasons:
        raw = empirical_long_only_kelly([trade['net_return'] for trade in result['audit']['phases']['formation']['trades']])
        result['eligible_count'] = len(ranked)-invalid_plans
        for item in ranked[:3]:
            symbol, rows = item['symbol'], groups[item['symbol']]
            plan = current_plans[symbol]
            if plan['status'] != 'ready':
                continue
            name = (names or {}).get(symbol, symbol)
            if isinstance(name, dict):
                name = name.get('name')
            name = name.strip()[:120] if isinstance(name, str) and name.strip() else symbol
            weight = min(.05, .25*raw, .01/plan['loss_fraction'])
            traded_value = format(item['average_traded_value20'], ',.0f' if item['average_traded_value20'] < 1e15 else '.5g')
            result['candidates'].append(dict(symbol=symbol, name=name, rank=item['rank'],
                strength_score=item['strength_score'], quote_session=calendar[-1],
                reason_facts=[f"20-session return {item['return20']:.2%}; cohort median {item['cohort_median_return20']:.2%}.",
                              f"60-session return {item['momentum60']:.2%}; SMA20 above SMA60.",
                              f"20-session average traded value KRW {traded_value}.",
                              f"Prior-20-high ratio {item['prior_high_proximity']:.3f}; volume ratio capped at 3: {item['volume_ratio']:.2f}."],
                plan=dict(entry_price=plan['entry_price'], entry_upper=plan['entry_upper'],
                          stop_price=plan['stop_price'], target_price=plan['target_price'],
                          horizon_sessions=policy.horizon, loss_fraction=plan['loss_fraction']),
                risk=dict(reference_weight=weight, raw_kelly=raw, kelly_fraction=.25, adjusted_kelly=.25*raw,
                          planned_account_loss=weight*plan['loss_fraction'], approved_exposure=0., live_orders=False)))
    result['rejection_counts'] = dict(sorted(rejection_counts.items()))
    result['funnel'] = [dict(id='inspected', label='Inspected quality-cohort symbols', count=len(groups)),
                        dict(id='current_setup', label='Current fixed setup passed', count=len(ranked)),
                        dict(id='pooled_evidence', label='Pooled evidence qualified', count=len(ranked) if not reasons else 0),
                        dict(id='eligible', label='Eligible conditional proposals', count=result['eligible_count']),
                        dict(id='returned', label='Returned proposals (maximum three)', count=len(result['candidates']))]
    return result
