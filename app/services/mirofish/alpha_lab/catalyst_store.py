# 캐시 뉴스 원장을 읽고 결정별 불변 보조 맥락과 전향 코호트를 저장한다.
"""Explicit cached-source writer and JSON-only read projection for AlphaLab."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import re
import sqlite3

from filelock import FileLock

from . import opportunity_store, store
from .catalyst_context import (HORIZON_HOURS, HYPOTHESIS, IDENTITY_KEYS, MAX_CONTEXT_BYTES,
    POLICY, _binding, _clock, _first_detection, _hex, _stamp, _time, build_catalyst_context, public_catalyst_context)

DIRECTORY = 'catalyst-context'
DEFAULT_DB_PATH = Path(__file__).resolve().parents[4]/'data'/'omni'/'omni.db'
MAX_SOURCE_ROWS = 256
MAX_COHORTS = opportunity_store.MAX_ISSUED
MAX_COHORT_BYTES = 262144
MAX_PROTOCOL_BYTES = 4096
PROTOCOL_KEYS = {'schema_version', 'policy_version', 'hypothesis', 'horizon_hours', 'started_at', 'control_policy'}
COHORT_KEYS = {'schema_version', 'policy_version', 'protocol_id', *IDENTITY_KEYS, 'decision_at',
    'enrolled_at', 'horizon_hours', 'horizon_until', 'selected_symbols', 'control_symbols', 'universe'}


def _directory(root):
    return Path(root)/DIRECTORY


def _read(path, limit):
    if not path.is_file():
        return None
    if path.stat().st_size > limit:
        raise ValueError('catalyst_store_capacity')
    raw = store._read(path)
    if (not isinstance(raw, dict) or set(raw) != {'schema_version', 'data', 'sha256'}
            or type(raw.get('schema_version')) is not int or raw['schema_version'] != 1
            or not isinstance(raw.get('data'), dict) or not _hex(raw.get('sha256'))
            or raw['sha256'] != store._hash(raw['data'])):
        raise ValueError('catalyst_store_integrity')
    return raw['data']


def _write(path, data):
    store._write(path, dict(schema_version=1, data=data, sha256=store._hash(data)))


def _immutable(path, data, limit):
    if path.exists():
        if _read(path, limit) != data:
            raise ValueError('catalyst_store_integrity')
    else:
        _write(path, data)


def _protocol(root, current, *, create=False):
    path = _directory(root)/'protocol.json'
    value = _read(path, MAX_PROTOCOL_BYTES)
    if value is None:
        if not create:
            return None
        value = dict(schema_version=1, policy_version=POLICY, hypothesis=HYPOTHESIS,
            horizon_hours=HORIZON_HOURS, started_at=_stamp(current), control_policy='all_supplied_same_quality_unselected')
        _immutable(path, value, MAX_PROTOCOL_BYTES)
    if (set(value) != PROTOCOL_KEYS or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or value.get('policy_version') != POLICY or value.get('hypothesis') != HYPOTHESIS
            or type(value.get('horizon_hours')) is not int or value['horizon_hours'] != HORIZON_HOURS
            or _time(value.get('started_at')) is None or _time(value['started_at']) > current
            or value.get('control_policy') != 'all_supplied_same_quality_unselected'):
        raise ValueError('catalyst_protocol_unavailable')
    return value


def _issued(root, board):
    try:
        journal = opportunity_store.read_journal(root)
        row = next((item['board'] for item in journal['issued'] if item['decision_id'] == board['decision_id']), None)
        if (row is None or opportunity_store._stable(row) != opportunity_store._stable(board)
                or _time(row['generated_at']) != _time(board['generated_at'])):
            raise ValueError('catalyst_journal_unavailable')
        return journal
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('catalyst_journal_unavailable') from None


def _registry(root, protocol):
    value = _read(_directory(root)/'enrollment.json', MAX_COHORT_BYTES)
    if value is None:
        return dict(schema_version=1, policy_version=POLICY, protocol_id=store._hash(protocol), cohort_ids=[])
    ids = value.get('cohort_ids')
    if (set(value) != {'schema_version', 'policy_version', 'protocol_id', 'cohort_ids'}
            or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or value.get('policy_version') != POLICY or value.get('protocol_id') != store._hash(protocol)
            or not isinstance(ids, list) or len(ids) > MAX_COHORTS or any(not _hex(item) for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('catalyst_cohort_integrity')
    for decision_id in ids:
        cohort = _read(_directory(root)/'cohorts'/f'{decision_id}.json', MAX_COHORT_BYTES)
        _validate_cohort(cohort, protocol)
        if cohort['decision_id'] != decision_id:
            raise ValueError('catalyst_cohort_integrity')
    return value


def _validation(root, protocol):
    return dict(status='collecting', hypothesis=HYPOTHESIS, horizon_hours=HORIZON_HOURS,
        started_at=protocol['started_at'], enrolled_decisions=len(_registry(root, protocol)['cohort_ids']),
        matured_decisions=0, coincidence_rejected=False)


def _cached_events(db_path, board, journal):
    path = Path(db_path or DEFAULT_DB_PATH).resolve()
    if not path.is_file():
        raise ValueError('catalyst_news_unavailable')
    try:
        connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        events, seen = [], set()
        try:
            for candidate in board['candidates']:
                symbol = candidate['symbol']
                first = _first_detection(journal, symbol, _time(board['generated_at']))
                select = ('SELECT content_hash, title, summary, link, source, grade, published_ts, symbols, '
                    'collected_at FROM news_events WHERE symbols LIKE ? ')
                order = 'ORDER BY julianday(collected_at) DESC, id DESC LIMIT ?'
                # Separate bounded slices keep pre-detection evidence available
                # as the same symbol accumulates hundreds of subsequent reports.
                rows = connection.execute(select+order, (f'%"{symbol}"%', MAX_SOURCE_ROWS)).fetchall()
                rows += connection.execute(select+'AND julianday(collected_at) <= julianday(?) '+order,
                    (f'%"{symbol}"%', _stamp(first['generated_at']), MAX_SOURCE_ROWS)).fetchall()
                for row in rows:
                    event = dict(row)
                    if event['content_hash'] in seen:
                        continue
                    seen.add(event['content_hash'])
                    try:
                        symbols = json.loads(event['symbols'] or '[]')
                    except (ValueError, TypeError):
                        symbols = []
                    event['symbols'] = symbols if isinstance(symbols, list) else []
                    events.append(event)
        finally:
            connection.close()
        return events
    except (sqlite3.Error, OSError, ValueError, TypeError):
        raise ValueError('catalyst_news_unavailable') from None


def read_context(root, board, *, now=None):
    """Read bounded saved JSON only; unavailable/corrupt/binding mismatch is omitted."""
    try:
        binding = _binding(board)
        directory = _directory(root)
        pointer = _read(directory/'current'/f'{binding["decision_id"]}.json', MAX_PROTOCOL_BYTES)
        if (pointer is None or set(pointer) != {*IDENTITY_KEYS, 'snapshot_id'}
                or any(pointer.get(key) != value for key,value in binding.items())
                or not _hex(pointer.get('snapshot_id'))):
            return None
        snapshot_id = pointer['snapshot_id']
        body = _read(directory/'runs'/f'{snapshot_id}.json', MAX_CONTEXT_BYTES+1024)
        if body is None or store._hash(body) != snapshot_id:
            return None
        return public_catalyst_context(dict(body, snapshot_id=snapshot_id), board, now=now)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None


def refresh_context(root, *, now=None, db_path=None):
    """Explicit refresh from existing cache. Failed work never replaces the pointer."""
    try:
        current = _clock(now)
        directory = _directory(root)
        directory.mkdir(parents=True, exist_ok=True)
        with FileLock(str(directory/'write.lock'), timeout=5):
            protocol = _protocol(root, current, create=True)
            status = store.read_status(root, now=_stamp(current))
            board = (status.get('report') or {}).get('opportunity_board')
            try:
                _binding(board)
            except (ValueError, TypeError):
                raise ValueError('catalyst_decision_unavailable') from None
            journal = _issued(root, board)
            events = _cached_events(db_path, board, journal)
            context = build_catalyst_context(board, journal, events,
                validation=_validation(root, protocol), now=current)
            snapshot_id = context['snapshot_id']
            body = {key:value for key,value in context.items() if key != 'snapshot_id'}
            _immutable(directory/'runs'/f'{snapshot_id}.json', body, MAX_CONTEXT_BYTES+1024)
            _write(directory/'current'/f'{board["decision_id"]}.json', dict(
                **{key:board[key] for key in IDENTITY_KEYS}, snapshot_id=snapshot_id))
            return dict(status='ready', snapshot_id=snapshot_id)
    except Exception as exc:
        allowed = {'catalyst_clock_invalid', 'catalyst_news_unavailable', 'catalyst_journal_unavailable',
            'catalyst_decision_unavailable', 'catalyst_protocol_unavailable', 'catalyst_cohort_integrity',
            'catalyst_store_integrity', 'catalyst_store_capacity', 'catalyst_news_capacity'}
        error = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else 'catalyst_refresh_unavailable'
        return dict(status='failed', error=error)


def _universe(symbols):
    if isinstance(symbols, dict):
        pairs = list(symbols.items())
    elif isinstance(symbols, (list, tuple, set)):
        pairs = [(symbol, symbol) for symbol in symbols]
    else:
        raise ValueError('catalyst_control_universe_invalid')
    if not pairs or len(pairs) > 1000:
        raise ValueError('catalyst_control_universe_invalid')
    names = {}
    for symbol, name in pairs:
        if (not isinstance(symbol, str) or re.fullmatch('[0-9]{6}', symbol) is None
                or not isinstance(name, str) or not 1 <= len(name) <= 120 or any(ord(c) < 32 for c in name)
                or symbol in names):
            raise ValueError('catalyst_control_universe_invalid')
        names[symbol] = name
    return {key:names[key] for key in sorted(names)}


def _validate_cohort(value, protocol):
    try:
        if (not isinstance(value, dict) or set(value) != COHORT_KEYS
                or type(value.get('schema_version')) is not int or value['schema_version'] != 1
                or value.get('policy_version') != POLICY or value.get('protocol_id') != store._hash(protocol)
                or any(not _hex(value.get(key)) for key in IDENTITY_KEYS)
                or type(value.get('horizon_hours')) is not int or value['horizon_hours'] != HORIZON_HOURS):
            raise ValueError('catalyst_cohort_integrity')
        decision, enrolled, deadline = (_time(value.get(key)) for key in ('decision_at', 'enrolled_at', 'horizon_until'))
        names = _universe(value['universe']); selected, controls = value['selected_symbols'], value['control_symbols']
        if (decision is None or enrolled is None or deadline is None or not _time(protocol['started_at']) <= decision <= enrolled
                or deadline != decision+timedelta(hours=HORIZON_HOURS)
                or enrolled >= deadline
                or not isinstance(selected, list) or not 1 <= len(selected) <= 3 or len(set(selected)) != len(selected)
                or not set(selected) <= set(names) or not isinstance(controls, list) or not controls
                or controls != sorted(set(names)-set(selected))):
            raise ValueError('catalyst_cohort_integrity')
    except (ValueError, TypeError, KeyError):
        raise ValueError('catalyst_cohort_integrity') from None


def register_cohort(root, board, symbols, *, now=None):
    """Freeze prospective selected and all supplied quality controls; never evaluate."""
    try:
        current = _clock(now); binding = _binding(board)
        # Merely probing enrollment before the first explicit refresh creates nothing.
        protocol = _protocol(root, current)
        if protocol is None:
            return dict(status='not_started')
        decision = _time(board['generated_at'])
        if decision < _time(protocol['started_at']):
            return dict(status='historical')
        if decision > current:
            raise ValueError('catalyst_clock_invalid')
        _issued(root, board)
        names = _universe(symbols)
        selected = [row['symbol'] for row in board['candidates']]
        if not selected or not set(selected) <= set(names) or not set(names)-set(selected):
            raise ValueError('catalyst_control_universe_invalid')
        directory = _directory(root)
        with FileLock(str(directory/'write.lock'), timeout=5):
            registry = _registry(root, protocol)
            path = directory/'cohorts'/f'{binding["decision_id"]}.json'
            old = _read(path, MAX_COHORT_BYTES)
            if old is None and current >= decision+timedelta(hours=HORIZON_HOURS):
                raise ValueError('catalyst_cohort_registration_late')
            data = dict(schema_version=1, policy_version=POLICY, protocol_id=store._hash(protocol), **binding,
                decision_at=_stamp(decision), enrolled_at=_stamp(current), horizon_hours=HORIZON_HOURS,
                horizon_until=_stamp(decision+timedelta(hours=HORIZON_HOURS)), selected_symbols=selected,
                control_symbols=sorted(set(names)-set(selected)), universe=deepcopy(names))
            if old is not None:
                _validate_cohort(old, protocol)
                data['enrolled_at'] = old['enrolled_at']
                if data != old:
                    raise ValueError('catalyst_cohort_identity')
            else:
                if len(registry['cohort_ids']) >= MAX_COHORTS:
                    raise ValueError('catalyst_store_capacity')
                _validate_cohort(data, protocol)
                _immutable(path, data, MAX_COHORT_BYTES)
            if binding['decision_id'] not in registry['cohort_ids']:
                registry['cohort_ids'].append(binding['decision_id'])
                _write(directory/'enrollment.json', registry)
            return dict(status='existing' if old is not None else 'enrolled')
    except Exception as exc:
        allowed = {'catalyst_clock_invalid', 'catalyst_identity_invalid', 'catalyst_journal_unavailable',
            'catalyst_protocol_unavailable', 'catalyst_cohort_integrity', 'catalyst_cohort_identity',
            'catalyst_control_universe_invalid', 'catalyst_store_integrity', 'catalyst_store_capacity',
            'catalyst_cohort_registration_late'}
        error = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else 'catalyst_cohort_unavailable'
        return dict(status='failed', error=error)
