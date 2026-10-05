"""Causal price leadership context inside the current financial-quality cohort.

The fixed rank combines trend quality, 52-week high proximity, and 63-session
return. It is inspired by rule F, without a trained committee, market-wide
universe, profit forecast, portfolio selection, allocation, or execution.
"""
from __future__ import annotations

import math
import re
from statistics import fmean, stdev

from .analyst_context import _day, _fingerprint, _number, _observed, _symbol

POLICY_VERSION = 'quality-leadership-context-v1'
MIN_COMPARISON = 8
WINDOW = 252
CHECK_KEYS = ('top3', 'fresh', 'trend', 'near_high')


def _name(symbol, names):
    value = names.get(symbol)
    if not isinstance(value, str):
        return symbol
    value = value.strip()
    if (not value or len(value) > 80 or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
            or any(char in value for char in '<>/\\')
            or re.search(r'bearer|\.env|^[a-z]:', value, re.IGNORECASE)):
        return symbol
    return value


def _metrics(symbol, rows, calendar, as_of):
    if not rows:
        return None, 'missing_prices'
    if rows[-1]['date'] != as_of:
        return None, 'missing_current_quote'
    if len(calendar) < WINDOW:
        return None, 'insufficient_history'
    expected = calendar[-WINDOW:]
    if len(rows) < WINDOW:
        return None, 'sparse_factor_window' if rows[0]['date'] <= expected[0] else 'insufficient_history'
    window = rows[-WINDOW:]
    if [raw['date'] for raw in window] != expected:
        return None, 'sparse_factor_window'
    closes = []
    for i, raw in enumerate(window):
        if (raw.get('quality_flags') or raw.get('flags') or raw.get('invalid') is True
                or raw.get('valid') is False):
            return None, 'flagged_observation'
        try:
            if raw.get('symbol', symbol) != symbol:
                raise ValueError('Price identity differs from cohort identity')
            row = {key: _number(raw.get(key)) for key in ('open', 'high', 'low', 'close', 'volume')}
            if (min(row[key] for key in ('open', 'high', 'low', 'close')) <= 0 or row['volume'] < 0
                    or not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']):
                raise ValueError('Invalid OHLCV')
        except ValueError:
            return None, 'invalid_observation'
        if row['volume'] == 0:
            return None, 'latest_quote_nontradable' if i == WINDOW - 1 else 'nontradable_observation'
        closes.append(row['close'])
    try:
        close = closes[-1]
        ma50, ma150, ma200 = (fmean(closes[-n:]) for n in (50, 150, 200))
        previous_ma200 = fmean(closes[-220:-20])
        hi, lo = max(closes), min(closes)
        ret21, ret63 = (_number(close / closes[-n-1] - 1) for n in (21, 63))
        log_returns = [math.log(_number(closes[i] / closes[i-1])) for i in range(WINDOW - 120, WINDOW)]
        sd = stdev(log_returns)
        quality = _number(fmean(log_returns) / sd) if sd > 0 else None
        from_high = _number(close / hi - 1)
        strict = bool(close > ma50 > ma150 > ma200 and ma200 > previous_ma200
                      and close >= .75 * hi and close >= 1.3 * lo)
        return dict(reference_price=close, ret_21=ret21, ret_63=ret63, from_high_252=from_high,
                    trend_quality=quality, above_ma200=bool(close > ma200), strict=strict,
                    near_high=bool(close >= .75 * hi)), None
    except (ValueError, OverflowError, ZeroDivisionError):
        return None, 'invalid_observation'


def _percentiles(metrics, key):
    values = [row[key] for row in metrics.values()]
    count = len(values)
    if count == 1:
        return {symbol: .5 for symbol in metrics}
    return {symbol: (sum(value < row[key] for value in values)
                    + .5 * (sum(value == row[key] for value in values) - 1)) / (count - 1)
            for symbol, row in metrics.items()}


def _row(symbol, names, metrics, reasons, ranks, enough):
    data = metrics.get(symbol)
    if data is None:
        return dict(symbol=symbol, name=_name(symbol, names), rank=None, status='unavailable',
                    reference_price=None, ret_21=None, ret_63=None, from_high_252=None, trend_quality=None,
                    checks={key: None for key in CHECK_KEYS}, points=0, available_checks=0,
                    reasons=[reasons.get(symbol) or 'missing_prices'])
    rank = ranks.get(symbol)
    checks = dict(top3=rank is not None and rank <= 3 if enough else None,
                  fresh=bool(.10 <= data['ret_21'] <= .40), trend=data['strict'], near_high=data['near_high'])
    held_reasons = [] if enough else ['insufficient_cohort']
    if data['trend_quality'] is None:
        held_reasons.append('undefined_trend_quality')
    return dict(symbol=symbol, name=_name(symbol, names), rank=rank, status='ready',
                **{key: data[key] for key in ('reference_price', 'ret_21', 'ret_63', 'from_high_252', 'trend_quality')},
                checks=checks, points=sum(value is True for value in checks.values()),
                available_checks=sum(value is not None for value in checks.values()), reasons=held_reasons)


def build_leadership_context(prices_by_symbol, *, names, as_of, input_fingerprint, source_audit_hash,
                             selected_symbols):
    """Return selected annotations and up to seven strict-trend observations.

    Every price window consists of 252 contiguous sessions on the observed
    cohort's union calendar, cut before validating or counting future rows.
    The selected list is supplied by the decision engine and never changed.
    """
    _day(as_of)
    _fingerprint(input_fingerprint)
    _fingerprint(source_audit_hash)
    if not isinstance(prices_by_symbol, dict) or not isinstance(names, dict):
        raise ValueError('Canonical price and name mappings are required')
    if not isinstance(selected_symbols, (list, tuple)):
        raise ValueError('A selected symbol sequence is required')
    for symbol in selected_symbols:
        _symbol(symbol)
    if len(set(selected_symbols)) != len(selected_symbols):
        raise ValueError('Selected symbols must be distinct')
    groups, reasons, calendar = _observed(prices_by_symbol, as_of)
    metrics = {}
    for symbol, rows in groups.items():
        if reasons[symbol]:
            continue
        data, reasons[symbol] = _metrics(symbol, rows, calendar, as_of)
        if data is not None:
            metrics[symbol] = data
    count = len(metrics)
    enough = count >= MIN_COMPARISON
    strict = {symbol: data for symbol, data in metrics.items()
              if data['strict'] and data['trend_quality'] is not None}
    ranks = {}
    if enough and strict:
        factors = [_percentiles(strict, key) for key in ('trend_quality', 'from_high_252', 'ret_63')]
        composite = {symbol: fmean(factor[symbol] for factor in factors) for symbol in strict}
        ordered = sorted(strict, key=lambda symbol: (-composite[symbol], symbol))
        ranks = {symbol: i for i, symbol in enumerate(ordered, start=1)}
    above = sum(data['above_ma200'] for data in metrics.values())
    ratio = above / count if enough else None
    state = 'unknown' if ratio is None else 'broad' if ratio >= .6 else 'mixed' if ratio >= .4 else 'weak'
    selected = [_row(symbol, names, metrics, reasons, ranks, enough) for symbol in selected_symbols]
    selected_set = set(selected_symbols)
    watch_symbols = [symbol for symbol in ranks if symbol not in selected_set][:7]
    return dict(policy_version=POLICY_VERSION, input_fingerprint=input_fingerprint, source_audit_hash=source_audit_hash,
                latest_session=as_of, status='ready' if enough else 'unavailable',
                cohort=dict(inspected=len(prices_by_symbol), valid=count, above_ma200=above,
                            strict_trend=sum(data['strict'] for data in metrics.values())),
                market=dict(basis='quality_cohort_price_breadth', state=state, ratio=ratio),
                selected=selected, watchlist=[_row(symbol, names, metrics, reasons, ranks, enough) for symbol in watch_symbols])
