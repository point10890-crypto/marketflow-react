"""auto_runner — Event-driven Stage 2 (MCP TOP 3) automation.

State machine + gates + circuit breaker + cost tracking for the GraphRAG
TOP 3 workflow. In-process trusted code — bypasses the autonomous_mcp HTTP
mutation gate (which is designed for external callers).

Gates (all must pass to fire — short-circuit on first failure):
  G1. Enabled & not paused
  G2. Market open    — KR regular_session
  G3. Freshness      — scanner last_run_at age < 5min
  G4. New events     — alpha_scanner.run_scanner_alert_check returns
                       >= MIN_NEW_EVENTS new candidates
  G5. Quality        — at least 1 candidate with alpha >= MIN_ALPHA / risk <= MAX_RISK
  G6. Cooldown       — N minutes since last success
  G7. Cost cap       — today's est USD < daily cap
  G8. Circuit closed — not in CIRCUIT_OPEN state (1hr auto-recover)

States:
  IDLE → CHECKING → TRIGGERED → ANALYZING → NOTIFYING → COOLDOWN → IDLE
  Failure: ANALYZING → FAILED
                       ↓
            consecutive++ if ≥3 → CIRCUIT_OPEN(1hr) → auto IDLE

Persistence:
  data/admin_mirofish/auto_runner_state.json   — runtime state + today stats
  data/admin_mirofish/auto_runner_history.jsonl — append-only cycle log

Environment overrides:
  MIROFISH_AUTO_RUNNER_ENABLED=1     (default 1 — auto-start)
  MIROFISH_AUTO_RUNNER_POLL_SECONDS  (default 60)
  MIROFISH_AUTO_RUNNER_COOLDOWN_MIN  (default 15)
  MIROFISH_AUTO_RUNNER_MIN_NEW       (default 3)
  MIROFISH_AUTO_RUNNER_MIN_ALPHA     (default 70)
  MIROFISH_AUTO_RUNNER_MAX_RISK      (default 45)
  MIROFISH_AUTO_RUNNER_DAILY_CAP_USD (default 5.0)
  MIROFISH_AUTO_RUNNER_DRY_RUN=1     (run gates + simulate, but no LLM call)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.mirofish import alpha_scanner, workflow as workflow_svc
from app.utils.atomic_json import write_json_atomic


logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
STATE_DIR = os.path.join(DATA_ROOT, 'admin_mirofish')
STATE_PATH = os.path.join(STATE_DIR, 'auto_runner_state.json')
HISTORY_PATH = os.path.join(STATE_DIR, 'auto_runner_history.jsonl')

try:
    from zoneinfo import ZoneInfo

    KST = ZoneInfo('Asia/Seoul')
except Exception:  # pragma: no cover
    KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Constants / tunables (env-overridable)
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _tunables() -> dict[str, Any]:
    return {
        'enabled': _env_bool('MIROFISH_AUTO_RUNNER_ENABLED', True),
        'poll_seconds': max(15, _env_int('MIROFISH_AUTO_RUNNER_POLL_SECONDS', 60)),
        'cooldown_minutes': max(1, _env_int('MIROFISH_AUTO_RUNNER_COOLDOWN_MIN', 15)),
        'min_new_events': max(1, _env_int('MIROFISH_AUTO_RUNNER_MIN_NEW', 3)),
        'min_alpha': _env_float('MIROFISH_AUTO_RUNNER_MIN_ALPHA', 70.0),
        'max_risk': _env_float('MIROFISH_AUTO_RUNNER_MAX_RISK', 45.0),
        'daily_cap_usd': _env_float('MIROFISH_AUTO_RUNNER_DAILY_CAP_USD', 5.0),
        'monthly_cap_usd': _env_float('MIROFISH_AUTO_RUNNER_MONTHLY_CAP_USD', 50.0),
        'circuit_breaker_failures': max(2, _env_int('MIROFISH_AUTO_RUNNER_CB_FAILS', 3)),
        'circuit_open_minutes': max(5, _env_int('MIROFISH_AUTO_RUNNER_CB_MIN', 60)),
        'est_cost_per_trigger_usd': _env_float('MIROFISH_AUTO_RUNNER_COST_PER_TRIGGER', 0.07),
        'analysis_timeout_seconds': max(60, _env_int('MIROFISH_AUTO_RUNNER_TIMEOUT', 180)),
        'dry_run': _env_bool('MIROFISH_AUTO_RUNNER_DRY_RUN', False),
        'allow_outside_market_hours': _env_bool('MIROFISH_AUTO_RUNNER_ALLOW_OUTSIDE', False),
        'allow_stale_sources': _env_bool('MIROFISH_AUTO_RUNNER_ALLOW_STALE', False),
    }


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

_state_lock = threading.RLock()
_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()


def _default_state() -> dict[str, Any]:
    now = _now_iso()
    return {
        'phase': 'IDLE',
        'paused': False,
        'started_at': now,
        'last_check_at': None,
        'last_check_reason': None,
        'last_trigger_at': None,
        'last_success_at': None,
        'last_failure_at': None,
        'last_workflow_id': None,
        'last_top3_count': 0,
        'consecutive_failures': 0,
        'circuit_opened_at': None,
        'circuit_release_at': None,
        'cooldown_until': None,
        'today': _empty_daily_bucket(),
        'recent_cycles': [],
    }


def _empty_daily_bucket() -> dict[str, Any]:
    return {
        'date_kst': _now_kst().date().isoformat(),
        'checks': 0,
        'triggers': 0,
        'successes': 0,
        'failures': 0,
        'telegram_sent': 0,
        'est_cost_usd': 0.0,
        'skip_reasons': {},
    }


def _read_state() -> dict[str, Any]:
    with _state_lock:
        if not os.path.isfile(STATE_PATH):
            return _default_state()
        try:
            import json
            with open(STATE_PATH, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return _default_state()
            # Daily bucket rollover
            today = _now_kst().date().isoformat()
            bucket = data.get('today') or {}
            if bucket.get('date_kst') != today:
                data['today'] = _empty_daily_bucket()
            return data
        except Exception as exc:
            logger.warning(f'[auto_runner] failed reading state: {exc}')
            return _default_state()


def _write_state(state: dict[str, Any]) -> None:
    with _state_lock:
        os.makedirs(STATE_DIR, exist_ok=True)
        try:
            write_json_atomic(STATE_PATH, state, sort_keys=False)
        except Exception as exc:
            logger.warning(f'[auto_runner] failed writing state: {exc}')


def _append_history(entry: dict[str, Any]) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        import json
        with open(HISTORY_PATH, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as exc:
        logger.debug(f'[auto_runner] history append failed: {exc}')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_kst() -> datetime:
    return datetime.now(KST)


def _iso_to_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API — admin actions
# ---------------------------------------------------------------------------


def get_status() -> dict[str, Any]:
    """Snapshot used by admin dashboard."""
    state = _read_state()
    tuning = _tunables()
    next_eligible = _next_eligible_time(state, tuning)
    return {
        'service': 'mirofish-auto-runner',
        'phase': state.get('phase'),
        'paused': bool(state.get('paused')),
        'enabled': bool(tuning['enabled']),
        'dry_run': bool(tuning['dry_run']),
        'worker_running': bool(_worker_thread and _worker_thread.is_alive()),
        'next_eligible_check_at': next_eligible.isoformat() if next_eligible else None,
        'last_check_at': state.get('last_check_at'),
        'last_check_reason': state.get('last_check_reason'),
        'last_trigger_at': state.get('last_trigger_at'),
        'last_success_at': state.get('last_success_at'),
        'last_failure_at': state.get('last_failure_at'),
        'last_workflow_id': state.get('last_workflow_id'),
        'last_top3_count': state.get('last_top3_count', 0),
        'consecutive_failures': int(state.get('consecutive_failures') or 0),
        'circuit_opened_at': state.get('circuit_opened_at'),
        'circuit_release_at': state.get('circuit_release_at'),
        'cooldown_until': state.get('cooldown_until'),
        'today': state.get('today') or _empty_daily_bucket(),
        'recent_cycles': (state.get('recent_cycles') or [])[-10:],
        'tuning': tuning,
        'checked_at': _now_iso(),
    }


def set_paused(paused: bool) -> dict[str, Any]:
    with _state_lock:
        state = _read_state()
        state['paused'] = bool(paused)
        if paused:
            state['phase'] = 'PAUSED'
        elif state.get('phase') == 'PAUSED':
            state['phase'] = 'IDLE'
        _write_state(state)
    return get_status()


def reset_circuit() -> dict[str, Any]:
    with _state_lock:
        state = _read_state()
        state['consecutive_failures'] = 0
        state['circuit_opened_at'] = None
        state['circuit_release_at'] = None
        if state.get('phase') == 'CIRCUIT_OPEN':
            state['phase'] = 'IDLE'
        _write_state(state)
    return get_status()


def reset_today() -> dict[str, Any]:
    """Manual reset of today's counters (cost cap unblock etc.)."""
    with _state_lock:
        state = _read_state()
        state['today'] = _empty_daily_bucket()
        _write_state(state)
    return get_status()


def force_trigger() -> dict[str, Any]:
    """Manual one-shot bypass of cooldown + new-events gate (still respects market/freshness)."""
    return _execute_cycle(force=True)


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------


def start_worker() -> bool:
    """Spawn the background polling thread if not already running."""
    global _worker_thread
    tuning = _tunables()
    if not tuning['enabled']:
        logger.info('[auto_runner] disabled via env — worker NOT started')
        return False
    with _state_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return True
        _worker_stop.clear()
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name='mirofish-auto-runner',
            daemon=True,
        )
        _worker_thread.start()
        logger.info(f'[auto_runner] worker started (poll={tuning["poll_seconds"]}s, dry_run={tuning["dry_run"]})')
        return True


def stop_worker(wait: bool = False) -> None:
    _worker_stop.set()
    if wait and _worker_thread is not None:
        _worker_thread.join(timeout=10)


def _worker_loop() -> None:
    while not _worker_stop.is_set():
        try:
            _execute_cycle()
        except Exception as exc:
            logger.warning(f'[auto_runner] cycle exception: {type(exc).__name__}: {exc}')
        poll = _tunables()['poll_seconds']
        # Sleep in small slices for responsive shutdown
        for _ in range(int(poll)):
            if _worker_stop.is_set():
                return
            time.sleep(1)


# ---------------------------------------------------------------------------
# Cycle logic
# ---------------------------------------------------------------------------


def _execute_cycle(force: bool = False) -> dict[str, Any]:
    """One iteration: check gates → trigger if all pass → update state."""
    started = time.perf_counter()
    cycle_record: dict[str, Any] = {'started_at': _now_iso(), 'force': force}
    with _state_lock:
        state = _read_state()
        state['today']['checks'] = int(state['today'].get('checks', 0)) + 1
        state['last_check_at'] = _now_iso()
        state['phase'] = 'CHECKING'
        _write_state(state)

    tuning = _tunables()
    gates = _evaluate_gates(force=force, tuning=tuning)
    cycle_record['gates'] = gates

    if not gates['all_pass']:
        reason = gates['failed_reason']
        with _state_lock:
            state = _read_state()
            state['phase'] = state.get('phase') if state.get('phase') in {'COOLDOWN', 'CIRCUIT_OPEN', 'PAUSED'} else 'IDLE'
            state['last_check_reason'] = reason
            skips = state['today'].setdefault('skip_reasons', {})
            skips[reason] = int(skips.get(reason, 0)) + 1
            _trim_recent({'at': _now_iso(), 'outcome': 'skipped', 'reason': reason}, state)
            _write_state(state)
        cycle_record.update({'outcome': 'skipped', 'reason': reason, 'duration_s': round(time.perf_counter() - started, 2)})
        _append_history(cycle_record)
        return {'fired': False, 'reason': reason, 'gates': gates}

    # All gates passed → fire
    return _fire_workflow(tuning, gates, cycle_record, started)


def _fire_workflow(tuning: dict[str, Any], gates: dict[str, Any], cycle_record: dict[str, Any], started: float) -> dict[str, Any]:
    with _state_lock:
        state = _read_state()
        state['phase'] = 'TRIGGERED'
        state['last_trigger_at'] = _now_iso()
        state['today']['triggers'] = int(state['today'].get('triggers', 0)) + 1
        _write_state(state)

    if tuning['dry_run']:
        cycle_record.update({'outcome': 'dry_run', 'duration_s': round(time.perf_counter() - started, 2)})
        _append_history(cycle_record)
        with _state_lock:
            state = _read_state()
            state['phase'] = 'COOLDOWN'
            state['cooldown_until'] = (datetime.now(timezone.utc) + timedelta(minutes=tuning['cooldown_minutes'])).isoformat()
            _trim_recent({'at': _now_iso(), 'outcome': 'dry_run'}, state)
            _write_state(state)
        return {'fired': True, 'dry_run': True}

    # Phase: ANALYZING — call underlying workflow svc directly (in-process trusted)
    with _state_lock:
        state = _read_state()
        state['phase'] = 'ANALYZING'
        _write_state(state)

    try:
        result = workflow_svc.start_workflow_from_scanner_events(
            payload={
                'min_alpha': tuning['min_alpha'],
                'max_risk': tuning['max_risk'],
                'max_events': 5,
                'top_n': 3,
                'agent_count': 5,
                'allow_stale_sources': bool(tuning['allow_stale_sources']),
            },
            async_mode=False,  # blocking — we want to send telegram after completion
            commit_event_state=False,  # commit later only on successful telegram
        )
    except Exception as exc:
        _record_failure(cycle_record, started, f'workflow_error:{type(exc).__name__}:{exc}', tuning)
        return {'fired': True, 'success': False, 'error': str(exc)}

    status = str(result.get('status') or '')
    if status in {'blocked', 'failed'}:
        _record_failure(cycle_record, started, f'workflow_{status}:{result.get("blocked_reason") or result.get("error") or ""}', tuning)
        return {'fired': True, 'success': False, 'workflow': result}

    if status == 'no_new_events':
        # Counted as triggered but no work — return to IDLE (no failure)
        with _state_lock:
            state = _read_state()
            state['phase'] = 'IDLE'
            _trim_recent({'at': _now_iso(), 'outcome': 'no_new_events'}, state)
            _write_state(state)
        cycle_record.update({'outcome': 'no_new_events', 'duration_s': round(time.perf_counter() - started, 2)})
        _append_history(cycle_record)
        return {'fired': True, 'success': True, 'no_new_events': True}

    top3 = result.get('top3') or result.get('analysis_runs') or []
    workflow_id = result.get('id')
    cycle_record['workflow_id'] = workflow_id
    cycle_record['top3_count'] = len(top3)

    # Phase: NOTIFYING — send to channel + AIbain in parallel
    with _state_lock:
        state = _read_state()
        state['phase'] = 'NOTIFYING'
        state['last_workflow_id'] = workflow_id
        state['last_top3_count'] = len(top3)
        _write_state(state)

    message = ''
    try:
        message = workflow_svc.build_workflow_top3_telegram_message(result)
    except Exception as exc:
        logger.warning(f'[auto_runner] build_workflow_top3_telegram_message failed: {exc}')

    telegram_ok = False
    aibain_ok = False
    if message and top3:
        try:
            from app.utils.scheduler import _send_telegram_long
            telegram_ok = bool(_send_telegram_long(message, channel=True))
        except Exception as exc:
            logger.warning(f'[auto_runner] telegram send failed: {exc}')

        # AIbain parallel — failure doesn't break main flow
        try:
            from app.utils.aibain_notify import send_workflow_top3
            aibain_ok = bool(send_workflow_top3(message))
        except Exception as exc:
            logger.debug(f'[auto_runner] aibain send failed: {exc}')

    cycle_record['telegram_ok'] = telegram_ok
    cycle_record['aibain_ok'] = aibain_ok

    if telegram_ok and workflow_id:
        # Commit event state so the same candidates don't trigger again
        try:
            workflow_svc.commit_workflow_event_state(result)
        except Exception as exc:
            logger.warning(f'[auto_runner] commit_workflow_event_state failed: {exc}')

    # Mark success/failure + transition
    if telegram_ok:
        _record_success(cycle_record, started, tuning, top3_count=len(top3))
    else:
        _record_failure(cycle_record, started, 'telegram_send_failed', tuning)

    return {
        'fired': True,
        'success': telegram_ok,
        'workflow_id': workflow_id,
        'top3_count': len(top3),
        'telegram_ok': telegram_ok,
        'aibain_ok': aibain_ok,
    }


def _record_success(cycle_record: dict[str, Any], started: float, tuning: dict[str, Any], *, top3_count: int) -> None:
    duration = round(time.perf_counter() - started, 2)
    cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=tuning['cooldown_minutes'])
    with _state_lock:
        state = _read_state()
        state['phase'] = 'COOLDOWN'
        state['last_success_at'] = _now_iso()
        state['cooldown_until'] = cooldown_until.isoformat()
        state['consecutive_failures'] = 0
        state['today']['successes'] = int(state['today'].get('successes', 0)) + 1
        state['today']['telegram_sent'] = int(state['today'].get('telegram_sent', 0)) + 1
        state['today']['est_cost_usd'] = round(
            float(state['today'].get('est_cost_usd', 0.0)) + float(tuning['est_cost_per_trigger_usd']),
            4,
        )
        _trim_recent({
            'at': _now_iso(),
            'outcome': 'success',
            'top3': top3_count,
            'duration_s': duration,
        }, state)
        _write_state(state)
    cycle_record.update({'outcome': 'success', 'duration_s': duration, 'top3_count': top3_count})
    _append_history(cycle_record)


def _record_failure(cycle_record: dict[str, Any], started: float, reason: str, tuning: dict[str, Any]) -> None:
    duration = round(time.perf_counter() - started, 2)
    cb_threshold = int(tuning['circuit_breaker_failures'])
    cb_minutes = int(tuning['circuit_open_minutes'])
    with _state_lock:
        state = _read_state()
        state['last_failure_at'] = _now_iso()
        state['consecutive_failures'] = int(state.get('consecutive_failures') or 0) + 1
        state['today']['failures'] = int(state['today'].get('failures', 0)) + 1
        if state['consecutive_failures'] >= cb_threshold:
            release = datetime.now(timezone.utc) + timedelta(minutes=cb_minutes)
            state['phase'] = 'CIRCUIT_OPEN'
            state['circuit_opened_at'] = _now_iso()
            state['circuit_release_at'] = release.isoformat()
        else:
            state['phase'] = 'IDLE'
        _trim_recent({
            'at': _now_iso(),
            'outcome': 'failed',
            'reason': reason,
            'duration_s': duration,
        }, state)
        _write_state(state)
    cycle_record.update({'outcome': 'failed', 'reason': reason, 'duration_s': duration})
    _append_history(cycle_record)


def _trim_recent(entry: dict[str, Any], state: dict[str, Any], max_keep: int = 30) -> None:
    cycles = state.get('recent_cycles') if isinstance(state.get('recent_cycles'), list) else []
    cycles.append(entry)
    state['recent_cycles'] = cycles[-max_keep:]


def _next_eligible_time(state: dict[str, Any], tuning: dict[str, Any]) -> datetime | None:
    """Next moment a check could fire (later of cooldown/circuit/poll)."""
    candidates: list[datetime] = []
    cd = _iso_to_dt(state.get('cooldown_until'))
    if cd and cd > datetime.now(timezone.utc):
        candidates.append(cd)
    cb = _iso_to_dt(state.get('circuit_release_at'))
    if cb and cb > datetime.now(timezone.utc) and state.get('phase') == 'CIRCUIT_OPEN':
        candidates.append(cb)
    if not candidates:
        # Default: next poll tick
        candidates.append(datetime.now(timezone.utc) + timedelta(seconds=int(tuning['poll_seconds'])))
    return min(candidates)


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


def _evaluate_gates(*, force: bool, tuning: dict[str, Any]) -> dict[str, Any]:
    """Return {gates: [...], all_pass: bool, failed_reason: str|None}."""
    results: list[dict[str, Any]] = []
    state = _read_state()
    now_utc = datetime.now(timezone.utc)
    now_kst = _now_kst()

    def add(name: str, ok: bool, detail: Any = None) -> None:
        results.append({'name': name, 'ok': bool(ok), 'detail': detail})

    # G1 enabled & not paused
    if not tuning['enabled']:
        add('enabled', False, 'MIROFISH_AUTO_RUNNER_ENABLED=false')
        return _gate_result(results)
    add('enabled', True)
    if state.get('paused'):
        add('not_paused', False, 'paused by admin')
        return _gate_result(results)
    add('not_paused', True)

    # G8 (early) circuit closed
    if state.get('phase') == 'CIRCUIT_OPEN':
        release = _iso_to_dt(state.get('circuit_release_at'))
        if release and release > now_utc:
            add('circuit_closed', False, f'circuit open until {release.isoformat()}')
            return _gate_result(results)
        # Auto-recover
        with _state_lock:
            state2 = _read_state()
            state2['phase'] = 'IDLE'
            state2['consecutive_failures'] = 0
            state2['circuit_opened_at'] = None
            state2['circuit_release_at'] = None
            _write_state(state2)
        state = state2
    add('circuit_closed', True)

    # G2 market open
    is_weekday = now_kst.weekday() < 5
    session_start = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    session_end = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
    is_regular = is_weekday and session_start <= now_kst <= session_end
    if not (is_regular or tuning['allow_outside_market_hours'] or force):
        add('market_open', False, f'session phase not regular (now_kst={now_kst.isoformat()})')
        return _gate_result(results)
    add('market_open', True, 'regular_session' if is_regular else 'forced/allowed_outside')

    # G3 scanner freshness (last_run age < 5 min)
    schedule = alpha_scanner.get_scanner_schedule_status(now=now_kst)
    last_run_at = _iso_to_dt(schedule.get('last_run_at'))
    if not last_run_at:
        add('scanner_freshness', False, 'no scanner runs yet')
        return _gate_result(results)
    age = (now_utc - last_run_at.astimezone(timezone.utc)).total_seconds()
    if age > 300:
        add('scanner_freshness', False, f'scanner stale ({age:.0f}s)')
        return _gate_result(results)
    add('scanner_freshness', True, f'{age:.0f}s ago')

    # G6 cooldown (unless force)
    if not force:
        cd = _iso_to_dt(state.get('cooldown_until'))
        if cd and cd > now_utc:
            remaining = (cd - now_utc).total_seconds()
            add('cooldown_clear', False, f'cooldown {int(remaining)}s remaining')
            return _gate_result(results)
    add('cooldown_clear', True)

    # G7 cost cap
    today_cost = float((state.get('today') or {}).get('est_cost_usd') or 0.0)
    daily_cap = float(tuning['daily_cap_usd'])
    if today_cost + float(tuning['est_cost_per_trigger_usd']) > daily_cap:
        add('cost_cap', False, f'daily ${today_cost:.2f} + ${tuning["est_cost_per_trigger_usd"]:.2f} > cap ${daily_cap:.2f}')
        return _gate_result(results)
    add('cost_cap', True, f'today ${today_cost:.2f} / cap ${daily_cap:.2f}')

    # G4 + G5 new events + quality (single scanner_alert_check call serves both)
    try:
        alert = alpha_scanner.run_scanner_alert_check(
            {},
            min_alpha=float(tuning['min_alpha']),
            max_risk=float(tuning['max_risk']),
            max_events=8,
            commit_state=False,
            block_on_stale=not bool(tuning['allow_stale_sources']),
        )
    except Exception as exc:
        add('new_events', False, f'scanner_alert_check error: {exc}')
        return _gate_result(results)

    events = alert.get('events') if isinstance(alert.get('events'), list) else []
    if alert.get('alert_blocked'):
        add('new_events', False, f'alert_blocked: {alert.get("blocked_reason")}')
        return _gate_result(results)
    min_new = int(tuning['min_new_events'])
    if len(events) < min_new and not force:
        add('new_events', False, f'{len(events)} new < required {min_new}')
        return _gate_result(results)
    add('new_events', True, f'{len(events)} new candidate(s)')

    # Quality gate — at least 1 event passes thresholds (run_scanner_alert_check already filters by min_alpha/max_risk)
    has_quality = any(
        (event.get('candidate') or {}).get('alpha_score') is not None
        for event in events
    )
    if not has_quality and not force:
        add('quality', False, 'no candidates with alpha/risk meta')
        return _gate_result(results)
    add('quality', True, 'thresholds met')

    return _gate_result(results)


def _gate_result(results: list[dict[str, Any]]) -> dict[str, Any]:
    all_pass = all(item['ok'] for item in results)
    failed = next((item for item in results if not item['ok']), None)
    return {
        'all_pass': all_pass,
        'failed_reason': f"{failed['name']}: {failed.get('detail')}" if failed else None,
        'gates': results,
    }
