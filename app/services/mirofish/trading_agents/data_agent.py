"""Scope and validate supplied data; no network, credentials or price imputation."""
from __future__ import annotations

import copy
import math
import re
from datetime import date, datetime, time, timedelta, timezone

from ..large_cap_universe import evaluate_quality, select_large_caps
from .models import AgentMessage, create_message


SOURCE_KEYS = ('universe', 'prices', 'current_financials', 'fundamentals')
KST = timezone(timedelta(hours=9))


def _day(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} must use YYYY-MM-DD')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{label} must use YYYY-MM-DD') from error
    if parsed.isoformat() != value:
        raise ValueError(f'{label} must use YYYY-MM-DD')
    return parsed


def _timestamp(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be an aware ISO timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError(f'{label} must be an aware ISO timestamp') from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f'{label} must be an aware ISO timestamp')
    return parsed


def _number(value, label, *, minimum=0):
    try:
        finite = isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite or value < minimum:
        raise ValueError(f'{label} must be a finite nonnegative number')
    return value


def _scoped_rows(rows, symbols, label):
    if not isinstance(rows, list):
        raise ValueError(f'{label} must be a list')
    selected = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('symbol'), str):
            raise ValueError(f'{label} rows must contain a symbol')
        if row['symbol'] in symbols:
            selected.append(dict(row))
    return selected


def _evidence(evidence, now):
    if not isinstance(evidence, dict):
        raise ValueError('evidence must be a dictionary')
    reasons = []
    for flag in ('price_adjustment_verified', 'financial_vintage_verified', 'synthetic', 'trusted_fixture'):
        if flag in evidence and not isinstance(evidence[flag], bool):
            raise ValueError(f'{flag} must be a boolean')
    for flag in ('price_adjustment_verified', 'financial_vintage_verified'):
        if evidence.get(flag) is not True:
            reasons.append(flag + '_missing_or_unverified')
    synthetic = evidence.get('synthetic', False)
    if synthetic and evidence.get('trusted_fixture') is not True:
        reasons.append('untrusted_synthetic_fixture')
    timestamps, hashes = evidence.get('source_timestamps', {}), evidence.get('source_hashes', {})
    if not isinstance(timestamps, dict) or not isinstance(hashes, dict):
        raise ValueError('source_timestamps and source_hashes must be dictionaries')
    for source in SOURCE_KEYS:
        if not timestamps.get(source):
            reasons.append('missing_source_timestamp:' + source)
        elif _timestamp(timestamps[source], source + ' capture') > now:
            reasons.append('future_source_capture:' + source)
        if not hashes.get(source):
            reasons.append('missing_source_hash:' + source)
        elif not isinstance(hashes[source], str) or not re.fullmatch(r'[0-9a-fA-F]{64}', hashes[source]):
            raise ValueError(f'{source} source hash must be 64 hexadecimal SHA-256 digits')
    return reasons


def _prices(rows, symbols, as_of):
    prices = _scoped_rows(rows, symbols, 'prices')
    seen, reasons = set(), []
    for row in prices:
        day = _day(row.get('date'), 'price date')
        if day > as_of:
            raise ValueError('Price date cannot follow as_of')
        key = (row['symbol'], day)
        if key in seen:
            raise ValueError('Duplicate price symbol/date')
        seen.add(key)
        _number(row.get('close'), 'close')
        for field in ('open', 'high', 'low', 'volume'):
            if field in row:
                _number(row[field], field)
        flags = row.get('quality_flags', [])
        if isinstance(flags, str):
            flags = [flag for flag in flags.split(';') if flag.strip()]
        if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
            raise ValueError('price quality_flags must be a string or a list of strings')
        invalid = bool(flags) or row['close'] <= 0
        invalid |= any(row[field] <= 0 for field in ('open', 'high', 'low') if field in row)
        invalid |= row.get('volume', 0) <= 0
        if ('high' in row) != ('low' in row):
            raise ValueError('Both high and low must be supplied together')
        if 'high' in row and 'low' in row:
            opening = row.get('open', row['close'])
            invalid |= not row['low'] <= min(opening, row['close']) <= max(opening, row['close']) <= row['high']
        if invalid:
            reason = 'price_quality_flags:' + row['symbol']
            if reason not in reasons:
                reasons.append(reason)
    present = {row['symbol'] for row in prices}
    reasons.extend('missing_prices:' + symbol for symbol in sorted(symbols - present))
    return prices, reasons


def _fundamentals(rows, symbols, as_of):
    fundamentals = _scoped_rows(rows, symbols, 'fundamentals')
    seen = set()
    for row in fundamentals:
        available = _day(row.get('available_date'), 'fundamental available_date')
        if available > as_of:
            raise ValueError('Fundamental available_date cannot follow as_of')
        key = (row['symbol'], available)
        if key in seen:
            raise ValueError('Duplicate fundamental symbol/available_date')
        seen.add(key)
        _number(row.get('market_cap'), 'historical market_cap')
        _number(row.get('debt_ratio'), 'historical debt_ratio')
        if not isinstance(row.get('tradable'), bool):
            raise ValueError('fundamental tradable must be a boolean')
    present = {row['symbol'] for row in fundamentals}
    return fundamentals, ['missing_fundamentals:' + symbol for symbol in sorted(symbols - present)]


class DataAgent:
    def __init__(self, now=None):
        if now is not None and (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None):
            raise ValueError('DataAgent clock must be an aware datetime')
        self._now = now

    async def handle(self, message: AgentMessage) -> AgentMessage:
        if not isinstance(message, AgentMessage) or message.stage != 'request':
            raise ValueError('DataAgent requires a request message')
        payload = copy.deepcopy(message.payload)
        request = payload.get('input')
        if not isinstance(request, dict):
            raise ValueError('request payload requires input')
        as_of = _day(request.get('as_of'), 'as_of')
        now = self._now or datetime.now(timezone.utc)
        local_now = now.astimezone(KST)
        ranking = select_large_caps(request.get('universe', []), request['as_of'], top_n=100)
        ranked = ranking['ranked']
        cohort = {row['symbol'] for row in ranked}
        current = _scoped_rows(request.get('current_financials', []), cohort, 'current_financials')
        quality = evaluate_quality(ranked, current, request['as_of'])
        eligible = [row['symbol'] for row in quality['passed']]
        evidence = request.get('evidence', {})
        reasons = _evidence(evidence, now)
        if as_of > local_now.date():
            reasons.append('future_as_of')
        elif as_of == local_now.date() and local_now.timetz().replace(tzinfo=None) < time(15, 30):
            reasons.append('as_of_not_closed')
        for row in current:
            if row.get('fetched_at') and _timestamp(row['fetched_at'], 'financial fetched_at') > now:
                reasons.append('future_current_financial_capture:' + row['symbol'])
        if not eligible:
            reasons.append('no_quality_eligible_symbols')
        metadata = {'current_cohort_bias': True, 'historical_point_in_time': False, 'refill_after_quality': False,
                    'win_rate_certified': False, 'future_win_probability_certified': False,
                    'performance_claims_allowed': False, 'research_only': True,
                    'synthetic': evidence.get('synthetic', False), 'ranked_count': len(ranked),
                    'quality_pass_count': len(eligible), 'source_timestamps': evidence.get('source_timestamps', {}),
                    'source_hashes': evidence.get('source_hashes', {}),
                    'price_adjustment_verified': evidence.get('price_adjustment_verified') is True,
                    'financial_vintage_verified': evidence.get('financial_vintage_verified') is True}
        prices, fundamentals = [], []
        if not reasons:
            splits = request.get('splits')
            if not isinstance(splits, dict):
                raise ValueError('splits must contain train_end, validation_end and test_end')
            train = _day(splits.get('train_end'), 'train_end')
            validation = _day(splits.get('validation_end'), 'validation_end')
            test = _day(splits.get('test_end'), 'test_end')
            if not train < validation < test <= as_of:
                raise ValueError('Splits must be ordered and cannot follow as_of')
            config = request.get('config', {})
            if not isinstance(config, dict) or any(not isinstance(config[key], dict) for key in ('research', 'risk') if key in config):
                raise ValueError('config research/risk overrides must be dictionaries')
            prices, price_reasons = _prices(request.get('prices', []), set(eligible), as_of)
            fundamentals, fundamental_reasons = _fundamentals(request.get('fundamentals', []), set(eligible), as_of)
            reasons.extend(price_reasons + fundamental_reasons)
        data = {'status': 'blocked' if reasons else 'ready', 'reasons': reasons, 'ranked': ranked,
                'quality': quality, 'prices': prices, 'fundamentals': fundamentals,
                'eligible_symbols': eligible, 'metadata': metadata}
        payload['data'] = data
        return create_message(message.run_id, 'data', payload, parent_id=message.message_id)
