"""Fixed causal price context within the current financial-quality cohort.

Original implementation adapted from the supplied AlphaTeam factor ideas.
Ranks describe observed prices, not trained committee votes or profit forecasts.
The attention metric uses close * volume, not actual traded amount. No IO,
selection, approval, execution, or portfolio allocation occurs here.
"""
from __future__ import annotations

from datetime import date
import math
import re
from statistics import fmean, stdev

ANALYST_IDS = ('rev_5', 'low_vol_60', 'anti_max_21', 'attention_fade')
POLICY_VERSION = 'quality-analyst-context-v1'
MIN_COMPARISON = 8


def _day(value):
    if not isinstance(value, str):
        raise ValueError('A canonical session date is required')
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise ValueError('A canonical session date is required')


def _symbol(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9]{6}', value) is None:
        raise ValueError('A six-digit symbol is required')
    return value


def _fingerprint(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('A SHA256 input fingerprint is required')
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Finite numeric observations are required')
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise ValueError('Finite numeric observations are required') from None
    if not math.isfinite(value):
        raise ValueError('Finite numeric observations are required')
    return value


def _observed(prices_by_symbol, as_of):
    groups, reasons, calendar = {}, {}, set()
    for symbol in prices_by_symbol:
        _symbol(symbol)
    for symbol, raw_rows in sorted(prices_by_symbol.items()):
        rows = []
        reason = None
        if raw_rows is None or isinstance(raw_rows, list) and not raw_rows:
            reason = 'missing_prices'
        elif not isinstance(raw_rows, list):
            reason = 'invalid_observation'
        else:
            previous = None
            for raw in raw_rows:
                try:
                    if not isinstance(raw, dict):
                        raise ValueError('Unknown price observation')
                    day = _day(raw.get('date'))
                except ValueError:
                    reason = 'invalid_observation'
                    continue
                if day > as_of:
                    # Future rows cannot influence validity, the market calendar,
                    # factor denominators, or comparison membership.
                    continue
                calendar.add(day)
                if previous is not None and day <= previous:
                    reason = 'invalid_observation'
                rows.append(raw)
                previous = day
        groups[symbol], reasons[symbol] = rows, reason
    return groups, reasons, sorted(calendar)


def _metrics(symbol, rows, calendar):
    if not rows:
        return None, 'missing_prices'
    if len(calendar) < 61:
        return None, 'insufficient_history'
    expected = calendar[-61:]
    if len(rows) < 61:
        reason = 'sparse_factor_window' if rows[0]['date'] <= expected[0] else 'insufficient_history'
        return None, reason
    window = rows[-61:]
    if [raw['date'] for raw in window] != expected:
        return None, 'sparse_factor_window'
    normalized = []
    for raw in window:
        if (raw.get('quality_flags') or raw.get('flags') or raw.get('invalid') is True
                or raw.get('valid') is False):
            return None, 'flagged_observation'
        try:
            if raw.get('symbol', symbol) != symbol:
                raise ValueError('Price symbol differs from cohort symbol')
            row = {key: _number(raw.get(key)) for key in ('open', 'high', 'low', 'close', 'volume')}
            if (min(row[key] for key in ('open', 'high', 'low', 'close')) <= 0 or row['volume'] < 0
                    or not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']):
                raise ValueError('Invalid OHLCV')
        except ValueError:
            return None, 'invalid_observation'
        normalized.append(row)
    if normalized[-1]['volume'] <= 0:
        return None, 'latest_quote_nontradable'
    try:
        closes = [row['close'] for row in normalized]
        returns = [_number(closes[i]/closes[i-1]-1) for i in range(1, 61)]
        amounts = [_number(row['close']*row['volume']) for row in normalized[-60:]]
        mean_amount = fmean(amounts)
        if mean_amount <= 0:
            return None, 'nonpositive_amount_mean'
        metrics = (closes[-1]/closes[-6]-1, stdev(returns)*math.sqrt(252),
                   max(returns[-21:]), fmean(amounts[-5:])/mean_amount)
        if (any(not math.isfinite(value) for value in metrics) or metrics[0] <= -1
                or metrics[1] < 0 or metrics[2] <= -1 or metrics[3] < 0):
            raise ValueError('Factor arithmetic exceeded finite bounds')
    except (ValueError, OverflowError):
        return None, 'invalid_observation'
    return metrics, None


def _stance(percentile):
    if percentile >= 66.666667:
        return 'favorable'
    if percentile <= 33.333333:
        return 'caution'
    return 'neutral'


def build_analyst_context(prices_by_symbol, *, as_of, input_fingerprint):
    """Return complete-cohort, lower-is-favorable ranks at one fixed cutoff."""
    _day(as_of)
    _fingerprint(input_fingerprint)
    if not isinstance(prices_by_symbol, dict):
        raise ValueError('Symbol to OHLCV-list cohort is required')
    groups, reasons, calendar = _observed(prices_by_symbol, as_of)
    metrics_by_symbol = {}
    for symbol, rows in groups.items():
        if reasons[symbol]:
            continue
        if rows and rows[-1]['date'] != as_of:
            reasons[symbol] = 'missing_current_quote'
            continue
        metrics, reasons[symbol] = _metrics(symbol, rows, calendar)
        if metrics is not None:
            metrics_by_symbol[symbol] = metrics
    n = len(metrics_by_symbol)
    result = {}
    for symbol in groups:
        ready = symbol in metrics_by_symbol and n >= MIN_COMPARISON
        analysts, counts = [], dict(favorable=0, caution=0, neutral=0)
        for i, identifier in enumerate(ANALYST_IDS):
            metric, percentile, stance = None, None, 'unavailable'
            if ready:
                metric = metrics_by_symbol[symbol][i]
                population = [values[i] for values in metrics_by_symbol.values()]
                greater = sum(value > metric for value in population)
                ties = sum(value == metric for value in population)
                percentile = round((greater+.5*(ties-1))/(n-1)*100, 6)
                stance = _stance(percentile)
                counts[stance] += 1
            analysts.append(dict(id=identifier, metric_value=metric, percentile=percentile, stance=stance))
        held_reasons = [reasons[symbol]] if reasons[symbol] else []
        if n < MIN_COMPARISON:
            held_reasons.append('insufficient_cohort')
        result[symbol] = dict(schema_version=1, policy_version=POLICY_VERSION, symbol=symbol,
            as_of=as_of, input_fingerprint=input_fingerprint, scope='current_quality_cohort',
            cohort_count=len(prices_by_symbol), comparison_count=n,
            status='ready' if ready else 'unavailable',
            score=round(fmean(row['percentile'] for row in analysts), 6) if ready else None,
            favorable_count=counts['favorable'], caution_count=counts['caution'], neutral_count=counts['neutral'],
            analysts=analysts, reasons=held_reasons)
    return result


def build_entry_guard(symbol, session, reference_price, input_fingerprint):
    """One manual reference ceiling; it is not an executed or backtested limit."""
    _symbol(symbol)
    _day(session)
    _fingerprint(input_fingerprint)
    reference = _number(reference_price)
    ceiling = round(reference*1.02, 6)
    if reference <= 0 or not math.isfinite(ceiling) or ceiling <= 0 or ceiling < reference:
        raise ValueError('A finite positive representable reference price is required')
    return dict(policy_version='reference-chase-cap-v1', symbol=symbol, as_of=session,
        input_fingerprint=input_fingerprint, reference_price=reference, max_chase_fraction=.02,
        max_entry_price=ceiling, applies_to='manual_next_open_reference', backtest_applied=False)
