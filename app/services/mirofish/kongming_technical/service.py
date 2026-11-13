"""Independent, bounded technical agent; HTTP reads never acquire market data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time

from filelock import FileLock, Timeout

from app.services import kongming_article_candidates as articles
from app.utils.atomic_json import write_json_atomic
from app.utils.paths import DATA_DIR
from .profile import CALENDAR_SOURCE, ProfileError, build_profile, _sessions as validated_sessions
from .provider import TechnicalProvider, completed_through

ROOT = Path(DATA_DIR)/'kongming_technical'
AGENT = 'volume_profile_20d_v1'
MAX_ENTRIES = 500
MAX_QUEUED = 32
COOLDOWN = timedelta(minutes=15)


def _clock(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('invalid_clock')
    return value.astimezone(timezone.utc)


def _stamp(value):
    return _clock(value).isoformat().replace('+00:00', 'Z')


def validate_symbol(symbol):
    if not isinstance(symbol, str) or not re.fullmatch(r'[0-9A-Z]{6}', symbol) or symbol == '000000':
        raise ValueError('invalid_symbol')
    return symbol


def _read(path, default=None):
    if not path.exists():
        return deepcopy(default)
    if path.stat().st_size > 8_000_000:
        raise ValueError('technical_store_invalid')
    value = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(value, dict):
        raise ValueError('technical_store_invalid')
    return value


def _state(root):
    state = _read(root/'state.json', dict(schema_version=1, entries={}, last_run_at=None))
    if state.get('schema_version') != 1 or not isinstance(state.get('entries'), dict) or len(state['entries']) > MAX_ENTRIES:
        raise ValueError('technical_store_invalid')
    for symbol, entry in state['entries'].items():
        validate_symbol(symbol)
        if not isinstance(entry, dict):
            raise ValueError('technical_store_invalid')
    return state


def _new(symbol, now, name=''):
    return dict(symbol=symbol, name=name[:80], queued_at=_stamp(now), priority=False,
                active_until=_stamp(now+timedelta(days=3)), failure_count=0, failure_through=None,
                through=None, retry_at=None, in_flight_until=None, error=None)


def _prune_inactive(state, current):
    # Remove only expired scheduling references, never stored profiles/receipts.
    for symbol, entry in list(state['entries'].items()):
        active = _clock(entry.get('active_until') or entry['queued_at'])
        in_flight = entry.get('in_flight_until')
        if active < current and not (in_flight and _clock(in_flight) > current):
            del state['entries'][symbol]


def _completed(entry, through, root):
    return (entry.get('through') == through and entry.get('result_status') in {'ready', 'insufficient_history', 'price_event_review'}
            and not entry.get('error') and (root/'profiles'/f"{entry['symbol']}.json").is_file())


def enqueue(symbol, root=ROOT, *, now=None):
    symbol, root, current = validate_symbol(symbol), Path(root), _clock(now)
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root/'state.lock'), timeout=.3):
        state = _state(root)
        if len(state['entries']) >= MAX_ENTRIES:
            _prune_inactive(state, current)
        old = state['entries'].get(symbol)
        if old and _completed(old, completed_through(current), root):
            return dict(schema_version=1, status='cached', symbol=symbol)
        queued = sum(bool(row.get('priority')) for row in state['entries'].values())
        if not (old or {}).get('priority') and queued >= MAX_QUEUED:
            raise ValueError('technical_queue_full')
        if old is None:
            if len(state['entries']) >= MAX_ENTRIES:
                raise ValueError('technical_queue_full')
            old = _new(symbol, current)
            state['entries'][symbol] = old
        # Repeated requests cannot reset failure cooldowns or billing/source work.
        old['priority'] = True
        old['active_until'] = _stamp(current+timedelta(days=7))
        write_json_atomic(root/'state.json', state)
    return dict(schema_version=1, status='queued', symbol=symbol)


def _discover(root, article_root, current):
    try:
        rows = articles.read_view(article_root, now=current)['items']
        symbols = {}
        for row in rows:
            if row.get('freshness') != 'recent':
                continue
            for entity in row.get('entities', []):
                try:
                    symbol = validate_symbol(entity.get('symbol'))
                except ValueError:
                    continue
                name = entity.get('name')
                if isinstance(name, str):
                    symbols.setdefault(symbol, name[:80])
        error = None
    except (OSError, ValueError, KeyError, TypeError):
        symbols, error = {}, 'article_input_unavailable'
    with FileLock(str(root/'state.lock'), timeout=.3):
        state = _state(root)
        if len(state['entries']) >= MAX_ENTRIES:
            _prune_inactive(state, current)
        for symbol, name in list(symbols.items())[:200]:
            if symbol not in state['entries'] and len(state['entries']) < MAX_ENTRIES:
                state['entries'][symbol] = _new(symbol, current, name)
            elif symbol in state['entries'] and not state['entries'][symbol].get('name'):
                state['entries'][symbol]['name'] = name
            if symbol in state['entries']:
                entry = state['entries'][symbol]
                entry['active_until'] = max(entry.get('active_until', ''), _stamp(current+timedelta(days=3)))
        state.update(last_run_at=_stamp(current), input_error=error)
        write_json_atomic(root/'state.json', state)


def _valid_calendar(value, through, current):
    try:
        days = value['sessions']
        captured = _clock(value['captured_at'])
        return (value.get('through') == through and value.get('source') == CALENDAR_SOURCE
                and days == validated_sessions(days) and days[-1] <= through
                and completed_through(captured) >= through and captured <= current+timedelta(minutes=1))
    except (ValueError, TypeError, KeyError):
        return False


def _sessions(root, provider, current):
    through = completed_through(current)
    cached = _read(root/'calendar.json', {})
    if cached.get('through') == through:
        if cached.get('retry_at') and current < _clock(cached['retry_at']):
            raise ValueError('session_source_unavailable')
        if _valid_calendar(cached, through, current):
            return cached
    try:
        value = provider.fetch_sessions(current)
        if not _valid_calendar(value, through, current):
            raise ValueError('session_source_invalid')
        write_json_atomic(root/'calendar.json', value)
        return value
    except Exception:
        write_json_atomic(root/'calendar.json', dict(through=through, retry_at=_stamp(current+COOLDOWN)))
        raise ValueError('session_source_unavailable') from None


def _due(entry, current, through, root):
    if current > _clock(entry.get('active_until') or entry['queued_at']):
        return False
    if _completed(entry, through, root):
        return False
    return all(not entry.get(field) or current >= _clock(entry[field]) for field in ('retry_at', 'in_flight_until'))


def _finish(root, symbol, current, through, *, profile=None, error=None):
    with FileLock(str(root/'state.lock'), timeout=.3):
        state = _state(root)
        entry = state['entries'][symbol]
        failures = entry.get('failure_count', 0) if entry.get('failure_through') == through else 0
        entry.update(priority=False, failure_count=failures+1 if error else 0,
                     failure_through=through if error else None)
        cooldown = timedelta(hours=1) if failures+1 >= 3 else COOLDOWN
        entry.update(in_flight_until=None, last_attempt_at=_stamp(current), error=error,
                     retry_at=_stamp(current+cooldown) if error else None)
        if profile is not None:
            entry.update(through=through, result_status=profile['status'], priority=False,
                         name=profile.get('name') or entry.get('name', ''))
        write_json_atomic(root/'state.json', state)


def run_once(root=ROOT, *, article_root=articles.ROOT, now=None, provider=None, deadline=None, max_symbols=3):
    root, current = Path(root), _clock(now)
    if type(max_symbols) is not int or not 1 <= max_symbols <= 10:
        raise ValueError('invalid_batch_size')
    root.mkdir(parents=True, exist_ok=True)
    stop = deadline if deadline is not None else time.monotonic()+40
    with FileLock(str(root/'worker.lock'), timeout=0):
        _discover(root, article_root, current)
        through = completed_through(current)
        entries = _state(root)['entries']
        due = sorted(((symbol, row) for symbol, row in entries.items() if _due(row, current, through, root)),
                     key=lambda item: (not item[1].get('priority'), item[1].get('last_attempt_at') or '', item[1]['queued_at'], item[0]))[:max_symbols]
        summary = dict(processed=0, failed=0, status='ready')
        if not due or time.monotonic()+11 >= stop:
            return summary
        provider = provider or TechnicalProvider()
        try:
            calendar = _sessions(root, provider, current)
        except ValueError:
            for symbol, _ in due:
                _finish(root, symbol, current, through, error='session_source_unavailable')
            return dict(processed=0, failed=len(due), status='partial')
        for symbol, entry in due:
            if time.monotonic()+11 >= stop:
                break
            with FileLock(str(root/'state.lock'), timeout=.3):
                state = _state(root)
                state['entries'][symbol]['in_flight_until'] = _stamp(current+timedelta(minutes=3))
                write_json_atomic(root/'state.json', state)
            try:
                previous = _read(root/'profiles'/f'{symbol}.json', {})
                if previous.get('status') == 'ready' and previous.get('window_end') == calendar['sessions'][-1]:
                    _finish(root, symbol, current, through, profile=previous)
                    continue
                source = provider.fetch_history(symbol, calendar['sessions'], current)
                profile = build_profile(symbol, source.get('name') or entry.get('name') or symbol,
                    source['bars'], calendar['sessions'], fetched_at=source['fetched_at'],
                    source=source['source'], calendar_source=calendar['source'])
                fingerprint = profile.get('fingerprint')
                if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
                    raise ValueError('technical_profile_invalid')
                receipt = root/'history'/symbol/f'{fingerprint}.json'
                if not receipt.exists():
                    write_json_atomic(receipt, dict(profile=profile, input=source, calendar=calendar))
                write_json_atomic(root/'profiles'/f'{symbol}.json', profile)
                _finish(root, symbol, current, through, profile=profile)
                summary['processed'] += 1
            except Exception as exc:
                reason = exc.code if isinstance(exc, ProfileError) else 'price_source_unavailable'
                _finish(root, symbol, current, through, error=reason)
                summary['failed'] += 1
        if summary['failed']:
            summary['status'] = 'partial'
        with FileLock(str(root/'state.lock'), timeout=.3):
            state = _state(root)
            state['last_run_summary'] = summary
            write_json_atomic(root/'state.json', state)
        return summary


def _pending(symbol, entry):
    return dict(symbol=symbol, name=entry.get('name') or symbol, status='pending', reason=None,
        as_of=None, fetched_at=None, window_start=None, window_end=None, sessions_required=20,
        sessions_used=0, reference_price=None, total_volume=None, total_traded_value=None,
        poc=None, support=None, resistance=None, current_zone=None, bins=[],
        method='daily_uniform_range_overlap_v1', source='KIS:FHKST03010100:J:D:1',
        calendar_source='KIS:KOSPI:FHKUP03500100', price_basis='KIS_KRX_raw_J_D_1',
        limitations=[], fingerprint=None)


def read_view(root=ROOT, *, symbol=None, now=None):
    root, current = Path(root), _clock(now)
    if symbol is not None:
        validate_symbol(symbol)
    state, items = _state(root), []
    through = completed_through(current)
    for code, entry in state['entries'].items():
        if symbol is not None and code != symbol:
            continue
        row = _read(root/'profiles'/f'{code}.json', _pending(code, entry))
        if row.get('symbol') != code:
            raise ValueError('technical_store_invalid')
        if entry.get('error'):
            row.update(status='stale' if row.get('poc') else 'source_unavailable', reason=entry['error'])
        elif row['status'] == 'ready' and entry.get('through') != through:
            row.update(status='stale', reason='next_session_refresh_pending')
        row['retry_at'] = entry.get('retry_at')
        items.append(row)
    items.sort(key=lambda row: (row['status'] != 'ready', row['name'], row['symbol']))
    status = 'waiting' if not items else 'ready' if all(row['status'] == 'ready' for row in items) else 'partial'
    return dict(schema_version=1, agent=AGENT, status=status, last_run_at=state.get('last_run_at'), items=items)
