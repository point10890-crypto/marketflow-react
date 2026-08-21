from __future__ import annotations

import json
import importlib.util
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.mirofish import verified_delivery


RUN_ID = 'scanner-verified-001'
GENERATED_AT = '2026-08-21T00:00:00+00:00'
EXPECTED_MESSAGE = '\n'.join([
    '<b>MiroFish 알파 스캐너 신규 후보</b>',
    '신규 매수 후보: <b>1</b>건 / 전체 후보: 1건',
    '기준: alpha &gt;= 70, risk &lt;= 45, 로컬 데이터 아티팩트 기반',
    f'Run ID: <code>{RUN_ID}</code>',
    f'생성 시각: {GENERATED_AT}',
    '',
    '#1 <b>삼성전자</b> (<code>005930</code> KOSPI)',
    '알파 <b>82.0</b> / 리스크 <b>21.0</b> / 랭킹 70.45',
    '판정: <b>매수 후보</b> / 기간: 스윙 5-20일',
    '현재가: 70,000 (+1.50%) / 태그: 추세 품질',
    '근거: price_history return_20d=0.8',
])
EXPECTED_BLOCKED_MESSAGE = '\n'.join([
    '<b>MiroFish 알파 스캐너 신규 후보</b>',
    '신규 매수 후보: <b>0</b>건 / 전체 후보: 1건',
    '기준: alpha &gt;= 70, risk &lt;= 45, 로컬 데이터 아티팩트 기반',
    f'Run ID: <code>{RUN_ID}</code>',
    f'생성 시각: {GENERATED_AT}',
    '알림 차단: 원천 데이터 freshness=stale. 데이터 갱신 후 재시도하세요.',
])


def _run(*, freshness: str = 'fresh') -> dict:
    return {
        'id': RUN_ID,
        'status': 'completed',
        'generated_at': GENERATED_AT,
        'candidate_count': 1,
        'freshness': {'status': freshness},
        'candidates': [{
            'rank': 1,
            'symbol': '005930',
            'name': '삼성전자',
            'display_name': '삼성전자',
            'market': 'KOSPI',
            'alpha_score': 82.0,
            'risk_score': 21.0,
            'ranking_score': 70.45,
            'action': 'BUY_CANDIDATE',
            'horizon': 'swing_5_20d',
            'strategy_tags': ['trend_quality'],
            'evidence': [{'source': 'price_history', 'field': 'return_20d', 'score': 0.8}],
            'price': {'date': '2026-08-20', 'current_price': 70000, 'change_rate': 1.5},
            'generated_at': GENERATED_AT,
        }],
    }


def _artifacts() -> dict:
    feature = {
        'symbol': '005930',
        'name': '삼성전자',
        'market': 'KOSPI',
        'action': 'BUY_CANDIDATE',
        'alpha_score': 82.0,
        'risk_score': 21.0,
        'ranking_score': 70.45,
        'price_date': '2026-08-20',
        'current_price': 70000,
        'lookahead_safe': True,
    }
    return {
        'feature_vectors.json': {
            'run_id': RUN_ID,
            'generated_at': GENERATED_AT,
            'lookahead_safe': True,
            'feature_count': 1,
            'features': [feature],
        },
        'evidence_ledger.json': {
            'run_id': RUN_ID,
            'generated_at': GENERATED_AT,
            'lookahead_safe': True,
            'candidate_count': 1,
            'rejected_candidate_count': 0,
            'items': [{
                'symbol': '005930',
                'name': '삼성전자',
                'market': 'KOSPI',
                'selection_status': 'selected',
                'action': 'BUY_CANDIDATE',
                'alpha_score': 82.0,
                'risk_score': 21.0,
                'ranking_score': 70.45,
                'evidence': [{'source': 'price_history', 'field': 'return_20d', 'score': 0.8}],
                'feature_vector': deepcopy(feature),
            }],
        },
    }


def _scanner_result(run: dict, *, blocked: bool = False) -> dict:
    candidate = run['candidates'][0]
    return {
        'run': run,
        'events': [{
            'event_key': '005930:BUY_CANDIDATE:2026-08-20',
            'run_id': run['id'],
            'generated_at': run['generated_at'],
            'candidate': candidate,
        }] if not blocked else [],
        'message': '<b>Directional candidate</b>',
        'state_path': 'not-used-in-test.json',
        'new_event_count': 0 if blocked else 1,
        'alert_blocked': blocked,
        'blocked_reason': 'stale_source' if blocked else None,
    }


def _assert_public_result_sanitized(result: dict) -> None:
    assert 'message' not in result
    rendered = json.dumps(result).lower()
    assert 'token' not in rendered
    assert 'chat_id' not in rendered


@pytest.fixture
def scanner(monkeypatch):
    run = _run()
    artifacts = _artifacts()
    result = _scanner_result(run)
    calls = {'commit': 0, 'payloads': []}

    def commit(payload):
        calls['commit'] += 1
        calls['payloads'].append(deepcopy(payload))
        return {'ok': True}

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
        commit,
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
    _assert_public_result_sanitized(result)


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
    _assert_public_result_sanitized(preview)


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
    _assert_public_result_sanitized(result)


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (lambda run, artifacts: run.__setitem__('candidate_count', 2), 'candidate_count_mismatch'),
        (lambda run, artifacts: run['candidates'][0].__setitem__('alpha_score', float('nan')), 'invalid_candidate_score'),
        (lambda run, artifacts: artifacts['feature_vectors.json'].__setitem__('lookahead_safe', False), 'feature_vectors_not_lookahead_safe'),
        (lambda run, artifacts: artifacts['evidence_ledger.json'].__setitem__('run_id', 'other-run'), 'evidence_ledger_identity_mismatch'),
        (lambda run, artifacts: artifacts['feature_vectors.json'].__setitem__('feature_count', 0), 'feature_vectors_count_mismatch'),
        (lambda run, artifacts: run.__setitem__('generated_at', 'not-a-timestamp'), 'invalid_generated_at'),
        (lambda run, artifacts: artifacts['feature_vectors.json'].__setitem__('generated_at', '2026-08-20T00:00:00+00:00'), 'feature_vectors_generated_at_mismatch'),
        (lambda run, artifacts: artifacts['evidence_ledger.json'].__setitem__('generated_at', 'not-a-timestamp'), 'evidence_ledger_generated_at_mismatch'),
        (lambda run, artifacts: run['candidates'][0]['price'].__setitem__('date', '2026-08-22'), 'candidate_price_after_run'),
        (lambda run, artifacts: run['candidates'][0]['price'].__setitem__('date', 'not-a-date'), 'invalid_candidate_price_date'),
        (lambda run, artifacts: run['candidates'][0]['evidence'][0].__setitem__('score', float('nan')), 'invalid_candidate_evidence'),
        (lambda run, artifacts: run['candidates'][0]['evidence'][0].__setitem__('source', ''), 'invalid_candidate_evidence'),
        (lambda run, artifacts: artifacts['feature_vectors.json']['features'][0].__setitem__('ranking_score', float('nan')), 'invalid_feature_vector'),
        (lambda run, artifacts: artifacts['feature_vectors.json']['features'][0].__setitem__('price_date', 'not-a-date'), 'invalid_feature_vector'),
        (lambda run, artifacts: artifacts['evidence_ledger.json']['items'][0]['evidence'][0].__setitem__('field', ''), 'invalid_evidence_ledger_item'),
        (lambda run, artifacts: artifacts['evidence_ledger.json']['items'][0].__setitem__('risk_score', float('nan')), 'invalid_evidence_ledger_item'),
        (lambda run, artifacts: artifacts['evidence_ledger.json']['items'][0].__setitem__('feature_vector', []), 'invalid_evidence_ledger_item'),
    ],
)
def test_validation_rejects_identity_count_and_nonfinite_artifact_defects(scanner, mutate, expected_code):
    """Accepting malformed persisted evidence could turn an unverified run into an alert."""
    run, artifacts, _, _ = scanner
    mutate(run, artifacts)

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation == {'ok': False, 'error_code': expected_code, 'details': {}}


def test_delivery_rejects_transient_event_and_message_for_another_symbol(scanner, tmp_path, monkeypatch):
    """A persisted 005930 run must never deliver or commit a transient 000660 event."""
    _, _, result, calls = scanner
    transient = deepcopy(result['events'][0]['candidate'])
    transient.update({'symbol': '000660', 'name': 'SK하이닉스', 'display_name': 'SK하이닉스'})
    result['events'][0].update({
        'event_key': '000660:BUY_CANDIDATE:2026-08-20',
        'candidate': transient,
    })
    result['message'] = '<b>000660 transient candidate</b>'
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert delivered == {
        'ok': False,
        'status': 'invalid_run',
        'run_id': RUN_ID,
        'error_code': 'event_candidate_mismatch',
    }
    assert calls['commit'] == 0
    _assert_public_result_sanitized(delivered)


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (lambda event: event.__setitem__('run_id', 'other-run'), 'event_run_id_mismatch'),
        (lambda event: event.__setitem__('generated_at', '2026-08-20T00:00:00+00:00'), 'event_generated_at_mismatch'),
        (lambda event: event.__setitem__('event_key', 'wrong:key'), 'event_key_mismatch'),
    ],
)
def test_delivery_rejects_transient_event_metadata_mismatch(scanner, tmp_path, monkeypatch, mutate, expected_code):
    """Transient event metadata must bind exactly to the persisted run and candidate."""
    _, _, result, calls = scanner
    mutate(result['events'][0])
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert delivered['status'] == 'invalid_run'
    assert delivered['error_code'] == expected_code
    assert calls['commit'] == 0
    _assert_public_result_sanitized(delivered)


def test_delivery_rejects_any_transient_run_difference_from_persisted(scanner, tmp_path, monkeypatch):
    """Checking only ID/count/timestamp leaves unverified candidate fields trusted."""
    _, _, result, calls = scanner
    result['run'] = deepcopy(result['run'])
    result['run']['candidates'][0]['risk_score'] = 1.0
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert delivered['status'] == 'invalid_run'
    assert delivered['error_code'] == 'run_content_mismatch'
    assert calls['commit'] == 0


def test_stale_run_with_corrupt_artifact_is_invalid_not_deliverable_hold(scanner, tmp_path, monkeypatch):
    """Freshness must not mask missing proof artifacts behind a sendable hold."""
    run, artifacts, result, calls = scanner
    run['freshness'] = {'status': 'stale'}
    result.update(_scanner_result(run, blocked=True))
    artifacts['feature_vectors.json'] = None
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert delivered == {
        'ok': False,
        'status': 'invalid_run',
        'run_id': RUN_ID,
        'error_code': 'feature_vectors_missing',
    }
    assert calls['commit'] == 0


@pytest.mark.parametrize(('freshness', 'alert_blocked'), [('fresh', True), ('stale', False)])
def test_persisted_and_transient_freshness_block_state_must_agree(
    scanner, tmp_path, monkeypatch, freshness, alert_blocked,
):
    """Neither a transient false hold nor a transient bypass may override persisted freshness."""
    run, _, result, calls = scanner
    run['freshness'] = {'status': freshness}
    result.update(_scanner_result(run, blocked=alert_blocked))
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert delivered['status'] == 'invalid_run'
    assert delivered['error_code'] == 'freshness_alert_mismatch'
    assert calls['commit'] == 0


def test_private_telegram_payload_requires_matching_private_chat_and_message_id(monkeypatch):
    """Treating a channel payload or response without a message id as delivered is unsafe."""
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {'ok': True, 'result': {'message_id': 321, 'chat': {'id': 12345, 'type': 'private'}}}

    def post(url, *, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '12345')
    monkeypatch.setenv('TELEGRAM_CHANNEL_BOT_TOKEN', 'channel-token')
    monkeypatch.setenv('TELEGRAM_CHANNEL_CHAT_ID', 'channel-chat')

    delivered = verified_delivery.post_private_telegram('<b>verified</b>', request_post=post)

    assert delivered == {'ok': True, 'status': 'delivered', 'message_id': 321}
    assert captured['url'].endswith('/botpersonal-token/sendMessage')
    assert captured['payload'] == {
        'chat_id': 12345,
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
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '12345')

    result = verified_delivery.post_private_telegram('verified', request_post=lambda url, **kwargs: Response())

    assert result == {'ok': False, 'status': 'rejected', 'error_code': 'invalid_message_id'}


@pytest.mark.parametrize('configured', ['0', '-100123', 'not-a-chat'])
def test_private_telegram_rejects_nonpositive_or_noninteger_config_without_request(monkeypatch, configured):
    """A group/channel-style or malformed configured ID must never reach Telegram."""
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', configured)

    result = verified_delivery.post_private_telegram('verified', request_post=pytest.fail)

    assert result == {
        'ok': False,
        'status': 'not_configured',
        'error_code': 'personal_telegram_not_configured',
        'retryable': True,
    }
    assert configured not in json.dumps(result)


@pytest.mark.parametrize(
    'chat',
    [
        {'id': 12345, 'type': 'group'},
        {'id': -100123, 'type': 'channel'},
        {'id': 54321, 'type': 'private'},
        None,
    ],
)
def test_private_telegram_rejects_unverified_response_chat(monkeypatch, chat):
    """A valid message ID is not proof that Telegram delivered to the configured private chat."""

    class Response:
        status_code = 200

        @staticmethod
        def json():
            result = {'message_id': 321}
            if chat is not None:
                result['chat'] = chat
            return {'ok': True, 'result': result}

    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '12345')

    result = verified_delivery.post_private_telegram('verified', request_post=lambda url, **kwargs: Response())

    assert result == {'ok': False, 'status': 'rejected', 'error_code': 'private_chat_verification_failed'}
    assert '12345' not in json.dumps(result)


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
    posted = []
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: posted.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 99},
    )

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(receipt_path),
    )
    ledger = json.loads(receipt_path.read_text(encoding='utf-8'))
    receipt = ledger['deliveries'][0]

    assert result['status'] == 'delivered'
    assert calls['commit'] == 1
    assert posted == [EXPECTED_MESSAGE]
    assert calls['payloads'][0]['run'] == _run()
    assert calls['payloads'][0]['events'][0]['candidate'] == _run()['candidates'][0]
    assert calls['payloads'][0]['events'][0]['event_key'] == '005930:BUY_CANDIDATE:2026-08-20'
    assert calls['payloads'][0]['message'] == EXPECTED_MESSAGE
    _assert_public_result_sanitized(result)
    assert ledger['schema_version'] == 2
    assert receipt['run_id'] == RUN_ID
    assert receipt['message_id'] == 99
    assert receipt['symbols'] == ['005930']
    assert receipt['event_count'] == 1
    rendered = json.dumps(receipt).lower()
    assert 'directional candidate' not in rendered
    assert 'token' not in rendered
    assert 'chat_id' not in rendered


@pytest.mark.parametrize('freshness', ['stale', 'missing', 'partial', 'unknown'])
def test_all_alert_blocking_freshness_states_return_non_directional_preview(scanner, tmp_path, freshness):
    """Relaxing any scanner blocking freshness state would leak a directional report."""
    run, _, result, _ = scanner
    run['freshness'] = {'status': freshness}
    result.update(_scanner_result(run, blocked=True))
    result['message'] = '<b>BUY candidate</b>'

    preview = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))

    assert preview['status'] == 'blocked'
    assert preview['symbols'] == []
    _assert_public_result_sanitized(preview)


def test_blocked_run_sends_one_status_message_only_with_exact_confirmation(scanner, tmp_path, monkeypatch):
    """A blocked run still needs a guarded operational status delivery, never a candidate alert."""
    run, _, result, calls = scanner
    run['freshness'] = {'status': 'stale'}
    result.update(_scanner_result(run, blocked=True))
    sent = []
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 55},
    )

    denied = verified_delivery.run_verified_detection(send=True, receipt_path=str(tmp_path / 'receipt.json'))
    delivered = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert denied['status'] == 'confirmation_required'
    assert delivered['status'] == 'blocked_delivered'
    assert delivered['ok'] is True
    assert sent == [EXPECTED_BLOCKED_MESSAGE.replace('freshness=stale', f'freshness={run["freshness"]["status"]}')]
    assert calls['commit'] == 0
    _assert_public_result_sanitized(denied)
    _assert_public_result_sanitized(delivered)


def test_scanner_typeerror_is_sanitized_without_second_run(scanner, monkeypatch, tmp_path):
    """An internal scanner TypeError must not rerun scanner work or expose its text."""
    attempts = []

    def fail_once(*args, **kwargs):
        attempts.append(1)
        raise TypeError('token=secret')

    monkeypatch.setattr(verified_delivery.alpha_scanner, 'run_scanner_alert_check', fail_once)

    result = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))

    assert result == {'ok': False, 'status': 'scanner_failed'}
    assert attempts == [1]
    _assert_public_result_sanitized(result)


def test_claim_write_failure_prevents_telegram_send(scanner, monkeypatch, tmp_path):
    """Sending before a durable pending claim makes an uncertain delivery retriable."""
    monkeypatch.setattr(verified_delivery, 'write_json_atomic', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert result == {'ok': False, 'status': 'receipt_claim_failed', 'run_id': RUN_ID, 'error_code': 'receipt_claim_write_failed', 'sent': False}


def test_final_receipt_failure_leaves_uncertain_claim_and_blocks_resend(scanner, monkeypatch, tmp_path):
    """A response after the pending claim but before final persistence is uncertain, not retryable."""
    receipt_path = tmp_path / 'receipt.json'
    real_write = verified_delivery.write_json_atomic
    writes = []

    def fail_final(path, payload, **kwargs):
        writes.append(payload)
        if len(writes) == 2:
            raise OSError('disk full')
        return real_write(path, payload, **kwargs)

    sent = []
    monkeypatch.setattr(verified_delivery, 'write_json_atomic', fail_final)
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 77})

    first = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    second = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))

    assert first['status'] == 'delivery_uncertain'
    assert first['sent'] is None
    assert second['status'] == 'delivery_uncertain'
    assert sent == [EXPECTED_MESSAGE]
    _assert_public_result_sanitized(first)
    _assert_public_result_sanitized(second)


def test_new_run_recovers_matching_uncommitted_event_without_resending(scanner, monkeypatch, tmp_path):
    """A newly-created scanner run must recover a delivered event by its stable event key."""
    run, artifacts, result, calls = scanner
    receipt_path = tmp_path / 'receipt.json'
    sent = []
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 88})

    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', lambda payload: (_ for _ in ()).throw(RuntimeError('commit failed')))
    first = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    run['id'] = 'scanner-verified-002'
    result['run'] = run
    result['events'][0]['run_id'] = run['id']
    artifacts['feature_vectors.json']['run_id'] = run['id']
    artifacts['evidence_ledger.json']['run_id'] = run['id']
    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', lambda payload: calls.__setitem__('commit', calls['commit'] + 1) or {'ok': True})
    second = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))

    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))['deliveries'][0]
    assert first['status'] == 'state_commit_failed'
    assert second['status'] == 'delivered_recovered'
    assert second['ok'] is True
    assert sent == [EXPECTED_MESSAGE]
    assert calls['commit'] == 1
    assert receipt['state_committed'] is True


def test_concurrent_same_digest_sends_once(scanner, monkeypatch, tmp_path):
    """Two simultaneous operators must serialize on the receipt lock before transport."""
    receipt_path = tmp_path / 'receipt.json'
    sent = []
    sent_lock = threading.Lock()

    def post(message):
        with sent_lock:
            sent.append(message)
        time.sleep(0.05)
        return {'ok': True, 'status': 'delivered', 'message_id': 101}

    monkeypatch.setattr(verified_delivery, 'post_private_telegram', post)
    results = []
    workers = [threading.Thread(target=lambda: results.append(verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path)))) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert sent == [EXPECTED_MESSAGE]
    assert sorted(result['status'] for result in results) == ['delivered', 'duplicate_refused']


def test_transient_message_changes_cannot_change_canonical_digest_or_resend(scanner, monkeypatch, tmp_path):
    """Transient message text must not create a second digest for one persisted run."""
    _, _, result, _ = scanner
    receipt_path = tmp_path / 'receipt.json'
    sent = []
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': len(sent)})

    first = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    result['message'] = '<b>changed candidate</b>'
    second = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    result['message'] = '<b>000660 attacker-controlled candidate</b>'
    third = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))

    assert [first['status'], second['status'], third['status']] == ['delivered', 'duplicate_refused', 'duplicate_refused']
    assert sent == [EXPECTED_MESSAGE]
    for item in (first, second, third):
        _assert_public_result_sanitized(item)


def test_known_telegram_nondelivery_is_recorded_retryable_and_can_send(scanner, monkeypatch, tmp_path):
    """A missing config or explicit API rejection is known not to have delivered a message."""
    receipt_path = tmp_path / 'receipt.json'
    responses = [
        {'ok': False, 'status': 'not_configured', 'error_code': 'personal_telegram_not_configured', 'retryable': True},
        {'ok': True, 'status': 'delivered', 'message_id': 144},
    ]
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', lambda message: responses.pop(0))

    first = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    second = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))

    ledger = json.loads(receipt_path.read_text(encoding='utf-8'))
    assert first['status'] == 'telegram_not_delivered'
    assert second['status'] == 'delivered'
    assert [entry['status'] for entry in ledger['deliveries']] == ['failed', 'delivered']
    _assert_public_result_sanitized(first)
    _assert_public_result_sanitized(second)


def test_ambiguous_telegram_request_remains_uncertain_and_blocks_resend(scanner, monkeypatch, tmp_path):
    """A request failure can have reached Telegram, so the pending claim must block a retry."""
    receipt_path = tmp_path / 'receipt.json'
    attempts = []
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: attempts.append(message) or {'ok': False, 'status': 'request_failed', 'error_code': 'telegram_request_failed'},
    )

    first = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    second = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))

    assert [first['status'], second['status']] == ['delivery_uncertain', 'delivery_uncertain']
    assert attempts == [EXPECTED_MESSAGE]


def test_private_telegram_marks_explicit_api_rejection_retryable(monkeypatch):
    """A Telegram `ok=false` response is explicit non-delivery, unlike a transport failure."""

    class Response:
        status_code = 400

        @staticmethod
        def json():
            return {'ok': False, 'description': 'bad request'}

    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '12345')

    result = verified_delivery.post_private_telegram('verified', request_post=lambda url, **kwargs: Response())

    assert result == {'ok': False, 'status': 'rejected', 'error_code': 'telegram_response_rejected', 'retryable': True}


@pytest.mark.parametrize('status', ['blocked_delivered', 'delivered_recovered'])
def test_cli_returns_success_for_recovered_and_blocked_delivery(status, monkeypatch, capsys):
    """Operator CLI must not report a successful guarded delivery as a failed process."""
    script_path = Path(__file__).parents[1] / 'scripts' / 'run_verified_alpha_telegram.py'
    spec = importlib.util.spec_from_file_location(f'verified_cli_{status}', script_path)
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, '_load_dotenv', lambda: None)
    monkeypatch.setattr(
        cli,
        'run_verified_detection',
        lambda **kwargs: {'ok': True, 'status': status, 'message': '<b>private transport content</b>'},
    )

    assert cli.main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['status'] == status
    assert 'message' not in payload


def test_cli_reconfigures_stdout_to_utf8_before_printing(monkeypatch):
    """Windows callers decoding UTF-8 must receive readable non-ASCII JSON."""
    script_path = Path(__file__).parents[1] / 'scripts' / 'run_verified_alpha_telegram.py'
    spec = importlib.util.spec_from_file_location('verified_cli_utf8', script_path)
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    class ReconfigurableStream:
        encoding = 'cp949'

        def __init__(self):
            self.value = ''

        def reconfigure(self, *, encoding):
            self.encoding = encoding

        def write(self, value):
            self.value += value
            return len(value)

        def flush(self):
            return None

    stream = ReconfigurableStream()
    monkeypatch.setattr(cli, '_load_dotenv', lambda: None)
    monkeypatch.setattr(cli, 'run_verified_detection', lambda **kwargs: {'ok': True, 'status': '검출 보류'})
    monkeypatch.setattr(cli.sys, 'stdout', stream)

    assert cli.main([]) == 0
    assert stream.encoding == 'utf-8'
    assert json.loads(stream.value)['status'] == '검출 보류'


def test_stdout_utf8_configuration_is_optional_for_streams_without_reconfigure():
    """Redirected or embedded streams without reconfigure remain supported."""
    script_path = Path(__file__).parents[1] / 'scripts' / 'run_verified_alpha_telegram.py'
    spec = importlib.util.spec_from_file_location('verified_cli_plain_stdout', script_path)
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    class PlainStream:
        pass

    cli._configure_stdout_utf8(PlainStream())


@pytest.mark.parametrize(
    'contents',
    [
        '{not valid json',
        json.dumps({'schema_version': 2, 'deliveries': {}}),
        json.dumps({'schema_version': 999, 'deliveries': []}),
    ],
)
def test_invalid_existing_ledger_fails_closed_without_telegram(scanner, monkeypatch, tmp_path, contents):
    """A corrupt receipt cannot be treated as an empty dedupe ledger."""
    receipt_path = tmp_path / 'receipt.json'
    receipt_path.write_text(contents, encoding='utf-8')
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(receipt_path),
    )

    assert result == {'ok': False, 'status': 'receipt_invalid', 'run_id': RUN_ID, 'error_code': 'receipt_invalid', 'sent': False}
    assert receipt_path.read_text(encoding='utf-8') == contents


@pytest.mark.parametrize(
    'mutate',
    [
        lambda entry: entry.update({'delivered': True, 'message_id': 42}),
        lambda entry: entry.__setitem__('message_sha256', 'not-a-digest'),
        lambda entry: entry.__setitem__('symbols', ['005930', 7]),
        lambda entry: entry.__setitem__('event_keys', '005930:BUY:2026-08-20'),
        lambda entry: entry.__setitem__('status', 'made_up'),
        lambda entry: entry.update({'status': 'delivered', 'delivered': True, 'message_id': None}),
    ],
)
def test_semantically_invalid_v2_entry_fails_closed_without_overwrite(scanner, monkeypatch, tmp_path, mutate):
    """Contradictory historical state must not be ignored to reopen a Telegram send."""
    receipt_path = tmp_path / 'receipt.json'
    entry = {
        'run_id': 'previous-run',
        'message_sha256': 'a' * 64,
        'status': 'failed',
        'delivered': False,
        'message_id': None,
        'candidate_count': 1,
        'event_count': 1,
        'symbols': ['005930'],
        'event_keys': ['005930:BUY_CANDIDATE:2026-08-20'],
        'state_committed': False,
        'retryable': True,
    }
    mutate(entry)
    contents = json.dumps({'schema_version': 2, 'deliveries': [entry]})
    receipt_path.write_text(contents, encoding='utf-8')
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(receipt_path),
    )

    assert result == {'ok': False, 'status': 'receipt_invalid', 'run_id': RUN_ID, 'error_code': 'receipt_invalid', 'sent': False}
    assert receipt_path.read_text(encoding='utf-8') == contents


@pytest.mark.parametrize(
    ('case', 'mutate'),
    [
        ('non_string_run_id', lambda entry: entry.__setitem__('run_id', 123)),
        ('uppercase_message_sha256', lambda entry: entry.__setitem__('message_sha256', 'A' * 64)),
        ('retryable_non_failed_state', lambda entry: entry.__setitem__('status', 'pending')),
    ],
)
def test_strict_v2_entry_identity_and_retryability_fail_closed(scanner, monkeypatch, tmp_path, case, mutate):
    """Malformed identity or retryability fields must not reopen a Telegram send."""
    receipt_path = tmp_path / f'{case}.json'
    entry = {
        'run_id': 'previous-run',
        'message_sha256': 'a' * 64,
        'status': 'failed',
        'delivered': False,
        'message_id': None,
        'candidate_count': 1,
        'event_count': 1,
        'symbols': ['005930'],
        'event_keys': ['005930:BUY_CANDIDATE:2026-08-20'],
        'state_committed': False,
        'retryable': True,
    }
    mutate(entry)
    contents = json.dumps({'schema_version': 2, 'deliveries': [entry]})
    receipt_path.write_text(contents, encoding='utf-8')
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        receipt_path=str(receipt_path),
    )

    assert result == {'ok': False, 'status': 'receipt_invalid', 'run_id': RUN_ID, 'error_code': 'receipt_invalid', 'sent': False}
    assert receipt_path.read_text(encoding='utf-8') == contents
