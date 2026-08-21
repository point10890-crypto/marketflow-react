from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.services.mirofish import verified_delivery


RUN_ID = 'scanner-verified-001'
GENERATED_AT = '2026-08-21T00:00:00+00:00'


def _run(*, freshness: str = 'fresh') -> dict:
    return {
        'id': RUN_ID,
        'status': 'completed',
        'generated_at': GENERATED_AT,
        'candidate_count': 1,
        'freshness': {'status': freshness},
        'candidates': [{
            'symbol': '005930',
            'display_name': '삼성전자',
            'market': 'KOSPI',
            'alpha_score': 0.82,
            'risk_score': 0.21,
            'evidence': [{'source': 'price_history', 'field': 'return_20d', 'score': 0.8}],
            'price': {'date': '2026-08-20', 'current_price': 70000},
        }],
    }


def _artifacts() -> dict:
    return {
        'feature_vectors.json': {
            'run_id': RUN_ID,
            'lookahead_safe': True,
            'features': [{'symbol': '005930'}],
        },
        'evidence_ledger.json': {
            'run_id': RUN_ID,
            'lookahead_safe': True,
            'items': [{'symbol': '005930'}],
        },
    }


def _scanner_result(run: dict, *, blocked: bool = False) -> dict:
    return {
        'run': run,
        'events': [{'candidate': run['candidates'][0]}] if not blocked else [],
        'message': '<b>Directional candidate</b>',
        'state_path': 'not-used-in-test.json',
        'new_event_count': 0 if blocked else 1,
        'alert_blocked': blocked,
        'blocked_reason': 'stale_source' if blocked else None,
    }


@pytest.fixture
def scanner(monkeypatch):
    run = _run()
    artifacts = _artifacts()
    result = _scanner_result(run)
    calls = {'commit': 0}

    monkeypatch.setattr(
        verified_delivery.alpha_scanner,
        'run_scanner_alert_check',
        lambda payload, **kwargs: result,
    )
    monkeypatch.setattr(verified_delivery.alpha_scanner, 'read_scanner_run', lambda run_id: deepcopy(run))
    monkeypatch.setattr(
        verified_delivery.alpha_scanner,
        'read_scanner_run_artifact',
        lambda run_id, name: deepcopy(artifacts.get(name)),
    )
    monkeypatch.setattr(
        verified_delivery.alpha_scanner,
        'commit_scanner_alert_events',
        lambda payload: calls.__setitem__('commit', calls['commit'] + 1) or {'ok': True},
    )
    return run, artifacts, result, calls


def test_preview_returns_sanitized_candidate_report_without_send_or_receipt(scanner, tmp_path, monkeypatch):
    """Dropping preview mode must never perform an operator-visible delivery side effect."""
    receipt_path = tmp_path / 'receipt.json'
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))

    assert result['status'] == 'preview'
    assert result['run_id'] == RUN_ID
    assert result['candidate_count'] == 1
    assert result['sent'] is False
    assert not receipt_path.exists()
    assert 'token' not in json.dumps(result).lower()
    assert 'chat_id' not in json.dumps(result).lower()


def test_stale_run_suppresses_directional_candidates(scanner, tmp_path, monkeypatch):
    """Treating stale evidence as a candidate would create a misleading directional alert."""
    run, _, result, _ = scanner
    run['freshness'] = {'status': 'stale'}
    result.update(_scanner_result(run, blocked=True))
    result['message'] = '<b>BUY candidate</b>'
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    preview = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))

    assert preview['status'] == 'blocked'
    assert preview['candidate_count'] == 0
    assert preview['event_count'] == 0
    assert '검출 보류' in preview['message']
    assert 'BUY candidate' not in preview['message']


def test_send_requires_exact_confirmation_before_private_delivery(scanner, tmp_path, monkeypatch):
    """A truthy but wrong confirmation must not authorize a real Telegram request."""
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM_NOW',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert result['status'] == 'confirmation_required'
    assert result['sent'] is False


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (lambda run, artifacts: run.__setitem__('candidate_count', 2), 'candidate_count_mismatch'),
        (lambda run, artifacts: run['candidates'][0].__setitem__('alpha_score', float('nan')), 'invalid_candidate_score'),
        (lambda run, artifacts: artifacts['feature_vectors.json'].__setitem__('lookahead_safe', False), 'feature_vectors_not_lookahead_safe'),
        (lambda run, artifacts: artifacts['evidence_ledger.json'].__setitem__('run_id', 'other-run'), 'evidence_ledger_identity_mismatch'),
    ],
)
def test_validation_rejects_identity_count_and_nonfinite_artifact_defects(scanner, mutate, expected_code):
    """Accepting malformed persisted evidence could turn an unverified run into an alert."""
    run, artifacts, _, _ = scanner
    mutate(run, artifacts)

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation == {'ok': False, 'error_code': expected_code, 'details': {}}


def test_private_telegram_payload_requires_personal_message_id(monkeypatch):
    """Treating a channel payload or response without a message id as delivered is unsafe."""
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {'ok': True, 'result': {'message_id': 321}}

    def post(url, *, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'personal-chat')
    monkeypatch.setenv('TELEGRAM_CHANNEL_BOT_TOKEN', 'channel-token')
    monkeypatch.setenv('TELEGRAM_CHANNEL_CHAT_ID', 'channel-chat')

    delivered = verified_delivery.post_private_telegram('<b>verified</b>', request_post=post)

    assert delivered == {'ok': True, 'status': 'delivered', 'message_id': 321}
    assert captured['url'].endswith('/botpersonal-token/sendMessage')
    assert captured['payload'] == {
        'chat_id': 'personal-chat',
        'text': '<b>verified</b>',
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }


def test_private_telegram_rejects_malformed_message_id_response(monkeypatch):
    """A malformed Telegram success envelope must not be interpreted as delivery."""

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {'ok': True, 'result': []}

    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'personal-chat')

    result = verified_delivery.post_private_telegram('verified', request_post=lambda url, **kwargs: Response())

    assert result == {'ok': False, 'status': 'rejected', 'error_code': 'invalid_message_id'}


def test_duplicate_run_message_digest_is_refused_before_second_delivery(scanner, tmp_path, monkeypatch):
    """A retry of the same run and message must not create a duplicate private alert."""
    receipt_path = tmp_path / 'receipt.json'
    posted = []
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: posted.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 7},
    )

    first = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(receipt_path),
    )
    second = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(receipt_path),
    )

    assert first['status'] == 'delivered'
    assert second['status'] == 'duplicate_refused'
    assert len(posted) == 1


def test_delivery_persists_safe_receipt_then_commits_events(scanner, tmp_path, monkeypatch):
    """Committing scanner alerts before a durable verified receipt would lose failed deliveries."""
    _, _, _, calls = scanner
    receipt_path = tmp_path / 'receipt.json'
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: {'ok': True, 'status': 'delivered', 'message_id': 99},
    )

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(receipt_path),
    )
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))

    assert result['status'] == 'delivered'
    assert calls['commit'] == 1
    assert receipt['schema_version'] == 1
    assert receipt['run_id'] == RUN_ID
    assert receipt['message_id'] == 99
    assert receipt['symbols'] == ['005930']
    assert receipt['event_count'] == 1
    rendered = json.dumps(receipt).lower()
    assert 'directional candidate' not in rendered
    assert 'token' not in rendered
    assert 'chat_id' not in rendered
