from __future__ import annotations

import json
import importlib.util
import hashlib
import os
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.mirofish import verified_delivery


RUN_ID = 'scanner-verified-001'
GENERATED_AT = '2026-08-21T00:00:00+00:00'
CANONICAL_STATE_PATH = str(
    Path(__file__).parents[1] / 'data' / 'admin_mirofish' / 'alpha_scanner_alert_state.json'
)
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
    '근거: daily_prices.csv return_20d=0.8',
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
    quality = {
        'grade': 'moderate',
        'source_count': 2,
        'evidence_count': 1,
        'freshness_status': freshness,
        'average_confidence': 0.75,
    }
    candidate = {
        'pool_rank': 1,
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
        'signal_quality': 'strong',
        'strategy_tags': ['trend_quality'],
        'evidence': [{
            'source': 'daily_prices.csv',
            'field': 'return_20d',
            'score': 0.8,
            'confidence': 0.75,
        }],
        'analysis_profile': {
            'source_count': 2,
            'base_source_count': 2,
            'evidence_quality': quality,
            'confidence_cap': 0.9,
            'freshness_status': freshness,
        },
        'replay_context': {
            'price_date': '2026-08-20',
            'generated_at': GENERATED_AT,
            'data_sources': ['daily_prices.csv', 'screener_leading_latest.json'],
            'lookahead_safe': True,
        },
        'price': {'date': '2026-08-20', 'current_price': 70000, 'change_rate': 1.5},
        'generated_at': GENERATED_AT,
        'freshness': {'status': freshness},
    }
    return {
        'id': RUN_ID,
        'status': 'completed',
        'generated_at': GENERATED_AT,
        'candidate_count': 1,
        'freshness': {'status': freshness},
        'source_files': [
            {
                'file': 'data/daily_prices.csv', 'exists': True, 'generated_at': None,
                'modified_at': '2026-08-20T00:00:00+00:00', 'freshness': 'fresh',
                'age_days': 1, 'max_age_days': 5, 'role': 'price_history',
                'required': True, 'alert_required': True,
            },
            {
                'file': 'data/ticker_to_yahoo_map.csv', 'exists': True, 'generated_at': None,
                'modified_at': '2026-08-01T00:00:00+00:00', 'freshness': 'fresh',
                'age_days': 20, 'max_age_days': 180, 'role': 'symbol_map',
                'required': True, 'alert_required': True,
            },
            {
                'file': 'data/screener_leading_latest.json', 'exists': True,
                'generated_at': '2026-08-21T08:59:00',
                'modified_at': '2026-08-20T23:59:00+00:00', 'freshness': 'fresh',
                'age_days': 0, 'max_age_days': 7, 'role': 'leading_screener',
                'required': True, 'alert_required': True,
            },
        ],
        'candidates': [candidate],
    }


def _feature(candidate: dict) -> dict:
    profile = candidate['analysis_profile']
    replay = candidate['replay_context']
    price = candidate['price']
    return {
        'symbol': '005930',
        'name': '삼성전자',
        'market': 'KOSPI',
        'pool_rank': 1,
        'rank': 1,
        'action': 'BUY_CANDIDATE',
        'horizon': 'swing_5_20d',
        'alpha_score': 82.0,
        'risk_score': 21.0,
        'ranking_score': 70.45,
        'signal_quality': 'strong',
        'strategy_tags': ['trend_quality'],
        'source_count': 2,
        'base_source_count': 2,
        'evidence_quality': profile['evidence_quality'],
        'confidence_cap': 0.9,
        'profitability_scorecard': None,
        'false_signal_gates': None,
        'capital_flow_confirmation': None,
        'mcp_quality_adjustment': None,
        'performance_memory': None,
        'goal_fit_score': None,
        'goal_verdict': None,
        'freshness_status': profile['freshness_status'],
        'freshness_penalty': None,
        'data_sources': replay['data_sources'],
        'lookahead_safe': True,
        'price_date': '2026-08-20',
        'current_price': 70000,
        'change_rate': 1.5,
        'volume': None,
        'trading_value': None,
        'trend_quality': None,
        'volume_accumulation': None,
        'trend_5d_pct': None,
        'trend_20d_pct': None,
        'volume_ratio': None,
        'volatility_20d_pct': None,
        'drawdown_20d_pct': None,
        'over_ma20_pct': None,
        'trend_consistency': None,
        'sample_days': None,
        'tradingview': None,
    }


def _artifacts(run: dict | None = None) -> dict:
    run = run or _run()
    candidate = run['candidates'][0]
    feature = _feature(candidate)
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
                'rank': 1,
                'pool_rank': 1,
                'selection_status': 'selected',
                'rejection_reasons': [],
                'action': 'BUY_CANDIDATE',
                'alpha_score': 82.0,
                'risk_score': 21.0,
                'ranking_score': 70.45,
                'signal_quality': 'strong',
                'strategy_tags': ['trend_quality'],
                'evidence_quality': candidate['analysis_profile']['evidence_quality'],
                'confidence_cap': 0.9,
                'freshness': candidate['freshness'],
                'data_sources': candidate['replay_context']['data_sources'],
                'evidence': deepcopy(candidate['evidence']),
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
        'state_path': CANONICAL_STATE_PATH,
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
def scanner(monkeypatch, tmp_path):
    run = _run()
    artifacts = _artifacts(run)
    result = _scanner_result(run)
    calls = {'scan': 0, 'commit': 0, 'payloads': []}

    monkeypatch.setattr(
        verified_delivery,
        '_utc_now',
        lambda: verified_delivery.datetime.fromisoformat('2026-08-21T00:10:00+00:00'),
    )
    monkeypatch.setattr(verified_delivery, 'DEFAULT_ALERT_STATE_PATH', tmp_path / 'alert_state.json')

    def commit(payload):
        calls['commit'] += 1
        calls['payloads'].append(deepcopy(payload))
        return {'ok': True}

    def scan(payload, **kwargs):
        calls['scan'] += 1
        return result

    monkeypatch.setattr(verified_delivery.alpha_scanner, 'run_scanner_alert_check', scan)
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


def _set_alert_source_status(run: dict, status: str) -> None:
    source = run['source_files'][0]
    if status == 'stale':
        source.update({
            'exists': True,
            'modified_at': '2026-01-01T00:00:00+00:00',
            'freshness': 'stale',
            'age_days': 200,
        })
    elif status in {'missing', 'partial'}:
        source.update({
            'exists': False,
            'generated_at': None,
            'modified_at': None,
            'freshness': 'unknown',
            'age_days': None,
        })
    elif status == 'unknown':
        source.update({'freshness': 'unknown'})
    else:
        raise AssertionError(f'unsupported test status: {status}')


def _send_bound(
    receipt_path: Path,
    *,
    preview: dict | None = None,
    confirmation: str = 'SEND_VERIFIED_ALPHA_TELEGRAM',
) -> dict:
    preview = preview or verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    return verified_delivery.run_verified_detection(
        send=True,
        confirmation=confirmation,
        run_id=preview['run_id'],
        message_digest=preview['message_digest'],
        receipt_path=str(receipt_path),
    )


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
    _set_alert_source_status(run, 'stale')
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


def _make_price_stale(run, artifacts):
    run['candidates'][0]['price']['date'] = '2026-08-01'
    run['candidates'][0]['replay_context']['price_date'] = '2026-08-01'
    artifacts['feature_vectors.json']['features'][0]['price_date'] = '2026-08-01'
    artifacts['evidence_ledger.json']['items'][0]['feature_vector']['price_date'] = '2026-08-01'


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


def test_delivery_ignores_transient_event_and_message_for_another_symbol(scanner, tmp_path, monkeypatch):
    """A transient 000660 event must not replace the persisted 005930 preview."""
    _, _, result, calls = scanner
    transient = deepcopy(result['events'][0]['candidate'])
    transient.update({'symbol': '000660', 'name': 'SK하이닉스', 'display_name': 'SK하이닉스'})
    result['events'][0].update({
        'event_key': '000660:BUY_CANDIDATE:2026-08-20',
        'candidate': transient,
    })
    result['message'] = '<b>000660 transient candidate</b>'
    posted = []
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: posted.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 12},
    )
    receipt_path = tmp_path / 'receipt.json'
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    delivered = _send_bound(receipt_path, preview=preview)

    assert delivered['status'] == 'delivered'
    assert posted == [EXPECTED_MESSAGE]
    assert calls['commit'] == 1
    _assert_public_result_sanitized(delivered)


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (lambda event: event.__setitem__('run_id', 'other-run'), 'event_run_id_mismatch'),
        (lambda event: event.__setitem__('generated_at', '2026-08-20T00:00:00+00:00'), 'event_generated_at_mismatch'),
        (lambda event: event.__setitem__('event_key', 'wrong:key'), 'event_key_mismatch'),
    ],
)
def test_delivery_ignores_transient_event_metadata_mismatch(scanner, tmp_path, monkeypatch, mutate, expected_code):
    """Transient metadata is not an input to the persisted-run preview or send."""
    _, _, result, calls = scanner
    mutate(result['events'][0])
    posted = []
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: posted.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 13},
    )
    receipt_path = tmp_path / f'{expected_code}.json'
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    delivered = _send_bound(receipt_path, preview=preview)

    assert delivered['status'] == 'delivered'
    assert posted == [EXPECTED_MESSAGE]
    assert calls['commit'] == 1
    _assert_public_result_sanitized(delivered)


def test_delivery_rejects_any_transient_run_difference_from_persisted(scanner, tmp_path, monkeypatch):
    """Checking only ID/count/timestamp leaves unverified candidate fields trusted."""
    _, _, result, calls = scanner
    result['run'] = deepcopy(result['run'])
    result['run']['candidates'][0]['risk_score'] = 1.0
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))

    assert delivered['status'] == 'invalid_run'
    assert delivered['error_code'] == 'run_content_mismatch'
    assert calls['commit'] == 0


def test_delivery_ignores_untrusted_transient_state_path(scanner, tmp_path, monkeypatch):
    """A transient state path cannot redirect the post-delivery scanner state write."""
    _, _, result, calls = scanner
    attacker_path = tmp_path / 'attacker-controlled-state.json'
    receipt_path = tmp_path / 'receipt.json'
    result['state_path'] = str(attacker_path)
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: {'ok': True, 'status': 'delivered', 'message_id': 14},
    )
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    delivered = _send_bound(receipt_path, preview=preview)

    assert delivered['status'] == 'delivered'
    assert calls['commit'] == 1
    assert calls['payloads'][0]['state_path'] == str(verified_delivery.DEFAULT_ALERT_STATE_PATH)
    assert not attacker_path.exists()
    assert receipt_path.exists()


def test_equivalent_state_path_is_canonicalized_before_commit(scanner, tmp_path, monkeypatch):
    """Equivalent spelling may pass, but only the trusted canonical path reaches the commit."""
    _, _, result, calls = scanner
    canonical = Path(CANONICAL_STATE_PATH)
    variant = os.path.join(str(canonical.parent), 'path-segment', '..', canonical.name)
    if os.name == 'nt':
        variant = variant.swapcase()
    result['state_path'] = variant
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: {'ok': True, 'status': 'delivered', 'message_id': 246},
    )

    receipt_path = tmp_path / 'receipt.json'
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    delivered = _send_bound(receipt_path, preview=preview)

    assert delivered['status'] == 'delivered'
    assert calls['commit'] == 1
    assert calls['payloads'][0]['state_path'] == str(verified_delivery.DEFAULT_ALERT_STATE_PATH)


def test_stale_run_with_corrupt_artifact_is_invalid_not_deliverable_hold(scanner, tmp_path, monkeypatch):
    """Freshness must not mask missing proof artifacts behind a sendable hold."""
    run, artifacts, result, calls = scanner
    run['freshness'] = {'status': 'stale'}
    _set_alert_source_status(run, 'stale')
    result.update(_scanner_result(run, blocked=True))
    artifacts['feature_vectors.json'] = None
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))

    assert delivered == {
        'ok': False,
        'status': 'invalid_run',
        'run_id': RUN_ID,
        'error_code': 'feature_vectors_missing',
    }
    assert calls['commit'] == 0


@pytest.mark.parametrize(('freshness', 'alert_blocked'), [('fresh', True), ('stale', False)])
def test_transient_freshness_block_state_cannot_override_persisted_sources(
    scanner, tmp_path, monkeypatch, freshness, alert_blocked,
):
    """Neither a transient false hold nor a transient bypass may override persisted freshness."""
    run, _, result, calls = scanner
    run['freshness'] = {'status': freshness}
    result.update(_scanner_result(run, blocked=alert_blocked))
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    delivered = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))

    assert delivered['status'] == 'preview'
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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    first = _send_bound(receipt_path, preview=preview)
    second = _send_bound(receipt_path, preview=preview)

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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    result = _send_bound(receipt_path, preview=preview)
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
    _set_alert_source_status(run, freshness)
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
    _set_alert_source_status(run, 'stale')
    result.update(_scanner_result(run, blocked=True))
    sent = []
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 55},
    )

    denied = verified_delivery.run_verified_detection(send=True, receipt_path=str(tmp_path / 'receipt.json'))
    receipt_path = tmp_path / 'receipt.json'
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    delivered = _send_bound(receipt_path, preview=preview)

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

    receipt_path = tmp_path / 'receipt.json'
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    result = _send_bound(receipt_path, preview=preview)

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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    first = _send_bound(receipt_path, preview=preview)
    second = _send_bound(receipt_path, preview=preview)

    assert first['status'] == 'delivery_uncertain'
    assert first['sent'] is None
    assert second['status'] == 'delivery_uncertain'
    assert sent == [EXPECTED_MESSAGE]
    _assert_public_result_sanitized(first)
    _assert_public_result_sanitized(second)


def test_same_preview_recovers_matching_uncommitted_event_without_resending(scanner, monkeypatch, tmp_path):
    """The exact preview can recover a delivered event whose state commit initially failed."""
    _, _, _, calls = scanner
    receipt_path = tmp_path / 'receipt.json'
    sent = []
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 88})

    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', lambda payload: (_ for _ in ()).throw(RuntimeError('commit failed')))
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    first = _send_bound(receipt_path, preview=preview)
    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', lambda payload: calls.__setitem__('commit', calls['commit'] + 1) or {'ok': True})
    second = _send_bound(receipt_path, preview=preview)

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
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    workers = [threading.Thread(target=lambda: results.append(_send_bound(receipt_path, preview=preview))) for _ in range(2)]
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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    first = _send_bound(receipt_path, preview=preview)
    result['message'] = '<b>changed candidate</b>'
    second = _send_bound(receipt_path, preview=preview)
    result['message'] = '<b>000660 attacker-controlled candidate</b>'
    third = _send_bound(receipt_path, preview=preview)

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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    first = _send_bound(receipt_path, preview=preview)
    second = _send_bound(receipt_path, preview=preview)

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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    first = _send_bound(receipt_path, preview=preview)
    second = _send_bound(receipt_path, preview=preview)

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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    result = _send_bound(receipt_path, preview=preview)

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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    result = _send_bound(receipt_path, preview=preview)

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

    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    result = _send_bound(receipt_path, preview=preview)

    assert result == {'ok': False, 'status': 'receipt_invalid', 'run_id': RUN_ID, 'error_code': 'receipt_invalid', 'sent': False}
    assert receipt_path.read_text(encoding='utf-8') == contents


def test_send_uses_exact_preview_run_and_digest_without_starting_another_scan(scanner, monkeypatch, tmp_path):
    """Removing the run/digest binding would let confirmation authorize unseen content."""
    _, _, _, calls = scanner
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: {'ok': True, 'status': 'delivered', 'message_id': 501},
    )

    preview = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))
    delivered = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        run_id=preview['run_id'],
        message_digest=preview['message_digest'],
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert preview['status'] == 'preview'
    assert delivered['status'] == 'delivered'
    assert calls['scan'] == 1


def test_send_rejects_preview_digest_mismatch_before_transport(scanner, monkeypatch, tmp_path):
    """Changing scanner state after preview must invalidate the operator's approval."""
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)
    preview = verified_delivery.run_verified_detection(receipt_path=str(tmp_path / 'receipt.json'))

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        run_id=preview['run_id'],
        message_digest='0' * 64,
        receipt_path=str(tmp_path / 'receipt.json'),
    )

    assert result['status'] == 'preview_mismatch'
    assert result['sent'] is False
    assert 'message_digest' not in result


def test_state_change_requires_a_new_preview_to_obtain_the_new_digest(scanner, monkeypatch, tmp_path):
    """A mismatch response cannot substitute for previewing the state-changed message."""
    receipt_path = tmp_path / 'receipt.json'
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)
    first_preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))
    verified_delivery.DEFAULT_ALERT_STATE_PATH.write_text(json.dumps({
        'version': 2,
        'sent_events': {
            '005930:BUY_CANDIDATE:2026-08-20': {'run_id': 'another-run'},
        },
    }), encoding='utf-8')

    mismatch = _send_bound(receipt_path, preview=first_preview)
    fresh_preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))

    assert mismatch['status'] == 'preview_mismatch'
    assert 'message_digest' not in mismatch
    assert fresh_preview['status'] == 'preview'
    assert fresh_preview['message_digest'] != first_preview['message_digest']


def test_cross_run_uncertain_claim_blocks_transport(scanner, monkeypatch, tmp_path):
    """A different run ID cannot make an ambiguous Telegram attempt retryable."""
    receipt_path = tmp_path / 'receipt.json'
    pending = {
        'run_id': 'older-run',
        'message_sha256': 'a' * 64,
        'status': 'uncertain',
        'delivered': False,
        'message_id': None,
        'candidate_count': 1,
        'event_count': 1,
        'symbols': ['005930'],
        'event_keys': ['005930:BUY_CANDIDATE:2026-08-20'],
        'state_committed': False,
    }
    receipt_path.write_text(json.dumps({'schema_version': 2, 'deliveries': [pending]}), encoding='utf-8')
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        run_id=preview['run_id'],
        message_digest=preview['message_digest'],
        receipt_path=str(receipt_path),
    )

    assert result['status'] == 'delivery_uncertain'
    assert result['sent'] is None


def test_cross_run_delivered_event_overlap_is_refused(scanner, monkeypatch, tmp_path):
    """Changing only a run ID must not deliver an already-delivered event twice."""
    receipt_path = tmp_path / 'receipt.json'
    delivered = {
        'run_id': 'older-run',
        'message_sha256': 'b' * 64,
        'status': 'delivered',
        'delivered': True,
        'message_id': 700,
        'candidate_count': 1,
        'event_count': 1,
        'symbols': ['005930'],
        'event_keys': ['005930:BUY_CANDIDATE:2026-08-20'],
        'state_committed': True,
    }
    receipt_path.write_text(json.dumps({'schema_version': 2, 'deliveries': [delivered]}), encoding='utf-8')
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        run_id=preview['run_id'],
        message_digest=preview['message_digest'],
        receipt_path=str(receipt_path),
    )

    assert result['status'] == 'duplicate_refused'
    assert result['sent'] is False


def test_state_commit_receipt_split_brain_is_repaired_from_canonical_state(scanner, monkeypatch, tmp_path):
    """A failed post-commit ledger write must be recoverable without another send or state commit."""
    receipt_path = tmp_path / 'receipt.json'
    delivered = {
        'run_id': RUN_ID,
        'message_sha256': hashlib.sha256(EXPECTED_MESSAGE.encode('utf-8')).hexdigest(),
        'status': 'delivered',
        'delivered': True,
        'message_id': 701,
        'candidate_count': 1,
        'event_count': 1,
        'symbols': ['005930'],
        'event_keys': ['005930:BUY_CANDIDATE:2026-08-20'],
        'state_committed': False,
    }
    receipt_path.write_text(json.dumps({'schema_version': 2, 'deliveries': [delivered]}), encoding='utf-8')
    monkeypatch.setattr(
        verified_delivery,
        '_read_canonical_alert_state',
        lambda: {'version': 2, 'sent_events': {
            '005930:BUY_CANDIDATE:2026-08-20': {'run_id': RUN_ID},
        }},
        raising=False,
    )
    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', pytest.fail)
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        run_id=RUN_ID,
        message_digest=delivered['message_sha256'],
        receipt_path=str(receipt_path),
    )

    repaired = json.loads(receipt_path.read_text(encoding='utf-8'))['deliveries'][0]
    assert result['status'] == 'delivered_recovered'
    assert repaired['state_committed'] is True


def test_recovery_reports_the_recovered_receipt_identity_not_requested_run(scanner, monkeypatch, tmp_path):
    """Recovering old run A while run B is requested must not mislabel the receipt as B."""
    receipt_path = tmp_path / 'receipt.json'
    older_digest = 'c' * 64
    delivered = {
        'run_id': 'older-run',
        'message_sha256': older_digest,
        'status': 'delivered',
        'delivered': True,
        'message_id': 704,
        'candidate_count': 1,
        'event_count': 1,
        'symbols': ['005930'],
        'event_keys': ['005930:BUY_CANDIDATE:2026-08-20'],
        'state_committed': False,
    }
    receipt_path.write_text(json.dumps({'schema_version': 2, 'deliveries': [delivered]}), encoding='utf-8')
    verified_delivery.DEFAULT_ALERT_STATE_PATH.write_text(json.dumps({
        'version': 2,
        'sent_events': {
            '005930:BUY_CANDIDATE:2026-08-20': {'run_id': 'older-run'},
        },
    }), encoding='utf-8')
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        run_id=RUN_ID,
        message_digest=hashlib.sha256(EXPECTED_MESSAGE.encode('utf-8')).hexdigest(),
        receipt_path=str(receipt_path),
    )

    assert result['status'] == 'delivered_recovered'
    assert result['run_id'] == 'older-run'
    assert 'message_digest' not in result
    assert result['recovered_count'] == 1


def test_third_receipt_write_failure_recovers_from_state_written_by_commit(scanner, monkeypatch, tmp_path):
    """The real claim/deliver/commit sequence must heal when only ledger write three fails."""
    receipt_path = tmp_path / 'receipt.json'
    state_path = verified_delivery.DEFAULT_ALERT_STATE_PATH
    real_write = verified_delivery.write_json_atomic
    writes = []

    def fail_third(path, payload, **kwargs):
        writes.append(deepcopy(payload))
        if len(writes) == 3:
            raise OSError('disk full after scanner state commit')
        return real_write(path, payload, **kwargs)

    commits = []

    def commit(payload):
        commits.append(deepcopy(payload))
        state_path.write_text(json.dumps({
            'version': 2,
            'sent_events': {
                event['event_key']: {'run_id': payload['run']['id']}
                for event in payload['events']
            },
        }), encoding='utf-8')
        return {'ok': True}

    sent = []
    monkeypatch.setattr(verified_delivery, 'write_json_atomic', fail_third)
    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', commit)
    monkeypatch.setattr(
        verified_delivery,
        'post_private_telegram',
        lambda message: sent.append(message) or {'ok': True, 'status': 'delivered', 'message_id': 702},
    )
    preview = verified_delivery.run_verified_detection(receipt_path=str(receipt_path))

    first = _send_bound(receipt_path, preview=preview)
    monkeypatch.setattr(verified_delivery, 'write_json_atomic', real_write)
    second = _send_bound(receipt_path, preview=preview)

    repaired = json.loads(receipt_path.read_text(encoding='utf-8'))['deliveries'][0]
    assert first['status'] == 'state_commit_failed'
    assert second['status'] == 'delivered_recovered'
    assert sent == [EXPECTED_MESSAGE]
    assert len(commits) == 1
    assert repaired['state_committed'] is True


def test_split_brain_state_with_wrong_run_association_is_not_repaired(scanner, monkeypatch, tmp_path):
    """A matching event key from another run cannot prove this receipt's state commit."""
    receipt_path = tmp_path / 'receipt.json'
    digest = hashlib.sha256(EXPECTED_MESSAGE.encode('utf-8')).hexdigest()
    delivered = {
        'run_id': RUN_ID,
        'message_sha256': digest,
        'status': 'delivered',
        'delivered': True,
        'message_id': 703,
        'candidate_count': 1,
        'event_count': 1,
        'symbols': ['005930'],
        'event_keys': ['005930:BUY_CANDIDATE:2026-08-20'],
        'state_committed': False,
    }
    receipt_path.write_text(json.dumps({'schema_version': 2, 'deliveries': [delivered]}), encoding='utf-8')
    verified_delivery.DEFAULT_ALERT_STATE_PATH.write_text(json.dumps({
        'version': 2,
        'sent_events': {
            '005930:BUY_CANDIDATE:2026-08-20': {'run_id': 'different-run'},
        },
    }), encoding='utf-8')
    monkeypatch.setattr(verified_delivery, 'post_private_telegram', pytest.fail)
    monkeypatch.setattr(verified_delivery.alpha_scanner, 'commit_scanner_alert_events', pytest.fail)

    result = verified_delivery.run_verified_detection(
        send=True,
        confirmation='SEND_VERIFIED_ALPHA_TELEGRAM',
        run_id=RUN_ID,
        message_digest=digest,
        receipt_path=str(receipt_path),
    )

    unchanged = json.loads(receipt_path.read_text(encoding='utf-8'))['deliveries'][0]
    assert result['status'] in {'preview_mismatch', 'state_recovery_required'}
    assert unchanged['state_committed'] is False


def test_validation_uses_alert_required_sources_not_aggregate_optional_freshness(scanner):
    """An optional stale source must not override fresh alert-required provenance."""
    run, _, _, _ = scanner
    run['freshness'] = {'status': 'stale'}
    run['source_files'] = [
        {
            'file': 'data/daily_prices.csv', 'exists': True, 'generated_at': None,
            'modified_at': '2026-08-20T00:00:00+00:00', 'freshness': 'fresh',
            'age_days': 1, 'max_age_days': 5, 'role': 'price_history',
            'required': True, 'alert_required': True,
        },
        {
            'file': 'data/ticker_to_yahoo_map.csv', 'exists': True, 'generated_at': None,
            'modified_at': '2026-08-01T00:00:00+00:00', 'freshness': 'fresh',
            'age_days': 20, 'max_age_days': 180, 'role': 'symbol_map',
            'required': True, 'alert_required': True,
        },
        {
            'file': 'data/screener_leading_latest.json', 'exists': True,
            'generated_at': '2026-08-21T08:59:00',
            'modified_at': '2026-08-20T23:59:00+00:00', 'freshness': 'fresh',
            'age_days': 0, 'max_age_days': 7, 'role': 'leading_screener',
            'required': True, 'alert_required': True,
        },
        {
            'file': 'data/vcp_kr_latest.json', 'exists': True,
            'generated_at': '2026-01-01T00:00:00+00:00',
            'modified_at': '2026-01-01T00:00:00+00:00', 'freshness': 'stale',
            'age_days': 200, 'max_age_days': 7, 'role': 'vcp_quality',
            'required': True, 'alert_required': False,
        },
    ]
    run['candidates'][0]['replay_context'] = {
        'price_date': '2026-08-20',
        'generated_at': GENERATED_AT,
        'data_sources': ['daily_prices.csv', 'screener_leading_latest.json'],
        'lookahead_safe': True,
    }
    for item in run['candidates'][0]['evidence']:
        item['confidence'] = 0.75

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation['ok'] is True


def test_validation_blocks_independently_stale_alert_required_source(scanner):
    """A forged aggregate `fresh` label cannot hide old price provenance."""
    run, _, _, _ = scanner
    run['source_files'] = [
        {
            'file': f'data/{name}', 'exists': True, 'generated_at': None,
            'modified_at': '2026-01-01T00:00:00+00:00' if name == 'daily_prices.csv' else '2026-08-20T00:00:00+00:00',
            'freshness': 'fresh', 'age_days': 0, 'max_age_days': policy['max_age_days'],
            'role': policy['role'], 'required': policy['required'], 'alert_required': True,
        }
        for name, policy in verified_delivery.alpha_scanner.SOURCE_FILE_POLICIES.items()
        if policy.get('alert_required')
    ]

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation['ok'] is False
    assert validation['error_code'] == 'blocked_freshness'


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (
            lambda run, artifacts: run['candidates'][0].__setitem__(
                'replay_context',
                {'price_date': '2026-08-20', 'generated_at': GENERATED_AT,
                 'data_sources': ['daily_prices.csv'], 'lookahead_safe': False},
            ),
            'candidate_not_lookahead_safe',
        ),
        (_make_price_stale, 'blocked_freshness'),
        (
            lambda run, artifacts: run['candidates'][0]['evidence'][0].pop('confidence', None),
            'invalid_candidate_evidence',
        ),
        (
            lambda run, artifacts: artifacts['evidence_ledger.json']['items'][0]['feature_vector'].__setitem__(
                'strategy_tags', ['tampered']
            ),
            'evidence_feature_vector_mismatch',
        ),
    ],
)
def test_validation_rejects_lookahead_stale_price_weak_evidence_and_artifact_drift(
    scanner, mutate, expected_code,
):
    """Removing any proof binding would allow stale or internally inconsistent evidence."""
    run, artifacts, _, _ = scanner
    mutate(run, artifacts)

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation['ok'] is False
    assert validation['error_code'] == expected_code


def test_private_telegram_treats_5xx_rejection_as_uncertain(monkeypatch):
    """A server error cannot prove that Telegram did not accept the message."""

    class Response:
        status_code = 500

        @staticmethod
        def json():
            return {'ok': False, 'description': 'internal server error'}

    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'personal-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '12345')

    result = verified_delivery.post_private_telegram('verified', request_post=lambda url, **kwargs: Response())

    assert result == {'ok': False, 'status': 'rejected', 'error_code': 'telegram_response_rejected'}


def test_cli_send_requires_preview_run_id_and_digest(monkeypatch):
    """The CLI must reject a send that is not bound to one printed preview."""
    script_path = Path(__file__).parents[1] / 'scripts' / 'run_verified_alpha_telegram.py'
    spec = importlib.util.spec_from_file_location('verified_cli_binding', script_path)
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, '_load_dotenv', lambda: None)
    monkeypatch.setattr(cli, 'run_verified_detection', pytest.fail)

    with pytest.raises(SystemExit) as exc:
        cli.main(['--send', '--confirm', 'SEND_VERIFIED_ALPHA_TELEGRAM'])

    assert exc.value.code == 2


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (
            lambda run, artifacts: run['candidates'][0].__setitem__(
                'generated_at', '2026-08-21T00:01:00+00:00'
            ),
            'candidate_generated_at_mismatch',
        ),
        (
            lambda run, artifacts: run['candidates'][0]['replay_context'].__setitem__(
                'generated_at', '2026-08-21T00:01:00+00:00'
            ),
            'replay_generated_at_mismatch',
        ),
        (
            lambda run, artifacts: run['candidates'][0]['replay_context'].__setitem__(
                'price_date', '2026-08-19'
            ),
            'replay_price_date_mismatch',
        ),
    ],
)
def test_validation_rejects_candidate_and_replay_time_mismatch(scanner, mutate, expected_code):
    """Candidate replay timestamps must describe the same bounded observation window as the run."""
    run, artifacts, _, _ = scanner
    mutate(run, artifacts)

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation['error_code'] == expected_code


def test_validation_rejects_future_run_generation(scanner, monkeypatch):
    """A run timestamp beyond the bounded clock skew cannot authorize a send."""
    monkeypatch.setattr(
        verified_delivery,
        '_utc_now',
        lambda: verified_delivery.datetime.fromisoformat('2026-08-20T23:00:00+00:00'),
    )

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation['error_code'] == 'run_generated_in_future'


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (
            lambda source: source.update({
                'exists': False,
                'generated_at': None,
                'modified_at': None,
                'freshness': 'unknown',
            }),
            'blocked_freshness',
        ),
        (
            lambda source: source.update({
                'generated_at': '2026-08-21T09:30:00',
                'modified_at': '2026-08-21T00:30:00+00:00',
            }),
            'source_observation_after_run',
        ),
    ],
)
def test_validation_blocks_missing_and_rejects_future_alert_provenance(scanner, mutate, expected_code):
    """Alert-required provenance must exist and must not post-date the persisted run."""
    run, _, _, _ = scanner
    mutate(run['source_files'][0])

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation['error_code'] == expected_code


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (
            lambda candidate: (
                candidate.__setitem__('evidence', [{
                    'source': 'news_theme_social_latest.json',
                    'field': 'buzz',
                    'score': 5.0,
                    'confidence': 0.9,
                }]),
                candidate['replay_context'].__setitem__('data_sources', ['news_theme_social_latest.json']),
            ),
            'missing_strong_evidence',
        ),
        (
            lambda candidate: candidate['analysis_profile']['evidence_quality'].__setitem__('grade', 'weak'),
            'weak_evidence_quality',
        ),
        (
            lambda candidate: candidate['evidence'][0].__setitem__('confidence', 0.2),
            'missing_strong_evidence',
        ),
    ],
)
def test_validation_rejects_social_only_weak_or_low_confidence_evidence(scanner, mutate, expected_code):
    """Weak/social support cannot become a standalone verified directional signal."""
    run, _, _, _ = scanner
    mutate(run['candidates'][0])

    validation = verified_delivery.validate_scanner_run(RUN_ID)

    assert validation['error_code'] == expected_code


def test_concurrent_different_run_ids_with_same_event_key_send_once(scanner, monkeypatch, tmp_path):
    """The receipt lock must dedupe an event even when simultaneous previews have different run IDs."""
    run_one, artifacts_one, _, calls = scanner
    run_two = deepcopy(run_one)
    run_two['id'] = 'scanner-verified-002'
    artifacts_two = deepcopy(artifacts_one)
    artifacts_two['feature_vectors.json']['run_id'] = run_two['id']
    artifacts_two['evidence_ledger.json']['run_id'] = run_two['id']
    runs = {RUN_ID: run_one, run_two['id']: run_two}
    artifacts = {RUN_ID: artifacts_one, run_two['id']: artifacts_two}
    scan_results = [_scanner_result(run_one), _scanner_result(run_two)]

    monkeypatch.setattr(
        verified_delivery.alpha_scanner,
        'run_scanner_alert_check',
        lambda payload, **kwargs: scan_results.pop(0),
    )
    monkeypatch.setattr(
        verified_delivery.alpha_scanner,
        'read_scanner_run',
        lambda run_id: deepcopy(runs.get(run_id)),
    )
    monkeypatch.setattr(
        verified_delivery.alpha_scanner,
        'read_scanner_run_artifact',
        lambda run_id, name: deepcopy((artifacts.get(run_id) or {}).get(name)),
    )
    sent = []
    sent_lock = threading.Lock()

    def post(message):
        with sent_lock:
            sent.append(message)
        time.sleep(0.05)
        return {'ok': True, 'status': 'delivered', 'message_id': len(sent)}

    monkeypatch.setattr(verified_delivery, 'post_private_telegram', post)
    receipt_path = tmp_path / 'receipt.json'
    previews = [
        verified_delivery.run_verified_detection(receipt_path=str(receipt_path)),
        verified_delivery.run_verified_detection(receipt_path=str(receipt_path)),
    ]
    results = []
    workers = [
        threading.Thread(target=lambda item=item: results.append(_send_bound(receipt_path, preview=item)))
        for item in previews
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(sent) == 1
    assert sorted(result['status'] for result in results) == ['delivered', 'duplicate_refused']
    assert calls['commit'] == 1


def test_cli_send_omits_telegram_message_id_and_exposes_only_verified_boolean(monkeypatch, capsys):
    """CLI output must not expose raw Telegram receipt identifiers."""
    script_path = Path(__file__).parents[1] / 'scripts' / 'run_verified_alpha_telegram.py'
    spec = importlib.util.spec_from_file_location('verified_cli_receipt_sanitized', script_path)
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, '_load_dotenv', lambda: None)
    monkeypatch.setattr(
        cli,
        'run_verified_detection',
        lambda **kwargs: {
            'ok': True,
            'status': 'delivered',
            'sent': True,
            'message_id': 9988,
            'message': '<b>private</b>',
        },
    )

    code = cli.main([
        '--send',
        '--confirm', 'SEND_VERIFIED_ALPHA_TELEGRAM',
        '--run-id', RUN_ID,
        '--message-digest', 'a' * 64,
    ])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output['delivery_verified'] is True
    assert 'message_id' not in output
    assert 'message' not in output
