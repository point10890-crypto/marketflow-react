"""Additive candidate desk orchestration; frozen v2 remains unchanged."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import threading

from filelock import FileLock, Timeout

from . import service as legacy, store, candidate_store
from .market_provider import KISMarketProvider

ROOT = legacy.ROOT


def _acquire(root, *, now=None, provider=None):
    from .candidate_inputs import collect_inputs
    root = Path(root)
    pointer = store._read(root/'inputs'/'current.json')
    attempt = store._read(root/'inputs'/'last_attempt.json')
    if (not isinstance(pointer, dict) or not isinstance(attempt, dict)
            or attempt.get('status') != 'complete' or not pointer.get('snapshot_id')
            or attempt.get('snapshot_id') != pointer['snapshot_id']):
        raise ValueError('candidate_scope_unavailable')
    original = legacy.load_inputs(*legacy.resolve_inputs(root))
    if (original['status'] != 'ready' or original['latest_session'] != pointer.get('latest_session')
            or original['provenance'].get('scope_hash') != (pointer.get('hashes') or {}).get('universe_report')):
        raise ValueError('candidate_scope_unavailable')
    return collect_inputs(Path(root)/'candidate-desk'/'inputs', sorted(original['names']),
        latest_session=original['latest_session'], scope_hash=original['provenance']['scope_hash'],
        names=original['names'], provider=provider, now=now)


def _detect(inputs):
    from .candidate_learning import discover_context_candidates
    return discover_context_candidates(inputs['prices_by_symbol'], names=inputs['names'], as_of=inputs['latest_session'])


def _entry(calendar, current):
    """Do not simulate an opening that passed before actual data acquisition."""
    day = current.astimezone(candidate_store.KST).date().isoformat()
    if not isinstance(calendar, dict) or calendar.get('source') != 'KIS:CTCA0903R':
        return None, None
    rows = calendar.get('days')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 370:
        return None, None
    try:
        captured = candidate_store._clock(calendar['captured_at'])
        if not timedelta(0) <= current-captured <= timedelta(minutes=5):
            return None, None
        days = {}
        for row in rows:
            value = row['date']
            parsed = date.fromisoformat(value)
            if (parsed.isoformat() != value or value < day or value in days
                    or type(row.get('is_open')) is not bool):
                return None, None
            days[value] = row['is_open']
        future = sorted(value for value,opened in days.items() if opened and value > day
                        and (date.fromisoformat(value)-date.fromisoformat(day)).days <= 30)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, None
    if not future:
        return None, None
    entry = future[0]
    first = date.fromisoformat(day)+timedelta(days=1)
    through = date.fromisoformat(entry)
    if any((first+timedelta(days=offset)).isoformat() not in days
           for offset in range((through-first).days+1)):
        return None, None
    expiry = datetime.combine(datetime.fromisoformat(entry).date(), time(15,30), candidate_store.KST)
    return entry, expiry.astimezone(timezone.utc).isoformat().replace('+00:00','Z')


def refresh_desk(root=None, *, now=None, provider=None, calendar_provider=None):
    root = Path(root) if root is not None else ROOT
    directory = root/'candidate-desk'; directory.mkdir(parents=True, exist_ok=True)
    candidate_store.set_attempt(directory, 'running', now=now)
    try:
        inputs = _acquire(root, now=now, provider=provider)
        code_hash = candidate_store._code_hash()
        audit_path = directory/'runs'/f"{inputs['latest_session']}-{inputs['input_fingerprint'][:16]}-{code_hash[:16]}.json"
        saved = candidate_store._load(audit_path)
        if saved is not None:
            if saved.get('code_hash') != code_hash or saved.get('input_fingerprint') != inputs['input_fingerprint']:
                raise ValueError('candidate_analysis_integrity')
            result = saved['result']
        else:
            result = _detect(inputs)
            candidate_store._save(audit_path, dict(code_hash=code_hash,
                input_fingerprint=inputs['input_fingerprint'], result=result))
        calendar_provider = calendar_provider or KISMarketProvider()
        calendar = None
        try:
            current = candidate_store._clock(now)
            calendar = calendar_provider.fetch_calendar(current.astimezone(candidate_store.KST).date().isoformat(), now=now)
        except Exception:
            pass
        moment = store.timestamp(now); current = candidate_store._clock(moment)
        entry, expiry = _entry(calendar, current)
        reasons = list(result.get('reasons', []))
        if entry is None:
            candidate_store.set_attempt(directory, 'failed', now=moment, error='calendar_unavailable')
            return candidate_store.read_public(directory, now=moment)
        captures = [value['last'] for value in inputs.get('capture_audit',{}).values()]
        source_at = max(captures) if captures else inputs['provenance']['captured_at']
        desk = dict(schema_version=1, policy_version=candidate_store.POLICY,
            state='ready' if result['candidates'] and entry is not None else 'held',
            input_fingerprint=inputs['input_fingerprint'], generated_at=moment,
            latest_session=inputs['latest_session'], entry_session=entry, valid_until=expiry,
            source=dict(provider='KIS', venue='KRX', adjusted_requested=True,
                        captured_at=source_at,
                        historical_vintage_verified=False, corporate_action_adjustment_verified=False),
            candidates=deepcopy(result['candidates']), funnel=deepcopy(result['funnel']),
            evidence=deepcopy(result['evidence']), reasons=list(dict.fromkeys(reasons)),
            approved_exposure=0., live_orders=False)
        if 'model' in result:
            desk['model'] = deepcopy(result['model'])
        candidate_store.publish(directory, desk, inputs, now=moment)
        candidate_store.set_attempt(directory, 'complete', now=moment)
        return candidate_store.read_public(directory, now=moment)
    except Exception:
        candidate_store.set_attempt(directory, 'failed', now=now, error='analysis_unavailable')
        return candidate_store.read_public(directory, now=now)


def _legacy_read(root, *, now=None):
    return legacy.read_status(now=now) if Path(root) == legacy.ROOT else store.read_status(root, now=now)


def read_status(*, now=None):
    result = _legacy_read(ROOT, now=now)
    desk = candidate_store.read_public(ROOT/'candidate-desk', now=now)
    if desk is not None:
        from .candidate_monitor import read_view
        desk['monitoring'] = read_view(ROOT, desk, now=now)
        result = dict(result, candidate_desk=desk)
    elif (ROOT/'candidate-desk'/'attempt.json').exists():
        result = dict(result, candidate_desk_unavailable=True)
    try:
        attempt = candidate_store._load(ROOT/'candidate-desk'/'attempt.json') or {}
        age = candidate_store._clock(now)-candidate_store._clock(attempt['at'])
        if attempt.get('state') == 'running' and timedelta(0) <= age <= timedelta(minutes=20):
            result = dict(result, state='running')
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def scan_once(root=None, *, desk_only=False):
    root = Path(root) if root is not None else ROOT
    lock = FileLock(str(root/'candidate-compose.lock'), thread_local=False)
    try:
        with lock.acquire(timeout=0):
            previous = store.read_status(root) if desk_only else legacy.scan_once(root)
            if previous.get('state') in ('ready','held'):
                desk = refresh_desk(root)
                return dict(previous, candidate_desk=desk) if desk is not None else dict(previous, candidate_desk_unavailable=True)
            return previous
    except Timeout:
        return dict(store.read_status(root), state='running')


def start_scan():
    lock = FileLock(str(ROOT/'candidate-compose.lock'), thread_local=False)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return dict(read_status(), state='running')
    def run():
        try:
            previous = legacy.scan_once(ROOT)
            if previous.get('state') in ('ready','held'):
                refresh_desk(ROOT)
            else:
                candidate_store.set_attempt(ROOT/'candidate-desk', 'failed', error='analysis_unavailable')
        except Exception:
            candidate_store.set_attempt(ROOT/'candidate-desk', 'failed', error='analysis_unavailable')
        finally:
            lock.release()
    candidate_store.set_attempt(ROOT/'candidate-desk', 'running')
    threading.Thread(target=run, name='alpha-candidate-research', daemon=True).start()
    return dict(read_status(), state='running')


def save_desk_evidence(payload, *, now=None):
    return legacy.save_desk_evidence(payload, now=now)
