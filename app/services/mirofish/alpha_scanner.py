"""Deterministic file-backed alpha scanner for MiroFish Phase 1."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import threading
import time as time_mod
from collections import Counter
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

import app.services.mirofish.blacklist as blacklist_service
import app.services.mirofish.credit_balance as credit_balance_service
import app.services.mirofish.live_data as live_data
import app.services.mirofish.sector_rs as sector_rs_service
import app.services.mirofish.tradingview_provider as tradingview_provider
from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
SCANNER_RUNS_ROOT = os.path.join(DATA_ROOT, 'admin_mirofish', 'scanner_runs')

MAX_CANDIDATES = 100
DEFAULT_LIMIT = 30
DEFAULT_ALERT_LIMIT = 20
DEFAULT_ALERT_MIN_ALPHA = 70.0
DEFAULT_ALERT_MAX_RISK = 45.0
DEFAULT_ALERT_MAX_EVENTS = 8
DEFAULT_MONITOR_RETRY_SECONDS = 300
DEFAULT_SCHEDULE_TIMES = '09:20,11:20,14:20,15:40,16:10'
KST = timezone(timedelta(hours=9))
MONITOR_STATE_VERSION = 2
ALERT_BLOCKING_FRESHNESS = {'stale', 'missing', 'partial', 'unknown'}
SOURCE_FILE_POLICIES = {
    'daily_prices.csv': {
        'role': 'price_history',
        'required': True,
        'alert_required': True,
        'max_age_days': 5,
    },
    'ticker_to_yahoo_map.csv': {
        'role': 'symbol_map',
        'required': True,
        'alert_required': True,
        'max_age_days': 180,
    },
    'korean_stocks_list.csv': {
        'role': 'canonical_stock_names',
        'required': False,
        'alert_required': False,
        'max_age_days': 365,
    },
    'screener_leading_latest.json': {
        'role': 'leading_screener',
        'required': True,
        'alert_required': True,
        'max_age_days': 7,
    },
    'vcp_kr_latest.json': {
        'role': 'vcp_quality',
        'required': True,
        'alert_required': False,
        'max_age_days': 7,
    },
    'jongga_v2_latest.json': {
        'role': 'jongga_setup',
        'required': True,
        'alert_required': False,
        'max_age_days': 7,
    },
    'all_institutional_trend_data.csv': {
        'role': 'capital_flow_confirmation',
        'required': False,
        'alert_required': False,
        'max_age_days': 30,
    },
    'kind_blacklist_latest.json': {
        'role': 'risk_blacklist',
        'required': False,
        'alert_required': False,
        'max_age_days': 7,
    },
    'credit_balance_latest.json': {
        'role': 'credit_balance_risk',
        'required': False,
        'alert_required': False,
        'max_age_days': 7,
    },
    'kis_live_snapshot_latest.json': {
        'role': 'kis_live_price_flow',
        'required': False,
        'alert_required': False,
        'max_age_days': 1,
    },
    'dart_event_latest.json': {
        'role': 'dart_disclosure_risk',
        'required': False,
        'alert_required': False,
        'max_age_days': 7,
    },
    'news_theme_social_latest.json': {
        'role': 'supporting_news_theme_social',
        'required': False,
        'alert_required': False,
        'max_age_days': 2,
    },
}
WATCHED_SOURCE_FILES = tuple(SOURCE_FILE_POLICIES.keys())
SCANNER_ARTIFACT_FILENAMES = {
    'feature_vectors.json',
    'evidence_ledger.json',
    'rejected_candidates.json',
    'deepseek_rerank.json',
}

SCORING_SCHEMA = {
    'alpha_score': {
        'description': 'Profit-potential score from deterministic local artifacts.',
        'components': {
            'price_momentum': '0..15 from latest daily change_rate, capped to avoid chasing spikes.',
            'trend_quality': '0..15 from 5/20 day trend, moving-average position, and consistency.',
            'liquidity': '0..10 from trading value or price*volume.',
            'volume_accumulation': '0..10 from latest volume versus recent average with positive price confirmation.',
            'screener_leading': '0..20 from screener score.total_enriched/total.',
            'vcp_quality': '0..15 from VCP composite_score and entry-ready flag.',
            'jongga_setup': '0..10 from jongga_v2 total score and checklist.',
            'source_convergence': '0..5 when independent artifacts agree with price behavior.',
            'tradingview_mcp': 'Optional TradingView MCP technical confirmation adjustment, fail-open.',
            'plan_a_flow_confirmation': 'Optional +2 when foreigner and institution 5-day flows are both positive.',
            'mcp_quality_adjustment': 'Bounded KIS/live flow, source freshness, disclosure-risk, and outcome-memory adjustment.',
        },
    },
    'risk_score': {
        'description': 'Penalty score where higher means worse entry/risk quality.',
        'components': {
            'overextension': 'Large one-day moves increase risk.',
            'intraday_range': 'Wide high-low range increases execution risk.',
            'volatility': 'Recent realized volatility and drawdown increase risk.',
            'liquidity_gap': 'Missing or thin trading value increases risk.',
            'source_gap': 'Missing independent artifacts reduce confidence.',
            'artifact_staleness': 'Older source artifacts increase risk.',
            'negative_flags': 'Negative news, suspicious volume, or long upper wick add risk.',
            'plan_a_false_signal_gates': 'KIND hard blocks, upper-wick risk, credit pressure, and thin-liquidity spike guards.',
            'mcp_resource_quality': 'Stale or low-confidence MCP resources increase risk; DART/event risk can hard-filter candidates.',
        },
    },
    'ranking': 'rank by alpha_score - 0.55 * risk_score + conviction_adjustment + bounded MCP/outcome adjustments, descending.',
}


def create_scanner_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    limit = _clean_limit(payload.get('limit'), default=DEFAULT_LIMIT)
    requested_symbols = _clean_symbols(payload.get('symbols'))
    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = _run_id(generated_at, requested_symbols, limit)

    artifacts = _load_artifacts()
    performance_advisory = _performance_advisory()
    candidate_pool = _build_candidate_pool(
        artifacts,
        generated_at=generated_at,
        requested_symbols=requested_symbols,
        performance_advisory=performance_advisory,
    )
    deepseek_rerank = _maybe_deepseek_rerank_candidates(
        candidate_pool,
        payload=payload,
        generated_at=generated_at,
        requested_symbols=requested_symbols,
        limit=limit,
    )
    candidate_pool = _apply_deepseek_rerank_overlay(candidate_pool, deepseek_rerank)
    candidates = _select_candidates(candidate_pool, limit)
    rejected_candidates = _rejected_candidates(candidate_pool, selected_count=len(candidates), limit=limit)
    feature_vectors = _feature_vectors(candidates)
    evidence_ledger = _evidence_ledger(candidates, rejected_candidates)
    source_files = _source_files(artifacts)
    goal_harness = _profitability_run_summary(candidates, rejected_candidates)
    run = {
        'id': run_id,
        'status': 'completed',
        'mode': 'deterministic_file_artifacts',
        'source': 'local_marketflow_artifacts',
        'generated_at': generated_at,
        'created_at': generated_at,
        'limit': limit,
        'requested_symbols': sorted(requested_symbols),
        'universe_size': len(artifacts['candidate_symbols']),
        'candidate_count': len(candidates),
        'screened_count': len(candidate_pool),
        'rejected_candidate_count': len(rejected_candidates),
        'scoring_schema': SCORING_SCHEMA,
        'goal_harness': goal_harness,
        'performance_advisory': performance_advisory,
        'providers': {
            'tradingview': artifacts.get('tradingview', {}).get('status') or tradingview_provider.get_status(include_live=False),
            'deepseek_rerank': _deepseek_rerank_provider_status(deepseek_rerank),
        },
        'source_files': source_files,
        'freshness': _aggregate_freshness(source_files),
        'candidates': candidates,
        'analysis_artifacts': {
            'feature_vectors': f'/api/admin/mirofish/scanner/runs/{run_id}/feature-vectors',
            'evidence_ledger': f'/api/admin/mirofish/scanner/runs/{run_id}/evidence',
            'rejected_candidates': f'/api/admin/mirofish/scanner/runs/{run_id}/rejects',
            'deepseek_rerank': f'/api/admin/mirofish/scanner/runs/{run_id}/artifacts/deepseek_rerank.json',
        },
        'links': {
            'self': f'/api/admin/mirofish/scanner/runs/{run_id}',
            'candidates': f'/api/admin/mirofish/scanner/runs/{run_id}/candidates',
        },
    }

    write_json_atomic(_run_path(run_id), run, sort_keys=False)
    write_json_atomic(_run_artifact_path(run_id, 'feature_vectors.json'), {
        'run_id': run_id,
        'generated_at': generated_at,
        'feature_count': len(feature_vectors),
        'features': feature_vectors,
        'lookahead_safe': True,
    }, sort_keys=False)
    write_json_atomic(_run_artifact_path(run_id, 'evidence_ledger.json'), {
        'run_id': run_id,
        'generated_at': generated_at,
        'candidate_count': len(candidates),
        'rejected_candidate_count': len(rejected_candidates),
        'items': evidence_ledger,
        'lookahead_safe': True,
    }, sort_keys=False)
    write_json_atomic(_run_artifact_path(run_id, 'rejected_candidates.json'), {
        'run_id': run_id,
        'generated_at': generated_at,
        'rejected_candidate_count': len(rejected_candidates),
        'candidates': rejected_candidates,
        'lookahead_safe': True,
    }, sort_keys=False)
    write_json_atomic(_run_artifact_path(run_id, 'deepseek_rerank.json'), {
        'run_id': run_id,
        'generated_at': generated_at,
        **deepseek_rerank,
        'lookahead_safe': True,
    }, sort_keys=False)
    return run


def read_scanner_run(run_id: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    path = _run_path(safe_id)
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def read_scanner_candidates(run_id: str) -> dict[str, Any] | None:
    run = read_scanner_run(run_id)
    if run is None:
        return None
    return {
        'run_id': run['id'],
        'generated_at': run.get('generated_at'),
        'source': run.get('source'),
        'freshness': run.get('freshness'),
        'candidate_count': len(run.get('candidates') or []),
        'candidates': run.get('candidates') or [],
    }


def read_scanner_run_artifact(run_id: str, filename: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    safe_filename = str(filename or '').strip()
    if safe_filename not in SCANNER_ARTIFACT_FILENAMES:
        raise ValueError('invalid scanner artifact')
    path = _run_artifact_path(safe_id, safe_filename)
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def list_scanner_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent scanner run summaries without loading candidate payloads."""
    records = _scanner_run_records()
    clean_limit = max(1, min(_clean_limit(limit, default=20), 100))
    return [_scanner_run_summary(item['run']) for item in records[:clean_limit]]


def read_latest_scanner_run() -> dict[str, Any] | None:
    """Return the newest persisted scanner run, if one exists."""
    for path in _latest_scanner_run_paths():
        try:
            run = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(run, dict):
            return run
    return None


def _latest_scanner_run_path() -> str | None:
    paths = _latest_scanner_run_paths()
    return paths[0] if paths else None


def _latest_scanner_run_paths() -> list[str]:
    if not os.path.isdir(SCANNER_RUNS_ROOT):
        return []
    candidates: list[tuple[float, str, str]] = []
    try:
        entries = list(os.scandir(SCANNER_RUNS_ROOT))
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            safe_id = _safe_run_id(entry.name)
        except ValueError:
            continue
        path = os.path.join(SCANNER_RUNS_ROOT, safe_id, 'run.json')
        if not os.path.isfile(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        candidates.append((mtime, safe_id, path))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in candidates]


def read_price_chart(symbol: str, limit: int = 120) -> dict[str, Any]:
    """Return deterministic OHLCV chart data for a scanner symbol."""
    clean_symbol = _symbol(symbol)
    if not clean_symbol:
        raise ValueError('invalid symbol')
    try:
        clean_limit = int(limit)
    except (TypeError, ValueError):
        clean_limit = 120
    clean_limit = max(20, min(clean_limit, 250))

    # 단일 종목 조회라도 _load_price_history 는 CSV 전체를 훑어서 ~40s 가 걸린다.
    # 메모리 캐시(_load_price_history_cached)에서 dict lookup 으로 끝낸다.
    history = _load_price_history_cached().get(clean_symbol, [])
    by_date: dict[str, dict[str, Any]] = {}
    for row in history:
        date = str(row.get('date') or '').strip()
        close = _float(row.get('current_price'))
        if not date or close <= 0:
            continue
        open_price = _float(row.get('open')) or close
        high = _float(row.get('high')) or max(open_price, close)
        low = _float(row.get('low')) or min(open_price, close)
        high = max(high, open_price, close)
        low = min(low, open_price, close)
        by_date[date] = {
            'date': date,
            'open': round(open_price, 4),
            'high': round(high, 4),
            'low': round(low, 4),
            'close': round(close, 4),
            'volume': int(_float(row.get('volume'))),
            'change_rate': round(_float(row.get('change_rate')), 4),
            'update_time': row.get('update_time') or '',
        }

    chart = [by_date[date] for date in sorted(by_date)][-clean_limit:]
    latest = history[-1] if history else {}
    return {
        'symbol': clean_symbol,
        'target': latest.get('name') or clean_symbol,
        'source': 'daily_prices.csv',
        'count': len(chart),
        'limit': clean_limit,
        'chart': chart,
        'latest': chart[-1] if chart else None,
    }


def get_scanner_schedule_status(now: datetime | None = None) -> dict[str, Any]:
    """Return alpha scanner schedule, latest run, and source freshness status."""
    current = (now or datetime.now(KST)).astimezone(KST)
    scheduled_times = _scanner_schedule_times()
    latest = read_latest_scanner_run()
    source_files = _source_files(_load_source_artifacts())
    freshness = _aggregate_freshness(source_files)
    latest_source_files = latest.get('source_files') if latest else None
    latest_freshness = latest.get('freshness') if latest else None
    scheduler_last_run_at = _scheduler_last_run_at()
    next_scheduled = _next_scheduled_times(current, scheduled_times, count=5)
    return {
        'enabled': os.getenv('ALPHA_SCANNER_ENABLED', 'true').strip().lower() == 'true',
        'timezone': 'Asia/Seoul',
        'scheduled_times': [item.strftime('%H:%M') for item in scheduled_times],
        'next_scheduled_times': next_scheduled,
        'next_scheduled_at': next_scheduled[0] if next_scheduled else None,
        'last_run_id': latest.get('id') if latest else None,
        'last_run_at': (latest or {}).get('generated_at') or (latest or {}).get('created_at'),
        'scheduler_last_run_at': scheduler_last_run_at,
        'freshness': freshness,
        'freshness_status': (freshness or {}).get('status'),
        'providers': {
            'tradingview': tradingview_provider.get_status(include_live=False),
        },
        'source_files': source_files,
        'latest_run_freshness': latest_freshness,
        'latest_run_source_files': latest_source_files,
        'candidate_count': latest.get('candidate_count') if latest else 0,
        'checked_at': current.isoformat(),
    }


def get_scanner_diagnostics(now: datetime | None = None) -> dict[str, Any]:
    """Return an operator-focused health view for scanner data and alerts."""
    schedule = get_scanner_schedule_status(now=now)
    source = get_scanner_source_signature()
    monitor = read_scanner_monitor_state()
    alert = read_scanner_alert_state()
    latest = read_latest_scanner_run()
    telegram = _telegram_config_status()
    deepseek = {'configured': bool(os.getenv('DEEPSEEK_API_KEY'))}
    tradingview = tradingview_provider.get_status(include_live=False)
    issues: list[dict[str, Any]] = []

    freshness = schedule.get('freshness') or {}
    source_files = schedule.get('source_files') or []
    stale_files = [item.get('file') for item in source_files if item.get('freshness') == 'stale']
    unknown_files = [item.get('file') for item in source_files if item.get('freshness') == 'unknown']
    if source.get('missing_files'):
        issues.append({
            'severity': 'error' if source.get('available_files') == 0 else 'warning',
            'code': 'missing_source_files',
            'message': f"{source.get('missing_files')} scanner source files are missing.",
        })
    if freshness.get('status') in {'stale', 'missing', 'partial', 'unknown'}:
        issues.append({
            'severity': 'warning',
            'code': 'source_freshness',
            'message': f"source freshness is {freshness.get('status')}.",
            'files': stale_files or unknown_files,
        })
    if not latest:
        issues.append({
            'severity': 'warning',
            'code': 'no_scanner_run',
            'message': 'no persisted scanner run is available yet.',
        })
    if monitor.get('last_status') == 'send_failed':
        issues.append({
            'severity': 'error',
            'code': 'telegram_send_failed',
            'message': monitor.get('last_error') or 'last realtime Telegram send failed.',
        })
    if not telegram['personal_configured']:
        issues.append({
            'severity': 'error',
            'code': 'telegram_not_configured',
            'message': 'TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.',
        })

    health = 'ok'
    if any(item['severity'] == 'error' for item in issues):
        health = 'error'
    elif issues:
        health = 'warning'

    return {
        'ok': health != 'error',
        'health': health,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'schedule': schedule,
        'source': source,
        'source_freshness': freshness,
        'source_files': source_files,
        'monitor': monitor,
        'alert': alert,
        'latest_run': _scanner_run_summary(latest) if latest else None,
        'telegram': telegram,
        'deepseek': deepseek,
        'tradingview': tradingview,
        'issues': issues,
    }


def read_scanner_alert_state(state_path: str | None = None) -> dict[str, Any]:
    """Return alpha-scanner alert state for admin diagnostics."""
    state_file = state_path or _alert_state_path()
    return _alert_state_summary(_read_alert_state(state_file), state_file, latest_run=read_latest_scanner_run())


def get_scanner_source_signature() -> dict[str, Any]:
    """Return a cheap fingerprint for files that feed the alpha scanner."""
    files = []
    parts = []
    for filename in WATCHED_SOURCE_FILES:
        path = os.path.join(DATA_ROOT, filename)
        exists = os.path.isfile(path)
        if exists:
            try:
                stat = os.stat(path)
                modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                size = int(stat.st_size)
                mtime_ns = int(stat.st_mtime_ns)
            except OSError:
                exists = False
                modified_at = None
                size = 0
                mtime_ns = 0
        else:
            modified_at = None
            size = 0
            mtime_ns = 0
        policy = SOURCE_FILE_POLICIES.get(filename, {})
        files.append({
            'file': f'data/{filename}',
            'exists': exists,
            'size': size,
            'modified_at': modified_at,
            'mtime_ns': mtime_ns,
            'role': policy.get('role'),
            'required': bool(policy.get('required', True)),
            'alert_required': bool(policy.get('alert_required', policy.get('required', True))),
            'max_age_days': policy.get('max_age_days', 7),
        })
        parts.append(f'{filename}:{mtime_ns}:{size}:{int(exists)}')
    fingerprint = hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()
    return {
        'fingerprint': fingerprint,
        'files': files,
        'available_files': sum(1 for item in files if item['exists']),
        'missing_files': sum(1 for item in files if not item['exists']),
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


def read_scanner_monitor_state(state_path: str | None = None) -> dict[str, Any]:
    """Return realtime monitor state with current source signature."""
    state_file = state_path or _monitor_state_path()
    state = _read_monitor_state(state_file)
    return _monitor_state_summary(state, state_file, get_scanner_source_signature())


def get_alert_block_reason(run: dict[str, Any]) -> str | None:
    """Return the production alert block reason for a scanner run, if any."""
    return _alert_block_reason(run)


def run_scanner_realtime_monitor_check(
    payload: dict[str, Any] | None = None,
    *,
    monitor_state_path: str | None = None,
    alert_state_path: str | None = None,
    min_alpha: float = DEFAULT_ALERT_MIN_ALPHA,
    max_risk: float = DEFAULT_ALERT_MAX_RISK,
    max_events: int = DEFAULT_ALERT_MAX_EVENTS,
    retry_seconds: int = DEFAULT_MONITOR_RETRY_SECONDS,
    force: bool = False,
    commit_monitor_state: bool = True,
    send_fn=None,
) -> dict[str, Any]:
    """Run alert scan only when source files changed, then send Telegram.

    `send_fn` is injected by Flask/scheduler so tests can validate behavior
    without touching Telegram. Alert state is committed only after send_fn
    succeeds, preventing missed retry after Telegram/API failures.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    monitor_file = monitor_state_path or _monitor_state_path()
    state = _read_monitor_state(monitor_file)
    source = get_scanner_source_signature()
    fingerprint = source['fingerprint']

    state_version = int(state.get('version') or 0)
    if (
        not force
        and state_version >= MONITOR_STATE_VERSION
        and state.get('last_source_fingerprint') == fingerprint
    ):
        next_state = dict(state)
        next_state.update({
            'version': MONITOR_STATE_VERSION,
            'last_checked_at': now_iso,
            'last_status': 'unchanged',
            'last_new_event_count': 0,
            'last_telegram_sent': False,
            'last_error': None,
            'current_source': source,
        })
        if commit_monitor_state:
            write_json_atomic(monitor_file, next_state, sort_keys=True)
        return {
            'ok': True,
            'status': 'unchanged',
            'source_changed': False,
            'monitor_state': _monitor_state_summary(
                next_state if commit_monitor_state else state,
                monitor_file,
                source,
            ),
            'source': source,
            'new_event_count': 0,
            'telegram_sent': False,
            'state_committed': False,
            'monitor_state_committed': bool(commit_monitor_state),
        }

    failed_at = _parse_dt(state.get('last_failed_at'))
    if (
        not force
        and state.get('last_failed_source_fingerprint') == fingerprint
        and failed_at is not None
        and (now - failed_at).total_seconds() < max(1, int(retry_seconds))
    ):
        return {
            'ok': False,
            'status': 'retry_wait',
            'source_changed': True,
            'monitor_state': _monitor_state_summary(state, monitor_file, source),
            'source': source,
            'new_event_count': 0,
            'telegram_sent': False,
            'state_committed': False,
        }

    result = run_scanner_alert_check(
        payload or {},
        state_path=alert_state_path,
        min_alpha=min_alpha,
        max_risk=max_risk,
        max_events=max_events,
        commit_state=False,
    )
    events = result.get('events') or []
    alert_blocked = bool(result.get('alert_blocked'))
    telegram_sent = False
    state_committed = False
    alert_state = result.get('state')
    status = 'blocked' if alert_blocked else 'no_new_events'
    error = None

    if events:
        if send_fn is None:
            status = 'pending_send'
        else:
            try:
                telegram_sent = bool(send_fn(result.get('message') or ''))
            except Exception as exc:
                telegram_sent = False
                error = f'{type(exc).__name__}: {exc}'
            if telegram_sent:
                if commit_monitor_state:
                    alert_state = commit_scanner_alert_events(result)
                    state_committed = True
                else:
                    alert_state = result.get('state')
                status = 'sent'
            else:
                status = 'send_failed'
    else:
        if commit_monitor_state:
            alert_state = commit_scanner_alert_events(result)
            state_committed = True
        else:
            alert_state = result.get('state')

    processed = status in {'sent', 'no_new_events', 'blocked'}
    next_state = dict(state)
    next_state.update({
        'version': MONITOR_STATE_VERSION,
        'last_checked_at': now_iso,
        'last_status': status,
        'last_run_id': (result.get('run') or {}).get('id'),
        'last_candidate_count': (result.get('run') or {}).get('candidate_count'),
        'last_new_event_count': len(events),
        'last_telegram_sent': telegram_sent,
        'last_error': error,
        'current_source': source,
    })
    if processed:
        next_state['last_source_fingerprint'] = fingerprint
        next_state['last_processed_at'] = now_iso
        next_state.pop('last_failed_source_fingerprint', None)
        next_state.pop('last_failed_at', None)
    elif status == 'send_failed':
        next_state['last_failed_source_fingerprint'] = fingerprint
        next_state['last_failed_at'] = now_iso
    if commit_monitor_state:
        write_json_atomic(monitor_file, next_state, sort_keys=True)

    return {
        'ok': status in {'sent', 'no_new_events', 'blocked', 'pending_send'},
        'status': status,
        'source_changed': True,
        'source': source,
        'run': result.get('run'),
        'events': events,
        'message': result.get('message'),
        'new_event_count': len(events),
        'telegram_sent': telegram_sent,
        'state_committed': state_committed,
        'alert_state': alert_state,
        'monitor_state': _monitor_state_summary(
            next_state if commit_monitor_state else state,
            monitor_file,
            source,
        ),
        'monitor_state_committed': bool(commit_monitor_state),
        'alert_blocked': alert_blocked,
        'blocked_reason': result.get('blocked_reason'),
        'error': error,
    }


def run_scanner_alert_check(
    payload: dict[str, Any] | None = None,
    *,
    state_path: str | None = None,
    min_alpha: float = DEFAULT_ALERT_MIN_ALPHA,
    max_risk: float = DEFAULT_ALERT_MAX_RISK,
    actions: tuple[str, ...] = ('BUY_CANDIDATE',),
    max_events: int = DEFAULT_ALERT_MAX_EVENTS,
    commit_state: bool = True,
    block_on_stale: bool = True,
) -> dict[str, Any]:
    """Create a scanner run and return only newly-qualified alert events.

    The state file stores stable symbol/action/date keys so repeated checks do
    not spam Telegram. Scheduled senders should use commit_state=False and call
    commit_scanner_alert_events only after Telegram succeeds.
    """
    run_payload = dict(payload or {})
    run_payload.setdefault('limit', DEFAULT_ALERT_LIMIT)
    run = create_scanner_run(run_payload)
    state_file = state_path or _alert_state_path()
    state = _read_alert_state(state_file)
    freshness_status = ((run.get('freshness') or {}).get('status') or 'unknown').lower()
    blocked_reason = None
    if block_on_stale:
        blocked_reason = _alert_block_reason(run)
    if blocked_reason:
        events = []
    else:
        events = _new_candidate_events(
            run,
            state,
            min_alpha=float(min_alpha),
            max_risk=float(max_risk),
            actions=actions,
            max_events=max_events,
        )
    updated_state = _update_alert_state(state, run, events)
    if commit_state:
        write_json_atomic(state_file, updated_state, sort_keys=True)
    return {
        'run': run,
        'events': events,
        'message': build_scanner_alert_message(
            run,
            events,
            min_alpha=min_alpha,
            max_risk=max_risk,
            blocked_reason=blocked_reason,
        ),
        'state_path': state_file,
        'state_committed': bool(commit_state),
        'state': _alert_state_summary(updated_state, state_file),
        'new_event_count': len(events),
        'alert_blocked': bool(blocked_reason),
        'blocked_reason': blocked_reason,
        'source_warning': _source_warning(run, blocked_reason),
    }


def commit_scanner_alert_events(result: dict[str, Any]) -> dict[str, Any]:
    """Persist alert state after a scheduler/API sender has handled events."""
    state_file = str(result.get('state_path') or _alert_state_path())
    run = result.get('run') or {}
    events = [event for event in (result.get('events') or []) if isinstance(event, dict)]
    state = _read_alert_state(state_file)
    updated_state = _update_alert_state(state, run, events)
    write_json_atomic(state_file, updated_state, sort_keys=True)
    return _alert_state_summary(updated_state, state_file)


def build_scanner_alert_message(
    run: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    min_alpha: float = DEFAULT_ALERT_MIN_ALPHA,
    max_risk: float = DEFAULT_ALERT_MAX_RISK,
    blocked_reason: str | None = None,
) -> str:
    """Build the production Telegram alert with readable Korean labels."""
    return _build_scanner_alert_message_ko(
        run,
        events,
        min_alpha=min_alpha,
        max_risk=max_risk,
        blocked_reason=blocked_reason,
    )
    generated_at = _escape(run.get('generated_at') or '')
    run_id = _escape(run.get('id') or '')
    candidate_count = int(run.get('candidate_count') or 0)
    lines = [
        '<b>MiroFish 알파 스캐너 신규 후보</b>',
        f'신규 매수 후보: <b>{len(events)}</b>건 / 전체 후보: {candidate_count}건',
        f'기준: alpha &gt;= {min_alpha:g}, risk &lt;= {max_risk:g}, 로컬 데이터 아티팩트 기반',
        f'Run ID: <code>{run_id}</code>',
        f'생성 시각: {generated_at}',
    ]
    if blocked_reason:
        freshness_status = _escape((run.get('freshness') or {}).get('status') or 'unknown')
        lines.append(f'알림 차단: 원천 데이터 freshness={freshness_status}. 데이터 갱신 후 재시도하세요.')
        return '\n'.join(lines)
    if not events:
        lines.append('이전 알림 이후 새 조건 충족 후보가 없습니다.')
        return '\n'.join(lines)

    for event in events:
        candidate = event['candidate']
        evidence = (candidate.get('evidence') or [{}])[0]
        tags = ', '.join(_tag_label(tag) for tag in (candidate.get('strategy_tags') or [])[:4])
        price = candidate.get('price') or {}
        current_price = _format_number(price.get('current_price'))
        change_rate = _format_signed(price.get('change_rate'), suffix='%')
        lines.extend([
            '',
            (
                f"#{candidate.get('rank')} <b>{_escape(candidate.get('display_name'))}</b> "
                f"(<code>{_escape(candidate.get('symbol'))}</code> {_escape(candidate.get('market'))})"
            ),
            (
                f"알파 <b>{candidate.get('alpha_score')}</b> / "
                f"리스크 <b>{candidate.get('risk_score')}</b> / "
                f"랭킹 {candidate.get('ranking_score')}"
            ),
            (
                f"판정: <b>{_escape(_action_label(candidate.get('action')))}</b> / "
                f"기간: {_escape(_horizon_label(candidate.get('horizon')))}"
            ),
            f"현재가: {current_price} ({change_rate}) / 태그: {_escape(tags)}",
            (
                f"근거: {_escape(evidence.get('source'))} "
                f"{_escape(_evidence_field_label(evidence.get('field')))}={evidence.get('score')}"
            ),
        ])
    return '\n'.join(lines)


def build_scanner_run_telegram_message(run: dict[str, Any], *, limit: int = 10) -> str:
    """Build a deterministic Telegram summary directly from scanner candidates."""
    return _build_scanner_run_telegram_message_ko(run, limit=limit)
    clean_limit = max(1, min(_clean_limit(limit, default=10), 20))
    candidates = [item for item in (run.get('candidates') or []) if isinstance(item, dict)]
    generated_at = _escape(run.get('generated_at') or run.get('created_at') or '')
    run_id = _escape(run.get('id') or '')
    freshness = run.get('freshness') or {}
    freshness_status = freshness.get('status') if isinstance(freshness, dict) else ''
    lines = [
        '<b>MiroFish 알파 스캐너 요약</b>',
        f'Run ID: <code>{run_id}</code>',
        f'생성 시각: {generated_at}',
        f'후보 수: <b>{len(candidates)}</b> / freshness: {_escape(freshness_status or "unknown")}',
        'Source: deterministic scanner artifacts',
    ]
    if not candidates:
        lines.append('이 스캐너 run에는 후보가 없습니다.')
        return '\n'.join(lines)

    for candidate in candidates[:clean_limit]:
        evidence = (candidate.get('evidence') or [{}])[0]
        tags = ', '.join(_tag_label(tag) for tag in (candidate.get('strategy_tags') or [])[:4])
        price = candidate.get('price') or {}
        current_price = _format_number(price.get('current_price') or candidate.get('price'))
        change_rate = _format_signed(price.get('change_rate') or candidate.get('change_pct'), suffix='%')
        lines.extend([
            '',
            (
                f"#{_escape(candidate.get('rank'))} <b>{_escape(candidate.get('display_name'))}</b> "
                f"(<code>{_escape(candidate.get('symbol'))}</code> {_escape(candidate.get('market'))})"
            ),
            (
                f"Alpha <b>{_escape(candidate.get('alpha_score'))}</b> / "
                f"Risk <b>{_escape(candidate.get('risk_score'))}</b> / "
                f"Rank score {_escape(candidate.get('ranking_score'))}"
            ),
            (
                f"판정: <b>{_escape(_action_label(candidate.get('action')))}</b> / "
                f"기간: {_escape(_horizon_label(candidate.get('horizon')))}"
            ),
            f"현재가: {current_price} ({change_rate}) / 태그: {_escape(tags)}",
            (
                f"근거: {_escape(evidence.get('source'))} "
                f"{_escape(_evidence_field_label(evidence.get('field')))}={_escape(evidence.get('score'))}"
            ),
        ])
    return '\n'.join(lines)


def _build_scanner_alert_message_ko(
    run: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    min_alpha: float = DEFAULT_ALERT_MIN_ALPHA,
    max_risk: float = DEFAULT_ALERT_MAX_RISK,
    blocked_reason: str | None = None,
) -> str:
    """Build the production Telegram alert with readable Korean labels."""
    generated_at = _escape(run.get('generated_at') or '')
    run_id = _escape(run.get('id') or '')
    candidate_count = int(run.get('candidate_count') or 0)
    lines = [
        '<b>MiroFish 알파 스캐너 신규 후보</b>',
        f'신규 매수 후보: <b>{len(events)}</b>건 / 전체 후보: {candidate_count}건',
        f'기준: alpha &gt;= {min_alpha:g}, risk &lt;= {max_risk:g}, 로컬 데이터 아티팩트 기반',
        f'Run ID: <code>{run_id}</code>',
        f'생성 시각: {generated_at}',
    ]
    if blocked_reason:
        freshness_status = _escape((run.get('freshness') or {}).get('status') or 'unknown')
        lines.append(f'알림 차단: 원천 데이터 freshness={freshness_status}. 데이터 갱신 후 재시도하세요.')
        return '\n'.join(lines)
    if not events:
        lines.append('이전 알림 이후 새 조건 충족 후보가 없습니다.')
        return '\n'.join(lines)

    for event in events:
        candidate = event['candidate']
        evidence = (candidate.get('evidence') or [{}])[0]
        tags = ', '.join(_tag_label(tag) for tag in (candidate.get('strategy_tags') or [])[:4])
        price = candidate.get('price') or {}
        current_price = _format_number(price.get('current_price'))
        change_rate = _format_signed(price.get('change_rate'), suffix='%')
        lines.extend([
            '',
            (
                f"#{candidate.get('rank')} <b>{_escape(candidate.get('display_name'))}</b> "
                f"(<code>{_escape(candidate.get('symbol'))}</code> {_escape(candidate.get('market'))})"
            ),
            (
                f"알파 <b>{candidate.get('alpha_score')}</b> / "
                f"리스크 <b>{candidate.get('risk_score')}</b> / "
                f"랭킹 {candidate.get('ranking_score')}"
            ),
            (
                f"판정: <b>{_escape(_action_label(candidate.get('action')))}</b> / "
                f"기간: {_escape(_horizon_label(candidate.get('horizon')))}"
            ),
            f"현재가: {current_price} ({change_rate}) / 태그: {_escape(tags)}",
            (
                f"근거: {_escape(evidence.get('source'))} "
                f"{_escape(_evidence_field_label(evidence.get('field')))}={evidence.get('score')}"
            ),
        ])
    return '\n'.join(lines)


def _build_scanner_run_telegram_message_ko(run: dict[str, Any], *, limit: int = 10) -> str:
    """Build a deterministic Telegram summary directly from scanner candidates."""
    clean_limit = max(1, min(_clean_limit(limit, default=10), 20))
    candidates = [item for item in (run.get('candidates') or []) if isinstance(item, dict)]
    generated_at = _escape(run.get('generated_at') or run.get('created_at') or '')
    run_id = _escape(run.get('id') or '')
    freshness = run.get('freshness') or {}
    freshness_status = freshness.get('status') if isinstance(freshness, dict) else ''
    lines = [
        '<b>MiroFish 알파 스캐너 요약</b>',
        f'Run ID: <code>{run_id}</code>',
        f'생성 시각: {generated_at}',
        f'후보 수: <b>{len(candidates)}</b> / freshness: {_escape(freshness_status or "unknown")}',
        'Source: deterministic scanner artifacts',
    ]
    if not candidates:
        lines.append('이번 scanner run에는 후보가 없습니다.')
        return '\n'.join(lines)

    for candidate in candidates[:clean_limit]:
        evidence = (candidate.get('evidence') or [{}])[0]
        tags = ', '.join(_tag_label(tag) for tag in (candidate.get('strategy_tags') or [])[:4])
        price = candidate.get('price') or {}
        current_price = _format_number(price.get('current_price') or candidate.get('price'))
        change_rate = _format_signed(price.get('change_rate') or candidate.get('change_pct'), suffix='%')
        lines.extend([
            '',
            (
                f"#{_escape(candidate.get('rank'))} <b>{_escape(candidate.get('display_name'))}</b> "
                f"(<code>{_escape(candidate.get('symbol'))}</code> {_escape(candidate.get('market'))})"
            ),
            (
                f"Alpha <b>{_escape(candidate.get('alpha_score'))}</b> / "
                f"Risk <b>{_escape(candidate.get('risk_score'))}</b> / "
                f"Rank score {_escape(candidate.get('ranking_score'))}"
            ),
            (
                f"판정: <b>{_escape(_action_label(candidate.get('action')))}</b> / "
                f"기간: {_escape(_horizon_label(candidate.get('horizon')))}"
            ),
            f"현재가: {current_price} ({change_rate}) / 태그: {_escape(tags)}",
            (
                f"근거: {_escape(evidence.get('source'))} "
                f"{_escape(_evidence_field_label(evidence.get('field')))}={_escape(evidence.get('score'))}"
            ),
        ])
    return '\n'.join(lines)


def _load_artifacts() -> dict[str, Any]:
    source_artifacts = _load_source_artifacts()
    screener = source_artifacts['screener']
    vcp = source_artifacts['vcp']
    jongga = source_artifacts['jongga']

    maps = _load_ticker_map()
    candidate_symbols = set()
    candidate_symbols.update(_symbols_from_screener(screener.get('data')))
    candidate_symbols.update(_symbols_from_vcp(vcp.get('data')))
    candidate_symbols.update(_symbols_from_jongga(jongga.get('data')))

    price_history = _load_price_history(candidate_symbols or None)
    latest_prices = {
        symbol: rows[-1]
        for symbol, rows in price_history.items()
        if rows
    }
    if not candidate_symbols:
        candidate_symbols.update(latest_prices.keys())
    tradingview = tradingview_provider.load_enrichment_for_symbols(
        candidate_symbols,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    institutional_trend = _load_institutional_trend_data()
    kind_blacklist = blacklist_service.get_kind_blacklist(
        data_root=DATA_ROOT,
        allow_fetch=_kind_live_fetch_enabled(),
    )
    credit_balance = credit_balance_service.get_credit_balance_snapshot(
        data_root=DATA_ROOT,
        allow_fetch=_credit_live_fetch_enabled(),
    )
    rs_ratings = sector_rs_service.get_rs_ratings(data_root=DATA_ROOT)
    kis_live = _load_indexed_resource_artifact('kis_live_snapshot_latest.json')
    dart_events = _load_indexed_resource_artifact('dart_event_latest.json')
    news_theme_social = _load_indexed_resource_artifact('news_theme_social_latest.json')

    return {
        'ticker_map': maps,
        'daily_prices': latest_prices,
        'price_history': price_history,
        'screener': screener,
        'vcp': vcp,
        'jongga': jongga,
        'tradingview': tradingview,
        'institutional_trend': institutional_trend,
        'kind_blacklist': kind_blacklist,
        'credit_balance': credit_balance,
        'rs_ratings': rs_ratings,
        'kis_live': kis_live,
        'dart_events': dart_events,
        'news_theme_social': news_theme_social,
        'candidate_symbols': candidate_symbols,
    }


def _load_source_artifacts() -> dict[str, Any]:
    return {
        'screener': _load_json_artifact('screener_leading_latest.json'),
        'vcp': _load_json_artifact('vcp_kr_latest.json'),
        'jongga': _load_json_artifact('jongga_v2_latest.json'),
        'kind_blacklist': _load_json_artifact('kind_blacklist_latest.json'),
        'credit_balance': _load_json_artifact('credit_balance_latest.json'),
        'rs_ratings': _load_json_artifact('alpha_rs_ratings.json'),
        'kis_live': _load_json_artifact('kis_live_snapshot_latest.json'),
        'dart_events': _load_json_artifact('dart_event_latest.json'),
        'news_theme_social': _load_json_artifact('news_theme_social_latest.json'),
    }


def _build_candidates(
    artifacts: dict[str, Any],
    *,
    generated_at: str,
    limit: int,
    requested_symbols: set[str],
    performance_advisory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return _select_candidates(
        _build_candidate_pool(
            artifacts,
            generated_at=generated_at,
            requested_symbols=requested_symbols,
            performance_advisory=performance_advisory,
        ),
        limit,
    )


def _build_candidate_pool(
    artifacts: dict[str, Any],
    *,
    generated_at: str,
    requested_symbols: set[str],
    performance_advisory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    maps = artifacts['ticker_map']
    prices = artifacts['daily_prices']
    screener_by_symbol = _index_screener(artifacts['screener'].get('data'))
    vcp_by_symbol = _index_vcp(artifacts['vcp'].get('data'))
    jongga_by_symbol = _index_jongga(artifacts['jongga'].get('data'))
    tradingview_by_symbol = (artifacts.get('tradingview') or {}).get('signals_by_symbol') or {}
    institutional_by_symbol = artifacts.get('institutional_trend') or {}
    kind_blacklist_by_symbol = (artifacts.get('kind_blacklist') or {}).get('entries') or {}
    credit_balance_by_symbol = (artifacts.get('credit_balance') or {}).get('entries') or {}
    rs_by_symbol = (artifacts.get('rs_ratings') or {}).get('entries') or {}
    kis_live_by_symbol = artifacts.get('kis_live') or {}
    dart_events_by_symbol = artifacts.get('dart_events') or {}
    news_theme_social_by_symbol = artifacts.get('news_theme_social') or {}
    allow_live_kis = _scanner_kis_live_enabled() and bool(requested_symbols) and len(requested_symbols) <= 10

    symbols = set(artifacts['candidate_symbols'])
    if requested_symbols:
        symbols = {symbol for symbol in symbols if symbol in requested_symbols}
        symbols.update(requested_symbols)

    rows = []
    for symbol in sorted(symbols):
        mapped = maps.get(symbol) or {}
        kis_live = kis_live_by_symbol.get(symbol)
        if not kis_live and allow_live_kis and symbol in requested_symbols:
            kis_live = _fetch_kis_live_snapshot_for_symbol(symbol, mapped)
        candidate = _score_symbol(
            symbol,
            mapped,
            prices.get(symbol) or {},
            (artifacts.get('price_history') or {}).get(symbol) or [],
            screener_by_symbol.get(symbol),
            vcp_by_symbol.get(symbol),
            jongga_by_symbol.get(symbol),
            tradingview_by_symbol.get(symbol),
            institutional_by_symbol.get(symbol),
            kind_blacklist_by_symbol.get(symbol),
            credit_balance_by_symbol.get(symbol),
            kis_live,
            dart_events_by_symbol.get(symbol),
            news_theme_social_by_symbol.get(symbol),
            artifacts,
            generated_at,
            performance_advisory or {},
            rs_rating=rs_by_symbol.get(symbol),
        )
        rows.append(candidate)

    rows.sort(
        key=lambda item: (
            item['ranking_score'],
            item['alpha_score'],
            -item['risk_score'],
            item['symbol'],
        ),
        reverse=True,
    )
    for index, item in enumerate(rows, start=1):
        item['pool_rank'] = index
    return rows


def _maybe_deepseek_rerank_candidates(
    rows: list[dict[str, Any]],
    *,
    payload: dict[str, Any],
    generated_at: str,
    requested_symbols: set[str],
    limit: int,
) -> dict[str, Any]:
    enabled = _payload_bool(payload, 'deepseek_rerank', _deepseek_rerank_enabled())
    max_items = _clean_limit(
        payload.get('deepseek_rerank_limit') or os.getenv('MIROFISH_DEEPSEEK_RERANK_LIMIT'),
        default=max(20, min(60, limit * 3)),
        max_value=60,
    )
    max_adjustment = _float(payload.get('deepseek_max_adjustment') or os.getenv('MIROFISH_DEEPSEEK_MAX_ADJUSTMENT', '8'))
    max_adjustment = _clamp(max_adjustment, 0, 12)
    model = str(payload.get('deepseek_model') or os.getenv('MIROFISH_DEEPSEEK_RERANK_MODEL') or '').strip() or None
    base = {
        'enabled': bool(enabled),
        'applied': False,
        'status': 'disabled',
        'provider': 'deepseek',
        'model': model or os.getenv('MIROFISH_DEEPSEEK_MODEL', 'deepseek-v4-pro'),
        'candidate_count': 0,
        'adjusted_count': 0,
        'max_abs_adjustment': max_adjustment,
        'schema_version': 'mirofish.deepseek_rerank.v1',
    }
    if not enabled:
        return base
    if not rows:
        return {**base, 'status': 'empty_candidate_pool'}
    try:
        from app.services.mirofish import deepseek_client

        result = deepseek_client.rerank_scanner_candidates(
            rows,
            run_context={
                'generated_at': generated_at,
                'requested_symbols': sorted(requested_symbols),
                'base_ranking': 'alpha_score - 0.55*risk_score + deterministic conviction_adjustment',
                'lookahead_safe': True,
            },
            limit=max_items,
            model=model,
            max_adjustment=max_adjustment,
        )
    except Exception as exc:
        retry_limit = max(1, min(max_items, max(limit, 5)))
        if retry_limit < max_items:
            try:
                result = deepseek_client.rerank_scanner_candidates(
                    rows,
                    run_context={
                        'generated_at': generated_at,
                        'requested_symbols': sorted(requested_symbols),
                        'base_ranking': 'alpha_score - 0.55*risk_score + deterministic conviction_adjustment',
                        'lookahead_safe': True,
                        'retry_reason': f'{type(exc).__name__}: {exc}',
                        'retry_mode': 'compact_limit',
                    },
                    limit=retry_limit,
                    model=model,
                    max_adjustment=max_adjustment,
                )
            except Exception as retry_exc:
                return {
                    **base,
                    'status': 'error',
                    'error': f'{type(retry_exc).__name__}: {retry_exc}',
                    'initial_error': f'{type(exc).__name__}: {exc}',
                }
            else:
                base['status'] = 'applied_retry_compact'
                base['initial_error'] = f'{type(exc).__name__}: {exc}'
        else:
            return {
                **base,
                'status': 'error',
                'error': f'{type(exc).__name__}: {exc}',
            }
    overlay = result.get('overlay') if isinstance(result, dict) else {}
    items = overlay.get('items') if isinstance(overlay, dict) else []
    if not isinstance(items, list):
        items = []
    return {
        **base,
        'applied': bool(items),
        'status': (
            'applied_retry_compact'
            if base.get('status') == 'applied_retry_compact' and items
            else 'empty_overlay_retry_compact'
            if base.get('status') == 'applied_retry_compact'
            else 'applied'
            if items
            else 'empty_overlay'
        ),
        'model': result.get('model') or base['model'],
        'candidate_count': result.get('candidate_count') or len(rows[:max_items]),
        'adjusted_count': len(items),
        'usage': result.get('usage'),
        'finish_reason': result.get('finish_reason'),
        'created_at': result.get('created_at'),
        'initial_error': base.get('initial_error'),
        'portfolio_note_ko': (overlay or {}).get('portfolio_note_ko') or '',
        'items': items,
    }


def _apply_deepseek_rerank_overlay(
    rows: list[dict[str, Any]],
    overlay: dict[str, Any],
) -> list[dict[str, Any]]:
    if not overlay.get('applied'):
        return rows
    max_adjustment = _float(overlay.get('max_abs_adjustment') or 8)
    by_symbol = {}
    for item in overlay.get('items') or []:
        if not isinstance(item, dict):
            continue
        symbol = _symbol(item.get('symbol'))
        if symbol:
            by_symbol[symbol] = item
    if not by_symbol:
        overlay['applied'] = False
        overlay['status'] = 'no_matching_symbols'
        return rows

    adjusted = 0
    for candidate in rows:
        symbol = _symbol(candidate.get('symbol'))
        item = by_symbol.get(symbol)
        if not item:
            continue
        adjustment = _clamp(_float(item.get('ranking_adjustment')), -max_adjustment, max_adjustment)
        conviction = _clamp(_float(item.get('deepseek_conviction')), 0, 100)
        risk_flags = [str(flag)[:80] for flag in (item.get('risk_flags') or []) if isinstance(flag, (str, int, float))][:6]
        positive_evidence = [
            str(value)[:100]
            for value in (item.get('positive_evidence') or [])
            if isinstance(value, (str, int, float))
        ][:6]
        rationale = str(item.get('rationale_ko') or '').strip()[:240]
        candidate['ranking_score'] = round(_float(candidate.get('ranking_score')) + adjustment, 2)
        candidate.setdefault('strategy_tags', [])
        if adjustment > 0 and 'deepseek_v4_confirmed' not in candidate['strategy_tags']:
            candidate['strategy_tags'].append('deepseek_v4_confirmed')
        elif adjustment < 0 and 'deepseek_v4_risk_flag' not in candidate['strategy_tags']:
            candidate['strategy_tags'].append('deepseek_v4_risk_flag')
        candidate['evidence'] = list(candidate.get('evidence') or []) + [
            _evidence('deepseek_v4', 'rerank_adjustment', adjustment, {
                'conviction': conviction,
                'risk_flags': risk_flags,
                'positive_evidence': positive_evidence,
                'rationale_ko': rationale,
            })
        ]
        profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
        profile['deepseek_rerank'] = {
            'applied': True,
            'model': overlay.get('model'),
            'ranking_adjustment': round(adjustment, 2),
            'deepseek_conviction': round(conviction, 2),
            'risk_flags': risk_flags,
            'positive_evidence': positive_evidence,
            'rationale_ko': rationale,
            'lookahead_safe': True,
        }
        candidate['analysis_profile'] = profile
        adjusted += 1

    rows.sort(
        key=lambda item: (
            item['ranking_score'],
            item['alpha_score'],
            -item['risk_score'],
            item['symbol'],
        ),
        reverse=True,
    )
    for index, item in enumerate(rows, start=1):
        item['pool_rank'] = index
    overlay['adjusted_count'] = adjusted
    return rows


def _deepseek_rerank_provider_status(overlay: dict[str, Any]) -> dict[str, Any]:
    return {
        'provider': 'deepseek',
        'enabled': bool(overlay.get('enabled')),
        'status': overlay.get('status') or 'unknown',
        'applied': bool(overlay.get('applied')),
        'model': overlay.get('model'),
        'candidate_count': overlay.get('candidate_count'),
        'adjusted_count': overlay.get('adjusted_count'),
        'max_abs_adjustment': overlay.get('max_abs_adjustment'),
        'error': overlay.get('error'),
    }


def _deepseek_rerank_enabled() -> bool:
    return _truthy(os.getenv('MIROFISH_DEEPSEEK_RERANK_ENABLED', '0'))


def _select_candidates(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected = rows[:limit]
    for index, item in enumerate(selected, start=1):
        item['rank'] = index
    return selected


def _rejected_candidates(
    rows: list[dict[str, Any]],
    *,
    selected_count: int,
    limit: int,
) -> list[dict[str, Any]]:
    rejected = []
    for index, candidate in enumerate(rows, start=1):
        reasons = _rejection_reasons(candidate, index=index, selected_count=selected_count, limit=limit)
        if not reasons:
            continue
        rejected.append({
            'pool_rank': candidate.get('pool_rank') or index,
            'symbol': candidate.get('symbol'),
            'name': candidate.get('name') or candidate.get('display_name'),
            'display_name': candidate.get('display_name') or candidate.get('name'),
            'market': candidate.get('market'),
            'action': candidate.get('action'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
            'ranking_score': candidate.get('ranking_score'),
            'signal_quality': candidate.get('signal_quality'),
            'strategy_tags': candidate.get('strategy_tags') or [],
            'rejection_reasons': reasons,
            'feature_vector': _feature_vector(candidate),
            'evidence': candidate.get('evidence') or [],
            'evidence_quality': (candidate.get('analysis_profile') or {}).get('evidence_quality'),
            'freshness': candidate.get('freshness'),
            'price': candidate.get('price'),
            'replay_context': candidate.get('replay_context'),
        })
    return rejected


def _rejection_reasons(
    candidate: dict[str, Any],
    *,
    index: int,
    selected_count: int,
    limit: int,
) -> list[str]:
    reasons = []
    if index > max(0, int(limit)):
        reasons.append('outside_requested_limit')
    if str(candidate.get('action') or '') == 'REJECT':
        reasons.append('scanner_action_reject')
    if _float(candidate.get('alpha_score')) < 50:
        reasons.append('alpha_below_watch_threshold')
    if _float(candidate.get('risk_score')) > 65:
        reasons.append('risk_above_watch_threshold')
    profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
    false_signal_gates = profile.get('false_signal_gates') if isinstance(profile.get('false_signal_gates'), dict) else {}
    for blocker in false_signal_gates.get('hard_blockers') or []:
        reasons.append(f'false_signal:{blocker}')
    if _float(profile.get('source_count')) < 3:
        reasons.append('insufficient_source_confirmation')
    if str(((candidate.get('freshness') or {}).get('status') or '')).lower() in ALERT_BLOCKING_FRESHNESS:
        reasons.append('source_freshness_not_confirmed')
    if index > selected_count and 'outside_requested_limit' not in reasons:
        reasons.append('not_selected')
    return reasons


def _score_symbol(
    symbol: str,
    mapped: dict[str, Any],
    price: dict[str, Any],
    price_history: list[dict[str, Any]],
    screener: dict[str, Any] | None,
    vcp: dict[str, Any] | None,
    jongga: dict[str, Any] | None,
    tradingview: dict[str, Any] | None,
    institutional: dict[str, Any] | None,
    kind_blacklist: dict[str, Any] | None,
    credit_balance: dict[str, Any] | None,
    kis_live: dict[str, Any] | None,
    dart_event: dict[str, Any] | None,
    news_theme_social: dict[str, Any] | None,
    artifacts: dict[str, Any],
    generated_at: str,
    performance_advisory: dict[str, Any],
    *,
    rs_rating: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = []
    kis_overlay = _kis_live_overlay(price, kis_live)
    if kis_overlay.get('applied'):
        price = kis_overlay['price']
    change_rate = _float(price.get('change_rate'))
    trading_value = _float(price.get('trading_value'))
    current_price = _float(price.get('current_price'))
    volume = _float(price.get('volume'))
    if not trading_value and current_price and volume:
        trading_value = current_price * volume

    price_metrics = _price_analysis(price_history, price)
    price_momentum = _clamp(change_rate * 1.7 if change_rate > 0 else 0, 0, 15)
    trend_quality = _float(price_metrics.get('trend_score'))
    volume_accumulation = _float(price_metrics.get('volume_accumulation_score'))
    liquidity = _clamp(trading_value / 20_000_000_000 * 10, 0, 10)
    alpha = price_momentum + trend_quality + liquidity + volume_accumulation
    evidence.append(_evidence('daily_prices.csv', 'price_momentum', price_momentum, change_rate))
    evidence.append(_evidence('daily_prices.csv', 'trend_quality', trend_quality, price_metrics.get('trend_20d_pct')))
    evidence.append(_evidence('daily_prices.csv', 'volume_accumulation', volume_accumulation, price_metrics.get('volume_ratio')))
    evidence.append(_evidence('daily_prices.csv', 'liquidity', liquidity, trading_value))

    screener_score = 0.0
    if screener:
        raw = _nested_float(screener, ['score', 'total_enriched'])
        if raw <= 0:
            raw = _nested_float(screener, ['score', 'total'])
        screener_score = _clamp(raw / 100 * 20, 0, 20)
        alpha += screener_score
        evidence.append(_evidence('screener_leading_latest.json', 'screener_leading', screener_score, raw))

    vcp_score = 0.0
    if vcp:
        raw = _nested_float(vcp, ['composite', 'composite_score'])
        entry_ready = _truthy(_nested_get(vcp, ['composite', 'entry_ready']))
        vcp_score = _clamp(raw / 100 * 13, 0, 13) + (2 if entry_ready else 0)
        alpha += vcp_score
        evidence.append(_evidence('vcp_kr_latest.json', 'vcp_quality', vcp_score, raw))

    jongga_score = 0.0
    if jongga:
        raw = _nested_float(jongga, ['score', 'total'])
        jongga_score = _clamp(raw / 15 * 10, 0, 10)
        alpha += jongga_score
        evidence.append(_evidence('jongga_v2_latest.json', 'jongga_setup', jongga_score, raw))

    source_count = _source_count(price, screener, vcp, jongga)
    convergence_score = _source_convergence_score(
        source_count=source_count,
        trend_quality=trend_quality,
        volume_accumulation=volume_accumulation,
        screener_score=screener_score,
        vcp_score=vcp_score,
        jongga_score=jongga_score,
    )
    alpha += convergence_score
    evidence.append(_evidence('source_convergence', 'source_convergence', convergence_score, source_count))

    intraday_range = 0.0
    if current_price:
        intraday_range = max(0.0, (_float(price.get('high')) - _float(price.get('low'))) / current_price * 100)
    risk = 0.0
    risk += _clamp(abs(change_rate) - 12, 0, 18)
    risk += _clamp(intraday_range * 1.7, 0, 24)
    risk += _float(price_metrics.get('volatility_risk'))
    risk += _float(price_metrics.get('drawdown_risk'))
    risk += _float(price_metrics.get('overextension_risk'))
    if trading_value <= 0:
        risk += 18
    elif trading_value < 2_000_000_000:
        risk += 10
    risk += _source_gap_penalty(price, screener, vcp, jongga)
    staleness_penalty = _staleness_penalty(artifacts, generated_at)
    risk += staleness_penalty
    risk += _negative_flag_penalty(jongga)

    base_alpha = alpha
    base_risk = risk
    tradingview_adjustment = tradingview_provider.score_signal(tradingview, price_metrics)
    if tradingview_adjustment.get('applied'):
        alpha += _float(tradingview_adjustment.get('alpha_delta'))
        risk += _float(tradingview_adjustment.get('risk_delta'))
        evidence.append(_evidence(
            'tradingview_mcp',
            'technical_alignment',
            tradingview_adjustment.get('alpha_delta'),
            tradingview_adjustment.get('recommendation'),
        ))
    flow_confirmation = _institutional_flow_confirmation(institutional)
    if flow_confirmation.get('passed'):
        alpha += 2.0
        evidence.append(_evidence(
            'all_institutional_trend_data.csv',
            'foreign_institution_dual_buy_5d',
            2.0,
            flow_confirmation.get('value'),
        ))
    rs_adjustment = sector_rs_service.score_rs_adjustment(rs_rating)
    if rs_adjustment.get('alpha_delta'):
        alpha += _float(rs_adjustment.get('alpha_delta'))
        evidence.append(_evidence(
            'alpha_rs_ratings.json',
            'relative_strength',
            rs_adjustment.get('alpha_delta'),
            rs_adjustment.get('rs_rating'),
        ))
    source_freshness = _symbol_freshness(artifacts)
    mcp_adjustment = _mcp_quality_adjustment(
        price=price,
        kis_live=kis_live,
        kis_overlay=kis_overlay,
        institutional=institutional,
        flow_confirmation=flow_confirmation,
        dart_event=dart_event,
        news_theme_social=news_theme_social,
        freshness=source_freshness,
        performance_advisory=performance_advisory,
    )
    alpha += _float(mcp_adjustment.get('alpha_delta'))
    risk += _float(mcp_adjustment.get('risk_delta'))
    evidence.extend(mcp_adjustment.get('evidence') or [])
    risk = round(_clamp(risk, 0, 100), 2)

    alpha = round(_clamp(alpha, 0, 100), 2)
    effective_source_count = (
        source_count
        + (1 if tradingview_adjustment.get('applied') else 0)
        + (1 if institutional else 0)
        + int(_float(mcp_adjustment.get('source_count_delta')))
    )
    conviction_adjustment = _conviction_adjustment(alpha, risk, effective_source_count, price_metrics)
    action = _action(alpha, risk)
    tags = _strategy_tags(
        price_momentum,
        trend_quality,
        volume_accumulation,
        screener_score,
        vcp_score,
        jongga_score,
        risk,
    )
    if tradingview_adjustment.get('applied'):
        tags.append('tradingview_confirmed' if _float(tradingview_adjustment.get('alpha_delta')) >= 0 else 'tradingview_warning')
    if flow_confirmation.get('passed'):
        tags.append('dual_flow_buy')
    if rs_adjustment.get('tag') and rs_adjustment['tag'] not in tags:
        tags.append(rs_adjustment['tag'])
    for tag in mcp_adjustment.get('tags') or []:
        if tag not in tags:
            tags.append(tag)
    tag_memory = _performance_tag_memory_adjustment(performance_advisory, tags)
    if tag_memory.get('applied'):
        mcp_adjustment['ranking_delta'] = round(_float(mcp_adjustment.get('ranking_delta')) + _float(tag_memory.get('ranking_delta')), 2)
        perf_memory = mcp_adjustment.get('performance_memory') if isinstance(mcp_adjustment.get('performance_memory'), dict) else {}
        perf_memory['tag_adjustment'] = tag_memory
        perf_memory['applied'] = True
        mcp_adjustment['performance_memory'] = perf_memory
        evidence.append(_evidence('workflow_outcomes', 'tag_hit_rate_adjustment', tag_memory['ranking_delta'], tag_memory))
        if 'outcome_tag_memory_adjusted' not in tags:
            tags.append('outcome_tag_memory_adjusted')
    mcp_ranking_delta = _float(mcp_adjustment.get('ranking_delta'))
    ranking_score = round(alpha - (0.55 * risk) + conviction_adjustment + mcp_ranking_delta, 2)
    signal_quality = _signal_quality(alpha, risk, effective_source_count, price_metrics)
    entry_plan = _entry_plan(current_price, risk, price_metrics, action)
    clean_evidence = [item for item in evidence if item['score'] > 0 or item['value'] not in (None, 0)]
    evidence_quality = _evidence_quality(
        clean_evidence,
        source_count=effective_source_count,
        freshness=source_freshness,
        risk=risk,
    )
    confidence_cap = _confidence_cap(
        source_count=effective_source_count,
        freshness=source_freshness,
        risk=risk,
    )
    data_sources = _candidate_sources(
        price,
        screener,
        vcp,
        jongga,
        tradingview_adjustment,
        institutional,
        kind_blacklist,
        credit_balance,
        kis_live,
        dart_event,
        news_theme_social,
    )
    profitability_scorecard = _profitability_scorecard(
        alpha=alpha,
        risk=risk,
        action=action,
        source_count=effective_source_count,
        data_sources=data_sources,
        evidence_quality=evidence_quality,
        confidence_cap=confidence_cap,
        freshness=source_freshness,
        entry_plan=entry_plan,
        price_metrics=price_metrics,
        trading_value=trading_value,
        current_price=current_price,
    )

    display_name = (
        mapped.get('display_name')
        or mapped.get('name')
        or price.get('name')
        or (screener or {}).get('name')
        or (vcp or {}).get('name')
        or (jongga or {}).get('stock_name')
        or symbol
    )

    candidate = {
        'rank': None,
        'symbol': symbol,
        'name': display_name,
        'display_name': display_name,
        'market': mapped.get('market') or (jongga or {}).get('market') or (vcp or {}).get('market') or 'KR',
        'alpha_score': alpha,
        'risk_score': risk,
        'ranking_score': ranking_score,
        'action': action,
        'horizon': 'swing_5_20d' if action in ('BUY_CANDIDATE', 'WATCH') else 'avoid_or_recheck',
        'signal_quality': signal_quality,
        'strategy_tags': tags,
        'evidence': clean_evidence,
        'analysis_profile': {
            'source_count': effective_source_count,
            'base_source_count': source_count,
            'base_alpha_score': round(base_alpha, 2),
            'base_risk_score': round(base_risk, 2),
            'convergence_score': round(convergence_score, 2),
            'conviction_adjustment': round(conviction_adjustment, 2),
            'mcp_ranking_delta': round(mcp_ranking_delta, 2),
            'tradingview_adjustment': tradingview_adjustment if tradingview_adjustment.get('available') else {'available': False},
            'capital_flow_confirmation': flow_confirmation,
            'kis_live_overlay': kis_overlay,
            'mcp_quality_adjustment': mcp_adjustment,
            'performance_memory': mcp_adjustment.get('performance_memory'),
            'trend_quality': round(trend_quality, 2),
            'volume_accumulation': round(volume_accumulation, 2),
            'volatility_20d_pct': price_metrics.get('volatility_20d_pct'),
            'trend_5d_pct': price_metrics.get('trend_5d_pct'),
            'trend_20d_pct': price_metrics.get('trend_20d_pct'),
            'volume_ratio': price_metrics.get('volume_ratio'),
            'drawdown_20d_pct': price_metrics.get('drawdown_20d_pct'),
            'over_ma20_pct': price_metrics.get('over_ma20_pct'),
            'trend_consistency': price_metrics.get('trend_consistency'),
            'sample_days': price_metrics.get('sample_days'),
            'evidence_quality': evidence_quality,
            'confidence_cap': confidence_cap,
            'profitability_scorecard': profitability_scorecard,
            'freshness_penalty': round(staleness_penalty, 2),
            'freshness_status': source_freshness.get('status'),
        },
        'entry_plan': entry_plan,
        'replay_context': {
            'price_date': price.get('date'),
            'generated_at': generated_at,
            'data_sources': data_sources,
            'lookahead_safe': True,
        },
        'price': {
            'date': price.get('date'),
            'current_price': current_price,
            'change_rate': change_rate,
            'volume': volume,
            'trading_value': trading_value,
        },
        'generated_at': generated_at,
        'source': 'local_marketflow_artifacts',
        'freshness': source_freshness,
        'tradingview': tradingview_adjustment,
    }
    return _apply_false_signal_gates(
        candidate,
        price=price,
        price_metrics=price_metrics,
        jongga=jongga,
        institutional=institutional,
        blacklist_entry=kind_blacklist,
        credit_entry=credit_balance,
    )


def _load_ticker_map() -> dict[str, dict[str, Any]]:
    path = os.path.join(DATA_ROOT, 'ticker_to_yahoo_map.csv')
    rows: dict[str, dict[str, Any]] = {}
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                for row in csv.DictReader(f):
                    symbol = _symbol(row.get('ticker'))
                    if symbol:
                        rows[symbol] = {
                            'symbol': symbol,
                            'market': row.get('market') or 'KR',
                            'yahoo_ticker': row.get('yahoo_ticker') or '',
                            'display_name': _clean_name(row.get('name')) or symbol,
                        }
        except (OSError, csv.Error, UnicodeDecodeError):
            rows = {}

    for symbol, canonical in _load_canonical_stock_names().items():
        item = rows.setdefault(symbol, {
            'symbol': symbol,
            'market': canonical.get('market') or 'KR',
            'yahoo_ticker': '',
            'display_name': symbol,
        })
        if canonical.get('display_name'):
            item['display_name'] = canonical['display_name']
        if canonical.get('market') and item.get('market') in (None, '', 'KR'):
            item['market'] = canonical['market']
    return rows


def _load_canonical_stock_names() -> dict[str, dict[str, str]]:
    path = os.path.join(DATA_ROOT, 'korean_stocks_list.csv')
    rows: dict[str, dict[str, str]] = {}
    if not os.path.isfile(path):
        return rows
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                symbol = _symbol(row.get('ticker') or row.get('code') or row.get('symbol'))
                name = _clean_name(row.get('name') or row.get('stock_name') or row.get('display_name'))
                if symbol and name:
                    rows[symbol] = {
                        'display_name': name,
                        'market': _clean_name(row.get('market')) or 'KR',
                    }
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return rows


def _load_price_history(symbol_filter: set[str] | None) -> dict[str, list[dict[str, Any]]]:
    path = os.path.join(DATA_ROOT, 'daily_prices.csv')
    rows: dict[str, list[dict[str, Any]]] = {}
    if not os.path.isfile(path):
        return rows
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = _symbol(row.get('ticker'))
                if not symbol or (symbol_filter and symbol not in symbol_filter):
                    continue
                date = str(row.get('date') or '')
                current_price = _float(row.get('current_price'))
                volume = _float(row.get('volume'))
                rows.setdefault(symbol, []).append({
                    'symbol': symbol,
                    'date': date,
                    'name': row.get('name') or symbol,
                    'current_price': current_price,
                    'change_rate': _float(row.get('change_rate')),
                    'high': _float(row.get('high')),
                    'low': _float(row.get('low')),
                    'open': _float(row.get('open')),
                    'volume': volume,
                    'trading_value': current_price * volume if current_price and volume else 0.0,
                    'update_time': row.get('update_time') or '',
                })
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    for symbol, history in list(rows.items()):
        history.sort(key=lambda item: (str(item.get('date') or ''), str(item.get('update_time') or '')))
        rows[symbol] = history[-120:]
    return rows


def _load_institutional_trend_data() -> dict[str, dict[str, Any]]:
    path = os.path.join(DATA_ROOT, 'all_institutional_trend_data.csv')
    rows: dict[str, dict[str, Any]] = {}
    if not os.path.isfile(path):
        return rows
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                symbol = _symbol(row.get('ticker') or row.get('symbol') or row.get('code'))
                if not symbol:
                    continue
                previous = rows.get(symbol)
                if previous and str(previous.get('scrape_date') or '') > str(row.get('scrape_date') or ''):
                    continue
                rows[symbol] = dict(row)
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return rows


def _load_indexed_resource_artifact(filename: str) -> dict[str, dict[str, Any]]:
    artifact = _load_json_artifact(filename)
    data = artifact.get('data') if isinstance(artifact, dict) else None
    entries = _extract_resource_entries(data)
    indexed: dict[str, dict[str, Any]] = {}
    for item in entries:
        symbol = _symbol(
            item.get('symbol')
            or item.get('ticker')
            or item.get('code')
            or item.get('stock_code')
            or item.get('isu_cd')
        )
        if not symbol:
            continue
        enriched = dict(item)
        enriched.setdefault('symbol', symbol)
        enriched.setdefault('source_file', filename)
        if artifact.get('generated_at') and not _resource_observed_at(enriched):
            enriched['generated_at'] = artifact.get('generated_at')
        indexed[symbol] = enriched
    return indexed


def _extract_resource_entries(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ('entries', 'items', 'results', 'signals', 'snapshots', 'candidates'):
        value = data.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            rows = []
            for symbol, item in value.items():
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault('symbol', symbol)
                    rows.append(row)
            return rows
    if any(key in data for key in ('symbol', 'ticker', 'code', 'stock_code', 'quote', 'investor')):
        return [dict(data)]
    rows = []
    for symbol, item in data.items():
        if isinstance(item, dict):
            row = dict(item)
            row.setdefault('symbol', symbol)
            rows.append(row)
    return rows


def _scanner_kis_live_enabled() -> bool:
    return _truthy(os.getenv('MIROFISH_ALPHA_SCANNER_LIVE_KIS', '0'))


def _fetch_kis_live_snapshot_for_symbol(symbol: str, mapped: dict[str, Any]) -> dict[str, Any] | None:
    try:
        resolved = {
            'symbol': symbol,
            'name': mapped.get('name') or mapped.get('display_name') or symbol,
            'display_name': mapped.get('display_name') or mapped.get('name') or symbol,
            'market': mapped.get('market') or 'KR',
            'asset_type': 'equity',
        }
        snapshot = live_data.load_kis_snapshot(resolved)
    except Exception:
        return None
    if not isinstance(snapshot, dict) or not snapshot.get('found'):
        return None
    return {
        'symbol': symbol,
        'source': 'KIS API',
        'source_file': 'KIS API: live scanner fetch',
        'fetched_at': snapshot.get('fetched_at'),
        'quote': snapshot.get('quote') or {},
        'investor': snapshot.get('investor') or {},
        'sources': snapshot.get('sources') or [],
        'confidence': 0.94,
        'live_fetch': True,
    }


def _kind_live_fetch_enabled() -> bool:
    return str(os.getenv('KIND_BLACKLIST_LIVE_FETCH', 'false')).strip().lower() in {'1', 'true', 'yes', 'y'}


def _credit_live_fetch_enabled() -> bool:
    return str(os.getenv('CREDIT_BALANCE_LIVE_FETCH', 'false')).strip().lower() in {'1', 'true', 'yes', 'y'}


# ──────────────────────────────────────────────────────────────────────
# 가격 히스토리 메모리 캐시
# daily_prices.csv 가 ~150MB 이고 csv.DictReader는 매 호출마다 전체 파일을
# 스트리밍하기 때문에 단일 종목 조회만 해도 ~40초가 걸린다.
# 전체 dict 을 한 번 메모리에 적재하고 TTL 동안 재사용한다.
# - TTL 기본 1시간 (PRICE_HISTORY_CACHE_TTL env 로 오버라이드)
# - mtime 변경 감지로 CSV 가 갱신되면 자동 무효화
# - threading.Lock 으로 동시 호출 시 thundering herd 방지
# ──────────────────────────────────────────────────────────────────────
_PRICE_HISTORY_LOCK = threading.Lock()
_PRICE_HISTORY_CACHE: dict[str, Any] = {
    'data': None,       # dict[symbol, list[row]]
    'ts': 0.0,          # 캐시 적재 시각
    'mtime': 0.0,       # 적재 시점의 CSV mtime
}
try:
    _PRICE_HISTORY_CACHE_TTL = float(os.getenv('PRICE_HISTORY_CACHE_TTL', '3600'))
except (TypeError, ValueError):
    _PRICE_HISTORY_CACHE_TTL = 3600.0


def _price_history_csv_mtime() -> float:
    path = os.path.join(DATA_ROOT, 'daily_prices.csv')
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _load_price_history_cached() -> dict[str, list[dict[str, Any]]]:
    """전체 가격 히스토리 dict 을 메모리 캐시로 반환.

    호출 1회 만에 모든 종목을 적재해두기 때문에 첫 호출 비용을 후속 호출 전체가 공유한다.
    """
    now = time_mod.time()
    current_mtime = _price_history_csv_mtime()
    cached = _PRICE_HISTORY_CACHE
    if (
        cached['data'] is not None
        and (now - cached['ts']) < _PRICE_HISTORY_CACHE_TTL
        and cached['mtime'] == current_mtime
    ):
        return cached['data']  # type: ignore[return-value]
    with _PRICE_HISTORY_LOCK:
        # 락 진입 후 한 번 더 검사 (다른 스레드가 이미 빌드해뒀을 수 있음)
        now = time_mod.time()
        current_mtime = _price_history_csv_mtime()
        if (
            cached['data'] is not None
            and (now - cached['ts']) < _PRICE_HISTORY_CACHE_TTL
            and cached['mtime'] == current_mtime
        ):
            return cached['data']  # type: ignore[return-value]
        data = _load_price_history(None)
        cached['data'] = data
        cached['ts'] = now
        cached['mtime'] = current_mtime
        return data


def _load_json_artifact(filename: str) -> dict[str, Any]:
    path = os.path.join(DATA_ROOT, filename)
    artifact = {
        'filename': filename,
        'path': path,
        'exists': os.path.isfile(path),
        'data': None,
        'generated_at': None,
        'mtime': None,
    }
    if not artifact['exists']:
        return artifact
    try:
        artifact['mtime'] = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return artifact
    artifact['data'] = data
    artifact['generated_at'] = (
        data.get('timestamp')
        or data.get('date')
        or _nested_get(data, ['metadata', 'generated_at'])
        or artifact['mtime']
    )
    return artifact


def _symbols_from_screener(data: Any) -> set[str]:
    return {_symbol(item.get('code')) for item in _list_from(data, 'results')} - {''}


def _symbols_from_vcp(data: Any) -> set[str]:
    return {_symbol(item.get('symbol')) for item in _list_from(data, 'signals')} - {''}


def _symbols_from_jongga(data: Any) -> set[str]:
    return {_symbol(item.get('stock_code')) for item in _list_from(data, 'signals')} - {''}


def _index_screener(data: Any) -> dict[str, dict[str, Any]]:
    return {_symbol(item.get('code')): item for item in _list_from(data, 'results') if _symbol(item.get('code'))}


def _index_vcp(data: Any) -> dict[str, dict[str, Any]]:
    return {_symbol(item.get('symbol')): item for item in _list_from(data, 'signals') if _symbol(item.get('symbol'))}


def _index_jongga(data: Any) -> dict[str, dict[str, Any]]:
    return {_symbol(item.get('stock_code')): item for item in _list_from(data, 'signals') if _symbol(item.get('stock_code'))}


def _list_from(data: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [item for item in data[key] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _price_analysis(history: list[dict[str, Any]], latest: dict[str, Any]) -> dict[str, Any]:
    ordered = [item for item in history if _float(item.get('current_price')) > 0]
    if latest and (not ordered or ordered[-1].get('date') != latest.get('date')):
        ordered.append(latest)
    ordered.sort(key=lambda item: (str(item.get('date') or ''), str(item.get('update_time') or '')))
    closes = [_float(item.get('current_price')) for item in ordered if _float(item.get('current_price')) > 0]
    volumes = [_float(item.get('volume')) for item in ordered if _float(item.get('volume')) > 0]
    current_price = _float(latest.get('current_price')) or (closes[-1] if closes else 0.0)
    change_rate = _float(latest.get('change_rate'))
    returns = [
        ((closes[index] / closes[index - 1]) - 1) * 100
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]
    trend_5d = _pct_change(closes, 5)
    trend_20d = _pct_change(closes, 20)
    ma5 = _average(closes[-5:])
    ma20 = _average(closes[-20:])
    over_ma20 = ((current_price / ma20) - 1) * 100 if current_price and ma20 else 0.0
    recent_returns = returns[-20:]
    volatility = _stddev(recent_returns)
    max_20 = max(closes[-20:]) if closes else 0.0
    drawdown_20 = ((max_20 - current_price) / max_20 * 100) if max_20 and current_price else 0.0
    consistency_base = returns[-10:]
    trend_consistency = (
        sum(1 for value in consistency_base if value > 0) / len(consistency_base)
        if consistency_base else 0.0
    )
    previous_volumes = volumes[-21:-1] if len(volumes) > 1 else []
    avg_volume = _average(previous_volumes)
    latest_volume = _float(latest.get('volume')) or (volumes[-1] if volumes else 0.0)
    volume_ratio = latest_volume / avg_volume if avg_volume else 0.0

    trend_score = 0.0
    if current_price and ma20 and current_price >= ma20:
        trend_score += 3.5
    if ma5 and ma20 and ma5 >= ma20:
        trend_score += 3.5
    trend_score += _clamp(trend_5d * 0.45, 0, 4.0)
    trend_score += _clamp(trend_20d * 0.18, 0, 3.0)
    trend_score += _clamp((trend_consistency - 0.5) * 4.0, 0, 1.0)
    if change_rate > 18 or over_ma20 > 35:
        trend_score -= 2.0
    trend_score = _clamp(trend_score, 0, 15)

    volume_score = 0.0
    if volume_ratio >= 1.15 and change_rate >= 0:
        volume_score = _clamp((volume_ratio - 1.0) * 4.0, 0, 10)
    elif volume_ratio >= 2.0 and change_rate < 0:
        volume_score = 1.0

    volatility_risk = _clamp((volatility - 4.0) * 2.0, 0, 16)
    drawdown_risk = _clamp(drawdown_20 * 0.55, 0, 16)
    overextension_risk = _clamp(over_ma20 - 25, 0, 18) + _clamp(change_rate - 18, 0, 12)

    return {
        'sample_days': len(closes),
        'trend_5d_pct': round(trend_5d, 2),
        'trend_20d_pct': round(trend_20d, 2),
        'ma5': round(ma5, 2) if ma5 else 0.0,
        'ma20': round(ma20, 2) if ma20 else 0.0,
        'over_ma20_pct': round(over_ma20, 2),
        'volatility_20d_pct': round(volatility, 2),
        'drawdown_20d_pct': round(drawdown_20, 2),
        'trend_consistency': round(trend_consistency, 2),
        'volume_ratio': round(volume_ratio, 2),
        'trend_score': round(trend_score, 2),
        'volume_accumulation_score': round(volume_score, 2),
        'volatility_risk': round(volatility_risk, 2),
        'drawdown_risk': round(drawdown_risk, 2),
        'overextension_risk': round(overextension_risk, 2),
    }


def _pct_change(values: list[float], periods: int) -> float:
    if len(values) <= periods:
        return 0.0
    previous = values[-periods - 1]
    latest = values[-1]
    if previous <= 0:
        return 0.0
    return ((latest / previous) - 1) * 100


def _average(values: list[float]) -> float:
    clean = [float(value) for value in values if value not in (None, '')]
    return sum(clean) / len(clean) if clean else 0.0


def _stddev(values: list[float]) -> float:
    clean = [float(value) for value in values]
    if len(clean) < 2:
        return 0.0
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / len(clean)
    return variance ** 0.5


def _source_files(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for filename in WATCHED_SOURCE_FILES:
        path = os.path.join(DATA_ROOT, filename)
        exists = os.path.isfile(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat() if exists else None
        generated_at = None
        for artifact in (artifacts or {}).values():
            if not isinstance(artifact, dict):
                continue
            if artifact.get('filename') == filename:
                generated_at = artifact.get('generated_at')
        max_age_days = _freshness_max_age_days(filename)
        freshness_value = generated_at or mtime
        policy = SOURCE_FILE_POLICIES.get(filename, {})
        files.append({
            'file': f'data/{filename}',
            'exists': exists,
            'generated_at': generated_at,
            'modified_at': mtime,
            'freshness': _freshness_label(freshness_value, max_age_days=max_age_days),
            'age_days': _age_days(freshness_value),
            'max_age_days': max_age_days,
            'role': policy.get('role'),
            'required': bool(policy.get('required', True)),
            'alert_required': bool(policy.get('alert_required', policy.get('required', True))),
        })
    return files


def _aggregate_freshness(source_files: list[dict[str, Any]]) -> dict[str, Any]:
    existing = [item for item in source_files if item.get('exists')]
    stale_count = sum(1 for item in existing if item.get('freshness') == 'stale')
    unknown_count = sum(1 for item in existing if item.get('freshness') == 'unknown')
    required_files = [item for item in source_files if item.get('required')]
    missing_required_count = sum(1 for item in required_files if not item.get('exists'))
    missing_count = len(source_files) - len(existing)
    if not required_files or not any(item.get('exists') for item in required_files):
        status = 'missing'
    elif stale_count:
        status = 'stale'
    elif unknown_count:
        status = 'unknown'
    elif missing_required_count:
        status = 'partial'
    else:
        status = 'fresh'
    return {
        'status': status,
        'available_files': len(existing),
        'missing_files': missing_count,
        'missing_required_files': missing_required_count,
        'stale_files': stale_count,
        'unknown_files': unknown_count,
    }


def _alert_block_reason(run: dict[str, Any]) -> str | None:
    source_files = [item for item in (run.get('source_files') or []) if isinstance(item, dict)]
    alert_required = [item for item in source_files if item.get('alert_required')]
    if alert_required:
        existing_required = [item for item in alert_required if item.get('exists')]
        if not existing_required:
            return 'source_freshness:missing'
        if any(str(item.get('freshness') or '').lower() == 'stale' for item in existing_required):
            return 'source_freshness:stale'
        if any(str(item.get('freshness') or '').lower() == 'unknown' for item in existing_required):
            return 'source_freshness:unknown'
        if len(existing_required) < len(alert_required):
            return 'source_freshness:partial'
        return None

    freshness_status = ((run.get('freshness') or {}).get('status') or 'unknown').lower()
    if freshness_status in ALERT_BLOCKING_FRESHNESS:
        return f'source_freshness:{freshness_status}'
    return None


def _source_warning(run: dict[str, Any], blocked_reason: str | None) -> str | None:
    if blocked_reason:
        return None
    freshness_status = ((run.get('freshness') or {}).get('status') or 'unknown').lower()
    if freshness_status in ALERT_BLOCKING_FRESHNESS:
        return f'source_freshness:{freshness_status}'
    return None


def _symbol_freshness(artifacts: dict[str, Any]) -> dict[str, Any]:
    source_files = _source_files(artifacts)
    return _aggregate_freshness(source_files)


def _staleness_penalty(artifacts: dict[str, Any], generated_at: str) -> float:
    penalty = 0.0
    for key in ['screener', 'vcp', 'jongga']:
        artifact = artifacts.get(key) or {}
        if not artifact.get('exists'):
            penalty += 2.5
        elif _freshness_label(
            artifact.get('generated_at'),
            generated_at,
            max_age_days=_freshness_max_age_days(artifact.get('filename')),
        ) == 'stale':
            penalty += 4.0
    return penalty


def _negative_flag_penalty(jongga: dict[str, Any] | None) -> float:
    if not jongga:
        return 0.0
    checklist = jongga.get('checklist') or {}
    penalty = 0.0
    for key in ['negative_news', 'upper_wick_long', 'volume_suspicious']:
        if checklist.get(key) is True:
            penalty += 7.0
    return penalty


def _source_count(
    price: dict[str, Any],
    screener: dict[str, Any] | None,
    vcp: dict[str, Any] | None,
    jongga: dict[str, Any] | None,
) -> int:
    return sum([
        1 if _float(price.get('current_price')) > 0 else 0,
        1 if screener else 0,
        1 if vcp else 0,
        1 if jongga else 0,
    ])


def _source_convergence_score(
    *,
    source_count: int,
    trend_quality: float,
    volume_accumulation: float,
    screener_score: float,
    vcp_score: float,
    jongga_score: float,
) -> float:
    score = _clamp((source_count - 1) * 1.2, 0, 3.6)
    if trend_quality >= 8 and vcp_score >= 8:
        score += 0.7
    if volume_accumulation >= 5 and screener_score >= 10:
        score += 0.4
    if jongga_score >= 6 and screener_score >= 10:
        score += 0.3
    return _clamp(score, 0, 5)


def _source_gap_penalty(
    price: dict[str, Any],
    screener: dict[str, Any] | None,
    vcp: dict[str, Any] | None,
    jongga: dict[str, Any] | None,
) -> float:
    penalty = 0.0
    if _float(price.get('current_price')) <= 0:
        penalty += 24.0
    missing_independent = sum(1 for item in (screener, vcp, jongga) if not item)
    penalty += missing_independent * 4.0
    return penalty


def _institutional_flow_confirmation(institutional: dict[str, Any] | None) -> dict[str, Any]:
    if not institutional:
        return {
            'status': 'missing',
            'passed': False,
            'source': 'all_institutional_trend_data.csv',
        }
    foreign_5d = _float(institutional.get('foreign_net_buy_5d'))
    institutional_5d = _float(institutional.get('institutional_net_buy_5d'))
    foreign_20d = _float(institutional.get('foreign_net_buy_20d'))
    institutional_20d = _float(institutional.get('institutional_net_buy_20d'))
    passed = foreign_5d > 0 and institutional_5d > 0
    return {
        'status': 'pass' if passed else 'fail',
        'passed': passed,
        'source': 'all_institutional_trend_data.csv',
        'value': {
            'foreign_5d': foreign_5d,
            'institutional_5d': institutional_5d,
            'foreign_20d': foreign_20d,
            'institutional_20d': institutional_20d,
            'scrape_date': institutional.get('scrape_date'),
        },
    }


def _kis_live_overlay(price: dict[str, Any], kis_live: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(kis_live, dict) or not kis_live:
        return {'applied': False, 'available': False}
    quote = kis_live.get('quote') if isinstance(kis_live.get('quote'), dict) else kis_live
    if not isinstance(quote, dict):
        return {'applied': False, 'available': False}
    live_price = _float(quote.get('price') or quote.get('current_price') or quote.get('stck_prpr'))
    if live_price <= 0:
        return {'applied': False, 'available': True, 'reason': 'price_missing'}
    merged = dict(price or {})
    if live_price:
        merged['current_price'] = live_price
    change_pct = quote.get('change_pct')
    if change_pct is None:
        change_pct = quote.get('prdy_ctrt')
    if change_pct is not None:
        merged['change_rate'] = _float(change_pct)
    for src, dst in (
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('volume', 'volume'),
        ('trading_value', 'trading_value'),
        ('stck_oprc', 'open'),
        ('stck_hgpr', 'high'),
        ('stck_lwpr', 'low'),
        ('acml_vol', 'volume'),
        ('acml_tr_pbmn', 'trading_value'),
    ):
        value = quote.get(src)
        if value not in (None, ''):
            merged[dst] = _float(value)
    merged['source'] = 'kis_live'
    merged['kis_fetched_at'] = kis_live.get('fetched_at') or kis_live.get('updated_at') or kis_live.get('generated_at')
    return {
        'applied': True,
        'available': True,
        'source': kis_live.get('source') or 'KIS API',
        'fetched_at': merged.get('kis_fetched_at'),
        'price': merged,
        'quote': quote,
        'weight': _resource_weight(kis_live, default_confidence=0.94, max_age_days=1),
    }


def _mcp_quality_adjustment(
    *,
    price: dict[str, Any],
    kis_live: dict[str, Any] | None,
    kis_overlay: dict[str, Any],
    institutional: dict[str, Any] | None,
    flow_confirmation: dict[str, Any],
    dart_event: dict[str, Any] | None,
    news_theme_social: dict[str, Any] | None,
    freshness: dict[str, Any],
    performance_advisory: dict[str, Any],
) -> dict[str, Any]:
    alpha_delta = 0.0
    risk_delta = 0.0
    ranking_delta = 0.0
    source_count_delta = 0
    tags: list[str] = []
    evidence: list[dict[str, Any]] = []
    resource_weights: dict[str, Any] = {}

    kis_weight = _resource_weight(kis_live, default_confidence=0.94, max_age_days=1) if kis_live else _resource_weight(None)
    if kis_live and kis_overlay.get('applied'):
        quote = kis_overlay.get('quote') or {}
        investor = kis_live.get('investor') if isinstance(kis_live.get('investor'), dict) else {}
        trading_value = _float((kis_overlay.get('price') or {}).get('trading_value') or quote.get('trading_value'))
        change_pct = _float((kis_overlay.get('price') or {}).get('change_rate') or quote.get('change_pct'))
        live_liquidity_delta = _clamp(trading_value / 100_000_000_000 * 2.2, 0, 3.0) * kis_weight['score_weight']
        foreign_value = _float(investor.get('foreign_net_value') or investor.get('foreign_net_qty'))
        institution_value = _float(investor.get('institution_net_value') or investor.get('institution_net_qty'))
        flow_delta = 0.0
        if foreign_value > 0 and institution_value > 0:
            flow_delta = 3.0
            tags.append('kis_live_dual_flow')
        elif foreign_value > 0 or institution_value > 0:
            flow_delta = 1.2
            tags.append('kis_live_partial_flow')
        elif foreign_value < 0 and institution_value < 0 and change_pct > 0:
            flow_delta = -2.5
            risk_delta += 2.0 * kis_weight['risk_weight']
            tags.append('price_flow_divergence')
        alpha_delta += (live_liquidity_delta + flow_delta) * kis_weight['score_weight']
        source_count_delta += 1
        evidence.append(_evidence('KIS API', 'live_price_trading_value', live_liquidity_delta, {
            'trading_value': trading_value,
            'change_pct': change_pct,
            'freshness': kis_weight['freshness'],
        }))
        if investor:
            evidence.append(_evidence('KIS API', 'live_investor_flow', flow_delta, {
                'foreign_net': foreign_value,
                'institution_net': institution_value,
                'freshness': kis_weight['freshness'],
            }))
    elif kis_live and kis_weight['freshness'] in {'stale', 'unknown'}:
        risk_delta += 1.5 * kis_weight['risk_weight']
    resource_weights['kis_live'] = kis_weight

    if flow_confirmation.get('passed') and institutional:
        flow_weight = _resource_weight(institutional, default_confidence=0.82, max_age_days=30)
        alpha_delta += 1.5 * flow_weight['score_weight']
        evidence.append(_evidence('all_institutional_trend_data.csv', 'flow_quality_weight', 1.5, flow_weight['freshness']))
        resource_weights['capital_flow'] = flow_weight

    dart_weight = _resource_weight(dart_event, default_confidence=0.86, max_age_days=7) if dart_event else _resource_weight(None)
    if dart_event:
        dart_result = _dart_event_risk_adjustment(dart_event, dart_weight)
        alpha_delta += dart_result['alpha_delta']
        risk_delta += dart_result['risk_delta']
        source_count_delta += 1
        tags.extend(dart_result['tags'])
        evidence.extend(dart_result['evidence'])
    resource_weights['dart_event'] = dart_weight

    nts_weight = _resource_weight(news_theme_social, default_confidence=0.58, max_age_days=2) if news_theme_social else _resource_weight(None)
    if news_theme_social:
        support = _news_theme_social_adjustment(news_theme_social, nts_weight, has_core_confirmation=bool(kis_live or institutional or flow_confirmation.get('passed')))
        alpha_delta += support['alpha_delta']
        risk_delta += support['risk_delta']
        source_count_delta += 1
        tags.extend(support['tags'])
        evidence.extend(support['evidence'])
    resource_weights['news_theme_social'] = nts_weight

    perf = _performance_memory_adjustment(performance_advisory)
    ranking_delta += perf.get('ranking_delta', 0.0)
    if perf.get('applied'):
        tags.append('outcome_memory_adjusted')
        evidence.append(_evidence('workflow_outcomes', 'recent_hit_rate_adjustment', perf['ranking_delta'], perf))

    freshness_status = str((freshness or {}).get('status') or 'unknown').lower()
    if freshness_status in {'stale', 'unknown', 'missing', 'partial'}:
        risk_delta += {'partial': 1.5, 'stale': 3.0, 'unknown': 2.5, 'missing': 4.0}.get(freshness_status, 2.0)
        tags.append('source_freshness_capped')

    alpha_delta = _clamp(alpha_delta, -12.0, 12.0)
    risk_delta = _clamp(risk_delta, -5.0, 18.0)
    ranking_delta = _clamp(ranking_delta, -4.0, 4.0)
    return {
        'schema_version': 'mirofish.mcp_quality_adjustment.v1',
        'alpha_delta': round(alpha_delta, 2),
        'risk_delta': round(risk_delta, 2),
        'ranking_delta': round(ranking_delta, 2),
        'source_count_delta': int(max(0, source_count_delta)),
        'tags': sorted(set(tags)),
        'evidence': evidence,
        'resource_weights': resource_weights,
        'performance_memory': perf,
        'lookahead_safe': True,
    }


def _dart_event_risk_adjustment(dart_event: dict[str, Any], weight: dict[str, Any]) -> dict[str, Any]:
    risk_level = str(dart_event.get('risk_level') or dart_event.get('severity') or dart_event.get('status') or '').lower()
    flags = [str(item).lower() for item in (dart_event.get('risk_flags') or dart_event.get('flags') or dart_event.get('categories') or [])]
    text = ' '.join([risk_level, *flags, str(dart_event.get('event_type') or ''), str(dart_event.get('summary') or '')]).lower()
    hard_terms = ('trading_halt', 'delisting', 'audit_opinion', 'capital_impairment', 'embezzlement', 'management_issue')
    caution_terms = ('lawsuit', 'cb', 'bw', 'capital_increase', 'refinancing', 'earnings_miss', 'warning')
    alpha_delta = 0.0
    risk_delta = 0.0
    tags: list[str] = []
    if any(term in text for term in hard_terms) or risk_level in {'hard_block', 'critical', 'high'}:
        alpha_delta -= 8.0 * weight['score_weight']
        risk_delta += 14.0 * weight['risk_weight']
        tags.append('dart_hard_risk')
    elif any(term in text for term in caution_terms) or risk_level in {'medium', 'caution'}:
        alpha_delta -= 2.0 * weight['score_weight']
        risk_delta += 5.0 * weight['risk_weight']
        tags.append('dart_event_caution')
    elif text.strip():
        risk_delta += 0.8 * weight['risk_weight']
        tags.append('dart_reviewed')
    return {
        'alpha_delta': round(alpha_delta, 2),
        'risk_delta': round(risk_delta, 2),
        'tags': tags,
        'evidence': [_evidence('OpenDART/KRX filing', 'disclosure_risk_filter', alpha_delta - risk_delta, {
            'risk_level': risk_level or None,
            'flags': flags,
            'freshness': weight['freshness'],
        })],
    }


def _news_theme_social_adjustment(
    news_theme_social: dict[str, Any],
    weight: dict[str, Any],
    *,
    has_core_confirmation: bool,
) -> dict[str, Any]:
    sentiment = _first_number(
        news_theme_social,
        ('sentiment_score', 'news_sentiment', 'theme_score', 'social_score', 'score', 'heat_score'),
    )
    heat = _first_number(news_theme_social, ('social_heat', 'theme_heat', 'buzz', 'search_interest', 'attention_score'))
    risk_flag = _truthy(news_theme_social.get('unverified') or news_theme_social.get('rumor') or news_theme_social.get('hype_flag'))
    source_grade = str(news_theme_social.get('source_grade') or news_theme_social.get('grade') or '').upper()
    alpha_delta = 0.0
    risk_delta = 0.0
    tags = ['news_theme_social_supporting_only']
    if has_core_confirmation and not risk_flag:
        alpha_delta += _clamp(sentiment / 100 * 1.5, -1.0, 1.5) * weight['score_weight']
    elif sentiment > 0 or heat > 0:
        alpha_delta -= 1.5
        risk_delta += 3.0
        tags.append('support_signal_without_core_confirmation')
    if heat >= 80 or risk_flag or source_grade in {'C', 'D'}:
        risk_delta += 2.5
        tags.append('unverified_or_hot_theme_risk')
    return {
        'alpha_delta': round(alpha_delta, 2),
        'risk_delta': round(risk_delta * weight['risk_weight'], 2),
        'tags': tags,
        'evidence': [_evidence('news_theme_social_latest.json', 'supporting_signal_only', alpha_delta - risk_delta, {
            'sentiment': sentiment,
            'heat': heat,
            'source_grade': source_grade or None,
            'has_core_confirmation': has_core_confirmation,
            'freshness': weight['freshness'],
        })],
    }


def _performance_memory_adjustment(performance_advisory: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(performance_advisory, dict) or not performance_advisory.get('available'):
        return {'applied': False, 'ranking_delta': 0.0, 'source': 'workflow_outcomes'}
    learning_gate = _learning_score_control(performance_advisory)
    if learning_gate and not learning_gate.get('outcome_memory_enabled'):
        return {
            'applied': False,
            'ranking_delta': 0.0,
            'source': 'workflow_outcomes',
            'reason': learning_gate.get('reason') or 'learning_policy_disabled',
            'learning_policy_status': learning_gate.get('status'),
        }
    baseline = _float((performance_advisory.get('recommendations') or {}).get('baseline_hit_rate'))
    hit_rate = _float(performance_advisory.get('hit_rate_recent'))
    evaluated = int(_float(performance_advisory.get('evaluated_count')))
    if evaluated < 9 or hit_rate <= 0:
        return {
            'applied': False,
            'ranking_delta': 0.0,
            'source': 'workflow_outcomes',
            'evaluated_count': evaluated,
            'reason': 'insufficient_evaluated_outcomes',
        }
    center = baseline if baseline > 0 else 0.50
    default_bounds = (-3.0, 3.0)
    lower, upper = _learning_global_delta_bounds(performance_advisory, default_bounds)
    delta = _clamp((hit_rate - center) * 10.0, lower, upper)
    return {
        'applied': bool(delta),
        'ranking_delta': round(delta, 2),
        'source': 'workflow_outcomes',
        'evaluated_count': evaluated,
        'hit_rate_recent': hit_rate,
        'baseline_hit_rate': center,
        'learning_policy_status': learning_gate.get('status') if learning_gate else None,
        'lookahead_safe': bool(performance_advisory.get('lookahead_safe', True)),
    }


def _performance_tag_memory_adjustment(performance_advisory: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    if not isinstance(performance_advisory, dict) or not performance_advisory.get('available'):
        return {'applied': False, 'ranking_delta': 0.0, 'source': 'workflow_outcomes'}
    learning_gate = _learning_score_control(performance_advisory)
    if learning_gate and not learning_gate.get('outcome_memory_enabled'):
        return {
            'applied': False,
            'ranking_delta': 0.0,
            'source': 'workflow_outcomes',
            'reason': learning_gate.get('reason') or 'learning_policy_disabled',
            'learning_policy_status': learning_gate.get('status'),
        }
    tag_adjust = ((performance_advisory.get('recommendations') or {}).get('tag_score_adjust') or {})
    if not isinstance(tag_adjust, dict) or not tag_adjust:
        return {'applied': False, 'ranking_delta': 0.0, 'source': 'workflow_outcomes'}
    matched = {
        tag: _float(tag_adjust.get(tag))
        for tag in tags or []
        if tag in tag_adjust and _float(tag_adjust.get(tag)) != 0
    }
    if not matched:
        return {'applied': False, 'ranking_delta': 0.0, 'source': 'workflow_outcomes'}
    lower, upper = _learning_tag_delta_bounds(performance_advisory, (-2.0, 2.0))
    delta = _clamp(sum(matched.values()), lower, upper)
    return {
        'applied': bool(delta),
        'ranking_delta': round(delta, 2),
        'source': 'workflow_outcomes',
        'matched_tags': matched,
        'learning_policy_status': learning_gate.get('status') if learning_gate else None,
        'lookahead_safe': bool(performance_advisory.get('lookahead_safe', True)),
    }


def _learning_score_control(performance_advisory: dict[str, Any]) -> dict[str, Any]:
    policy = performance_advisory.get('learning_policy') if isinstance(performance_advisory, dict) else None
    control = policy.get('score_control') if isinstance(policy, dict) else None
    return control if isinstance(control, dict) else {}


def _learning_global_delta_bounds(
    performance_advisory: dict[str, Any],
    default: tuple[float, float],
) -> tuple[float, float]:
    policy = performance_advisory.get('learning_policy') if isinstance(performance_advisory, dict) else None
    if not isinstance(policy, dict):
        return default
    try:
        from app.services.mirofish import learning_policy as policy_helpers

        return policy_helpers.global_delta_bounds(policy, default=default)
    except Exception:
        return default


def _learning_tag_delta_bounds(
    performance_advisory: dict[str, Any],
    default: tuple[float, float],
) -> tuple[float, float]:
    policy = performance_advisory.get('learning_policy') if isinstance(performance_advisory, dict) else None
    if not isinstance(policy, dict):
        return default
    try:
        from app.services.mirofish import learning_policy as policy_helpers

        return policy_helpers.tag_delta_bounds(policy, default=default)
    except Exception:
        return default


def _apply_false_signal_gates(
    candidate: dict[str, Any],
    *,
    price: dict[str, Any],
    price_metrics: dict[str, Any],
    jongga: dict[str, Any] | None,
    institutional: dict[str, Any] | None,
    blacklist_entry: dict[str, Any] | None,
    credit_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
    if not _false_signal_gates_enabled():
        profile['false_signal_gates'] = {'enabled': False, 'lookahead_safe': True}
        candidate['analysis_profile'] = profile
        return candidate

    gates = []
    hard_blockers: list[str] = []
    alpha_delta = 0.0
    risk_delta = 0.0
    tag_additions: list[str] = []
    evidence = list(candidate.get('evidence') or [])
    trading_value = _float((candidate.get('price') or {}).get('trading_value'))
    current_price = _float((candidate.get('price') or {}).get('current_price'))
    change_rate = _float((candidate.get('price') or {}).get('change_rate'))

    if blacklist_entry:
        categories = blacklist_entry.get('categories') or ['listed']
        gates.append(_false_signal_gate(
            'kind_blacklist',
            'fail',
            'KIND/KRX risk blacklist matched',
            {'categories': categories},
            hard_block=True,
        ))
        hard_blockers.append('kind_blacklist')
        tag_additions.append('kind_blacklist')
        evidence.append(_evidence('kind_blacklist_latest.json', 'kind_blacklist', 0.0, categories))
    else:
        gates.append(_false_signal_gate('kind_blacklist', 'pass', 'no local KIND/KRX risk match', None))

    flow_gate = _institutional_flow_confirmation(institutional)
    gates.append(_false_signal_gate(
        'foreign_institution_dual_buy_5d',
        'pass' if flow_gate.get('passed') else ('unknown' if flow_gate.get('status') == 'missing' else 'partial'),
        'foreign and institution five-day flow confirmation',
        flow_gate.get('value'),
    ))

    wick_ratio = _upper_wick_ratio(price, jongga)
    if wick_ratio >= 0.5:
        gates.append(_false_signal_gate(
            'upper_wick_exhaustion',
            'fail',
            'long upper wick suggests intraday supply or chase risk',
            round(wick_ratio, 3),
        ))
        alpha_delta -= 5.0
        risk_delta += 5.0
        tag_additions.append('upper_wick_risk')
    else:
        gates.append(_false_signal_gate('upper_wick_exhaustion', 'pass', 'upper wick below risk threshold', round(wick_ratio, 3)))

    credit_pct = _credit_pressure_pct(jongga, credit_entry)
    if credit_pct is None:
        gates.append(_false_signal_gate('credit_pressure', 'unknown', 'credit balance data not available', None))
    elif credit_pct >= 5.0:
        gates.append(_false_signal_gate(
            'credit_pressure',
            'fail',
            'credit balance ratio exceeds hard-block threshold',
            round(credit_pct, 2),
            hard_block=True,
        ))
        hard_blockers.append('credit_pressure')
        tag_additions.append('credit_pressure')
    else:
        gates.append(_false_signal_gate('credit_pressure', 'pass', 'credit balance below hard-block threshold', round(credit_pct, 2)))

    if trading_value and trading_value < 10_000_000_000 and change_rate >= 15:
        gates.append(_false_signal_gate(
            'thin_liquidity_spike',
            'fail',
            'large move on sub-10B KRW trading value',
            {'trading_value': trading_value, 'change_rate': change_rate},
        ))
        alpha_delta -= 10.0
        risk_delta += 5.0
        tag_additions.append('thin_liquidity_spike')
    else:
        gates.append(_false_signal_gate(
            'thin_liquidity_spike',
            'pass',
            'liquidity and latest move do not match thin-spike guard',
            {'trading_value': trading_value, 'change_rate': change_rate},
        ))

    if hard_blockers:
        candidate['alpha_score'] = 0.0
        candidate['risk_score'] = round(max(_float(candidate.get('risk_score')) + risk_delta, 90.0), 2)
    else:
        candidate['alpha_score'] = round(_clamp(_float(candidate.get('alpha_score')) + alpha_delta, 0, 100), 2)
        candidate['risk_score'] = round(_clamp(_float(candidate.get('risk_score')) + risk_delta, 0, 100), 2)

    tags = list(dict.fromkeys(list(candidate.get('strategy_tags') or []) + tag_additions))
    candidate['strategy_tags'] = tags
    candidate['action'] = _action(_float(candidate.get('alpha_score')), _float(candidate.get('risk_score')))
    candidate['horizon'] = 'swing_5_20d' if candidate['action'] in ('BUY_CANDIDATE', 'WATCH') else 'avoid_or_recheck'
    source_count = int(_float(profile.get('source_count')))
    conviction_adjustment = _conviction_adjustment(
        _float(candidate.get('alpha_score')),
        _float(candidate.get('risk_score')),
        source_count,
        price_metrics,
    )
    mcp_ranking_delta = _float((profile.get('mcp_quality_adjustment') or {}).get('ranking_delta'))
    candidate['ranking_score'] = round(
        _float(candidate.get('alpha_score')) - (0.55 * _float(candidate.get('risk_score'))) + conviction_adjustment + mcp_ranking_delta,
        2,
    )
    candidate['signal_quality'] = _signal_quality(
        _float(candidate.get('alpha_score')),
        _float(candidate.get('risk_score')),
        source_count,
        price_metrics,
    )
    candidate['entry_plan'] = _entry_plan(
        current_price,
        _float(candidate.get('risk_score')),
        price_metrics,
        candidate['action'],
    )
    clean_evidence = [item for item in evidence if item.get('score', 0) > 0 or item.get('value') not in (None, 0)]
    candidate['evidence'] = clean_evidence
    source_freshness = candidate.get('freshness') if isinstance(candidate.get('freshness'), dict) else {}
    evidence_quality = _evidence_quality(
        clean_evidence,
        source_count=source_count,
        freshness=source_freshness,
        risk=_float(candidate.get('risk_score')),
    )
    confidence_cap = _confidence_cap(
        source_count=source_count,
        freshness=source_freshness,
        risk=_float(candidate.get('risk_score')),
    )
    profile['conviction_adjustment'] = round(conviction_adjustment, 2)
    profile['mcp_ranking_delta'] = round(mcp_ranking_delta, 2)
    profile['evidence_quality'] = evidence_quality
    profile['confidence_cap'] = confidence_cap
    profile['false_signal_gates'] = {
        'enabled': True,
        'schema_version': 'mirofish.plan_a_false_signal_gates.v1',
        'gates': gates,
        'alpha_delta': round(alpha_delta, 2),
        'risk_delta': round(risk_delta, 2),
        'hard_blockers': hard_blockers,
        'lookahead_safe': True,
    }
    scorecard = _profitability_scorecard(
        alpha=_float(candidate.get('alpha_score')),
        risk=_float(candidate.get('risk_score')),
        action=candidate['action'],
        source_count=source_count,
        data_sources=(candidate.get('replay_context') or {}).get('data_sources') or [],
        evidence_quality=evidence_quality,
        confidence_cap=confidence_cap,
        freshness=source_freshness,
        entry_plan=candidate.get('entry_plan') or {},
        price_metrics=price_metrics,
        trading_value=trading_value,
        current_price=current_price,
    )
    if hard_blockers:
        scorecard['hard_blockers'] = sorted(set(list(scorecard.get('hard_blockers') or []) + [f'false_signal:{item}' for item in hard_blockers]))
        scorecard['goal_verdict'] = 'blocked_by_guardrail'
    profile['profitability_scorecard'] = scorecard
    candidate['analysis_profile'] = profile
    return candidate


def _false_signal_gate(
    gate: str,
    status: str,
    reason: str,
    value: Any,
    *,
    hard_block: bool = False,
) -> dict[str, Any]:
    return {
        'gate': gate,
        'status': status,
        'reason': reason,
        'value': value,
        'hard_blocker': hard_block,
    }


def _upper_wick_ratio(price: dict[str, Any], jongga: dict[str, Any] | None) -> float:
    checklist = (jongga or {}).get('checklist') if isinstance((jongga or {}).get('checklist'), dict) else {}
    if checklist.get('upper_wick_long') is True:
        return 1.0
    high = _float(price.get('high'))
    low = _float(price.get('low'))
    close = _float(price.get('current_price'))
    if high <= 0 or low <= 0 or close <= 0 or high <= low:
        return 0.0
    return _clamp((high - close) / (high - low), 0, 1)


def _credit_pressure_pct(jongga: dict[str, Any] | None, credit_entry: dict[str, Any] | None = None) -> float | None:
    if credit_entry:
        ratio = _float(credit_entry.get('credit_ratio_pct') or credit_entry.get('credit_ratio') or credit_entry.get('credit_balance_ratio'))
        if ratio:
            return ratio * 100 if 0 < ratio <= 1 else ratio
        balance = _float(credit_entry.get('balance_shares'))
        listed = _float(credit_entry.get('listed_shares'))
        if listed > 0:
            return balance / listed * 100
    if not jongga:
        return None
    keys = [
        'credit_balance_ratio',
        'credit_ratio',
        'margin_debt_ratio',
        'credit_balance_pct',
        '신용잔고율',
    ]
    nested_paths = [
        ['risk', 'credit_balance_ratio'],
        ['risk', 'credit_ratio'],
        ['metrics', 'credit_balance_ratio'],
        ['checklist', 'credit_balance_ratio'],
    ]
    value = None
    for key in keys:
        if key in jongga:
            value = _float(jongga.get(key))
            break
    if value is None:
        for path in nested_paths:
            found = _nested_get(jongga, path)
            if found not in (None, ''):
                value = _float(found)
                break
    if value is None:
        return None
    return value * 100 if 0 < value <= 1 else value


def _false_signal_gates_enabled() -> bool:
    preferred = os.getenv('ENABLE_ALPHA_PHASE_1_GATES')
    if preferred is not None:
        return str(preferred).strip().lower() in {'1', 'true', 'yes', 'y'}
    return str(os.getenv('ALPHA_FALSE_SIGNAL_GATES_ENABLED', 'true')).strip().lower() in {'1', 'true', 'yes', 'y'}


def _conviction_adjustment(
    alpha: float,
    risk: float,
    source_count: int,
    price_metrics: dict[str, Any],
) -> float:
    adjustment = 0.0
    if source_count >= 4 and alpha >= 65 and risk <= 40:
        adjustment += 3.0
    if _float(price_metrics.get('trend_score')) >= 10 and _float(price_metrics.get('volume_accumulation_score')) >= 5:
        adjustment += 1.5
    if _float(price_metrics.get('overextension_risk')) >= 12:
        adjustment -= 3.0
    if _float(price_metrics.get('drawdown_risk')) >= 10:
        adjustment -= 2.0
    return _clamp(adjustment, -6, 5)


def _signal_quality(
    alpha: float,
    risk: float,
    source_count: int,
    price_metrics: dict[str, Any],
) -> str:
    if alpha >= 75 and risk <= 35 and source_count >= 4:
        return 'high_conviction'
    if alpha >= 65 and risk <= 45 and source_count >= 3:
        return 'actionable'
    if alpha >= 50 and risk <= 65:
        return 'watch'
    if _float(price_metrics.get('overextension_risk')) >= 12:
        return 'overextended'
    return 'weak'


def _entry_plan(
    current_price: float,
    risk: float,
    price_metrics: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    if current_price <= 0 or action == 'REJECT':
        return {
            'status': 'not_actionable',
            'reason': 'rejected_or_missing_price',
        }
    volatility = _float(price_metrics.get('volatility_20d_pct'))
    stop_pct = _clamp(max(4.0, volatility * 1.6, risk * 0.10), 4.0, 14.0)
    target_pct = _clamp(stop_pct * 2.0, 8.0, 28.0)
    return {
        'status': 'ready' if action == 'BUY_CANDIDATE' else 'watch',
        'entry_price': round(current_price, 2),
        'stop_loss': round(current_price * (1 - stop_pct / 100), 2),
        'target_1': round(current_price * (1 + target_pct / 100), 2),
        'target_2': round(current_price * (1 + (target_pct * 1.5) / 100), 2),
        'stop_pct': round(stop_pct, 2),
        'target_pct': round(target_pct, 2),
        'risk_reward': round(target_pct / stop_pct, 2) if stop_pct else 0,
        'invalidation': 'close_below_stop_or_source_score_drop',
    }


def _candidate_sources(
    price: dict[str, Any],
    screener: dict[str, Any] | None,
    vcp: dict[str, Any] | None,
    jongga: dict[str, Any] | None,
    tradingview_adjustment: dict[str, Any] | None = None,
    institutional: dict[str, Any] | None = None,
    kind_blacklist: dict[str, Any] | None = None,
    credit_balance: dict[str, Any] | None = None,
    kis_live: dict[str, Any] | None = None,
    dart_event: dict[str, Any] | None = None,
    news_theme_social: dict[str, Any] | None = None,
) -> list[str]:
    sources = []
    if _float(price.get('current_price')) > 0:
        sources.append('daily_prices.csv')
    if screener:
        sources.append('screener_leading_latest.json')
    if vcp:
        sources.append('vcp_kr_latest.json')
    if jongga:
        sources.append('jongga_v2_latest.json')
    if tradingview_adjustment and tradingview_adjustment.get('applied'):
        sources.append('tradingview_mcp')
    if institutional:
        sources.append('all_institutional_trend_data.csv')
    if kind_blacklist:
        sources.append('kind_blacklist_latest.json')
    if credit_balance:
        sources.append('credit_balance_latest.json')
    if kis_live:
        sources.append('KIS API: live price/investor flow')
    if dart_event:
        sources.append('dart_event_latest.json')
    if news_theme_social:
        sources.append('news_theme_social_latest.json')
    return sources


def _feature_vectors(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_feature_vector(candidate) for candidate in candidates]


def _feature_vector(candidate: dict[str, Any]) -> dict[str, Any]:
    profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    replay = candidate.get('replay_context') if isinstance(candidate.get('replay_context'), dict) else {}
    freshness = candidate.get('freshness') if isinstance(candidate.get('freshness'), dict) else {}
    return {
        'symbol': candidate.get('symbol'),
        'name': candidate.get('name') or candidate.get('display_name'),
        'market': candidate.get('market'),
        'pool_rank': candidate.get('pool_rank'),
        'rank': candidate.get('rank'),
        'action': candidate.get('action'),
        'horizon': candidate.get('horizon'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
        'ranking_score': candidate.get('ranking_score'),
        'signal_quality': candidate.get('signal_quality'),
        'strategy_tags': candidate.get('strategy_tags') or [],
        'source_count': profile.get('source_count'),
        'base_source_count': profile.get('base_source_count'),
        'evidence_quality': profile.get('evidence_quality'),
        'confidence_cap': profile.get('confidence_cap'),
        'profitability_scorecard': profile.get('profitability_scorecard'),
        'false_signal_gates': profile.get('false_signal_gates'),
        'capital_flow_confirmation': profile.get('capital_flow_confirmation'),
        'mcp_quality_adjustment': profile.get('mcp_quality_adjustment'),
        'performance_memory': profile.get('performance_memory'),
        'goal_fit_score': (profile.get('profitability_scorecard') or {}).get('goal_fit_score')
            if isinstance(profile.get('profitability_scorecard'), dict) else None,
        'goal_verdict': (profile.get('profitability_scorecard') or {}).get('goal_verdict')
            if isinstance(profile.get('profitability_scorecard'), dict) else None,
        'freshness_status': profile.get('freshness_status') or freshness.get('status'),
        'freshness_penalty': profile.get('freshness_penalty'),
        'data_sources': replay.get('data_sources') or [],
        'lookahead_safe': bool(replay.get('lookahead_safe', True)),
        'price_date': replay.get('price_date') or price.get('date'),
        'current_price': price.get('current_price'),
        'change_rate': price.get('change_rate'),
        'volume': price.get('volume'),
        'trading_value': price.get('trading_value'),
        'trend_quality': profile.get('trend_quality'),
        'volume_accumulation': profile.get('volume_accumulation'),
        'trend_5d_pct': profile.get('trend_5d_pct'),
        'trend_20d_pct': profile.get('trend_20d_pct'),
        'volume_ratio': profile.get('volume_ratio'),
        'volatility_20d_pct': profile.get('volatility_20d_pct'),
        'drawdown_20d_pct': profile.get('drawdown_20d_pct'),
        'over_ma20_pct': profile.get('over_ma20_pct'),
        'trend_consistency': profile.get('trend_consistency'),
        'sample_days': profile.get('sample_days'),
        'tradingview': profile.get('tradingview_adjustment'),
    }


def _evidence_ledger(
    candidates: list[dict[str, Any]],
    rejected_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = [
        _evidence_ledger_entry(candidate, selection_status='selected')
        for candidate in candidates
    ]
    for candidate in rejected_candidates:
        items.append(_evidence_ledger_entry(
            candidate,
            selection_status='rejected',
            rejection_reasons=candidate.get('rejection_reasons') or [],
        ))
    return items


def _evidence_ledger_entry(
    candidate: dict[str, Any],
    *,
    selection_status: str,
    rejection_reasons: list[str] | None = None,
) -> dict[str, Any]:
    profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
    feature_vector = candidate.get('feature_vector') if isinstance(candidate.get('feature_vector'), dict) else None
    return {
        'symbol': candidate.get('symbol'),
        'name': candidate.get('name') or candidate.get('display_name'),
        'market': candidate.get('market'),
        'rank': candidate.get('rank'),
        'pool_rank': candidate.get('pool_rank'),
        'selection_status': selection_status,
        'rejection_reasons': rejection_reasons or [],
        'action': candidate.get('action'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
        'ranking_score': candidate.get('ranking_score'),
        'signal_quality': candidate.get('signal_quality'),
        'strategy_tags': candidate.get('strategy_tags') or [],
        'evidence_quality': candidate.get('evidence_quality') or profile.get('evidence_quality'),
        'confidence_cap': profile.get('confidence_cap') or (feature_vector or {}).get('confidence_cap'),
        'freshness': candidate.get('freshness'),
        'data_sources': ((candidate.get('replay_context') or {}).get('data_sources') if isinstance(candidate.get('replay_context'), dict) else None)
            or (feature_vector or {}).get('data_sources')
            or [],
        'evidence': candidate.get('evidence') or [],
        'feature_vector': feature_vector or _feature_vector(candidate),
    }


def _evidence_quality(
    evidence: list[dict[str, Any]],
    *,
    source_count: int,
    freshness: dict[str, Any],
    risk: float,
) -> dict[str, Any]:
    freshness_status = str((freshness or {}).get('status') or 'unknown').lower()
    confidence_values = [_float(item.get('confidence')) for item in evidence if isinstance(item, dict)]
    avg_confidence = _average(confidence_values) if confidence_values else 0.0
    if freshness_status == 'fresh' and source_count >= 4 and len(evidence) >= 6 and risk <= 45:
        grade = 'strong'
    elif freshness_status in {'fresh', 'stale'} and source_count >= 3 and len(evidence) >= 4 and risk <= 65:
        grade = 'moderate'
    else:
        grade = 'weak'
    return {
        'grade': grade,
        'source_count': int(source_count),
        'evidence_count': len(evidence),
        'freshness_status': freshness_status,
        'average_confidence': round(avg_confidence, 3),
    }


def _confidence_cap(
    *,
    source_count: int,
    freshness: dict[str, Any],
    risk: float,
) -> float:
    status = str((freshness or {}).get('status') or 'unknown').lower()
    cap = 0.95
    if source_count < 4:
        cap = min(cap, 0.82)
    if source_count < 3:
        cap = min(cap, 0.68)
    if status != 'fresh':
        cap = min(cap, 0.70 if status == 'stale' else 0.58)
    if risk > 65:
        cap = min(cap, 0.55)
    elif risk > 45:
        cap = min(cap, 0.78)
    return round(cap, 2)


def _profitability_scorecard(
    *,
    alpha: float,
    risk: float,
    action: str,
    source_count: int,
    data_sources: list[str],
    evidence_quality: dict[str, Any],
    confidence_cap: float,
    freshness: dict[str, Any],
    entry_plan: dict[str, Any],
    price_metrics: dict[str, Any],
    trading_value: float,
    current_price: float,
) -> dict[str, Any]:
    """Goal harness for profitable stock-candidate detection.

    This is a deterministic scorecard, not a live ranking mutation. It keeps the
    scanner focused on data quality, risk control, and replayable outcomes.
    """
    source_text = ' '.join(str(source).lower() for source in data_sources)
    freshness_status = str((freshness or {}).get('status') or 'unknown').lower()
    evidence_grade = str((evidence_quality or {}).get('grade') or 'unknown').lower()
    risk_reward = _float((entry_plan or {}).get('risk_reward'))
    trend_quality = _float(price_metrics.get('trend_score'))
    volume_quality = _float(price_metrics.get('volume_accumulation_score'))
    has_capital_flow = any(token in source_text for token in ('flow', 'investor', 'institution', 'foreigner', 'kis', 'krx', 'kiwoom'))
    has_disclosure = any(token in source_text for token in ('dart', 'disclosure', 'filing'))
    has_technical = any(token in source_text for token in ('tradingview', 'technical'))

    gates = [
        _goal_gate('candidate_action', 10, action in {'BUY_CANDIDATE', 'WATCH'}, action == 'REJECT', action),
        _goal_gate('price_liquidity', 12, current_price > 0 and trading_value >= 2_000_000_000, current_price <= 0 or trading_value <= 0, trading_value),
        _goal_gate('evidence_depth', 16, source_count >= 4 and evidence_grade in {'strong', 'moderate'}, source_count < 3 or evidence_grade == 'weak', f'{evidence_grade}:{source_count}'),
        _goal_gate('risk_control', 18, risk <= 45, risk > 65, risk),
        _goal_gate('freshness', 12, freshness_status == 'fresh', freshness_status in ALERT_BLOCKING_FRESHNESS, freshness_status),
        _goal_gate('trend_volume_quality', 12, trend_quality >= 8 and volume_quality >= 4, trend_quality < 4 and volume_quality < 2, f'{trend_quality}/{volume_quality}'),
        _goal_gate('entry_plan', 10, (entry_plan or {}).get('status') == 'ready' and risk_reward >= 2, risk_reward <= 0, risk_reward),
        _goal_gate('capital_flow_confirmation', 6, has_capital_flow, False, 'present' if has_capital_flow else 'missing'),
        _goal_gate('event_risk_review', 4, has_disclosure, False, 'present' if has_disclosure else 'missing'),
    ]
    score = round(sum(_float(gate.get('contribution')) for gate in gates), 2)
    hard_blockers = [
        gate['gate']
        for gate in gates
        if gate.get('hard_blocker')
    ]
    missing_confirmations = []
    if not has_capital_flow:
        missing_confirmations.append('capital_flow')
    if not has_disclosure:
        missing_confirmations.append('disclosure_event')
    if not has_technical:
        missing_confirmations.append('technical_confirmation')
    if hard_blockers:
        verdict = 'blocked_by_guardrail'
    elif score >= 74 and action == 'BUY_CANDIDATE' and not missing_confirmations:
        verdict = 'prime_profit_candidate'
    elif score >= 62 and action in {'BUY_CANDIDATE', 'WATCH'}:
        verdict = 'candidate_needs_confirmation'
    elif score >= 48:
        verdict = 'watch_only'
    else:
        verdict = 'reject_for_now'
    return {
        'schema_version': 'mirofish.profitability_goal.v1',
        'goal': 'detect profitable stock candidates from reliable data',
        'goal_fit_score': score,
        'goal_verdict': verdict,
        'hard_blockers': hard_blockers,
        'missing_confirmations': missing_confirmations,
        'confidence_cap': confidence_cap,
        'alpha_score': alpha,
        'risk_score': risk,
        'ranking_effect': 'direct_bounded_quality_adjustment',
        'mcp_role': 'score_risk_confirmation_with_supporting_signal_limits',
        'gates': gates,
        'lookahead_safe': True,
    }


def _goal_gate(name: str, weight: float, passed: bool, failed: bool, value: Any) -> dict[str, Any]:
    if passed:
        status = 'pass'
        contribution = weight
        hard_blocker = False
    elif failed:
        status = 'fail'
        contribution = 0.0
        hard_blocker = name in {'candidate_action', 'price_liquidity', 'freshness'}
    else:
        status = 'partial'
        contribution = round(weight * 0.5, 2)
        hard_blocker = False
    return {
        'gate': name,
        'status': status,
        'weight': weight,
        'contribution': contribution,
        'hard_blocker': hard_blocker,
        'value': value,
    }


def _profitability_run_summary(
    candidates: list[dict[str, Any]],
    rejected_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    scorecards = []
    for candidate in candidates:
        profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
        scorecard = profile.get('profitability_scorecard')
        if isinstance(scorecard, dict):
            scorecards.append(scorecard)
    verdict_counts = Counter(str(card.get('goal_verdict') or 'unknown') for card in scorecards)
    blocker_counts = Counter()
    missing_counts = Counter()
    for card in scorecards:
        for blocker in card.get('hard_blockers') or []:
            blocker_counts[str(blocker)] += 1
        for missing in card.get('missing_confirmations') or []:
            missing_counts[str(missing)] += 1
    scores = [_float(card.get('goal_fit_score')) for card in scorecards]
    return {
        'schema_version': 'mirofish.profitability_goal.run.v1',
        'primary_objective': 'detect profitable stock candidates from reliable data',
        'mcp_role': 'score/risk confirmation with supporting-signal limits',
        'candidate_count': len(candidates),
        'rejected_candidate_count': len(rejected_candidates),
        'average_goal_fit_score': round(_average(scores) or 0.0, 2),
        'top_goal_fit_score': round(max(scores), 2) if scores else None,
        'verdict_counts': dict(verdict_counts),
        'hard_blocker_counts': dict(blocker_counts),
        'missing_confirmation_counts': dict(missing_counts),
        'ranking_effect': 'direct_bounded_quality_adjustment',
        'lookahead_safe': True,
    }


def _performance_advisory() -> dict[str, Any]:
    try:
        from app.services.mirofish import outcome_tracker

        advisory = outcome_tracker.get_advisory_feedback(horizon_days=5, limit_workflows=200)
    except Exception as exc:
        return {
            'available': False,
            'applied_to_scoring': False,
            'source': 'workflow_outcomes',
            'lookahead_safe': True,
            'error': f'{type(exc).__name__}: {exc}',
        }
    if not isinstance(advisory, dict):
        advisory = {}
    base = {
        'available': bool(advisory.get('evaluated_count')),
        'applied_to_scoring': bool(_float(advisory.get('evaluated_count')) >= 9),
        'source': 'workflow_outcomes',
        'lookahead_safe': bool(advisory.get('lookahead_safe', True)),
        'evaluated_count': advisory.get('evaluated_count', 0),
        'workflow_count_scanned': advisory.get('workflow_count_scanned', 0),
        'hit_rate_recent': advisory.get('hit_rate_recent'),
        'horizon_days': advisory.get('horizon_days'),
        'recommendations': advisory.get('recommendations') or {'tag_score_adjust': {}},
        'asof': advisory.get('asof'),
        'note': 'bounded ranking adjustment when enough replay-safe outcomes exist',
    }
    try:
        from app.services.mirofish import agent_actions

        overlay = agent_actions.scoring_overlay_deltas()
    except Exception:
        overlay = {}
    if overlay:
        merged = dict((base.get('recommendations') or {}).get('tag_score_adjust') or {})
        for tag, delta in overlay.items():
            merged[tag] = round(max(-2.0, min(2.0, _float(merged.get(tag)) + delta)), 2)
        base['recommendations'] = {
            **(base.get('recommendations') or {}),
            'tag_score_adjust': merged,
            'agent_overlay_applied': True,
            'agent_overlay_source': 'alpha_brain_agent',
        }
    try:
        from app.services.mirofish import learning_policy

        base['learning_policy'] = learning_policy.build_learning_policy(base, persist_guard=True)
        control = (base['learning_policy'].get('score_control') or {})
        base['applied_to_scoring'] = bool(control.get('outcome_memory_enabled'))
        base['learning_readiness'] = base['learning_policy'].get('learning_readiness')
    except Exception as exc:
        base['learning_policy'] = {
            'available': False,
            'error': f'{type(exc).__name__}: {exc}',
        }
    return {
        **base,
    }


def _resource_weight(
    item: dict[str, Any] | None,
    *,
    default_confidence: float = 0.60,
    max_age_days: int = 7,
) -> dict[str, Any]:
    if not isinstance(item, dict) or not item:
        return {
            'available': False,
            'freshness': 'missing',
            'confidence': 0.0,
            'score_weight': 0.0,
            'risk_weight': 1.0,
        }
    observed_at = _resource_observed_at(item)
    age = _age_days(observed_at)
    if age is None:
        freshness = 'unknown'
        freshness_weight = 0.45
    elif age <= max_age_days:
        freshness = 'fresh'
        freshness_weight = 1.0
    elif age <= max_age_days * 3:
        freshness = 'stale'
        freshness_weight = 0.45
    else:
        freshness = 'stale'
        freshness_weight = 0.20
    confidence = _float(item.get('confidence'))
    if confidence <= 0:
        grade = str(item.get('source_grade') or item.get('grade') or '').upper()
        confidence = {'S': 0.96, 'A': 0.90, 'B': 0.78, 'C': 0.48, 'D': 0.25}.get(grade, default_confidence)
    confidence = _clamp(confidence, 0.0, 1.0)
    score_weight = _clamp(confidence * freshness_weight, 0.0, 1.0)
    risk_weight = _clamp(1.0 + (1.0 - score_weight) * 0.75, 0.8, 1.75)
    return {
        'available': True,
        'freshness': freshness,
        'observed_at': observed_at,
        'age_days': age,
        'confidence': round(confidence, 3),
        'score_weight': round(score_weight, 3),
        'risk_weight': round(risk_weight, 3),
    }


def _resource_observed_at(item: dict[str, Any]) -> Any:
    for key in ('fetched_at', 'updated_at', 'generated_at', 'timestamp', 'date', 'scrape_date', 'observed_at'):
        value = item.get(key)
        if value:
            return value
    for key in ('quote', 'investor', 'metadata'):
        nested = item.get(key)
        if isinstance(nested, dict):
            value = _resource_observed_at(nested)
            if value:
                return value
    return None


def _first_number(item: dict[str, Any], keys: tuple[str, ...]) -> float:
    if not isinstance(item, dict):
        return 0.0
    for key in keys:
        value = item.get(key)
        if value not in (None, ''):
            return _float(value)
    for nested_key in ('score', 'metrics', 'summary'):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            value = _first_number(nested, keys)
            if value:
                return value
    return 0.0


def _age_days(value: Any, now_iso: str | None = None) -> float | None:
    if not value:
        return None
    now = _parse_dt(now_iso) or datetime.now(timezone.utc)
    dt = _parse_dt(value)
    if dt is None:
        return None
    return round(max(0, (now - dt).total_seconds() / 86400), 2)


def _freshness_label(value: Any, now_iso: str | None = None, *, max_age_days: int = 7) -> str:
    age_days = _age_days(value, now_iso)
    if age_days is None:
        return 'unknown'
    return 'fresh' if age_days <= max(1, int(max_age_days)) else 'stale'


def _freshness_max_age_days(filename: Any) -> int:
    policy = SOURCE_FILE_POLICIES.get(str(filename or ''), {})
    return int(policy.get('max_age_days') or 7)


def _evidence(source: str, field: str, score: float, value: Any) -> dict[str, Any]:
    return {
        'source': source,
        'field': field,
        'score': round(float(score), 2),
        'value': value,
        'confidence': 0.75 if value not in (None, '', 0) else 0.35,
    }


def _action(alpha: float, risk: float) -> str:
    if alpha >= 70 and risk <= 45:
        return 'BUY_CANDIDATE'
    if alpha >= 50 and risk <= 65:
        return 'WATCH'
    return 'REJECT'


def _strategy_tags(
    price_momentum: float,
    trend_quality: float,
    volume_accumulation: float,
    screener_score: float,
    vcp_score: float,
    jongga_score: float,
    risk: float,
) -> list[str]:
    tags = []
    if price_momentum >= 12:
        tags.append('momentum')
    if trend_quality >= 9:
        tags.append('trend_quality')
    if volume_accumulation >= 5:
        tags.append('volume_accumulation')
    if screener_score >= 12:
        tags.append('leading_screener')
    if vcp_score >= 8:
        tags.append('vcp_entry')
    if jongga_score >= 6:
        tags.append('jongga_setup')
    if risk >= 45:
        tags.append('risk_penalty')
    return tags or ['artifact_candidate']


def _clean_limit(value: Any, *, default: int, max_value: int = MAX_CANDIDATES) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, max(1, int(max_value))))


def _payload_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    if not isinstance(payload, dict) or key not in payload:
        return bool(default)
    return _truthy(payload.get(key))


def _clean_symbols(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    return {_symbol(item) for item in value if _symbol(item)}


def _telegram_config_status() -> dict[str, Any]:
    personal_token = os.getenv('TELEGRAM_BOT_TOKEN')
    personal_chat = os.getenv('TELEGRAM_CHAT_ID')
    channel_token = os.getenv('TELEGRAM_CHANNEL_BOT_TOKEN')
    channel_chat = os.getenv('TELEGRAM_CHANNEL_CHAT_ID')
    return {
        'personal_configured': bool(personal_token and personal_chat and 'your_bot_token' not in personal_token),
        'channel_configured': bool(channel_token and channel_chat),
        'personal_chat_present': bool(personal_chat),
        'channel_chat_present': bool(channel_chat),
    }


def _scanner_run_records() -> list[dict[str, Any]]:
    if not os.path.isdir(SCANNER_RUNS_ROOT):
        return []
    records: list[dict[str, Any]] = []
    for name in os.listdir(SCANNER_RUNS_ROOT):
        try:
            safe_id = _safe_run_id(name)
        except ValueError:
            continue
        path = os.path.join(SCANNER_RUNS_ROOT, safe_id, 'run.json')
        if not os.path.isfile(path):
            continue
        try:
            run = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(run, dict):
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
        sort_dt = _parse_dt(run.get('generated_at') or run.get('created_at')) or mtime
        records.append({'run': run, 'path': path, 'mtime': mtime, 'sort_dt': sort_dt})
    records.sort(key=lambda item: (item['sort_dt'], item['mtime']), reverse=True)
    return records


def _scanner_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': run.get('id'),
        'status': run.get('status'),
        'mode': run.get('mode'),
        'source': run.get('source'),
        'generated_at': run.get('generated_at'),
        'created_at': run.get('created_at'),
        'limit': run.get('limit'),
        'candidate_count': run.get('candidate_count'),
        'freshness': run.get('freshness'),
        'links': run.get('links'),
    }


def _scanner_schedule_times() -> list[dt_time]:
    out: list[dt_time] = []
    raw = os.getenv('ALPHA_SCANNER_TIMES', DEFAULT_SCHEDULE_TIMES)
    for item in str(raw or '').split(','):
        text = item.strip()
        if not re.fullmatch(r'\d{1,2}:\d{2}', text):
            continue
        hour_text, minute_text = text.split(':', 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append(dt_time(hour=hour, minute=minute))
    return sorted(set(out)) or [dt_time(9, 20), dt_time(11, 20), dt_time(14, 20), dt_time(15, 40), dt_time(16, 10)]


def _next_scheduled_times(now: datetime, scheduled_times: list[dt_time], *, count: int = 5) -> list[str]:
    current = now.astimezone(KST)
    out: list[str] = []
    day = current.date()
    while len(out) < count:
        if day.weekday() < 5:
            for scheduled in scheduled_times:
                candidate = datetime.combine(day, scheduled, tzinfo=KST)
                if candidate > current:
                    out.append(candidate.isoformat())
                    if len(out) >= count:
                        break
        day += timedelta(days=1)
    return out


def _scheduler_last_run_at() -> str | None:
    path = os.path.join(DATA_ROOT, 'scheduler_last_run.json')
    if not os.path.isfile(path):
        return None
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    values = []
    for key, value in data.items():
        if not str(key).startswith('alpha_scanner_') and key != 'alpha_scanner':
            continue
        parsed = _parse_scheduler_last_run_dt(value)
        if parsed is not None:
            values.append(parsed)
    if not values:
        return None
    return max(values).astimezone(KST).isoformat()


def _parse_scheduler_last_run_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(timezone.utc)


def _alert_state_path() -> str:
    return os.path.join(DATA_ROOT, 'admin_mirofish', 'alpha_scanner_alert_state.json')


def _monitor_state_path() -> str:
    return os.path.join(DATA_ROOT, 'admin_mirofish', 'alpha_scanner_monitor_state.json')


def _read_alert_state(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {'version': 1, 'sent_events': {}}
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {'version': 1, 'sent_events': {}}
    if not isinstance(data, dict):
        return {'version': 1, 'sent_events': {}}
    sent_events = data.get('sent_events')
    if not isinstance(sent_events, dict):
        sent_events = {}
    data['sent_events'] = sent_events
    data.setdefault('version', 1)
    return data


def _read_monitor_state(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {'version': 1}
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {'version': 1}
    if not isinstance(data, dict):
        return {'version': 1}
    data.setdefault('version', 1)
    return data


def _new_candidate_events(
    run: dict[str, Any],
    state: dict[str, Any],
    *,
    min_alpha: float,
    max_risk: float,
    actions: tuple[str, ...],
    max_events: int,
) -> list[dict[str, Any]]:
    seen = state.get('sent_events') or {}
    action_set = {str(action) for action in actions}
    events = []
    for candidate in run.get('candidates') or []:
        if candidate.get('action') not in action_set:
            continue
        if _float(candidate.get('alpha_score')) < min_alpha:
            continue
        if _float(candidate.get('risk_score')) > max_risk:
            continue
        event_key = _candidate_event_key(candidate)
        if event_key in seen:
            continue
        events.append({
            'event_key': event_key,
            'run_id': run.get('id'),
            'generated_at': run.get('generated_at'),
            'candidate': candidate,
        })
        if len(events) >= max(1, int(max_events)):
            break
    return events


def _update_alert_state(
    state: dict[str, Any],
    run: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    sent_events = dict(state.get('sent_events') or {})
    checked_at = run.get('generated_at')
    history = [item for item in (state.get('history') or []) if isinstance(item, dict)]
    new_history: list[dict[str, Any]] = []
    for event in events:
        candidate = event.get('candidate') or {}
        event_key = str(event.get('event_key') or _candidate_event_key(candidate))
        snapshot = _alert_event_snapshot(event, run, sent_at=checked_at)
        sent_events[event_key] = {
            'sent_at': checked_at,
            'run_id': run.get('id'),
            'rank': candidate.get('rank'),
            'symbol': candidate.get('symbol'),
            'display_name': candidate.get('display_name'),
            'market': candidate.get('market'),
            'action': candidate.get('action'),
            'horizon': candidate.get('horizon'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
            'ranking_score': candidate.get('ranking_score'),
            'price': snapshot.get('price'),
            'strategy_tags': snapshot.get('strategy_tags'),
            'signal_quality': candidate.get('signal_quality'),
        }
        new_history.append(snapshot)
    history = _merge_alert_history(history, new_history)
    last_sent_at = _latest_alert_sent_at(list(sent_events.values()) + history)
    return {
        'version': max(2, int(state.get('version') or 1)),
        'last_checked_at': checked_at,
        'last_sent_at': last_sent_at,
        'last_run_id': run.get('id'),
        'last_candidate_count': run.get('candidate_count'),
        'sent_events': sent_events,
        'history': history,
    }


def _candidate_event_key(candidate: dict[str, Any]) -> str:
    price_date = (candidate.get('price') or {}).get('date') or str(candidate.get('generated_at') or '')[:10]
    return f"{candidate.get('symbol')}:{candidate.get('action')}:{price_date}"


def _alert_event_snapshot(event: dict[str, Any], run: dict[str, Any], *, sent_at: str | None) -> dict[str, Any]:
    candidate = event.get('candidate') or {}
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    evidence = candidate.get('evidence') if isinstance(candidate.get('evidence'), list) else []
    event_key = str(event.get('event_key') or _candidate_event_key(candidate))
    return {
        'event_key': event_key,
        'sent_at': sent_at,
        'run_id': run.get('id') or event.get('run_id'),
        'generated_at': event.get('generated_at') or run.get('generated_at'),
        'rank': candidate.get('rank'),
        'symbol': candidate.get('symbol'),
        'display_name': candidate.get('display_name'),
        'market': candidate.get('market'),
        'action': candidate.get('action'),
        'horizon': candidate.get('horizon'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
        'ranking_score': candidate.get('ranking_score'),
        'signal_quality': candidate.get('signal_quality'),
        'strategy_tags': list(candidate.get('strategy_tags') or [])[:8],
        'price': {
            'current_price': price.get('current_price'),
            'change_rate': price.get('change_rate'),
            'date': price.get('date'),
        },
        'evidence': evidence[:2],
    }


def _latest_run_candidate_events(run: dict[str, Any] | None, *, limit: int = 20) -> list[dict[str, Any]]:
    """Expose latest scanner-run candidates as dashboard feed rows.

    Alert state only records committed Telegram-send events. The dashboard feed
    also needs to reflect the newest scanner run so a successful alert sender
    cannot leave the widget pinned to older sent-event snapshots.
    """
    if not isinstance(run, dict):
        return []
    generated_at = run.get('generated_at') or run.get('created_at')
    items: list[dict[str, Any]] = []
    for candidate in run.get('candidates') or []:
        if not isinstance(candidate, dict):
            continue
        event_key = f"latest:{run.get('id')}:{_candidate_event_key(candidate)}"
        item = _alert_event_snapshot(
            {
                'event_key': event_key,
                'generated_at': generated_at,
                'candidate': candidate,
            },
            run,
            sent_at=generated_at,
        )
        item['source'] = 'latest_run'
        items.append(item)
        if len(items) >= max(1, int(limit)):
            break
    return items


def _merge_alert_history(
    history: list[dict[str, Any]],
    new_entries: list[dict[str, Any]],
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for entry in history + new_entries:
        if not isinstance(entry, dict):
            continue
        key = str(
            entry.get('event_key')
            or f"{entry.get('symbol')}:{entry.get('action')}:{entry.get('sent_at')}:{entry.get('run_id')}"
        )
        current = by_key.get(key)
        if current is None or str(entry.get('sent_at') or '') >= str(current.get('sent_at') or ''):
            next_entry = dict(current or {})
            next_entry.update(entry)
            next_entry.setdefault('event_key', key)
            by_key[key] = next_entry
    items = list(by_key.values())
    items.sort(key=lambda item: str(item.get('sent_at') or item.get('generated_at') or ''), reverse=True)
    return items[: max(1, int(limit))]


def _alert_state_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    sent_events = state.get('sent_events') if isinstance(state.get('sent_events'), dict) else {}
    for key, value in sent_events.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault('event_key', str(key))
            entries.append(item)
    for value in state.get('history') or []:
        if isinstance(value, dict):
            entries.append(dict(value))
    return _merge_alert_history([], entries, limit=200)


def _latest_alert_sent_at(entries: list[dict[str, Any]]) -> str | None:
    latest: str | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = entry.get('sent_at') or entry.get('timestamp')
        if not value:
            continue
        text = str(value)
        if latest is None or text > latest:
            latest = text
    return latest


def _action_label(value: Any) -> str:
    labels = {
        'BUY_CANDIDATE': '매수 후보',
        'WATCH': '관찰',
        'REJECT': '제외',
    }
    key = str(value or '')
    if key in labels:
        return labels[key]
    return {
        'BUY_CANDIDATE': '매수 후보',
        'WATCH': '관찰',
        'REJECT': '제외',
    }.get(str(value or ''), str(value or ''))


def _horizon_label(value: Any) -> str:
    labels = {
        'swing_5_20d': '스윙 5-20일',
        'avoid_or_recheck': '회피 또는 재점검',
    }
    key = str(value or '')
    if key in labels:
        return labels[key]
    return {
        'swing_5_20d': '스윙 5-20일',
        'avoid_or_recheck': '회피 또는 재점검',
    }.get(str(value or ''), str(value or ''))


def _tag_label(value: Any) -> str:
    labels = {
        'momentum': '모멘텀',
        'trend_quality': '추세 품질',
        'volume_accumulation': '거래량 축적',
        'leading_screener': '리딩 스크리너',
        'vcp_entry': 'VCP 진입',
        'jongga_setup': '종가 셋업',
        'risk_penalty': '리스크 패널티',
        'artifact_candidate': '파일 기반 후보',
    }
    key = str(value or '')
    if key in labels:
        return labels[key]
    return {
        'momentum': '모멘텀',
        'trend_quality': '추세 품질',
        'volume_accumulation': '거래량 축적',
        'leading_screener': '리딩 스크리너',
        'vcp_entry': 'VCP 진입',
        'jongga_setup': '종가 셋업',
        'risk_penalty': '리스크 패널티',
        'artifact_candidate': '파일 기반 후보',
    }.get(str(value or ''), str(value or ''))


def _evidence_field_label(value: Any) -> str:
    labels = {
        'price_momentum': '가격 모멘텀',
        'trend_quality': '추세 품질',
        'volume_accumulation': '거래량 축적',
        'liquidity': '유동성',
        'screener_leading': '리딩 스크리너',
        'vcp_quality': 'VCP 품질',
        'jongga_setup': '종가 셋업',
        'source_convergence': '소스 수렴도',
    }
    key = str(value or '')
    if key in labels:
        return labels[key]
    return {
        'price_momentum': '가격 모멘텀',
        'trend_quality': '추세 품질',
        'volume_accumulation': '거래량 축적',
        'liquidity': '유동성',
        'screener_leading': '리딩 스크리너',
        'vcp_quality': 'VCP 품질',
        'jongga_setup': '종가 셋업',
        'source_convergence': '소스 수렴도',
    }.get(str(value or ''), str(value or ''))


def _format_signed(value: Any, suffix: str = '') -> str:
    number = _float(value)
    return f'{number:+.2f}{suffix}'


def _alert_state_summary(
    state: dict[str, Any],
    state_file: str,
    *,
    latest_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sent_events = state.get('sent_events') if isinstance(state.get('sent_events'), dict) else {}
    recent = _alert_state_entries(state)[:20]
    latest = _latest_run_candidate_events(latest_run, limit=20)
    feed = _merge_alert_history(recent, latest, limit=20)
    return {
        'state_path': state_file,
        'version': state.get('version', 1),
        'last_checked_at': state.get('last_checked_at'),
        'last_sent_at': state.get('last_sent_at') or _latest_alert_sent_at(recent),
        'last_run_id': state.get('last_run_id'),
        'last_candidate_count': state.get('last_candidate_count'),
        'sent_event_count': len(sent_events),
        'recent_sent_events': recent,
        'latest_run_id': (latest_run or {}).get('id'),
        'latest_run_at': (latest_run or {}).get('generated_at') or (latest_run or {}).get('created_at'),
        'latest_candidate_count': (latest_run or {}).get('candidate_count'),
        'latest_candidate_events': latest,
        'feed_event_count': len(feed),
        'feed_events': feed,
    }


def _monitor_state_summary(
    state: dict[str, Any],
    state_file: str,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = source or state.get('current_source') or {}
    return {
        'state_path': state_file,
        'version': state.get('version', 1),
        'last_checked_at': state.get('last_checked_at'),
        'last_processed_at': state.get('last_processed_at'),
        'last_status': state.get('last_status'),
        'last_run_id': state.get('last_run_id'),
        'last_candidate_count': state.get('last_candidate_count'),
        'last_new_event_count': state.get('last_new_event_count'),
        'last_telegram_sent': state.get('last_telegram_sent'),
        'last_error': state.get('last_error'),
        'last_source_fingerprint': state.get('last_source_fingerprint'),
        'last_failed_source_fingerprint': state.get('last_failed_source_fingerprint'),
        'last_failed_at': state.get('last_failed_at'),
        'current_source_fingerprint': source.get('fingerprint'),
        'source_changed': state.get('last_source_fingerprint') != source.get('fingerprint'),
        'source': source,
    }


def _run_id(generated_at: str, symbols: set[str], limit: int) -> str:
    seed = json.dumps(
        {'generated_at': generated_at, 'symbols': sorted(symbols), 'limit': limit},
        sort_keys=True,
    )
    digest = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]
    stamp = re.sub(r'[^0-9]', '', generated_at)[:14]
    return f'mfas_{stamp}_{digest}'


def _run_path(run_id: str) -> str:
    safe_id = _safe_run_id(run_id)
    return os.path.join(SCANNER_RUNS_ROOT, safe_id, 'run.json')


def _run_artifact_path(run_id: str, filename: str) -> str:
    safe_id = _safe_run_id(run_id)
    safe_filename = str(filename or '').strip()
    if safe_filename not in SCANNER_ARTIFACT_FILENAMES:
        raise ValueError('invalid scanner artifact')
    return os.path.join(SCANNER_RUNS_ROOT, safe_id, safe_filename)


def _safe_run_id(run_id: str) -> str:
    safe_id = str(run_id or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{8,80}', safe_id):
        raise ValueError('invalid scanner run_id')
    return safe_id


def _read_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def _symbol(value: Any) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    return digits.zfill(6)[-6:] if digits else ''


def _clean_name(value: Any) -> str:
    text = str(value or '').strip()
    return text if text else ''


def _float(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0


def _nested_get(data: dict[str, Any], path: list[str]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_float(data: dict[str, Any], path: list[str]) -> float:
    return _float(_nested_get(data, path))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y'}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _escape(value: Any) -> str:
    return html.escape(str(value or ''), quote=False)


def _format_number(value: Any) -> str:
    number = _float(value)
    if number == 0:
        return '0'
    if number.is_integer():
        return f'{int(number):,}'
    return f'{number:,.2f}'


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        text = f'{text}T00:00:00+00:00'
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
