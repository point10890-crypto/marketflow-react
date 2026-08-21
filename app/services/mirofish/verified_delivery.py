"""Guarded one-shot delivery for verified scanner alerts.

This module deliberately owns no scheduler state beyond a minimal receipt.  It
never returns Telegram credentials and only commits scanner alert events after a
personal Telegram delivery has a durable receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from app.services.mirofish import alpha_scanner
from app.utils.atomic_json import write_json_atomic
from app.utils.file_lock import safe_write


CONFIRMATION_PHRASE = 'SEND_VERIFIED_ALPHA_TELEGRAM'
RECEIPT_SCHEMA_VERSION = 2
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RECEIPT_PATH = REPO_ROOT / 'data' / 'admin_mirofish' / 'verified_delivery_receipt.json'
DEFAULT_ALERT_STATE_PATH = REPO_ROOT / 'data' / 'admin_mirofish' / 'alpha_scanner_alert_state.json'
MAX_RUN_AGE = timedelta(minutes=30)
MAX_FUTURE_SKEW = timedelta(seconds=60)


def run_verified_detection(
    payload: dict[str, Any] | None = None,
    *,
    send: bool = False,
    confirmation: str | None = None,
    run_id: str | None = None,
    message_digest: str | None = None,
    receipt_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Preview a new scan or deliver one exact previously-previewed run.

    Preview persists scanner artifacts but performs no delivery/receipt write.
    A send never starts a scan: it re-reads the caller-selected persisted run
    and requires both the preview digest and the exact confirmation phrase.
    """
    if send:
        clean_run_id = _text(run_id)
        clean_digest = _text(message_digest)
        if confirmation != CONFIRMATION_PHRASE:
            return _result('confirmation_required', run_id=clean_run_id or None, sent=False)
        if not clean_run_id or re.fullmatch(r'[0-9a-f]{64}', clean_digest) is None:
            return _result(
                'preview_binding_required',
                run_id=clean_run_id or None,
                error_code='preview_binding_required',
                sent=False,
            )
        validation, persisted = _validate_scanner_run_canonical(clean_run_id)
        blocked = validation.get('error_code') == 'blocked_freshness'
        if not validation.get('ok') and not blocked:
            return _result('invalid_run', run_id=clean_run_id, error_code=validation.get('error_code'), sent=False)
        if not isinstance(persisted, dict):
            return _result('invalid_run', run_id=clean_run_id, error_code='run_not_found', sent=False)
        return _deliver_or_preview(
            run=persisted,
            send=True,
            confirmation=confirmation,
            expected_message_digest=clean_digest,
            receipt_path=receipt_path,
            blocked=blocked,
            error_code='blocked_freshness' if blocked else None,
        )

    scan_payload = dict(payload or {})
    scan_payload['deepseek_rerank'] = False
    try:
        alert = alpha_scanner.run_scanner_alert_check(
            scan_payload,
            commit_state=False,
            block_on_stale=True,
        )
    except Exception:
        return _result('scanner_failed')

    run = alert.get('run') if isinstance(alert, dict) else None
    if not isinstance(run, dict):
        return _result('invalid_run', error_code='missing_scanner_run')
    run_id = _text(run.get('id'))
    if not run_id:
        return _result('invalid_run', error_code='missing_run_id')

    validation, persisted = _validate_scanner_run_canonical(run_id, expected_run=run)
    blocked = validation.get('error_code') == 'blocked_freshness'
    if not validation.get('ok') and not blocked:
        return _result('invalid_run', run_id=run_id, error_code=validation.get('error_code'))
    if not isinstance(persisted, dict):
        return _result('invalid_run', run_id=run_id, error_code='run_not_found')
    return _deliver_or_preview(
        run=persisted,
        send=False,
        confirmation=None,
        expected_message_digest=None,
        receipt_path=receipt_path,
        blocked=blocked,
        error_code='blocked_freshness' if blocked else None,
    )


def validate_scanner_run(
    run_id: str | dict[str, Any],
    *,
    expected_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-read and validate a completed scanner run and its proof artifacts."""
    if isinstance(run_id, dict):
        expected_run = run_id
        run_id = _text(run_id.get('id'))
    validation, _ = _validate_scanner_run_canonical(run_id, expected_run=expected_run)
    return validation


def _validate_scanner_run_canonical(
    run_id: str,
    *,
    expected_run: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return validation metadata plus the one persisted run used downstream."""
    clean_id = _text(run_id)
    if not clean_id:
        return _invalid('missing_run_id'), None
    try:
        persisted = alpha_scanner.read_scanner_run(clean_id)
    except Exception:
        return _invalid('run_read_failed'), None
    if not isinstance(persisted, dict):
        return _invalid('run_not_found'), None
    if _text(persisted.get('id')) != clean_id:
        return _invalid('run_identity_mismatch'), persisted
    if persisted.get('status') != 'completed':
        return _invalid('run_not_completed'), persisted
    if expected_run is not None and expected_run != persisted:
        return _invalid('run_content_mismatch'), persisted
    generated_at = _text(persisted.get('generated_at'))
    if not generated_at:
        return _invalid('missing_generated_at'), persisted
    generated_dt = _parse_timestamp(generated_at)
    if generated_dt is None:
        return _invalid('invalid_generated_at'), persisted
    now = _utc_now()
    if generated_dt > now + MAX_FUTURE_SKEW:
        return _invalid('run_generated_in_future'), persisted
    if now - generated_dt > MAX_RUN_AGE:
        return _invalid('run_expired'), persisted

    source_error, source_blocked, strong_sources = _source_files_status(persisted, generated_dt)
    if source_error:
        return _invalid(source_error), persisted
    candidates = persisted.get('candidates')
    count = persisted.get('candidate_count')
    if not isinstance(candidates, list) or not isinstance(count, int) or isinstance(count, bool) or count != len(candidates):
        return _invalid('candidate_count_mismatch'), persisted
    candidate_blocked = False
    for candidate in candidates:
        error = _candidate_error(
            candidate,
            generated_at=generated_dt,
            strong_sources=strong_sources,
        )
        if error == 'blocked_freshness':
            candidate_blocked = True
            continue
        if error:
            return _invalid(error), persisted

    try:
        features = alpha_scanner.read_scanner_run_artifact(clean_id, 'feature_vectors.json')
        ledger = alpha_scanner.read_scanner_run_artifact(clean_id, 'evidence_ledger.json')
    except Exception:
        return _invalid('artifact_read_failed'), persisted
    artifact_error = _artifact_error(features, clean_id, generated_at, 'feature_vectors', count)
    if artifact_error:
        return _invalid(artifact_error), persisted
    artifact_error = _artifact_error(ledger, clean_id, generated_at, 'evidence_ledger', count)
    if artifact_error:
        return _invalid(artifact_error), persisted
    artifact_error = _feature_vectors_error(features.get('features'), candidates, generated_dt.date())
    if artifact_error:
        return _invalid(artifact_error), persisted
    artifact_error = _evidence_ledger_error(
        ledger.get('items'),
        candidates,
        generated_dt.date(),
        features.get('features'),
    )
    if artifact_error:
        return _invalid(artifact_error), persisted
    if source_blocked or candidate_blocked:
        return _invalid('blocked_freshness'), persisted
    return ({
        'ok': True,
        'run_id': clean_id,
        'generated_at': generated_at,
        'candidate_count': count,
        'freshness': _freshness(persisted),
    }, persisted)


def post_private_telegram(
    message: str,
    *,
    request_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Deliver one HTML message with the personal bot only and verify Telegram's ID."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    configured_chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not configured_chat_id:
        return {'ok': False, 'status': 'not_configured', 'error_code': 'personal_telegram_not_configured', 'retryable': True}
    try:
        chat_id = int(configured_chat_id.strip())
    except (TypeError, ValueError):
        chat_id = 0
    if chat_id <= 0:
        return {'ok': False, 'status': 'not_configured', 'error_code': 'personal_telegram_not_configured', 'retryable': True}
    post = request_post or requests.post
    try:
        response = post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={
                'chat_id': chat_id,
                'text': str(message),
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            timeout=15,
        )
        payload = response.json()
    except Exception:
        return {'ok': False, 'status': 'request_failed', 'error_code': 'telegram_request_failed'}
    telegram_result = payload.get('result') if isinstance(payload, dict) else None
    message_id = telegram_result.get('message_id') if isinstance(telegram_result, dict) else None
    status_code = getattr(response, 'status_code', None)
    if status_code != 200 or not isinstance(payload, dict) or payload.get('ok') is not True:
        result = {'ok': False, 'status': 'rejected', 'error_code': 'telegram_response_rejected'}
        if (
            isinstance(status_code, int)
            and 400 <= status_code < 500
            and isinstance(payload, dict)
            and payload.get('ok') is False
            and bool(_text(payload.get('description')))
        ):
            result['retryable'] = True
        return result
    if not _positive_int(message_id):
        return {'ok': False, 'status': 'rejected', 'error_code': 'invalid_message_id'}
    response_chat = telegram_result.get('chat') if isinstance(telegram_result, dict) else None
    response_chat_id = response_chat.get('id') if isinstance(response_chat, dict) else None
    if (
        not isinstance(response_chat, dict)
        or not _positive_int(response_chat_id)
        or response_chat_id != chat_id
        or response_chat.get('type') != 'private'
    ):
        return {'ok': False, 'status': 'rejected', 'error_code': 'private_chat_verification_failed'}
    return {'ok': True, 'status': 'delivered', 'message_id': message_id}


def _deliver_or_preview(
    *,
    run: dict[str, Any],
    send: bool,
    confirmation: str | None,
    expected_message_digest: str | None,
    receipt_path: str | os.PathLike[str] | None,
    blocked: bool,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Preview or serialize one delivery attempt behind its durable claim."""
    if not send:
        try:
            with alpha_scanner.scanner_alert_delivery_guard(str(DEFAULT_ALERT_STATE_PATH), timeout=15) as locked_state_path:
                state = _read_canonical_alert_state(locked_state_path)
                if state is None:
                    return _result('invalid_run', run_id=_text(run.get('id')), error_code='alert_state_invalid', sent=False)
                alert, alert_error = _canonical_alert_from_state(
                    run,
                    state,
                    blocked=blocked,
                    state_path=locked_state_path,
                )
                if alert_error:
                    return _result('invalid_run', run_id=_text(run.get('id')), error_code=alert_error, sent=False)
                message = alert['message']
                base = _delivery_base(run, alert, message, blocked=blocked, error_code=error_code)
                return _result('blocked' if blocked else 'preview', **base)
        except Exception:
            return _result('invalid_run', run_id=_text(run.get('id')), error_code='alert_state_lock_failed', sent=False)
    if confirmation != CONFIRMATION_PHRASE:
        return _result('confirmation_required', run_id=_text(run.get('id')), sent=False)

    path = Path(receipt_path) if receipt_path else DEFAULT_RECEIPT_PATH
    try:
        with alpha_scanner.scanner_alert_delivery_guard(str(DEFAULT_ALERT_STATE_PATH), timeout=15) as locked_state_path:
            if not _same_path(path, DEFAULT_RECEIPT_PATH):
                return _result(
                    'receipt_path_untrusted',
                    error_code='receipt_path_untrusted',
                    sent=False,
                )
            # Never atomically replace through a caller alias: replacing a
            # symlink path can split the receipt into a second namespace.
            path = Path(DEFAULT_RECEIPT_PATH)
            locked_validation, locked_run = _validate_scanner_run_canonical(
                _text(run.get('id')),
                expected_run=run,
            )
            locked_blocked = locked_validation.get('error_code') == 'blocked_freshness'
            if not locked_validation.get('ok') and not locked_blocked:
                return _result(
                    'invalid_run',
                    run_id=_text(run.get('id')),
                    error_code=locked_validation.get('error_code'),
                    sent=False,
                )
            if not isinstance(locked_run, dict):
                return _result(
                    'invalid_run',
                    run_id=_text(run.get('id')),
                    error_code='run_not_found',
                    sent=False,
                )
            return _deliver_with_receipt_lock(
                path=path,
                run=locked_run,
                expected_message_digest=_text(expected_message_digest),
                blocked=locked_blocked,
                error_code='blocked_freshness' if locked_blocked else error_code,
                canonical_state_path=locked_state_path,
            )
    except Exception:
        return _result('receipt_lock_failed', run_id=_text(run.get('id')), error_code='receipt_lock_failed', sent=False)


def _deliver_with_receipt_lock(
    *,
    path: Path,
    run: dict[str, Any],
    expected_message_digest: str,
    blocked: bool,
    error_code: str | None,
    canonical_state_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Handle the durable receipt while the canonical alert guard is held."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with safe_write(str(path), timeout=15):
        ledger = _read_ledger(path)
        if ledger is None:
            return _result('receipt_invalid', run_id=_text(run.get('id')), error_code='receipt_invalid', sent=False)
        state = _read_canonical_alert_state(canonical_state_path)
        if state is None:
            return _result('receipt_invalid', run_id=_text(run.get('id')), error_code='alert_state_invalid', sent=False)
        recovered = _recover_outstanding_state(ledger, path, state)
        if recovered is not None:
            return recovered
        existing = _find_delivery(ledger, _text(run.get('id')), expected_message_digest)
        if existing is not None and _text(existing.get('status')) in {'pending', 'uncertain'}:
            return _blocking_delivery_result(existing)
        if existing is not None and (
            _text(existing.get('status')) != 'delivered'
            or existing.get('state_committed') is True
            or blocked
        ):
            return _result(
                'duplicate_refused',
                run_id=_text(run.get('id')),
                message_digest=expected_message_digest,
                message_id=existing.get('message_id'),
                sent=False,
                state_committed=bool(existing.get('state_committed')),
            )
        blocking = next(
            (
                item for item in ledger.get('deliveries') or []
                if _text(item.get('status')) in {'pending', 'uncertain'}
            ),
            None,
        )
        if blocking is not None:
            return _blocking_delivery_result(blocking)

        alert, alert_error = _canonical_alert_from_state(
            run,
            state,
            blocked=blocked,
            state_path=canonical_state_path,
        )
        if alert_error:
            return _result('invalid_run', run_id=_text(run.get('id')), error_code=alert_error, sent=False)
        message = alert['message']
        digest = _message_digest(message)
        base = _delivery_base(run, alert, message, blocked=blocked, error_code=error_code)
        if digest != expected_message_digest:
            return _result(
                'preview_mismatch',
                run_id=_text(run.get('id')),
                error_code='preview_mismatch',
                sent=False,
            )
        if existing is not None:
            return _handle_existing_delivery(ledger, path, existing, alert, base, blocked)
        outstanding = [
            item for item in ledger.get('deliveries') or []
            if _text(item.get('status')) == 'delivered' and item.get('state_committed') is not True
        ]
        if outstanding:
            return _state_recovery_required_result(outstanding)
        current_keys = set(base.get('event_keys') or [])
        if current_keys and any(
            _text(item.get('status')) == 'delivered'
            and bool(current_keys.intersection(set(item.get('event_keys') or [])))
            for item in ledger.get('deliveries') or []
        ):
            return _result('duplicate_refused', **{**base, 'sent': False})

        claim = _delivery_entry(
            status='pending',
            run=run,
            message_digest=digest,
            event_count=base['event_count'],
            symbols=base['symbols'],
            event_keys=base['event_keys'],
            blocked=blocked,
        )
        ledger['deliveries'].append(claim)
        try:
            _write_ledger(path, ledger)
        except Exception:
            return _result(
                'receipt_claim_failed',
                run_id=base['run_id'],
                error_code='receipt_claim_write_failed',
                sent=False,
            )

        delivery = post_private_telegram(message)
        if not delivery.get('ok'):
            if delivery.get('retryable') is True:
                claim.update({'status': 'failed', 'retryable': True, 'updated_at': _now_iso()})
                try:
                    _write_ledger(path, ledger)
                except Exception:
                    return _result('delivery_uncertain', **{**base, 'sent': None, 'error_code': 'receipt_final_write_failed'})
                return _result('telegram_not_delivered', **{**base, 'sent': False, 'error_code': delivery.get('error_code')})
            claim['status'] = 'uncertain'
            claim['updated_at'] = _now_iso()
            _best_effort_write_ledger(path, ledger)
            return _result('delivery_uncertain', **{**base, 'sent': None, 'error_code': delivery.get('error_code')})
        message_id = delivery.get('message_id')
        if not _positive_int(message_id):
            claim['status'] = 'uncertain'
            claim['updated_at'] = _now_iso()
            _best_effort_write_ledger(path, ledger)
            return _result('delivery_uncertain', **{**base, 'sent': None, 'error_code': 'invalid_message_id'})

        claim.update({
            'status': 'blocked' if blocked else 'delivered',
            'delivered': True,
            'message_id': message_id,
            'state_committed': False,
            'updated_at': _now_iso(),
        })
        try:
            _write_ledger(path, ledger)
        except Exception:
            return _result('delivery_uncertain', **{**base, 'sent': None, 'error_code': 'receipt_final_write_failed'})
        if blocked:
            return _result('blocked_delivered', **{**base, 'message_id': message_id, 'sent': True, 'state_committed': False})
        return _commit_after_delivery(ledger, path, claim, alert, base)


def _handle_existing_delivery(
    ledger: dict[str, Any],
    path: Path,
    entry: dict[str, Any],
    alert: dict[str, Any],
    base: dict[str, Any],
    blocked: bool,
) -> dict[str, Any]:
    status = _text(entry.get('status'))
    if status in {'pending', 'uncertain'}:
        return _blocking_delivery_result(entry)
    if status == 'delivered' and not entry.get('state_committed') and not blocked:
        recovered = _commit_after_delivery(ledger, path, entry, alert, base)
        if recovered.get('status') == 'delivered':
            recovered['status'] = 'delivered_recovered'
        return recovered
    return _result(
        'duplicate_refused',
        **{**base, 'message_id': entry.get('message_id'), 'sent': False, 'state_committed': bool(entry.get('state_committed'))},
    )


def _recover_outstanding_state(
    ledger: dict[str, Any],
    path: Path,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Repair a ledger write lost after canonical scanner state was committed."""
    outstanding = [
        entry for entry in ledger.get('deliveries') or []
        if _text(entry.get('status')) == 'delivered' and entry.get('state_committed') is not True
    ]
    if not outstanding:
        return None
    matching = [entry for entry in outstanding if _state_confirms_delivery(state, entry)]
    if not matching:
        return None
    now = _now_iso()
    for entry in matching:
        entry['state_committed'] = True
        entry['state_recovered_at'] = now
        entry['updated_at'] = now
    try:
        _write_ledger(path, ledger)
    except Exception:
        return _state_recovery_required_result(outstanding)
    if len(matching) != len(outstanding):
        return _state_recovery_required_result(outstanding)
    fields: dict[str, Any] = {
        'sent': False,
        'state_committed': True,
        'recovered_count': len(matching),
    }
    if len(matching) == 1:
        fields['run_id'] = _text(matching[0].get('run_id'))
        fields['message_id'] = matching[0].get('message_id')
    return _result('delivered_recovered', **fields)


def _blocking_delivery_result(entry: dict[str, Any]) -> dict[str, Any]:
    """Identify the durable blocking claim without echoing a requested preview."""
    fields: dict[str, Any] = {
        'sent': None,
        'blocking_status': _text(entry.get('status')) or 'unknown',
    }
    blocking_run_id = _text(entry.get('run_id'))
    if blocking_run_id:
        fields['blocking_run_id'] = blocking_run_id
    return _result('delivery_uncertain', **fields)


def _state_recovery_required_result(entries: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        'error_code': 'state_recovery_required',
        'sent': False,
    }
    run_ids = {_text(entry.get('run_id')) for entry in entries if _text(entry.get('run_id'))}
    if len(run_ids) == 1:
        fields['blocking_run_id'] = next(iter(run_ids))
    return _result('state_recovery_required', **fields)


def _commit_after_delivery(
    ledger: dict[str, Any],
    path: Path,
    entry: dict[str, Any],
    alert: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    try:
        alpha_scanner.commit_scanner_alert_events(alert)
    except Exception:
        entry['state_committed'] = False
        entry['updated_at'] = _now_iso()
        _best_effort_write_ledger(path, ledger)
        return _result('state_commit_failed', **{**base, 'message_id': entry.get('message_id'), 'sent': True, 'state_committed': False})
    entry['state_committed'] = True
    entry['updated_at'] = _now_iso()
    try:
        _write_ledger(path, ledger)
    except Exception:
        return _result('state_commit_failed', **{**base, 'message_id': entry.get('message_id'), 'sent': True, 'state_committed': False})
    return _result('delivered', **{**base, 'message_id': entry.get('message_id'), 'sent': True, 'state_committed': True})


def _canonical_alert_from_state(
    run: dict[str, Any],
    state: dict[str, Any],
    *,
    blocked: bool,
    state_path: str | os.PathLike[str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Build events/message only from a persisted run and trusted state."""
    sent_events = state.get('sent_events') if isinstance(state.get('sent_events'), dict) else None
    if sent_events is None:
        return {}, 'alert_state_invalid'
    candidates = run.get('candidates') if isinstance(run.get('candidates'), list) else []
    canonical_events: list[dict[str, Any]] = []
    if not blocked:
        seen_keys: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                return {}, 'invalid_candidate'
            if (
                candidate.get('action') != 'BUY_CANDIDATE'
                or float(candidate['alpha_score']) < alpha_scanner.DEFAULT_ALERT_MIN_ALPHA
                or float(candidate['risk_score']) > alpha_scanner.DEFAULT_ALERT_MAX_RISK
            ):
                continue
            expected_key = _candidate_event_key(candidate)
            if expected_key in sent_events or expected_key in seen_keys:
                continue
            seen_keys.add(expected_key)
            canonical_events.append({
                'event_key': expected_key,
                'run_id': run['id'],
                'generated_at': run['generated_at'],
                'candidate': candidate,
            })
            if len(canonical_events) >= alpha_scanner.DEFAULT_ALERT_MAX_EVENTS:
                break

    blocked_reason = 'blocked_freshness' if blocked else None
    try:
        message = alpha_scanner.build_scanner_alert_message(
            run,
            canonical_events,
            min_alpha=alpha_scanner.DEFAULT_ALERT_MIN_ALPHA,
            max_risk=alpha_scanner.DEFAULT_ALERT_MAX_RISK,
            blocked_reason=blocked_reason,
        )
    except Exception:
        return {}, 'message_build_failed'
    if not _text(message):
        return {}, 'message_build_failed'
    return ({
        'run': run,
        'events': canonical_events,
        'message': message,
        'state_path': str(state_path or DEFAULT_ALERT_STATE_PATH),
        'new_event_count': len(canonical_events),
        'alert_blocked': blocked,
        'blocked_reason': blocked_reason,
    }, None)


def _delivery_base(
    run: dict[str, Any],
    alert: dict[str, Any],
    message: str,
    *,
    blocked: bool,
    error_code: str | None,
) -> dict[str, Any]:
    events = [] if blocked else _events(alert)
    base = {
        'run_id': _text(run.get('id')),
        'message_digest': _message_digest(message),
        'candidate_count': 0 if blocked else _candidate_count(run),
        'event_count': len(events),
        'symbols': [] if blocked else _event_symbols(events),
        'event_keys': [] if blocked else _event_keys(events),
        'freshness': _freshness(run),
        'sent': False,
    }
    if error_code:
        base['error_code'] = error_code
    return base


def _read_canonical_alert_state(
    state_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read only the repository-owned state and fail closed on corruption."""
    return alpha_scanner._read_alert_state_strict(str(state_path or DEFAULT_ALERT_STATE_PATH))


def _state_confirms_delivery(state: dict[str, Any], entry: dict[str, Any]) -> bool:
    sent_events = state.get('sent_events') if isinstance(state.get('sent_events'), dict) else {}
    keys = entry.get('event_keys') if isinstance(entry.get('event_keys'), list) else []
    run_id = _text(entry.get('run_id'))
    if keys:
        return all(
            isinstance(sent_events.get(key), dict)
            and _text(sent_events[key].get('run_id')) == run_id
            for key in keys
        )
    event_count = entry.get('event_count')
    last_new_event_count = state.get('last_new_event_count')
    committed_runs = state.get('committed_runs') if isinstance(state.get('committed_runs'), dict) else {}
    marker = committed_runs.get(run_id) if isinstance(committed_runs.get(run_id), dict) else None
    marker_count = marker.get('event_count') if isinstance(marker, dict) else None
    marker_confirms = (
        isinstance(marker_count, int)
        and not isinstance(marker_count, bool)
        and marker_count == 0
        and bool(_text(marker.get('committed_at')))
    )
    return (
        isinstance(event_count, int)
        and not isinstance(event_count, bool)
        and event_count == 0
        and (
            marker_confirms
            or (
                _text(state.get('last_run_id')) == run_id
                and isinstance(last_new_event_count, int)
                and not isinstance(last_new_event_count, bool)
                and last_new_event_count == 0
            )
        )
    )


def _same_path(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> bool:
    def canonical(value: str | os.PathLike[str]) -> str:
        expanded = os.path.expanduser(os.fspath(value))
        return os.path.normcase(os.path.realpath(os.path.abspath(expanded)))

    return canonical(left) == canonical(right)


def _candidate_event_key(candidate: dict[str, Any]) -> str:
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    price_date = _text(price.get('date')) or _text(candidate.get('generated_at'))[:10]
    return f"{_text(candidate.get('symbol'))}:{_text(candidate.get('action'))}:{price_date}"


def _source_files_status(
    run: dict[str, Any],
    generated_at: datetime,
) -> tuple[str | None, bool, set[str]]:
    items = run.get('source_files')
    if not isinstance(items, list):
        return 'missing_source_files', False, set()
    expected = {
        name: policy
        for name, policy in alpha_scanner.SOURCE_FILE_POLICIES.items()
        if policy.get('alert_required')
    }
    alert_items = [item for item in items if isinstance(item, dict) and item.get('alert_required') is True]
    names = [_text(item.get('file')).removeprefix('data/') for item in alert_items]
    if len(names) != len(set(names)) or set(names) != set(expected):
        return 'alert_source_files_mismatch', False, set()

    blocked = False
    strong_sources: set[str] = set()
    by_name = dict(zip(names, alert_items, strict=True))
    for name, policy in expected.items():
        item = by_name[name]
        if (
            not isinstance(item.get('exists'), bool)
            or _text(item.get('role')) != _text(policy.get('role'))
            or item.get('required') is not bool(policy.get('required'))
            or item.get('alert_required') is not True
            or item.get('max_age_days') != policy.get('max_age_days')
        ):
            return 'alert_source_policy_mismatch', False, set()
        is_analytical_source = _text(policy.get('role')) in {'price_history', 'leading_screener'}
        if item.get('exists') is not True:
            blocked = True
            if is_analytical_source:
                strong_sources.add(name)
            continue
        observed_at = _parse_source_timestamp(item.get('generated_at') or item.get('modified_at'))
        if observed_at is None:
            return 'invalid_source_observation', False, set()
        if observed_at > generated_at:
            return 'source_observation_after_run', False, set()
        max_age = timedelta(days=int(policy['max_age_days']))
        if generated_at - observed_at > max_age or _text(item.get('freshness')).lower() != 'fresh':
            blocked = True
        if is_analytical_source:
            strong_sources.add(name)
    return None, blocked, strong_sources


def _candidate_error(
    candidate: Any,
    *,
    generated_at: datetime,
    strong_sources: set[str],
) -> str | None:
    if not isinstance(candidate, dict):
        return 'invalid_candidate'
    if not _text(candidate.get('symbol')) or not (_text(candidate.get('display_name')) or _text(candidate.get('name'))):
        return 'invalid_candidate_identity'
    if not _text(candidate.get('market')):
        return 'invalid_candidate_market'
    if (
        not _finite(candidate.get('alpha_score'))
        or not _finite(candidate.get('risk_score'))
        or not _finite(candidate.get('ranking_score'))
    ):
        return 'invalid_candidate_score'
    if not _valid_evidence(candidate.get('evidence')):
        return 'invalid_candidate_evidence'
    candidate_generated_at = _parse_timestamp(candidate.get('generated_at'))
    if candidate_generated_at is None or candidate_generated_at != generated_at:
        return 'candidate_generated_at_mismatch'
    replay = candidate.get('replay_context')
    if not isinstance(replay, dict):
        return 'invalid_replay_context'
    if replay.get('lookahead_safe') is not True:
        return 'candidate_not_lookahead_safe'
    replay_generated_at = _parse_timestamp(replay.get('generated_at'))
    if replay_generated_at is None or replay_generated_at != generated_at:
        return 'replay_generated_at_mismatch'
    data_sources = replay.get('data_sources')
    if (
        not isinstance(data_sources, list)
        or not data_sources
        or not all(isinstance(source, str) and source.strip() for source in data_sources)
    ):
        return 'invalid_candidate_data_sources'
    price = candidate.get('price')
    if not isinstance(price, dict) or not _finite(price.get('current_price')):
        return 'invalid_candidate_price'
    price_date = _parse_date(price.get('date'))
    if price_date is None:
        return 'invalid_candidate_price_date'
    if price_date > generated_at.date():
        return 'candidate_price_after_run'
    if _text(replay.get('price_date')) != _text(price.get('date')):
        return 'replay_price_date_mismatch'
    price_max_age = int(alpha_scanner.SOURCE_FILE_POLICIES['daily_prices.csv']['max_age_days'])
    if (generated_at.date() - price_date).days > price_max_age:
        return 'blocked_freshness'
    evidence = candidate['evidence']
    strong_evidence = [
        item for item in evidence
        if _text(item.get('source')) in strong_sources
        and _text(item.get('source')) in set(data_sources)
        and float(item.get('confidence')) >= 0.5
    ]
    if not strong_evidence:
        return 'missing_strong_evidence'
    profile = candidate.get('analysis_profile')
    quality = profile.get('evidence_quality') if isinstance(profile, dict) else None
    if not isinstance(quality, dict) or _text(quality.get('grade')).lower() not in {'moderate', 'strong'}:
        return 'weak_evidence_quality'
    return None


def _artifact_error(
    artifact: Any,
    run_id: str,
    generated_at: str,
    label: str,
    candidate_count: int,
) -> str | None:
    if not isinstance(artifact, dict):
        return f'{label}_missing'
    if _text(artifact.get('run_id')) != run_id:
        return f'{label}_identity_mismatch'
    if _text(artifact.get('generated_at')) != generated_at:
        return f'{label}_generated_at_mismatch'
    if artifact.get('lookahead_safe') is not True:
        return f'{label}_not_lookahead_safe'
    entries_key = 'features' if label == 'feature_vectors' else 'items'
    entries = artifact.get(entries_key)
    count_key = 'feature_count' if label == 'feature_vectors' else 'candidate_count'
    if not isinstance(entries, list) or artifact.get(count_key) != candidate_count:
        return f'{label}_count_mismatch'
    if label == 'feature_vectors' and len(entries) != candidate_count:
        return f'{label}_count_mismatch'
    if label == 'evidence_ledger':
        selected = [item for item in entries if not isinstance(item, dict) or item.get('selection_status') != 'rejected']
        if len(selected) != candidate_count:
            return f'{label}_count_mismatch'
        rejected_count = artifact.get('rejected_candidate_count')
        if rejected_count is not None and (not isinstance(rejected_count, int) or len(entries) != candidate_count + rejected_count):
            return f'{label}_count_mismatch'
    return None


def _feature_vectors_error(entries: Any, candidates: list[Any], generated_date: date) -> str | None:
    if not isinstance(entries, list):
        return 'feature_vectors_count_mismatch'
    candidate_by_symbol = {
        _text(candidate.get('symbol')): candidate
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    if len(candidate_by_symbol) != len(candidates):
        return 'feature_vectors_symbol_mismatch'
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return 'invalid_feature_vector'
        symbol = _text(entry.get('symbol'))
        candidate = candidate_by_symbol.get(symbol)
        if candidate is None or symbol in seen:
            return 'feature_vectors_symbol_mismatch'
        error = _feature_vector_error(entry, generated_date)
        if error:
            return error
        if entry != alpha_scanner._feature_vector(candidate):
            return 'feature_vectors_candidate_mismatch'
        seen.add(symbol)
    if seen != set(candidate_by_symbol):
        return 'feature_vectors_symbol_mismatch'
    return None


def _evidence_ledger_error(
    entries: Any,
    candidates: list[Any],
    generated_date: date,
    feature_entries: Any,
) -> str | None:
    if not isinstance(entries, list):
        return 'evidence_ledger_count_mismatch'
    selected = [entry for entry in entries if isinstance(entry, dict) and entry.get('selection_status') != 'rejected']
    if len(selected) != len(candidates):
        return 'evidence_ledger_count_mismatch'
    candidate_by_symbol = {
        _text(candidate.get('symbol')): candidate
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    feature_by_symbol = {
        _text(feature.get('symbol')): feature
        for feature in feature_entries or []
        if isinstance(feature, dict)
    }
    seen: set[str] = set()
    for entry in selected:
        symbol = _text(entry.get('symbol'))
        candidate = candidate_by_symbol.get(symbol)
        if candidate is None or symbol in seen:
            return 'invalid_evidence_ledger_item'
        feature = entry.get('feature_vector')
        if not isinstance(feature, dict) or _feature_vector_error(feature, generated_date):
            return 'invalid_evidence_ledger_item'
        if feature != feature_by_symbol.get(symbol):
            return 'evidence_feature_vector_mismatch'
        profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
        expected = {
            'symbol': candidate.get('symbol'),
            'name': candidate.get('name') or candidate.get('display_name'),
            'market': candidate.get('market'),
            'rank': candidate.get('rank'),
            'pool_rank': candidate.get('pool_rank'),
            'selection_status': 'selected',
            'rejection_reasons': [],
            'action': candidate.get('action'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
            'ranking_score': candidate.get('ranking_score'),
            'signal_quality': candidate.get('signal_quality'),
            'strategy_tags': candidate.get('strategy_tags') or [],
            'evidence_quality': candidate.get('evidence_quality') or profile.get('evidence_quality'),
            'confidence_cap': profile.get('confidence_cap') or feature.get('confidence_cap'),
            'freshness': candidate.get('freshness'),
            'data_sources': (candidate.get('replay_context') or {}).get('data_sources') or feature.get('data_sources') or [],
            'evidence': candidate.get('evidence') or [],
            'feature_vector': feature,
        }
        if entry != expected or not _valid_evidence(entry.get('evidence')):
            return 'invalid_evidence_ledger_item'
        seen.add(symbol)
    if seen != set(candidate_by_symbol):
        return 'evidence_ledger_symbol_mismatch'
    return None


def _feature_vector_error(entry: dict[str, Any], generated_date: date) -> str | None:
    if (
        not _text(entry.get('symbol'))
        or not _text(entry.get('name'))
        or not _text(entry.get('market'))
        or not _text(entry.get('action'))
        or entry.get('lookahead_safe') is not True
    ):
        return 'invalid_feature_vector'
    for field in ('alpha_score', 'risk_score', 'ranking_score', 'current_price'):
        if not _finite(entry.get(field)):
            return 'invalid_feature_vector'
    price_date = _parse_date(entry.get('price_date'))
    if price_date is None or price_date > generated_date:
        return 'invalid_feature_vector'
    return None


def _valid_evidence(evidence: Any) -> bool:
    return (
        isinstance(evidence, list)
        and bool(evidence)
        and all(
            isinstance(item, dict)
            and bool(_text(item.get('source')))
            and bool(_text(item.get('field')))
            and _finite(item.get('score'))
            and _finite(item.get('confidence'))
            and 0.0 <= float(item.get('confidence')) <= 1.0
            for item in evidence
        )
    )


def _events(alert: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in (alert.get('events') or []) if isinstance(event, dict)]


def _event_symbols(events: list[dict[str, Any]]) -> list[str]:
    return sorted({_text((event.get('candidate') or {}).get('symbol')) for event in events if _text((event.get('candidate') or {}).get('symbol'))})


def _candidate_count(run: dict[str, Any]) -> int:
    return int(run.get('candidate_count') or 0)


def _freshness(run: dict[str, Any]) -> str:
    freshness = run.get('freshness')
    return _text(freshness.get('status')).lower() if isinstance(freshness, dict) else 'unknown'


def _delivery_entry(
    *,
    status: str,
    run: dict[str, Any],
    message_digest: str,
    event_count: int,
    symbols: list[str],
    event_keys: list[str],
    blocked: bool,
) -> dict[str, Any]:
    now = _now_iso()
    return {
        'claimed_at': now,
        'updated_at': now,
        'run_id': _text(run.get('id')),
        'message_sha256': message_digest,
        'status': status,
        'delivered': False,
        'message_id': None,
        'candidate_count': 0 if blocked else _candidate_count(run),
        'event_count': event_count,
        'symbols': symbols,
        'event_keys': event_keys,
        'freshness': _freshness(run),
        'state_committed': False,
    }


def _read_ledger(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': _now_iso(), 'deliveries': []}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    deliveries = payload.get('deliveries')
    if payload.get('schema_version') == RECEIPT_SCHEMA_VERSION:
        if not isinstance(deliveries, list) or not all(_valid_delivery_entry(item) for item in deliveries):
            return None
        return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': payload.get('updated_at') or _now_iso(), 'deliveries': deliveries}
    # Safely retain a receipt written by the first release as a historical entry.
    if payload.get('schema_version') == 1:
        legacy = dict(payload)
        legacy.setdefault('event_keys', [])
        legacy.setdefault('state_committed', False)
        if _valid_delivery_entry(legacy):
            return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': _now_iso(), 'deliveries': [legacy]}
    return None


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    ledger['schema_version'] = RECEIPT_SCHEMA_VERSION
    ledger['updated_at'] = _now_iso()
    write_json_atomic(str(path), ledger, sort_keys=True)


def _best_effort_write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    try:
        _write_ledger(path, ledger)
    except Exception:
        pass


def _find_delivery(ledger: dict[str, Any], run_id: str, digest: str) -> dict[str, Any] | None:
    for entry in reversed(ledger.get('deliveries') or []):
        if (
            _text(entry.get('run_id')) == run_id
            and _text(entry.get('message_sha256')) == digest
            and _text(entry.get('status')) != 'failed'
        ):
            return entry
    return None


def _event_keys(events: list[dict[str, Any]]) -> list[str]:
    keys = set()
    for event in events:
        supplied = _text(event.get('event_key'))
        if supplied:
            keys.add(supplied)
            continue
        candidate = event.get('candidate') if isinstance(event.get('candidate'), dict) else {}
        symbol = _text(candidate.get('symbol'))
        price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
        price_date = _text(price.get('date')) or _text(candidate.get('generated_at'))[:10]
        if symbol and price_date:
            keys.add(f"{symbol}:{_text(candidate.get('action'))}:{price_date}")
    return sorted(keys)


def _valid_delivery_entry(entry: Any) -> bool:
    """Accept only semantically coherent receipt state; invalid history fails closed."""
    if not isinstance(entry, dict):
        return False
    status = entry.get('status')
    if status not in {'pending', 'uncertain', 'failed', 'delivered', 'blocked'}:
        return False
    run_id = entry.get('run_id')
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(entry.get('message_sha256'), str):
        return False
    if re.fullmatch(r'[0-9a-f]{64}', entry['message_sha256']) is None:
        return False
    if not isinstance(entry.get('delivered'), bool) or not isinstance(entry.get('state_committed'), bool):
        return False
    for field in ('candidate_count', 'event_count'):
        value = entry.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
    for field in ('symbols', 'event_keys'):
        value = entry.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return False
    message_id = entry.get('message_id')
    positive_message_id = _positive_int(message_id)
    if status in {'delivered', 'blocked'}:
        if not entry['delivered'] or not positive_message_id:
            return False
    elif entry['delivered'] or message_id is not None:
        return False
    if status == 'failed' and entry.get('retryable') is not True:
        return False
    if status != 'failed' and 'retryable' in entry and entry['retryable'] is not False:
        return False
    if status == 'blocked' and entry['state_committed']:
        return False
    if entry['state_committed'] and status != 'delivered':
        return False
    return True


def _now_iso() -> str:
    return _utc_now().isoformat()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _message_digest(message: str) -> str:
    return hashlib.sha256(message.encode('utf-8')).hexdigest()


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_source_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=alpha_scanner.KST)
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any) -> date | None:
    text = _text(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _text(value: Any) -> str:
    return str(value or '').strip()


def _invalid(error_code: str) -> dict[str, Any]:
    return {'ok': False, 'error_code': error_code, 'details': {}}


def _result(status: str, **fields: Any) -> dict[str, Any]:
    return {'ok': status in {'preview', 'delivered', 'blocked', 'blocked_delivered', 'delivered_recovered'}, 'status': status, **fields}
