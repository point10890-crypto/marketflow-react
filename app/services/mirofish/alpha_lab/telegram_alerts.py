"""Receipt-verified AlphaLab research notifications to one private operator.

Only the latest saved, sealed decision is eligible. A durable pending claim is
written before sendMessage; an ambiguous delivery is never automatically retried.
The scanner/OpenClaw transport and their notification ledgers are not used here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import html
import os
from pathlib import Path
import re

from filelock import FileLock, Timeout
import requests

from . import decision_engine, opportunity_store, store

EXPECTED_BOT_USERNAME = 'bitman75_bot'
DETAIL_URL = 'https://bit-man.net/dashboard/ai-bain/chart-predict'
MAX_LEDGER_ENTRIES = 2048
MAX_ATTEMPTS = 3
MAX_PRICE = 1_000_000_000_000
MAX_MESSAGE_UNITS = 3900
MAX_DECISION_AGE = timedelta(days=7)
LEDGER_RETENTION = timedelta(days=8)
_STATES = {'pending', 'delivered', 'uncertain', 'action_required', 'rejected', 'rate_limited', 'retry_exhausted'}
_ENTRY_KEYS = {'event_id', 'decision_id', 'digest', 'recipient_fingerprint', 'state', 'created_at',
               'updated_at', 'attempts', 'next_retry_at', 'receipt_digest'}


def _result(status, prepared=None):
    value = prepared or {}
    return dict(status=status, decision_id=value.get('decision_id'), digest=value.get('digest'),
                candidate_count=value.get('candidate_count', 0), source_session=value.get('source_session'),
                sendable=bool(value.get('sendable', False)))


def _valid_board(value):
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int or value.get('schema_version') != 1
            or value.get('policy_version') != decision_engine.POLICY
            or value.get('research_only') is not True or value.get('live_orders') is not False
            or value.get('status') not in ('held', 'ready')
            or decision_engine._day(value.get('latest_session')) is None
            or decision_engine._timestamp(value.get('generated_at')) is None
            or not all(decision_engine._hash_valid(value.get(key)) for key in
                       ('decision_id', 'input_fingerprint', 'source_audit_hash'))):
        return False
    rows = value.get('candidates')
    if (not isinstance(rows, list) or not 0 <= len(rows) <= 3
            or len({row.get('symbol') for row in rows if isinstance(row, dict)}) != len(rows)):
        return False
    for rank, row in enumerate(rows, 1):
        if (not decision_engine._saved_candidate_valid(row, value, rank)
                or type(row.get('rank')) is not int
                or type(row['plan'].get('horizon_sessions')) is not int
                or any(row['plan'][key] > MAX_PRICE for key in
                       ('entry_low', 'entry_high', 'stop_price', 'target_price'))):
            return False
    return decision_engine._stable_identity(value['input_fingerprint'], value['source_audit_hash'],
               value['latest_session'], rows) == value['decision_id']


def _price(value):
    return f'{value:,.0f}' if value == int(value) else f'{value:,.2f}'


def _message(board):
    # This text is derived exclusively from the first issued board, never from
    # polling time, monitor observations, today's quotes or a refreshed scan clock.
    created = decision_engine._timestamp(board['generated_at']).astimezone(decision_engine.KST)
    lines = ['<b>AlphaLab 최신 연구 후보 TOP3</b>',
             f'기준 거래일: {board["latest_session"]} · 저장: {created:%Y-%m-%d %H:%M} KST',
             '마지막 완료 세션 보고서 · 연구 참고용 · 주문 승인 아님',
             '시세: 저장된 종가 참고(stale / 실시간 미검증)',
             f'상태: {"보류(held) · 실시간 진입 승인 미확인" if board["status"] == "held" else "연구 참고(ready)"}', '']
    for row in board['candidates']:
        name = row['name'][:80] + ('…' if len(row['name']) > 80 else '')
        name = ''.join(c for c in name if c.isprintable())
        plan = row['plan']
        lines.extend([f'<b>{row["rank"]}. {html.escape(name, quote=False)} ({row["symbol"]} · KR)</b>',
            f'참고 비중: {row["reference_weight"] * 100:.2f}%',
            f'기준 진입: {_price(plan["entry_low"])} ~ {_price(plan["entry_high"])}원',
            f'기준 손절: {_price(plan["stop_price"])}원 · 목표: {_price(plan["target_price"])}원',
            f'관찰 기간: {plan["horizon_sessions"]} 거래일', ''])
    lines.append(f'<a href="{DETAIL_URL}">AlphaLab 상세 보기</a>')
    message = '\n'.join(lines)
    if len(message.encode('utf-16-le')) // 2 >= MAX_MESSAGE_UNITS:
        raise ValueError('message_capacity')
    return message


def _prepare(root, current):
    """Require exact current-to-issued source/plan binding; return frozen text."""
    try:
        status = store.read_status(root, now=decision_engine._stamp(current))
        report = status.get('report')
        if (status.get('state') not in ('held', 'ready') or not isinstance(report, dict)
                or report.get('schema_version') != 1 or report.get('mode') != 'research'):
            return _result('invalid_saved_decision'), None
        board = report.get('opportunity_board')
        if not _valid_board(board):
            return _result('invalid_saved_decision'), None
        audit = report.get('opportunity_scan')
        if (report.get('input_fingerprint') != board['input_fingerprint'] or not isinstance(audit, dict)
                or audit.get('audit_hash') != board['source_audit_hash']
                or report.get('latest_session') != board['latest_session']):
            return _result('invalid_saved_decision'), None
        journal, recovered = opportunity_store._journal(root)
        issued = next((row for row in journal['issued'] if row['decision_id'] == board['decision_id']), None)
        if (recovered or issued is None or opportunity_store._stable(issued['board']) != opportunity_store._stable(board)
                or not _valid_board(issued['board'])):
            return _result('invalid_saved_decision'), None
        frozen = issued['board']
        origin = decision_engine._timestamp(frozen['generated_at'])
        clocks = [origin, decision_engine._timestamp(board['generated_at']),
                  decision_engine._timestamp(status.get('generated_at')),
                  decision_engine._timestamp(report.get('decision_at'))]
        session = date.fromisoformat(frozen['latest_session'])
        safe = dict(decision_id=frozen['decision_id'], candidate_count=len(frozen['candidates']),
                    source_session=frozen['latest_session'], sendable=False)
        if any(clock is None for clock in clocks):
            return _result('invalid_saved_decision'), None
        if any(clock > current for clock in clocks) or session > origin.astimezone(decision_engine.KST).date():
            return _result('future_decision', safe), None
        if current - origin > MAX_DECISION_AGE or (current.astimezone(decision_engine.KST).date() - session).days > 7:
            return _result('stale_decision', safe), None
        if not frozen['candidates']:
            return _result('no_candidates', safe), None
        message = _message(frozen)
        safe.update(digest=store._hash(message), sendable=True)
        return _result('preview', safe), message
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return _result('invalid_saved_decision'), None


def preview_latest(root, now=None):
    """Read-only six-field summary; never exposes message, credentials or receipt."""
    try:
        current = decision_engine._now(now)
    except (ValueError, TypeError):
        return _result('invalid_saved_decision')
    return _prepare(root, current)[0]


def _config():
    token_key = os.getenv('ALPHA_LAB_TELEGRAM_BOT_TOKEN_KEY', 'TELEGRAM_BOT_TOKEN')
    chat_key = os.getenv('ALPHA_LAB_TELEGRAM_CHAT_ID_KEY', 'TELEGRAM_CHAT_ID')
    if token_key not in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_BOT_TOKEN') or chat_key != 'TELEGRAM_CHAT_ID':
        return None
    token, peer = os.getenv(token_key, ''), os.getenv(chat_key, '')
    if re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{20,160}', token) is None or re.fullmatch(r'[0-9]{1,16}', peer.strip()) is None:
        return None
    chat_id = int(peer.strip())
    if not 0 < chat_id < 2 ** 52:
        return None
    # The configured private peer and fixed bot username permit a dedupe check
    # without another API call. New sends still verify both actual identities.
    fingerprint = store._hash(dict(bot=EXPECTED_BOT_USERNAME, private_chat=chat_id))
    return token, chat_id, fingerprint


def _positive_int(value):
    return type(value) is int and 0 < value < 2 ** 52


def _valid_bot(value):
    return (isinstance(value, dict) and value.get('is_bot') is True and _positive_int(value.get('id'))
            and isinstance(value.get('username'), str) and value['username'].casefold() == EXPECTED_BOT_USERNAME)


def _verified_peer(get, token, chat_id):
    try:
        response = get(f'https://api.telegram.org/bot{token}/getMe', timeout=15, allow_redirects=False)
        payload = response.json()
        if (getattr(response, 'status_code', None) != 200 or not isinstance(payload, dict)
                or payload.get('ok') is not True or not _valid_bot(payload.get('result'))):
            return 'bot_identity_failed', None
        bot = payload['result']
    except Exception:
        return 'bot_identity_failed', None
    try:
        response = get(f'https://api.telegram.org/bot{token}/getChat', params=dict(chat_id=chat_id),
                       timeout=15, allow_redirects=False)
        payload = response.json()
        chat = payload.get('result') if isinstance(payload, dict) else None
        if (getattr(response, 'status_code', None) != 200 or not isinstance(payload, dict)
                or payload.get('ok') is not True or not isinstance(chat, dict)
                or not _positive_int(chat.get('id')) or chat['id'] != chat_id or chat.get('type') != 'private'):
            return 'private_chat_failed', None
        return None, bot
    except Exception:
        return 'private_chat_failed', None


def _ledger(path, current):
    raw = store._read(path)
    if raw is None:
        if path.exists():
            raise ValueError('notification_ledger_integrity')
        return dict(schema_version=1, entries=[])
    if (not isinstance(raw, dict) or set(raw) != {'schema_version', 'data', 'sha256'}
            or raw['schema_version'] != 1 or not isinstance(raw['data'], dict)
            or raw['sha256'] != store._hash(raw['data'])):
        raise ValueError('notification_ledger_integrity')
    data = raw['data']
    if (set(data) != {'schema_version', 'entries'} or data['schema_version'] != 1
            or not isinstance(data['entries'], list) or len(data['entries']) > MAX_LEDGER_ENTRIES):
        raise ValueError('notification_ledger_integrity')
    seen = set()
    for row in data['entries']:
        if (not isinstance(row, dict) or set(row) != _ENTRY_KEYS
                or not all(decision_engine._hash_valid(row.get(key)) for key in
                           ('event_id', 'decision_id', 'digest', 'recipient_fingerprint'))
                or row['state'] not in _STATES or type(row['attempts']) is not int
                or not 1 <= row['attempts'] <= MAX_ATTEMPTS or row['event_id'] in seen
                or row['event_id'] != store._hash({key: row[key] for key in
                    ('decision_id', 'digest', 'recipient_fingerprint')})):
            raise ValueError('notification_ledger_integrity')
        created, updated = map(decision_engine._timestamp, (row['created_at'], row['updated_at']))
        if created is None or updated is None or not created <= updated <= current:
            raise ValueError('notification_ledger_integrity')
        retry = decision_engine._timestamp(row['next_retry_at'])
        if row['state'] == 'rate_limited':
            if retry is None or retry <= updated or row['attempts'] >= MAX_ATTEMPTS:
                raise ValueError('notification_ledger_integrity')
        elif row['next_retry_at'] is not None:
            raise ValueError('notification_ledger_integrity')
        if row['state'] == 'delivered':
            if not decision_engine._hash_valid(row['receipt_digest']):
                raise ValueError('notification_ledger_integrity')
        elif row['receipt_digest'] is not None:
            raise ValueError('notification_ledger_integrity')
        seen.add(row['event_id'])
    # Expired decisions cannot be sent by _prepare, so these old claims can be
    # discarded safely. At capacity, fail closed rather than evict a live claim.
    return dict(schema_version=1, entries=[deepcopy(row) for row in data['entries']
                if current - decision_engine._timestamp(row['created_at']) <= LEDGER_RETENTION])


def _write_ledger(path, data):
    store._write(path, dict(schema_version=1, data=data, sha256=store._hash(data)))


def _receipt(payload, chat_id, bot, message, current):
    result = payload.get('result') if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not _positive_int(result.get('message_id')):
        return None
    chat, sender, when = result.get('chat'), result.get('from'), result.get('date')
    if (not isinstance(chat, dict) or not _positive_int(chat.get('id')) or chat['id'] != chat_id
            or chat.get('type') != 'private' or not _valid_bot(sender) or sender['id'] != bot['id']
            or not _positive_int(when) or abs(when - current.timestamp()) > 60
            or result.get('text') != html.unescape(re.sub(r'<[^>]+>', '', message))):
        return None
    # Preserve proof of the validated receipt, without storing any Telegram IDs
    # or message content. No raw response is returned, logged or persisted.
    return store._hash(result)


def _send(post, token, chat_id, bot, message, current, attempts, *, realtime=False):
    received = current
    try:
        response = post(f'https://api.telegram.org/bot{token}/sendMessage',
            json=dict(chat_id=chat_id, text=message, parse_mode='HTML', disable_web_page_preview=True),
            timeout=15, allow_redirects=False)
        received = decision_engine._now(None) if realtime else current
        payload = response.json()
        code = getattr(response, 'status_code', None)
        if code == 200 and isinstance(payload, dict) and payload.get('ok') is True:
            receipt = _receipt(payload, chat_id, bot, message, received)
            return ('delivered', None, receipt, received) if receipt else ('uncertain', None, None, received)
        explicit = (isinstance(payload, dict) and payload.get('ok') is False and payload.get('error_code') == code)
        if explicit and code in (401, 403):
            return 'action_required', None, None, received
        if explicit and code == 429:
            delay = (payload.get('parameters') or {}).get('retry_after')
            if type(delay) is not int or not 1 <= delay <= 86400:
                return 'action_required', None, None, received
            if attempts >= MAX_ATTEMPTS:
                return 'retry_exhausted', None, None, received
            return 'rate_limited', decision_engine._stamp(received + timedelta(seconds=delay)), None, received
        if explicit and code == 400:
            return 'rejected', None, None, received
        return 'uncertain', None, None, received
    except Exception:
        return 'uncertain', None, None, received


def deliver_latest(root, now=None, enabled=None, request_get=None, request_post=None):
    """Send only the current sealed decision; return a sanitized six-field status.

    Default-off via ALPHA_LAB_TELEGRAM_ENABLED. An explicitly authorized one-time
    caller may use enabled=True. Dependency injection keeps all network optional
    in tests. 429 is the only automatic send retry, bounded by delay and attempts.
    """
    try:
        current = decision_engine._now(now)
    except (ValueError, TypeError):
        return _result('invalid_saved_decision')
    preview, message = _prepare(root, current)
    active = (os.getenv('ALPHA_LAB_TELEGRAM_ENABLED', 'false').strip().lower() == 'true'
              if enabled is None else enabled is True)
    if not active:
        return _result('disabled', preview)
    if message is None:
        return preview
    config = _config()
    if config is None:
        return _result('not_configured', preview)
    token, chat_id, fingerprint = config
    binding = dict(decision_id=preview['decision_id'], digest=preview['digest'], recipient_fingerprint=fingerprint)
    event_id = store._hash(binding)
    directory = Path(root) / 'notifications'
    path = directory / 'telegram.json'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with FileLock(str(directory / 'telegram.lock'), timeout=30):
            # A slow lock waiter must not deliver a decision replaced while it
            # waited; re-read the saved current decision before any network IO.
            if now is None:
                current = decision_engine._now(None)
            latest, latest_message = _prepare(root, current)
            if latest_message is None:
                return latest
            if latest['decision_id'] != preview['decision_id'] or latest['digest'] != preview['digest']:
                return _result('decision_changed', latest)
            data = _ledger(path, current)
            entry = next((row for row in data['entries'] if row['event_id'] == event_id), None)
            if entry is not None:
                state = entry['state']
                if state != 'rate_limited':
                    return _result('already_delivered' if state == 'delivered' else state, preview)
                if current < decision_engine._timestamp(entry['next_retry_at']):
                    return _result('retry_deferred', preview)
            elif len(data['entries']) >= MAX_LEDGER_ENTRIES:
                return _result('ledger_capacity', preview)
            error, bot = _verified_peer(request_get or requests.get, token, chat_id)
            if error:
                return _result(error, preview)
            # Lock acquisition and identity checks can take up to a minute. Use
            # a fresh wall clock for the final eligibility check, durable claim
            # and receipt comparison; explicitly injected clocks remain fixed.
            if now is None:
                current = decision_engine._now(None)
            latest, latest_message = _prepare(root, current)
            if latest_message is None:
                return latest
            if latest['decision_id'] != preview['decision_id'] or latest['digest'] != preview['digest']:
                return _result('decision_changed', latest)
            stamp = decision_engine._stamp(current)
            if entry is None:
                entry = dict(binding, event_id=event_id, state='pending', attempts=1,
                    created_at=stamp, updated_at=stamp, next_retry_at=None, receipt_digest=None)
                data['entries'].append(entry)
            else:
                entry.update(state='pending', attempts=entry['attempts'] + 1, updated_at=stamp,
                             next_retry_at=None, receipt_digest=None)
            _write_ledger(path, data)  # If this fails, sendMessage must not run.
            state, retry, receipt, received = _send(request_post or requests.post, token, chat_id, bot,
                message, current, entry['attempts'], realtime=now is None)
            entry.update(state=state, next_retry_at=retry, receipt_digest=receipt,
                         updated_at=decision_engine._stamp(received))
            try:
                _write_ledger(path, data)
            except (OSError, ValueError, TypeError):
                # The durable pending claim remains and blocks another attempt.
                return _result('uncertain', preview)
            return _result('retry_deferred' if state == 'rate_limited' else state, preview)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, Timeout):
        return _result('ledger_unavailable', preview)
