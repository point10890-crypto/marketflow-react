"""Streaming descriptive closes and resumable, shortlisted KIS verification.

Naver closes have a present-day adjustment vintage, not point-in-time execution
prices. They cannot support an opening-price backtest. KIS request-0 OHLCV also
retains the provider's corporate-action and finality caveats.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import csv
from datetime import date, datetime, time as wall_time, timedelta
import json
import math
from pathlib import Path
import re
import time

from app.services.surge_trace.common import KST, clock, stamp
from app.services.mirofish.alpha_lab.daily_source import (
    DailySourceError, KISDailyProvider, SOURCE_CONTRACT, _bar, _cutoff, _session, _symbol,
)
from app.services.mirofish.alpha_lab.market_provider import KISMarketProvider, MarketDataError
from app.utils.atomic_json import write_json_atomic

_CAVEATS = dict(historical_vintage_verified=False, corporate_actions_verified=False, finality_verified=False)
_SOURCE = 'naver_closed_daily'
_BASIS = 'provider_adjusted'
_CALENDAR_SOURCES = {'KIS:CTCA0903R', 'KRX:official-holiday-schedule',
                     'KRX:regular-market-rules', 'KIS:KOSPI:FHKUP03500100'}


def _session_date(value):
    if not isinstance(value, str):
        raise ValueError('invalid_session')
    value = value.strip()
    if re.fullmatch(r'[0-9]{8}', value):
        value = f'{value[:4]}-{value[4:6]}-{value[6:]}'
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('invalid_session')
    return parsed


def _naver_capture(value):
    """Only this collector documents naive update_time as Korean wall time."""
    if not isinstance(value, str) or not re.search(r'[T ]\d{2}:\d{2}', value):
        raise ValueError('capture_missing')
    return stamp(value.strip(), legacy_kst=True)


def calendar_window_verified(diagnostics, start, end):
    """Every civil date must be confirmed; missing weekdays are never holidays."""
    try:
        first, last = _session_date(start), _session_date(end)
        known = diagnostics.get('calendar_confirmed_days', {})
        conflicts = set(diagnostics.get('calendar_conflicts', []))
        if last < first or (last - first).days > 20000 or not isinstance(known, dict):
            return False
        return all(type(known.get(day)) is bool and day not in conflicts
                   for day in ((first + timedelta(days=offset)).isoformat()
                               for offset in range((last - first).days + 1)))
    except (ValueError, TypeError, AttributeError):
        return False


def _calendar_row(day, row, now, source=None, captured_at=None):
    if not isinstance(row, dict) or type(row.get('is_open')) is not bool:
        raise ValueError('calendar_invalid')
    session = _session_date(day)
    captured = stamp(row.get('captured_at') or captured_at)
    source = row.get('source') or source
    if (source not in _CALENDAR_SOURCES or captured > now or session >= now.date()
            or captured.date() < session):
        raise ValueError('calendar_invalid')
    if source == 'KIS:KOSPI:FHKUP03500100' and row['is_open'] is not True:
        raise ValueError('calendar_invalid')
    return session.isoformat(), dict(is_open=row['is_open'], source=source, captured_at=captured.isoformat())


def _calendar_merge(evidence, conflicts, day, row):
    previous = evidence.get(day)
    if previous and previous['is_open'] != row['is_open']:
        conflicts.add(day)
    elif not previous:
        evidence[day] = row


def _calendar_file(path, now, *, sealed=False):
    """Read only existing project caches; never touch their producer state."""
    try:
        if path.stat().st_size > 4_000_000:
            raise ValueError()
        body = json.loads(path.read_text(encoding='utf-8-sig'))
        if sealed:
            from app.services.mirofish.alpha_lab.store import _hash
            if not isinstance(body, dict) or body.get('sha256') != _hash(body.get('data')):
                raise ValueError()
            body = body['data']
        if not isinstance(body, dict) or body.get('source') not in _CALENDAR_SOURCES:
            raise ValueError()
        rows = body.get('days')
        if isinstance(rows, list):
            records = [(row.get('date'), row) for row in rows if isinstance(row, dict)]
        elif isinstance(rows, dict):
            records = list(rows.items())
        else:
            raise ValueError()
        evidence, conflicts = {}, set()
        for day, raw in records:
            try:
                day, value = _calendar_row(day, raw, now, body.get('source'), body.get('captured_at'))
                _calendar_merge(evidence, conflicts, day, value)
            except (ValueError, TypeError, OverflowError):
                continue
        conflicts.update(day for day in body.get('conflicts', []) if isinstance(day, str))
        return evidence, conflicts
    except (OSError, ValueError, TypeError, OverflowError):
        return {}, set()


def _calendar_diagnostics(evidence, conflicts, observed=(), *, start=None, end=None):
    conflicts = set(conflicts) | {day for day in observed if day in evidence and not evidence[day]['is_open']}
    known = {day: row['is_open'] for day, row in sorted(evidence.items()) if day not in conflicts}
    sessions = sorted(set(observed) | {day for day, opened in known.items() if opened})
    ranges = []
    for day in known:
        if ranges and (date.fromisoformat(day) - date.fromisoformat(ranges[-1]['end'])).days == 1:
            ranges[-1]['end'] = day
        else:
            ranges.append(dict(start=day, end=day))
    result = dict(calendar_sessions=sessions, calendar_confirmed_days=known,
                  calendar_day_evidence=deepcopy(evidence), calendar_verified_ranges=ranges,
                  calendar_conflicts=sorted(conflicts), calendar_verified=False,
                  calendar_source='saved_official_and_csv' if evidence else 'csv_union_unverified',
                  calendar_sources=sorted({row['source'] for row in evidence.values()}))
    if start is None and sessions:
        start, end = sessions[0], sessions[-1]
    if start is not None and end is not None:
        result['calendar_verified'] = calendar_window_verified(result, start, end)
    return result


def _saved_calendars(project_root, symbols, now):
    project = Path(project_root)
    evidence, conflicts = _calendar_file(project / 'data/kongming_article_candidates/price_calendar.json', now)
    for symbol in sorted(symbols):
        path = project / 'data/admin_mirofish/symbol_alpha' / symbol / 'sources/calendar.json'
        additional, clash = _calendar_file(path, now, sealed=True)
        conflicts.update(clash)
        for day, row in additional.items():
            _calendar_merge(evidence, conflicts, day, row)
    return evidence, conflicts


def acquire_calendar(root, start, end, now, provider=None, max_fetch=3, deadline=None, seed=None):
    """Fill only the requested historical interval in an isolated atomic cache.

    Completed days retain their exact source/capture. Unknown days resume from
    the earliest gap, with at most three KIS calendar requests per invocation.
    ``seed`` can be a load_closes diagnostic containing saved official evidence.
    """
    now, root = clock(now), Path(root)
    first, last = _session_date(start), min(_session_date(end), now.date() - timedelta(days=1))
    if last < first or (last - first).days > 20000 or type(max_fetch) is not int or not 0 <= max_fetch <= 3:
        raise ValueError('calendar_scope_invalid')
    wanted = [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]
    evidence, conflicts = _calendar_file(root / 'calendar.json', now)
    # Conflicts are durable exclusions, independent of which source's row won
    # the merge. Copying evidence alone could certify a date already disputed
    # by the CSV or another saved official calendar.
    for value in (seed or {}).get('calendar_conflicts', []):
        try:
            day = _session_date(value)
            if day < now.date():
                conflicts.add(day.isoformat())
        except (ValueError, TypeError):
            continue
    for day, raw in (seed or {}).get('calendar_day_evidence', {}).items():
        try:
            key, row = _calendar_row(day, raw, now)
            _calendar_merge(evidence, conflicts, key, row)
        except (ValueError, TypeError, OverflowError):
            continue
    errors, requests = [], 0
    live = provider is None
    deadline = time.monotonic() + 45 if deadline is None else deadline

    def save():
        write_json_atomic(root / 'calendar.json', dict(source='KIS:CTCA0903R', schema_version=1,
                                                       days=evidence, conflicts=sorted(conflicts)))

    try:
        if evidence or conflicts:
            save()
        while requests < max_fetch and time.monotonic() < deadline:
            pending = [day for day in wanted if day not in evidence]
            if not pending:
                break
            base = pending[0]
            if provider is None:
                provider = KISMarketProvider()
            requests += 1
            response = provider.fetch_calendar(base)
            upper = clock() if live else now
            if (not isinstance(response, dict) or response.get('source') != 'KIS:CTCA0903R'
                    or not isinstance(response.get('days'), list) or not 1 <= len(response['days']) <= 370):
                raise ValueError('calendar_invalid')
            captured = stamp(response.get('captured_at'))
            if captured > upper:
                raise ValueError('calendar_future_capture')
            incoming = {}
            for raw in response['days']:
                if not isinstance(raw, dict):
                    raise ValueError('calendar_invalid')
                day = _session_date(raw.get('date')).isoformat()
                if day < base or day in incoming or type(raw.get('is_open')) is not bool:
                    raise ValueError('calendar_invalid')
                # Calendar APIs also return future schedule rows. They cannot
                # become confirmed historical days until that date has passed.
                if day > last.isoformat() or day >= now.date().isoformat():
                    continue
                day, value = _calendar_row(day, raw, upper, response['source'], captured.isoformat())
                incoming[day] = value
            added = set(incoming) - set(evidence)
            for day, row in incoming.items():
                _calendar_merge(evidence, conflicts, day, row)
            save()
            if not added:
                errors.append('calendar_no_progress')
                break
    except MarketDataError as exc:
        errors.append(exc.code)
    except OSError:
        errors.append('calendar_cache_write_failed')
    except Exception:
        errors.append('calendar_source_failed')
    result = _calendar_diagnostics(evidence, conflicts, start=first.isoformat(), end=last.isoformat())
    missing = [day for day in wanted if day not in result['calendar_confirmed_days']]
    result.update(status='ready' if not missing and not errors else 'partial' if evidence else 'unavailable',
                  requests=requests, errors=errors, missing_days=missing, pending_calendar_days=len(missing))
    return result


def load_closes(project_root, symbols, now):
    """Read every CSV row but retain only requested issuers, preserving captures."""
    now = clock(now)
    requested = {symbol for symbol in symbols if isinstance(symbol, str) and re.fullmatch(r'[0-9A-Z]{6}', symbol)}
    diag = dict(status='ready', source=_SOURCE, price_basis=_BASIS, requested_symbols=len(requested),
                scanned_rows=0, selected_rows=0, accepted_rows=0, invalid=Counter(), duplicate_rows=0,
                **_CAVEATS, limitations=['descriptive_close_to_close_only', 'current_adjustment_vintage',
                                        'same_day_sessions_excluded', 'historical_close_finality_unverified'])
    prices, conflicted = {}, set()
    calendar_dates, dates, captures = set(), {}, {}
    path = Path(project_root) / 'data/chart_analogue/closed_prices.csv'
    if not requested:
        diag.update(status='empty', invalid={}, **_calendar_diagnostics({}, set()))
        return {}, diag
    try:
        with path.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            required = {'ticker', 'date', 'current_price', 'update_time', 'price_basis', 'source_id', 'collection_status'}
            if not required <= set(reader.fieldnames or ()):
                raise ValueError('price_columns')
            for raw in reader:
                diag['scanned_rows'] += 1
                symbol = raw.get('ticker', '').strip()
                selected = symbol in requested
                diag['selected_rows'] += int(selected)
                if not re.fullmatch(r'[0-9A-Z]{6}', symbol) or symbol == '000000':
                    continue
                if (raw.get('source_id') != _SOURCE or raw.get('price_basis') != _BASIS
                        or raw.get('collection_status') not in {'fresh', 'cache_preserved'}):
                    if selected: diag['invalid']['provenance'] += 1
                    continue
                try:
                    day_text, capture_text = raw.get('date'), raw.get('update_time')
                    if day_text not in dates:
                        dates[day_text] = _session_date(day_text)
                    day = dates[day_text]
                    if capture_text not in captures:
                        captures[capture_text] = _naver_capture(capture_text)
                    captured = captures[capture_text]
                    close = float(raw.get('current_price'))
                    if not math.isfinite(close) or not 0 < close <= 1e12:
                        raise ValueError()
                except (ValueError, TypeError, OverflowError):
                    if selected: diag['invalid']['price_or_timestamp'] += 1
                    continue
                if day >= now.date():
                    if selected: diag['invalid']['same_day_or_future_session'] += 1
                    continue
                if captured > now:
                    if selected: diag['invalid']['future_capture'] += 1
                    continue
                if captured < datetime.combine(day, wall_time(15, 30), KST):
                    if selected: diag['invalid']['capture_before_close'] += 1
                    continue
                calendar_dates.add(day.isoformat())
                if not selected:
                    continue
                key = (symbol, day.isoformat())
                if key in conflicted:
                    diag['invalid']['duplicate_conflict'] += 1
                    continue
                previous = prices.get(key)
                row = dict(date=day.isoformat(), close=close, fetched_at=captured.isoformat(),
                           source=_SOURCE, price_basis=_BASIS)
                if previous:
                    if previous['close'] != close:
                        conflicted.add(key)
                        prices.pop(key)
                        diag['invalid']['duplicate_conflict'] += 1
                        continue
                    diag['duplicate_rows'] += 1
                    # The first real acquisition of an unchanged value is the
                    # only receipt that may be attributed to that observation.
                    if previous['fetched_at'] <= row['fetched_at']:
                        continue
                prices[key] = row
    except (OSError, UnicodeError, ValueError, csv.Error):
        diag.update(status='partial' if prices else 'unavailable', error='price_archive_unavailable')
    result = {}
    for (symbol, _), row in sorted(prices.items()):
        result.setdefault(symbol, []).append(row)
    diag.update(accepted_rows=len(prices), available_symbols=len(result), invalid=dict(diag['invalid']),
                missing_symbols=sorted(requested - set(result)))
    if diag['status'] == 'ready' and (not result or diag['missing_symbols']):
        diag['status'] = 'partial' if result else 'unavailable'
    evidence, clashes = _saved_calendars(project_root, requested, now)
    diag.update(_calendar_diagnostics(evidence, clashes, calendar_dates))
    return result, diag


def _validated(value, symbol, end_session, now):
    """Keep only provider-validated public fields, never raw response pages."""
    if not isinstance(value, dict) or value.get('symbol') != symbol:
        raise DailySourceError('daily_identity')
    if value.get('source') != SOURCE_CONTRACT:
        raise DailySourceError('daily_payload')
    try:
        captured = stamp(value['captured_at'])
        capture = value.get('capture') or {'first': value['captured_at'], 'last': value['captured_at']}
        first, last = stamp(capture['first']), stamp(capture['last'])
        if not _cutoff(end_session) <= first <= last == captured <= now:
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise DailySourceError('invalid_clock') from None
    bars = value.get('bars')
    if not isinstance(bars, list) or not 1 <= len(bars) <= 756:
        raise DailySourceError('daily_payload')
    normalized = []
    source_fields = {'open': 'stck_oprc', 'high': 'stck_hgpr', 'low': 'stck_lwpr',
                     'close': 'stck_clpr', 'volume': 'acml_vol', 'traded_value': 'acml_tr_pbmn'}
    for raw in bars:
        if not isinstance(raw, dict) or raw.get('symbol') != symbol:
            raise DailySourceError('daily_identity')
        day = _session(raw.get('date'))
        if day > end_session:
            raise DailySourceError('daily_future_row')
        flags = raw.get('source_flags')
        if not isinstance(flags, dict) or not set(flags) <= {'flng_cls_code', 'prtt_rate', 'mod_yn', 'revl_issu_reas'}:
            raise DailySourceError('daily_payload')
        public = {'stck_bsop_date': day.replace('-', ''), 'symbol': symbol, **flags}
        public.update({target: raw.get(field) for field, target in source_fields.items()})
        bar, _ = _bar(public, symbol)
        if raw.get('tradable') != bar['tradable'] or raw.get('quality_flags') != bar['quality_flags']:
            raise DailySourceError('daily_payload')
        normalized.append(bar)
    days = [row['date'] for row in normalized]
    if days != sorted(set(days)) or days[-1] != end_session:
        raise DailySourceError('daily_latest_missing')
    return dict(symbol=symbol, end_session=end_session, bars=normalized[-100:], source=deepcopy(SOURCE_CONTRACT),
                captured_at=captured.isoformat(), capture={'first': first.isoformat(), 'last': last.isoformat()},
                history_status='complete' if len(normalized) >= 100 else 'insufficient_history', **_CAVEATS)


def _candidate_cache(project_root, end_session, now, symbols, diag):
    """Reuse a bounded sealed candidate-desk snapshot; no acquisition side effects."""
    from app.services.mirofish.alpha_lab import candidate_inputs
    directory = Path(project_root) / 'data/alpha_lab/candidate-desk/inputs'
    if not (directory / 'current.json').is_file():
        diag['candidate_cache'] = 'missing'
        return {}
    try:
        # Inspect the small sealed pointer/manifest before load_inputs validates
        # potentially large immutable objects for every member of the cohort.
        pointer = candidate_inputs._read(directory / 'current.json')
        identity = pointer.get('snapshot_id')
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity):
            raise ValueError()
        manifest = candidate_inputs._read(directory / 'snapshots' / identity / 'manifest.json')
        spec = manifest.get('spec') or {}
        scope = spec.get('symbols')
        if not isinstance(scope, list) or len(scope) > 50:
            diag['candidate_cache'] = 'scope_exceeds_50'
            return {}
        if spec.get('latest_session') != end_session:
            diag['candidate_cache'] = 'different_session'
            return {}
        loaded = candidate_inputs.load_inputs(directory)
        if loaded.get('latest_session') != end_session:
            raise ValueError()
        result = {}
        for symbol in symbols:
            bars = loaded.get('prices_by_symbol', {}).get(symbol)
            capture = loaded.get('capture_audit', {}).get(symbol)
            if bars is None or not isinstance(capture, dict):
                continue
            result[symbol] = _validated(dict(symbol=symbol, bars=bars, capture=capture,
                captured_at=capture.get('last'), source=loaded['provenance']['source_contract']), symbol, end_session, now)
        diag['candidate_cache'] = 'ready'
        return result
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        diag['candidate_cache'] = 'invalid'
        return {}


def load_current_prices(project_root, symbols, end_session, now, root, provider=None, deadline=None, max_fetch=12):
    """Acquire <= max_fetch shortlisted issuers, retrying only unfinished ones.

    ``deadline`` is an absolute monotonic clock. The default KIS provider has its
    own request timeout; a deadline also prevents the next issuer request.
    """
    now, root = clock(now), Path(root)
    live = provider is None
    ordered = list(dict.fromkeys(symbols))
    diag = dict(status='ready', requested=len(ordered), fetched=0, reused=0, pending_symbols=[],
                errors={}, candidate_cache='not_needed', **_CAVEATS)
    try:
        end_session = _session(end_session)
        if len(ordered) > 50 or isinstance(max_fetch, bool) or not isinstance(max_fetch, int) or not 0 <= max_fetch <= 50:
            raise DailySourceError('daily_count')
        for symbol in ordered:
            _symbol(symbol)
        if now < _cutoff(end_session):
            raise DailySourceError('daily_session_incomplete')
    except DailySourceError as exc:
        diag.update(status='unavailable', pending_symbols=ordered, errors={'session': exc.code})
        return {}, diag
    deadline = time.monotonic() + 120 if deadline is None else deadline
    result = {}
    for symbol in ordered:
        path = root / 'prices' / f'{symbol}.json'
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 2_000_000:
                raise ValueError()
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved.get('end_session') != end_session:
                continue
            result[symbol] = _validated(saved, symbol, end_session, now)
            diag['reused'] += 1
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            diag['errors'][symbol] = 'saved_price_invalid'
    remaining = [symbol for symbol in ordered if symbol not in result]
    if remaining:
        for symbol, value in _candidate_cache(project_root, end_session, now, remaining, diag).items():
            try:
                write_json_atomic(root / 'prices' / f'{symbol}.json', value)
                result[symbol] = value
                diag['reused'] += 1
                diag['errors'].pop(symbol, None)
            except OSError:
                diag['errors'][symbol] = 'price_cache_write_failed'
    for symbol in ordered:
        if symbol in result:
            continue
        if diag['fetched'] >= max_fetch or time.monotonic() >= deadline:
            continue
        if provider is None:
            provider = KISDailyProvider()
        diag['fetched'] += 1
        try:
            acquired = provider.fetch_history(symbol, end_session, count=100)
            # Actual responses arrive after the job's starting clock. Injected
            # providers stay pinned to now for deterministic future-data tests.
            upper = clock() if live else now
            value = _validated(acquired, symbol, end_session, upper)
            write_json_atomic(root / 'prices' / f'{symbol}.json', value)
            result[symbol] = value
            diag['errors'].pop(symbol, None)
        except DailySourceError as exc:
            diag['errors'][symbol] = exc.code
        except OSError:
            diag['errors'][symbol] = 'price_cache_write_failed'
        except Exception:
            # Provider exceptions can include token-bearing URLs or bodies.
            diag['errors'][symbol] = 'price_source_failed'
    diag['pending_symbols'] = [symbol for symbol in ordered if symbol not in result]
    if diag['pending_symbols']:
        diag['status'] = 'partial' if result else 'unavailable'
    return result, diag
