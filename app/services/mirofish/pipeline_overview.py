"""Pipeline overview + outcomes board aggregations for the admin dashboard.

Two read-only aggregations powering the right-side panel on /admin/endpoints:

1. ``get_pipeline_today_snapshot()`` — live market context + today's detection
   funnel + recent KPI summary (7d).
2. ``get_outcomes_board(days, limit)`` — recent workflow recommendations and
   their forward outcomes aggregated for the "Recent Outcomes" board.

Pure read aggregations — no side-effects, no LLM calls. Both endpoints are
safe to hit at high frequency.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.mirofish import alpha_scanner, workflow as workflow_svc
import app.services.mirofish.crash_rebound_gate as crash_rebound_gate
import app.services.mirofish.fear_index as fear_index


logger = logging.getLogger(__name__)


# ── pipeline_today 캐시 (95s+ cold build, 30s TTL) ────────────────────
# /pipeline/today 가 _kpi_window(7) + _kpi_window(30) + operating_snapshot 등
# 합산 95s+ 걸림. 30초 TTL 메모리 캐시로 첫 호출만 비싸고 후속 즉시.
_PIPELINE_TODAY_CACHE: dict[str, Any] = {}
_PIPELINE_TODAY_LOCK = threading.Lock()
_PIPELINE_TODAY_BUILD_LOCK = threading.Lock()
_PIPELINE_TODAY_BUILDING = False
_PIPELINE_TODAY_BUILD_STARTED_AT = 0.0
_PIPELINE_TODAY_TTL = 30.0
_PIPELINE_TODAY_BUILD_STALE_AFTER = 300.0
_PIPELINE_TODAY_MAX_WAIT = 0.75
_PIPELINE_TODAY_BACKGROUND_REFRESH = os.getenv(
    'MIROFISH_PIPELINE_BACKGROUND_REFRESH',
    '1',
).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
ADMIN_DATA_ROOT = os.path.join(DATA_ROOT, 'admin_mirofish')
SCANNER_RUNS_ROOT = os.path.join(ADMIN_DATA_ROOT, 'scanner_runs')
WORKFLOWS_ROOT = os.path.join(ADMIN_DATA_ROOT, 'workflows')
MARKET_GATE_CACHE = os.path.join(DATA_ROOT, 'market_gate_cache.json')
US_MARKET_DATA = os.path.join(REPO_ROOT, 'us_market', 'output', 'market_data.json')

try:  # KST timezone — fall back to UTC+9 if zoneinfo missing
    from zoneinfo import ZoneInfo

    KST = ZoneInfo('Asia/Seoul')
except Exception:  # pragma: no cover — best-effort
    KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Public — Today's Pipeline Snapshot
# ---------------------------------------------------------------------------


def get_pipeline_today_snapshot(max_wait_seconds: float | None = None) -> dict[str, Any]:
    """Aggregate live market + funnel + 7d KPI for the right-side dashboard.

    30초 TTL 메모리 캐시 — cold build ~95s 이므로 후속 폴링은 즉시 hit.
    Cold requests fail open with a cheap degraded response, then a background
    refresh fills the cache so the next poll receives the full snapshot.
    """
    return _get_pipeline_today_snapshot_nonblocking(max_wait_seconds)


def _get_pipeline_today_snapshot_nonblocking(max_wait_seconds: float | None = None) -> dict[str, Any]:
    now_ts = _time.time()
    max_wait = _PIPELINE_TODAY_MAX_WAIT if max_wait_seconds is None else max(0.05, float(max_wait_seconds))
    with _PIPELINE_TODAY_LOCK:
        slot = _PIPELINE_TODAY_CACHE.get('snapshot')
        if slot is not None:
            ts, data = slot
            if now_ts - ts < _PIPELINE_TODAY_TTL:
                return data
            stale_data = data
        else:
            stale_data = None

    if not _PIPELINE_TODAY_BACKGROUND_REFRESH:
        if stale_data is not None:
            return _mark_pipeline_snapshot_stale(stale_data, reason='cache_stale')
        return _fallback_pipeline_today_snapshot(reason='fast_path')

    done = threading.Event()
    started = _start_pipeline_today_refresh(done)
    if stale_data is not None:
        return _mark_pipeline_snapshot_stale(stale_data, reason='refreshing')
    if started and done.wait(timeout=max_wait):
        with _PIPELINE_TODAY_LOCK:
            slot = _PIPELINE_TODAY_CACHE.get('snapshot')
            if slot is not None:
                return slot[1]
    return _fallback_pipeline_today_snapshot(reason='refreshing')


def _start_pipeline_today_refresh(done: threading.Event | None = None) -> bool:
    global _PIPELINE_TODAY_BUILDING, _PIPELINE_TODAY_BUILD_STARTED_AT
    now_ts = _time.time()
    with _PIPELINE_TODAY_BUILD_LOCK:
        if (
            _PIPELINE_TODAY_BUILDING
            and now_ts - _PIPELINE_TODAY_BUILD_STARTED_AT < _PIPELINE_TODAY_BUILD_STALE_AFTER
        ):
            return False
        _PIPELINE_TODAY_BUILDING = True
        _PIPELINE_TODAY_BUILD_STARTED_AT = now_ts

    def _worker():
        global _PIPELINE_TODAY_BUILDING, _PIPELINE_TODAY_BUILD_STARTED_AT
        try:
            data = _build_pipeline_today_snapshot()
            with _PIPELINE_TODAY_LOCK:
                _PIPELINE_TODAY_CACHE['snapshot'] = (_time.time(), data)
        except Exception as exc:  # pragma: no cover - fail-open operator endpoint
            logger.warning(f'pipeline_today refresh failed: {exc}')
        finally:
            with _PIPELINE_TODAY_BUILD_LOCK:
                _PIPELINE_TODAY_BUILDING = False
                _PIPELINE_TODAY_BUILD_STARTED_AT = 0.0
            if done is not None:
                done.set()

    threading.Thread(target=_worker, name='mirofish-pipeline-today-refresh', daemon=True).start()
    return True


def _mark_pipeline_snapshot_stale(data: dict[str, Any], *, reason: str) -> dict[str, Any]:
    snapshot = dict(data)
    snapshot['degraded'] = True
    snapshot['degraded_reason'] = reason
    snapshot['served_at'] = datetime.now(timezone.utc).isoformat()
    return snapshot


def _fallback_pipeline_today_snapshot(*, reason: str) -> dict[str, Any]:
    now_kst = datetime.now(KST)
    now_utc = datetime.now(timezone.utc)
    schedule = _safe_fallback_call(alpha_scanner.get_scanner_schedule_status, now=now_kst) or {}
    latest_workflow = _safe_fallback_call(_latest_workflow_safe)
    workflow_summary = None
    if latest_workflow:
        workflow_summary = _safe_fallback_call(workflow_svc._workflow_summary, latest_workflow)
    workflow_summary = workflow_summary or {}
    event_count = int(workflow_summary.get('event_count') or 0)
    analyzed_count = int(workflow_summary.get('analyzed_count') or 0)
    top3_count = len(workflow_summary.get('top3') or [])
    return {
        'generated_at': now_utc.isoformat(),
        'date_kst': now_kst.date().isoformat(),
        'degraded': True,
        'degraded_reason': reason,
        'market': _safe_fallback_call(_market_pulse, now_kst),
        'crash_rebound_gate': _safe_fallback_call(_crash_rebound_gate_summary),
        'fear_index': _safe_fallback_call(_fear_index_summary),
        'funnel': {
            'scanner_pool': int(schedule.get('candidate_count') or 0),
            'scanner_runs_today': _safe_fallback_call(_count_scanner_runs_today, now_kst) or 0,
            'batch_new_candidates': event_count,
            'graphrag_uploaded': analyzed_count,
            'top3_ready': top3_count,
            'latest_workflow_id': workflow_summary.get('id'),
            'latest_workflow_status': workflow_summary.get('status'),
            'latest_workflow_at': workflow_summary.get('completed_at') or workflow_summary.get('created_at'),
            'latest_scanner_run_at': schedule.get('last_run_at'),
            'freshness_status': schedule.get('freshness_status'),
        },
        'operating_workflow': None,
        'kpi_7d': _cached_kpi_window(days=7),
        'kpi_30d': _cached_kpi_window(days=30),
        'next': {
            'next_scheduled_scan_at': schedule.get('next_scheduled_at'),
            'next_scheduled_scans': (schedule.get('next_scheduled_times') or [])[:3],
            'scanner_enabled': schedule.get('enabled'),
        },
        'alerts_today': _safe_fallback_call(_alerts_today, now_kst),
    }


def _cached_kpi_window(days: int) -> dict[str, Any]:
    """Return KPI from an existing board cache only.

    The fail-open pipeline response must stay cheap even during a cold start.
    If the board cache is cold, the background refresh will fill it later.
    """
    cache_key = f'board:{int(days)}:50'
    now_ts = _time.time()
    with _PIPELINE_TODAY_LOCK:
        slot = _PIPELINE_TODAY_CACHE.get(cache_key)
        if slot is not None and now_ts - slot[0] < _PIPELINE_TODAY_TTL:
            board = slot[1]
            summary = board.get('summary', {}) if isinstance(board, dict) else {}
            return {
                'window_days': int(days),
                'sample_size': summary.get('evaluated_count', 0),
                'hit_rate_pct': summary.get('hit_rate_pct'),
                'avg_return_pct': summary.get('avg_forward_return_pct'),
                'pending_count': summary.get('pending_count', 0),
                'source': 'cache',
            }
    return {
        'window_days': int(days),
        'sample_size': 0,
        'hit_rate_pct': None,
        'avg_return_pct': None,
        'pending_count': 0,
        'source': 'pending_refresh',
    }


def _safe_fallback_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.debug(f'pipeline_today fallback {getattr(fn, "__name__", "call")} failed: {exc}')
        return None


def _build_pipeline_today_snapshot() -> dict[str, Any]:
    """실제 snapshot 생성 — 캐시 미스 시 호출.

    sub-call 7개를 try/except 로 격리. 한 함수가 hang 해도 다른 데이터는 채워짐.
    Outer 30초 cache 와 결합 — cold call 만 1회 느리고 warm 즉시.

    NOTE: ThreadPoolExecutor 사용 X — with-context 가 shutdown(wait=True) 라
    timeout 안 끝나는 future 가 있으면 wall time 이 그대로 hang 으로 이어짐.
    sync 호출 + outer cache 로 단순화.
    """
    now_kst = datetime.now(KST)
    now_utc = datetime.now(timezone.utc)

    def _safe(label: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning(f'pipeline_today sub-call {label} failed: {exc}')
            return None

    return {
        'generated_at': now_utc.isoformat(),
        'date_kst': now_kst.date().isoformat(),
        'market': _safe('market', _market_pulse, now_kst),
        'crash_rebound_gate': _safe('crash_rebound_gate', _crash_rebound_gate_summary),
        'fear_index': _safe('fear_index', _fear_index_summary),
        'funnel': _safe('funnel', _funnel_today, now_kst),
        'operating_workflow': _safe('operating_workflow', get_pipeline_operating_snapshot, now=now_kst),
        'kpi_7d': _safe('kpi_7d', _kpi_window, days=7),
        'kpi_30d': _safe('kpi_30d', _kpi_window, days=30),
        'next': _safe('next', _next_eta, now_kst),
        'alerts_today': _safe('alerts_today', _alerts_today, now_kst),
    }


def get_pipeline_operating_snapshot(now: datetime | None = None) -> dict[str, Any]:
    """Return machine-readable scanner -> outcomes operating workflow state."""
    now_kst = (now or datetime.now(KST)).astimezone(KST)
    latest_workflow = _latest_workflow_safe()
    workflow_summary = workflow_svc._workflow_summary(latest_workflow) if latest_workflow else None
    schedule = alpha_scanner.get_scanner_schedule_status(now=now_kst)
    alerts = _alerts_today(now_kst)
    event_count = int((workflow_summary or {}).get('event_count') or 0)
    analyzed_count = int((workflow_summary or {}).get('analyzed_count') or 0)
    top3_count = len((workflow_summary or {}).get('top3') or [])
    outcome_status = str((latest_workflow or {}).get('outcome_status') or 'not_evaluated')
    workflow_status = str((workflow_summary or {}).get('status') or 'idle')
    stages = [
        _stage_snapshot(
            'scanner',
            'Alpha Scanner pool',
            'detect and rank raw alpha candidates',
            _scanner_stage_status(schedule),
            _stage_progress(1 if schedule.get('last_run_id') else 0, 1),
            count=int(schedule.get('candidate_count') or 0),
            total=None,
            artifact_id=schedule.get('last_run_id'),
            updated_at=schedule.get('last_run_at'),
        ),
        _stage_snapshot(
            'batch',
            'New-event batch',
            'filter scanner candidates into a replayable analysis batch',
            _batch_stage_status(workflow_status, event_count),
            _stage_progress(event_count, max(event_count, 1)),
            count=event_count,
            total=max(event_count, 1),
            artifact_id=(workflow_summary or {}).get('id'),
            updated_at=(workflow_summary or {}).get('created_at'),
            requires=['scanner'],
        ),
        _stage_snapshot(
            'graphrag',
            'GraphRAG analysis',
            'validate each batched candidate with multi-agent evidence',
            _analysis_stage_status(workflow_status, event_count, analyzed_count),
            _stage_progress(analyzed_count, max(event_count, 1)),
            count=analyzed_count,
            total=max(event_count, 1),
            artifact_id=(workflow_summary or {}).get('id'),
            updated_at=(workflow_summary or {}).get('completed_at') or (workflow_summary or {}).get('created_at'),
            requires=['batch'],
        ),
        _stage_snapshot(
            'top3',
            'MCP Top3',
            'select the highest forward-profit candidates for action',
            _top3_stage_status(workflow_status, analyzed_count, top3_count),
            _stage_progress(top3_count, min(max(event_count, 1), 3)),
            count=top3_count,
            total=min(max(event_count, 1), 3),
            artifact_id=(workflow_summary or {}).get('id'),
            updated_at=(workflow_summary or {}).get('completed_at'),
            requires=['graphrag'],
        ),
        _stage_snapshot(
            'telegram',
            'Telegram handoff',
            'publish actionable Top3 or scanner alerts to the operator',
            _telegram_stage_status(latest_workflow, top3_count, alerts),
            _stage_progress(1 if _telegram_was_sent(latest_workflow, alerts) else 0, 1),
            count=int(alerts.get('scanner_alerts_today') or 0),
            total=1,
            artifact_id=(workflow_summary or {}).get('id'),
            updated_at=(latest_workflow or {}).get('telegram_sent_at') or alerts.get('scanner_last_alert_at'),
            requires=['top3'],
        ),
        _stage_snapshot(
            'outcomes',
            'Forward outcomes',
            'track look-ahead-safe returns and feed learning memory',
            _outcomes_stage_status(outcome_status, top3_count),
            _stage_progress(1 if outcome_status in {'evaluated', 'partial'} else 0, 1),
            count=top3_count,
            total=top3_count or 1,
            artifact_id=(workflow_summary or {}).get('id'),
            updated_at=(workflow_summary or {}).get('completed_at'),
            requires=['top3'],
        ),
    ]
    current_stage = next((stage for stage in stages if stage['status'] in {'running', 'ready', 'waiting', 'attention'}), stages[-1])
    return {
        'schema_version': 'mirofish.operating_workflow.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'date_kst': now_kst.date().isoformat(),
        'workflow_id': (workflow_summary or {}).get('id'),
        'workflow_status': workflow_status,
        'current_stage_id': current_stage['id'],
        'overall_status': _overall_status(stages),
        'overall_progress_pct': round(sum(float(stage['progress_pct']) for stage in stages) / len(stages), 1),
        'stages': stages,
        'links': {
            'scanner_latest': 'mirofish://scanner/latest',
            'workflow_latest': 'mirofish://workflows/latest',
            'outcomes': 'mirofish://pipeline/outcomes',
        },
    }


def _market_pulse(now_kst: datetime) -> dict[str, Any]:
    kr_gate = _read_json_safe(MARKET_GATE_CACHE) or {}
    us_data = _read_json_safe(US_MARKET_DATA) or {}
    is_weekday = now_kst.weekday() < 5
    session_start = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    session_end = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
    is_regular = is_weekday and session_start <= now_kst <= session_end
    if not is_weekday:
        kr_phase = 'closed_weekend'
    elif now_kst < session_start:
        kr_phase = 'pre_open'
    elif now_kst <= session_end:
        kr_phase = 'regular_session'
    else:
        kr_phase = 'after_close'
    us_vix = None
    try:
        us_vix = (us_data.get('volatility') or {}).get('^VIX', {}).get('current')
    except Exception:
        us_vix = None
    fear_greed = us_data.get('fear_greed') or {}
    return {
        'kr': {
            'phase': kr_phase,
            'is_regular_session': is_regular,
            'gate_label': kr_gate.get('label') or kr_gate.get('status'),
            'gate_score': kr_gate.get('score'),
            'kospi_change_pct': kr_gate.get('kospi_change_pct'),
            'kosdaq_change_pct': kr_gate.get('kosdaq_change_pct'),
            'updated_at': kr_gate.get('updated_at'),
        },
        'us': {
            'vix': us_vix,
            'vix_level': _vix_level(us_vix),
            'fear_greed_score': fear_greed.get('score'),
            'fear_greed_label': fear_greed.get('level'),
            'timestamp': us_data.get('timestamp'),
        },
    }


def _crash_rebound_gate_summary() -> dict[str, Any]:
    return crash_rebound_gate.compact_crash_rebound_gate()


def _fear_index_summary() -> dict[str, Any]:
    return fear_index.compact_fear_index()


def _vix_level(vix: float | None) -> str | None:
    if vix is None:
        return None
    try:
        v = float(vix)
    except (TypeError, ValueError):
        return None
    if v < 15:
        return 'low'
    if v < 25:
        return 'moderate'
    if v < 35:
        return 'elevated'
    return 'high'


def _funnel_today(now_kst: datetime) -> dict[str, Any]:
    """Today's detection funnel counts.

    - scanner_pool       : latest scanner run candidate count (current state)
    - scanner_runs_today : count of scanner runs since 00:00 KST
    - batch_new          : event_count from latest workflow
    - graphrag_uploaded  : analyzed_count from latest workflow
    - top3_ready         : len(top3) from latest workflow
    """
    schedule = alpha_scanner.get_scanner_schedule_status(now=now_kst)
    latest_run_count = int(schedule.get('candidate_count') or 0)
    scanner_runs_today = _count_scanner_runs_today(now_kst)

    latest_workflow = None
    try:
        latest_workflow = workflow_svc.read_latest_workflow()
    except Exception as exc:
        logger.debug(f'read_latest_workflow failed: {exc}')

    workflow_summary = workflow_svc._workflow_summary(latest_workflow) if latest_workflow else None
    batch_new = int((workflow_summary or {}).get('event_count') or 0)
    analyzed = int((workflow_summary or {}).get('analyzed_count') or 0)
    top3_count = len((workflow_summary or {}).get('top3') or [])

    return {
        'scanner_pool': latest_run_count,
        'scanner_runs_today': scanner_runs_today,
        'batch_new_candidates': batch_new,
        'graphrag_uploaded': analyzed,
        'top3_ready': top3_count,
        'latest_workflow_id': (workflow_summary or {}).get('id'),
        'latest_workflow_status': (workflow_summary or {}).get('status'),
        'latest_workflow_at': (workflow_summary or {}).get('completed_at') or (workflow_summary or {}).get('created_at'),
        'latest_scanner_run_at': schedule.get('last_run_at'),
        'freshness_status': schedule.get('freshness_status'),
    }


def _count_scanner_runs_today(now_kst: datetime) -> int:
    if not os.path.isdir(SCANNER_RUNS_ROOT):
        return 0
    today_kst = now_kst.astimezone(KST).date()
    count = 0
    try:
        for name in os.listdir(SCANNER_RUNS_ROOT):
            if not name.startswith('mfas_'):
                continue
            run_at = _scanner_run_datetime_from_id(name)
            if run_at is None:
                run = _read_json_safe(os.path.join(SCANNER_RUNS_ROOT, name, 'run.json')) or {}
                run_at = _parse_timestamp(run.get('generated_at') or run.get('created_at'))
            if run_at and run_at.astimezone(KST).date() == today_kst:
                count += 1
        return count
    except OSError as exc:
        logger.debug(f'list scanner_runs failed: {exc}')
        return 0


def _next_eta(now_kst: datetime) -> dict[str, Any]:
    schedule = alpha_scanner.get_scanner_schedule_status(now=now_kst)
    return {
        'next_scheduled_scan_at': schedule.get('next_scheduled_at'),
        'next_scheduled_scans': (schedule.get('next_scheduled_times') or [])[:3],
        'scanner_enabled': schedule.get('enabled'),
    }


def _alerts_today(now_kst: datetime) -> dict[str, Any]:
    """Today's telegram alert tally — heuristic from alert state file."""
    state_path = os.path.join(ADMIN_DATA_ROOT, 'alpha_scanner_alert_state.json')
    state = _read_json_safe(state_path) or {}
    history = _scanner_alert_entries(state)
    last_sent_at = state.get('last_sent_at') or _latest_alert_sent_at(history) or state.get('updated_at')
    events_today = 0
    today_entries: list[dict[str, Any]] = []
    today_iso = now_kst.date().isoformat()
    for entry in history:
        if not isinstance(entry, dict):
            continue
        ts = str(entry.get('sent_at') or entry.get('timestamp') or '')
        sent_at = _parse_timestamp(ts)
        if sent_at and sent_at.astimezone(KST).date().isoformat() == today_iso:
            events_today += 1
            today_entries.append(entry)
        elif not sent_at and ts.startswith(today_iso):
            events_today += 1
            today_entries.append(entry)
    recent = today_entries or history
    return {
        'scanner_alerts_today': events_today,
        'scanner_last_alert_at': last_sent_at,
        'recent_scanner_alerts': recent[:5],
    }


def _scanner_alert_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    sent_events = state.get('sent_events') if isinstance(state.get('sent_events'), dict) else {}
    for key, value in sent_events.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault('event_key', str(key))
            entries.append(item)
    persisted_history = state.get('history') if isinstance(state.get('history'), list) else []
    for value in persisted_history:
        if isinstance(value, dict):
            entries.append(dict(value))

    by_key: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = str(
            entry.get('event_key')
            or f"{entry.get('symbol')}:{entry.get('action')}:{entry.get('sent_at')}:{entry.get('run_id')}"
        )
        current = by_key.get(key)
        if current is None or str(entry.get('sent_at') or '') >= str(current.get('sent_at') or ''):
            merged = dict(current or {})
            merged.update(entry)
            merged.setdefault('event_key', key)
            by_key[key] = merged
    items = list(by_key.values())
    items.sort(key=lambda item: str(item.get('sent_at') or item.get('timestamp') or ''), reverse=True)
    return items


def _latest_alert_sent_at(entries: list[dict[str, Any]]) -> str | None:
    latest: str | None = None
    for entry in entries:
        value = entry.get('sent_at') or entry.get('timestamp')
        if not value:
            continue
        text = str(value)
        if latest is None or text > latest:
            latest = text
    return latest


# ---------------------------------------------------------------------------
# Public — Recent Outcomes Board
# ---------------------------------------------------------------------------


def get_outcomes_board(days: int = 30, limit: int = 20) -> dict[str, Any]:
    """Aggregate recent workflow outcomes within ``days`` window.

    Iterates the workflows directory, loads each ``outcomes.json``, and
    builds a flat board of recommendation items + an aggregate KPI summary.
    """
    days = max(1, min(int(days or 30), 180))
    limit = max(1, min(int(limit or 20), 200))

    # outcomes_board 30s 캐시 — get_pipeline_today 가 이 함수를 7d/30d 두 번
    # 호출하고, 사용자 화면 60s 폴링도 매번 build 하면 95s+ hang 으로 이어짐.
    cache_key = f'board:{days}:{limit}'
    now_ts = _time.time()
    with _PIPELINE_TODAY_LOCK:
        slot = _PIPELINE_TODAY_CACHE.get(cache_key)
        if slot is not None and now_ts - slot[0] < _PIPELINE_TODAY_TTL:
            return slot[1]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    workflow_ids = _recent_workflow_ids(cutoff)

    all_items: list[dict[str, Any]] = []
    horizon_summary = {
        'evaluated_count': 0,
        'pending_count': 0,
        'hit_count': 0,
        'miss_count': 0,
        'stopped_count': 0,
        'forward_returns': [],
    }
    workflows_used: list[str] = []
    for workflow_id in workflow_ids:
        # Admin dashboard reads must never trigger lazy outcome recomputation.
        # Recompute can pull daily_prices.csv and block Flask request threads.
        outcomes = _read_outcomes_artifact(workflow_id)
        if not isinstance(outcomes, dict):
            continue
        # Try refresh stale/pending ones (cheap — daily_prices.csv read is cached implicitly via file mtime)
        items = outcomes.get('items') if isinstance(outcomes.get('items'), list) else []
        if not items:
            continue
        workflows_used.append(workflow_id)
        for item in items:
            if not isinstance(item, dict):
                continue
            flat = _flatten_outcome_item(item, workflow_id=workflow_id)
            all_items.append(flat)
            status = item.get('status')
            if status in {'evaluated', 'partial'}:
                horizon_summary['evaluated_count'] += 1
                if item.get('hit') is True:
                    horizon_summary['hit_count'] += 1
                elif item.get('hit') is False:
                    horizon_summary['miss_count'] += 1
                fr = item.get('forward_return_pct')
                if isinstance(fr, (int, float)):
                    horizon_summary['forward_returns'].append(float(fr))
            else:
                horizon_summary['pending_count'] += 1
            if item.get('stopped'):
                horizon_summary['stopped_count'] += 1

    # Sort items: evaluated/hit-true first, then by entry_date desc
    all_items.sort(key=lambda r: (
        0 if r.get('status') in {'evaluated', 'partial'} else 1,
        # newest entry_date first
        -(_date_sort_key(r.get('entry_date'))),
    ))
    visible = all_items[:limit]

    returns = horizon_summary['forward_returns']
    evaluated = horizon_summary['evaluated_count']
    hit_rate = round((horizon_summary['hit_count'] / evaluated) * 100, 1) if evaluated else None
    avg_return = round(sum(returns) / len(returns), 2) if returns else None
    false_positive_pct = round((horizon_summary['miss_count'] / evaluated) * 100, 1) if evaluated else None

    result = {
        'window_days': days,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sample_size': len(all_items),
        'workflow_count': len(workflows_used),
        'summary': {
            'evaluated_count': evaluated,
            'pending_count': horizon_summary['pending_count'],
            'hit_count': horizon_summary['hit_count'],
            'miss_count': horizon_summary['miss_count'],
            'stopped_count': horizon_summary['stopped_count'],
            'hit_rate_pct': hit_rate,
            'avg_forward_return_pct': avg_return,
            'false_positive_pct': false_positive_pct,
            'best_return_pct': max(returns) if returns else None,
            'worst_return_pct': min(returns) if returns else None,
            'targets': {
                'hit_rate_pct': 55.0,
                'avg_return_pct': 1.5,
                'false_positive_pct': 20.0,
            },
        },
        'items': visible,
        'items_truncated': len(all_items) > len(visible),
        'total_items': len(all_items),
    }
    # 캐시 저장
    with _PIPELINE_TODAY_LOCK:
        _PIPELINE_TODAY_CACHE[cache_key] = (_time.time(), result)
    return result


def _recent_workflow_ids(cutoff: datetime) -> list[str]:
    """Return workflow ids whose dir-name datetime stamp is within ``cutoff``."""
    if not os.path.isdir(WORKFLOWS_ROOT):
        return []
    ids: list[tuple[str, str]] = []  # (id, sort_key)
    for name in os.listdir(WORKFLOWS_ROOT):
        if name.startswith('_') or name.startswith('.'):
            continue
        full = os.path.join(WORKFLOWS_ROOT, name)
        if not os.path.isdir(full):
            continue
        # mtime-based cutoff is safest (dir name has datetime stamp but format may vary)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if datetime.fromtimestamp(mtime, tz=timezone.utc) < cutoff:
            continue
        ids.append((name, datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()))
    ids.sort(key=lambda x: x[1], reverse=True)
    return [item[0] for item in ids]


def _read_outcomes_artifact(workflow_id: str) -> dict[str, Any] | None:
    safe_id = os.path.basename(str(workflow_id or ''))
    if not safe_id or safe_id in {'.', '..'}:
        return None
    return _read_json_safe(os.path.join(WORKFLOWS_ROOT, safe_id, 'outcomes.json'))


def _flatten_outcome_item(item: dict[str, Any], *, workflow_id: str) -> dict[str, Any]:
    horizons = item.get('horizons') if isinstance(item.get('horizons'), dict) else {}
    flat_horizons = {}
    for key, payload in horizons.items():
        if isinstance(payload, dict):
            flat_horizons[str(key)] = payload.get('return_pct')
    return {
        'workflow_id': workflow_id,
        'symbol': item.get('symbol'),
        'name': item.get('name'),
        'rank': item.get('rank'),
        'entry_date': item.get('entry_date'),
        'entry_price': item.get('entry_price'),
        'status': item.get('status'),
        'hit': item.get('hit'),
        'stopped': item.get('stopped'),
        'forward_return_pct': item.get('forward_return_pct'),
        'max_forward_return_pct': item.get('max_forward_return_pct'),
        'max_drawdown_pct': item.get('max_drawdown_pct'),
        'primary_horizon_days': item.get('primary_horizon_days'),
        'available_future_days': item.get('available_future_days'),
        'horizons': flat_horizons,
        'feature_snapshot': item.get('feature_snapshot'),
    }


def _date_sort_key(date_str: Any) -> int:
    """Numeric date key: YYYY-MM-DD → 20260512, else 0."""
    if not isinstance(date_str, str):
        return 0
    digits = date_str.replace('-', '')[:8]
    try:
        return int(digits) if digits.isdigit() else 0
    except Exception:
        return 0


def _kpi_window(days: int) -> dict[str, Any]:
    """Compact KPI for the live pulse — small window.

    limit=200 은 board 의 items[] 크기일 뿐 summary 통계와 무관.
    summary 만 사용하므로 limit 50 으로 줄여 디스크 IO 단축.
    """
    board = get_outcomes_board(days=days, limit=50)
    return {
        'window_days': days,
        'sample_size': board.get('summary', {}).get('evaluated_count', 0),
        'hit_rate_pct': board.get('summary', {}).get('hit_rate_pct'),
        'avg_return_pct': board.get('summary', {}).get('avg_forward_return_pct'),
        'pending_count': board.get('summary', {}).get('pending_count', 0),
    }


def _latest_workflow_safe() -> dict[str, Any] | None:
    try:
        return workflow_svc.read_latest_workflow()
    except Exception as exc:
        logger.debug(f'read_latest_workflow failed: {exc}')
        return None


def _stage_snapshot(
    stage_id: str,
    label: str,
    objective: str,
    status: str,
    progress_pct: float,
    *,
    count: int,
    total: int | None,
    artifact_id: Any,
    updated_at: Any,
    requires: list[str] | None = None,
) -> dict[str, Any]:
    return {
        'id': stage_id,
        'label': label,
        'objective': objective,
        'status': status,
        'progress_pct': progress_pct,
        'count': count,
        'total': total,
        'artifact_id': artifact_id,
        'updated_at': updated_at,
        'requires': requires or [],
    }


def _stage_progress(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (float(count) / float(total)) * 100.0)), 1)


def _scanner_stage_status(schedule: dict[str, Any]) -> str:
    freshness = str(schedule.get('freshness_status') or '').lower()
    if freshness in {'stale', 'missing', 'partial', 'unknown'}:
        return 'attention'
    return 'complete' if schedule.get('last_run_id') else 'waiting'


def _batch_stage_status(workflow_status: str, event_count: int) -> str:
    if workflow_status in {'queued', 'running'}:
        return 'running'
    if event_count > 0:
        return 'complete'
    if workflow_status in {'no_new_events', 'idle'}:
        return 'waiting'
    return 'attention' if workflow_status in {'failed', 'blocked'} else 'waiting'


def _analysis_stage_status(workflow_status: str, event_count: int, analyzed_count: int) -> str:
    if workflow_status == 'running':
        return 'running'
    if event_count > 0 and analyzed_count >= event_count:
        return 'complete'
    if analyzed_count > 0:
        return 'running'
    return 'attention' if workflow_status == 'failed' else 'waiting'


def _top3_stage_status(workflow_status: str, analyzed_count: int, top3_count: int) -> str:
    if top3_count > 0:
        return 'complete'
    if workflow_status in {'queued', 'running'}:
        return 'waiting'
    if analyzed_count > 0:
        return 'attention'
    return 'waiting'


def _telegram_was_sent(latest_workflow: dict[str, Any] | None, alerts: dict[str, Any]) -> bool:
    workflow_sent = bool((latest_workflow or {}).get('telegram_sent') or (latest_workflow or {}).get('event_state_committed'))
    scanner_sent = int(alerts.get('scanner_alerts_today') or 0) > 0
    return workflow_sent or scanner_sent


def _telegram_stage_status(
    latest_workflow: dict[str, Any] | None,
    top3_count: int,
    alerts: dict[str, Any],
) -> str:
    if _telegram_was_sent(latest_workflow, alerts):
        return 'complete'
    if top3_count > 0:
        return 'ready'
    return 'waiting'


def _outcomes_stage_status(outcome_status: str, top3_count: int) -> str:
    if outcome_status in {'evaluated', 'partial'}:
        return 'complete'
    if outcome_status in {'pending', 'not_evaluated', 'unknown'} and top3_count > 0:
        return 'ready'
    if outcome_status == 'failed':
        return 'attention'
    return 'waiting'


def _overall_status(stages: list[dict[str, Any]]) -> str:
    statuses = {str(stage.get('status')) for stage in stages}
    if 'attention' in statuses:
        return 'attention'
    if 'running' in statuses:
        return 'running'
    if 'ready' in statuses:
        return 'ready'
    if statuses == {'complete'}:
        return 'complete'
    return 'waiting'


# ---------------------------------------------------------------------------
# Public — Subscriber-facing AIBain Overview
# ---------------------------------------------------------------------------


def get_aibain_overview(*, perf_days: int = 30) -> dict:
    """Subscriber-facing aggregation: detections + performance + learning.

    Read-only. Composes existing services. Each section is isolated so one
    failing source never breaks the whole response.
    """
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'detections': {'as_of': None, 'items': []},
        'performance': {'window_days': perf_days, 'hit_rate_pct': None,
                        'avg_forward_return_pct': None, 'false_positive_pct': None,
                        'evaluated_count': 0, 'verified': []},
        'learning': {'regime_distribution': {}, 'top_positive': [], 'top_negative': [], 'updated_at': None},
    }
    # detections
    try:
        import app.services.mirofish.workflow as _wf
        wf = _wf.read_latest_workflow()
        if isinstance(wf, dict):
            out['detections']['as_of'] = wf.get('completed_at') or wf.get('generated_at')
            payload = _wf.build_share_payload(wf, rank=None) or {}
            items = []
            for it in (payload.get('top_items') or [])[:3]:
                if not isinstance(it, dict):
                    continue
                items.append({
                    'symbol': it.get('symbol'),
                    'name': it.get('name'),
                    'action': it.get('action'),
                    'alpha_score': it.get('alpha_score'),
                    'risk_score': it.get('risk_score'),
                    'rs_rating': it.get('rs_rating'),
                    'entry_date': it.get('entry_date') or it.get('replay_safe_after'),
                })
            out['detections']['items'] = items
    except Exception as exc:
        out['detections']['error'] = f'{type(exc).__name__}: {exc}'
    # performance
    try:
        board = get_outcomes_board(days=perf_days, limit=8)
        summary = (board or {}).get('summary') or {}
        out['performance'].update({
            'window_days': (board or {}).get('window_days', perf_days),
            'hit_rate_pct': summary.get('hit_rate_pct'),
            'avg_forward_return_pct': summary.get('avg_forward_return_pct'),
            'false_positive_pct': summary.get('false_positive_pct'),
            'evaluated_count': summary.get('evaluated_count') or 0,
        })
        verified = []
        items = (board or {}).get('items') or []
        # evaluated/partial first
        ordered = [i for i in items if isinstance(i, dict) and i.get('status') in {'evaluated', 'partial'}]
        ordered += [i for i in items if isinstance(i, dict) and i.get('status') not in {'evaluated', 'partial'}]
        for it in ordered[:8]:
            verified.append({
                'symbol': it.get('symbol'), 'name': it.get('name'),
                'entry_date': it.get('entry_date'),
                'forward_return_pct': it.get('forward_return_pct'),
                'hit': it.get('hit'), 'status': it.get('status'),
            })
        out['performance']['verified'] = verified
    except Exception as exc:
        out['performance'] = {'window_days': perf_days, 'evaluated_count': 0, 'verified': [],
                              'error': f'{type(exc).__name__}: {exc}'}
    # learning
    try:
        import app.services.mirofish.alpha_brain_agent as _agent
        obs = _agent.build_agent_observation() or {}
        imap = obs.get('interaction_map') or {}
        out['learning']['top_positive'] = (imap.get('top_positive') or [])[:5]
        out['learning']['top_negative'] = (imap.get('top_negative') or [])[:5]
        out['learning']['regime_distribution'] = obs.get('regime_distribution') or {}
        try:
            status = _agent.get_agent_status() or {}
            out['learning']['updated_at'] = status.get('edge_map_generated_at')
        except Exception:
            pass
    except Exception as exc:
        out['learning'] = {'regime_distribution': {}, 'top_positive': [], 'top_negative': [],
                           'updated_at': None, 'error': f'{type(exc).__name__}: {exc}'}
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_json_safe(path: str) -> dict[str, Any] | None:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (IOError, OSError, json.JSONDecodeError) as exc:
        logger.debug(f'read {path} failed: {exc}')
        return None


def _scanner_run_datetime_from_id(name: str) -> datetime | None:
    parts = str(name or '').split('_')
    if len(parts) < 2:
        return None
    stamp = parts[1][:14]
    if len(stamp) != 14 or not stamp.isdigit():
        return None
    try:
        return datetime.strptime(stamp, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
