# -*- coding: utf-8 -*-
"""회원 본인 텔레그램 알림 — 구독 승인/거절/만료 안내를 관리자가 아니라 **본인**에게.

기존 흐름은 승인·만료 알림이 전부 관리자 텔레그램(TELEGRAM_BOT_TOKEN/CHAT_ID)로만 갔다.
이 모듈은 회원별 chat_id 를 받아 본인에게 보내는 별도 사일로다.

연결 방식 (인바운드 웹훅 없음):
    1. POST /api/auth/telegram/link-code → 8자리 코드 + 딥링크 https://t.me/<bot>?start=<code>
    2. 회원이 봇에게 /start <code> 전송
    3. poll_link_updates() (60초 주기 워커) 가 getUpdates 로 메시지를 읽어 코드 매칭 →
       User.telegram_chat_id 저장 + "연결 완료" 회신
    offset 은 data/telegram_member_offset.json 에 원자적으로 보존한다.

환경변수:
    TELEGRAM_MEMBER_BOT_TOKEN     회원 알림 봇 토큰 (없으면 TELEGRAM_BOT_TOKEN 폴백)
    TELEGRAM_MEMBER_BOT_USERNAME  딥링크용 봇 username (@ 없이)
    MEMBER_TELEGRAM_LINK_ENABLED  폴러 on/off (기본: 봇 토큰이 있으면 on)

모든 네트워크 호출은 requests + timeout + try/except — 워커 루프/요청 흐름으로 예외를 올리지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone

import requests

from app.utils.atomic_json import write_json_atomic
from app.utils.paths import DATA_DIR

logger = logging.getLogger('marketflow.telegram.member')

LINK_CODE_TTL_MINUTES = 30
LINK_CODE_LENGTH = 8
# 혼동 문자(0/O, 1/I) 제외 — Telegram start 파라미터 허용 문자([A-Za-z0-9_-]) 안에서 선택
_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
OFFSET_PATH = os.path.join(DATA_DIR, 'telegram_member_offset.json')
REQUEST_TIMEOUT = 10
TELEGRAM_API_BASE = 'https://api.telegram.org'

_FALSY = {'0', 'false', 'no', 'off'}
_KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────

def bot_token() -> str:
    return (os.getenv('TELEGRAM_MEMBER_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN') or '').strip()


def bot_username() -> str:
    return (os.getenv('TELEGRAM_MEMBER_BOT_USERNAME') or '').strip().lstrip('@')


def is_configured() -> bool:
    """본인 알림 발송 가능 여부 (봇 토큰 존재)."""
    return bool(bot_token())


def link_enabled() -> bool:
    """연결 폴러 활성 여부 — 명시적으로 끄지 않았고 봇 토큰이 있으면 on."""
    raw = (os.getenv('MEMBER_TELEGRAM_LINK_ENABLED') or '').strip().lower()
    if raw in _FALSY:
        return False
    return is_configured()


def deep_link(code: str) -> str | None:
    username = bot_username()
    if not username or not code:
        return None
    return f'https://t.me/{username}?start={code}'


# ─────────────────────────────────────────────────────────────────────────────
# 링크 코드 발급 / 해제 (commit 은 호출자 책임)
# ─────────────────────────────────────────────────────────────────────────────

def generate_link_code() -> str:
    return ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(LINK_CODE_LENGTH))


def issue_link_code(user, *, now: datetime | None = None) -> dict:
    """유저에게 새 연결 코드를 발급해 저장(미commit)하고 딥링크 정보를 돌려준다."""
    now = now or datetime.now(timezone.utc)
    code = generate_link_code()
    expires_at = now + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    user.telegram_link_code = code
    user.telegram_link_code_expires_at = expires_at
    return {
        'code': code,
        'deep_link': deep_link(code),
        'bot_username': bot_username() or None,
        'expires_at': expires_at.isoformat(),
        'ttl_minutes': LINK_CODE_TTL_MINUTES,
    }


def unlink(user) -> None:
    user.telegram_chat_id = None
    user.telegram_linked_at = None
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None


# ─────────────────────────────────────────────────────────────────────────────
# 전송
# ─────────────────────────────────────────────────────────────────────────────

def _api_url(method: str) -> str:
    return f'{TELEGRAM_API_BASE}/bot{bot_token()}/{method}'


def send_message(chat_id: str | int, text: str, *, parse_mode: str = 'HTML') -> bool:
    """chat_id 로 메시지 1건 전송. 실패는 로그만 남기고 False."""
    if not is_configured() or not chat_id or not text:
        return False
    if len(text) > 4000:
        text = text[:3990] + '\n[…잘림]'
    try:
        resp = requests.post(
            _api_url('sendMessage'),
            json={
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            try:
                ok = bool(resp.json().get('ok'))
            except Exception:
                ok = True
            if ok:
                logger.info(f'member telegram ok chat={chat_id}')
                return True
        logger.warning(f'member telegram HTTP {resp.status_code} chat={chat_id} body={resp.text[:200]}')
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'member telegram exception chat={chat_id}: {type(exc).__name__}: {exc}')
        return False


def notify_member(user, text: str, *, background: bool = False) -> bool:
    """연결된 회원 본인에게 전송. 미연결/미설정이면 아무것도 안 하고 False.

    background=True 면 데몬 스레드로 전송하고 즉시 True(발송 시도) 를 돌려준다 —
    관리자 승인 버튼이 텔레그램 지연에 묶이지 않게 하는 용도.
    """
    chat_id = (getattr(user, 'telegram_chat_id', None) or '').strip() if user is not None else ''
    if not chat_id:
        return False
    if not is_configured():
        logger.info('member telegram skipped: bot token unset')
        return False
    if background:
        threading.Thread(
            target=send_message, args=(chat_id, text), daemon=True, name='MemberTelegramSend',
        ).start()
        return True
    return send_message(chat_id, text)


# ─────────────────────────────────────────────────────────────────────────────
# 메시지 본문
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_kst(value) -> str:
    """ISO 문자열/DateTime → 'YYYY-MM-DD HH:MM (KST)'. 파싱 실패 시 원문."""
    if value is None:
        return '-'
    dt = value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
    if not isinstance(dt, datetime):
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST).strftime('%Y-%m-%d %H:%M') + ' (KST)'


_TIER_LABEL = {'pro': 'Pro', 'premium': 'Ultra Pro'}


def build_approval_message(user, *, summary: str = '') -> str:
    tier_label = _TIER_LABEL.get(getattr(user, 'tier', None) or '', getattr(user, 'tier', None) or '-')
    expires = getattr(user, 'pro_expires_at', None)
    lines = [
        '✅ <b>구독이 승인되었습니다</b>',
        '',
        f'👤 {user.name} 님',
        f'📋 플랜: {tier_label}',
        f'📅 만료일: {_fmt_kst(expires) if expires else "무기한"}',
    ]
    if getattr(user, 'is_aibain_active', False) and getattr(user, 'aibain_expires_at', None):
        lines.append(f'🤖 AI Brain 만료일: {_fmt_kst(user.aibain_expires_at)}')
    if summary:
        lines += ['', f'ℹ️ {summary}']
    lines += ['', '지금 바로 대시보드에서 이용하실 수 있습니다: https://bit-man.net/dashboard']
    return '\n'.join(lines)


def build_reject_message(user, *, note: str = '') -> str:
    lines = [
        '⚠️ <b>구독 신청이 반려되었습니다</b>',
        '',
        f'👤 {user.name} 님',
    ]
    if note:
        lines.append(f'📝 사유: {note}')
    lines += ['', '입금 정보 확인 후 다시 신청해 주세요: https://bit-man.net/plan-select']
    return '\n'.join(lines)


def build_member_expiry_message(stage: str, when) -> str:
    when_label = _fmt_kst(when)
    if stage == 'd3':
        head = '⏰ <b>Pro 구독이 3일 뒤 만료됩니다</b>'
        tail = '만료 전 갱신하면 남은 기간이 그대로 이어집니다.'
    elif stage == 'd1':
        head = '⏰ <b>Pro 구독이 내일 만료됩니다</b>'
        tail = '지금 갱신 신청하면 끊김 없이 이용할 수 있습니다.'
    else:
        head = '🔒 <b>Pro 구독이 만료되었습니다</b>'
        tail = '재구독 신청 후 승인되면 즉시 다시 이용할 수 있습니다.'
    return '\n'.join([
        head,
        '',
        f'📅 만료일: {when_label}',
        '',
        tail,
        '🔁 갱신/재구독: https://bit-man.net/plan-select?resubscribe=1',
    ])


# ─────────────────────────────────────────────────────────────────────────────
# 연결 폴러 (getUpdates)
# ─────────────────────────────────────────────────────────────────────────────

def _read_offset() -> int:
    try:
        with open(OFFSET_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return int(data.get('offset') or 0)
    except Exception:
        return 0


def _write_offset(offset: int) -> None:
    try:
        write_json_atomic(OFFSET_PATH, {
            'offset': int(offset),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'member telegram offset write failed: {type(exc).__name__}: {exc}')


def parse_start_code(text: str | None) -> str | None:
    """'/start ABCD1234' → 'ABCD1234'. /start 가 아니면 None, 코드 없으면 ''."""
    if not text:
        return None
    parts = text.strip().split()
    if not parts:
        return None
    cmd = parts[0].split('@', 1)[0].lower()
    if cmd != '/start':
        return None
    if len(parts) < 2:
        return ''
    return parts[1].strip().upper()


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def match_link_code(code: str, *, now: datetime | None = None):
    """유효(미만료)한 코드를 가진 유저를 찾는다. 없으면 None. app context 필요."""
    from app.models.user import User

    if not code:
        return None
    now_naive = _naive_utc(now or datetime.now(timezone.utc))
    user = User.query.filter(User.telegram_link_code == code).first()
    if user is None:
        return None
    expires = _naive_utc(user.telegram_link_code_expires_at)
    if expires is None or expires < now_naive:
        return None
    return user


def _complete_link(user, chat_id: str, *, now: datetime | None = None) -> None:
    from app.models import db

    user.telegram_chat_id = str(chat_id)
    user.telegram_linked_at = now or datetime.now(timezone.utc)
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None
    db.session.commit()


def fetch_updates(offset: int, *, limit: int = 50) -> list[dict]:
    """getUpdates 호출. 실패 시 빈 리스트 (예외 없음)."""
    try:
        resp = requests.get(
            _api_url('getUpdates'),
            params={
                'offset': offset,
                'limit': limit,
                'timeout': 0,
                'allowed_updates': json.dumps(['message']),
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(f'member telegram getUpdates HTTP {resp.status_code} body={resp.text[:200]}')
            return []
        data = resp.json()
        if not data.get('ok'):
            logger.warning(f'member telegram getUpdates not ok: {str(data)[:200]}')
            return []
        result = data.get('result') or []
        return result if isinstance(result, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'member telegram getUpdates exception: {type(exc).__name__}: {exc}')
        return []


def poll_link_updates(*, limit: int = 50) -> dict:
    """봇 메시지를 읽어 /start <code> 를 유저에 매칭한다. Flask app context 안에서 호출.

    반환: {'updates': n, 'linked': n, 'offset': next_offset, 'skipped': bool}
    """
    if not is_configured():
        return {'updates': 0, 'linked': 0, 'offset': 0, 'skipped': True}

    offset = _read_offset()
    updates = fetch_updates(offset, limit=limit)
    linked = 0
    max_update_id = None

    for upd in updates:
        try:
            update_id = int(upd.get('update_id'))
        except (TypeError, ValueError):
            continue
        max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)

        message = upd.get('message') or {}
        chat = message.get('chat') or {}
        chat_id = chat.get('id')
        if chat_id is None:
            continue
        code = parse_start_code(message.get('text'))
        if code is None:
            continue  # /start 이외 메시지는 무시
        if code == '':
            send_message(chat_id, '계정 페이지(bit-man.net/account)에서 발급한 연결 링크로 다시 시작해 주세요.')
            continue
        try:
            user = match_link_code(code)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'member telegram match failed: {type(exc).__name__}: {exc}')
            user = None
        if user is None:
            send_message(chat_id, '연결 코드가 유효하지 않거나 만료되었습니다(30분). 계정 페이지에서 새 코드를 발급해 주세요.')
            continue
        try:
            _complete_link(user, str(chat_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'member telegram link commit failed: {type(exc).__name__}: {exc}')
            try:
                from app.models import db
                db.session.rollback()
            except Exception:
                pass
            continue
        linked += 1
        send_message(
            chat_id,
            f'✅ <b>연결 완료</b>\n\n{user.name} 님, 이제 구독 승인·만료 안내를 이 채팅으로 받습니다.',
        )

    next_offset = offset
    if max_update_id is not None:
        next_offset = max_update_id + 1
        if next_offset != offset:
            _write_offset(next_offset)

    return {'updates': len(updates), 'linked': linked, 'offset': next_offset, 'skipped': False}
