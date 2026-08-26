"""L1 market-regime classifier — lookahead-safe market-breadth (MA-based).

Deterministic, no LLM, no network. For each date D, breadth is the fraction
of tickers whose current_price on D is above the simple moving average of
the prior `ma_window` days (i.e. days strictly before D). Regime label is
derived from breadth thresholds.
"""

import os
import csv
import json
import math
from datetime import date as date_type
from datetime import datetime, timezone

from app.utils.atomic_json import write_json_atomic

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
PRICE_HISTORY_PATH = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')
REGIME_TIMELINE_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'intelligence', 'regime_timeline.json')

MA_WINDOW = 20
RISK_ON_BREADTH = 0.60
RISK_OFF_BREADTH = 0.40
PRICE_DEDUPE_POLICY = 'latest_valid_update_time_then_source_order.v1'
REGIME_METHOD_VERSION = 'mirofish.regime.breadth.v2'


def _safe_float(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _valid_iso_date(value):
    text = str(value or '').strip()
    try:
        return date_type.fromisoformat(text).isoformat()
    except (TypeError, ValueError):
        return None


def _update_rank(value, source_order):
    """Return a deterministic rank for a source row.

    `daily_prices.csv` normally uses an ISO-like local timestamp without a
    timezone.  Parsed timestamps sort chronologically; a missing/malformed
    timestamp sorts before every parsed timestamp.  The source row order is a
    deterministic final tie breaker, so an identical input always selects the
    same record.
    """
    text = str(value or '').strip()
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        timestamp_rank = parsed.isoformat(timespec='microseconds')
        return (1, timestamp_rank, source_order)
    except (TypeError, ValueError):
        return (0, '', source_order)


def _valid_price_row(row, required_price_fields):
    values = {}
    for field in required_price_fields:
        value = _safe_float(row.get(field))
        if value is None or value <= 0:
            return None, 'invalid_numeric_price'
        values[field] = value
    if 'high' in values and 'low' in values:
        low = values['low']
        high = values['high']
        if high < low:
            return None, 'invalid_ohlc_bounds'
        for field in ('open', 'current_price', 'close'):
            if field in values and not low <= values[field] <= high:
                return None, 'invalid_ohlc_bounds'
    return values, None


def _compact_selected_row(ticker, normalized_date, values):
    """Keep only replay/breadth fields so the 1.7M-row corpus stays bounded."""
    return {'ticker': ticker, 'date': normalized_date, **values}


def load_deduplicated_daily_rows(
        path=PRICE_HISTORY_PATH, *, symbols=None,
        required_price_fields=('current_price',)):
    """Load one deterministic latest-valid row per ``(ticker, date)``.

    A candidate is valid when its key is present, the date is ISO formatted,
    every requested price field is finite and positive, and high is not below
    low when both are requested.  Among valid candidates the greatest parsed
    ``update_time`` wins; malformed/missing timestamps rank oldest and a later
    source row breaks ties.  The returned quality metadata makes every dropped
    or conflicting duplicate explicit instead of silently inflating breadth.

    Returns ``(rows, quality)``.  ``rows`` contains raw CSV dictionaries in
    ticker/date order.  With ``symbols`` set, both rows and duplicate statistics
    intentionally describe that requested-symbol scope, while
    ``source_rows_total`` still describes the complete file scan.
    """
    requested = {str(symbol).strip() for symbol in symbols} if symbols is not None else None
    required = tuple(str(field) for field in required_price_fields)
    quality = {
        'schema_version': 'mirofish.daily_price_quality.v1',
        'dedupe_policy': PRICE_DEDUPE_POLICY,
        'scope': 'requested_symbols' if requested is not None else 'all_symbols',
        'requested_symbols': len(requested) if requested is not None else None,
        'source_rows_total': 0,
        'source_rows_in_scope': 0,
        'valid_candidate_rows': 0,
        'rejected_rows': 0,
        'invalid_key_rows': 0,
        'invalid_price_rows': 0,
        'invalid_numeric_price_rows': 0,
        'invalid_ohlc_rows': 0,
        'invalid_update_time_rows': 0,
        'selected_rows': 0,
        'duplicate_rows_removed': 0,
        'duplicate_keys': 0,
        'conflicting_duplicate_keys': 0,
        'max_candidates_per_key': 0,
        'min_data_date': None,
        'max_data_date': None,
    }
    if not os.path.isfile(path):
        quality['error'] = 'price_file_missing'
        return [], quality

    selected = {}
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for source_order, row in enumerate(csv.DictReader(f), start=2):
                quality['source_rows_total'] += 1
                ticker = str(row.get('ticker') or '').strip()
                if requested is not None and ticker not in requested:
                    continue
                quality['source_rows_in_scope'] += 1
                normalized_date = _valid_iso_date(row.get('date'))
                if not ticker or not normalized_date:
                    quality['rejected_rows'] += 1
                    quality['invalid_key_rows'] += 1
                    continue
                values, price_error = _valid_price_row(row, required)
                if values is None:
                    quality['rejected_rows'] += 1
                    quality['invalid_price_rows'] += 1
                    if price_error == 'invalid_ohlc_bounds':
                        quality['invalid_ohlc_rows'] += 1
                    else:
                        quality['invalid_numeric_price_rows'] += 1
                    continue

                update_time = str(row.get('update_time') or '').strip()
                rank = _update_rank(update_time, source_order)
                if rank[0] == 0:
                    quality['invalid_update_time_rows'] += 1
                quality['valid_candidate_rows'] += 1
                key = (ticker, normalized_date)
                fingerprint = tuple(values[field] for field in required)
                state = selected.get(key)
                if state is None:
                    # Compact list state is intentional: the complete corpus has
                    # ~1.8M rows and a dict-per-state would add hundreds of MB.
                    # [rank, selected_values, count, first_values, conflicting]
                    selected[key] = [rank, fingerprint, 1, fingerprint, False]
                    continue
                state[2] += 1
                if fingerprint != state[3]:
                    state[4] = True
                if rank > state[0]:
                    state[0] = rank
                    state[1] = fingerprint
    except (OSError, csv.Error, UnicodeError) as exc:
        quality['error'] = f'price_file_read_failed:{type(exc).__name__}'
        return [], quality

    rows = []
    min_date = None
    max_date = None
    for key in sorted(selected):
        state = selected.pop(key)
        ticker, row_date = key
        values = {field: state[1][index] for index, field in enumerate(required)}
        rows.append(_compact_selected_row(ticker, row_date, values))
        count = int(state[2])
        if count > 1:
            quality['duplicate_keys'] += 1
            quality['duplicate_rows_removed'] += count - 1
        if state[4]:
            quality['conflicting_duplicate_keys'] += 1
        quality['max_candidates_per_key'] = max(quality['max_candidates_per_key'], count)
        min_date = row_date if min_date is None else min(min_date, row_date)
        max_date = row_date if max_date is None else max(max_date, row_date)

    quality['selected_rows'] = len(rows)
    quality['min_data_date'] = min_date
    quality['max_data_date'] = max_date
    return rows, quality


def _deduplicate_price_mapping(prices):
    """Apply the same latest-valid policy to caller-provided price mappings."""
    selected = {}
    quality = {
        'schema_version': 'mirofish.daily_price_quality.v1',
        'dedupe_policy': PRICE_DEDUPE_POLICY,
        'scope': 'provided_mapping',
        'source_rows_total': 0,
        'source_rows_in_scope': 0,
        'valid_candidate_rows': 0,
        'rejected_rows': 0,
        'invalid_key_rows': 0,
        'invalid_price_rows': 0,
        'invalid_numeric_price_rows': 0,
        'invalid_ohlc_rows': 0,
        'invalid_update_time_rows': 0,
        'selected_rows': 0,
        'duplicate_rows_removed': 0,
        'duplicate_keys': 0,
        'conflicting_duplicate_keys': 0,
        'max_candidates_per_key': 0,
        'min_data_date': None,
        'max_data_date': None,
    }
    source_order = 0
    for raw_ticker, raw_rows in sorted((prices or {}).items(), key=lambda item: str(item[0])):
        ticker = str(raw_ticker or '').strip()
        for raw_row in (raw_rows or []):
            source_order += 1
            quality['source_rows_total'] += 1
            quality['source_rows_in_scope'] += 1
            row = raw_row if isinstance(raw_row, dict) else {}
            normalized_date = _valid_iso_date(row.get('date'))
            if not ticker or not normalized_date:
                quality['rejected_rows'] += 1
                quality['invalid_key_rows'] += 1
                continue
            values, price_error = _valid_price_row(row, ('current_price',))
            if values is None:
                quality['rejected_rows'] += 1
                quality['invalid_price_rows'] += 1
                if price_error == 'invalid_ohlc_bounds':
                    quality['invalid_ohlc_rows'] += 1
                else:
                    quality['invalid_numeric_price_rows'] += 1
                continue
            rank = _update_rank(row.get('update_time'), source_order)
            if rank[0] == 0:
                quality['invalid_update_time_rows'] += 1
            quality['valid_candidate_rows'] += 1
            key = (ticker, normalized_date)
            fingerprint = (values['current_price'],)
            state = selected.get(key)
            normalized = {'date': normalized_date, 'current_price': values['current_price']}
            if state is None:
                selected[key] = {
                    'row': normalized, 'rank': rank, 'count': 1,
                    'first_fingerprint': fingerprint, 'conflicting': False,
                }
                continue
            state['count'] += 1
            if fingerprint != state['first_fingerprint']:
                state['conflicting'] = True
            if rank > state['rank']:
                state['row'] = normalized
                state['rank'] = rank

    by_ticker = {}
    min_date = None
    max_date = None
    for (ticker, row_date), state in sorted(selected.items()):
        by_ticker.setdefault(ticker, []).append(state['row'])
        count = int(state['count'])
        if count > 1:
            quality['duplicate_keys'] += 1
            quality['duplicate_rows_removed'] += count - 1
        if state['conflicting']:
            quality['conflicting_duplicate_keys'] += 1
        quality['max_candidates_per_key'] = max(quality['max_candidates_per_key'], count)
        min_date = row_date if min_date is None else min(min_date, row_date)
        max_date = row_date if max_date is None else max(max_date, row_date)
    quality['selected_rows'] = len(selected)
    quality['min_data_date'] = min_date
    quality['max_data_date'] = max_date
    return by_ticker, quality


def load_universe_prices(path=PRICE_HISTORY_PATH, *, return_quality=False):
    """Load per-ticker price series from CSV, sorted by date ascending.

    Returns {ticker: [{'date': ..., 'current_price': float}, ...]}.
    Missing file -> {}. Rows with bad/missing/non-positive price are skipped.
    """
    by_ticker = {}
    rows, quality = load_deduplicated_daily_rows(path)
    for row in rows:
        ticker = row.pop('ticker')
        by_ticker.setdefault(ticker, []).append(row)
    return (by_ticker, quality) if return_quality else by_ticker


def build_regime_timeline(prices=None, *, ma_window=MA_WINDOW, write=True):
    """Build the lookahead-safe regime timeline from per-ticker price series."""
    if prices is None:
        prices, data_quality = load_universe_prices(return_quality=True)
    else:
        prices, data_quality = _deduplicate_price_mapping(prices)

    counts = {}  # date -> {'above': int, 'total': int}

    try:
        for ticker, rows in (prices or {}).items():
            n = len(rows)
            for i in range(n):
                if i < ma_window:
                    continue
                window = rows[i - ma_window:i]
                if len(window) < ma_window:
                    continue
                ma = sum(r['current_price'] for r in window) / ma_window
                date = rows[i]['date']
                bucket = counts.setdefault(date, {'above': 0, 'total': 0})
                bucket['total'] += 1
                if rows[i]['current_price'] > ma:
                    bucket['above'] += 1
    except Exception:
        counts = {}

    by_date = {}
    for date, c in counts.items():
        total = c['total']
        above = c['above']
        breadth = (above / total) if total > 0 else 0.0
        if breadth >= RISK_ON_BREADTH:
            label = 'RISK_ON'
        elif breadth <= RISK_OFF_BREADTH:
            label = 'RISK_OFF'
        else:
            label = 'NEUTRAL'
        by_date[date] = {
            'breadth': round(breadth, 4),
            'regime': label,
            'above': above,
            'total': total,
        }

    envelope = {
        'schema_version': 'mirofish.regime_timeline.v2',
        'method_version': REGIME_METHOD_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'ma_window': ma_window,
        'data_quality': data_quality,
        'by_date': by_date,
    }

    if write:
        try:
            os.makedirs(os.path.dirname(REGIME_TIMELINE_PATH), exist_ok=True)
            write_json_atomic(REGIME_TIMELINE_PATH, envelope, sort_keys=False)
        except Exception:
            pass

    return envelope


def classify_regime(entry_date, timeline):
    """Return the regime label for entry_date, falling back to the most
    recent prior date in the timeline. Defaults to 'NEUTRAL'."""
    if not timeline or not isinstance(timeline, dict):
        return 'NEUTRAL'

    by_date = timeline.get('by_date') or {}
    if not by_date:
        return 'NEUTRAL'

    entry = by_date.get(entry_date)
    if entry:
        return entry.get('regime', 'NEUTRAL')

    candidates = [d for d in by_date.keys() if d <= entry_date]
    if not candidates:
        return 'NEUTRAL'

    latest = max(candidates)
    return by_date.get(latest, {}).get('regime', 'NEUTRAL')


def read_regime_timeline():
    """Read the regime timeline JSON file. Missing/corrupt -> None."""
    if not os.path.isfile(REGIME_TIMELINE_PATH):
        return None
    try:
        with open(REGIME_TIMELINE_PATH, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None
