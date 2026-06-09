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
        'min_top_score': _env_float('MIROFISH_AUTO_RUNNER_MIN_TOP_SCORE', 50.0),
        # 마지막 success 후 N시간 지나면 dedup 우회 자동 force (0 = 비활성).
        # 쿨다운 + 비용캡은 여전히 적용되므로 폭주 방지.
        'force_after_hours': _env_int('MIROFISH_AUTO_RUNNER_FORCE_AFTER_HOURS', 4),
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
    """One iteration: check gates → trigger if all pass → update state.

    Auto-force: 마지막 success 후 force_after_hours 경과 시 (또는 success 자체가
    없을 시) dedup 우회 force=True 활성화. 쿨다운/circuit/cost cap 은 그대로 적용.
    """
    started = time.perf_counter()
    cycle_record: dict[str, Any] = {'started_at': _now_iso(), 'force': force}
    with _state_lock:
        state = _read_state()
        state['today']['checks'] = int(state['today'].get('checks', 0)) + 1
        state['last_check_at'] = _now_iso()
        state['phase'] = 'CHECKING'
        _write_state(state)

    tuning = _tunables()

    # === auto-force decision (dedup fallback) ============================
    if not force:
        force_after_hours = int(tuning.get('force_after_hours') or 0)
        if force_after_hours > 0:
            current = _read_state()
            # 쿨다운/서킷/일시정지 중에는 auto-force 적용 X (다른 게이트에서 처리)
            cd_until = _iso_to_dt(current.get('cooldown_until'))
            in_cooldown = cd_until is not None and cd_until > datetime.now(timezone.utc)
            blocked_phase = current.get('phase') in {'CIRCUIT_OPEN', 'PAUSED'}
            if not in_cooldown and not blocked_phase:
                last_success = _iso_to_dt(current.get('last_success_at'))
                if last_success is None:
                    force = True
                    cycle_record['auto_forced'] = 'no_prior_success'
                else:
                    age_hours = (datetime.now(timezone.utc) - last_success).total_seconds() / 3600.0
                    if age_hours >= force_after_hours:
                        force = True
                        cycle_record['auto_forced'] = f'{age_hours:.1f}h_since_last_success'
    # ====================================================================

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
    return _fire_workflow(tuning, gates, cycle_record, started, force=force)


def _fire_workflow(tuning: dict[str, Any], gates: dict[str, Any], cycle_record: dict[str, Any], started: float, *, force: bool = False) -> dict[str, Any]:
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
        # force=True → workflow에 force 플래그 전달해서 dedup 우회 (관리자 강제 트리거 경로)
        # 일반 폴링은 force=False → workflow가 자체 event_state로 dedup
        result = workflow_svc.start_workflow_from_scanner_events(
            payload={
                'min_alpha': tuning['min_alpha'],
                'max_risk': tuning['max_risk'],
                'max_events': 5,
                'top_n': 3,
                'agent_count': 5,
                'allow_stale_sources': bool(tuning['allow_stale_sources']),
                'force': bool(force),
            },
            async_mode=False,
            commit_event_state=False,
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

    should_notify, notify_reason = workflow_svc.should_send_workflow_top3(
        result,
        min_top_score=tuning['min_top_score'],
    )
    cycle_record['top3_quality_gate'] = {
        'ok': should_notify,
        'reason': notify_reason,
        'min_top_score': tuning['min_top_score'],
    }

    if not should_notify:
        if workflow_id:
            try:
                workflow_svc.commit_workflow_event_state(result)
            except Exception as exc:
                logger.warning(f'[auto_runner] commit low-quality workflow state failed: {exc}')
        _record_quality_hold(cycle_record, started, notify_reason, tuning, top3_count=len(top3))
        return {
            'fired': True,
            'success': True,
            'workflow_id': workflow_id,
            'top3_count': len(top3),
            'telegram_ok': False,
            'quality_hold': True,
            'quality_reason': notify_reason,
        }

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
            # AI Brain 알파 스캐너 TOP 3 메세지 — 개인봇만, 채널 발송 금지
            # (사용자 요청: t.me/+gC5JgpGLsPJhZWJl 채널에는 알파 스캐너 메세지 보내지 않음)
            from app.utils.scheduler import _send_telegram_long
            telegram_ok = bool(_send_telegram_long(message, channel=False))
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

        # Deep enrich — TOP 3 각 종목에 대해 뉴스/공시/네이버 메타 수집해서
        # follow-up 메시지로 발송 (메인 텔레그램 메시지는 그대로, 추가 보강만)
        try:
            enrich_msg = _build_deep_enrich_message(top3)
            if enrich_msg:
                try:
                    # Deep enrich follow-up 메시지 — 개인봇만, 채널 발송 금지 (위와 동일 정책)
                    from app.utils.scheduler import _send_telegram_long
                    deep_ok = bool(_send_telegram_long(enrich_msg, channel=False))
                    cycle_record['deep_enrich_ok'] = deep_ok
                except Exception as exc:
                    logger.debug(f'[auto_runner] deep enrich telegram failed: {exc}')
                    cycle_record['deep_enrich_ok'] = False
        except Exception as exc:
            logger.debug(f'[auto_runner] deep enrich build failed: {exc}')

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


def _record_quality_hold(
    cycle_record: dict[str, Any],
    started: float,
    reason: str,
    tuning: dict[str, Any],
    *,
    top3_count: int,
) -> None:
    duration = round(time.perf_counter() - started, 2)
    cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=tuning['cooldown_minutes'])
    with _state_lock:
        state = _read_state()
        state['phase'] = 'COOLDOWN'
        state['last_check_reason'] = f'top3_quality_hold:{reason}'
        state['last_workflow_id'] = cycle_record.get('workflow_id')
        state['last_top3_count'] = top3_count
        state['cooldown_until'] = cooldown_until.isoformat()
        state['consecutive_failures'] = 0
        state['today']['successes'] = int(state['today'].get('successes', 0)) + 1
        skips = state['today'].setdefault('skip_reasons', {})
        skips['top3_quality_hold'] = int(skips.get('top3_quality_hold') or 0) + 1
        _trim_recent({
            'at': _now_iso(),
            'outcome': 'quality_hold',
            'reason': reason,
            'top3': top3_count,
            'duration_s': duration,
        }, state)
        _write_state(state)
    cycle_record.update({
        'outcome': 'quality_hold',
        'reason': reason,
        'duration_s': duration,
        'top3_count': top3_count,
    })
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


def _scanner_freshness_max_age_seconds(tuning: dict[str, Any]) -> int:
    """Allowed scanner/monitor freshness age for event-driven automation."""
    poll_seconds = max(15, int(tuning.get('poll_seconds') or 60))
    monitor_minutes = max(1, _env_int('ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES', 5))
    return max(300, poll_seconds * 2 + 30, monitor_minutes * 60 * 2 + 60)


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

    # G3 scanner freshness.
    # If source files are unchanged, the realtime scanner intentionally skips a
    # new run. A fresh monitor heartbeat with fresh source status is enough.
    schedule = alpha_scanner.get_scanner_schedule_status(now=now_kst)
    last_run_at = _iso_to_dt(schedule.get('last_run_at'))
    source_freshness = str(schedule.get('freshness_status') or '').lower()
    max_scanner_age = _scanner_freshness_max_age_seconds(tuning)
    if last_run_at:
        age = (now_utc - last_run_at.astimezone(timezone.utc)).total_seconds()
        if age <= max_scanner_age:
            add('scanner_freshness', True, f'run {age:.0f}s ago')
        else:
            monitor = alpha_scanner.read_scanner_monitor_state()
            monitor_at = _iso_to_dt(monitor.get('last_checked_at'))
            monitor_age = (now_utc - monitor_at.astimezone(timezone.utc)).total_seconds() if monitor_at else None
            if (
                monitor_age is not None
                and monitor_age <= max_scanner_age
                and source_freshness not in {'stale', 'missing', 'partial', 'unknown'}
            ):
                add(
                    'scanner_freshness',
                    True,
                    f'monitor {monitor_age:.0f}s ago; latest run {age:.0f}s ago; source {source_freshness or "fresh"}',
                )
            else:
                detail = f'scanner stale ({age:.0f}s)'
                if source_freshness:
                    detail += f', source {source_freshness}'
                add('scanner_freshness', False, detail)
                return _gate_result(results)
    else:
        monitor = alpha_scanner.read_scanner_monitor_state()
        monitor_at = _iso_to_dt(monitor.get('last_checked_at'))
        monitor_age = (now_utc - monitor_at.astimezone(timezone.utc)).total_seconds() if monitor_at else None
        if (
            monitor_age is not None
            and monitor_age <= max_scanner_age
            and source_freshness not in {'stale', 'missing', 'partial', 'unknown'}
        ):
            add('scanner_freshness', True, f'monitor {monitor_age:.0f}s ago; no persisted run yet')
        else:
            add('scanner_freshness', False, 'no scanner runs yet')
            return _gate_result(results)

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
    # 중요: workflow의 자체 event_state 와 동일한 경로 사용 — 아니면 게이트가 새 이벤트를 본다고
    # 판정해도 workflow 가 'no_new_events' 반환할 수 있음 (이중 dedup 미스매치)
    try:
        from app.services.mirofish.workflow import _event_state_path as _workflow_state_path
        alert = alpha_scanner.run_scanner_alert_check(
            {},
            state_path=_workflow_state_path(),
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


def _build_deep_enrich_message(top3: list[dict[str, Any]]) -> str:
    """TOP 3 각 종목에 대해 뉴스(perplexity)/네이버 메타/DART 공시 1줄씩 보강.

    실패해도 메인 흐름 영향 X — best-effort. 빈 결과 시 빈 문자열 반환.
    """
    if not top3:
        return ''
    lines: list[str] = ['📰 <b>TOP 3 심층 컨텍스트</b>', '']
    has_any_data = False

    for idx, item in enumerate(top3[:3], start=1):
        candidate = item.get('candidate') if isinstance(item.get('candidate'), dict) else {}
        symbol = str(item.get('symbol') or candidate.get('symbol') or '')
        name = str(item.get('target') or candidate.get('display_name') or candidate.get('name') or symbol)
        if not symbol:
            continue

        block: list[str] = [f'#{idx} <b>{name}</b> ({symbol})']

        # 1) 네이버 금융 메타 (외국인비, PER) — best effort
        try:
            naver = _scrape_naver_finance_lite(symbol)
            if naver and not naver.get('error'):
                meta_bits = []
                if naver.get('foreign_ratio'):
                    meta_bits.append(f'외인 {naver["foreign_ratio"]}%')
                if naver.get('per'):
                    meta_bits.append(f'PER {naver["per"]}')
                if naver.get('market_cap'):
                    meta_bits.append(f'시총 {naver["market_cap"]}')
                if meta_bits:
                    block.append('· ' + ' / '.join(meta_bits))
        except Exception as exc:
            logger.debug(f'[deep_enrich] naver scrape failed {symbol}: {exc}')

        # 2) Perplexity 뉴스 (호재 키워드) — best effort
        try:
            news = _perplexity_news_brief(f'{name} 호재 또는 악재 관련 최신 뉴스')
            if news:
                block.append(f'· 뉴스: {news[:140]}')
                has_any_data = True
        except Exception as exc:
            logger.debug(f'[deep_enrich] perplexity failed {symbol}: {exc}')

        # 3) DART 공시 (캐시된 호재 있으면)
        try:
            from engine.dart_deep_pipeline import get_cached_result
            dart = get_cached_result(symbol)
            if isinstance(dart, dict):
                pos = (dart.get('positive_disclosures') or [])
                if pos:
                    block.append(f'· DART 호재: {len(pos)}건')
                    has_any_data = True
        except Exception as exc:
            logger.debug(f'[deep_enrich] dart failed {symbol}: {exc}')

        if len(block) > 1:
            lines.append('\n'.join(block))
            lines.append('')

    if not has_any_data:
        return ''
    lines.append('🤖 <i>auto_runner deep enrich — MCP 도구 자동 호출 결과</i>')
    return '\n'.join(lines).strip()


def _scrape_naver_finance_lite(symbol: str) -> dict[str, Any]:
    """네이버 금융 종목 페이지 핵심 메타 (외인비/PER/시총) 가벼운 추출."""
    import re
    import requests as _req
    try:
        r = _req.get(
            f'https://finance.naver.com/item/main.naver?code={symbol}',
            headers={'User-Agent': 'Mozilla/5.0 MiroFish/1.0'},
            timeout=8,
        )
        if r.status_code != 200:
            return {'error': f'HTTP {r.status_code}'}
        html = r.text
        def find(p: str) -> str:
            m = re.search(p, html)
            return m.group(1).strip() if m else ''
        return {
            'per': find(r'<em id="_per">([^<]+)</em>'),
            'eps': find(r'<em id="_eps">([^<]+)</em>'),
            'foreign_ratio': find(r'외국인소진율[\s\S]*?<em[^>]*>([0-9\.]+)</em>'),
            'market_cap': find(r'시가총액[^<]*</span>[\s\S]*?<em[^>]*>([^<]+)</em>'),
        }
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def _perplexity_news_brief(query: str) -> str | None:
    """Perplexity 단일 짧은 한국어 답변 (실패 시 None)."""
    import requests as _req
    api_key = os.getenv('PERPLEXITY_API_KEY')
    if not api_key:
        return None
    try:
        resp = _req.post(
            'https://api.perplexity.ai/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': os.getenv('PERPLEXITY_MODEL', 'sonar'),
                'messages': [
                    {'role': 'system', 'content': '한국어로 1문장만. 최신 뉴스/시장 영향만.'},
                    {'role': 'user', 'content': query},
                ],
                'max_tokens': 200,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        text = ((data.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
        return text.strip() or None
    except Exception:
        return None


def _gate_result(results: list[dict[str, Any]]) -> dict[str, Any]:
    all_pass = all(item['ok'] for item in results)
    failed = next((item for item in results if not item['ok']), None)
    return {
        'all_pass': all_pass,
        'failed_reason': f"{failed['name']}: {failed.get('detail')}" if failed else None,
        'gates': results,
    }


# ---------------------------------------------------------------------------
# LLM 임계값 추천 (Open-Claude 식 자가 개선 — 최소 도입)
# ---------------------------------------------------------------------------


def recommend_thresholds(window_days: int = 14) -> dict[str, Any]:
    """최근 outcomes 를 분석해 Gemini 가 새 임계값을 제안.

    결과는 _state.json 의 last_recommendation 에도 저장됨 (admin 대시보드 표시용).
    실제 적용은 env var 수정 + Flask 재시작 또는 별도 apply 액션 필요 — 자동 적용 X.
    """
    import json
    import os
    import re

    from app.services.mirofish.pipeline_overview import get_outcomes_board

    started = time.perf_counter()
    board = get_outcomes_board(days=max(3, min(int(window_days or 14), 60)), limit=200)
    summary = board.get('summary') or {}
    current = _tunables()

    summary_lines = [
        f"- Hit rate: {summary.get('hit_rate_pct')}% (target ≥55%)",
        f"- Avg forward return: {summary.get('avg_forward_return_pct')}% (target ≥1.5%)",
        f"- False positive: {summary.get('false_positive_pct')}% (target <20%)",
        f"- Evaluated sample: {summary.get('evaluated_count', 0)} (pending: {summary.get('pending_count', 0)})",
        f"- Stopped (loss-cut): {summary.get('stopped_count', 0)}",
    ]

    prompt = (
        "당신은 한국 주식 자동 검출 시스템의 임계값을 튜닝하는 분석가입니다.\n\n"
        f"=== 지난 {window_days}일 성능 ===\n"
        + '\n'.join(summary_lines)
        + "\n\n=== 현재 임계값 ===\n"
        + f"- min_alpha (알파 최소): {current['min_alpha']}\n"
        + f"- max_risk (리스크 최대): {current['max_risk']}\n"
        + f"- min_new_events (신규 후보 최소): {current['min_new_events']}\n"
        + f"- cooldown_minutes (성공 후 쿨다운): {current['cooldown_minutes']}\n"
        + f"- force_after_hours (dedup 우회 주기): {current.get('force_after_hours', 0)}\n\n"
        + "=== 지침 ===\n"
        + "1. hit rate 가 낮으면 → min_alpha 올리거나 max_risk 낮춰 정밀도 ↑\n"
        + "2. 발사 빈도가 너무 낮으면 → min_alpha/min_new_events 낮춰 재현율 ↑\n"
        + "3. false positive 가 높으면 → max_risk 낮추거나 cooldown 길게\n"
        + "4. 표본이 너무 작으면 (<5) → 보수적 조정만\n"
        + "5. 한 번에 너무 큰 변경 금지 (±10 이내)\n\n"
        + "=== 응답 형식 (반드시 valid JSON 만, 다른 텍스트 없이) ===\n"
        + '{\n'
        + '  "min_alpha": <float 40-80>,\n'
        + '  "max_risk": <float 30-80>,\n'
        + '  "min_new_events": <int 1-5>,\n'
        + '  "cooldown_minutes": <int 5-60>,\n'
        + '  "force_after_hours": <int 1-24>,\n'
        + '  "reasoning": "<2-3 문장 한국어 근거>",\n'
        + '  "confidence": "<low|medium|high>"\n'
        + '}'
    )

    try:
        from app.services.mirofish.llm_client import generate_text

        raw = generate_text(
            prompt,
            model_env='MIROFISH_TUNER_MODEL',
            temperature=0.3,
            max_tokens=2048,
        )
        raw = (raw or '').strip()
        if not raw:
            return {
                'ok': False,
                'error': 'LLM 응답 없음 (API 키 미설정 또는 호출 실패 — 로그 확인)',
                'current_thresholds': _current_thresholds_summary(current),
                'recent_kpi': summary,
            }
    except Exception as exc:
        return {
            'ok': False,
            'error': f'LLM call failed: {type(exc).__name__}: {exc}',
            'current_thresholds': _current_thresholds_summary(current),
            'recent_kpi': summary,
        }

    # Extract JSON object from response
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        return {
            'ok': False,
            'error': 'LLM 응답에서 JSON 추출 실패',
            'raw_preview': raw[:500],
            'current_thresholds': _current_thresholds_summary(current),
            'recent_kpi': summary,
        }
    try:
        rec = json.loads(match.group(0))
    except Exception as exc:
        return {
            'ok': False,
            'error': f'JSON parse 실패: {exc}',
            'raw_preview': raw[:500],
            'current_thresholds': _current_thresholds_summary(current),
            'recent_kpi': summary,
        }

    # Bounds clamp (LLM 환각 방지)
    rec = _clamp_recommendation(rec)

    # Diff
    diff = _diff_thresholds(current, rec)

    result = {
        'ok': True,
        'generated_at': _now_iso(),
        'window_days': window_days,
        'current_thresholds': _current_thresholds_summary(current),
        'recent_kpi': summary,
        'recommendation': rec,
        'diff': diff,
        'duration_s': round(time.perf_counter() - started, 2),
        'apply_note': (
            'env var (.env) 에 반영하고 Flask 재시작 시 영구 적용. '
            'POST /auto-runner/apply-tune 으로 in-memory 적용도 가능 (재시작 시 env 우선).'
        ),
    }

    # 상태 파일에도 마지막 추천 기록 (감사 / 대시보드)
    try:
        with _state_lock:
            state = _read_state()
            state['last_recommendation'] = result
            _write_state(state)
    except Exception as exc:
        logger.debug(f'[auto_runner] persist recommendation failed: {exc}')

    return result


def _current_thresholds_summary(tuning: dict[str, Any]) -> dict[str, Any]:
    return {
        'min_alpha': tuning.get('min_alpha'),
        'max_risk': tuning.get('max_risk'),
        'min_new_events': tuning.get('min_new_events'),
        'cooldown_minutes': tuning.get('cooldown_minutes'),
        'force_after_hours': tuning.get('force_after_hours'),
    }


def _clamp_recommendation(rec: dict[str, Any]) -> dict[str, Any]:
    """LLM 추천을 안전 범위로 clamp."""
    def _f(v, lo, hi, default):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, x))

    def _i(v, lo, hi, default):
        try:
            x = int(v)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, x))

    return {
        'min_alpha': _f(rec.get('min_alpha'), 40, 80, 60),
        'max_risk': _f(rec.get('max_risk'), 30, 80, 50),
        'min_new_events': _i(rec.get('min_new_events'), 1, 5, 2),
        'cooldown_minutes': _i(rec.get('cooldown_minutes'), 5, 60, 15),
        'force_after_hours': _i(rec.get('force_after_hours'), 1, 24, 4),
        'reasoning': str(rec.get('reasoning') or '')[:600],
        'confidence': str(rec.get('confidence') or 'medium').lower(),
    }


def _diff_thresholds(current: dict[str, Any], rec: dict[str, Any]) -> list[dict[str, Any]]:
    """현재 vs 추천 차이를 비교용 리스트로."""
    fields = ['min_alpha', 'max_risk', 'min_new_events', 'cooldown_minutes', 'force_after_hours']
    out: list[dict[str, Any]] = []
    for f in fields:
        cur = current.get(f)
        new = rec.get(f)
        try:
            delta = float(new) - float(cur) if cur is not None and new is not None else None
        except (TypeError, ValueError):
            delta = None
        out.append({
            'field': f,
            'current': cur,
            'recommended': new,
            'delta': delta,
        })
    return out


def apply_recommendation_in_memory(rec: dict[str, Any]) -> dict[str, Any]:
    """LLM 추천을 in-memory 환경변수에 즉시 적용 (Flask 재시작 시 env 우선)."""
    mapping = {
        'min_alpha': 'MIROFISH_AUTO_RUNNER_MIN_ALPHA',
        'max_risk': 'MIROFISH_AUTO_RUNNER_MAX_RISK',
        'min_new_events': 'MIROFISH_AUTO_RUNNER_MIN_NEW',
        'cooldown_minutes': 'MIROFISH_AUTO_RUNNER_COOLDOWN_MIN',
        'force_after_hours': 'MIROFISH_AUTO_RUNNER_FORCE_AFTER_HOURS',
    }
    applied = {}
    for field, env_name in mapping.items():
        if field in rec and rec[field] is not None:
            os.environ[env_name] = str(rec[field])
            applied[field] = rec[field]
    with _state_lock:
        state = _read_state()
        state['last_applied_recommendation'] = {
            'applied_at': _now_iso(),
            'values': applied,
            'reasoning': rec.get('reasoning'),
        }
        _write_state(state)
    return {
        'ok': True,
        'applied': applied,
        'effective_tunables': _tunables(),
        'note': 'in-memory 적용 완료. 영구화하려면 .env 수정 후 Flask 재시작.',
    }
