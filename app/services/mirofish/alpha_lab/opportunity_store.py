"""Sealed issued opportunity records, separate from paper trades and account PnL.

Reads are projections only. A previous sealed journal can be read after primary
corruption, while guidance is held; GET never repairs or acquires evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import math
from pathlib import Path
import re

from filelock import FileLock

from . import store

POLICY = 'profit-opportunity-v1'
CALENDAR_SOURCE = 'KIS:CTCA0903R'
QUOTE_SOURCE = 'KIS:J:FHKST03010200+FHKST01010100'
KST = timezone(timedelta(hours=9))
MAX_ISSUED = 730


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return result.astimezone(timezone.utc) if isinstance(result, datetime) and result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _now(value):
    result = datetime.now(timezone.utc) if value is None else _time(value)
    if result is None:
        raise ValueError('timezone_required')
    return result


def _hex(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _binding(board):
    if (not isinstance(board, dict) or board.get('schema_version') != 1
            or board.get('policy_version') != POLICY
            or any(not _hex(board.get(key)) for key in ('decision_id', 'input_fingerprint', 'source_audit_hash'))
            or _time(board.get('generated_at')) is None):
        raise ValueError('opportunity_identity')
    candidates = board.get('candidates')
    if (not isinstance(candidates, list) or len(candidates) > 3
            or any(not isinstance(row, dict) or not _hex(row.get('opportunity_id'))
                   or not isinstance(row.get('symbol'), str) or re.fullmatch('[0-9]{6}', row['symbol']) is None
                   for row in candidates)
            or len({row['symbol'] for row in candidates}) != len(candidates)):
        raise ValueError('opportunity_identity')
    return {key: board[key] for key in ('decision_id', 'input_fingerprint', 'source_audit_hash')}


def _stable(board):
    # Display state and a later scan clock do not renew the first issued decision.
    return dict(_binding(board), latest_session=board.get('latest_session'),
        candidates=[{key: deepcopy(row.get(key)) for key in
            ('opportunity_id', 'symbol', 'strategy_id', 'rank', 'plan', 'ranking', 'kelly', 'reference_weight')}
            for row in board['candidates']])


def _directory(root):
    return Path(root)/'decision_engine'


def _read(path):
    raw = store._read(path)
    if raw is None:
        return None
    if (not isinstance(raw, dict) or raw.get('schema_version') != 1
            or not isinstance(raw.get('data'), dict) or raw.get('sha256') != store._hash(raw['data'])):
        raise ValueError('opportunity_store_integrity')
    return raw['data']


def _write(path, data):
    store._write(path, dict(schema_version=1, data=data, sha256=store._hash(data)))


def _validate_journal(value):
    if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('issued'), list):
        raise ValueError('opportunity_store_integrity')
    seen = set()
    for row in value['issued']:
        if (not isinstance(row, dict) or row.get('sha256') != store._hash({k:v for k,v in row.items() if k != 'sha256'})
                or row.get('decision_id') in seen or row.get('decision_id') != _binding(row.get('board'))['decision_id']):
            raise ValueError('opportunity_store_integrity')
        seen.add(row['decision_id'])
    if len(seen) > MAX_ISSUED:
        raise ValueError('opportunity_store_capacity')
    return value


def _journal(root):
    directory = _directory(root)
    try:
        value = _read(directory/'issued.json')
        if value is None and (directory/'issued.backup.json').is_file():
            fallback = _read(directory/'issued.backup.json')
            return _validate_journal(fallback), True
        return _validate_journal(value or dict(schema_version=1, issued=[])), False
    except (OSError, ValueError, KeyError, TypeError):
        fallback = _read(directory/'issued.backup.json')
        if fallback is None:
            raise ValueError('opportunity_store_integrity')
        return _validate_journal(fallback), True


def read_journal(root):
    return deepcopy(_journal(root)[0])


def register_board(root, board):
    """Issue once per deterministic board identity; first clock/plan stays fixed."""
    binding = _binding(board)
    directory = _directory(root); directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory/'issued.lock'), timeout=30):
        journal, recovered = _journal(root)
        if recovered:
            # A writer must not erase corrupt evidence or claim a repaired issue.
            raise ValueError('opportunity_store_recovered')
        old = next((row for row in journal['issued'] if row['decision_id'] == binding['decision_id']), None)
        if old is not None:
            if _stable(old['board']) != _stable(board):
                raise ValueError('opportunity_identity')
            return deepcopy(old['board'])
        if len(journal['issued']) >= MAX_ISSUED:
            raise ValueError('opportunity_store_capacity')
        previous = deepcopy(journal)
        frozen = dict(binding, board=deepcopy(board))
        frozen['board'].pop('evaluation', None)
        journal['issued'].append(dict(frozen, sha256=store._hash(frozen)))
        _write(directory/'issued.backup.json', previous)
        _write(directory/'issued.json', journal)
        return deepcopy(frozen['board'])


def _quotes(value):
    if isinstance(value, dict):
        return list(value.values())
    return value if isinstance(value, list) else []


def _valid_quote(row, symbol, current, session):
    if not isinstance(row, dict) or row.get('symbol') != symbol or row.get('source') != QUOTE_SOURCE:
        return False
    price, quote, fetched = row.get('price'), _time(row.get('quote_at')), _time(row.get('fetched_at'))
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return False
    return bool(quote and fetched and quote <= fetched <= current
        and quote.astimezone(KST).date().isoformat() == session
        and fetched.astimezone(KST).date().isoformat() == session
        and 0 <= (current-quote).total_seconds() <= 420
        and 0 <= (current-fetched).total_seconds() <= 420
        and (fetched-quote).total_seconds() <= 120
        and time(9) <= quote.astimezone(KST).time().replace(tzinfo=None) < time(15,30))


def _observation(root, board, *, now=None):
    binding = _binding(board)
    value = _read(_directory(root)/'observations'/f"{board['decision_id']}.json")
    if value is None:
        if (_directory(root)/'quotes'/f"{board['decision_id']}.json").exists():
            # Receipt precedes quote publication. Its disappearance must not
            # reset a certified window or allow an existing quote to reissue it.
            raise ValueError('opportunity_observation_integrity')
        return dict(binding, window=None, observed={})
    # File names and outer checksums alone cannot bind a receipt to its issue.
    if (any(value.get(key) != item for key,item in binding.items())
            or not isinstance(value.get('observed'),dict)):
        raise ValueError('opportunity_observation_integrity')
    symbols = {row['symbol'] for row in board['candidates']}
    if not set(value['observed']).issubset(symbols):
        raise ValueError('opportunity_observation_integrity')
    window = value.get('window')
    if window is None:
        if value['observed']:
            raise ValueError('opportunity_observation_integrity')
        return value
    if not isinstance(window,dict) or window.get('calendar_source') != CALENDAR_SOURCE:
        raise ValueError('opportunity_observation_integrity')
    session = window.get('entry_session')
    try:
        day = datetime.strptime(session,'%Y-%m-%d').date()
    except (ValueError,TypeError):
        raise ValueError('opportunity_observation_integrity') from None
    deadline = _time(window.get('valid_until'))
    origin = _time(board.get('origin_at') or board['generated_at'])
    if (day.isoformat() != session or origin is None
            or not origin.astimezone(KST).date() < day <= origin.astimezone(KST).date()+timedelta(days=7)
            or deadline != datetime.combine(day,time(15,30),KST).astimezone(timezone.utc)):
        raise ValueError('opportunity_observation_integrity')
    current = _now(now)
    start = datetime.combine(day,time(9),KST)
    for symbol,receipt in value['observed'].items():
        observed = _time(receipt.get('observed_at')) if isinstance(receipt,dict) else None
        if (observed is None or observed > current or not start <= observed < deadline
                or not _valid_quote(receipt.get('quote'),symbol,observed,session)):
            raise ValueError('opportunity_observation_integrity')
    return value


def _window(calendar, board, current, observed):
    if not isinstance(calendar, dict) or calendar.get('status') != 'ready':
        return None
    checked, deadline = _time(calendar.get('checked_at')), _time(calendar.get('valid_until'))
    session = calendar.get('entry_session')
    try:
        day = datetime.strptime(session, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    origin = _time(board.get('origin_at') or board['generated_at'])
    if (calendar.get('source') != CALENDAR_SOURCE or checked is None or observed is None
            or checked > observed or observed > current or deadline is None
            or checked.astimezone(KST).date() != observed.astimezone(KST).date()
            or day <= origin.astimezone(KST).date()
            or day > origin.astimezone(KST).date()+timedelta(days=7)
            or deadline != datetime.combine(day, time(15,30), KST).astimezone(timezone.utc)):
        raise ValueError('opportunity_window')
    return dict(entry_session=session, valid_until=calendar['valid_until'], calendar_source=CALENDAR_SOURCE)


def save_quote_snapshot(root, board, snapshot, *, now=None):
    """Save read-only market observations bound to an immutable issued board."""
    binding = _binding(board); current = _now(now)
    if not isinstance(snapshot, dict) or any(snapshot.get(key) != value for key,value in binding.items()):
        raise ValueError('opportunity_identity')
    observed = _time(snapshot.get('observed_at'))
    if observed is None or observed > current:
        raise ValueError('opportunity_quote_time')
    # Validate the entire proposed artifact before recording even its window.
    if len(store._encode(snapshot)) > store.MAX_BYTES:
        raise ValueError('opportunity_store_capacity')
    directory = _directory(root); directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory/'issued.lock'), timeout=30):
        journal, recovered = _journal(root)
        issued = next((row for row in journal['issued'] if row['decision_id'] == board['decision_id']), None)
        if recovered or issued is None or _stable(issued['board']) != _stable(board):
            raise ValueError('opportunity_identity')
        evidence = _observation(root, board, now=current)
        window = _window(snapshot.get('calendar'), issued['board'], current, observed)
        if window is not None:
            if evidence['window'] is not None and evidence['window'] != window:
                raise ValueError('opportunity_window')
            evidence['window'] = window
        window = evidence['window']
        start = datetime.combine(datetime.strptime(window['entry_session'],'%Y-%m-%d').date(), time(9), KST) if window else None
        deadline = _time(window['valid_until']) if window else None
        symbols = {row['symbol'] for row in board['candidates']}
        if window and start <= observed < deadline:
            for row in _quotes(snapshot.get('quotes')):
                symbol = row.get('symbol') if isinstance(row,dict) else None
                if symbol in symbols and symbol not in evidence['observed'] and _valid_quote(row,symbol,observed,window['entry_session']):
                    evidence['observed'][symbol] = dict(quote=deepcopy(row),observed_at=snapshot['observed_at'])
        _write(directory/'observations'/f"{board['decision_id']}.json", evidence)
        _write(directory/'quotes'/f"{board['decision_id']}.json", deepcopy(snapshot))


def read_quote_snapshot(root, board):
    if not isinstance(board,dict):
        return None
    binding = _binding(board)
    value = _read(_directory(root)/'quotes'/f"{board['decision_id']}.json")
    if value is not None and any(value.get(key) != item for key,item in binding.items()):
        raise ValueError('opportunity_identity')
    return deepcopy(value)


def attach_saved(status, root, *, now=None):
    """Count issued rows from saved evidence without fills, performance, or writes."""
    result = deepcopy(status)
    board = (result.get('report') or {}).get('opportunity_board')
    if not isinstance(board,dict):
        return result
    counts = dict(basis='issued_opportunities_not_fills', issued=0,pending=0,expired=0,observed=0,unobserved=0)
    try:
        current = _now(now); _binding(board)
        journal,recovered = _journal(root)
        current_issued = any(row['decision_id'] == board['decision_id'] and _stable(row['board']) == _stable(board)
                             for row in journal['issued'])
        for issued in journal['issued']:
            frozen = issued['board']; evidence = _observation(root,frozen,now=current)
            window = evidence.get('window')
            deadline = _time((window or {}).get('valid_until'))
            start = datetime.combine(datetime.strptime(window['entry_session'],'%Y-%m-%d').date(),time(9),KST) if window else None
            for row in frozen['candidates']:
                counts['issued'] += 1
                state = ('observed' if row['symbol'] in evidence['observed'] else
                    'pending' if start and current < start else 'expired' if deadline and current >= deadline else 'unobserved')
                counts[state] += 1
        if recovered:
            board.update(status='held', reasons=list(dict.fromkeys([*board.get('reasons',[]),'opportunity_store_recovered'])))
        elif not current_issued:
            board.update(status='held', reasons=list(dict.fromkeys([*board.get('reasons',[]),'opportunity_store_unavailable'])))
        board['evaluation'] = counts
    except (OSError,ValueError,KeyError,TypeError,OverflowError):
        board.update(status='held', reasons=list(dict.fromkeys([*board.get('reasons',[]),'opportunity_store_unavailable'])))
        board['evaluation'] = counts
    return result
