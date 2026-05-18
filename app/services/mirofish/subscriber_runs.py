"""AI Brain subscriber run creation policy for MiroFish GraphRAG runs."""

from __future__ import annotations

import os
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.mirofish import store
from app.utils.atomic_json import write_json_atomic

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - fallback for unusual runtimes
    ZoneInfo = None  # type: ignore


STATE_ROOT = os.path.join(store.REPO_ROOT, 'data', 'admin_mirofish', 'subscriber_runs')
STATE_FILE = os.path.join(STATE_ROOT, 'aibain_run_usage.json')

ACTIVE_STATUSES = {'queued', 'pending', 'running'}
TERMINAL_BAD_STATUSES = {'failed', 'error', 'api_error', 'cancelled'}

_lock = threading.Lock()


class AIBainRunLimitError(Exception):
    """Raised when an AI Brain subscriber exceeds a run creation policy."""

    def __init__(self, message: str, policy: dict[str, Any], status_code: int = 429):
        super().__init__(message)
        self.policy = policy
        self.status_code = status_code


def create_aibain_run_for_user(
    payload: dict[str, Any] | None,
    *,
    user_id: int | str | None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """Create or reuse a run for an AI Brain subscriber.

    Subscriber-created runs are always background runs. That keeps the Flask
    worker responsive and lets us enforce a small concurrent-run gate.
    """

    raw_payload = dict(payload or {})
    clean = _clean_request(raw_payload)
    user_key = _user_key(user_id, user_email)
    now = _utc_now()
    today = _kst_date(now)
    config = _policy_config()

    with _lock:
        state = _read_state()
        user_state = _user_state(state, user_key, user_id, user_email)
        _prune_user_state(user_state, now)

        cached_run = _find_cached_run(user_state, clean, now, config['cache_minutes'])
        if cached_run is not None:
            active_ids = _active_run_ids(user_state)
            used_today = _used_today(user_state, today)
            _write_state(state)
            return _with_policy(
                cached_run,
                config=config,
                used_today=used_today,
                active_count=len(active_ids),
                reused=True,
                message='recent_same_run_reused',
            )

        active_ids = _active_run_ids(user_state)
        used_today = _used_today(user_state, today)
        if used_today >= config['daily_limit']:
            policy = _policy_payload(
                config=config,
                used_today=used_today,
                active_count=len(active_ids),
                reused=False,
                message='daily_limit_exceeded',
            )
            raise AIBainRunLimitError(
                f"AI Brain daily run limit exceeded ({used_today}/{config['daily_limit']}).",
                policy,
            )

        if len(active_ids) >= config['concurrent_limit']:
            policy = _policy_payload(
                config=config,
                used_today=used_today,
                active_count=len(active_ids),
                reused=False,
                message='concurrent_limit_exceeded',
            )
            raise AIBainRunLimitError(
                f"AI Brain concurrent run limit exceeded ({len(active_ids)}/{config['concurrent_limit']}).",
                policy,
            )

        run_payload = dict(raw_payload)
        run_payload.update({
            'target': clean['target'],
            'agent_count': clean['agent_count'],
            'mode': clean['mode'],
            'async': True,
        })
        run = store.create_run(run_payload)

        run_id = str(run.get('id') or '')
        _record_created_run(user_state, clean, run_id, now, today)
        active_ids = _active_run_ids(user_state)
        used_today = _used_today(user_state, today)
        _write_state(state)

        return _with_policy(
            run,
            config=config,
            used_today=used_today,
            active_count=len(active_ids),
            reused=False,
            message='created',
        )


def get_aibain_run_policy_snapshot(
    *,
    user_id: int | str | None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """Return the current subscriber policy/usage snapshot."""

    user_key = _user_key(user_id, user_email)
    now = _utc_now()
    today = _kst_date(now)
    config = _policy_config()
    with _lock:
        state = _read_state()
        user_state = _user_state(state, user_key, user_id, user_email)
        _prune_user_state(user_state, now)
        active_ids = _active_run_ids(user_state)
        used_today = _used_today(user_state, today)
        _write_state(state)
    return _policy_payload(
        config=config,
        used_today=used_today,
        active_count=len(active_ids),
        reused=False,
        message='snapshot',
    )


def _clean_request(payload: dict[str, Any]) -> dict[str, Any]:
    target = store._clean_target(payload.get('target'))  # same validation as the core run path
    agent_count = store._clean_agent_count(payload.get('agent_count'))
    mode = store._clean_mode(payload.get('mode'))
    return {
        'target': target,
        'target_key': _target_key(target),
        'agent_count': agent_count,
        'mode': mode,
    }


def _policy_config() -> dict[str, int]:
    return {
        'daily_limit': _env_int('MIROFISH_AIBAIN_RUN_DAILY_LIMIT', 10, 1, 100),
        'concurrent_limit': _env_int('MIROFISH_AIBAIN_RUN_CONCURRENT_LIMIT', 1, 1, 10),
        'cache_minutes': _env_int('MIROFISH_AIBAIN_RUN_CACHE_MINUTES', 30, 0, 1440),
    }


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _read_state() -> dict[str, Any]:
    if not os.path.isfile(STATE_FILE):
        return {'schema_version': 1, 'users': {}, 'updated_at': _utc_now().isoformat()}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = f.read().strip()
        if not data:
            raise ValueError('empty state')
        state = json.loads(data)
    except Exception:
        return {'schema_version': 1, 'users': {}, 'updated_at': _utc_now().isoformat()}
    if not isinstance(state, dict):
        return {'schema_version': 1, 'users': {}, 'updated_at': _utc_now().isoformat()}
    state.setdefault('schema_version', 1)
    state.setdefault('users', {})
    return state


def _write_state(state: dict[str, Any]) -> None:
    os.makedirs(STATE_ROOT, exist_ok=True)
    state['updated_at'] = _utc_now().isoformat()
    write_json_atomic(STATE_FILE, state, sort_keys=True)


def _user_state(
    state: dict[str, Any],
    user_key: str,
    user_id: int | str | None,
    user_email: str | None,
) -> dict[str, Any]:
    users = state.setdefault('users', {})
    item = users.setdefault(user_key, {})
    item.setdefault('user_id', None if user_id is None else str(user_id))
    item.setdefault('user_email', (user_email or '').strip().lower())
    item.setdefault('daily', {})
    item.setdefault('recent', [])
    item.setdefault('active_run_ids', [])
    return item


def _record_created_run(
    user_state: dict[str, Any],
    clean: dict[str, Any],
    run_id: str,
    now: datetime,
    today: str,
) -> None:
    day = user_state.setdefault('daily', {}).setdefault(today, {'created': 0, 'run_ids': []})
    run_ids = day.setdefault('run_ids', [])
    if run_id and run_id not in run_ids:
        run_ids.append(run_id)
    day['created'] = len(run_ids)

    active_ids = user_state.setdefault('active_run_ids', [])
    if run_id and run_id not in active_ids:
        active_ids.append(run_id)

    user_state.setdefault('recent', []).append({
        'run_id': run_id,
        'target_key': clean['target_key'],
        'target': clean['target'],
        'agent_count': clean['agent_count'],
        'mode': clean['mode'],
        'created_at': now.isoformat(),
        'date_kst': today,
    })


def _find_cached_run(
    user_state: dict[str, Any],
    clean: dict[str, Any],
    now: datetime,
    cache_minutes: int,
) -> dict[str, Any] | None:
    if cache_minutes <= 0:
        return None
    cutoff = now - timedelta(minutes=cache_minutes)
    recent = user_state.get('recent') or []
    for entry in reversed(recent):
        if not isinstance(entry, dict):
            continue
        if entry.get('target_key') != clean['target_key']:
            continue
        if int(entry.get('agent_count') or 0) != clean['agent_count']:
            continue
        if str(entry.get('mode') or '') != clean['mode']:
            continue
        created_at = _parse_dt(entry.get('created_at'))
        if created_at is None or created_at < cutoff:
            continue
        run_id = str(entry.get('run_id') or '')
        if not run_id:
            continue
        run = store.read_run(run_id)
        if not run:
            continue
        if str(run.get('status') or '').lower() in TERMINAL_BAD_STATUSES:
            continue
        return run
    return None


def _active_run_ids(user_state: dict[str, Any]) -> list[str]:
    active: list[str] = []
    for run_id in list(user_state.get('active_run_ids') or []):
        safe_id = str(run_id or '')
        if not safe_id:
            continue
        try:
            run = store.read_run(safe_id)
        except ValueError:
            continue
        if run and str(run.get('status') or '').lower() in ACTIVE_STATUSES:
            active.append(safe_id)
    user_state['active_run_ids'] = active
    return active


def _used_today(user_state: dict[str, Any], today: str) -> int:
    day = (user_state.get('daily') or {}).get(today) or {}
    run_ids = day.get('run_ids')
    if isinstance(run_ids, list):
        return len([item for item in run_ids if item])
    try:
        return int(day.get('created') or 0)
    except (TypeError, ValueError):
        return 0


def _prune_user_state(user_state: dict[str, Any], now: datetime) -> None:
    cutoff = now - timedelta(days=14)
    daily = user_state.get('daily') or {}
    for date_key in list(daily.keys()):
        try:
            date_dt = datetime.strptime(date_key, '%Y-%m-%d').replace(tzinfo=_kst_tz())
        except (TypeError, ValueError):
            del daily[date_key]
            continue
        if date_dt < cutoff.astimezone(_kst_tz()):
            del daily[date_key]
    user_state['daily'] = daily

    recent_cutoff = now - timedelta(days=7)
    user_state['recent'] = [
        entry for entry in (user_state.get('recent') or [])
        if isinstance(entry, dict)
        and (_parse_dt(entry.get('created_at')) or datetime.min.replace(tzinfo=timezone.utc)) >= recent_cutoff
    ]
    _active_run_ids(user_state)


def _with_policy(
    run: dict[str, Any],
    *,
    config: dict[str, int],
    used_today: int,
    active_count: int,
    reused: bool,
    message: str,
) -> dict[str, Any]:
    result = dict(run)
    result['subscriber_policy'] = _policy_payload(
        config=config,
        used_today=used_today,
        active_count=active_count,
        reused=reused,
        message=message,
    )
    return result


def _policy_payload(
    *,
    config: dict[str, int],
    used_today: int,
    active_count: int,
    reused: bool,
    message: str,
) -> dict[str, Any]:
    return {
        'role': 'aibain',
        'daily_limit': config['daily_limit'],
        'used_today': used_today,
        'remaining_today': max(0, config['daily_limit'] - used_today),
        'concurrent_limit': config['concurrent_limit'],
        'active_count': active_count,
        'cache_minutes': config['cache_minutes'],
        'reused_cached_run': bool(reused),
        'message': message,
        'date_kst': _kst_date(_utc_now()),
    }


def _target_key(target: str) -> str:
    return re.sub(r'\s+', ' ', str(target or '').strip().lower())


def _user_key(user_id: int | str | None, user_email: str | None) -> str:
    if user_id not in (None, ''):
        return f'id:{user_id}'
    email = (user_email or '').strip().lower()
    if email:
        return f'email:{email}'
    return 'anonymous'


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace('Z', '+00:00')
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _kst_tz():
    if ZoneInfo is not None:
        return ZoneInfo('Asia/Seoul')
    return timezone(timedelta(hours=9))


def _kst_date(now: datetime) -> str:
    return now.astimezone(_kst_tz()).date().isoformat()
