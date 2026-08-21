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
from datetime import datetime, timezone
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

    validation = validate_scanner_run(run_id, expected_run=run)
    stale = bool(alert.get('alert_blocked')) or validation.get('error_code') == 'blocked_freshness'
    if stale:
        return _deliver_or_preview(
            run=run,
            alert=alert,
            message='<b>검출 보류</b>\n스캐너 원천 데이터 freshness 검증이 통과하지 않았습니다.',
            send=send,
            confirmation=confirmation,
            receipt_path=receipt_path,
            blocked=True,
            error_code=validation.get('error_code') or _text(alert.get('blocked_reason')) or 'blocked_freshness',
        )
    if not validation.get('ok'):
        return _result('invalid_run', run_id=run_id, error_code=validation.get('error_code'))

    message = _text(alert.get('message'))
    if not message:
        return _result('invalid_run', run_id=run_id, error_code='missing_alert_message')
    return _deliver_or_preview(
        run=run,
        alert=alert,
        message=message,
        send=send,
        confirmation=confirmation,
        receipt_path=receipt_path,
        blocked=False,
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
    clean_id = _text(run_id)
    if not clean_id:
        return _invalid('missing_run_id')
    try:
        persisted = alpha_scanner.read_scanner_run(clean_id)
    except Exception:
        return _invalid('run_read_failed')
    if not isinstance(persisted, dict):
        return _invalid('run_not_found')
    if _text(persisted.get('id')) != clean_id:
        return _invalid('run_identity_mismatch')
    if persisted.get('status') != 'completed':
        return _invalid('run_not_completed')
    if expected_run is not None:
        if _text(expected_run.get('id')) != _text(persisted.get('id')):
            return _invalid('run_identity_mismatch')
        if _text(expected_run.get('generated_at')) != _text(persisted.get('generated_at')):
            return _invalid('generated_at_mismatch')
        if expected_run.get('candidate_count') != persisted.get('candidate_count'):
            return _invalid('candidate_count_mismatch')
    generated_at = _text(persisted.get('generated_at'))
    if not generated_at:
        return _invalid('missing_generated_at')
    candidates = persisted.get('candidates')
    count = persisted.get('candidate_count')
    if not isinstance(candidates, list) or not isinstance(count, int) or isinstance(count, bool) or count != len(candidates):
        return _invalid('candidate_count_mismatch')
    if _freshness(persisted) in alpha_scanner.ALERT_BLOCKING_FRESHNESS:
        return _invalid('blocked_freshness')
    for candidate in candidates:
        error = _candidate_error(candidate)
        if error:
            return _invalid(error)

    try:
        features = alpha_scanner.read_scanner_run_artifact(clean_id, 'feature_vectors.json')
        ledger = alpha_scanner.read_scanner_run_artifact(clean_id, 'evidence_ledger.json')
    except Exception:
        return _invalid('artifact_read_failed')
    artifact_error = _artifact_error(features, clean_id, 'feature_vectors', count)
    if artifact_error:
        return _invalid(artifact_error)
    artifact_error = _artifact_error(ledger, clean_id, 'evidence_ledger', count)
    if artifact_error:
        return _invalid(artifact_error)
    if not _candidate_symbols_present(candidates, features.get('features')):
        return _invalid('feature_vectors_symbol_mismatch')
    if not _candidate_symbols_present(candidates, ledger.get('items')):
        return _invalid('evidence_ledger_symbol_mismatch')
    return {'ok': True, 'run_id': clean_id, 'generated_at': generated_at, 'candidate_count': count, 'freshness': _freshness(persisted)}


def post_private_telegram(
    message: str,
    *,
    request_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Deliver one HTML message with the personal bot only and verify Telegram's ID."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return {'ok': False, 'status': 'not_configured', 'error_code': 'personal_telegram_not_configured'}
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
        return {'ok': False, 'status': 'rejected', 'error_code': 'telegram_response_rejected'}
    if not _positive_int(message_id):
        return {'ok': False, 'status': 'rejected', 'error_code': 'invalid_message_id'}
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
    digest = _message_digest(message)
    base = {
        'run_id': _text(run.get('id')),
        'message': message,
        'message_digest': digest,
        'candidate_count': 0 if blocked else _candidate_count(run),
        'event_count': len(events),
        'symbols': symbols,
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
            existing = _find_delivery(ledger, base['run_id'], digest)
            if existing is not None:
                return _handle_existing_delivery(ledger, path, existing, alert, base, blocked)

            claim = _delivery_entry(
                status='pending',
                run=run,
                message_digest=digest,
                event_count=len(events),
                symbols=symbols,
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


def _candidate_error(candidate: Any) -> str | None:
    if not isinstance(candidate, dict):
        return 'invalid_candidate'
    if not _text(candidate.get('symbol')) or not (_text(candidate.get('display_name')) or _text(candidate.get('name'))):
        return 'invalid_candidate_identity'
    if not _text(candidate.get('market')):
        return 'invalid_candidate_market'
    if not _finite(candidate.get('alpha_score')) or not _finite(candidate.get('risk_score')):
        return 'invalid_candidate_score'
    if not isinstance(candidate.get('evidence'), list) or not candidate['evidence']:
        return 'invalid_candidate_evidence'
    price = candidate.get('price')
    if not isinstance(price, dict) or not _text(price.get('date')):
        return 'invalid_candidate_price_date'
    return None


def _artifact_error(artifact: Any, run_id: str, label: str, candidate_count: int) -> str | None:
    if not isinstance(artifact, dict):
        return f'{label}_missing'
    if _text(artifact.get('run_id')) != run_id:
        return f'{label}_identity_mismatch'
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


def _candidate_symbols_present(candidates: list[Any], entries: Any) -> bool:
    if not isinstance(entries, list):
        return False
    actual = {_text(item.get('symbol')) for item in entries if isinstance(item, dict)}
    return {_text(item.get('symbol')) for item in candidates if isinstance(item, dict)}.issubset(actual)


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
        'freshness': _freshness(run),
        'state_committed': False,
    }


def _read_ledger(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': _now_iso(), 'deliveries': []}
    if not isinstance(payload, dict):
        return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': _now_iso(), 'deliveries': []}
    deliveries = payload.get('deliveries')
    if isinstance(deliveries, list):
        return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': payload.get('updated_at') or _now_iso(), 'deliveries': [item for item in deliveries if isinstance(item, dict)]}
    # Safely retain a receipt written by the first release as a historical entry.
    if _text(payload.get('run_id')) and _text(payload.get('message_sha256')):
        return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': _now_iso(), 'deliveries': [payload]}
    return {'schema_version': RECEIPT_SCHEMA_VERSION, 'updated_at': _now_iso(), 'deliveries': []}


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
    for entry in ledger.get('deliveries') or []:
        if _text(entry.get('run_id')) == run_id and _text(entry.get('message_sha256')) == digest:
            return entry
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_digest(message: str) -> str:
    return hashlib.sha256(message.encode('utf-8')).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _text(value: Any) -> str:
    return str(value or '').strip()


def _invalid(error_code: str) -> dict[str, Any]:
    return {'ok': False, 'error_code': error_code, 'details': {}}


def _result(status: str, **fields: Any) -> dict[str, Any]:
    return {'ok': status in {'preview', 'delivered', 'blocked'}, 'status': status, **fields}
