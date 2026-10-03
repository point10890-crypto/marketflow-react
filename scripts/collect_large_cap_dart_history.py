#!/usr/bin/env python3
"""Bounded, resumable historical DART collection for a fixed current cohort.

Year-based API values are collected at today's correction state. Receipt dates
are publication proxies; neither exact historical numeric vintage nor a
historical market-cap universe is certified. No orders or model calls occur.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from filelock import FileLock, Timeout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'app/utils'))
from atomic_json import write_json_atomic
from screen_large_cap_kelly import DART_API, normalize_dart

REPORTS = [('11013', '03-31'), ('11012', '06-30'), ('11014', '09-30'), ('11011', '12-31')]
FIELDS = ('equity', 'liabilities', 'operating_profit', 'net_income')
ACCOUNTS = {'자본총계', '부채총계', '영업이익', '영업이익(손실)', '당기순이익', '당기순이익(손실)'}
ORIGINAL_SAMPLES = [('005930', '20160330003536'), ('000660', '20160516001867')]
MAX_JSON_BYTES = 25 * 1024 * 1024
MAX_ORIGINAL_BYTES = 25 * 1024 * 1024
KST = timezone(timedelta(hours=9))


class SourceBytes(bytes):
    """Retain a nonsecret media type alongside an in-memory response body."""

    def __new__(cls, body, content_type=None):
        result = super().__new__(cls, body)
        media = str(content_type or '').split(';', 1)[0].strip().lower()
        result.content_type = media if re.fullmatch(r'[a-z0-9.+_-]+/[a-z0-9.+_-]+', media) else None
        return result


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _instant(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Capture timestamp requires timezone')
    return result.astimezone(timezone.utc)


def _now(fixed=None):
    if fixed is not None and fixed.tzinfo is None:
        raise ValueError('Current timestamp requires timezone')
    return fixed.astimezone(timezone.utc) if fixed is not None else datetime.now(timezone.utc)


def _sanitize(value, key=''):
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if str(k).lower() in {'crtfc_key', 'api_key', 'dart_api_key', 'authorization'}
                else _sanitize(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v, key) for v in value]
    if isinstance(value, str):
        result = value.replace(key, '[REDACTED]') if key else value
        return re.sub(r'(crtfc_key=)[^&\s<>"\']+', r'\1[REDACTED]', result, flags=re.I)
    return value


def _api_key(env_file):
    from dotenv import dotenv_values
    # Dotenv parse warnings and network exception strings must never expose a key.
    with contextlib.redirect_stderr(io.StringIO()):
        key = str(dotenv_values(env_file).get('DART_API_KEY') or '').strip()
    if not key:
        raise ValueError('DART_API_KEY is not configured in the selected project')
    return key


def _get_bytes(url, params, *, max_bytes):
    request = Request(url + '?' + urlencode(params), headers={'User-Agent': 'MarketFlow-DART-history-research/1.0'})
    try:
        with urlopen(request, timeout=45) as response:
            content = response.read(max_bytes + 1)
            content_type = response.headers.get('Content-Type')
        if len(content) > max_bytes:
            raise ValueError('Source response exceeded byte budget')
        return SourceBytes(content, content_type)
    except HTTPError as error:
        raise ValueError(f'Source HTTP status {error.code}') from None
    except Exception:
        raise ValueError('Source request failed or exceeded byte budget') from None


def reporting_periods(start_year=2015, through_year=2026, through_report='11012'):
    if not 2015 <= start_year <= through_year <= date.today().year or through_report not in dict(REPORTS):
        raise ValueError('Reporting range must begin in 2015 or later and use a valid terminal report')
    terminal = [code for code, _ in REPORTS].index(through_report)
    return [dict(year=year, report_code=code, period_end=f'{year}-{end}')
            for year in range(start_year, through_year + 1)
            for index, (code, end) in enumerate(REPORTS) if year < through_year or index <= terminal]


def _cohort(report_path, mapping_path):
    raw = Path(report_path).read_bytes()
    source = json.loads(raw)
    rows = source.get('ranking', {}).get('ranked')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('A fixed ranking.ranked cohort of at most 100 companies is required')
    as_of = source.get('as_of')
    date.fromisoformat(as_of)
    symbols = [str(row.get('symbol', '')) for row in rows]
    if len(set(symbols)) != len(symbols) or any(not re.fullmatch(r'\d{6}', s) for s in symbols):
        raise ValueError('Cohort requires distinct six-digit stock symbols')
    mapping = _read(mapping_path)
    pairs = []
    for symbol in sorted(symbols):
        code = str(mapping.get(symbol) or '')
        if code and not re.fullmatch(r'\d{8}', code):
            raise ValueError('Corporate mapping requires eight-digit DART identifiers')
        if code:
            pairs.append(dict(symbol=symbol, corp_code=code))
    if len({p['corp_code'] for p in pairs}) != len(pairs):
        raise ValueError('Duplicate corporate identities in the requested cohort')
    return symbols, pairs, dict(path=str(Path(report_path).resolve()), sha256=_sha(raw), as_of=as_of,
        symbols=sorted(symbols), requested_count=len(symbols), mapped_count=len(pairs),
        missing_corp_codes=sorted(set(symbols) - {p['symbol'] for p in pairs}))


def _period_date(value):
    if not value:
        return None, 'missing_period_date'
    parts = re.findall(r'(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})', str(value))
    if not parts or len(parts) > 2:
        return None, 'invalid_period_date'
    try:
        days = [date(*map(int, p)) for p in parts]
    except ValueError:
        return None, 'invalid_period_date'
    if len(days) == 2 and days[0] > days[1]:
        return None, 'invalid_period_date'
    return days[-1].isoformat(), None


def _normalize(rows, period, fetched_at, requested):
    groups, issues = {}, {symbol: [] for symbol in requested}
    for raw in rows:
        symbol = str(raw.get('stock_code') or '')
        if symbol not in requested:
            continue
        receipt, fs = str(raw.get('rcept_no') or ''), raw.get('fs_div')
        try:
            if not re.fullmatch(r'\d{14}', receipt):
                raise ValueError()
            receipt_day = datetime.strptime(receipt[:8], '%Y%m%d').date()
        except ValueError:
            issues[symbol].append('invalid_receipt')
            continue
        if fs not in {'CFS', 'OFS'}:
            issues[symbol].append('unverified_statement_scope')
            continue
        groups.setdefault((symbol, receipt, fs), []).append(raw)
    values = []
    for (symbol, receipt, fs), accounts in groups.items():
        reasons, period_dates = [], []
        relevant = [row for row in accounts if row.get('account_nm') in ACCOUNTS]
        if not relevant:
            issues[symbol].append('missing_required_accounts')
            continue
        krw = [row for row in relevant if row.get('currency') == 'KRW']
        if len(krw) != len(relevant):
            reasons.append('non_KRW_account')
        if not krw:
            issues[symbol].extend(reasons)
            continue
        for raw in relevant:
            if str(raw.get('bsns_year') or '') != str(period['year']) or raw.get('reprt_code') != period['report_code']:
                reasons.append('report_identity_unverified')
            end, reason = _period_date(raw.get('thstrm_dt'))
            if reason:
                reasons.append(reason)
            elif end != period['period_end']:
                reasons.append('period_end_mismatch')
            period_dates.append(end)
        period_ok = bool(period_dates) and all(day == period['period_end'] for day in period_dates) and 'report_identity_unverified' not in reasons
        try:
            normalized = normalize_dart(krw, period_end=period['period_end'], fetched_at=fetched_at)
            row = normalized[0]
        except (ValueError, TypeError, IndexError):
            row = dict(symbol=symbol, fs_div=fs, rcept_no=receipt, fetched_at=fetched_at,
                currency='KRW', income_basis='year_to_date', source=DART_API, **{field: None for field in FIELDS})
            reasons.append('conflicting_or_invalid_account_amount')
        receipt_day = datetime.strptime(receipt[:8], '%Y%m%d').date()
        if receipt_day < date.fromisoformat(period['period_end']):
            reasons.append('receipt_before_period_end')
        if receipt_day > _instant(fetched_at).astimezone(KST).date():
            reasons.append('receipt_after_capture')
        reasons.extend(f'missing_{field}' for field in FIELDS if row[field] is None)
        row.update(period_end=period['period_end'] if period_ok else None,
            requested_period_end=period['period_end'], period_verified=period_ok,
            bsns_year=period['year'], report_code=period['report_code'],
            receipt_date=receipt_day.isoformat(), available_date=(receipt_day + timedelta(days=1)).isoformat(),
            available_date_basis='receipt_date_plus_one_day_proxy',
            observed_period_dates=sorted({str(raw.get('thstrm_dt') or '') for raw in relevant}),
            historical_vintage_verified=False, numeric_vintage_verified=False,
            research_usable=not reasons, completeness_reasons=sorted(set(reasons)))
        values.append(row)
    return sorted(values, key=lambda r: (r['symbol'], r['rcept_no'], r['fs_div'])), issues


def _valid_payload(payload):
    if not isinstance(payload, dict) or payload.get('status') not in {'000', '013'}:
        return False
    rows = payload.get('list') or []
    return isinstance(rows, list) and all(isinstance(row, dict) for row in rows) and (payload['status'] == '013' or bool(rows))


def _payload_identity(payload, pairs, period):
    expected = {p['symbol']: p['corp_code'] for p in pairs}
    return all(str(row.get('stock_code')) in expected
        and str(row.get('corp_code')) == expected[str(row.get('stock_code'))]
        and str(row.get('bsns_year')) == str(period['year'])
        and row.get('reprt_code') == period['report_code'] for row in payload.get('list') or [])


def _envelope(payload, *, pairs, period, fetched_at, raw_sha=None, imported=None, key=''):
    payload = _sanitize(payload, key)
    return dict(schema_version=1, source=DART_API, year=period['year'], report_code=period['report_code'],
        requested=pairs, fetched_at=fetched_at, raw_response_sha256=raw_sha,
        payload_sha256=_sha(_json_bytes(payload)), payload=payload,
        imported_source_path=str(imported.resolve()) if imported else None,
        imported_source_sha256=_sha(imported.read_bytes()) if imported else None,
        historical_vintage_verified=False)


def _valid_snapshot(envelope, pairs, period, now):
    try:
        return (envelope['source'] == DART_API and envelope['requested'] == pairs
                and envelope['year'] == period['year'] and envelope['report_code'] == period['report_code']
                and envelope['payload_sha256'] == _sha(_json_bytes(envelope['payload']))
                and _instant(envelope['fetched_at']) <= now and _valid_payload(envelope['payload'])
                and _payload_identity(envelope['payload'], pairs, period))
    except (KeyError, ValueError, TypeError):
        return False


def _import_capture(cache_dirs, pairs, period, now):
    code_identity = _sha(','.join(p['corp_code'] for p in pairs).encode())[:16]
    filename = f'dart_{period["year"]}_{period["report_code"]}_{code_identity}.json'
    for directory in cache_dirs:
        path = Path(directory) / filename
        if not path.exists():
            continue
        try:
            old = _read(path)
            age = now - _instant(old['fetched_at'])
            payload = old['payload']
            if old.get('source') == DART_API and timedelta(0) <= age < timedelta(days=1) and _valid_payload(payload) and _payload_identity(payload, pairs, period):
                return _envelope(payload, pairs=pairs, period=period, fetched_at=old['fetched_at'], imported=path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _ledger(path, identity=None):
    if path.exists():
        ledger = _read(path)
        if identity is not None and ledger.get('plan_identity') != identity:
            raise ValueError('Output plan identity changed; choose a different output directory')
        if not isinstance(ledger.get('financial_attempts'), list) or not isinstance(ledger.get('original_attempts'), list):
            raise ValueError('Invalid persistent request ledger')
        return ledger
    return dict(schema_version=1, plan_identity=identity, financial_attempts=[], original_attempts=[])


def collect_history(*, cohort_report, mapping_path, env_file, out, start_year=2015,
                    through_year=2026, through_report='11012', fetch=False, max_calls=96,
                    reuse_cache_dirs=(), transport=None, now=None):
    if not 0 <= max_calls <= 96:
        raise ValueError('Financial request budget must be between 0 and 96')
    current = _now(now)
    symbols, pairs, cohort = _cohort(cohort_report, mapping_path)
    periods = reporting_periods(start_year, through_year, through_report)
    if any(date.fromisoformat(p['period_end']) > current.astimezone(KST).date() for p in periods):
        raise ValueError('A requested reporting period ends in the future')
    batches = [pairs[i:i + 50] for i in range(0, len(pairs), 50)]
    identity = _sha(_json_bytes(dict(cohort_sha256=cohort['sha256'], requested=pairs, periods=periods)))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with FileLock(str(out / 'collection.lock'), timeout=0):
        ledger_path = out / 'request_ledger.json'
        ledger = _ledger(ledger_path, identity)
        write_json_atomic(str(ledger_path), ledger)
        before, captures, values, coverage, error = len(ledger['financial_attempts']), [], [], [], None
        key, completed, imported_count = '', 0, 0
        transport = transport or _get_bytes
        for period in periods:
            observed, notes = [], {s: ['missing_corp_code'] for s in cohort['missing_corp_codes']}
            statuses = []
            for batch in batches:
                batch_identity = _sha(_json_bytes(batch))[:16]
                path = out / 'sources' / f'dart_{period["year"]}_{period["report_code"]}_{batch_identity}.json'
                envelope = None
                if path.exists():
                    try:
                        envelope = _read(path)
                        if not _valid_snapshot(envelope, batch, period, current):
                            envelope = None
                    except (ValueError, OSError):
                        pass
                    if envelope is None:
                        error = 'invalid_completed_snapshot'
                        break
                else:
                    envelope = _import_capture(reuse_cache_dirs, batch, period, current)
                    if envelope is not None:
                        imported_count += 1
                        write_json_atomic(str(path), envelope)
                if envelope is None:
                    if not fetch:
                        error = 'fetch_required'
                        break
                    if len(ledger['financial_attempts']) >= max_calls:
                        error = 'financial_request_budget_exhausted'
                        break
                    if not key:
                        key = _api_key(env_file)
                    attempt = dict(year=period['year'], report_code=period['report_code'],
                        batch_identity=batch_identity, requested_symbols=[p['symbol'] for p in batch],
                        requested_at=_now(now).isoformat(), state='reserved')
                    ledger['financial_attempts'].append(attempt)
                    write_json_atomic(str(ledger_path), ledger)
                    try:
                        body = transport(DART_API, dict(crtfc_key=key,
                            corp_code=','.join(p['corp_code'] for p in batch), bsns_year=period['year'],
                            reprt_code=period['report_code']), max_bytes=MAX_JSON_BYTES)
                        if not isinstance(body, bytes) or len(body) > MAX_JSON_BYTES:
                            raise ValueError('Invalid bounded source body')
                        payload = json.loads(body)
                        captured = _now(now).isoformat()
                        if not _valid_payload(payload) or not _payload_identity(payload, batch, period):
                            error = 'invalid_source_response' if not _valid_payload(payload) else 'invalid_source_identity'
                            attempt.update(state='source_error', response_sha256=_sha(body),
                                error=error, fetched_at=captured)
                            write_json_atomic(str(out / 'failures' / f'financial_{len(ledger["financial_attempts"]):03d}.json'),
                                dict(fetched_at=captured, source=DART_API, payload=_sanitize(payload, key), raw_response_sha256=_sha(body)))
                        else:
                            envelope = _envelope(payload, pairs=batch, period=period, fetched_at=captured, raw_sha=_sha(body), key=key)
                            write_json_atomic(str(path), envelope)
                            attempt.update(state='completed', response_sha256=_sha(body))
                    except Exception:
                        attempt.update(state='source_error', error='source_request_failed')
                        error = 'source_request_failed'
                    write_json_atomic(str(ledger_path), ledger)
                    if error:
                        break
                payload = envelope['payload']
                completed += 1
                capture = {k: v for k, v in envelope.items() if k not in {'payload', 'requested'}}
                capture.update(path=str(path.resolve()), artifact_sha256=_sha(path.read_bytes()),
                    requested_symbols=[p['symbol'] for p in batch], status=payload['status'])
                captures.append(capture)
                statuses.append(payload['status'])
                batch_symbols = [p['symbol'] for p in batch]
                if payload['status'] == '013':
                    notes.update({s: ['DART_status_013'] for s in batch_symbols})
                    continue
                normalized, issues = _normalize(payload.get('list') or [], period, envelope['fetched_at'], batch_symbols)
                values.extend(normalized)
                observed.extend(normalized)
                for s, reasons in issues.items():
                    notes.setdefault(s, []).extend(reasons)
            found = {r['symbol'] for r in observed}
            for symbol in symbols:
                symbol_rows = [r for r in observed if r['symbol'] == symbol]
                if not symbol_rows:
                    notes.setdefault(symbol, []).append('not_collected' if error else 'no_valid_statement_rows')
                elif not any(r['research_usable'] for r in symbol_rows):
                    notes.setdefault(symbol, []).extend(reason for r in symbol_rows for reason in r['completeness_reasons'])
            # A status-013 result is a known source hole, not an unexpected parse failure.
            notes = {s: sorted(set(reasons)) for s, reasons in notes.items() if reasons}
            for s in notes:
                if 'DART_status_013' in notes[s]:
                    notes[s] = ['DART_status_013']
            coverage.append(dict(**period, requested_symbols=len(symbols), returned_symbols=len(found),
                research_usable_symbols=len({r['symbol'] for r in observed if r['research_usable']}),
                missing_symbols=sorted(set(symbols) - found), symbol_reasons=notes, batch_statuses=statuses))
            if error:
                break
        values.sort(key=lambda r: (r['symbol'], r['bsns_year'], r['report_code'], r['rcept_no'], r['fs_div']))
        write_json_atomic(str(out / 'financials.json'), values)
        report = dict(schema_version=1, status='partial' if error else 'complete', error=error,
            source=DART_API, cohort=cohort, periods=periods, historical_vintage_verified=False,
            historical_universe_verified=False, available_date_basis='receipt_date_plus_one_day_proxy',
            financials_path=str((out / 'financials.json').resolve()), financials_sha256=_sha((out / 'financials.json').read_bytes()),
            generated_at=_now(now).isoformat(), records=len(values), research_usable_records=sum(r['research_usable'] for r in values),
            budget=dict(limit=max_calls, calls_total=len(ledger['financial_attempts']),
                calls_this_run=len(ledger['financial_attempts']) - before, planned_batches=len(periods) * len(batches),
                completed_batches=completed, imported_captures_this_run=imported_count),
            captures=captures, coverage=coverage, live_orders=False,
            limitations=['Current-cohort survivorship bias remains; historical market-cap membership is unverified.',
                'Year-based DART responses cannot select an earlier correction vintage.',
                'Receipt-date-plus-one availability is a conservative proxy, not exact historical numeric proof.',
                'Calendar reporting end dates are verified against source thstrm_dt; ambiguous or different fiscal periods are held.',
                'Both CFS and OFS are preserved separately; quarterly income requires cumulative amounts.'])
        write_json_atomic(str(out / 'collection_report.json'), report)
        return report


def _zip_metadata(body):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > 5000 or sum(info.file_size for info in infos) > 100 * 1024 * 1024:
            raise ValueError('Archive expansion exceeds validation budget')
        for info in infos:
            name = info.filename.replace('\\', '/')
            parts = PurePosixPath(name)
            if parts.is_absolute() or '..' in parts.parts or ':' in name or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Unsafe archive member path')
        if archive.testzip() is not None:
            raise ValueError('Archive CRC failed')
        return dict(members=len(infos), uncompressed_bytes=sum(info.file_size for info in infos),
                    zip_structure_verified=True, archive_integrity_verified=True)


def _write_bytes(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.tmp_', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _original_failure_diagnostics(attempt):
    return dict(source_status=attempt.get('source_status'), body_bytes=attempt.get('body_bytes'),
        content_type=attempt.get('content_type'), response_sha256=attempt.get('response_sha256'),
        archive_error_reason=attempt.get('archive_error_reason'),
        diagnostics_available=attempt.get('body_bytes') is not None)


def _original_error_reason(error, stage):
    # Only local fixed reason codes, never arbitrary upstream exception strings.
    if stage != 'archive':
        return 'source_request_or_storage_failed'
    if isinstance(error, zipfile.BadZipFile):
        return 'archive_format_or_crc_error'
    if isinstance(error, UnicodeError):
        return 'archive_member_encoding_error'
    if isinstance(error, NotImplementedError):
        return 'archive_unsupported_compression'
    if isinstance(error, ValueError):
        return {'Archive expansion exceeds validation budget': 'archive_expansion_budget_exceeded',
            'Unsafe archive member path': 'unsafe_archive_member_path',
            'Archive CRC failed': 'archive_crc_failed'}.get(str(error), 'archive_validation_failed')
    return 'archive_validation_failed'


def collect_original_samples(*, out, env_file, fetch=False, max_calls=4,
                             max_total_bytes=MAX_ORIGINAL_BYTES, transport=None, now=None):
    if not 0 <= max_calls <= 4 or not 0 < max_total_bytes <= MAX_ORIGINAL_BYTES:
        raise ValueError('Original samples require at most four calls and 25 MB total storage')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with FileLock(str(out / 'collection.lock'), timeout=0):
        ledger_path = out / 'request_ledger.json'
        if not ledger_path.exists():
            raise ValueError('Collect the fixed cohort before requesting original samples')
        ledger = _ledger(ledger_path)
        before, captures, failures = len(ledger['original_attempts']), [], []
        stored = sum((out / 'originals' / f'{symbol}_{receipt}_{kind}.zip').stat().st_size
            for symbol, receipt in ORIGINAL_SAMPLES for kind in ('document', 'xbrl')
            if (out / 'originals' / f'{symbol}_{receipt}_{kind}.zip').exists())
        key, transport = '', transport or _get_bytes
        for symbol, receipt in ORIGINAL_SAMPLES:
            for kind, endpoint in [('document', 'document.xml'), ('xbrl', 'fnlttXbrl.xml')]:
                path = out / 'originals' / f'{symbol}_{receipt}_{kind}.zip'
                meta_path = path.with_suffix('.json')
                failure = dict(symbol=symbol, rcept_no=receipt, kind=kind)
                source = 'https://opendart.fss.or.kr/api/' + endpoint
                if path.exists() and meta_path.exists():
                    try:
                        meta = _read(meta_path)
                        valid = (meta.get('sha256') == _sha(path.read_bytes()) and meta.get('rcept_no') == receipt
                            and meta.get('source') == source and meta.get('kind') == kind
                            and meta.get('symbol') == symbol and _instant(meta['fetched_at']) <= _now(now))
                    except (ValueError, OSError, KeyError, TypeError):
                        valid = False
                    if not valid:
                        failures.append(dict(failure, error='invalid_original_snapshot'))
                        continue
                    captures.append(meta)
                    continue
                if path.exists() or meta_path.exists():
                    failures.append(dict(failure, error='incomplete_original_snapshot'))
                    continue
                previous = [attempt for attempt in ledger['original_attempts']
                    if attempt.get('rcept_no') == receipt and attempt.get('kind') == kind and attempt.get('state') == 'source_error']
                if previous and (not fetch or len(ledger['original_attempts']) >= max_calls):
                    attempt = previous[-1]
                    failures.append(dict(failure, error=attempt['error'], **_original_failure_diagnostics(attempt)))
                    continue
                remaining = max_total_bytes - stored
                if remaining <= 0:
                    failures.append(dict(failure, error='original_byte_budget_exhausted'))
                    continue
                if not fetch:
                    failures.append(dict(failure, error='fetch_required'))
                    continue
                if len(ledger['original_attempts']) >= max_calls:
                    failures.append(dict(failure, error='original_request_budget_exhausted'))
                    continue
                if not key:
                    key = _api_key(env_file)
                attempt = dict(source=source, rcept_no=receipt, kind=kind,
                    requested_at=_now(now).isoformat(), state='reserved')
                ledger['original_attempts'].append(attempt)
                write_json_atomic(str(ledger_path), ledger)
                body = b''
                stage = 'request'
                try:
                    params = dict(crtfc_key=key, rcept_no=receipt)
                    if kind == 'xbrl':
                        params['reprt_code'] = '11011'
                    body = transport(source, params, max_bytes=remaining)
                    if not isinstance(body, bytes) or len(body) > remaining:
                        raise ValueError('Original source exceeded byte budget')
                    attempt.update(body_bytes=len(body), content_type=getattr(body, 'content_type', None),
                        fetched_at=_now(now).isoformat(), response_sha256=_sha(body))
                    stage = 'archive'
                    metadata = _zip_metadata(body)
                    captured = _now(now).isoformat()
                    meta = dict(symbol=symbol, rcept_no=receipt, report_code='11011', kind=kind,
                        source=source, path=str(path.resolve()), fetched_at=captured, sha256=_sha(body),
                        bytes=len(body), content_type=attempt['content_type'], downloaded=True, content_validated=False,
                        numeric_vintage_verified=False, historical_vintage_verified=False, **metadata)
                    stage = 'storage'
                    _write_bytes(path, body)
                    write_json_atomic(str(meta_path), meta)
                    attempt.update(state='completed', response_sha256=_sha(body), bytes=len(body))
                    captures.append(meta)
                    stored += len(body)
                except Exception as error:
                    attempt.update(state='source_error', error='original_retrieval_or_archive_validation_failed',
                        archive_error_reason=_original_error_reason(error, stage))
                    status = re.search(rb'<status>\s*(\d{3})\s*</status>', body) if isinstance(body, bytes) else None
                    if status:
                        attempt['source_status'] = status.group(1).decode('ascii')
                    if isinstance(body, bytes) and body:
                        attempt['response_sha256'] = _sha(body)
                    failures.append(dict(failure, error=attempt['error'], **_original_failure_diagnostics(attempt)))
                write_json_atomic(str(ledger_path), ledger)
        report = dict(schema_version=1, status='partial' if failures else 'complete',
            error=failures[0]['error'] if failures else None, failures=failures,
            calls_total=len(ledger['original_attempts']), calls_this_run=len(ledger['original_attempts']) - before,
            call_limit=max_calls, byte_limit=max_total_bytes, stored_bytes=stored, captures=captures,
            historical_vintage_verified=False, numeric_vintage_verified=False,
            limitation='Archives are receipt-addressed and integrity-checked; financial contents and amendment chains are not yet validated.')
        write_json_atomic(str(out / 'original_samples_report.json'), report)
        return report


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cohort-report', type=Path, required=True)
    p.add_argument('--corp-codes', type=Path, default=ROOT / 'data/dart_corp_codes.json')
    p.add_argument('--env-file', type=Path, default=ROOT / '.env')
    p.add_argument('--out', type=Path, default=ROOT / 'data/kelly_research/long_history_20261002/financials')
    p.add_argument('--start-year', type=int, default=2015)
    p.add_argument('--through-year', type=int, default=2026)
    p.add_argument('--through-report', choices=[code for code, _ in REPORTS], default='11012')
    p.add_argument('--max-calls', type=int, default=96)
    p.add_argument('--reuse-cache', action='append', type=Path, default=[])
    p.add_argument('--fetch', action='store_true', help='Explicitly allow bounded DART requests')
    p.add_argument('--original-samples', action='store_true', help='At most four receipt-addressed archive requests')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        report = collect_history(cohort_report=args.cohort_report, mapping_path=args.corp_codes,
            env_file=args.env_file, out=args.out, start_year=args.start_year, through_year=args.through_year,
            through_report=args.through_report, fetch=args.fetch, max_calls=args.max_calls,
            reuse_cache_dirs=args.reuse_cache)
        originals = None
        if args.original_samples:
            originals = collect_original_samples(out=args.out, env_file=args.env_file, fetch=args.fetch)
        print(json.dumps(dict(status=report['status'], records=report['records'],
            research_usable_records=report['research_usable_records'], budget=report['budget'],
            originals_status=originals['status'] if originals else 'not_requested',
            historical_vintage_verified=False, report=str((args.out / 'collection_report.json').resolve()))))
        return 0 if report['status'] == 'complete' and (originals is None or originals['status'] == 'complete') else 2
    except (ValueError, TypeError, KeyError, OSError, Timeout):
        # No arbitrary exception representation: it may contain an authenticated URL.
        print('Error: collector input, local artifact or single-worker lock validation failed', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
