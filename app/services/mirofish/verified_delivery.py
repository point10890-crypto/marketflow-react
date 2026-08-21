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


CONFIRMATION_PHRASE = 'SEND_VERIFIED_ALPHA_TELEGRAM'
RECEIPT_SCHEMA_VERSION = 1
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

    Preview is the default and has no filesystem or network side effects.  A
    send is allowed only with the exact operator confirmation phrase.
    """
    scan_payload = dict(payload or {})
    scan_payload['deepseek_rerank'] = False
    try:
        alert = alpha_scanner.run_scanner_alert_check(
            scan_payload,
            deepseek_rerank=False,
            commit_state=False,
            block_on_stale=True,
        )
    except TypeError:
        # The scanner currently accepts deepseek_rerank through its payload.
        # Retain compatibility with that public signature while keeping it off.
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
    stale = bool(alert.get('alert_blocked')) or validation.get('error_code') == 'stale_run'
    if stale:
        return _blocked_result(run, alert, validation)
    if not validation.get('ok'):
        return _result('invalid_run', run_id=run_id, error_code=validation.get('error_code'))

    message = _text(alert.get('message'))
    if not message:
        return _result('invalid_run', run_id=run_id, error_code='missing_alert_message')
    events = _events(alert)
    digest = _message_digest(message)
    result = _result(
        'preview',
        run_id=run_id,
        message=message,
        message_digest=digest,
        candidate_count=_candidate_count(run),
        event_count=len(events),
        symbols=_event_symbols(events),
        freshness=_freshness(run),
        sent=False,
    )
    if not send:
        return result
    if confirmation != CONFIRMATION_PHRASE:
        return _result('confirmation_required', **{key: value for key, value in result.items() if key != 'status'})

    path = Path(receipt_path) if receipt_path else DEFAULT_RECEIPT_PATH
    if _already_delivered(path, run_id, digest):
        return _result('duplicate_refused', **{key: value for key, value in result.items() if key != 'status'})

    delivery = post_private_telegram(message)
    if not delivery.get('ok'):
        return _result('telegram_failed', run_id=run_id, error_code=delivery.get('error_code'), sent=False)
    message_id = delivery.get('message_id')
    if not _positive_int(message_id):
        return _result('telegram_failed', run_id=run_id, error_code='invalid_message_id', sent=False)

    receipt = _receipt(
        status='delivered',
        run=run,
        message_digest=digest,
        message_id=message_id,
        event_count=len(events),
        symbols=_event_symbols(events),
    )
    try:
        write_json_atomic(str(path), receipt, sort_keys=True)
    except Exception:
        return _result('receipt_failed', run_id=run_id, error_code='receipt_write_failed', sent=False)
    try:
        alpha_scanner.commit_scanner_alert_events(alert)
    except Exception:
        return _result('state_commit_failed', run_id=run_id, message_id=message_id, sent=True)
    return _result(
        'delivered',
        run_id=run_id,
        message_id=message_id,
        message_digest=digest,
        candidate_count=_candidate_count(run),
        event_count=len(events),
        symbols=_event_symbols(events),
        freshness=_freshness(run),
        sent=True,
        state_committed=True,
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
    if _freshness(persisted) == 'stale':
        return _invalid('stale_run')
    for candidate in candidates:
        error = _candidate_error(candidate)
        if error:
            return _invalid(error)

    try:
        features = alpha_scanner.read_scanner_run_artifact(clean_id, 'feature_vectors.json')
        ledger = alpha_scanner.read_scanner_run_artifact(clean_id, 'evidence_ledger.json')
    except Exception:
        return _invalid('artifact_read_failed')
    artifact_error = _artifact_error(features, clean_id, 'feature_vectors')
    if artifact_error:
        return _invalid(artifact_error)
    artifact_error = _artifact_error(ledger, clean_id, 'evidence_ledger')
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


def _blocked_result(run: dict[str, Any], alert: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    """Return a non-directional stale-data status; it never contains candidates."""
    return _result(
        'blocked',
        run_id=_text(run.get('id')),
        message='<b>검출 보류</b>\n스캐너 원천 데이터 freshness 검증이 통과하지 않았습니다.',
        candidate_count=0,
        event_count=0,
        symbols=[],
        freshness=_freshness(run),
        error_code=validation.get('error_code') or _text(alert.get('blocked_reason')) or 'stale_run',
        sent=False,
    )


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


def _artifact_error(artifact: Any, run_id: str, label: str) -> str | None:
    if not isinstance(artifact, dict):
        return f'{label}_missing'
    if _text(artifact.get('run_id')) != run_id:
        return f'{label}_identity_mismatch'
    if artifact.get('lookahead_safe') is not True:
        return f'{label}_not_lookahead_safe'
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


def _receipt(*, status: str, run: dict[str, Any], message_digest: str, message_id: int, event_count: int, symbols: list[str]) -> dict[str, Any]:
    return {
        'schema_version': RECEIPT_SCHEMA_VERSION,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'run_id': _text(run.get('id')),
        'message_sha256': message_digest,
        'status': status,
        'delivered': status == 'delivered',
        'message_id': message_id,
        'candidate_count': _candidate_count(run),
        'event_count': event_count,
        'symbols': symbols,
        'freshness': _freshness(run),
    }


def _already_delivered(path: Path, run_id: str, digest: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get('run_id') == run_id and payload.get('message_sha256') == digest


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
