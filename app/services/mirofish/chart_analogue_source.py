"""Offline, bounded Naver adjusted daily snapshots for the chart analogue index.

Provider capture is the actual response acquisition time, not the historical
session date. Entire symbol snapshots are replaced together, avoiding mixed
adjustment vintages. Failed symbols keep their prior trusted snapshots.
"""
from __future__ import annotations

import csv
import math
import os
import re
import tempfile
import time as monotonic_time
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timezone
from pathlib import Path

import requests
from urllib3.exceptions import HTTPError as UrllibHTTPError

from app.services.mirofish.chart_analogue import KST, MAX_ROWS, MAX_SYMBOLS, REPO_ROOT, _cutoff

PROVIDER_URL = 'https://fchart.stock.naver.com/sise.nhn'
SOURCE_ID = 'naver_closed_daily'
PRICE_BASIS = 'provider_adjusted'
HISTORY_COUNT = 800
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_SECONDS = 16
FIELDS = ['ticker', 'date', 'name', 'current_price', 'update_time', 'price_basis', 'source_id', 'collection_status']


class InvalidSnapshot(ValueError):
    """A broken provider bar must not silently shorten the trading timeline."""
    def __init__(self, rejected):
        super().__init__('Provider daily snapshot contains invalid or conflicting observations')
        self.rejected = rejected


def fetch_history(symbol):
    """Fetch only a fixed public endpoint, with size, socket and duration bounds."""
    if not re.fullmatch(r'\d{6}', str(symbol), flags=re.ASCII):
        raise ValueError('A six-digit KR equity code is required')
    started = monotonic_time.monotonic()
    with requests.get(PROVIDER_URL, params={'timeframe': 'day', 'count': HISTORY_COUNT,
                                          'requestType': '0', 'symbol': symbol},
                      timeout=8, stream=True, headers={'User-Agent': 'MarketFlow-ChartAnalogue/1.0'}) as response:
        response.raise_for_status()
        payload = bytearray()
        while True:
            if monotonic_time.monotonic() - started > MAX_RESPONSE_SECONDS:
                raise ValueError('Provider response exceeded its bounded fetch budget')
            # read1 returns available network bytes after a single read, so a
            # trickle cannot keep a large iter_content buffer waiting forever.
            chunk = response.raw.read1(65536, decode_content=True)
            payload.extend(chunk)
            if len(payload) > MAX_RESPONSE_BYTES or monotonic_time.monotonic() - started > MAX_RESPONSE_SECONDS:
                raise ValueError('Provider response exceeded its bounded fetch budget')
            if not chunk:
                break
    return bytes(payload)


def _universe(path):
    names = {}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'ticker', 'name'}.issubset(reader.fieldnames or []):
            raise ValueError('Universe CSV requires ticker and name columns')
        for index, row in enumerate(reader):
            if index >= MAX_ROWS:
                raise ValueError('Universe CSV exceeds the row bound')
            symbol = str(row.get('ticker', '')).strip()
            if re.fullmatch(r'\d{6}', symbol, flags=re.ASCII):
                names[symbol] = str(row.get('name') or symbol)[:80]
                if len(names) > MAX_SYMBOLS:
                    raise ValueError('Universe exceeds the symbol bound')
    return names


def _parse(payload, symbol, captured):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError('Provider XML exceeds the response bound')
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise ValueError('Provider XML declarations are unsupported')
    declaration = re.search(br'^\s*<\?xml\b[^>]*\bencoding\s*=\s*[\"\x27]([^\"\x27]+)[\"\x27]', payload[:200], flags=re.IGNORECASE)
    encoding = declaration.group(1).decode('ascii').lower().replace('_', '-') if declaration else 'utf-8'
    if encoding not in {'utf-8', 'utf8', 'euc-kr'}:
        raise ValueError('Provider XML encoding is unsupported')
    # ElementTree's byte parser cannot decode this provider's EUC-KR XML.
    # Decode only the documented bounded encodings before XML interpretation.
    root = ET.fromstring(payload.decode(encoding))
    chart = root if root.tag == 'chartdata' else root.find('.//chartdata')
    if chart is None or chart.attrib.get('symbol') != symbol:
        raise ValueError('Provider XML must identify the exact requested symbol')
    items = list(chart.iter('item'))
    if len(items) > HISTORY_COUNT:
        raise ValueError('Provider returned more than the requested history bound')
    rejected = Counter({key: 0 for key in ['bad_date', 'bad_price', 'intraday', 'non_session_date', 'duplicate_sessions', 'conflicting_duplicates']})
    rows = {}
    for item in items:
        columns = str(item.attrib.get('data', '')).split('|')
        if len(columns) != 6 or not re.fullmatch(r'\d{8}', columns[0], flags=re.ASCII):
            rejected['bad_date'] += 1
            continue
        try:
            day = datetime.strptime(columns[0], '%Y%m%d').date()
        except ValueError:
            rejected['bad_date'] += 1
            continue
        if day.weekday() >= 5:
            rejected['non_session_date'] += 1
            continue
        if datetime.combine(day, time(15, 30), KST) > captured:
            rejected['intraday'] += 1
            continue
        try:
            close = float(columns[4])
        except (ValueError, TypeError):
            close = math.nan
        if not math.isfinite(close) or close <= 0:
            rejected['bad_price'] += 1
            continue
        key = day.isoformat()
        if key in rows:
            rejected['duplicate_sessions'] += 1
            if rows[key] != close:
                rejected['conflicting_duplicates'] += 1
            continue
        rows[key] = close
    if rejected['bad_date'] or rejected['bad_price'] or rejected['conflicting_duplicates']:
        raise InvalidSnapshot(rejected)
    if not rows:
        raise ValueError('Provider returned no valid completed daily observations')
    stamp = captured.isoformat().replace('+00:00', 'Z')
    return [(day, close, stamp) for day, close in sorted(rows.items())], rejected


def _previous(path, universe):
    snapshots = {}
    invalid_symbols = set()
    if not path.exists():
        return snapshots
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not (set(FIELDS) - {'collection_status'}).issubset(reader.fieldnames or []):
            return snapshots
        for index, row in enumerate(reader):
            if index >= MAX_ROWS:
                raise ValueError('Previous source snapshot exceeds the row bound')
            symbol = row.get('ticker')
            if symbol not in universe:
                continue
            try:
                if row.get('price_basis') != PRICE_BASIS or row.get('source_id') != SOURCE_ID:
                    raise ValueError('Previous snapshot has a different price basis or provider')
                day = date.fromisoformat(row['date'])
                captured = _cutoff(row['update_time'])
                close = float(row['current_price'])
                if day.weekday() >= 5 or datetime.combine(day, time(15, 30), KST) > captured or not math.isfinite(close) or close <= 0:
                    raise ValueError('Invalid previous snapshot row')
                snapshots.setdefault(symbol, []).append((row['date'], close, row['update_time']))
                if len(snapshots[symbol]) > HISTORY_COUNT:
                    raise ValueError('Previous symbol history exceeds the bound')
            except (ValueError, KeyError, TypeError):
                invalid_symbols.add(symbol)
    for symbol in invalid_symbols:
        snapshots.pop(symbol, None)
    return snapshots


def refresh_prices(prices_path=None, output_path=None, symbols=None, workers=4, fetcher=None, now=None, progress=None, max_seconds=900):
    """Refresh an independent completed-price CSV; never modify raw input.

    Optional fetcher/clock are injectable for deterministic offline checks. The
    CLI has no clock override and always records real post-fetch UTC timestamps.
    """
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 8:
        raise ValueError('workers must be an integer between 1 and 8')
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not 0 < max_seconds <= 900:
        raise ValueError('max_seconds must be greater than zero and at most 900')
    clock = _cutoff(now) if now is not None else None
    raw = Path(prices_path) if prices_path is not None else REPO_ROOT / 'data' / 'daily_prices.csv'
    output = Path(output_path) if output_path is not None else REPO_ROOT / 'data' / 'chart_analogue' / 'closed_prices.csv'
    if raw.resolve() == output.resolve():
        raise ValueError('Completed adjusted snapshots must be separate from raw prices')
    names = _universe(raw)
    if symbols is None:
        requested = sorted(names)
    else:
        if isinstance(symbols, str):
            symbols = symbols.split(',')
        requested = sorted(set(str(value).strip() for value in symbols))
        if not requested or len(requested) > MAX_SYMBOLS or any(not re.fullmatch(r'\d{6}', symbol, flags=re.ASCII) or symbol not in names for symbol in requested):
            raise ValueError('symbols must be bounded six-digit codes in the input universe')
    if not requested:
        raise ValueError('No valid KR symbols were found in the input universe')
    snapshots = _previous(output, names)
    original = set(snapshots)
    rejected = Counter({key: 0 for key in ['bad_date', 'bad_price', 'intraday', 'non_session_date', 'duplicate_sessions', 'conflicting_duplicates']})
    succeeded, failed = 0, 0
    successful_symbols = set()
    provider = fetcher or fetch_history

    def collect(symbol):
        payload = provider(symbol)
        captured = clock if clock is not None else datetime.now(timezone.utc)
        rows, dropped = _parse(payload, symbol, captured)
        return rows, dropped

    budget_expired = False
    started = monotonic_time.monotonic()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='chart-source') as executor:
        futures = {executor.submit(collect, symbol): symbol for symbol in requested}
        try:
            for completed, future in enumerate(as_completed(futures, timeout=max_seconds), start=1):
                if monotonic_time.monotonic() - started >= max_seconds:
                    raise TimeoutError('Collection budget expired')
                symbol = futures[future]
                try:
                    new_rows, dropped = future.result()
                    snapshots[symbol] = new_rows
                    rejected.update(dropped)
                    succeeded += 1
                    successful_symbols.add(symbol)
                except (requests.RequestException, UrllibHTTPError, ValueError, ET.ParseError, TimeoutError, OSError, TypeError) as error:
                    if isinstance(error, InvalidSnapshot):
                        rejected.update(error.rejected)
                    failed += 1
                if progress is not None and (completed % 200 == 0 or completed == len(requested)):
                    progress({'completed': completed, 'attempted': len(requested), 'succeeded': succeeded, 'failed': failed})
        except TimeoutError:
            budget_expired = True
            for future in futures:
                future.cancel()
            failed = len(requested) - succeeded
    # Explicitly track which requests succeeded without changing retained stamps.
    preserved = sum(symbol in original and symbol not in successful_symbols for symbol in requested)
    row_count = sum(len(rows) for rows in snapshots.values())
    if row_count > MAX_ROWS:
        raise ValueError('Completed source snapshot exceeds the corpus row bound')
    report = {'status': 'failed' if succeeded == 0 else ('partial' if failed else 'complete'),
              'source_id': SOURCE_ID, 'price_basis': PRICE_BASIS,
              'attempted_symbols': len(requested), 'succeeded_symbols': succeeded,
              'failed_symbols': failed, 'preserved_symbols': preserved,
              'symbols': len(snapshots), 'rows': row_count, 'rejected': dict(rejected),
              'budget_expired': budget_expired,
              'collection_summary': {'fresh_symbols': len(successful_symbols),
                                     'cache_preserved_symbols': len(snapshots) - len(successful_symbols),
                                     'untracked_symbols': 0}}
    if succeeded == 0:
        return report
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.closed-prices-', suffix='.csv', dir=str(output.parent))
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            for symbol in sorted(snapshots):
                for day, close, stamp in snapshots[symbol]:
                    writer.writerow({'ticker': symbol, 'date': day, 'name': names[symbol], 'current_price': close,
                                     'update_time': stamp, 'price_basis': PRICE_BASIS, 'source_id': SOURCE_ID,
                                     'collection_status': 'fresh' if symbol in successful_symbols else 'cache_preserved'})
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    report['latest_session'] = max(row[0] for rows in snapshots.values() for row in rows)
    report['captured_at'] = max(row[2] for rows in snapshots.values() for row in rows)
    return report
