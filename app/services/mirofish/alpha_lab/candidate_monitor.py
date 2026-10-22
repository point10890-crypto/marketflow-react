"""Saved, bounded entry-day observations of an immutable candidate desk.

This module owns only candidate-desk/monitor. A quote is a manual reference,
never an order, fill, notification or alteration to the original price plan.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import math
from pathlib import Path
import re

from filelock import FileLock, Timeout

from . import candidate_store, store
from .market_provider import CALENDAR_SOURCE, QUOTE_SOURCE

KST = timezone(timedelta(hours=9))
_STATES = {'waiting', 'closed', 'monitoring', 'held', 'failed', 'stale', 'unavailable'}


def _clock(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('candidate_monitor_clock')
    return value.astimezone(timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('candidate_monitor_session')
    return value


def _hash_valid(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('candidate_monitor_price')
    result = float(value)
    if not math.isfinite(result) or not 0 < result <= 1e12:
        raise ValueError('candidate_monitor_price')
    return result


def _view(state, now, decision_id=None, quotes=None):
    return dict(state=state if state in _STATES else 'unavailable', checked_at=_stamp(now),
        decision_id=decision_id if _hash_valid(decision_id) else None, quotes=quotes or [])


def _binding(desk, current):
    if (not isinstance(desk, dict) or not _hash_valid(desk.get('decision_id'))
            or desk.get('schema_version') != 1 or desk.get('policy_version') != candidate_store.POLICY
            or desk.get('approved_exposure') != 0 or desk.get('live_orders') is not False):
        raise ValueError('candidate_monitor_binding')
    generated = _clock(desk['generated_at'])
    entry = _day(desk['entry_session'])
    expiry = _clock(desk['valid_until'])
    if (generated > current or _clock(desk['source']['captured_at']) > generated
            or entry <= generated.astimezone(KST).date().isoformat()
            or expiry != datetime.combine(date.fromisoformat(entry), time(15, 30), KST)):
        raise ValueError('candidate_monitor_binding')
    candidates = desk.get('candidates')
    if not isinstance(candidates, list) or len(candidates) > 3:
        raise ValueError('candidate_monitor_binding')
    plans = {}
    for candidate in candidates:
        symbol = candidate['symbol']
        if (not isinstance(symbol, str) or re.fullmatch(r'[0-9]{6}', symbol) is None
                or symbol == '000000' or symbol in plans):
            raise ValueError('candidate_monitor_binding')
        plan = {key: _number(candidate['plan'][key])
                for key in ('entry_price', 'entry_upper', 'stop_price', 'target_price')}
        if not plan['stop_price'] < plan['entry_price'] <= plan['entry_upper'] < plan['target_price']:
            raise ValueError('candidate_monitor_binding')
        plans[symbol] = plan
    return dict(decision_id=desk['decision_id'], entry_session=entry, expiry=expiry,
                plans=plans, plan_hash=store._hash(plans))


def _window(binding, current):
    local = current.astimezone(KST)
    day, hour = local.date().isoformat(), local.time().replace(tzinfo=None)
    if day < binding['entry_session'] or day == binding['entry_session'] and hour < time(9):
        return 'waiting'
    if day > binding['entry_session'] or hour > time(15, 30) or current > binding['expiry']:
        return 'closed'
    return None


def _calendar(raw, day, current):
    if not isinstance(raw, dict) or raw.get('source') != CALENDAR_SOURCE:
        raise ValueError('candidate_monitor_calendar')
    capture = _clock(raw['captured_at'])
    if capture > current or current-capture > timedelta(seconds=420):
        raise ValueError('candidate_monitor_calendar')
    rows, observed = raw.get('days'), {}
    if not isinstance(rows, list) or not 1 <= len(rows) <= 370:
        raise ValueError('candidate_monitor_calendar')
    for row in rows:
        session = _day(row['date'])
        if session < day or session in observed or type(row.get('is_open')) is not bool:
            raise ValueError('candidate_monitor_calendar')
        observed[session] = row['is_open']
    if day not in observed:
        raise ValueError('candidate_monitor_calendar')
    return observed[day]


def _quote(raw, symbol, plan, binding, current, age):
    if (not isinstance(raw, dict) or raw.get('symbol') != symbol or raw.get('source') != QUOTE_SOURCE):
        raise ValueError('candidate_monitor_quote')
    quoted, fetched = _clock(raw['quote_at']), _clock(raw['fetched_at'])
    local = quoted.astimezone(KST)
    if (not quoted <= fetched <= current or current-quoted > timedelta(seconds=age)
            or local.date().isoformat() != binding['entry_session']
            or not time(9) <= local.time().replace(tzinfo=None) <= time(15, 30)):
        raise ValueError('candidate_monitor_quote')
    price, opening = _number(raw['price']), _number(raw['opening_price'])
    within = all(plan['stop_price'] < value <= plan['entry_upper'] and value < plan['target_price']
                 for value in (price, opening))
    return dict(symbol=symbol, state='within_band' if within else 'skip', price=price,
        opening_price=opening, quote_at=_stamp(quoted), fetched_at=_stamp(fetched), source=QUOTE_SOURCE)


def _read(path):
    if not path.is_file() or path.stat().st_size > 64*1024:
        raise ValueError('candidate_monitor_integrity')
    raw = store._read(path)
    if (not isinstance(raw, dict) or set(raw) != {'data', 'sha256'}
            or not isinstance(raw['data'], dict) or raw['sha256'] != store._hash(raw['data'])):
        raise ValueError('candidate_monitor_integrity')
    return raw['data']


def _save(directory, value, binding):
    data = dict(schema_version=1, plan_hash=binding['plan_hash'], **value)
    digest = store._hash(data)
    path = directory/'observations'/(digest+'.json')
    if path.exists():
        if _read(path) != data:
            raise ValueError('candidate_monitor_integrity')
    else:
        store._write(path, dict(data=data, sha256=digest))
    pointer = dict(schema_version=1, observation_hash=digest, decision_id=binding['decision_id'])
    store._write(directory/'latest.json', dict(data=pointer, sha256=store._hash(pointer)))


def read_view(root, desk, *, now=None):
    """Project only saved observations bound to this exact still-usable desk."""
    try:
        current = _clock(now)
    except (ValueError, TypeError, OverflowError):
        return dict(state='unavailable', checked_at=None, decision_id=None, quotes=[])
    identity = desk.get('decision_id') if isinstance(desk, dict) else None
    try:
        binding = _binding(desk, current)
        state = _window(binding, current)
        if state:
            return _view(state, current, identity)
        if desk.get('state') != 'ready' or not binding['plans']:
            return _view('held', current, identity)
        directory = Path(root)/'candidate-desk'/'monitor'
        pointer = _read(directory/'latest.json')
        digest = pointer.get('observation_hash')
        if (pointer.get('schema_version') != 1 or pointer.get('decision_id') != identity or not _hash_valid(digest)):
            raise ValueError('candidate_monitor_binding')
        saved = _read(directory/'observations'/(digest+'.json'))
        if (store._hash(saved) != digest or saved.get('schema_version') != 1
                or saved.get('decision_id') != identity or saved.get('plan_hash') != binding['plan_hash']
                or saved.get('state') not in _STATES):
            raise ValueError('candidate_monitor_binding')
        checked = _clock(saved['checked_at'])
        if checked > current or current-checked > timedelta(seconds=420):
            return _view('stale', current, identity)
        rows = saved.get('quotes')
        if not isinstance(rows, list) or len(rows) > 3:
            raise ValueError('candidate_monitor_integrity')
        quotes, symbols = [], set()
        for raw in rows:
            symbol = raw.get('symbol')
            if symbol not in binding['plans'] or symbol in symbols:
                raise ValueError('candidate_monitor_binding')
            symbols.add(symbol)
            if raw.get('state') == 'unavailable':
                quotes.append(dict(symbol=symbol, state='unavailable'))
            else:
                try:
                    quotes.append(_quote(raw, symbol, binding['plans'][symbol], binding, current, 420))
                except (ValueError, KeyError, TypeError, OverflowError):
                    return _view('stale', current, identity)
        if saved['state'] == 'monitoring' and symbols != set(binding['plans']):
            raise ValueError('candidate_monitor_binding')
        return _view(saved['state'], checked, identity, quotes)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return _view('unavailable', current, identity)


def tick(root, provider, *, now=None):
    """At most one calendar and three quote calls, then an atomic own pointer."""
    try:
        current = _clock(now)
    except (ValueError, TypeError, OverflowError):
        return dict(state='unavailable', checked_at=None, decision_id=None, quotes=[])
    root = Path(root)
    desk = candidate_store.read_public(root/'candidate-desk', now=_stamp(current))
    identity = desk.get('decision_id') if isinstance(desk, dict) else None
    try:
        binding = _binding(desk, current)
        directory = root/'candidate-desk'/'monitor'; directory.mkdir(parents=True, exist_ok=True)
        with FileLock(str(directory/'tick.lock'), timeout=0):
            state = _window(binding, current)
            quotes = []
            if state is None and (desk.get('state') != 'ready' or not binding['plans']):
                state = 'held'
            if state is None:
                try:
                    calendar = provider.fetch_calendar(binding['entry_session'], now=now)
                    current = _clock(now)
                    state = None if _calendar(calendar, binding['entry_session'], current) else 'closed'
                    state = _window(binding, current) or state
                except Exception:
                    state = 'held'
            if state is None:
                for symbol, plan in binding['plans'].items():
                    current = _clock(now)
                    window = _window(binding, current)
                    if window is not None:
                        state, quotes = window, []
                        break
                    try:
                        raw = provider.fetch_quote(symbol, now=now)
                        current = _clock(now)
                        quotes.append(_quote(raw, symbol, plan, binding, current, 120))
                    except Exception:
                        quotes.append(dict(symbol=symbol, state='unavailable'))
                if state is None:
                    state = 'failed' if all(row['state'] == 'unavailable' for row in quotes) else 'monitoring'
            current = _clock(now)
            latest = candidate_store.read_public(root/'candidate-desk', now=_stamp(current))
            if (not isinstance(latest, dict) or latest.get('decision_id') != identity
                    or _binding(latest, current)['plan_hash'] != binding['plan_hash']):
                return _view('held', current, identity)
            window = _window(binding, current)
            if window is not None:
                state, quotes = window, []
            elif latest.get('state') != 'ready':
                state, quotes = 'held', []
            value = _view(state, current, identity, quotes)
            _save(directory, value, binding)
            return value
    except Timeout:
        return _view('held', current, identity)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return _view('unavailable', current, identity)
