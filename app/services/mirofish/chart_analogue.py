"""Read-only historical chart analogues, built offline from observed daily closes.

The distribution is an unweighted empirical description of similar historical
windows, not a calibrated probability. The v1 index supports a 252-session input
and up to 40 observed future sessions. It never changes scanner ranking.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import tempfile
import threading
import zipfile
from collections import Counter, deque
from datetime import date, datetime, time, timedelta, timezone
from itertools import islice
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
INDEX_ROOT = Path(os.environ.get('MIROFISH_CHART_ANALOGUE_ROOT', REPO_ROOT / 'data' / 'chart_analogue'))
MODEL_VERSION = 'historical-chart-analogue-v1-calendar10'
INDEX_NAME = 'chart_analogue.npz'
KST = timezone(timedelta(hours=9))
EPOCH = date(1970, 1, 1)
LOOKBACK = 252
MAX_HORIZON = 40
MIN_SAMPLES = 5
MAX_ROWS = 3_000_000
MAX_SYMBOLS = 8_000
MAX_WINDOWS = 350_000
MAX_ARCHIVE_BYTES = 192 * 1024 * 1024
MAX_GAP_DAYS = 14
STALE_DAYS = 7
_LOCK = threading.RLock()
_CACHE = {}
_WARNINGS = [
    'Historical analogues are shadow evidence; forward efficacy has not been validated.',
    'Up frequency is an empirical sample frequency, not a calibrated probability.',
    'Samples can share market regimes and are not statistically independent.',
    'Gross close-to-close returns exclude trading costs and slippage.',
]


def _warnings(price_basis='unadjusted'):
    basis = ('Source closes are provider-adjusted snapshots; historic adjustments may be revised later.'
             if price_basis == 'provider_adjusted' else
             'Source closes are unadjusted; suspected corporate-action discontinuities are excluded.')
    return [*_WARNINGS, basis]


def _iso(timestamp):
    return datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat().replace('+00:00', 'Z')


def _iso_us(timestamp):
    seconds, microseconds = divmod(int(timestamp), 1_000_000)
    return (datetime.fromtimestamp(seconds, timezone.utc) + timedelta(microseconds=microseconds)).isoformat().replace('+00:00', 'Z')


def _date(day):
    return (EPOCH + timedelta(days=int(day))).isoformat()


def _cutoff(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError) as error:
        raise ValueError('as_of must be an ISO timestamp with an explicit timezone') from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('as_of must be an ISO timestamp with an explicit timezone')
    return result.astimezone(timezone.utc)


def _capture(value, microseconds=False):
    if not value or not re.search(r'[T ]\d{2}:\d{2}', str(value)):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
        # The collector writes local Korean wall-clock update_time values.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        # A capture at .900 seconds must never appear available at .100 seconds.
        return round(parsed.timestamp() * 1_000_000) if microseconds else math.ceil(parsed.timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def _valid_span(closes, dates):
    if len(closes) < 2 or not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        return False
    return bool(np.all(np.diff(dates) > 0) and np.all(np.diff(dates) <= MAX_GAP_DAYS)
                and np.all(np.abs(closes[1:] / closes[:-1] - 1) <= 0.35))


def _feature(closes):
    # Shape plus amplitude and realised daily volatility; no learned parameters.
    logs = np.log(closes)
    positions = np.linspace(0, len(closes) - 1, 32)
    shape = np.interp(positions, np.arange(len(closes)), logs)
    shape -= shape.mean()
    scale = float(np.sqrt(np.mean(shape * shape)))
    shape /= max(scale, 1e-8)
    summary = [(logs[-1] - logs[0]) / 0.2, np.std(np.diff(logs)) * math.sqrt(252) / 0.5]
    return np.concatenate((shape, np.clip(summary, -10, 10))).astype(np.float32)


def _rolling_max(values, width):
    result = np.zeros(len(values), dtype=np.int64)
    queue = deque()
    for index, value in enumerate(values):
        while queue and queue[0] <= index - width:
            queue.popleft()
        while queue and values[queue[-1]] <= value:
            queue.pop()
        queue.append(index)
        result[index] = values[queue[0]]
    return result


def build_index(csv_path=None, index_root=None, price_basis='unadjusted', source_id='local_daily_prices'):
    """Offline-only builder. Publish all data and metadata in one atomic archive.

    Duplicate sessions keep their earliest valid completed capture, avoiding a
    revised value being represented as knowable at an earlier cutoff. Invalid
    prices/captures remain barriers rather than silently shortened timelines.
    """
    source = Path(csv_path) if csv_path is not None else REPO_ROOT / 'data' / 'daily_prices.csv'
    if price_basis not in {'unadjusted', 'provider_adjusted'} or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', source_id):
        raise ValueError('A supported price basis and bounded source identifier are required')
    destination = Path(index_root) if index_root is not None else Path(INDEX_ROOT)
    rejected = Counter({key: 0 for key in ['bad_price', 'intraday', 'unknown_capture',
                                          'duplicate_sessions', 'bad_symbol', 'bad_date',
                                          'non_session_date', 'invalid_windows', 'raw_discontinuities', 'large_gaps']})
    groups = {}
    names = {}
    collection_statuses = {}
    date_cache, capture_cache = {}, {}
    raw_rows = 0
    with source.open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'ticker', 'date', 'current_price', 'update_time'}.issubset(reader.fieldnames or []):
            raise ValueError('Price CSV requires ticker,date,current_price,update_time columns')
        for row in reader:
            raw_rows += 1
            if raw_rows > MAX_ROWS:
                raise ValueError(f'Price corpus exceeds the {MAX_ROWS} row bound')
            if row.get('price_basis') and row['price_basis'] != price_basis or row.get('source_id') and row['source_id'] != source_id:
                raise ValueError('CSV price basis/source must match the declared index source')
            collection_status = row.get('collection_status') or 'untracked'
            if collection_status not in {'fresh', 'cache_preserved', 'untracked'}:
                raise ValueError('CSV collection status is unsupported')
            symbol = str(row.get('ticker', '')).strip()
            if not re.fullmatch(r'\d{6}', symbol, flags=re.ASCII):
                rejected['bad_symbol'] += 1
                continue
            raw_date = str(row.get('date', '')).strip()
            if raw_date not in date_cache:
                try:
                    parsed_day = date.fromisoformat(raw_date)
                    date_cache[raw_date] = ((parsed_day - EPOCH).days,
                                            int(datetime.combine(parsed_day, time(15, 30), KST).timestamp()))
                except ValueError:
                    date_cache[raw_date] = None
            day_info = date_cache[raw_date]
            if day_info is None:
                rejected['bad_date'] += 1
                continue
            day, market_close = day_info
            if (EPOCH + timedelta(days=day)).weekday() >= 5:
                rejected['non_session_date'] += 1
                continue
            capture_text = str(row.get('update_time', '')).strip()
            if capture_text not in capture_cache:
                capture_cache[capture_text] = (_capture(capture_text), _capture(capture_text, microseconds=True))
            captured, captured_actual_us = capture_cache[capture_text]
            if captured is not None and captured < market_close:
                rejected['intraday'] += 1
                continue
            if symbol not in groups:
                if len(groups) >= MAX_SYMBOLS:
                    raise ValueError(f'Price corpus exceeds the {MAX_SYMBOLS} symbol bound')
                groups[symbol] = {}
            if collection_status == 'cache_preserved' or symbol not in collection_statuses:
                collection_statuses[symbol] = collection_status
            names[symbol] = str(row.get('name') or symbol)[:80]
            try:
                close = float(str(row.get('current_price', '')).replace(',', ''))
            except (ValueError, TypeError):
                close = math.nan
            if not math.isfinite(close) or close <= 0:
                rejected['bad_price'] += 1
                close = math.nan
            if captured is None:
                rejected['unknown_capture'] += 1
                close, captured, captured_actual_us = math.nan, 0, 0
            existing = groups[symbol].get(day)
            if existing is not None:
                rejected['duplicate_sessions'] += 1
                # A later valid row may rescue a previously invalid observation.
                if math.isfinite(existing[0]) and (not math.isfinite(close) or existing[2] <= captured_actual_us):
                    continue
            groups[symbol][day] = (close, captured, captured_actual_us)

    symbols = sorted(groups)
    all_dates, all_closes, all_captures, all_actual_captures, offsets = [], [], [], [], [0]
    feature_rows, candidate_symbols, candidate_ends, candidate_available = [], [], [], []
    width = LOOKBACK + MAX_HORIZON
    for symbol_index, symbol in enumerate(symbols):
        rows = sorted(groups[symbol].items())
        dates = np.array([item[0] for item in rows], dtype=np.int32)
        closes = np.array([item[1][0] for item in rows], dtype=np.float64)
        captures = np.array([item[1][1] for item in rows], dtype=np.int64)
        actual_captures = np.array([item[1][2] for item in rows], dtype=np.int64)
        invalid = (~np.isfinite(closes)) | (closes <= 0) | (captures <= 0)
        with np.errstate(invalid='ignore', divide='ignore'):
            jumps = np.abs(closes[1:] / closes[:-1] - 1) > 0.35
        gaps = np.diff(dates) > MAX_GAP_DAYS
        rejected['raw_discontinuities'] += int(jumps.sum())
        rejected['large_gaps'] += int(gaps.sum())
        bad_prices = np.concatenate(([0], np.cumsum(invalid, dtype=np.int64)))
        bad_links = np.concatenate(([0], np.cumsum(jumps | gaps, dtype=np.int64)))
        available = _rolling_max(captures, width)
        base = offsets[-1]
        for end in range(LOOKBACK - 1, len(rows) - MAX_HORIZON):
            # A fixed calendar anchor remains unchanged by later captures,
            # duplicate input rows, or a larger future source corpus.
            if int(dates[end]) % 10 != 0:
                continue
            start, future_end = end - LOOKBACK + 1, end + MAX_HORIZON
            if bad_prices[future_end + 1] != bad_prices[start] or bad_links[future_end] != bad_links[start]:
                rejected['invalid_windows'] += 1
                continue
            feature_rows.append(_feature(closes[start:end + 1]))
            candidate_symbols.append(symbol_index)
            candidate_ends.append(base + end)
            candidate_available.append(int(available[future_end]))
        all_dates.append(dates)
        all_closes.append(closes)
        all_captures.append(captures)
        all_actual_captures.append(actual_captures)
        offsets.append(base + len(rows))
    del groups
    dates = np.concatenate(all_dates) if all_dates else np.empty(0, dtype=np.int32)
    closes = np.concatenate(all_closes) if all_closes else np.empty(0, dtype=np.float64)
    captures = np.concatenate(all_captures) if all_captures else np.empty(0, dtype=np.int64)
    actual_captures = np.concatenate(all_actual_captures) if all_actual_captures else np.empty(0, dtype=np.int64)
    valid = np.isfinite(closes) & (closes > 0) & (captures > 0)
    latest = int(dates[valid].max()) if valid.any() else None
    metadata = {
        'model_version': MODEL_VERSION,
        'mode': 'shadow',
        'source': {'name': source.name, 'source_id': source_id, 'price_basis': price_basis,
                   'latest_session': _date(latest) if latest is not None else None,
                   'corpus_latest_session': _date(latest) if latest is not None else None,
                   'captured_at': _iso_us(actual_captures[valid].max()) if valid.any() else None,
                   'built_at': _iso(datetime.now(timezone.utc).timestamp()),
                   'rows': int(valid.sum()), 'raw_rows': raw_rows, 'symbols': len(symbols),
                   'collection_summary': {f'{state}_symbols': sum(collection_statuses[symbol] == state for symbol in symbols)
                                          for state in ['fresh', 'cache_preserved', 'untracked']}},
        'diagnostics': {'rejected': dict(rejected), 'window_count': len(feature_rows),
                        'session_rows': int(valid.sum()), 'symbols': len(symbols),
                        'sampling': 'end_date_ordinal_mod_10', 'window_stride_calendar_days': 10,
                        'lookback_sessions': LOOKBACK,
                        'max_horizon_sessions': MAX_HORIZON, 'min_samples': MIN_SAMPLES,
                        'feature_dimensions': 34, 'max_query_windows': MAX_WINDOWS},
    }
    arrays = {
        'metadata': np.array(json.dumps(metadata, ensure_ascii=False)),
        'symbols': np.array(symbols, dtype='U6'),
        'names': np.array([names[symbol] for symbol in symbols], dtype='U80'),
        'collection_statuses': np.array([collection_statuses[symbol] for symbol in symbols], dtype='U16'),
        'offsets': np.array(offsets, dtype=np.int64),
        'dates': dates, 'closes': closes, 'captures': captures, 'captures_actual_us': actual_captures,
        'features': np.array(feature_rows, dtype=np.float32).reshape(-1, 34),
        'candidate_symbols': np.array(candidate_symbols, dtype=np.int32),
        'candidate_ends': np.array(candidate_ends, dtype=np.int64),
        'candidate_available': np.array(candidate_available, dtype=np.int64),
    }
    if len(feature_rows) > MAX_WINDOWS or sum(value.nbytes for value in arrays.values()) > MAX_ARCHIVE_BYTES:
        raise ValueError('Chart index exceeds its bounded query/memory budget')
    destination.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.chart-analogue-', suffix='.npz', dir=str(destination))
    try:
        with os.fdopen(handle, 'wb') as stream:
            np.savez(stream, **arrays)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination / INDEX_NAME)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    with _LOCK:
        _CACHE.clear()
    return {'status': 'built', **metadata, 'warnings': _warnings(price_basis)}


def _load(full=False, index_root=None):
    path = Path(index_root if index_root is not None else INDEX_ROOT) / INDEX_NAME
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None, 'missing_index'
    if stat.st_size > MAX_ARCHIVE_BYTES or stat.st_size < 1:
        return None, 'unavailable'
    signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        if _CACHE.get('signature') == signature and (not full or 'data' in _CACHE):
            return _CACHE['data'] if full else _CACHE['metadata'], None
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_ARCHIVE_BYTES:
                    return None, 'unavailable'
            with np.load(path, allow_pickle=False) as archive:
                metadata = json.loads(str(archive['metadata'].item()))
                if metadata.get('model_version') != MODEL_VERSION or not isinstance(metadata.get('source'), dict) or not isinstance(metadata.get('diagnostics'), dict):
                    return None, 'unavailable'
                latest = metadata['source'].get('latest_session')
                if latest is not None:
                    date.fromisoformat(latest)
                captured_at = metadata['source'].get('captured_at')
                if captured_at is not None:
                    _cutoff(captured_at)
                if full:
                    data = {key: archive[key] for key in archive.files if key != 'metadata'}
                    data['metadata'] = metadata
                    row_count, window_count = len(data['dates']), len(data['features'])
                    symbols_count = len(data['symbols'])
                    if (row_count > MAX_ROWS or window_count > MAX_WINDOWS or symbols_count > MAX_SYMBOLS
                            or data['features'].shape != (window_count, 34)
                            or len(data['closes']) != row_count or len(data['captures']) != row_count
                            or len(data['captures_actual_us']) != row_count or len(data['collection_statuses']) != symbols_count
                            or len(data['names']) != symbols_count or len(data['offsets']) != symbols_count + 1
                            or data['offsets'][0] != 0 or data['offsets'][-1] != row_count
                            or np.any(np.diff(data['offsets']) < 0)
                            or any(len(data[key]) != window_count for key in ['candidate_symbols', 'candidate_ends', 'candidate_available'])
                            or np.any(data['candidate_symbols'] < 0) or np.any(data['candidate_symbols'] >= symbols_count)
                            or np.any(data['candidate_ends'] < LOOKBACK - 1)
                            or np.any(data['candidate_ends'] + MAX_HORIZON >= row_count)
                            or not np.all(np.isfinite(data['features']))):
                        return None, 'unavailable'
                    # Every stored endpoint must remain within its own symbol's
                    # observation partition, including its full future path.
                    owner = data['candidate_symbols']
                    if (np.any(data['candidate_ends'] - LOOKBACK + 1 < data['offsets'][owner])
                            or np.any(data['candidate_ends'] + MAX_HORIZON >= data['offsets'][owner + 1])):
                        return None, 'unavailable'
                else:
                    data = None
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError):
            return None, 'unavailable'
        _CACHE.clear()
        _CACHE.update(signature=signature, metadata=metadata)
        if full:
            _CACHE['data'] = data
        return data if full else metadata, None


def _freshness(source, cutoff):
    latest = source.get('latest_session')
    return max(0, (cutoff.astimezone(KST).date() - date.fromisoformat(latest)).days) if latest else None


def status():
    """Read only a tiny NPZ metadata member; never load the price corpus."""
    metadata, error = _load()
    if error:
        return {'status': error, 'mode': 'shadow', 'model_version': MODEL_VERSION,
                'source': {}, 'diagnostics': {}, 'warnings': [error, *_WARNINGS]}
    # Make copies so freshness fields cannot mutate the cache across requests.
    result = json.loads(json.dumps(metadata))
    freshness = _freshness(result['source'], _cutoff())
    result['source']['freshness_days'] = freshness
    result['status'] = 'stale_data' if freshness is None or freshness > STALE_DAYS else 'ready'
    result['warnings'] = ([result['status']] if result['status'] != 'ready' else []) + _warnings(result['source'].get('price_basis'))
    return result


def predict(symbol, as_of=None, lookback=252, horizons=(5, 20, 40), k=20,
            *, index_root=None, _loaded_index=None):
    """Describe historical outcomes knowable by cutoff. Never rebuild or write.

    v1 deliberately fixes lookback to 252. The neighbour count is bounded at 50
    and horizon inputs at 1..40; every statistic is unweighted and deterministic.
    """
    symbol = str(symbol).strip()
    if not re.fullmatch(r'\d{6}', symbol, flags=re.ASCII):
        raise ValueError('symbol must be a six-digit KR equity code')
    if isinstance(lookback, bool) or lookback != LOOKBACK:
        raise ValueError('v1 supports exactly 252 observed input sessions')
    if isinstance(k, bool) or not isinstance(k, int) or not 5 <= k <= 50:
        raise ValueError('k must be an integer between 5 and 50')
    try:
        horizons = tuple(horizons)
    except TypeError as error:
        raise ValueError('horizons must contain 1..40 session integers') from error
    if not horizons or len(horizons) > MAX_HORIZON or any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HORIZON for value in horizons):
        raise ValueError('horizons must contain 1..40 session integers')
    horizons = tuple(sorted(set(horizons)))
    decision = _cutoff(as_of)
    timestamp = int(decision.timestamp())
    result = {'symbol': symbol, 'target': symbol, 'status': 'missing_index', 'mode': 'shadow',
              'model_version': MODEL_VERSION, 'as_of': decision.isoformat().replace('+00:00', 'Z'),
              'lookback_sessions': lookback, 'source': {}, 'diagnostics': {}, 'sample_count': 0,
              'history': [], 'horizons': [], 'fan': [], 'neighbors': [], 'warnings': list(_WARNINGS)}
    # Offline multi-symbol scans pin one vintage for the complete batch.
    data, error = _loaded_index if _loaded_index is not None else _load(full=True, index_root=index_root)
    if error:
        result['status'] = error
        result['warnings'].insert(0, error)
        return result
    metadata = data['metadata']
    result['source'] = dict(metadata['source'])
    result['warnings'] = _warnings(result['source'].get('price_basis'))
    result['diagnostics'] = {**metadata['diagnostics'], 'eligible_windows': 0}
    match = int(np.searchsorted(data['symbols'], symbol))
    if match >= len(data['symbols']) or data['symbols'][match] != symbol:
        result['status'] = 'insufficient_history'
        result['warnings'].insert(0, 'Target symbol has no indexed daily observations.')
        return result
    result['target'] = str(data['names'][match])
    result['source']['query_collection_status'] = str(data['collection_statuses'][match])
    result['source']['query_captured_at'] = None
    begin, finish = (int(value) for value in data['offsets'][match:match + 2])
    valid = np.isfinite(data['closes'][begin:finish]) & (data['closes'][begin:finish] > 0)
    valid &= (data['captures'][begin:finish] > 0) & (data['captures'][begin:finish] <= timestamp)
    eligible = np.flatnonzero(valid)
    if not len(eligible):
        result['status'] = 'insufficient_history'
        return result
    end = begin + int(eligible[-1])
    start = max(begin, end - LOOKBACK + 1)
    query_closes = data['closes'][start:end + 1]
    query_dates = data['dates'][start:end + 1]
    query_captures = data['captures'][start:end + 1]
    query_actual_captures = data['captures_actual_us'][start:end + 1]
    known_query = (query_captures > 0) & (query_captures <= timestamp)
    result['source']['query_captured_at'] = _iso_us(query_actual_captures[known_query].max())
    result['history'] = [{'date': _date(day), 'close': round(float(close), 6)}
                         for day, close, capture in zip(query_dates, query_closes, query_captures)
                         if np.isfinite(close) and close > 0 and 0 < capture <= timestamp]
    result['source']['latest_session'] = _date(data['dates'][end])
    result['source']['captured_at'] = result['source']['query_captured_at']
    freshness = _freshness(result['source'], decision)
    result['source']['freshness_days'] = freshness
    result['diagnostics'].update(latest_session=result['source']['latest_session'], freshness_days=freshness)
    if freshness > STALE_DAYS:
        result['status'] = 'stale_data'
        result['warnings'].insert(0, 'Daily observations are more than seven calendar days old.')
        return result
    if len(query_closes) != LOOKBACK or not _valid_span(query_closes, query_dates) or np.any(query_captures <= 0) or np.any(query_captures > timestamp):
        result['status'] = 'insufficient_history'
        result['warnings'].insert(0, 'A complete clean 252-session history was not available at the decision cutoff.')
        return result
    ends = data['candidate_ends']
    # Max capture covers all input sessions AND all 40 future observations.
    allowed = data['candidate_available'] <= timestamp
    allowed &= data['dates'][ends + MAX_HORIZON] <= (decision.astimezone(KST).date() - EPOCH).days
    # Self-analogues cannot overlap the current target input window.
    allowed &= (data['candidate_symbols'] != match) | (ends + MAX_HORIZON < start)
    indices = np.flatnonzero(allowed)
    result['diagnostics']['eligible_windows'] = int(len(indices))
    feature = _feature(query_closes)
    distances = np.empty(len(indices), dtype=np.float32)
    for offset in range(0, len(indices), 4096):
        chunk = data['features'][indices[offset:offset + 4096]] - feature
        distances[offset:offset + 4096] = np.mean(chunk * chunk, axis=1)
    order = np.argsort(distances, kind='stable')
    selected, occupied = [], {}
    # Query work is bounded by the index size, and selections by k <= 50.
    for position in order:
        candidate = int(indices[position])
        candidate_end = int(ends[candidate])
        candidate_symbol = int(data['candidate_symbols'][candidate])
        interval = (candidate_end - LOOKBACK + 1, candidate_end + MAX_HORIZON)
        if any(interval[0] <= previous[1] and previous[0] <= interval[1] for previous in occupied.get(candidate_symbol, [])):
            continue
        occupied.setdefault(candidate_symbol, []).append(interval)
        selected.append((candidate, float(distances[position])))
        if len(selected) >= k:
            break
    result['sample_count'] = len(selected)
    if len(selected) < MIN_SAMPLES:
        result['status'] = 'insufficient_analogues'
        result['warnings'].insert(0, 'Fewer than five non-overlapping historical analogue samples were available.')
        return result
    sample_ends = np.array([int(ends[candidate]) for candidate, _ in selected], dtype=np.int64)
    paths = data['closes'][sample_ends[:, None] + np.arange(MAX_HORIZON + 1)] / data['closes'][sample_ends, None] - 1
    current_price = float(query_closes[-1])
    for horizon in horizons:
        returns = paths[:, horizon] * 100
        low, median, high = (float(value) for value in np.quantile(returns, [0.1, 0.5, 0.9]))
        result['horizons'].append({'sessions': horizon, 'median_return_pct': round(median, 6),
                                  'p10_return_pct': round(low, 6), 'p90_return_pct': round(high, 6),
                                  'up_frequency_pct': round(float(np.mean(returns > 0) * 100), 6),
                                  'median_price': round(current_price * (1 + median / 100), 6),
                                  'lower_price': round(current_price * (1 + low / 100), 6),
                                  'upper_price': round(current_price * (1 + high / 100), 6)})
    quantiles = np.quantile(paths[:, :max(horizons) + 1], [0.1, 0.5, 0.9], axis=0)
    result['fan'] = [{'session': session, 'median_price': round(current_price * (1 + float(quantiles[1, session])), 6),
                      'p10_price': round(current_price * (1 + float(quantiles[0, session])), 6),
                      'p90_price': round(current_price * (1 + float(quantiles[2, session])), 6)}
                     for session in range(max(horizons) + 1)]
    for row, (candidate, distance) in enumerate(selected):
        historical_end = int(ends[candidate])
        historical_symbol = int(data['candidate_symbols'][candidate])
        result['neighbors'].append({'symbol': str(data['symbols'][historical_symbol]),
                                    'target': str(data['names'][historical_symbol]),
                                    'start_date': _date(data['dates'][historical_end - LOOKBACK + 1]),
                                    'end_date': _date(data['dates'][historical_end]),
                                    'outcome_end_date': _date(data['dates'][historical_end + MAX_HORIZON]),
                                    'captured_at': _iso_us(data['captures_actual_us'][historical_end - LOOKBACK + 1:historical_end + MAX_HORIZON + 1].max()),
                                    'similarity': round(1 / (1 + distance), 6),
                                    'returns': {str(horizon): round(float(paths[row, horizon] * 100), 6) for horizon in horizons}})
    result['source']['captured_at'] = _iso_us(max(int(query_actual_captures.max()),
                                               max(int(data['captures_actual_us'][int(ends[candidate]) - LOOKBACK + 1:int(ends[candidate]) + MAX_HORIZON + 1].max()) for candidate, _ in selected)))
    result['status'] = 'ready'
    return result


def observed_outcomes(symbol, *, decision_at, reference_session, frozen_reference_close,
                      as_of=None, horizons=(5, 20, 40), expected_source_id=None,
                      expected_price_basis=None, index_root=None, _loaded_index=None):
    """Read realised labels from one saved price vintage without filtering rows.

    Forecast labels start at the exact frozen reference session, using its
    evaluated close from this index. Trade labels start at the first observation
    strictly after the Korean decision date and then count H more observations.
    Neither sequence substitutes a later row for an invalid/unavailable row.
    Top-level ``ready`` means the index can be read; each horizon independently
    reports maturity. Work after the cached index load is bounded by 40 rows per
    requested horizon, and this operation performs no network access or writes.
    """
    if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}', symbol, flags=re.ASCII):
        raise ValueError('symbol must be a six-digit KR equity code')
    if decision_at is None:
        raise ValueError('decision_at must be an explicit timezone-aware timestamp')
    decision = _cutoff(decision_at)
    evaluation = _cutoff(as_of)
    if evaluation < decision:
        raise ValueError('as_of cannot be before decision_at')
    try:
        if not isinstance(reference_session, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', reference_session):
            raise ValueError('reference_session must be a YYYY-MM-DD date')
        reference_day = date.fromisoformat(reference_session)
    except (ValueError, TypeError) as error:
        raise ValueError('reference_session must be a YYYY-MM-DD date') from error
    if isinstance(frozen_reference_close, bool) or not isinstance(frozen_reference_close, (int, float)):
        raise ValueError('frozen_reference_close must be a finite positive number')
    try:
        frozen_reference_close = float(frozen_reference_close)
    except (OverflowError, ValueError) as error:
        raise ValueError('frozen_reference_close must be a finite positive number') from error
    if not math.isfinite(frozen_reference_close) or frozen_reference_close <= 0:
        raise ValueError('frozen_reference_close must be a finite positive number')
    if expected_source_id is not None and (not isinstance(expected_source_id, str)
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', expected_source_id)):
        raise ValueError('expected_source_id must be a bounded source identifier')
    if expected_price_basis is not None and (not isinstance(expected_price_basis, str)
            or expected_price_basis not in {'unadjusted', 'provider_adjusted'}):
        raise ValueError('expected_price_basis is unsupported')
    try:
        horizons = tuple(islice(iter(horizons), MAX_HORIZON + 1))
    except TypeError as error:
        raise ValueError('horizons must contain 1..40 session integers') from error
    if (not horizons or len(horizons) > MAX_HORIZON
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or not 1 <= value <= MAX_HORIZON for value in horizons)):
        raise ValueError('horizons must contain 1..40 session integers')
    horizons = tuple(sorted(set(horizons)))

    def blank(horizon, status='blocked', reason=None):
        return {'sessions': horizon, 'status': status, 'reason': reason, 'observed_sessions': 0,
                'entry_date': None, 'entry_close': None, 'exit_date': None, 'exit_close': None,
                'captured_at': None, 'gross_return_pct': None}

    result = {'symbol': symbol, 'as_of': evaluation.isoformat().replace('+00:00', 'Z'),
              'status': 'ready', 'source': {},
              'reference': {'session': reference_session, 'frozen_close': float(frozen_reference_close),
                            'evaluated_close': None, 'rebased': False},
              'forecast_horizons': [blank(horizon) for horizon in horizons],
              'trade_horizons': [blank(horizon) for horizon in horizons]}

    def unavailable(reason, status='blocked'):
        for row in result['forecast_horizons'] + result['trade_horizons']:
            row.update(status=status, reason=reason)
        return result

    # The offline evaluator holds this private (data, error) tuple for its
    # entire run, so a concurrent atomic publisher cannot mix price vintages.
    data, error = _loaded_index if _loaded_index is not None else _load(full=True, index_root=index_root)
    if error:
        result['status'] = error
        return unavailable(error)
    result['source'] = dict(data['metadata']['source'])
    if expected_source_id is not None and result['source'].get('source_id') != expected_source_id:
        return unavailable('source_mismatch')
    if expected_price_basis is not None and result['source'].get('price_basis') != expected_price_basis:
        return unavailable('price_basis_mismatch')
    match = int(np.searchsorted(data['symbols'], symbol))
    if match >= len(data['symbols']) or data['symbols'][match] != symbol:
        return unavailable('symbol_missing')
    result['source']['query_collection_status'] = str(data['collection_statuses'][match])
    begin, finish = (int(value) for value in data['offsets'][match:match + 2])
    dates = data['dates'][begin:finish]
    closes = data['closes'][begin:finish]
    captures = data['captures_actual_us'][begin:finish]
    reference_ordinal = (reference_day - EPOCH).days
    reference_position = int(np.searchsorted(dates, reference_ordinal))
    if reference_position >= len(dates) or int(dates[reference_position]) != reference_ordinal:
        return unavailable('reference_missing')
    elapsed = evaluation - datetime(1970, 1, 1, tzinfo=timezone.utc)
    cutoff_us = ((elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds)

    def observation(position):
        day = EPOCH + timedelta(days=int(dates[position]))
        close = float(closes[position])
        capture = int(captures[position])
        if day.weekday() >= 5 or capture <= 0:
            return 'blocked', 'invalid_span'
        market_close = datetime.combine(day, time(15, 30), KST)
        if market_close > evaluation:
            return 'pending', 'close_not_completed'
        if capture > cutoff_us:
            return 'pending', 'capture_after_as_of'
        market_elapsed = market_close.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        market_close_us = (market_elapsed.days * 86400 + market_elapsed.seconds) * 1_000_000
        if capture < market_close_us or not math.isfinite(close) or close <= 0:
            return 'blocked', 'invalid_span'
        return None, None

    anchor_status, anchor_reason = observation(reference_position)
    if anchor_status:
        return unavailable(anchor_reason, anchor_status)
    evaluated_reference = round(float(closes[reference_position]), 6)
    result['reference'].update(evaluated_close=evaluated_reference,
                               rebased=evaluated_reference != round(float(frozen_reference_close), 6))
    result['source']['query_captured_at'] = _iso_us(captures[reference_position])

    def label(anchor, horizon):
        row = blank(horizon, 'pending', 'incomplete_sessions')
        if anchor >= len(dates):
            row['reason'] = 'entry_not_observed'
            return row
        anchor_status, anchor_reason = observation(anchor)
        if anchor_status:
            row.update(status=anchor_status, reason=anchor_reason)
            return row
        entry_close = float(closes[anchor])
        maximum_capture = int(captures[anchor])
        row.update(entry_date=_date(dates[anchor]), entry_close=round(entry_close, 6),
                   captured_at=_iso_us(maximum_capture))
        for position in range(anchor + 1, min(anchor + horizon + 1, len(dates))):
            row_status, row_reason = observation(position)
            if row_status:
                row.update(status=row_status, reason=row_reason)
                return row
            difference = int(dates[position]) - int(dates[position - 1])
            if (not 0 < difference <= MAX_GAP_DAYS
                    or abs(float(closes[position]) / float(closes[position - 1]) - 1) > 0.35):
                row.update(status='blocked', reason='invalid_span')
                return row
            maximum_capture = max(maximum_capture, int(captures[position]))
            row['captured_at'] = _iso_us(maximum_capture)
            row['observed_sessions'] += 1
        if row['observed_sessions'] == horizon:
            exit_position = anchor + horizon
            exit_close = float(closes[exit_position])
            row.update(status='matured', reason=None, exit_date=_date(dates[exit_position]),
                       exit_close=round(exit_close, 6),
                       gross_return_pct=round((exit_close / entry_close - 1) * 100, 6))
        return row

    decision_ordinal = (decision.astimezone(KST).date() - EPOCH).days
    trade_position = int(np.searchsorted(dates, decision_ordinal, side='right'))
    result['forecast_horizons'] = [label(reference_position, horizon) for horizon in horizons]
    # A delayed resumption or discontinuity must not replace the intended
    # first post-decision entry with a seemingly normal later price path.
    entry_issue = None
    if trade_position < len(dates) and observation(trade_position)[0] is None:
        if int(dates[trade_position]) - decision_ordinal > MAX_GAP_DAYS or trade_position == 0:
            entry_issue = ('blocked', 'invalid_entry_span')
        else:
            previous_status, previous_reason = observation(trade_position - 1)
            if previous_status:
                entry_issue = (previous_status, previous_reason)
            elif not _valid_span(closes[trade_position - 1:trade_position + 1],
                                 dates[trade_position - 1:trade_position + 1]):
                entry_issue = ('blocked', 'invalid_entry_span')
    result['trade_horizons'] = ([blank(horizon, *entry_issue) for horizon in horizons]
                              if entry_issue else [label(trade_position, horizon) for horizon in horizons])
    return result
