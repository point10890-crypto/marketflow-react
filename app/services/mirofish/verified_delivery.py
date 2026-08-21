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
from datetime import date, datetime, timezone
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


def run_verified_detection(
    payload: dict[str, Any] | None = None,
    *,
    send: bool = False,
    confirmation: str | None = None,
    receipt_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Run a scanner check, validate persisted artifacts, then optionally deliver.

    Preview is the default and omits delivery and receipt writes. Scanner run
    artifacts are intentionally persisted by the scanner itself. A send is
    allowed only with the exact operator confirmation phrase.
    """
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
    canonical_alert, alert_error = _canonicalize_alert(alert, persisted, blocked=blocked)
    if alert_error:
        return _result('invalid_run', run_id=run_id, error_code=alert_error)
    message = canonical_alert['message']
    return _deliver_or_preview(
        run=persisted,
        alert=canonical_alert,
        message=message,
        send=send,
        confirmation=confirmation,
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
    candidates = persisted.get('candidates')
    count = persisted.get('candidate_count')
    if not isinstance(candidates, list) or not isinstance(count, int) or isinstance(count, bool) or count != len(candidates):
        return _invalid('candidate_count_mismatch'), persisted
    for candidate in candidates:
        error = _candidate_error(candidate, generated_date=generated_dt.date())
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
    artifact_error = _evidence_ledger_error(ledger.get('items'), candidates, generated_dt.date())
    if artifact_error:
        return _invalid(artifact_error), persisted
    if _freshness(persisted) in alpha_scanner.ALERT_BLOCKING_FRESHNESS:
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
    if getattr(response, 'status_code', None) != 200 or not isinstance(payload, dict) or payload.get('ok') is not True:
        return {'ok': False, 'status': 'rejected', 'error_code': 'telegram_response_rejected', 'retryable': True}
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
    alert: dict[str, Any],
    message: str,
    send: bool,
    confirmation: str | None,
    receipt_path: str | os.PathLike[str] | None,
    blocked: bool,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Preview or serialize one delivery attempt behind its durable claim."""
    events = [] if blocked else _events(alert)
    symbols = [] if blocked else _event_symbols(events)
    event_keys = [] if blocked else _event_keys(events)
    digest = _message_digest(message)
    base = {
        'run_id': _text(run.get('id')),
        'message_digest': digest,
        'candidate_count': 0 if blocked else _candidate_count(run),
        'event_count': len(events),
        'symbols': symbols,
        'event_keys': event_keys,
        'freshness': _freshness(run),
        'sent': False,
    }
    if error_code:
        base['error_code'] = error_code
    if not send:
        return _result('blocked' if blocked else 'preview', **base)
    if confirmation != CONFIRMATION_PHRASE:
        return _result('confirmation_required', **base)

    path = Path(receipt_path) if receipt_path else DEFAULT_RECEIPT_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with safe_write(str(path), timeout=15):
            ledger = _read_ledger(path)
            if ledger is None:
                return _result('receipt_invalid', run_id=base['run_id'], error_code='receipt_invalid', sent=False)
            recovered = _recover_outstanding_state(ledger, path, alert, base, blocked)
            if recovered is not None:
                return recovered
            existing = _find_delivery(ledger, base['run_id'], digest)
            if existing is not None:
                return _handle_existing_delivery(ledger, path, existing, alert, base, blocked)

            claim = _delivery_entry(
                status='pending',
                run=run,
                message_digest=digest,
                event_count=len(events),
                symbols=symbols,
                event_keys=event_keys,
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
    except Exception:
        return _result('receipt_lock_failed', run_id=base['run_id'], error_code='receipt_lock_failed', sent=False)


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
        return _result('delivery_uncertain', **{**base, 'sent': None, 'message_id': entry.get('message_id')})
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
    alert: dict[str, Any],
    base: dict[str, Any],
    blocked: bool,
) -> dict[str, Any] | None:
    """Recover pending scanner event state before considering any new delivery."""
    if blocked:
        return None
    outstanding = [
        entry for entry in ledger.get('deliveries') or []
        if _text(entry.get('status')) == 'delivered' and entry.get('state_committed') is not True
    ]
    if not outstanding:
        return None
    current_keys = set(base.get('event_keys') or [])
    matching = [entry for entry in outstanding if set(entry.get('event_keys') or []) == current_keys and current_keys]
    if len(matching) != len(outstanding):
        return _result('state_recovery_required', run_id=base['run_id'], error_code='state_recovery_required', sent=False)
    try:
        alpha_scanner.commit_scanner_alert_events(alert)
    except Exception:
        return _result('state_recovery_required', run_id=base['run_id'], error_code='state_recovery_required', sent=False)
    now = _now_iso()
    for entry in matching:
        entry['state_committed'] = True
        entry['state_recovered_at'] = now
        entry['updated_at'] = now
    try:
        _write_ledger(path, ledger)
    except Exception:
        return _result('state_recovery_required', run_id=base['run_id'], error_code='state_recovery_required', sent=False)
    return _result(
        'delivered_recovered',
        **{**base, 'message_id': matching[0].get('message_id'), 'sent': False, 'state_committed': True},
    )


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


def _canonicalize_alert(
    alert: dict[str, Any],
    run: dict[str, Any],
    *,
    blocked: bool,
) -> tuple[dict[str, Any], str | None]:
    """Validate transient event metadata and rebuild one persisted-run alert."""
    raw_blocked = alert.get('alert_blocked')
    if not isinstance(raw_blocked, bool) or raw_blocked != blocked:
        return {}, 'freshness_alert_mismatch'
    raw_events = alert.get('events')
    if not isinstance(raw_events, list):
        return {}, 'invalid_alert_events'
    event_count = alert.get('new_event_count')
    if not isinstance(event_count, int) or isinstance(event_count, bool) or event_count != len(raw_events):
        return {}, 'event_count_mismatch'
    state_path = alert.get('state_path')
    if not isinstance(state_path, str) or not state_path.strip():
        return {}, 'invalid_state_path'
    if blocked and raw_events:
        return {}, 'blocked_alert_has_events'

    candidates = run.get('candidates') if isinstance(run.get('candidates'), list) else []
    candidate_by_symbol: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        symbol = _text(candidate.get('symbol')) if isinstance(candidate, dict) else ''
        if not symbol or symbol in candidate_by_symbol:
            return {}, 'candidate_identity_mismatch'
        candidate_by_symbol[symbol] = candidate

    canonical_events: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            return {}, 'invalid_alert_event'
        raw_candidate = raw_event.get('candidate')
        if not isinstance(raw_candidate, dict):
            return {}, 'event_candidate_mismatch'
        symbol = _text(raw_candidate.get('symbol'))
        candidate = candidate_by_symbol.get(symbol)
        if candidate is None or raw_candidate != candidate:
            return {}, 'event_candidate_mismatch'
        if raw_event.get('run_id') != run.get('id'):
            return {}, 'event_run_id_mismatch'
        if raw_event.get('generated_at') != run.get('generated_at'):
            return {}, 'event_generated_at_mismatch'
        expected_key = _candidate_event_key(candidate)
        if raw_event.get('event_key') != expected_key:
            return {}, 'event_key_mismatch'
        if expected_key in seen_keys:
            return {}, 'duplicate_event_key'
        if (
            candidate.get('action') != 'BUY_CANDIDATE'
            or float(candidate['alpha_score']) < alpha_scanner.DEFAULT_ALERT_MIN_ALPHA
            or float(candidate['risk_score']) > alpha_scanner.DEFAULT_ALERT_MAX_RISK
        ):
            return {}, 'ineligible_alert_event'
        seen_keys.add(expected_key)
        canonical_events.append({
            'event_key': expected_key,
            'run_id': run['id'],
            'generated_at': run['generated_at'],
            'candidate': candidate,
        })

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
        'state_path': state_path,
        'new_event_count': len(canonical_events),
        'alert_blocked': blocked,
        'blocked_reason': blocked_reason,
    }, None)


def _candidate_event_key(candidate: dict[str, Any]) -> str:
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    price_date = _text(price.get('date')) or _text(candidate.get('generated_at'))[:10]
    return f"{_text(candidate.get('symbol'))}:{_text(candidate.get('action'))}:{price_date}"


def _candidate_error(candidate: Any, *, generated_date: date) -> str | None:
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
    price = candidate.get('price')
    if not isinstance(price, dict) or not _finite(price.get('current_price')):
        return 'invalid_candidate_price'
    price_date = _parse_date(price.get('date'))
    if price_date is None:
        return 'invalid_candidate_price_date'
    if price_date > generated_date:
        return 'candidate_price_after_run'
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
        if not _artifact_candidate_core_matches(entry, candidate):
            return 'feature_vectors_candidate_mismatch'
        seen.add(symbol)
    if seen != set(candidate_by_symbol):
        return 'feature_vectors_symbol_mismatch'
    return None


def _evidence_ledger_error(entries: Any, candidates: list[Any], generated_date: date) -> str | None:
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
    seen: set[str] = set()
    for entry in selected:
        symbol = _text(entry.get('symbol'))
        candidate = candidate_by_symbol.get(symbol)
        if (
            entry.get('selection_status') != 'selected'
            or candidate is None
            or symbol in seen
            or not _valid_evidence(entry.get('evidence'))
            or not _artifact_candidate_core_matches(entry, candidate)
            or entry.get('evidence') != candidate.get('evidence')
        ):
            return 'invalid_evidence_ledger_item'
        feature = entry.get('feature_vector')
        if not isinstance(feature, dict) or _feature_vector_error(feature, generated_date):
            return 'invalid_evidence_ledger_item'
        if not _artifact_candidate_core_matches(feature, candidate):
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


def _artifact_candidate_core_matches(entry: dict[str, Any], candidate: dict[str, Any]) -> bool:
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    return (
        _text(entry.get('symbol')) == _text(candidate.get('symbol'))
        and _text(entry.get('name')) == _text(candidate.get('name') or candidate.get('display_name'))
        and _text(entry.get('market')) == _text(candidate.get('market'))
        and _text(entry.get('action')) == _text(candidate.get('action'))
        and entry.get('alpha_score') == candidate.get('alpha_score')
        and entry.get('risk_score') == candidate.get('risk_score')
        and entry.get('ranking_score') == candidate.get('ranking_score')
        and (
            'price_date' not in entry
            or _text(entry.get('price_date')) == _text(price.get('date'))
        )
        and (
            'current_price' not in entry
            or entry.get('current_price') == price.get('current_price')
        )
    )


def _valid_evidence(evidence: Any) -> bool:
    return (
        isinstance(evidence, list)
        and bool(evidence)
        and all(
            isinstance(item, dict)
            and bool(_text(item.get('source')))
            and bool(_text(item.get('field')))
            and _finite(item.get('score'))
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
    return datetime.now(timezone.utc).isoformat()


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
