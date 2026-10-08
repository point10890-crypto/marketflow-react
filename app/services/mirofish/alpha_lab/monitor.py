"""Sealed next-session price references; observations are never account fills.

This module owns only ``root/monitor``.  The original two prospective paper
journals and their performance denominator are not read or modified here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import math
from pathlib import Path
import re

from filelock import FileLock

from . import store

KST = timezone(timedelta(hours=9))
POLICY = 'alpha-cadence-v1'
WINDOW_POLICY = 'next-session-proposal-v1'
CALENDAR_SOURCE = 'KIS:CTCA0903R'
QUOTE_SOURCE = 'KIS:J:FHKST03010200+FHKST01010100'
MAX_ORIGINS = 730
QUOTE_TTL = 420
TRADE_AGE = 120
PAPER_BASIS = 'frozen_watchlist_next_open_outcomes_not_account_pnl'


def _timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _now(now):
    value = datetime.now(timezone.utc) if now is None else _timestamp(now)
    if value is None:
        raise ValueError('timezone_required')
    return value


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if value else None


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _hash_valid(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _path(root, name):
    return Path(root)/'monitor'/f'{name}.json'


def _load(root, name, default=None):
    raw = store._read(_path(root, name))
    if raw is None:
        return deepcopy(default)
    if (not isinstance(raw, dict) or not isinstance(raw.get('data'), dict) or raw.get('schema_version') != 1
            or raw.get('sha256') != store._hash(raw.get('data'))):
        raise ValueError('monitor_integrity')
    return raw['data']


def _save(root, name, value):
    store._write(_path(root, name), dict(schema_version=1, data=value, sha256=store._hash(value)))


def _registry(root):
    value = _load(root, 'registry', dict(records=[], active_identity=None))
    if not isinstance(value, dict) or not isinstance(value.get('records'), list):
        raise ValueError('monitor_integrity')
    identities = []
    for row in value['records']:
        if not isinstance(row, dict) or row.get('sha256') != store._hash({k: v for k, v in row.items() if k != 'sha256'}):
            raise ValueError('monitor_integrity')
        identities.append(row.get('identity'))
    if len(identities) != len(set(identities)) or len(identities) > MAX_ORIGINS:
        raise ValueError('monitor_integrity')
    return value


def _binding(report, now):
    """Exact stable BUY identity; tolerate sparse old reports without upgrading them."""
    if not isinstance(report, dict) or report.get('schema_version') != 1 or report.get('mode') != 'research':
        return None
    fingerprint = report.get('input_fingerprint')
    scan = report.get('opportunity_scan') or {}
    if not isinstance(scan, dict) or not isinstance(report.get('provenance'), dict) or not isinstance(report.get('universe'), dict):
        return None
    audit = scan.get('audit_hash')
    decision = _timestamp(report.get('decision_at'))
    capture = _timestamp((report.get('provenance') or {}).get('captured_at'))
    session = _day(report.get('latest_session'))
    scope = _day(report['universe'].get('scope_date'))
    if (not _hash_valid(fingerprint) or not _hash_valid(audit) or decision is None or capture is None
            or capture > decision or decision > now or session is None or scope is None
            or session > decision.astimezone(KST).date()
            or not 0 <= (decision.astimezone(KST).date()-scope).days <= 7
            or (decision.astimezone(KST).date()-session).days > 7):
        return None
    # Validate the existing manual research opinion at its own decision clock.
    # Its optional projection fields never enter the stable source identity.
    from .proposals import present_status
    original = deepcopy(report)
    original.pop('proposal_window', None)
    try:
        view = present_status(dict(state='held', report=original), now=_stamp(decision))['report']
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None
    candidates = []
    for row in view.get('buy_candidates') or []:
        if not isinstance(row, dict) or row.get('proposal', {}).get('action') != 'buy':
            continue
        plan = row.get('plan') or {}
        atr = _number(plan.get('atr'))
        symbol = row.get('symbol')
        if (not isinstance(symbol, str) or re.fullmatch('[0-9]{6}', symbol) is None
                or atr is None or atr <= 0 or row.get('quote_session') != report['latest_session']):
            return None
        distance = min(2*atr, row['last_close']*.08)
        if not math.isclose(row['last_close']-plan['stop_price'], distance, rel_tol=1e-9, abs_tol=1e-7):
            return None
        frozen = {key: deepcopy(row.get(key)) for key in
                  ('symbol', 'name', 'strategy_id', 'quote_session', 'last_close', 'plan')}
        frozen['research_weight'] = row['risk']['research_weight']
        candidates.append(frozen)
    if not candidates or len(candidates) > 3 or len({row['symbol'] for row in candidates}) != len(candidates):
        return None
    candidates.sort(key=lambda row: row['symbol'])
    candidate_hash = store._hash(candidates)
    identity = store._hash(dict(input_fingerprint=fingerprint, opportunity_audit_hash=audit,
                               candidate_hash=candidate_hash))
    return dict(identity=identity, input_fingerprint=fingerprint, opportunity_audit_hash=audit,
        candidate_hash=candidate_hash, origin_at=_stamp(decision), captured_at=_stamp(capture),
        source_session=session.isoformat(), scope_session=scope.isoformat(),
        price_basis=(report.get('provenance') or {}).get('price_basis'),
        candidates=candidates)


def _matches(binding, record):
    return (binding is not None and record is not None and binding['identity'] == record['identity']
            and _timestamp(record['origin_at']) <= _timestamp(binding['origin_at'])
            and all(binding[key] == record[key] for key in
                    ('captured_at', 'source_session', 'scope_session', 'price_basis')))


def register_report(root, report, now=None):
    """Pin first origin for identical inputs/plans; no original report/journal writes."""
    current = _now(now)
    directory = Path(root)/'monitor'
    # Read before considering legacy/no-candidate data: corruption fails a scan.
    registry = _registry(root)
    binding = _binding(report, current)
    if binding is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory/'monitor.lock'), timeout=30):
        registry = _registry(root)
        record = next((row for row in registry['records'] if row['identity'] == binding['identity']), None)
        if record is None:
            if len(registry['records']) >= MAX_ORIGINS:
                raise ValueError('monitor_capacity')
            record = dict(binding, sha256=store._hash(binding))
            registry['records'].append(record)
        elif not _matches(binding, record):
            raise ValueError('monitor_source_identity')
        registry['active_identity'] = record['identity']
        _save(root, 'registry', registry)
    return deepcopy(record)


def _active(registry):
    return next((row for row in registry['records'] if row['identity'] == registry['active_identity']), None)


def _fresh(record, now):
    if record is None:
        return False
    today = now.astimezone(KST).date()
    origin, capture, session = _timestamp(record['origin_at']), _timestamp(record['captured_at']), _day(record['source_session'])
    scope = _day(record['scope_session'])
    return (origin is not None and capture is not None and session is not None and scope is not None and capture <= origin <= now
            and 0 <= (today-origin.astimezone(KST).date()).days <= 7
            and 0 <= (today-capture.astimezone(KST).date()).days <= 7
            and 0 <= (today-session).days <= 7 and 0 <= (today-scope).days <= 7)


def _calendar_data(value, base, now):
    if not isinstance(value, dict) or value.get('source') != CALENDAR_SOURCE:
        raise ValueError('calendar_invalid')
    captured = _timestamp(value.get('captured_at'))
    days = value.get('days')
    if (captured is None or captured > now or captured.astimezone(KST).date() != now.astimezone(KST).date()
            or not isinstance(days, list) or not days or len(days) > 366):
        raise ValueError('calendar_invalid')
    normalized = {}
    for row in days:
        day = _day(row.get('date')) if isinstance(row, dict) else None
        if day is None or not isinstance(row.get('is_open'), bool) or day in normalized:
            raise ValueError('calendar_invalid')
        normalized[day] = row['is_open']
    first, last = min(normalized), max(normalized)
    if (first > base or last < now.astimezone(KST).date()
            or len(normalized) != (last-first).days+1):
        raise ValueError('calendar_gap')
    return dict(source=CALENDAR_SOURCE, captured_at=_stamp(captured),
                days=[dict(date=day.isoformat(), is_open=normalized[day]) for day in sorted(normalized)])


def _calendar(root, provider, now, record=None, *, fixed=True):
    today = now.astimezone(KST).date()
    cached = _load(root, 'calendar')
    attempts = 0
    if cached is not None and cached.get('checked_day') == today.isoformat():
        checked = _timestamp(cached.get('checked_at'))
        if checked is None or checked > now:
            raise ValueError('monitor_integrity')
        attempts = cached.get('attempts', 1)
        if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 3:
            raise ValueError('monitor_integrity')
        if cached.get('status') == 'ready' or attempts >= 3 or (now-checked).total_seconds() < 900:
            _pin_session(root, record, cached, now)
            return cached
    base = _timestamp(record['origin_at']).astimezone(KST).date() if _fresh(record, now) else today
    cached = dict(checked_day=today.isoformat(), checked_at=_stamp(now), attempts=attempts+1, status='failed', data=None,
                  reasons=['calendar_unavailable'])
    try:
        data = provider.fetch_calendar(base.isoformat(), _stamp(now) if fixed else None)
        now = now if fixed else _now(None)
        cached.update(checked_at=_stamp(now), checked_day=now.astimezone(KST).date().isoformat())
        cached.update(status='ready', data=_calendar_data(data, base, now), reasons=[])
    except ValueError as error:
        code = str(error) if str(error) in {'calendar_invalid', 'calendar_gap'} else 'calendar_unavailable'
        cached.update(status='held', reasons=[code])
    except Exception:
        pass
    _save(root, 'calendar', cached)
    _pin_session(root, record, cached, now)
    return cached


def _calendar_view(cached, now):
    today = now.astimezone(KST).date()
    checked = _timestamp(cached.get('checked_at')) if isinstance(cached, dict) else None
    if (cached is None or checked is None or checked > now or cached.get('checked_day') != today.isoformat()):
        return dict(market_state='unknown', calendar_status='held', calendar_checked_at=_stamp(checked),
                    is_open=None, reasons=['calendar_stale' if cached else 'calendar_unavailable'])
    ready = cached.get('status') == 'ready'
    day = next((row for row in (cached.get('data') or {}).get('days', []) if row['date'] == today.isoformat()), None)
    is_open = day['is_open'] if ready and day else None
    clock = now.astimezone(KST).time().replace(tzinfo=None)
    state = ('unknown' if is_open is None else 'open' if is_open and time(9) <= clock < time(15, 30)
             else 'closed' if is_open or today.weekday() >= 5 else 'holiday')
    return dict(market_state=state, calendar_status=cached['status'], calendar_checked_at=_stamp(checked),
                is_open=is_open, reasons=deepcopy(cached.get('reasons') or ([] if is_open else ['market_closed'])))


def _raw_session(record, cached, now):
    if not _fresh(record, now) or _calendar_view(cached, now)['calendar_status'] != 'ready':
        return None
    origin = _timestamp(record['origin_at']).astimezone(KST).date()
    days = {_day(row['date']): row['is_open'] for row in cached['data']['days']}
    for offset in range(1, 8):
        day = origin+timedelta(days=offset)
        if day not in days:
            return None
        if days[day]:
            return day
    return None


def _pin_session(root, record, cached, now):
    session = _raw_session(record, cached, now)
    if session is None:
        return
    bindings = _load(root, 'sessions', {})
    if record['identity'] in bindings:
        return
    if len(bindings) >= MAX_ORIGINS:
        raise ValueError('monitor_capacity')
    bindings[record['identity']] = dict(origin_at=record['origin_at'], entry_session=session.isoformat(),
        valid_until=_stamp(datetime.combine(session, time(15, 30), KST)),
        input_fingerprint=record['input_fingerprint'], opportunity_audit_hash=record['opportunity_audit_hash'],
        calendar_source=CALENDAR_SOURCE, calendar_sha256=store._hash(cached['data']),
        captured_at=cached['data']['captured_at'])
    _save(root, 'sessions', bindings)


def _entry_session(root, record, cached, now):
    session = _raw_session(record, cached, now)
    if session is None:
        return None
    pinned = _load(root, 'sessions', {}).get(record['identity'])
    if pinned is None:
        return None
    if (not isinstance(pinned, dict) or pinned.get('origin_at') != record['origin_at']
            or pinned.get('input_fingerprint') != record['input_fingerprint']
            or pinned.get('opportunity_audit_hash') != record['opportunity_audit_hash']
            or pinned.get('calendar_source') != CALENDAR_SOURCE
            or not _hash_valid(pinned.get('calendar_sha256'))):
        raise ValueError('monitor_integrity')
    day = _day(pinned.get('entry_session'))
    if day is None or pinned.get('valid_until') != _stamp(datetime.combine(day, time(15, 30), KST)):
        raise ValueError('monitor_integrity')
    return day if day == session else None


def _session_problem(root, record, cached, now):
    current = _raw_session(record, cached, now)
    if current is not None and record:
        pinned = _load(root, 'sessions', {}).get(record['identity'])
        if pinned is not None and pinned.get('entry_session') != current.isoformat():
            return 'calendar_revision'
    return 'calendar_unavailable'


def calendar_check(root, provider, now=None):
    """Certify today's session from one sealed daily provider observation."""
    current = _now(now)
    directory = Path(root)/'monitor'; directory.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(directory/'monitor.lock'), timeout=30):
            cached = _calendar(root, provider, current, _active(_registry(root)), fixed=now is not None)
            current = current if now is not None else _now(None)
            result = _calendar_view(cached, current)
    except (OSError, ValueError, KeyError, TypeError):
        result = dict(market_state='unknown', calendar_status='failed', calendar_checked_at=None,
                      is_open=None, reasons=['monitor_corrupt'])
    return result


def _base_quote(candidate, state='unavailable', reasons=None):
    plan = candidate['plan']
    return dict(symbol=candidate['symbol'], price=None, quote_at=None, fetched_at=None, opening_price=None,
        source=QUOTE_SOURCE, entry_state=state, reference_price=candidate['last_close'],
        entry_ceiling=round(candidate['last_close']*1.02, 6), stop_price=plan['stop_price'],
        target_price=plan['target_price'], reasons=list(reasons or []))


def _mask(row, state, reason):
    row.update(price=None, quote_at=None, fetched_at=None, opening_price=None, entry_state=state)
    row.pop('adjusted_plan', None)
    row['reasons'] = list(dict.fromkeys([*row.get('reasons', []), reason]))
    return row


def _validate_quote(raw, symbol, now):
    if not isinstance(raw, dict) or raw.get('symbol') != symbol:
        return 'quote_symbol_mismatch'
    price, opening = _number(raw.get('price')), _number(raw.get('opening_price'))
    quote, fetched = _timestamp(raw.get('quote_at')), _timestamp(raw.get('fetched_at'))
    if price is None or price <= 0 or opening is None or opening <= 0 or raw.get('source') != QUOTE_SOURCE or quote is None or fetched is None:
        return 'quote_invalid'
    if quote > now or fetched > now or quote > fetched:
        return 'quote_future'
    today = now.astimezone(KST).date()
    if (quote.astimezone(KST).date() != today or fetched.astimezone(KST).date() != today
            or (now-quote).total_seconds() > TRADE_AGE or (now-fetched).total_seconds() > TRADE_AGE
            or (fetched-quote).total_seconds() > TRADE_AGE):
        return 'quote_stale'
    if not time(9) <= quote.astimezone(KST).time().replace(tzinfo=None) <= time(15, 30):
        return 'quote_invalid'
    if now.astimezone(KST).time().replace(tzinfo=None) >= time(15, 30):
        return 'after_close'
    return None


def _reference(candidate, raw, record, now, status_digest):
    opening = float(raw['opening_price'])
    plan = candidate['plan']
    state = ('above_ceiling' if opening > round(candidate['last_close']*1.02, 6)
             else 'below_stop' if opening < plan['stop_price'] else 'within_band')
    reference = dict(identity=record['identity'], symbol=candidate['symbol'], observed_at=_stamp(now),
        quote_at=_stamp(_timestamp(raw['quote_at'])), fetched_at=_stamp(_timestamp(raw['fetched_at'])),
        source=QUOTE_SOURCE, status_digest=status_digest, opening_price=opening, entry_state=state)
    if state == 'within_band':
        distance = min(2*plan['atr'], opening*.08)
        adjusted = dict(entry_price=opening, stop_price=opening-distance, target_price=opening+2*distance,
                        loss_fraction=distance/opening,
                        proposed_weight=min(candidate['research_weight'], .05, .01/(distance/opening)))
        if any(_number(value) is None or value <= 0 for value in adjusted.values()):
            raise ValueError('quote_invalid')
        reference['adjusted_plan'] = adjusted
    return reference


def _paper(report):
    raw = ((report or {}).get('opportunity_scan') or {}).get('forward') or {}
    result = {key: deepcopy(raw[key]) for key in ('decisions', 'matured', 'win_rate', 'mean_net_return',
        'counts', 'excluded_revised_closed', 'revision_policy') if key in raw}
    result.setdefault('decisions', 0); result.setdefault('matured', 0)
    result.setdefault('win_rate', None); result.setdefault('mean_net_return', None)
    result.setdefault('excluded_revised_closed', 0)
    result.setdefault('counts', {key: 0 for key in ('pending', 'open', 'unfilled', 'missing_session', 'source_revision', 'closed')})
    return dict(result, basis=PAPER_BASIS, entry_guard_applied=False)


def _schedule(cached, now, clock):
    if _calendar_view(cached, now)['calendar_status'] != 'ready':
        return None
    for row in cached['data']['days']:
        value = datetime.combine(_day(row['date']), clock, KST)
        if row['is_open'] and value > now:
            return _stamp(value)
    return None


def _operations(report, record, cached, now, *, root, quotes=None, status='held', reasons=None, observed_at=None):
    calendar = _calendar_view(cached, now)
    session = _entry_session(root, record, cached, now)
    deadline = datetime.combine(session, time(15, 30), KST) if session else None
    local = now.astimezone(KST)
    next_monitor = _schedule(cached, now, time(9))
    if calendar['is_open'] and time(9) <= local.time().replace(tzinfo=None) < time(15, 30):
        opening = datetime.combine(local.date(), time(9), KST)
        step = int((now-opening).total_seconds()//300)+1
        next_monitor = _stamp(min(opening+timedelta(seconds=step*300), datetime.combine(local.date(), time(15, 30), KST)))
    return dict(schema_version=1, policy_version=POLICY, generated_at=_stamp(now),
        cadence=dict(timezone='Asia/Seoul', research_time='20:30', monitor_interval_seconds=300,
            market_state=calendar['market_state'], calendar_status=calendar['calendar_status'],
            calendar_checked_at=calendar['calendar_checked_at'], last_scan_at=(report or {}).get('decision_at'),
            next_scan_at=_schedule(cached, now, time(20, 30)), last_monitor_at=observed_at,
            next_monitor_at=next_monitor, reasons=calendar['reasons']),
        monitoring=dict(status=status, decision_at=(report or {}).get('decision_at'),
            origin_at=record['origin_at'] if record else None,
            input_fingerprint=record['input_fingerprint'] if record else None,
            opportunity_audit_hash=record['opportunity_audit_hash'] if record else None,
            entry_session=session.isoformat() if session else None, valid_until=_stamp(deadline),
            observed_at=observed_at, quotes=quotes if quotes is not None else
                [_base_quote(row) for row in record['candidates']] if record else [], reasons=list(reasons or [])),
        paper=_paper(report))


def _current_report(root, now):
    status = store.read_status(root, now=_stamp(now))
    report = status.get('report')
    if status.get('state') not in {'ready', 'held'}:
        return report, None, 'research_unavailable'
    binding = _binding(report, now)
    if binding is None:
        return report, None, 'missing_report'
    return report, binding, None


def _run_legacy_monitor(root, provider, now=None):
    """Observe official opening/current references and save only monitor artifacts."""
    current = _now(now)
    directory = Path(root)/'monitor'; directory.mkdir(parents=True, exist_ok=True)
    report = None
    try:
        with FileLock(str(directory/'monitor.lock'), timeout=30):
            registry = _registry(root); record = _active(registry)
            cached = _calendar(root, provider, current, record, fixed=now is not None)
            current = current if now is not None else _now(None)
            report, binding, failure = _current_report(root, current)
            entries = None
            source_status_digest = store._hash(store.read_status(root, now=_stamp(current)))
            if not _matches(binding, record):
                reason = failure or 'identity_mismatch'
                result = _operations(report, record, cached, current, root=root, reasons=[reason], observed_at=_stamp(current))
            elif not _fresh(record, current):
                result = _operations(report, record, cached, current, root=root, reasons=['source_stale'], observed_at=_stamp(current))
            else:
                calendar = _calendar_view(cached, current)
                session = _entry_session(root, record, cached, current)
                session_reason = _session_problem(root, record, cached, current) if session is None else None
                entries = _load(root, 'entries', {})
                local = current.astimezone(KST)
                clock = local.time().replace(tzinfo=None)
                quotes, failed = [], False
                for candidate in record['candidates']:
                    local = current.astimezone(KST)
                    clock = local.time().replace(tzinfo=None)
                    calendar = _calendar_view(cached, current)
                    row = _base_quote(candidate)
                    entry_key = record['identity']+':'+candidate['symbol']
                    entry = entries.get(entry_key)
                    if calendar['is_open'] is not True or session is None:
                        _mask(row, 'closed' if calendar['is_open'] is False else 'unavailable',
                              'market_closed' if calendar['is_open'] is False else session_reason or 'calendar_unavailable')
                    elif clock < time(9) or local.date() < session:
                        _mask(row, 'wait_open', 'before_open')
                    elif clock >= time(15, 30):
                        _mask(row, 'closed', 'after_close')
                    elif entry is None and (local.date() != session or clock >= time(15, 30)):
                        _mask(row, 'unavailable', 'window_expired')
                    elif entry is not None and entry['entry_state'] != 'within_band' and local.date() != session:
                        _mask(row, 'closed', 'window_expired')
                    else:
                        try:
                            raw = provider.fetch_quote(candidate['symbol'], _stamp(current) if now is not None else None)
                            current = current if now is not None else _now(None)
                            reason = _validate_quote(raw, candidate['symbol'], current)
                            if reason:
                                raise ValueError(reason)
                            if entry is None:
                                entry = _reference(candidate, raw, record, current, source_status_digest)
                                entries[entry_key] = entry
                            elif local.date() == session and float(raw['opening_price']) != entry['opening_price']:
                                raise ValueError('opening_revision')
                            row.update(price=float(raw['price']), quote_at=_stamp(_timestamp(raw['quote_at'])),
                                fetched_at=_stamp(_timestamp(raw['fetched_at'])), opening_price=entry['opening_price'],
                                entry_state=entry['entry_state'], reasons=[])
                            if 'adjusted_plan' in entry:
                                row['adjusted_plan'] = deepcopy(entry['adjusted_plan'])
                                if row['price'] <= entry['adjusted_plan']['stop_price']:
                                    row.update(entry_state='below_stop', reasons=['below_stop'])
                                elif row['price'] >= entry['adjusted_plan']['target_price']:
                                    row.update(entry_state='target_reached', reasons=['target_reached'])
                            else:
                                row['reasons'] = [entry['entry_state']]
                        except Exception as error:
                            allowed = {'quote_symbol_mismatch', 'quote_invalid', 'quote_future', 'quote_stale', 'opening_revision', 'after_close'}
                            reason = str(error) if isinstance(error, ValueError) and str(error) in allowed else 'quote_unavailable'
                            _mask(row, 'closed' if reason == 'after_close' else 'stale' if reason == 'quote_stale' else 'unavailable', reason)
                            failed = failed or reason != 'after_close'
                    quotes.append(row)
                if failed:
                    for row in quotes:
                        _mask(row, 'unavailable', 'quote_unavailable')
                result = _operations(report, record, cached, current, root=root, quotes=quotes,
                    status='failed' if failed else 'ready' if any(row['price'] is not None for row in quotes) else 'held',
                    reasons=['quote_unavailable'] if failed else [session_reason] if session_reason else [], observed_at=_stamp(current))
            # Research status can change during external requests. Old input quotes
            # cannot be published against a newly saved or unfinished report.
            latest, latest_binding, latest_failure = _current_report(root, current)
            if not _matches(latest_binding, record):
                reason = latest_failure or 'identity_mismatch'
                result['monitoring'].update(status='held', reasons=[reason])
                for row in result['monitoring']['quotes']:
                    _mask(row, 'unavailable', reason)
            elif entries is not None:
                # Commit opening references only if the source is still current.
                _save(root, 'entries', entries)
            final_calendar = _calendar_view(cached, current)
            if final_calendar['is_open'] is True and final_calendar['market_state'] == 'closed':
                after_close = current.astimezone(KST).time().replace(tzinfo=None) >= time(15, 30)
                for row in result['monitoring']['quotes']:
                    _mask(row, 'closed' if after_close else 'wait_open', 'after_close' if after_close else 'before_open')
                if result['monitoring']['status'] == 'ready':
                    result['monitoring']['status'] = 'held'
            result['monitoring']['decision_at'] = (latest or {}).get('decision_at')
            result['cadence']['last_scan_at'] = (latest or {}).get('decision_at')
            result['paper'] = _paper(latest)
            result['status_digest'] = source_status_digest
            result['identity'] = record['identity'] if record else None
            _save(root, 'current', result)
            return {key: deepcopy(value) for key, value in result.items() if key not in {'status_digest', 'identity'}}
    except (OSError, ValueError, KeyError, TypeError):
        result = _operations(report, None, None, current, root=root, status='failed', reasons=['monitor_corrupt'], observed_at=_stamp(current))
        # Corruption must hide guidance, but do not overwrite the corrupt evidence.
        return result


def attach_operations(status, root, now=None):
    """Pure saved projection: no provider, mutation, locks, or artifact writes."""
    current = _now(now)
    result = deepcopy(status)
    report = result.get('report')
    binding = _binding(report, current)
    try:
        registry = _registry(root)
        record = next((row for row in registry['records'] if binding and row['identity'] == binding['identity']), None)
        cached = _load(root, 'calendar')
        saved = _load(root, 'current')
        operational = result.get('state') in {'ready', 'held'}
        reason = (None if operational else 'research_unavailable')
        if binding is None or record is None:
            reason = reason or ('identity_mismatch' if saved or registry['records'] else 'missing_report')
        elif not _fresh(record, current):
            reason = reason or 'source_stale'
        elif not _matches(binding, record):
            reason = reason or 'identity_mismatch'
        quotes = deepcopy((saved or {}).get('monitoring', {}).get('quotes') or [])
        if record is not None and {row['symbol'] for row in quotes} != {row['symbol'] for row in record['candidates']}:
            quotes = [_base_quote(row) for row in record['candidates']]
        saved_monitor = (saved or {}).get('monitoring') or {}
        if record is not None and (saved_monitor.get('input_fingerprint') != record['input_fingerprint']
                or saved_monitor.get('opportunity_audit_hash') != record['opportunity_audit_hash']
                or (saved or {}).get('identity') != record['identity']):
            # A repeated symbol does not bind its previous reference prices to
            # new evidence. Project the new frozen plan without replaying quotes.
            quotes = [_base_quote(row) for row in record['candidates']]
            if saved:
                reason = reason or 'identity_mismatch'
        if saved_monitor.get('status') == 'failed':
            reason = reason or 'quote_unavailable'
        calendar = _calendar_view(cached, current)
        if calendar['calendar_status'] != 'ready':
            reason = reason or calendar['reasons'][0]
        elif record is not None and _entry_session(root, record, cached, current) is None:
            reason = reason or _session_problem(root, record, cached, current)
        local = current.astimezone(KST)
        for row in quotes:
            if reason:
                _mask(row, 'unavailable', reason)
            elif calendar['is_open'] is False:
                _mask(row, 'closed', 'market_closed')
            elif local.time().replace(tzinfo=None) < time(9):
                _mask(row, 'wait_open', 'before_open')
            elif local.time().replace(tzinfo=None) >= time(15, 30):
                _mask(row, 'closed', 'after_close')
            elif row.get('price') is not None:
                timestamps = [_timestamp(row.get(key)) for key in ('quote_at', 'fetched_at')]
                if any(stamp is None or stamp > current or stamp.astimezone(KST).date() != local.date()
                       or (current-stamp).total_seconds() >= QUOTE_TTL for stamp in timestamps):
                    _mask(row, 'stale', 'quote_stale')
        operations = _operations(report, record, cached, current, root=root, quotes=quotes,
            status='held' if reason else saved_monitor.get('status', 'held'), reasons=[reason] if reason else saved_monitor.get('reasons', []),
            observed_at=saved_monitor.get('observed_at'))
        if any(row['entry_state'] == 'stale' for row in quotes):
            operations['monitoring']['status'] = 'held'
        if isinstance(report, dict) and binding is not None:
            origin = record['origin_at'] if record else binding['origin_at']
            session = _entry_session(root, record, cached, current) if operational and reason not in {'identity_mismatch', 'source_stale'} else None
            report['proposal_window'] = dict(policy_version=WINDOW_POLICY, input_fingerprint=binding['input_fingerprint'],
                opportunity_audit_hash=binding['opportunity_audit_hash'], origin_at=origin,
                entry_session=session.isoformat() if session else None,
                valid_until=_stamp(datetime.combine(session, time(15, 30), KST)) if session else None,
                calendar_source=CALENDAR_SOURCE)
        result['operations'] = operations
        return result
    except (OSError, ValueError, KeyError, TypeError):
        result['operations'] = _operations(report, None, None, current, root=root, status='failed', reasons=['monitor_corrupt'])
        if isinstance(report, dict) and binding is not None:
            report['proposal_window'] = dict(policy_version=WINDOW_POLICY, input_fingerprint=binding['input_fingerprint'],
                opportunity_audit_hash=binding['opportunity_audit_hash'], origin_at=binding['origin_at'],
                entry_session=None, valid_until=None, calendar_source=CALENDAR_SOURCE)
        return result


def _observe_opportunity_board(root, provider, operations, now=None):
    """Add bounded current-price references without changing legacy monitor output."""
    from . import opportunity_store

    # Use the legacy post-request clock. Sparse reports add no provider calls.
    current = _timestamp(operations.get('generated_at'))
    if current is None:
        return
    source = store.read_status(root, now=_stamp(current))
    report = source.get('report') or {}
    board = report.get('opportunity_board')
    if (source.get('state') not in {'ready', 'held'} or not isinstance(board, dict)
            or not isinstance(board.get('candidates'), list)):
        return
    if (board.get('input_fingerprint') != report.get('input_fingerprint')
            or board.get('source_audit_hash') != (report.get('opportunity_scan') or {}).get('audit_hash')):
        return
    view = attach_operations(source, root, now=_stamp(current))
    window = (view.get('report') or {}).get('proposal_window') or {}
    saved_operations = view['operations']
    cadence = saved_operations['cadence']
    market = _calendar_view(_load(root, 'calendar'), current)
    calendar = dict(status=cadence['calendar_status'], source=CALENDAR_SOURCE,
        checked_at=cadence['calendar_checked_at'], is_open=market['is_open'],
        market_state=cadence['market_state'], entry_session=window.get('entry_session'),
        valid_until=window.get('valid_until'))
    binding = opportunity_store._binding(board)
    snapshot = dict(binding, observed_at=_stamp(current), calendar=calendar, quotes={}, reasons=[])
    session = _day(window.get('entry_session'))
    deadline = _timestamp(window.get('valid_until'))
    local = current.astimezone(KST)
    eligible_clock = (calendar['status'] == 'ready' and calendar['is_open'] is True
        and session == local.date() and deadline and current < deadline
        and time(9) <= local.time().replace(tzinfo=None) < time(15,30)
        and saved_operations['monitoring']['status'] != 'failed')
    if eligible_clock:
        # Quotes for the original frozen BUY3 were fetched by the old monitor.
        # Reuse only its identity-bound saved projection; add at most three new calls.
        legacy = {row['symbol']: row for row in saved_operations['monitoring']['quotes']}
        failed = False
        for candidate in board['candidates'][:3]:
            symbol = candidate['symbol']
            row = legacy.get(symbol)
            try:
                if row is not None:
                    raw = {key: deepcopy(row.get(key)) for key in
                        ('symbol', 'price', 'opening_price', 'quote_at', 'fetched_at', 'source')}
                else:
                    raw = provider.fetch_quote(symbol, _stamp(current) if now is not None else None)
                    current = current if now is not None else _now(None)
                problem = _validate_quote(raw, symbol, current)
                if problem:
                    raise ValueError(problem)
                snapshot['quotes'][symbol] = {key: deepcopy(raw[key]) for key in
                    ('symbol', 'price', 'opening_price', 'quote_at', 'fetched_at', 'source')}
            except Exception:
                failed = True
        if failed:
            snapshot.update(quotes={}, reasons=['quote_unavailable'])
    elif saved_operations['monitoring']['status'] == 'failed':
        snapshot['reasons'] = ['quote_unavailable']
    snapshot['observed_at'] = _stamp(current)
    # Recheck the complete raw board and source after all external requests.
    latest = store.read_status(root, now=_stamp(current))
    latest_report = latest.get('report') or {}
    latest_board = latest_report.get('opportunity_board')
    if (latest.get('state') not in {'ready', 'held'} or not isinstance(latest_board, dict)
            or opportunity_store._stable(latest_board) != opportunity_store._stable(board)
            or latest_report.get('input_fingerprint') != report.get('input_fingerprint')
            or (latest_report.get('opportunity_scan') or {}).get('audit_hash') != board['source_audit_hash']):
        return
    fresh_view = attach_operations(latest, root, now=_stamp(current))
    final_window = (fresh_view.get('report') or {}).get('proposal_window') or {}
    final_calendar = _calendar_view(_load(root,'calendar'), current)
    if (final_window.get('entry_session') != calendar['entry_session']
            or final_window.get('valid_until') != calendar['valid_until']
            or final_calendar['calendar_status'] != calendar['status']):
        snapshot.update(quotes={}, reasons=['calendar_revision'])
        snapshot['calendar']['status'] = 'held'
    elif (final_calendar['is_open'] is not True
            or current.astimezone(KST).time().replace(tzinfo=None) >= time(15,30)):
        snapshot['quotes'] = {}
    opportunity_store.save_quote_snapshot(root, board, snapshot, now=_stamp(current))


def run_monitor(root, provider, now=None):
    """Retain the original return value, adding an isolated opportunity snapshot."""
    result = _run_legacy_monitor(root, provider, now=now)
    try:
        _observe_opportunity_board(root, provider, result, now=now)
    except Exception as exc:
        # The saved raw/new guidance holds when its isolated evidence is missing;
        # the two original journals and the monitor return value are untouched.
        import logging
        logging.getLogger(__name__).warning('Opportunity observations held (%s)', type(exc).__name__)
    return result
