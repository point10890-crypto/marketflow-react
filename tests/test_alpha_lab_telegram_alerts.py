"""AlphaLab private delivery: real sealed artifacts, fake Telegram transport only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import hashlib
import html
import importlib
import importlib.util
import json
import re
import threading

import pytest
import requests

from app.services.mirofish.alpha_lab import opportunity_store, store

NOW = '2026-10-09T02:00:00Z'
ORIGIN = '2026-10-08T07:00:00Z'
SESSION = '2026-10-08'
CHAT = 11223344
BOT = 99887766
TOKEN = '123456789:' + 'x' * 35


def module():
    name = 'app.services.mirofish.alpha_lab.telegram_alerts'
    assert importlib.util.find_spec(name), 'AlphaLab private Telegram delivery is missing'
    return importlib.import_module(name)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def board(fingerprint='a' * 64):
    rows = []
    for rank, (symbol, name) in enumerate((('196170', '알테오젠'), ('005930', '삼성전자'), ('000660', 'SK하이닉스')), 1):
        rows.append(dict(symbol=symbol, name=name, market='KR', rank=rank, strategy_id='momentum',
            decision_id='', opportunity_id='', input_fingerprint=fingerprint, source_audit_hash='b' * 64,
            action='data_check', label='데이터 확인', why_stock='저장된 과거 분석', why_now='시세 확인 대기',
            next_action='공식 거래일 확인', quote_session=SESSION, source_at=ORIGIN, current_price=None,
            quote_at=None, fetched_at=None, quote_source=None, valid_until=None, reference_weight=.05,
            plan=dict(basis='last_closed_price_reference', entry_low=100., entry_high=102.,
                stop_price=96., target_price=108., horizon_sessions=10),
            ranking=dict(stress_mean_net_return=.02, standard_error=.001, conservative_score=.01804,
                correlation_penalty=0., score=.01804, calibration_samples=40, confirmation_samples=20),
            kelly=dict(raw_fraction=2., fraction=.25, cap=.05, account_risk_cap=.01),
            audit=dict(status='passed', reasons=[], independent_validation=False), reasons=[]))
    value = dict(schema_version=1, policy_version='profit-opportunity-v1', decision_id='',
        input_fingerprint=fingerprint, source_audit_hash='b' * 64, generated_at=ORIGIN, origin_at=ORIGIN,
        latest_session=SESSION, entry_session=None, valid_until=None, status='held', research_only=True,
        live_orders=False, coverage=dict(inspected=10, eligible=4, selected=3), candidates=rows,
        alternatives=[], stages=[], reasons=['entry_window_unavailable'])
    rebind(value)
    return value


def rebind(value):
    keys = ('symbol', 'strategy_id', 'rank', 'reference_weight', 'plan', 'ranking', 'kelly')
    value['decision_id'] = digest(dict(policy_version=value['policy_version'],
        input_fingerprint=value['input_fingerprint'], source_audit_hash=value['source_audit_hash'],
        latest_session=value['latest_session'], candidates=[{k: row[k] for k in keys} for row in value['candidates']]))
    for row in value['candidates']:
        row.update(decision_id=value['decision_id'], input_fingerprint=value['input_fingerprint'],
            source_audit_hash=value['source_audit_hash'])
        row['opportunity_id'] = digest(dict(decision_id=value['decision_id'], symbol=row['symbol'],
            strategy_id=row['strategy_id']))


def save(root, value=None, *, state='held', register=True):
    value = value or board()
    if register:
        opportunity_store.register_board(root, value)
    report = dict(schema_version=1, mode='research', input_fingerprint=value['input_fingerprint'],
        latest_session=value['latest_session'], opportunity_scan=dict(audit_hash=value['source_audit_hash']),
        opportunity_board=value, decision_at=value['generated_at'], provenance=dict(captured_at=ORIGIN))
    store.publish(root, report, now=ORIGIN, held=state == 'held')
    if state not in ('held', 'ready'):
        status = store.read_status(root, now=NOW)
        store._save(root, dict(status, state=state))
    return value


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return deepcopy(self.payload)


class Telegram:
    def __init__(self, now=NOW):
        self.gets = []
        self.posts = []
        self.now = now
        self.me = dict(id=BOT, is_bot=True, username='bitman75_bot', first_name='test')
        self.chat = dict(id=CHAT, type='private', first_name='operator')
        self.post_result = None
        self.before_send = None

    def get(self, url, **kwargs):
        method = url.rsplit('/', 1)[-1]
        assert method in ('getMe', 'getChat')
        self.gets.append(method)
        if method == 'getChat':
            assert kwargs['params'] == {'chat_id': CHAT}
        return Response(dict(ok=True, result=self.me if method == 'getMe' else self.chat))

    def post(self, url, **kwargs):
        assert url.endswith('/sendMessage')
        data = kwargs['json']
        assert data['chat_id'] == CHAT and data['parse_mode'] == 'HTML'
        assert data['disable_web_page_preview'] is True
        if self.before_send:
            self.before_send()
        self.posts.append(deepcopy(data))
        result = dict(message_id=7733, date=int(datetime.fromisoformat(self.now.replace('Z', '+00:00')).timestamp()),
            chat=self.chat, **{'from': self.me}, text=html.unescape(re.sub(r'<[^>]+>', '', data['text'])))
        response = Response(dict(ok=True, result=result))
        if callable(self.post_result):
            return self.post_result(response)
        if isinstance(self.post_result, Exception):
            raise self.post_result
        return self.post_result or response


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    for key in ('ALPHA_LAB_TELEGRAM_ENABLED', 'ALPHA_LAB_TELEGRAM_BOT_TOKEN_KEY', 'ALPHA_LAB_TELEGRAM_CHAT_ID_KEY'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', TOKEN)
    monkeypatch.setenv('TELEGRAM_CHAT_ID', str(CHAT))
    monkeypatch.setenv('TELEGRAM_CHANNEL_BOT_TOKEN', '654321:' + 'y' * 35)
    # A broad test run must never fall through to a real transport.
    monkeypatch.setattr(requests, 'get', lambda *a, **k: pytest.fail('unexpected live Telegram GET'))
    monkeypatch.setattr(requests, 'post', lambda *a, **k: pytest.fail('unexpected live Telegram POST'))


def deliver(root, transport, **kwargs):
    return module().deliver_latest(root, now=kwargs.pop('now', NOW), enabled=kwargs.pop('enabled', True),
        request_get=transport.get, request_post=transport.post, **kwargs)


def test_preview_is_read_only_sanitized_and_held_oct8_is_sendable_on_oct9(tmp_path):
    value = save(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = module().preview_latest(tmp_path, now=NOW)
    assert result['status'] == 'preview' and result['sendable'] is True
    assert result['decision_id'] == value['decision_id'] and result['source_session'] == SESSION
    assert result['candidate_count'] == 3 and re.fullmatch('[0-9a-f]{64}', result['digest'])
    assert set(result) == {'status', 'decision_id', 'digest', 'candidate_count', 'source_session', 'sendable'}
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert module().preview_latest(tmp_path, now='2026-10-10T02:00:00Z')['digest'] == result['digest']


def test_private_receipt_success_and_repeat_performs_no_telegram_calls(tmp_path):
    value = save(tmp_path); transport = Telegram()
    first = deliver(tmp_path, transport)
    assert first['status'] == 'delivered' and first['decision_id'] == value['decision_id']
    assert transport.gets == ['getMe', 'getChat'] and len(transport.posts) == 1
    second = deliver(tmp_path, transport)
    assert second['status'] == 'already_delivered'
    assert len(transport.posts) == 1 and len(transport.gets) == 2
    ledger = (tmp_path / 'notifications' / 'telegram.json').read_text(encoding='utf-8')
    for secret in (TOKEN, str(CHAT), str(BOT), '7733', '알테오젠'):
        assert secret not in ledger and secret not in json.dumps(first, ensure_ascii=False)


def test_pending_is_durable_before_send_and_failed_pending_write_prevents_send(tmp_path, monkeypatch):
    save(tmp_path); transport = Telegram(); mod = module()
    def before():
        raw = store._read(tmp_path / 'notifications' / 'telegram.json')
        assert raw['sha256'] == store._hash(raw['data'])
        assert raw['data']['entries'][0]['state'] == 'pending'
    transport.before_send = before
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    root = tmp_path / 'other'; save(root)
    write = store._write
    def fail(path, data):
        if path.parent.name == 'notifications':
            raise OSError('synthetic disk failure')
        return write(path, data)
    monkeypatch.setattr(store, '_write', fail)
    other = Telegram()
    assert deliver(root, other)['status'] == 'ledger_unavailable'
    assert not other.posts


def test_concurrent_callers_send_only_once(tmp_path):
    save(tmp_path); transport = Telegram(); barrier = threading.Barrier(2)
    def attempt():
        barrier.wait(timeout=5)
        return deliver(tmp_path, transport)['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ['already_delivered', 'delivered']
    assert len(transport.posts) == 1 and len(transport.gets) == 2


@pytest.mark.parametrize('failure', ['timeout', 'server', 'malformed_json', 'malformed_200',
    'invalid_message_id', 'wrong_chat', 'group_chat', 'wrong_sender', 'wrong_text', 'future_receipt'])
def test_uncertain_send_blocks_all_automatic_retries(tmp_path, failure):
    save(tmp_path); transport = Telegram()
    if failure == 'timeout': transport.post_result = requests.Timeout('synthetic timeout')
    elif failure == 'server': transport.post_result = Response(dict(ok=False), 503)
    elif failure == 'malformed_json': transport.post_result = Response(ValueError('synthetic JSON error'))
    elif failure == 'malformed_200': transport.post_result = Response(dict(ok=True, result=[]))
    else:
        def corrupt(response):
            row = response.payload['result']
            if failure == 'invalid_message_id': row['message_id'] = True
            elif failure == 'wrong_chat': row['chat']['id'] = CHAT + 1
            elif failure == 'group_chat': row['chat']['type'] = 'group'
            elif failure == 'wrong_sender': row['from']['username'] = 'another_bot'
            elif failure == 'wrong_text': row['text'] = 'different message'
            elif failure == 'future_receipt': row['date'] += 3600
            return response
        transport.post_result = corrupt
    assert deliver(tmp_path, transport)['status'] == 'uncertain'
    transport.post_result = None
    assert deliver(tmp_path, transport)['status'] == 'uncertain'
    assert len(transport.posts) == 1 and len(transport.gets) == 2


@pytest.mark.parametrize('code', [401, 403])
def test_explicit_permission_rejection_requires_user_action_and_never_retries(tmp_path, code):
    save(tmp_path); transport = Telegram()
    transport.post_result = Response(dict(ok=False, error_code=code, description='synthetic rejection'), code)
    assert deliver(tmp_path, transport)['status'] == 'action_required'
    transport.post_result = None
    assert deliver(tmp_path, transport)['status'] == 'action_required'
    assert len(transport.posts) == 1 and len(transport.gets) == 2


def test_rate_limit_retries_only_after_delay_and_attempt_budget(tmp_path):
    save(tmp_path); transport = Telegram()
    transport.post_result = Response(dict(ok=False, error_code=429, parameters=dict(retry_after=60)), 429)
    assert deliver(tmp_path, transport)['status'] == 'retry_deferred'
    assert deliver(tmp_path, transport, now='2026-10-09T02:00:59Z')['status'] == 'retry_deferred'
    assert len(transport.posts) == 1 and len(transport.gets) == 2
    assert deliver(tmp_path, transport, now='2026-10-09T02:01:00Z')['status'] == 'retry_deferred'
    assert deliver(tmp_path, transport, now='2026-10-09T02:02:00Z')['status'] == 'retry_exhausted'
    assert deliver(tmp_path, transport, now='2026-10-09T02:03:00Z')['status'] == 'retry_exhausted'
    assert len(transport.posts) == 3 and len(transport.gets) == 6


def test_rate_limit_can_recover_to_verified_delivery(tmp_path):
    save(tmp_path); transport = Telegram()
    transport.post_result = Response(dict(ok=False, error_code=429, parameters=dict(retry_after=5)), 429)
    assert deliver(tmp_path, transport)['status'] == 'retry_deferred'
    transport.post_result = None; transport.now = '2026-10-09T02:00:05Z'
    assert deliver(tmp_path, transport, now=transport.now)['status'] == 'delivered'
    assert len(transport.posts) == 2


@pytest.mark.parametrize('mutation', ['wrong_bot', 'human_bot', 'group', 'channel', 'wrong_private_id'])
def test_identity_preflight_blocks_send_and_is_recoverable(tmp_path, mutation):
    save(tmp_path); transport = Telegram()
    if mutation == 'wrong_bot': transport.me['username'] = 'wrong_bot'
    elif mutation == 'human_bot': transport.me['is_bot'] = False
    elif mutation in ('group', 'channel'): transport.chat['type'] = mutation
    else: transport.chat['id'] = CHAT + 1
    result = deliver(tmp_path, transport)
    assert result['status'] in ('bot_identity_failed', 'private_chat_failed')
    assert not transport.posts
    fixed = Telegram()
    assert deliver(tmp_path, fixed)['status'] == 'delivered'


def test_disabled_has_no_network_or_notification_files_and_explicit_enable_sends(tmp_path, monkeypatch):
    save(tmp_path); transport = Telegram()
    assert deliver(tmp_path, transport, enabled=None)['status'] == 'disabled'
    assert not transport.gets and not transport.posts and not (tmp_path / 'notifications').exists()
    monkeypatch.setenv('ALPHA_LAB_TELEGRAM_ENABLED', 'true')
    assert deliver(tmp_path, transport, enabled=None)['status'] == 'delivered'


@pytest.mark.parametrize('key,value', [('TELEGRAM_CHAT_ID', '-12'), ('TELEGRAM_CHAT_ID', 'bad'),
    ('TELEGRAM_BOT_TOKEN', ''), ('ALPHA_LAB_TELEGRAM_BOT_TOKEN_KEY', 'OTHER_PROJECT_TOKEN'),
    ('ALPHA_LAB_TELEGRAM_CHAT_ID_KEY', 'TELEGRAM_CHANNEL_ID')])
def test_invalid_or_cross_project_config_blocks_network_and_can_recover(tmp_path, monkeypatch, key, value):
    save(tmp_path); transport = Telegram()
    monkeypatch.setenv(key, value)
    assert deliver(tmp_path, transport)['status'] == 'not_configured'
    assert not transport.posts and not transport.gets
    monkeypatch.setenv(key, str(CHAT) if key == 'TELEGRAM_CHAT_ID' else TOKEN if key == 'TELEGRAM_BOT_TOKEN'
        else 'TELEGRAM_BOT_TOKEN' if key == 'ALPHA_LAB_TELEGRAM_BOT_TOKEN_KEY' else 'TELEGRAM_CHAT_ID')
    assert deliver(tmp_path, transport)['status'] == 'delivered'


def test_only_allowed_alternative_token_alias_is_used_without_environment_mutation(tmp_path, monkeypatch):
    save(tmp_path); transport = Telegram()
    monkeypatch.setenv('ALPHA_LAB_TELEGRAM_BOT_TOKEN_KEY', 'TELEGRAM_CHANNEL_BOT_TOKEN')
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN')
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    import os
    assert 'TELEGRAM_BOT_TOKEN' not in os.environ


def test_fresh_decision_with_same_candidates_sends_new_event(tmp_path):
    first = save(tmp_path); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    second = save(tmp_path, board('c' * 64))
    assert first['decision_id'] != second['decision_id']
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    assert len(transport.posts) == 2


def test_message_escapes_names_and_uses_only_frozen_reference_prices(tmp_path):
    value = board(); value['candidates'][0]['name'] = '<Alpha & "KR">' + '😀' * 80
    value['candidates'][0]['current_price'] = 777777.
    save(tmp_path, value); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    message = transport.posts[0]['text']
    assert '&lt;Alpha &amp;' in message and '<Alpha' not in message
    assert len(message.encode('utf-16-le')) // 2 < 3900
    for fragment in ('196170', '005930', '000660', '100', '102', '96', '108', '10', '5.00%', SESSION,
        'held', 'stale', '실시간', '연구', '주문', 'https://bit-man.net/dashboard/ai-bain/chart-predict'):
        assert fragment in message
    assert '777777' not in message and 'BUY' not in message


@pytest.mark.parametrize('mutation', ['decision_id', 'fingerprint', 'audit', 'rank', 'symbol', 'weight',
    'plan', 'huge_price', 'research', 'live', 'session', 'board_state', 'duplicate', 'missing_registered',
    'boolean_schema', 'fractional_horizon'])
def test_malformed_or_unbound_saved_decisions_never_send(tmp_path, mutation):
    value = board()
    if mutation == 'decision_id': value['decision_id'] = 'd' * 64
    elif mutation == 'fingerprint': value['candidates'][0]['input_fingerprint'] = 'e' * 64
    elif mutation == 'audit': value['source_audit_hash'] = 'no-hash'
    elif mutation == 'rank': value['candidates'][0]['rank'] = True; rebind(value)
    elif mutation == 'symbol': value['candidates'][0]['symbol'] = '000000'; rebind(value)
    elif mutation == 'weight': value['candidates'][0]['reference_weight'] = .5; rebind(value)
    elif mutation == 'plan': value['candidates'][0]['plan']['stop_price'] = 103.; rebind(value)
    elif mutation == 'huge_price':
        value['candidates'][0]['plan'].update(entry_low=1e100, entry_high=1.02e100, stop_price=.96e100, target_price=1.08e100)
        rebind(value)
    elif mutation == 'research': value['research_only'] = False
    elif mutation == 'live': value['live_orders'] = True
    elif mutation == 'session': value['candidates'][0]['quote_session'] = '2026-10-07'
    elif mutation == 'board_state': value['status'] = 'running'
    elif mutation == 'duplicate': value['candidates'][1]['symbol'] = value['candidates'][0]['symbol']; rebind(value)
    elif mutation == 'boolean_schema': value['schema_version'] = True
    elif mutation == 'fractional_horizon': value['candidates'][0]['plan']['horizon_sessions'] = 10.; rebind(value)
    save(tmp_path, value, register=False)
    if mutation not in ('missing_registered', 'audit', 'duplicate'):
        opportunity_store.register_board(tmp_path, value)
    transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'invalid_saved_decision'
    assert not transport.gets and not transport.posts


@pytest.mark.parametrize('state', ['running', 'failed', 'missing'])
def test_nonfinished_status_does_not_send_retained_previous_report(tmp_path, state):
    save(tmp_path, state=state); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'invalid_saved_decision'
    assert not transport.gets and not transport.posts


@pytest.mark.parametrize('now,status', [('2026-10-08T06:59:00Z', 'future_decision'),
    ('2026-10-16T07:00:01Z', 'stale_decision')])
def test_future_or_more_than_seven_days_old_frozen_decision_is_rejected(tmp_path, now, status):
    save(tmp_path); transport = Telegram()
    assert deliver(tmp_path, transport, now=now)['status'] == status
    assert not transport.gets and not transport.posts


def test_current_board_requires_exact_registered_plan_and_source_binding(tmp_path):
    value = save(tmp_path)
    changed = deepcopy(value); changed['candidates'][0]['plan']['entry_high'] = 103.
    save(tmp_path, changed, register=False); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'invalid_saved_decision'
    raw = store.read_status(tmp_path, now=NOW)
    raw['report']['opportunity_board'] = value
    raw['report']['input_fingerprint'] = 'c' * 64
    store._save(tmp_path, raw)
    assert deliver(tmp_path, transport)['status'] == 'invalid_saved_decision'
    assert not transport.posts


def test_recovered_issued_journal_is_not_used_for_delivery(tmp_path):
    value = save(tmp_path); save(tmp_path, board('c' * 64))
    (tmp_path / 'decision_engine' / 'issued.json').write_text('{bad', encoding='utf-8')
    save(tmp_path, value, register=False); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'invalid_saved_decision'
    assert not transport.posts


def test_post_success_final_write_failure_leaves_pending_and_blocks_replay(tmp_path, monkeypatch):
    save(tmp_path); transport = Telegram(); write = store._write
    def fail_delivered(path, raw):
        if path.parent.name == 'notifications' and raw['data']['entries'][0]['state'] == 'delivered':
            raise OSError('synthetic final write error')
        return write(path, raw)
    monkeypatch.setattr(store, '_write', fail_delivered)
    assert deliver(tmp_path, transport)['status'] == 'uncertain'
    monkeypatch.setattr(store, '_write', write)
    assert deliver(tmp_path, transport)['status'] == 'pending'
    assert len(transport.posts) == 1


def test_corrupt_or_semantically_invalid_ledger_fails_closed(tmp_path):
    save(tmp_path); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    path = tmp_path / 'notifications' / 'telegram.json'
    raw = store._read(path); raw['data']['entries'][0]['state'] = 'ignored'
    raw['sha256'] = store._hash(raw['data']); store._write(path, raw)
    assert deliver(tmp_path, transport)['status'] == 'ledger_unavailable'
    path.write_text('{bad', encoding='utf-8')
    assert deliver(tmp_path, transport)['status'] == 'ledger_unavailable'
    assert len(transport.posts) == 1 and len(transport.gets) == 2


def test_existing_null_ledger_is_corruption_and_never_erases_delivery_history(tmp_path):
    save(tmp_path); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    (tmp_path / 'notifications' / 'telegram.json').write_text('null', encoding='utf-8')
    assert deliver(tmp_path, transport)['status'] == 'ledger_unavailable'
    assert len(transport.posts) == 1 and len(transport.gets) == 2


def test_finished_registered_empty_board_is_no_candidates_without_network_or_ledger(tmp_path):
    value = board(); value['candidates'] = []; value['coverage']['selected'] = 0; rebind(value)
    save(tmp_path, value); transport = Telegram()
    preview = module().preview_latest(tmp_path, now=NOW)
    assert preview['status'] == 'no_candidates' and preview['candidate_count'] == 0
    assert preview['sendable'] is False and preview['digest'] is None
    assert deliver(tmp_path, transport)['status'] == 'no_candidates'
    assert not transport.gets and not transport.posts and not (tmp_path / 'notifications').exists()


def test_ledger_capacity_is_bounded_and_does_not_evict_live_dedupe_records(tmp_path, monkeypatch):
    save(tmp_path); transport = Telegram(); mod = module()
    monkeypatch.setattr(mod, 'MAX_LEDGER_ENTRIES', 1)
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    save(tmp_path, board('c' * 64))
    assert deliver(tmp_path, transport)['status'] == 'ledger_capacity'
    save(tmp_path, board())
    assert deliver(tmp_path, transport)['status'] == 'already_delivered'
    assert len(transport.posts) == 1


@pytest.mark.parametrize('audit', [['bad'], 7, 'not-a-map'])
def test_malformed_report_source_metadata_returns_sanitized_failure(tmp_path, audit):
    save(tmp_path)
    status = store.read_status(tmp_path, now=NOW)
    status['report']['opportunity_scan'] = audit
    store._save(tmp_path, status)
    transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'invalid_saved_decision'
    assert not transport.posts and not transport.gets


@pytest.mark.parametrize('method', ['getMe', 'getChat'])
def test_preflight_network_failure_can_retry_without_leaving_pending_claim(tmp_path, method):
    save(tmp_path); transport = Telegram(); original_get = transport.get
    def unavailable(url, **kwargs):
        if url.endswith('/' + method):
            raise requests.Timeout('synthetic preflight timeout')
        return original_get(url, **kwargs)
    transport.get = unavailable
    assert deliver(tmp_path, transport)['status'] in ('bot_identity_failed', 'private_chat_failed')
    assert not transport.posts and not (tmp_path / 'notifications' / 'telegram.json').exists()
    transport.get = original_get
    assert deliver(tmp_path, transport)['status'] == 'delivered'


def test_saved_display_changes_do_not_renew_or_rewrite_first_issued_message(tmp_path):
    value = save(tmp_path); transport = Telegram()
    preview = module().preview_latest(tmp_path, now=NOW)
    value['candidates'][0].update(name='later display name', current_price=999999., action='entry_candidate')
    value['generated_at'] = NOW
    save(tmp_path, value, register=False)
    assert module().preview_latest(tmp_path, now=NOW)['digest'] == preview['digest']
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    assert '알테오젠' in transport.posts[0]['text']
    assert 'later display name' not in transport.posts[0]['text'] and '999999' not in transport.posts[0]['text']


def test_delivery_record_is_bound_to_the_configured_private_recipient(tmp_path, monkeypatch):
    save(tmp_path); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    # Synthetic private configuration change must not reuse the first peer's receipt.
    import sys
    monkeypatch.setattr(sys.modules[__name__], 'CHAT', CHAT + 10)
    monkeypatch.setenv('TELEGRAM_CHAT_ID', str(CHAT))
    other = Telegram()
    assert deliver(tmp_path, other)['status'] == 'delivered'
    assert len(other.posts) == 1 and other.gets == ['getMe', 'getChat']


def test_expired_ledger_claims_can_be_pruned_only_when_old_decisions_are_unsendable(tmp_path):
    save(tmp_path); transport = Telegram()
    assert deliver(tmp_path, transport)['status'] == 'delivered'
    later = '2026-10-18T07:00:00Z'
    newer = board('c' * 64)
    newer.update(latest_session='2026-10-16', generated_at=later, origin_at=later)
    for row in newer['candidates']: row['quote_session'] = '2026-10-16'
    rebind(newer); save(tmp_path, newer)
    status = store.read_status(tmp_path, now=later)
    status['generated_at'] = later
    store._save(tmp_path, status)
    transport.now = later
    assert deliver(tmp_path, transport, now=later)['status'] == 'delivered'
    assert len(store._read(tmp_path / 'notifications' / 'telegram.json')['data']['entries']) == 1
    save(tmp_path, board(), register=False)
    assert deliver(tmp_path, transport, now=later)['status'] == 'stale_decision'
    assert len(transport.posts) == 2


def test_real_time_call_refreshes_clock_after_lock_and_slow_identity_checks(tmp_path, monkeypatch):
    save(tmp_path); mod = module(); transport = Telegram(now='2026-10-09T02:02:00Z')
    moments = iter(['2026-10-09T02:00:00Z', '2026-10-09T02:01:10Z', '2026-10-09T02:01:50Z',
        '2026-10-09T02:02:00Z'])
    original_now = mod.decision_engine._now
    monkeypatch.setattr(mod.decision_engine, '_now', lambda _: original_now(next(moments)))
    assert deliver(tmp_path, transport, now=None)['status'] == 'delivered'
    raw = store._read(tmp_path / 'notifications' / 'telegram.json')
    assert raw['data']['entries'][0]['created_at'] == '2026-10-09T02:01:50Z'
    assert raw['data']['entries'][0]['updated_at'] == '2026-10-09T02:02:00Z'


def test_a_replaced_current_decision_during_preflight_is_not_sent(tmp_path):
    save(tmp_path); transport = Telegram(); original_get = transport.get
    def replace_during_identity(url, **kwargs):
        response = original_get(url, **kwargs)
        if url.endswith('/getChat'):
            save(tmp_path, board('c' * 64))
        return response
    transport.get = replace_during_identity
    assert deliver(tmp_path, transport)['status'] == 'decision_changed'
    assert not transport.posts and not (tmp_path / 'notifications' / 'telegram.json').exists()
    transport.get = original_get
    assert deliver(tmp_path, transport)['status'] == 'delivered'


def test_decision_expiring_during_preflight_is_not_sent(tmp_path, monkeypatch):
    save(tmp_path); mod = module(); transport = Telegram()
    moments = iter(['2026-10-15T06:59:50Z', '2026-10-15T06:59:50Z', '2026-10-15T07:00:10Z'])
    original_now = mod.decision_engine._now
    monkeypatch.setattr(mod.decision_engine, '_now', lambda _: original_now(next(moments)))
    assert deliver(tmp_path, transport, now=None)['status'] == 'stale_decision'
    assert not transport.posts and not (tmp_path / 'notifications' / 'telegram.json').exists()


def test_real_time_rate_limit_delay_starts_at_response_receipt_time(tmp_path, monkeypatch):
    save(tmp_path); mod = module(); transport = Telegram()
    transport.post_result = Response(dict(ok=False, error_code=429, parameters=dict(retry_after=60)), 429)
    moments = iter([NOW, NOW, NOW, '2026-10-09T02:00:15Z'])
    original_now = mod.decision_engine._now
    def clock(value):
        return original_now(next(moments) if value is None else value)
    monkeypatch.setattr(mod.decision_engine, '_now', clock)
    assert deliver(tmp_path, transport, now=None)['status'] == 'retry_deferred'
    raw = store._read(tmp_path / 'notifications' / 'telegram.json')
    assert raw['data']['entries'][0]['next_retry_at'] == '2026-10-09T02:01:15Z'
    assert deliver(tmp_path, transport, now='2026-10-09T02:01:00Z')['status'] == 'retry_deferred'
    assert len(transport.posts) == 1 and len(transport.gets) == 2
    transport.post_result = None; transport.now = '2026-10-09T02:01:15Z'
    assert deliver(tmp_path, transport, now=transport.now)['status'] == 'delivered'
