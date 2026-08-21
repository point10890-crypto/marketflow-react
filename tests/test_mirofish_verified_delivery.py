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
            'feature_count': 1,
            'features': [{'symbol': '005930'}],
        },
        'evidence_ledger.json': {
            'run_id': RUN_ID,
            'lookahead_safe': True,
            'candidate_count': 1,
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
        (lambda run, artifacts: artifacts['feature_vectors.json'].__setitem__('feature_count', 0), 'feature_vectors_count_mismatch'),
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
    ledger = json.loads(receipt_path.read_text(encoding='utf-8'))
    receipt = ledger['deliveries'][0]

    assert result['status'] == 'delivered'
    assert calls['commit'] == 1
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
    assert '검출 보류' in preview['message']


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
    assert sent == ['<b>검출 보류</b>\n스캐너 원천 데이터 freshness 검증이 통과하지 않았습니다.']
    assert calls['commit'] == 0


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
    assert sent == ['<b>Directional candidate</b>']


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
    artifacts['feature_vectors.json']['run_id'] = run['id']
    artifacts['evidence_ledger.json']['run_id'] = run['id']
    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', lambda payload: calls.__setitem__('commit', calls['commit'] + 1) or {'ok': True})
    second = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))

    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))['deliveries'][0]
    assert first['status'] == 'state_commit_failed'
    assert second['status'] == 'delivered_recovered'
    assert second['ok'] is True
    assert sent == ['<b>Directional candidate</b>']
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

    assert sent == ['<b>Directional candidate</b>']
    assert sorted(result['status'] for result in results) == ['delivered', 'duplicate_refused']


def test_historical_receipts_refuse_original_digest_after_different_message(scanner, monkeypatch, tmp_path):
    """Replacing a single latest receipt would forget an earlier delivery for the same run."""
    _, _, result, _ = scanner
    receipt_path = tmp_path / 'receipt.json'
    sent = []
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': len(sent)})

    first = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    result['message'] = '<b>changed candidate</b>'
    second = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))
    result['message'] = '<b>Directional candidate</b>'
    third = verified_delivery.run_verified_detection(send=True, confirmation='SEND_VERIFIED_ALPHA_TELEGRAM', receipt_path=str(receipt_path))

    assert [first['status'], second['status'], third['status']] == ['delivered', 'delivered', 'duplicate_refused']
    assert sent == ['<b>Directional candidate</b>', '<b>changed candidate</b>']


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
    assert attempts == ['<b>Directional candidate</b>']


def test_private_telegram_marks_explicit_api_rejection_retryable(monkeypatch):
    """A Telegram `ok=false` response is explicit non-delivery, unlike a transport failure."""

    class Response:
        status_code = 400

        @staticmethod
        def json():
            return {'ok': False, 'description': 'bad request'}

    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'personal-chat')

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
    monkeypatch.setattr(cli, 'run_verified_detection', lambda **kwargs: {'ok': True, 'status': status})

    assert cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == status


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
