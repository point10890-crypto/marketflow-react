#!/usr/bin/env python3
"""Refresh public TOP100/financial/OHLCV research inputs, then publish one pointer.

Collectors require explicit --fetch. Dry runs launch nothing. Every completed
snapshot is sealed; partial collector stages can be resumed without replacing
the last valid snapshot. Source adjustment/vintage limitations remain false.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from filelock import FileLock, Timeout

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
SOURCE = 'naver_sise_json_public'
BASIS = 'provider_reported_unverified'


class RefreshError(ValueError):
    """A safe code, never a collector URL, credential or raw traceback."""


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise RefreshError('invalid_session_date')
    return value


def _capture(value, now):
    try:
        captured = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError, TypeError):
        raise RefreshError('invalid_source_capture') from None
    if captured.utcoffset() is None or captured > now:
        raise RefreshError('future_or_unaware_source_capture')
    return captured


def latest_closed_weekday(now):
    """Calendar fallback, not a certified exchange/holiday calendar."""
    local = now.astimezone(KST)
    day = local.date()
    if local.time().replace(tzinfo=None) < time(15, 30):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def _period(as_of, year, report_code):
    if (year is None) != (report_code is None):
        raise RefreshError('year_and_report_code_must_be_paired')
    day = date.fromisoformat(as_of)
    if year is None:
        # Conservative standard deadlines; not a latest-filing search per issuer.
        if (day.month, day.day) >= (11, 16):
            year, report_code = day.year, '11014'
        elif (day.month, day.day) >= (8, 16):
            year, report_code = day.year, '11012'
        elif (day.month, day.day) >= (5, 16):
            year, report_code = day.year, '11013'
        elif (day.month, day.day) >= (4, 1):
            year, report_code = day.year-1, '11011'
        else:
            year, report_code = day.year-1, '11014'
    if (isinstance(year, bool) or not isinstance(year, int) or not 2015 <= year <= day.year
            or report_code not in {'11013', '11012', '11014', '11011'}):
        raise RefreshError('invalid_financial_period')
    period_end = f'{year}-'+{'11013': '03-31', '11012': '06-30', '11014': '09-30', '11011': '12-31'}[report_code]
    if period_end > as_of:
        raise RefreshError('financial_period_after_session')
    return year, report_code


def _inside(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise RefreshError('invalid_snapshot_path')
    path = (root/relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise RefreshError('snapshot_path_escapes_root')
    return path


def _reuse(root, as_of, settings):
    try:
        pointer = _json(root/'current.json')
        if pointer.get('schema_version') != 1 or pointer.get('as_of') != as_of or pointer.get('settings') != settings:
            return None
        for key in ('prices', 'price_manifest', 'universe_report'):
            if _hash(_inside(root, pointer[key])) != pointer['hashes'][key]:
                return None
        return dict(status='complete', reused=True, **pointer)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _recover_sealed(root, destination, as_of, settings, now):
    pointer = _json(destination/'sealed.json')
    if (pointer.get('schema_version') != 1 or pointer.get('snapshot_id') != destination.name
            or pointer.get('as_of') != as_of or pointer.get('settings') != settings):
        raise RefreshError('sealed_snapshot_identity_mismatch')
    for key in ('prices', 'price_manifest', 'universe_report'):
        if _hash(_inside(root, pointer[key])) != pointer['hashes'][key]:
            raise RefreshError('sealed_snapshot_artifact_changed')
    _capture(pointer['source_metadata']['captured_at'], now)
    _scope(_inside(root, pointer['universe_report']), as_of, now)
    _write(root/'current.json', pointer)
    _write(root/'last_attempt.json', dict(status='complete', as_of=as_of,
                                        snapshot_id=destination.name, recovered_publication=True))
    return dict(status='complete', reused=True, **pointer)


def _scope(path, as_of, now):
    report = _json(path)
    if report.get('as_of') != as_of:
        raise RefreshError('scope_date_does_not_match_source_request')
    ranking, quality = report.get('ranking', {}), report.get('quality', {})
    if any(group.get('as_of', as_of) != as_of for group in (ranking, quality)):
        raise RefreshError('mixed_scope_dates')
    ranked, results, passed = ranking.get('ranked'), quality.get('results'), quality.get('passed')
    if not isinstance(ranked, list) or len(ranked) != 100:
        raise RefreshError('complete_top100_required')
    identities = [row.get('symbol') for row in ranked]
    if (len(set(identities)) != 100 or any(not isinstance(symbol, str) or not re.fullmatch(r'\d{6}', symbol) for symbol in identities)
            or {row.get('rank') for row in ranked} != set(range(1, 101))):
        raise RefreshError('invalid_top100_identity')
    for row in ranked:
        cap = row.get('market_cap')
        if (row.get('market') not in {'KOSPI', 'KOSDAQ'} or not isinstance(row.get('name'), str)
                or not row['name'].strip() or isinstance(cap, bool) or not isinstance(cap, (int, float))
                or not math.isfinite(cap) or cap <= 0):
            raise RefreshError('invalid_top100_source_values')
    if (not isinstance(results, list) or not isinstance(passed, list)
            or len(results) != 100 or {row.get('symbol') for row in results} != set(identities)):
        raise RefreshError('incomplete_quality_results')
    if {row.get('symbol') for row in passed} != {row['symbol'] for row in results if row.get('quality_pass') is True}:
        raise RefreshError('inconsistent_quality_passed_set')
    evidence = report.get('input_evidence', {})
    listing, financials = evidence.get('listing', {}), evidence.get('financials', {})
    if listing.get('as_of') != as_of:
        raise RefreshError('listing_date_unverified')
    for item in (listing, financials):
        if not item.get('path') or not Path(item['path']).resolve().is_relative_to(Path(path).resolve().parent.parent):
            raise RefreshError('scope_source_path_outside_snapshot')
        if not item.get('path') or _hash(item['path']) != item.get('sha256'):
            raise RefreshError('scope_source_hash_mismatch')
    captures = financials.get('fetched_at_by_batch')
    if not isinstance(captures, list) or not captures:
        raise RefreshError('financial_capture_missing')
    for stamp in captures:
        _capture(stamp, now)
    _capture(evidence.get('generated_at'), now)
    return report


def _prices(directory, scope_path, as_of, start, now):
    report, manifest = _json(directory/'report.json'), _json(directory/'manifest.json')
    scope = _json(scope_path)
    expected = {row['symbol'] for row in scope['ranking']['ranked']}
    if (manifest.get('end') != as_of or manifest.get('start') != start
            or manifest.get('universe_report_sha256') != _hash(scope_path)):
        raise RefreshError('collector_request_identity_mismatch')
    if (report.get('source') != SOURCE or report.get('price_basis') != BASIS
            or report.get('analysis_ready') is not False or report.get('historical_vintage_verified') is not False
            or report.get('corporate_action_adjustment_verified') is not False
            or report.get('point_in_time_universe_verified') is not False):
        raise RefreshError('unsupported_or_promoted_price_provenance')
    if (set(report.get('selected_symbols', [])) != expected or report.get('status_counts') != {'collected': 100}
            or _hash(directory/'prices.csv') != report.get('prices_sha256')):
        raise RefreshError('incomplete_or_modified_price_collection')
    metadata = report.get('symbols', [])
    if len(metadata) != 100 or {row.get('symbol') for row in metadata} != expected:
        raise RefreshError('price_symbol_metadata_mismatch')
    for row in metadata:
        if row.get('status') != 'collected' or row.get('coverage', {}).get('last_date') != as_of:
            raise RefreshError('stale_or_failed_symbol_prices')
        _capture(row.get('captured_at'), now)
    counts, latest, captures = Counter(), {}, set()
    with (directory/'prices.csv').open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'source', 'price_basis', 'analysis_ready', 'captured_at'}
        if not required.issubset(reader.fieldnames or []):
            raise RefreshError('collector_ohlcv_columns_missing')
        for row in reader:
            day, symbol = _day(row['date']), row['symbol']
            if symbol not in expected or not start <= day <= as_of:
                raise RefreshError('price_rows_outside_request')
            if row['source'] != SOURCE or row['price_basis'] != BASIS or row['analysis_ready'].lower() != 'false':
                raise RefreshError('mixed_or_promoted_price_row_source')
            stamp = _capture(row['captured_at'], now)
            if stamp < datetime.combine(date.fromisoformat(day), time(15, 30), KST):
                raise RefreshError('price_capture_before_session_close')
            counts[symbol] += 1
            latest[symbol] = max(latest.get(symbol, day), day)
            captures.add(stamp.isoformat())
    if set(counts) != expected or any(latest[symbol] != as_of for symbol in expected):
        raise RefreshError('actual_price_rows_are_stale')
    if sum(counts.values()) != report.get('total_rows') or any(counts[row['symbol']] != row['coverage'].get('rows') for row in metadata):
        raise RefreshError('price_row_count_mismatch')
    return report, max(captures)


def _diagnostic(stage, result):
    def raw(value):
        return value if isinstance(value, bytes) else str(value or '').encode('utf-8', errors='replace')
    stdout, stderr = raw(result.stdout), raw(result.stderr)
    http = re.search(rb'HTTP\s+(\d{3})\b', stderr)
    return dict(stage=stage, returncode=result.returncode,
                http_status=int(http[1]) if http else None,
                stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest(),
                error_category='http_failure' if http else 'collector_failed')


def _screen_projection(source, destination):
    """Project observed closes/volume for the older price-only screen reader.

    Halted OHLC rows are kept verbatim in the canonical acquisition. Removing
    unused O/H/L columns here never repairs, imputes or certifies those bars.
    """
    source, destination = Path(source), Path(destination)
    source_hash = _hash(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name+'.', suffix='.tmp', dir=destination.parent)
    rows = 0
    try:
        with source.open(encoding='utf-8-sig', newline='') as handle, os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as out:
            reader = csv.DictReader(handle)
            fields = [field for field in (reader.fieldnames or []) if field not in {'open', 'high', 'low'}]
            if not {'symbol', 'date', 'close'}.issubset(fields):
                raise RefreshError('screen_projection_columns_missing')
            writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in reader:
                writer.writerow(row)
                rows += 1
            out.flush()
            os.fsync(out.fileno())
        if _hash(source) != source_hash:
            raise RefreshError('screen_projection_source_changed')
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return dict(path=str(source.resolve()), sha256=source_hash, rows=rows,
                transformation='close_volume_projection_no_ohlc_inference',
                projection_path=str(destination.resolve()), projection_sha256=_hash(destination), columns=fields)


def _link_screen_evidence(path, projection, first=None):
    report = _json(path)
    evidence = report['input_evidence']
    prices = evidence['prices']
    if (Path(prices.get('path', '')).resolve() != Path(projection['projection_path'])
            or prices.get('sha256') != projection['projection_sha256']):
        raise RefreshError('screen_projection_hash_mismatch')
    prices['source_price_input'] = projection
    if first is not None:
        # A local-input rerank does not recapture sources. Carry the original
        # verified evidence only after proving both bytes and path are equal.
        for key in ('listing', 'financials'):
            original, current = first['input_evidence'][key], evidence[key]
            if (original['sha256'] != current.get('sha256')
                    or Path(original['path']).resolve() != Path(current.get('path', '')).resolve()):
                raise RefreshError('scope_source_changed_during_collection')
            evidence[key] = dict(original)
    _write(path, report)


def refresh_inputs(*, root=None, seed_prices=None, as_of=None, start='2005-01-01',
                   fetch=False, dry_run=False, runner=None, now=None, year=None,
                   report_code=None, env_file=None, corp_codes=None):
    fixed_clock = now is not None
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise RefreshError('clock_timezone_required')
    as_of = _day(as_of or latest_closed_weekday(now))
    start = _day(start)
    if as_of > latest_closed_weekday(now) or start > as_of or date.fromisoformat(as_of).weekday() >= 5:
        raise RefreshError('requested_session_not_closed')
    year, report_code = _period(as_of, year, report_code)
    settings = dict(start=start, year=year, report_code=report_code, top_n=100)
    root = Path(root or ROOT/'data/alpha_lab/inputs').resolve()
    reused = _reuse(root, as_of, settings)
    if reused and not dry_run:
        return reused
    if seed_prices is None:
        try:
            seed_prices = _inside(root, _json(root/'current.json')['prices'])
        except (OSError, ValueError, KeyError, TypeError):
            seed_prices = ROOT/'data/kelly_research/long_history_20261002/prices/prices.csv'
    seed_prices = Path(seed_prices).resolve()
    if not seed_prices.is_file():
        raise RefreshError('seed_price_file_missing')
    request = dict(as_of=as_of, **settings, seed_prices_sha256=_hash(seed_prices), capture_day=now.astimezone(KST).date().isoformat())
    identity = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:20]
    snapshot_id = as_of+'-'+identity
    destination = root/'snapshots'/snapshot_id
    scope_dir, prices_dir, final_dir = destination/'scope', destination/'prices', destination/'universe'
    common = ['--as-of', as_of, '--top-n', '100', '--year', str(year), '--report-code', report_code]
    screen = str(ROOT/'scripts/screen_large_cap_kelly.py')
    listing = scope_dir/'sources'/f'listing_{as_of}.csv'
    financials = scope_dir/'sources'/'financials.json'
    seed_projection_path = scope_dir/'technical_prices.csv'
    final_projection_path = final_dir/'technical_prices.csv'
    commands = [
        [sys.executable, screen, '--prices', str(seed_projection_path), *common, '--fetch-listing', '--fetch-financials',
         '--env-file', str(env_file or ROOT/'.env'), '--corp-codes', str(corp_codes or ROOT/'data/dart_corp_codes.json'), '--out', str(scope_dir)],
        [sys.executable, str(ROOT/'scripts/collect_large_cap_price_history.py'), '--universe-report', str(scope_dir/'report.json'),
         '--output-dir', str(prices_dir), '--start', start, '--end', as_of, '--max-symbols', '100', '--workers', '3', '--retries', '2', '--fetch'],
        [sys.executable, screen, '--prices', str(final_projection_path), *common, '--listing', str(listing),
         '--financials', str(financials), '--out', str(final_dir)],
    ]
    if dry_run:
        return dict(status='dry_run', as_of=as_of, commands=commands,
                    calendar_verified=False, financial_period_policy='conservative_standard_deadline_not_latest_filing_search')
    if not fetch:
        raise RefreshError('fetch_opt_in_required')
    root.mkdir(parents=True, exist_ok=True)
    execute = runner or subprocess.run
    stage = 'scope'
    with FileLock(str(root/'.refresh.lock'), timeout=1):
        destination.mkdir(parents=True, exist_ok=True)
        if (destination/'sealed.json').exists():
            return _recover_sealed(root, destination, as_of, settings, now)
        try:
            for stage, command, output in zip(('scope', 'prices', 'final_scope'), commands,
                                               (scope_dir/'report.json', prices_dir/'report.json', final_dir/'report.json')):
                projection = None
                if stage == 'scope':
                    projection = _screen_projection(seed_prices, seed_projection_path)
                elif stage == 'final_scope':
                    projection = _screen_projection(prices_dir/'prices.csv', final_projection_path)
                # Collector outputs retain raw capture time and hash on retries.
                incomplete_prices = (stage == 'prices' and output.exists()
                                     and _json(output).get('status_counts') != {'collected': 100})
                if not output.exists() or incomplete_prices:
                    try:
                        result = execute(command, capture_output=True, text=True, timeout=1800, cwd=str(ROOT), check=False)
                    except (OSError, subprocess.TimeoutExpired) as error:
                        result = subprocess.CompletedProcess(command, -1, '', type(error).__name__)
                    if result.returncode:
                        _write(root/'last_attempt.json', dict(status='failed', as_of=as_of, snapshot_id=snapshot_id, **_diagnostic(stage, result)))
                        raise RefreshError('collector_failed:'+stage)
                observed_now = now if fixed_clock else datetime.now(timezone.utc)
                if stage == 'scope':
                    _link_screen_evidence(output, projection)
                    first = _scope(output, as_of, observed_now)
                elif stage == 'prices':
                    price_report, captured_at = _prices(prices_dir, scope_dir/'report.json', as_of, start, observed_now)
                else:
                    _link_screen_evidence(output, projection, first)
                    final = _scope(output, as_of, observed_now)
            if first['ranking']['ranked'] != final['ranking']['ranked'] or first['quality']['results'] != final['quality']['results']:
                raise RefreshError('scope_changed_during_collection')
            for key in ('listing', 'financials'):
                if first['input_evidence'][key]['sha256'] != final['input_evidence'][key]['sha256']:
                    raise RefreshError('scope_source_changed_during_collection')
            if final['input_evidence']['prices']['source_price_input'].get('sha256') != price_report['prices_sha256']:
                raise RefreshError('final_scope_price_hash_mismatch')
            artifacts = dict(prices=prices_dir/'prices.csv', price_manifest=prices_dir/'report.json', universe_report=final_dir/'report.json')
            pointer = dict(schema_version=1, snapshot_id=snapshot_id, as_of=as_of, latest_session=as_of,
                published_at=(now if fixed_clock else datetime.now(timezone.utc)).isoformat(), settings=settings,
                quality_count=len(final['quality']['passed']), ranked_count=100,
                hashes={key: _hash(path) for key, path in artifacts.items()},
                source_metadata=dict(price_source=SOURCE, price_basis=BASIS, captured_at=captured_at,
                    financial_captures=first['input_evidence']['financials']['fetched_at_by_batch'],
                    screen_price_input=final['input_evidence']['prices']['source_price_input'],
                    analysis_ready=False, corporate_action_adjustment_verified=False,
                    historical_vintage_verified=False, point_in_time_universe_verified=False,
                    current_cohort_bias=True, calendar_verified=False,
                    financial_period_policy='conservative_standard_deadline_not_latest_filing_search'),
                **{key: path.relative_to(root).as_posix() for key, path in artifacts.items()})
            _write(destination/'sealed.json', pointer)
            _write(root/'current.json', pointer)
            _write(root/'last_attempt.json', dict(status='complete', as_of=as_of, snapshot_id=snapshot_id))
            return dict(status='complete', reused=False, **pointer)
        except RefreshError as error:
            if not str(error).startswith('collector_failed:'):
                _write(root/'last_attempt.json', dict(status='failed', as_of=as_of, snapshot_id=snapshot_id,
                                                    stage=stage, error_code=str(error)))
            raise
        except (ValueError, KeyError, TypeError, OSError):
            _write(root/'last_attempt.json', dict(status='failed', as_of=as_of, snapshot_id=snapshot_id,
                                                stage=stage, error_code='invalid_collector_artifacts'))
            raise RefreshError('invalid_collector_artifacts:'+stage) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--seed-prices', type=Path)
    parser.add_argument('--as-of')
    parser.add_argument('--start', default='2005-01-01')
    parser.add_argument('--year', type=int)
    parser.add_argument('--report-code', choices=['11013', '11012', '11014', '11011'])
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--corp-codes', type=Path)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = refresh_inputs(**vars(args))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (RefreshError, ValueError, OSError, Timeout):
        # Detailed safe diagnostics live in last_attempt.json; no raw URL/key.
        print(json.dumps(dict(status='held', error='alpha_lab_input_refresh_failed')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
