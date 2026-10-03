#!/usr/bin/env python3
"""Acquire archived KRX capitalization metadata, then scope numeric outputs.

Annual source files contain the exchange universe solely for historical ranking.
The cohort CSVs contain at most the report's 100 symbols. This collector performs
no price-pattern analysis, financial imputation, orders, or credential access.
Requires optional research dependency pyarrow; Marcap Close is RAW, not the
adjusted price series used by the separate historical-price collector.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_BASE = 'https://raw.githubusercontent.com/FinanceData/marcap/master/data'
COLUMNS = ['Date', 'Code', 'Name', 'Market', 'MarketId', 'Marcap', 'Stocks',
           'Rank', 'Close', 'Volume']
CSV_FIELDS = ['date', 'symbol', 'name', 'market', 'source_market', 'market_id', 'market_cap',
              'shares_outstanding', 'raw_close', 'volume', 'tradable', 'source_rank']


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(512 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_universe(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    ranked = raw.get('ranking', {}).get('ranked', [])
    if not isinstance(ranked, list) or not 1 <= len(ranked) <= 100:
        raise ValueError('Universe report must contain 1 to 100 ranked symbols')
    symbols = [str(row.get('symbol', '')).strip() for row in ranked]
    if any(not re.fullmatch(r'[0-9A-Z]{6}', code) for code in symbols):
        raise ValueError('Universe contains an invalid six-character symbol')
    if len(set(symbols)) != len(symbols):
        raise ValueError('Universe contains duplicate symbols')
    return {'symbols': set(symbols), 'as_of': raw['ranking'].get('as_of'),
            'path': str(Path(path).resolve()), 'sha256': sha256(path)}


class ByteBudget:
    def __init__(self, maximum):
        self.maximum = int(maximum)
        self.used = 0
        self.lock = threading.Lock()

    def claim(self, size):
        with self.lock:
            if self.used + size > self.maximum:
                raise ValueError('Total download byte limit exceeded')
            self.used += size


def download_year(year, out, *, budget, existing=None,
                  max_file_bytes=40_000_000, timeout=20):
    """Atomic bounded download, or hash-verified reuse preserving capture time."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'marcap-{year}.parquet'
    temporary = path.with_name(path.name + '.part')
    if existing and existing.get('download_status') == 'complete':
        if existing.get('year') != year or existing.get('source_url') != f'{SOURCE_BASE}/marcap-{year}.parquet':
            raise ValueError(f'Cached source identity mismatch for {year}')
        cached = Path(existing['path'])
        if not cached.exists() or sha256(cached) != existing.get('sha256'):
            raise ValueError(f'Cached source hash mismatch for {year}')
        if cached.stat().st_size > max_file_bytes:
            raise ValueError('Cached source exceeds per-file byte limit')
        if path.exists() and sha256(path) != existing['sha256']:
            raise ValueError(f'Destination source hash mismatch for {year}')
        if not path.exists():
            try:
                shutil.copyfile(cached, temporary)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        record = dict(existing, path=str(path.resolve()), reused=True)
        if cached.resolve() != path.resolve():
            record['source_cache_path'] = str(cached.resolve())
        return record
    if path.exists():
        raise ValueError(f'Existing source lacks a verified capture manifest: {year}')
    url = f'{SOURCE_BASE}/marcap-{year}.parquet'
    started = utc_now()
    received = 0
    digest = hashlib.sha256()
    headers = {}
    try:
        request = Request(url, headers={'User-Agent': 'MarketFlow-large-cap-metadata-research/1.0'})
        with urlopen(request, timeout=timeout) as response:
            declared = int(response.headers.get('Content-Length') or 0)
            if declared > max_file_bytes:
                raise ValueError('Per-file download byte limit exceeded')
            headers = {key: response.headers.get(key) for key in
                       ('Content-Length', 'Content-Type', 'ETag', 'Last-Modified')}
            with temporary.open('wb') as handle:
                while True:
                    chunk = response.read(512 * 1024)
                    if not chunk:
                        break
                    if received + len(chunk) > max_file_bytes:
                        raise ValueError('Per-file download byte limit exceeded')
                    budget.claim(len(chunk))
                    handle.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
            status = response.status
        if declared and declared != received:
            raise ValueError('Incomplete source download')
        with temporary.open('rb') as handle:
            magic = handle.read(4)
            handle.seek(-4, os.SEEK_END)
            trailer = handle.read(4)
        if magic != b'PAR1' or trailer != b'PAR1':
            raise ValueError('Source is not a Parquet file')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {'year': year, 'source_url': url, 'provider': 'FinanceData/marcap archived KRX',
            'capture_started_utc': started, 'capture_completed_utc': utc_now(),
            'http_status': status, 'headers': headers, 'byte_count': received,
            'sha256': digest.hexdigest(), 'path': str(path.resolve()),
            'download_status': 'complete', 'reused': False}


def _csv_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return '' if not math.isfinite(value) else format(value, '.0f')
    return '' if value is None else value


def _write_csv(path, frame, *, membership=False):
    temporary = path.with_name(path.name + '.part')
    fields = CSV_FIELDS + (['rank'] if membership else [])
    try:
        with temporary.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for raw in frame.to_dict('records'):
                row = dict(date=raw['Date'], symbol=raw['Code'], name=raw['Name'],
                           market=raw['Market'], source_market=raw['SourceMarket'], market_id=raw['MarketId'],
                           market_cap=raw['Marcap'], shares_outstanding=raw['Stocks'],
                           raw_close=raw['Close'], volume=raw['Volume'],
                           tradable=bool(raw['Volume'] > 0 and raw['Close'] > 0),
                           source_rank=raw['Rank'])
                if membership:
                    row['rank'] = raw['ComputedRank']
                writer.writerow({key: _csv_value(value) for key, value in row.items()})
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def extract_year(source, symbols, out, *, year, batch_size=16384):
    """Validate every usable source row; retain cohort and ranking metadata only."""
    try:
        import numpy as np
        import pandas as pd
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError('Install optional research dependency pyarrow to read annual archives') from error
    source = Path(source)
    out = Path(out)
    if not 1 <= len(symbols) <= 100:
        raise ValueError('Scope must contain 1 to 100 symbols')
    archive = pq.ParquetFile(source)
    if not set(COLUMNS).issubset(archive.schema_arrow.names):
        raise ValueError('Historical source schema is missing required columns')
    selected, candidates = [], []
    dates, source_codes, markets = set(), set(), set()
    unit = dict(verified_rows=0, mismatched_rows=0, unknown_rows=0, zero_or_nonpositive_rows=0)
    max_batch_bytes = 0
    for batch in archive.iter_batches(batch_size=batch_size, columns=COLUMNS, use_threads=False):
        max_batch_bytes = max(max_batch_bytes, batch.nbytes)
        frame = batch.to_pandas()
        parsed_dates = pd.to_datetime(frame['Date'], errors='coerce')
        if parsed_dates.isna().any() or (parsed_dates.dt.year != year).any():
            raise ValueError('Archive contains missing dates or dates outside its year')
        frame['Date'] = parsed_dates.dt.strftime('%Y-%m-%d')
        frame['Code'] = frame['Code'].astype(str).str.strip()
        if not frame['Code'].str.fullmatch(r'[0-9A-Z]{6}').all():
            raise ValueError('Archive contains an invalid symbol')
        markets.update(frame['Market'].dropna().unique())
        frame['SourceMarket'] = frame['Market']
        frame['Market'] = frame['Market'].replace({'KOSDAQ GLOBAL': 'KOSDAQ'})
        for column in ('Marcap', 'Stocks', 'Close', 'Volume', 'Rank'):
            frame[column] = pd.to_numeric(frame[column], errors='coerce')
        values = frame[['Marcap', 'Close', 'Stocks']].to_numpy(dtype=float)
        finite = np.isfinite(values).all(axis=1)
        positive = (values > 0).all(axis=1)
        valid = finite & positive
        expected = values[valid, 1] * values[valid, 2]
        mismatch = ~np.isclose(values[valid, 0], expected, rtol=1e-12, atol=1)
        unit['verified_rows'] += int(valid.sum())
        unit['mismatched_rows'] += int(mismatch.sum())
        unit['unknown_rows'] += int((~finite).sum())
        unit['zero_or_nonpositive_rows'] += int((finite & ~positive).sum())
        dates.update(frame['Date'].unique())
        source_codes.update(frame['Code'].unique())
        cohort = frame.loc[frame['Code'].isin(symbols)].copy()
        if len(cohort):
            selected.append(cohort)
        eligible = frame.loc[frame['Market'].isin(['KOSPI', 'KOSDAQ']) & valid]
        for _, group in eligible.groupby('Date', sort=False):
            candidates.append(group.sort_values(['Marcap', 'Code'], ascending=[False, True]).head(100))
    if unit['mismatched_rows']:
        raise ValueError(f'Market-cap unit validation failed for {year}: {unit["mismatched_rows"]} rows')
    cohort = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame(columns=COLUMNS)
    pool = pd.concat(candidates, ignore_index=True) if candidates else pd.DataFrame(columns=COLUMNS)
    for frame in (cohort, pool):
        if frame.duplicated(['Date', 'Code']).any():
            raise ValueError('Source has duplicate symbol/day rows in the retained scope')
    cohort = cohort.sort_values(['Code', 'Date'])
    pool = pool.sort_values(['Date', 'Marcap', 'Code'], ascending=[True, False, True])
    membership = pool.groupby('Date', sort=False).head(100).copy()
    membership['ComputedRank'] = membership.groupby('Date', sort=False).cumcount() + 1
    out.mkdir(parents=True, exist_ok=True)
    cohort_path = out / f'current_top100_caps_{year}.csv'
    membership_path = out / f'historical_top100_membership_{year}.csv'
    _write_csv(cohort_path, cohort)
    _write_csv(membership_path, membership, membership=True)
    coverage = []
    for code in sorted(symbols):
        rows = cohort.loc[cohort['Code'] == code]
        coverage.append(dict(symbol=code, rows=len(rows),
                             first_date=rows['Date'].min() if len(rows) else None,
                             last_date=rows['Date'].max() if len(rows) else None,
                             zero_volume_rows=int((rows['Volume'] == 0).sum())))
    counts = membership.groupby('Date').size()
    return dict(year=year, source_rows=archive.metadata.num_rows,
                source_schema=str(archive.schema_arrow), source_first_date=min(dates) if dates else None,
                source_last_date=max(dates) if dates else None, source_trading_days=len(dates),
                source_distinct_symbols=len(source_codes), source_markets=sorted(markets), unit_check=unit,
                current_cohort_rows=len(cohort), current_cohort_symbols_with_rows=int(cohort['Code'].nunique()),
                current_cohort_missing_symbols=sorted(symbols - set(cohort['Code'])),
                current_cohort_coverage=coverage, current_cohort_path=str(cohort_path.resolve()),
                historical_membership_rows=len(membership),
                historical_membership_distinct_symbols=int(membership['Code'].nunique()),
                historical_membership_rows_per_day_min=int(counts.min()) if len(counts) else 0,
                historical_membership_rows_per_day_max=int(counts.max()) if len(counts) else 0,
                historical_membership_path=str(membership_path.resolve()), max_arrow_batch_bytes=max_batch_bytes,
                output_sha256={path.name: sha256(path) for path in (cohort_path, membership_path)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe-report', type=Path, required=True)
    parser.add_argument('--years', nargs='+', type=int, default=list(range(2015, datetime.now().year + 1)))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--input-cache', type=Path)
    parser.add_argument('--fetch', action='store_true', help='Explicitly allow download of missing annual source files')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--max-file-bytes', type=int, default=40_000_000)
    parser.add_argument('--max-total-bytes', type=int, default=400_000_000)
    args = parser.parse_args(argv)
    summary = None
    try:
        if not 1 <= args.workers <= 3 or not 1 <= args.timeout <= 20:
            raise ValueError('Use at most 3 workers and 20 seconds socket timeout')
        if not 0 < args.max_file_bytes <= 40_000_000 or not 0 < args.max_total_bytes <= 400_000_000:
            raise ValueError('Maximum acquisition limits are 40 MB per file and 400 MB total')
        years = sorted(set(args.years))
        if not years or any(year < 1995 or year > datetime.now().year for year in years):
            raise ValueError('Requested year is outside the archival range')
        universe = load_universe(args.universe_report)
        try:
            import pyarrow.parquet  # noqa: F401
        except ImportError as error:
            raise ValueError('Install optional research dependency pyarrow before acquisition') from error
        args.out.mkdir(parents=True, exist_ok=True)
        existing = {}
        for directory in (args.input_cache, args.out):
            if directory and (directory / 'download_manifest.json').exists():
                old = json.loads((directory / 'download_manifest.json').read_text(encoding='utf-8'))
                existing.update({int(row['year']): row for row in old.get('files', [])})
        missing = [year for year in years if existing.get(year, {}).get('download_status') != 'complete'
                   or not Path(existing[year]['path']).is_file()]
        if missing and not args.fetch:
            raise ValueError(f'Cached source missing for years {missing}; pass --fetch to authorize network acquisition')
        records = {year: record for year, record in existing.items() if year in years}
        budget = ByteBudget(args.max_total_bytes)
        manifest_path = args.out / 'download_manifest.json'

        def persist():
            write_json_atomic(manifest_path, dict(captured_utc=utc_now(), downloaded_bytes=budget.used,
                max_total_bytes=args.max_total_bytes, max_file_bytes=args.max_file_bytes,
                max_workers=args.workers, socket_timeout_seconds=args.timeout,
                files=[records[year] for year in sorted(records)]))

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(download_year, year, args.out, budget=budget,
                existing=existing.get(year), max_file_bytes=args.max_file_bytes,
                timeout=args.timeout): year for year in years}
            for future in as_completed(futures):
                year = futures[future]
                try:
                    records[year] = future.result()
                except Exception as error:
                    records[year] = dict(year=year, download_status='failed', error=str(error), captured_utc=utc_now())
                persist()
                print(json.dumps(dict(year=year, download_status=records[year]['download_status'],
                                      reused=records[year].get('reused', False))), flush=True)
        failures = [year for year in years if records[year]['download_status'] != 'complete']
        if failures:
            raise ValueError(f'Acquisition incomplete for years {failures}; verified files retained for resume')
        summary = dict(status='running', requested_years=years, captured_utc=utc_now(), cohort_codes_count=len(universe['symbols']),
            cohort_as_of=universe['as_of'], current_cohort_source=universe['path'],
            current_cohort_source_sha256=universe['sha256'], source_units={'Marcap': 'KRW',
                'Close': 'KRW raw/unadjusted, only market-cap unit validation', 'Stocks': 'shares'},
            membership_scope='daily actual KOSPI/KOSDAQ market-cap top100; historical quality/share type not verified',
            market_normalization={'KOSDAQ GLOBAL': 'KOSDAQ'},
            ranking_method='Marcap descending, symbol ascending tie break; original source Rank is separate',
            tradability_method='same-day positive volume and raw close proxy; exchange trading status not verified',
            timing='Use completed prior-session capitalization for subsequent-session eligibility; never current shares retroactively',
            point_in_time_limitation='Archived observation dates are historical; original publication/revision vintages are not proven by a present capture',
            license_status='Public retrieval, no explicit dataset license located; verify KRX/data redistribution rights before publication',
            price_basis='raw_close must not be mixed with adjusted historical OHLC', files=[])
        for year in years:
            result = extract_year(records[year]['path'], universe['symbols'], args.out, year=year)
            result['source_provenance'] = records[year]
            summary['files'].append(result)
            write_json_atomic(args.out / 'verification_summary.json', summary)
            print(json.dumps(dict(year=year, first_date=result['source_first_date'], last_date=result['source_last_date'],
                cohort_symbols=result['current_cohort_symbols_with_rows'], unit_check=result['unit_check'])), flush=True)
        summary['status'] = 'complete'
        write_json_atomic(args.out / 'verification_summary.json', summary)
        return 0
    except Exception as error:
        if summary is not None:
            summary['status'] = 'incomplete'
            summary['error'] = str(error)
            write_json_atomic(args.out / 'verification_summary.json', summary)
        print(f'Market-cap acquisition failed: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
