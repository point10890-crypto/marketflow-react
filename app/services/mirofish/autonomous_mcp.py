"""Autonomous MiroFish MCP control-plane.

This module keeps the automation policy separate from the MCP SDK adapter.
The actual alpha engines already live in alpha_scanner, workflow, and
outcome_tracker; this layer adds security gates, audit logging, and compact
tool-shaped functions around them.
"""

from __future__ import annotations

import hmac
import csv
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import app.services.mirofish.alpha_scanner as alpha_scanner
import app.services.mirofish.outcome_tracker as outcome_tracker
import app.services.mirofish.workflow as workflow
from app.utils.atomic_json import write_json_atomic


REPO_ROOT = Path(__file__).resolve().parents[3]
AUTONOMOUS_ROOT = REPO_ROOT / 'data' / 'admin_mirofish' / 'autonomous_mcp'
AUDIT_LOG_PATH = AUTONOMOUS_ROOT / 'audit.jsonl'
LEARNING_FEEDBACK_PATH = AUTONOMOUS_ROOT / 'learning_feedback.json'
SAFE_ARTIFACT_ROOT = REPO_ROOT / 'data' / 'admin_mirofish'

MUTATION_ENV = 'MIROFISH_MCP_ALLOW_MUTATION'
SHARED_SECRET_ENV = 'MIROFISH_MCP_SHARED_SECRET'
CONFIRM_SEND_PHRASE = 'SEND_MIROFISH_AUTONOMOUS_ALERT'
MCP_HTTP_URL_ENV = 'MIROFISH_MCP_HTTP_URL'
DEFAULT_MCP_HTTP_URL = 'http://127.0.0.1:8765/mcp'
MCP_STARTUP_TASK = 'MarketFlow-MiroFish-MCP'
MCP_WATCHDOG_TASK = 'MarketFlow-MiroFish-MCP-Watchdog'

KST = timezone(timedelta(hours=9))

MAX_LIMIT = 100
MAX_EVENTS = 20
MAX_TOP_N = 10
MAX_PARALLEL = 8
MAX_AGENT_COUNT = 15
SAFE_ARTIFACT_MAX_BYTES = 256 * 1024
SAFE_ARTIFACT_LIST_LIMIT = 100
SAFE_ARTIFACT_EXTENSIONS = {'.json', '.jsonl', '.md', '.txt'}
SAFE_ARTIFACT_DIRS = {'runs', 'scanner_runs', 'workflows', 'autonomous_mcp'}
SAFE_ARTIFACT_STATE_FILES = {
    'alpha_scanner_alert_state.json',
    'alpha_scanner_monitor_state.json',
    'ekg.json',
}
SAFE_ARTIFACT_KINDS = SAFE_ARTIFACT_DIRS | {'all', 'state'}

SENSITIVE_KEY_PARTS = (
    'api_key',
    'authorization',
    'bot_token',
    'cloudflare',
    'kis',
    'password',
    'secret',
    'telegram',
    'token',
)


ToolSender = Callable[[str], bool]


def get_autonomous_status() -> dict[str, Any]:
    """Return a redacted operator view of the autonomous MCP control-plane."""
    return {
        'service': 'mirofish-autonomous-mcp',
        'ready': True,
        'mode': 'scanner_workflow_learning_telegram_control_plane',
        'mutation_enabled': _env_bool(MUTATION_ENV, False),
        'shared_secret_configured': bool(os.getenv(SHARED_SECRET_ENV)),
        'send_confirmation_phrase': CONFIRM_SEND_PHRASE,
        'telegram': _telegram_config_status(),
        'scanner': alpha_scanner.get_scanner_schedule_status(),
        'workflow': workflow.get_workflow_status(),
        'learning': _learning_summary(read_learning_feedback()),
        'runtime': {
            'mcp_server': _mcp_http_status(),
            'startup_task': _scheduled_task_status(MCP_STARTUP_TASK),
            'watchdog_task': _scheduled_task_status(MCP_WATCHDOG_TASK),
        },
        'tools': [
            'get_autonomous_status',
            'get_mcp_security_policy',
            'get_market_clock',
            'get_repository_state',
            'list_safe_artifacts',
            'read_safe_artifact',
            'run_candidate_detection_alert',
            'run_autonomous_scan_analysis',
            'refresh_learning_feedback',
            'send_latest_workflow_telegram',
            'list_recent_scanner_runs',
            'list_recent_workflows',
        ],
        'resources': [
            'mirofish://autonomous/status',
            'mirofish://autonomous/security',
            'mirofish://autonomous/learning',
            'mirofish://market/clock',
            'mirofish://scanner/latest',
            'mirofish://workflows/latest',
        ],
        'checked_at': _now_iso(),
    }


def get_mcp_security_policy() -> dict[str, Any]:
    """Return the redacted MCP security policy and tool allowlist."""
    return {
        'service': 'mirofish-mcp-security-policy',
        'mode': 'read_only_wrappers_plus_guarded_mutation',
        'mutation_enabled': _env_bool(MUTATION_ENV, False),
        'mutation_env': MUTATION_ENV,
        'shared_secret_configured': bool(os.getenv(SHARED_SECRET_ENV)),
        'shared_secret_env': SHARED_SECRET_ENV,
        'send_confirmation_phrase': CONFIRM_SEND_PHRASE,
        'telegram': _telegram_config_status(),
        'read_only_tools': [
            'get_autonomous_status',
            'get_mcp_security_policy',
            'get_market_clock',
            'get_repository_state',
            'list_recent_scanner_runs',
            'list_recent_workflows',
            'list_safe_artifacts',
            'read_safe_artifact',
        ],
        'mutating_tools': [
            'run_candidate_detection_alert',
            'run_autonomous_scan_analysis',
            'refresh_learning_feedback',
            'send_latest_workflow_telegram',
        ],
        'artifact_allowlist_root': 'data/admin_mirofish',
        'artifact_allowed_dirs': sorted(SAFE_ARTIFACT_DIRS),
        'artifact_allowed_state_files': sorted(SAFE_ARTIFACT_STATE_FILES),
        'artifact_allowed_extensions': sorted(SAFE_ARTIFACT_EXTENSIONS),
        'artifact_max_bytes': SAFE_ARTIFACT_MAX_BYTES,
        'guards': [
            'generic filesystem/git/fetch MCP servers are not exposed',
            'artifact reads are relative-path only and confined to data/admin_mirofish',
            'artifact reads reject unsupported extensions and oversized files',
            'mutating tools require mutation env flag',
            'shared secret is required when configured',
            'Telegram sends require an explicit confirmation phrase',
            'audit logs redact token, secret, key, password, KIS, Cloudflare, and Telegram fields',
        ],
        'checked_at': _now_iso(),
    }


def get_market_clock(now: datetime | None = None) -> dict[str, Any]:
    """Return a deterministic KST market-session helper for MCP operators."""
    current = (now or datetime.now(KST)).astimezone(KST)
    session_start = current.replace(hour=9, minute=0, second=0, microsecond=0)
    session_end = current.replace(hour=15, minute=30, second=0, microsecond=0)
    is_weekday = current.weekday() < 5
    is_regular = is_weekday and session_start <= current <= session_end
    if not is_weekday:
        phase = 'closed_weekend'
    elif current < session_start:
        phase = 'pre_open'
    elif current <= session_end:
        phase = 'regular_session'
    else:
        phase = 'after_close'
    scanner_status = alpha_scanner.get_scanner_schedule_status(now=current)
    return {
        'timezone': 'Asia/Seoul',
        'now': current.isoformat(),
        'date': current.date().isoformat(),
        'is_weekday': is_weekday,
        'kr_regular_session': is_regular,
        'session_phase': phase,
        'session': {
            'start': session_start.isoformat(),
            'end': session_end.isoformat(),
        },
        'scanner': {
            'enabled': bool(scanner_status.get('enabled')),
            'scheduled_times': scanner_status.get('scheduled_times') or [],
            'next_scheduled_at': scanner_status.get('next_scheduled_at'),
            'freshness_status': scanner_status.get('freshness_status'),
            'last_run_id': scanner_status.get('last_run_id'),
            'last_run_at': scanner_status.get('last_run_at'),
        },
        'note': 'holiday calendar is not applied; weekend and regular-session time checks only',
        'checked_at': _now_iso(),
    }


def get_repository_state() -> dict[str, Any]:
    """Return a read-only git state summary without exposing file contents."""
    branch = _git_output(['rev-parse', '--abbrev-ref', 'HEAD'])
    commit = _git_output(['rev-parse', 'HEAD'])
    last_commit = _git_output(['log', '-1', '--format=%cI|%s'])
    status = _git_output(['status', '--short', '--untracked-files=all'], allow_failure=True)
    status_lines = [line for line in status.splitlines() if line.strip()]
    last_commit_at = None
    last_commit_subject = None
    if '|' in last_commit:
        last_commit_at, last_commit_subject = last_commit.split('|', 1)
    return {
        'ok': bool(branch and commit),
        'repo_root': str(REPO_ROOT),
        'branch': branch or None,
        'head': commit or None,
        'short_head': commit[:12] if commit else None,
        'last_commit_at': last_commit_at,
        'last_commit_subject': last_commit_subject,
        'dirty': bool(status_lines),
        'dirty_count': len(status_lines),
        'dirty_entries': [_safe_dirty_entry(line) for line in status_lines[:80]],
        'dirty_entries_truncated': len(status_lines) > 80,
        'checked_at': _now_iso(),
    }


def list_safe_artifacts(kind: str = 'all', limit: int = 50) -> dict[str, Any]:
    """List read-only artifacts under the explicit MiroFish allowlist."""
    clean_kind = str(kind or 'all').strip().lower()
    if clean_kind not in SAFE_ARTIFACT_KINDS:
        raise ValueError(f'kind must be one of: {", ".join(sorted(SAFE_ARTIFACT_KINDS))}')
    clean_limit = _int(limit, 50, 1, SAFE_ARTIFACT_LIST_LIMIT)
    roots = _safe_artifact_roots(clean_kind)
    items: list[dict[str, Any]] = []
    for root in roots:
        if root.is_file():
            candidate_files = [root]
        elif root.is_dir():
            candidate_files = [path for path in root.rglob('*') if path.is_file()]
        else:
            continue
        for path in candidate_files:
            if path.suffix.lower() not in SAFE_ARTIFACT_EXTENSIONS:
                continue
            try:
                safe_path = _resolve_safe_artifact_path(_safe_artifact_relpath(path))
                stat = safe_path.stat()
            except (OSError, ValueError):
                continue
            items.append({
                'path': _safe_artifact_relpath(safe_path),
                'kind': _artifact_kind(safe_path),
                'format': safe_path.suffix.lower().lstrip('.'),
                'size_bytes': stat.st_size,
                'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                'readable': stat.st_size <= SAFE_ARTIFACT_MAX_BYTES,
            })
    items.sort(key=lambda item: str(item.get('modified_at') or ''), reverse=True)
    return {
        'root': 'data/admin_mirofish',
        'kind': clean_kind,
        'limit': clean_limit,
        'count': min(len(items), clean_limit),
        'total_matched': len(items),
        'truncated': len(items) > clean_limit,
        'items': items[:clean_limit],
        'checked_at': _now_iso(),
    }


def read_safe_artifact(path: str) -> dict[str, Any]:
    """Read a small allowlisted MiroFish artifact without arbitrary filesystem access."""
    safe_path = _resolve_safe_artifact_path(path)
    if not safe_path.is_file():
        raise ValueError('artifact not found')
    if safe_path.suffix.lower() not in SAFE_ARTIFACT_EXTENSIONS:
        raise ValueError('unsupported artifact extension')
    stat = safe_path.stat()
    relpath = _safe_artifact_relpath(safe_path)
    if stat.st_size > SAFE_ARTIFACT_MAX_BYTES:
        return {
            'ok': False,
            'status': 'too_large',
            'path': relpath,
            'size_bytes': stat.st_size,
            'max_bytes': SAFE_ARTIFACT_MAX_BYTES,
            'checked_at': _now_iso(),
        }
    text = safe_path.read_text(encoding='utf-8', errors='replace')
    suffix = safe_path.suffix.lower()
    if suffix == '.json':
        content: Any = json.loads(text)
    elif suffix == '.jsonl':
        content = [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]
    else:
        content = text
    return {
        'ok': True,
        'status': 'ok',
        'path': relpath,
        'kind': _artifact_kind(safe_path),
        'format': suffix.lstrip('.'),
        'size_bytes': stat.st_size,
        'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        'content': content,
        'checked_at': _now_iso(),
    }


def list_recent_scanner_runs(limit: int = 20) -> dict[str, Any]:
    clean_limit = _int(limit, 20, 1, MAX_LIMIT)
    return {'runs': alpha_scanner.list_scanner_runs(limit=clean_limit)}


def list_recent_workflows(limit: int = 20) -> dict[str, Any]:
    clean_limit = _int(limit, 20, 1, MAX_LIMIT)
    return {'workflows': workflow.list_workflows(limit=clean_limit)}


def run_candidate_detection_alert(
    payload: dict[str, Any] | None = None,
    *,
    send_fn: ToolSender | None = None,
) -> dict[str, Any]:
    """Run deterministic candidate detection, optionally sending Telegram.

    Defaults to dry-run preview. Real Telegram sends require mutation mode,
    shared-secret validation when configured, and the confirmation phrase.
    """
    payload = dict(payload or {})
    dry_run = _bool(payload.get('dry_run'), True)
    send_telegram = _bool(payload.get('send_telegram'), False)
    try:
        if not dry_run and send_telegram:
            _require_mutation(payload, 'run_candidate_detection_alert', require_send_confirmation=True)
        elif not dry_run:
            _require_mutation(payload, 'run_candidate_detection_alert')
    except Exception as exc:
        _audit('run_candidate_detection_alert', payload, _error_result(exc), status='rejected')
        raise

    scanner_payload = _scanner_payload(payload)
    min_alpha = _float(payload.get('min_alpha'), alpha_scanner.DEFAULT_ALERT_MIN_ALPHA)
    max_risk = _float(payload.get('max_risk'), alpha_scanner.DEFAULT_ALERT_MAX_RISK)
    max_events = _int(payload.get('max_events'), alpha_scanner.DEFAULT_ALERT_MAX_EVENTS, 1, MAX_EVENTS)
    commit_state = _bool(payload.get('commit_state'), send_telegram)
    channel = _bool(payload.get('channel'), False)
    result: dict[str, Any] | None = None
    try:
        result = alpha_scanner.run_scanner_alert_check(
            scanner_payload,
            min_alpha=min_alpha,
            max_risk=max_risk,
            max_events=max_events,
            commit_state=False,
            block_on_stale=not _bool(payload.get('allow_stale_sources'), False),
        )
        events = result.get('events') or []
        result.update({
            'ok': True,
            'status': 'dry_run' if dry_run else 'checked',
            'dry_run': dry_run,
            'telegram_sent': False,
            'state_committed': False,
        })
        if not dry_run and send_telegram and events:
            scanner_message = result.get('message') or ''
            ok = _send_message(scanner_message, send_fn=send_fn, channel=channel)
            # AIbain_bot 병렬 알림 (설정 시) — 신규 5종 후보 알림
            try:
                from app.utils.aibain_notify import send_scanner_alert
                aibain_sent = send_scanner_alert(scanner_message)
                result['aibain_sent'] = aibain_sent
            except Exception as exc:
                result['aibain_sent'] = False
                result['aibain_error'] = f'{type(exc).__name__}: {exc}'
            result['telegram_sent'] = ok
            result['status'] = 'sent' if ok else 'send_failed'
            result['ok'] = ok
            if ok and commit_state:
                result['state'] = alpha_scanner.commit_scanner_alert_events(result)
                result['state_committed'] = True
        elif not dry_run and commit_state:
            result['state'] = alpha_scanner.commit_scanner_alert_events(result)
            result['state_committed'] = True
        return _with_links(_summarize_detection_result(result))
    except Exception as exc:
        _audit('run_candidate_detection_alert', payload, _error_result(exc), status='failed')
        raise
    finally:
        if result is not None:
            _audit('run_candidate_detection_alert', payload, _summarize_detection_result(result), status=str(result.get('status') or 'ok'))


def run_autonomous_scan_analysis(
    payload: dict[str, Any] | None = None,
    *,
    send_fn: ToolSender | None = None,
) -> dict[str, Any]:
    """Run scanner -> GraphRAG workflow -> learning/outcome loop.

    This is the main autonomous MCP action. It defaults to dry-run so an LLM
    can inspect candidates before spending tokens, committing event state, or
    sending Telegram.
    """
    payload = dict(payload or {})
    dry_run = _bool(payload.get('dry_run'), True)
    sync = _bool(payload.get('sync'), False)
    send_telegram = _bool(payload.get('send_telegram'), False)
    commit_event_state = _bool(payload.get('commit_event_state'), send_telegram)
    try:
        if not dry_run and send_telegram:
            _require_mutation(payload, 'run_autonomous_scan_analysis', require_send_confirmation=True)
        elif not dry_run:
            _require_mutation(payload, 'run_autonomous_scan_analysis')
    except Exception as exc:
        _audit('run_autonomous_scan_analysis', payload, _error_result(exc), status='rejected')
        raise

    workflow_payload = _workflow_payload(payload)
    workflow_payload['dry_run'] = dry_run
    result: dict[str, Any] | None = None
    try:
        result = workflow.start_workflow_from_scanner_events(
            workflow_payload,
            async_mode=(not sync) and (not dry_run),
            commit_event_state=False if send_telegram else commit_event_state,
        )
        result = dict(result)
        result['dry_run'] = dry_run
        result['telegram_sent'] = False
        result['event_state_committed'] = bool(result.get('event_state_committed'))

        if not dry_run and sync and result.get('status') == 'completed':
            if _bool(payload.get('refresh_learning'), True):
                learning = refresh_learning_feedback({'limit': 20, 'commit': True, 'api_key': payload.get('api_key')})
                result['learning_feedback'] = _learning_summary(learning)
            if send_telegram and result.get('top3'):
                top3_message = workflow.build_workflow_top3_telegram_message(result)
                ok = _send_message(
                    top3_message,
                    send_fn=send_fn,
                    channel=_bool(payload.get('channel'), False),
                )
                # AIbain_bot 병렬 알림 (설정된 경우만, 실패해도 메인 흐름 무영향)
                try:
                    from app.utils.aibain_notify import send_workflow_top3
                    aibain_sent = send_workflow_top3(top3_message)
                    result['aibain_sent'] = aibain_sent
                except Exception as exc:
                    result['aibain_sent'] = False
                    result['aibain_error'] = f'{type(exc).__name__}: {exc}'
                result['telegram_sent'] = ok
                result['telegram_sent_at'] = _now_iso() if ok else None
                if ok and commit_event_state:
                    result['event_state'] = workflow.commit_workflow_event_state(result)
                    result['event_state_committed'] = True
                elif not ok:
                    result['ok'] = False
                    result['status'] = 'telegram_send_failed'
            elif commit_event_state:
                result['event_state'] = workflow.commit_workflow_event_state(result)
                result['event_state_committed'] = True
        elif send_telegram and not sync:
            result['telegram_skipped_reason'] = 'async_workflow_not_completed'

        result.setdefault('ok', result.get('status') not in {'failed', 'telegram_send_failed'})
        return _with_links(_summarize_workflow_result(result))
    except Exception as exc:
        _audit('run_autonomous_scan_analysis', payload, _error_result(exc), status='failed')
        raise
    finally:
        if result is not None:
            _audit('run_autonomous_scan_analysis', payload, _summarize_workflow_result(result), status=str(result.get('status') or 'ok'))


def refresh_learning_feedback(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh outcome-derived learning feedback without changing live weights."""
    payload = dict(payload or {})
    commit = _bool(payload.get('commit'), True)
    if commit:
        try:
            _require_mutation(payload, 'refresh_learning_feedback')
        except Exception as exc:
            _audit('refresh_learning_feedback', payload, _error_result(exc), status='rejected')
            raise
    limit = _int(payload.get('limit'), 20, 1, MAX_LIMIT)
    workflows = workflow.list_workflows(limit=limit)
    refreshed: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for summary in workflows:
        workflow_id = str(summary.get('id') or '')
        if not workflow_id:
            continue
        record = workflow.read_workflow(workflow_id)
        if not isinstance(record, dict) or record.get('status') != 'completed':
            continue
        try:
            outcomes = (
                outcome_tracker.refresh_workflow_outcomes(workflow_id, workflow=record)
                if commit
                else outcome_tracker.read_workflow_outcomes(workflow_id)
            )
        except Exception as exc:
            errors.append({'workflow_id': workflow_id, 'error': f'{type(exc).__name__}: {exc}'})
            continue
        if not isinstance(outcomes, dict):
            continue
        refreshed.append({
            'workflow_id': workflow_id,
            'status': outcomes.get('status'),
            'summary': outcomes.get('summary') or {},
        })
        all_items.extend([item for item in (outcomes.get('items') or []) if isinstance(item, dict)])

    feedback = _build_learning_feedback(refreshed, all_items, errors)
    if commit:
        write_json_atomic(str(LEARNING_FEEDBACK_PATH), feedback, sort_keys=False)
    _audit('refresh_learning_feedback', payload, _learning_summary(feedback), status='completed')
    return feedback


def read_learning_feedback() -> dict[str, Any] | None:
    if not LEARNING_FEEDBACK_PATH.is_file():
        return None
    with LEARNING_FEEDBACK_PATH.open('r', encoding='utf-8') as handle:
        return json.load(handle)


def send_latest_workflow_telegram(
    payload: dict[str, Any] | None = None,
    *,
    send_fn: ToolSender | None = None,
) -> dict[str, Any]:
    """Send the latest or selected workflow Top-N message to Telegram."""
    payload = dict(payload or {})
    try:
        _require_mutation(payload, 'send_latest_workflow_telegram', require_send_confirmation=True)
    except Exception as exc:
        _audit('send_latest_workflow_telegram', payload, _error_result(exc), status='rejected')
        raise
    workflow_id = str(payload.get('workflow_id') or '').strip()
    record = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
    if not isinstance(record, dict):
        raise ValueError('workflow not found')
    message = workflow.build_workflow_top3_telegram_message(record)
    ok = _send_message(message, send_fn=send_fn, channel=_bool(payload.get('channel'), False))
    # AIbain_bot 병렬 알림 (설정 시)
    aibain_sent = False
    try:
        from app.utils.aibain_notify import send_workflow_top3
        aibain_sent = send_workflow_top3(message)
    except Exception:
        aibain_sent = False
    result = {
        'ok': ok,
        'status': 'sent' if ok else 'send_failed',
        'workflow_id': record.get('id'),
        'aibain_sent': aibain_sent,
        'telegram_sent': ok,
        'telegram_sent_at': _now_iso() if ok else None,
        'message_chars': len(message),
        'event_state_committed': False,
    }
    if ok and _bool(payload.get('commit_event_state'), True):
        result['event_state'] = workflow.commit_workflow_event_state(record)
        result['event_state_committed'] = True
    _audit('send_latest_workflow_telegram', payload, result, status=str(result['status']))
    return result


def _git_output(args: list[str], *, allow_failure: bool = False) -> str:
    try:
        completed = subprocess.run(
            ['git', *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    if completed.returncode != 0 and not allow_failure:
        return ''
    return (completed.stdout or '').strip()


def _mcp_http_status() -> dict[str, Any]:
    """Probe the local MCP HTTP adapter without exposing credentials."""
    url = str(os.getenv(MCP_HTTP_URL_ENV) or DEFAULT_MCP_HTTP_URL).strip() or DEFAULT_MCP_HTTP_URL
    payload = {
        'jsonrpc': '2.0',
        'id': 'marketflow-status',
        'method': 'initialize',
        'params': {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {
                'name': 'marketflow-status',
                'version': '1.0',
            },
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Accept': 'application/json, text/event-stream',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            raw_body = response.read(64 * 1024).decode('utf-8', errors='replace')
            body = _json_loads(raw_body)
            result = body.get('result') if isinstance(body, dict) else {}
            server_info = result.get('serverInfo') if isinstance(result, dict) else {}
            return {
                'url': url,
                'healthy': 200 <= int(response.status) < 300,
                'status_code': int(response.status),
                'server_name': str(server_info.get('name') or '') or None,
                'server_version': str(server_info.get('version') or '') or None,
                'checked_at': _now_iso(),
            }
    except urllib.error.HTTPError as exc:
        return {
            'url': url,
            'healthy': False,
            'status_code': int(exc.code),
            'error': 'http_error',
            'checked_at': _now_iso(),
        }
    except Exception as exc:
        return {
            'url': url,
            'healthy': False,
            'status_code': None,
            'error': _safe_error_message(exc),
            'checked_at': _now_iso(),
        }


def _scheduled_task_status(task_name: str) -> dict[str, Any]:
    """Return a redacted Windows scheduled-task status summary."""
    status: dict[str, Any] = {
        'task_name': task_name,
        'registered': False,
        'query_ok': False,
        'platform': os.name,
        'checked_at': _now_iso(),
    }
    if os.name != 'nt':
        status['error'] = 'not_windows'
        return status
    try:
        completed = subprocess.run(
            ['schtasks', '/Query', '/TN', task_name, '/V', '/FO', 'CSV'],
            capture_output=True,
            text=True,
            encoding='mbcs',
            errors='replace',
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        status['error'] = _safe_error_message(exc)
        return status

    status['query_ok'] = completed.returncode == 0
    status['registered'] = completed.returncode == 0
    status['return_code'] = completed.returncode
    if completed.returncode != 0:
        status['error'] = _safe_task_error(completed.stderr or completed.stdout)
        return status

    row = _first_csv_row(completed.stdout)
    status.update({
        'state': _row_value(row, 'Status', '상태'),
        'next_run_time': _row_value(row, 'Next Run Time', '다음 실행 시간'),
        'last_run_time': _row_value(row, 'Last Run Time', '마지막 실행 시간'),
        'last_result': _row_value(row, 'Last Result', '마지막 결과'),
    })
    return status


def _first_csv_row(raw: str) -> dict[str, str]:
    clean = (raw or '').strip().lstrip('\ufeff')
    if not clean:
        return {}
    try:
        reader = csv.DictReader(io.StringIO(clean))
        for row in reader:
            return {
                str(key or '').strip().lstrip('\ufeff'): str(value or '').strip()
                for key, value in row.items()
                if key
            }
    except csv.Error:
        return {}
    return {}


def _row_value(row: dict[str, str], *names: str) -> str | None:
    if not row:
        return None
    lower = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        direct = row.get(name)
        if direct:
            return direct
        folded = lower.get(name.casefold())
        if folded:
            return folded
    return None


def _json_loads(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or '{}')
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _safe_error_message(exc: Exception) -> str:
    return re.sub(r'\s+', ' ', str(exc))[:200] or exc.__class__.__name__


def _safe_task_error(raw: str) -> str:
    clean = re.sub(r'\s+', ' ', str(raw or '')).strip()
    return clean[:200] or 'task_query_failed'


def _safe_dirty_entry(entry: str) -> str:
    clean = entry.strip()
    lower = clean.lower()
    if '.env' in lower or any(part in lower for part in SENSITIVE_KEY_PARTS):
        status = clean[:3].strip()
        return f'{status} [REDACTED_PATH]'
    return clean[:300]


def _safe_artifact_roots(kind: str) -> list[Path]:
    if kind == 'all':
        return [SAFE_ARTIFACT_ROOT / name for name in sorted(SAFE_ARTIFACT_DIRS)] + [
            SAFE_ARTIFACT_ROOT / name for name in sorted(SAFE_ARTIFACT_STATE_FILES)
        ]
    if kind == 'state':
        return [SAFE_ARTIFACT_ROOT / name for name in sorted(SAFE_ARTIFACT_STATE_FILES)]
    return [SAFE_ARTIFACT_ROOT / kind]


def _resolve_safe_artifact_path(path: str) -> Path:
    clean = _resource_to_artifact_path(str(path or '').strip()).replace('\\', '/')
    prefix = 'data/admin_mirofish/'
    if clean.startswith(prefix):
        clean = clean[len(prefix):]
    if not clean:
        raise ValueError('artifact path is required')
    if clean.startswith('/') or re.match(r'^[A-Za-z]:', clean):
        raise ValueError('absolute artifact paths are not allowed')
    if clean == '..' or clean.startswith('../') or '/..' in clean:
        raise ValueError('artifact path traversal is not allowed')
    candidate = (SAFE_ARTIFACT_ROOT / clean).resolve()
    safe_root = SAFE_ARTIFACT_ROOT.resolve()
    try:
        relpath = candidate.relative_to(safe_root)
    except ValueError:
        raise ValueError('artifact path outside allowlist')
    parts = relpath.parts
    if not parts:
        raise ValueError('artifact path is required')
    first = parts[0]
    if first in SAFE_ARTIFACT_DIRS:
        return candidate
    if len(parts) == 1 and first in SAFE_ARTIFACT_STATE_FILES:
        return candidate
    raise ValueError('artifact path is outside the MiroFish allowlist')


def _resource_to_artifact_path(path: str) -> str:
    if path == 'mirofish://scanner/latest':
        latest = alpha_scanner.read_latest_scanner_run() or {}
        run_id = _safe_identifier(latest.get('id'), 'scanner run id')
        return f'scanner_runs/{run_id}/run.json'
    match = re.fullmatch(r'mirofish://scanner/runs/([^/]+)', path)
    if match:
        return f'scanner_runs/{_safe_identifier(match.group(1), "scanner run id")}/run.json'
    if path == 'mirofish://workflows/latest':
        latest = workflow.read_latest_workflow() or {}
        workflow_id = _safe_identifier(latest.get('id'), 'workflow id')
        return f'workflows/{workflow_id}/workflow.json'
    match = re.fullmatch(r'mirofish://workflows/([^/]+)', path)
    if match:
        return f'workflows/{_safe_identifier(match.group(1), "workflow id")}/workflow.json'
    if path == 'mirofish://autonomous/learning':
        return 'autonomous_mcp/learning_feedback.json'
    if path == 'mirofish://autonomous/audit':
        return 'autonomous_mcp/audit.jsonl'
    return path


def _safe_identifier(value: Any, label: str) -> str:
    text = str(value or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', text):
        raise ValueError(f'invalid {label}')
    return text


def _safe_artifact_relpath(path: Path) -> str:
    return str(path.resolve().relative_to(SAFE_ARTIFACT_ROOT.resolve())).replace('\\', '/')


def _artifact_kind(path: Path) -> str:
    relpath = path.resolve().relative_to(SAFE_ARTIFACT_ROOT.resolve())
    first = relpath.parts[0] if relpath.parts else ''
    return 'state' if first in SAFE_ARTIFACT_STATE_FILES else first


def _build_learning_feedback(
    workflows: list[dict[str, Any]],
    items: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    evaluated = [item for item in items if item.get('status') in {'partial', 'evaluated'}]
    hits = [item for item in evaluated if item.get('hit') is True]
    misses = [item for item in evaluated if item.get('hit') is False]
    returns = [_number(item.get('forward_return_pct')) for item in evaluated if item.get('forward_return_pct') is not None]
    hit_rate = round((len(hits) / len(evaluated)) * 100, 1) if evaluated else None
    avg_return = round(sum(returns) / len(returns), 2) if returns else None
    recommendations: list[dict[str, Any]] = []
    if hit_rate is not None and hit_rate < 40:
        recommendations.append({
            'type': 'risk_gate',
            'action': 'tighten',
            'reason': 'recent evaluated hit rate is below 40%',
            'suggested_change': 'raise min_alpha or lower max_risk before Telegram alerts',
        })
    if avg_return is not None and avg_return < 0:
        recommendations.append({
            'type': 'entry_timing',
            'action': 'delay_or_confirm',
            'reason': 'average forward return is negative',
            'suggested_change': 'require trend/volume confirmation before BUY_CANDIDATE alerts',
        })
    if not recommendations and evaluated:
        recommendations.append({
            'type': 'keep_current_weights',
            'action': 'monitor',
            'reason': 'recent evaluated outcomes do not require automatic production weight changes',
        })
    return {
        'service': 'mirofish-autonomous-learning',
        'generated_at': _now_iso(),
        'mode': 'advisory_feedback_only',
        'production_weights_mutated': False,
        'lookahead_safe': True,
        'workflow_count': len(workflows),
        'item_count': len(items),
        'evaluated_count': len(evaluated),
        'hit_count': len(hits),
        'miss_count': len(misses),
        'hit_rate_pct': hit_rate,
        'average_forward_return_pct': avg_return,
        'workflows': workflows,
        'recommendations': recommendations,
        'errors': errors,
    }


def _workflow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        'limit': _int(payload.get('limit'), 20, 1, MAX_LIMIT),
        'min_alpha': _float(payload.get('min_alpha'), workflow.DEFAULT_MIN_ALPHA),
        'max_risk': _float(payload.get('max_risk'), workflow.DEFAULT_MAX_RISK),
        'max_events': _int(payload.get('max_events'), workflow.DEFAULT_MAX_EVENTS, 1, MAX_EVENTS),
        'agent_count': _int(payload.get('agent_count'), workflow.DEFAULT_AGENT_COUNT, 1, MAX_AGENT_COUNT),
        'top_n': _int(payload.get('top_n'), workflow.DEFAULT_TOP_N, 1, MAX_TOP_N),
        'max_parallel': _int(payload.get('max_parallel'), workflow.DEFAULT_MAX_PARALLEL, 1, MAX_PARALLEL),
        'allow_stale_sources': _bool(payload.get('allow_stale_sources'), False),
        'force': _bool(payload.get('force'), False),
        'mode': _mode(payload.get('mode')),
    }
    symbols = _symbols(payload.get('symbols'))
    if symbols:
        result['symbols'] = symbols
    actions = _actions(payload.get('actions'))
    if actions:
        result['actions'] = actions
    return result


def _scanner_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {'limit': _int(payload.get('limit'), 20, 1, MAX_LIMIT)}
    symbols = _symbols(payload.get('symbols'))
    if symbols:
        result['symbols'] = symbols
    return result


def _require_mutation(
    payload: dict[str, Any],
    action: str,
    *,
    require_send_confirmation: bool = False,
) -> None:
    if not _env_bool(MUTATION_ENV, False):
        raise PermissionError(f'{action} is disabled; set {MUTATION_ENV}=true for mutating MCP tools')
    configured_secret = os.getenv(SHARED_SECRET_ENV)
    if configured_secret:
        provided = str(payload.get('api_key') or payload.get('shared_secret') or '')
        if not hmac.compare_digest(provided, configured_secret):
            raise PermissionError(f'{action} rejected: invalid MCP shared secret')
    if require_send_confirmation and str(payload.get('confirmation') or '') != CONFIRM_SEND_PHRASE:
        raise PermissionError(f'{action} requires confirmation={CONFIRM_SEND_PHRASE}')


def _send_message(message: str, *, send_fn: ToolSender | None, channel: bool) -> bool:
    if send_fn is not None:
        return bool(send_fn(message))
    from app.utils.scheduler import _send_telegram_long

    return bool(_send_telegram_long(message, channel=channel))


def _summarize_detection_result(result: dict[str, Any]) -> dict[str, Any]:
    run = result.get('run') or {}
    events = result.get('events') or []
    return {
        'ok': bool(result.get('ok', True)),
        'status': result.get('status'),
        'dry_run': bool(result.get('dry_run')),
        'run_id': run.get('id'),
        'candidate_count': run.get('candidate_count'),
        'new_event_count': len(events),
        'telegram_sent': bool(result.get('telegram_sent')),
        'state_committed': bool(result.get('state_committed')),
        'alert_blocked': bool(result.get('alert_blocked')),
        'blocked_reason': result.get('blocked_reason'),
        'message_chars': len(result.get('message') or ''),
        'events': _event_summaries(events),
    }


def _summarize_workflow_result(result: dict[str, Any]) -> dict[str, Any]:
    top3 = [item for item in (result.get('top3') or []) if isinstance(item, dict)]
    return {
        'ok': bool(result.get('ok', result.get('status') not in {'failed', 'telegram_send_failed'})),
        'status': result.get('status'),
        'dry_run': bool(result.get('dry_run')),
        'workflow_id': result.get('id'),
        'scanner_run_id': result.get('scanner_run_id'),
        'candidate_count': result.get('candidate_count') or result.get('event_count'),
        'event_count': result.get('event_count'),
        'analysis_count': len(result.get('analysis_runs') or []),
        'top_count': len(top3),
        'top_symbols': [item.get('symbol') for item in top3],
        'top_names': [item.get('target') for item in top3],
        'telegram_sent': bool(result.get('telegram_sent')),
        'telegram_skipped_reason': result.get('telegram_skipped_reason'),
        'event_state_committed': bool(result.get('event_state_committed')),
        'outcome_status': result.get('outcome_status'),
        'learning_feedback': result.get('learning_feedback'),
    }


def _event_summaries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for event in events[:MAX_EVENTS]:
        candidate = event.get('candidate') if isinstance(event.get('candidate'), dict) else {}
        summaries.append({
            'key': event.get('key') or event.get('event_key'),
            'symbol': candidate.get('symbol'),
            'name': candidate.get('display_name') or candidate.get('name'),
            'market': candidate.get('market'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
            'action': candidate.get('action'),
        })
    return summaries


def _with_links(result: dict[str, Any]) -> dict[str, Any]:
    links: dict[str, str] = {}
    if result.get('run_id'):
        links['scanner_run'] = f"mirofish://scanner/runs/{result['run_id']}"
    if result.get('workflow_id'):
        links['workflow'] = f"mirofish://workflows/{result['workflow_id']}"
    if result.get('top_symbols'):
        links['latest_workflow'] = 'mirofish://workflows/latest'
    if links:
        result['resource_links'] = links
    return result


def _telegram_config_status() -> dict[str, bool]:
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


def _audit(tool: str, payload: dict[str, Any], result: dict[str, Any], *, status: str) -> None:
    AUTONOMOUS_ROOT.mkdir(parents=True, exist_ok=True)
    record = {
        'ts': _now_iso(),
        'tool': tool,
        'status': status,
        'payload': _redact(payload),
        'result': _redact(result),
    }
    with AUDIT_LOG_PATH.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                redacted[key] = '[REDACTED]'
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str) and (value.startswith('sk_') or len(value) > 120 and 'token' in value.lower()):
        return '[REDACTED]'
    return value


def _error_result(exc: Exception) -> dict[str, str]:
    return {'error': f'{type(exc).__name__}: {exc}'}


def _learning_summary(feedback: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(feedback, dict):
        return {'available': False}
    return {
        'available': True,
        'generated_at': feedback.get('generated_at'),
        'workflow_count': feedback.get('workflow_count'),
        'evaluated_count': feedback.get('evaluated_count'),
        'hit_rate_pct': feedback.get('hit_rate_pct'),
        'average_forward_return_pct': feedback.get('average_forward_return_pct'),
        'production_weights_mutated': bool(feedback.get('production_weights_mutated')),
        'recommendation_count': len(feedback.get('recommendations') or []),
    }


def _symbols(value: Any) -> list[str]:
    if value is None or value == '':
        return []
    raw = value if isinstance(value, list) else str(value).split(',')
    symbols = []
    for item in raw:
        symbol = str(item or '').strip().upper()
        if not symbol:
            continue
        if not re.fullmatch(r'[A-Z0-9._-]{1,24}', symbol):
            raise ValueError(f'invalid symbol: {symbol}')
        symbols.append(symbol)
    return sorted(set(symbols))


def _actions(value: Any) -> tuple[str, ...]:
    if value is None or value == '':
        return tuple()
    raw = value if isinstance(value, list) else str(value).split(',')
    actions = []
    for item in raw:
        action = str(item or '').strip().upper()
        if action not in {'BUY_CANDIDATE', 'WATCH'}:
            raise ValueError(f'invalid action: {action}')
        actions.append(action)
    return tuple(dict.fromkeys(actions))


def _mode(value: Any) -> str:
    mode = str(value or 'full').strip().lower()
    if mode not in {'full', 'fast', 'offline'}:
        raise ValueError('mode must be full, fast, or offline')
    return mode


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _env_bool(name: str, default: bool = False) -> bool:
    return _bool(os.getenv(name), default)


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == '':
        number = default
    else:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError('integer value required')
    return max(minimum, min(number, maximum))


def _float(value: Any, default: float) -> float:
    if value is None or value == '':
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError('number value required')


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
