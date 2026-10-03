#!/usr/bin/env python3
"""Collect bounded, unverified NAVER daily OHLCV for a fixed current cohort.

Research artifacts only: no returns, orders, production prices, or index writes.
Provider adjustment, dividend treatment and historical vintages are undocumented.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import re
import statistics
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib3.exceptions import HTTPError as StreamHTTPError

import requests
from filelock import FileLock


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_URL = 'https://api.finance.naver.com/siseJson.naver'
SOURCE = 'naver_sise_json_public'
PRICE_BASIS = 'provider_reported_unverified'
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
HEADER = ['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율']
UNVERIFIED = {'corporate_action_adjustment_verified': False,
              'historical_vintage_verified': False, 'dividend_included': False,
              'analysis_ready': False}
CSV_FIELDS = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume',
              'quality_flags', 'captured_at', 'source', 'price_basis', 'analysis_ready']


class InvalidPayload(ValueError):
    """An invalid snapshot cannot become a silently shortened price series."""


class FetchRequired(RuntimeError):
    """A missing trusted raw capture requires explicit network opt-in."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))


def iso_day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('Dates must use YYYY-MM-DD')
    return value


def bounded_integer(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{label} must be an integer between {low} and {high}')


def load_universe(path, max_symbols=100):
    bounded_integer(max_symbols, 1, 100, 'max_symbols')
    content = Path(path).read_bytes()
    if len(content) > MAX_BYTES:
        raise ValueError('Universe report exceeds the size bound')
    report = json.loads(content.decode('utf-8-sig'))
    ranked = report['ranking']['ranked']
    if not isinstance(ranked, list) or not ranked:
        raise ValueError('Universe requires a nonempty ranking.ranked list')
    selected, seen = [], set()
    for row in ranked[:max_symbols]:
        if not isinstance(row, dict) or not re.fullmatch(r'\d{6}', str(row.get('symbol', '')), flags=re.ASCII):
            raise ValueError('Selected universe contains an invalid symbol')
        symbol = row['symbol']
        if symbol in seen:
            raise ValueError('Selected universe contains duplicate symbols')
        seen.add(symbol)
        selected.append({'symbol': symbol, 'rank': row.get('rank'),
                         'name': str(row.get('name') or symbol), 'market': str(row.get('market') or ''),
                         'name_as_of': report.get('as_of')})
    return selected


def _provider_literal(text):
    try:
        return ast.literal_eval(text.strip())
    except ValueError:
        # The historical feed may use JSON null despite single-quoted headers.
        # Only literal null names are translated; calls and other expressions
        # still fail ast.literal_eval and can never execute.
        class NullableNames(ast.NodeTransformer):
            def visit_Name(self, node):
                return ast.copy_location(ast.Constant(None), node) if node.id == 'null' else node
        return ast.literal_eval(NullableNames().visit(ast.parse(text.strip(), mode='eval')))


def parse_payload(payload, start, end):
    """Parse bounded provider literals, preserving numerical values and all rows."""
    iso_day(start)
    iso_day(end)
    if start > end:
        raise ValueError('start must not follow end')
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise InvalidPayload('Provider response exceeds the size bound')
    table, encoding = None, None
    for candidate in ('utf-8-sig', 'euc-kr', 'cp949'):
        try:
            parsed = _provider_literal(payload.decode(candidate))
        except (UnicodeError, ValueError, SyntaxError, RecursionError, MemoryError):
            continue
        if isinstance(parsed, list) and parsed and parsed[0] in (HEADER, HEADER[:6]):
            table, encoding = parsed, candidate
            break
    if table is None:
        raise InvalidPayload('Unsupported provider literal or header encoding')
    if not 1 <= len(table) - 1 <= MAX_ROWS:
        raise InvalidPayload('Provider returned an empty or oversized row list')
    bars, counts, shapes, previous = [], Counter(), Counter(), None
    for index, row in enumerate(table[1:], 1):
        if not isinstance(row, list) or len(row) not in (6, 7):
            raise InvalidPayload(f'Malformed row shape at row {index}')
        if not isinstance(row[0], str) or not re.fullmatch(r'\d{8}', row[0], flags=re.ASCII):
            raise InvalidPayload(f'Invalid date at row {index}')
        try:
            day = datetime.strptime(row[0], '%Y%m%d').date().isoformat()
        except ValueError as error:
            raise InvalidPayload(f'Invalid calendar date at row {index}') from error
        if not start <= day <= end or (previous is not None and day <= previous):
            raise InvalidPayload(f'Duplicate, unordered or out-of-range date at row {index}')
        previous = day
        # Foreign ratio is optional, historically absent or nullable. It is not
        # an OHLCV input and stays solely in the preserved raw snapshot.
        for value in row[1:6]:
            try:
                finite = isinstance(value, (int, float)) and math.isfinite(value)
            except OverflowError:
                finite = False
            if isinstance(value, bool) or not finite or value < 0:
                raise InvalidPayload(f'Invalid finite nonnegative number at row {index}')
        opening, high, low, close, volume = row[1:6]
        flags = []
        if opening == high == low == 0:
            flags.append('zero_ohl')
        elif min(opening, high, low) <= 0:
            flags.append('nonpositive_ohl')
        if close <= 0:
            flags.append('nonpositive_close')
        if volume <= 0:
            flags.append('no_tradable_volume')
        if min(opening, high, low, close) > 0 and not low <= min(opening, close) <= max(opening, close) <= high:
            flags.append('ohlc_bounds_mismatch')
        bars.append({'date': day, 'open': opening, 'high': high, 'low': low,
                     'close': close, 'volume': volume, 'quality_flags': flags})
        counts.update(flags)
        shapes[str(len(row))] += 1
    return {'header': table[0], 'encoding': encoding, 'bars': bars,
            'quality_counts': dict(counts), 'row_shape_counts': dict(shapes)}


def fetch_payload(symbol, params, *, requester=None, monotonic=None):
    """A fixed public endpoint with socket, whole-response and size budgets."""
    requester = requester or requests.get
    monotonic = monotonic or time.monotonic
    begun = monotonic()
    with requester(PROVIDER_URL, params=params, timeout=(4, 8), stream=True,
                   allow_redirects=False, headers={'User-Agent': 'MarketFlow-LongHistoryResearch/1.0'}) as response:
        if 300 <= response.status_code < 400:
            raise requests.HTTPError('Provider redirect is not allowed', response=response)
        response.raise_for_status()
        length = response.headers.get('Content-Length')
        if length is not None and int(length) > MAX_BYTES:
            raise InvalidPayload('Provider response exceeds the size bound')
        payload = bytearray()
        while True:
            if monotonic() - begun > 20:
                raise requests.Timeout('Provider response exceeded the whole-read budget')
            chunk = response.raw.read1(65536, decode_content=True)
            payload.extend(chunk)
            if len(payload) > MAX_BYTES:
                raise InvalidPayload('Provider response exceeds the size bound')
            if monotonic() - begun > 20:
                raise requests.Timeout('Provider response exceeded the whole-read budget')
            if not chunk:
                break
        return {'payload': bytes(payload), 'captured_at': utc_now(), 'http_status': response.status_code}


def _retryable(error):
    if isinstance(error, requests.HTTPError):
        return error.response is not None and error.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(error, (requests.Timeout, requests.ConnectionError, StreamHTTPError))


def _capture_time(value):
    if not isinstance(value, str):
        raise InvalidPayload('Missing actual provider capture time')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise InvalidPayload('Invalid provider capture time') from error
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise InvalidPayload('Provider capture time requires a timezone')
    return value


def _one_symbol(row, out, start, end, retries, fetcher, sleeper, fetch_enabled):
    symbol = row['symbol']
    params = {'symbol': symbol, 'requestType': '1', 'startTime': start.replace('-', ''),
              'endTime': end.replace('-', ''), 'timeframe': 'day'}
    directory = out / 'symbols' / symbol
    summary_path = directory / 'summary.json'
    entry = {**row, **UNVERIFIED, 'source': SOURCE, 'price_basis': PRICE_BASIS,
             'request_params': params, 'request_url': PROVIDER_URL + '?' + urlencode(params),
             'status': 'failed', 'attempts': 0, 'cache_reused': False}
    capture, cached = None, None
    try:
        if summary_path.exists():
            try:
                cached = json.loads(summary_path.read_text(encoding='utf-8'))
                if cached.get('request_params') == params and cached.get('status') in {'collected', 'received'}:
                    raw_path = out / cached['raw_file']
                    if not raw_path.resolve().is_relative_to(directory.resolve()):
                        entry['cache_rejection'] = 'invalid_raw_path'
                    elif not raw_path.exists() or raw_path.stat().st_size > MAX_BYTES:
                        entry['cache_rejection'] = 'raw_missing_or_oversized'
                    else:
                        raw = raw_path.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != cached['raw_sha256']:
                            entry['cache_rejection'] = 'raw_hash_mismatch'
                        else:
                            capture = {'payload': raw, 'captured_at': cached['captured_at'], 'http_status': cached['http_status']}
                            entry['cache_reused'] = True
            except (ValueError, OSError, KeyError, TypeError):
                entry['cache_rejection'] = 'invalid_cache_metadata'
        if capture is None:
            if not fetch_enabled:
                raise FetchRequired('No valid raw capture; pass --fetch to enable bounded acquisition')
            for attempt in range(retries + 1):
                entry['attempts'] = attempt + 1
                try:
                    capture = fetcher(symbol, params)
                    break
                except (requests.RequestException, StreamHTTPError) as error:
                    if attempt >= retries or not _retryable(error):
                        raise
                    sleeper(min(attempt + 1, 2))
        if not isinstance(capture, dict) or not isinstance(capture.get('payload'), bytes):
            raise InvalidPayload('Provider capture is not a byte payload')
        raw = capture['payload']
        if len(raw) > MAX_BYTES:
            raise InvalidPayload('Provider response exceeds the size bound')
        captured_at = _capture_time(capture.get('captured_at'))
        raw_hash = hashlib.sha256(raw).hexdigest()
        raw_path = directory / f'raw-{raw_hash}.txt'
        atomic_write(raw_path, raw)
        entry.update({'captured_at': captured_at, 'http_status': capture.get('http_status'),
                      'raw_sha256': raw_hash, 'raw_bytes': len(raw),
                      'raw_file': raw_path.relative_to(out).as_posix(), 'status': 'received'})
        write_json(summary_path, entry)
        parsed = parse_payload(raw, start, end)
        bars_path = directory / 'bars.json'
        write_json(bars_path, parsed['bars'])
        entry.update({'status': 'collected', 'encoding': parsed['encoding'], 'header': parsed['header'],
                      'row_shape_counts': parsed['row_shape_counts'], 'quality_counts': parsed['quality_counts'],
                      'bars_file': bars_path.relative_to(out).as_posix(),
                      'bars_sha256': hashlib.sha256(bars_path.read_bytes()).hexdigest(),
                      'coverage': {'first_date': parsed['bars'][0]['date'], 'last_date': parsed['bars'][-1]['date'],
                                   'rows': len(parsed['bars']), 'requested_start': start, 'requested_end': end,
                                   'start_coverage_observed': parsed['bars'][0]['date'] <= start,
                                   'requested_end_observed': parsed['bars'][-1]['date'] == end,
                                   'exchange_calendar_verified': False}})
    except (InvalidPayload, FetchRequired, ValueError, requests.RequestException, StreamHTTPError, OSError, KeyError, TypeError) as error:
        entry.update({'status': 'rejected' if isinstance(error, InvalidPayload) else 'failed',
                      'error_type': type(error).__name__, 'error': str(error)[:300], 'failed_at': utc_now()})
        if isinstance(error, FetchRequired):
            entry['error_code'] = 'fetch_required'
    write_json(summary_path, entry)
    return entry


def _write_prices(path, entries, out):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    total = 0
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for entry in entries:
                if entry['status'] != 'collected':
                    continue
                bars_path = out / entry['bars_file']
                raw = bars_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry['bars_sha256']:
                    raise ValueError('Parsed bars changed before CSV publication')
                for bar in json.loads(raw.decode('utf-8')):
                    writer.writerow({**bar, 'symbol': entry['symbol'],
                                     'quality_flags': ';'.join(bar['quality_flags']),
                                     'captured_at': entry['captured_at'], 'source': SOURCE,
                                     'price_basis': PRICE_BASIS, 'analysis_ready': 'false'})
                    total += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return total


def collect(universe_report, output_dir, *, start='2005-01-01', end='2026-10-02',
            max_symbols=100, workers=3, retries=2, fetch=False, fetcher=None, sleeper=None, progress=None):
    bounded_integer(workers, 1, 3, 'workers')
    bounded_integer(retries, 0, 2, 'retries')
    if not isinstance(fetch, bool):
        raise ValueError('fetch must be an explicit boolean opt-in')
    selected = load_universe(universe_report, max_symbols)
    iso_day(start)
    iso_day(end)
    if start > end:
        raise ValueError('start must not follow end')
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_bytes = Path(universe_report).read_bytes()
    manifest = {'schema_version': 1, 'source': SOURCE, 'provider_url': PROVIDER_URL,
                'start': start, 'end': end, 'selected': selected,
                'universe_report_sha256': hashlib.sha256(source_bytes).hexdigest(),
                'current_cohort_bias': True, 'point_in_time_universe_verified': False, **UNVERIFIED}
    with FileLock(str(out / '.collection.lock'), timeout=1):
        manifest_path = out / 'manifest.json'
        if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
            raise ValueError('Existing manifest differs; use a separate output folder')
        write_json(manifest_path, manifest)
        begun = utc_now()
        entries = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='long-price-research') as pool:
            futures = {pool.submit(_one_symbol, row, out, start, end, retries,
                                   fetcher or fetch_payload, sleeper or time.sleep, fetch): row['symbol'] for row in selected}
            for done, future in enumerate(as_completed(futures), 1):
                result = future.result()
                entries[result['symbol']] = result
                if progress:
                    progress(done, len(selected), result)
        ordered = [entries[row['symbol']] for row in selected]
        prices_path = out / 'prices.csv'
        total = _write_prices(prices_path, ordered, out)
        row_counts = [row['coverage']['rows'] for row in ordered if row['status'] == 'collected']
        report = {'schema_version': 1, 'started_at': begun, 'completed_at': utc_now(),
                  'source': SOURCE, 'price_basis': PRICE_BASIS, **UNVERIFIED,
                  'network_fetch_enabled': fetch,
                  'current_cohort_bias': True, 'point_in_time_universe_verified': False,
                  'selected_symbols': [row['symbol'] for row in selected],
                  'status_counts': dict(Counter(row['status'] for row in ordered)),
                  'total_rows': total, 'symbols': ordered, 'prices_file': 'prices.csv',
                  'coverage_summary': {'collected_symbols': len(row_counts),
                                       'min_rows': min(row_counts) if row_counts else 0,
                                       'median_rows': statistics.median(row_counts) if row_counts else 0,
                                       'max_rows': max(row_counts) if row_counts else 0,
                                       'symbols_over_800_rows': sum(count > 800 for count in row_counts),
                                       'symbols_at_least_3000_rows': sum(count >= 3000 for count in row_counts)},
                  'prices_sha256': hashlib.sha256(prices_path.read_bytes()).hexdigest(),
                  'bounds': {'workers': workers, 'max_retries': retries, 'max_response_bytes': MAX_BYTES,
                             'socket_timeout_seconds': [4, 8], 'response_budget_seconds': 20},
                  'limitations': ['Research-only provider-reported data; adjustment and historical vintage are unverified.',
                                  'Dividends are not established as included. No returns or historical trade claims are calculated.',
                                  'All raw rows, including zero-volume and anomalous OHLC bars, are retained.',
                                  'Current TOP100 membership creates survivorship and current-cohort bias.']}
        write_json(out / 'report.json', report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe-report', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/kelly_research/long_history_20261002/prices')
    parser.add_argument('--start', default='2005-01-01')
    parser.add_argument('--end', default='2026-10-02')
    parser.add_argument('--max-symbols', type=int, default=100)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--fetch', action='store_true', help='Explicitly enable bounded public network acquisition')
    args = parser.parse_args()
    def progress(done, total, result):
        print(f'{done}/{total} {result["symbol"]} {result["status"]} rows={result.get("coverage", {}).get("rows", 0)}', flush=True)
    report = collect(args.universe_report, args.output_dir, start=args.start, end=args.end,
                     max_symbols=args.max_symbols, workers=args.workers, retries=args.retries,
                     fetch=args.fetch, progress=progress)
    print(json.dumps({key: report[key] for key in ('status_counts', 'total_rows', 'analysis_ready', 'prices_sha256')}, ensure_ascii=True))
    return 0 if report['status_counts'].get('collected') == len(report['selected_symbols']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
