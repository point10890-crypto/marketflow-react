"""발송 — 기본 dry-run. 실발송은 send=True 와 CLAW_DELIVERY_ENABLED 둘 다 필요.

경로 선택 (비밀값은 절대 로그/DB/리포트에 남기지 않는다):
- CLAW_TELEGRAM_CHAT_ID 가 설정되면: CLAW_TELEGRAM_BOT_TOKEN_KEY(기본 TELEGRAM_CHANNEL_BOT_TOKEN,
  즉 @bitman75_bot) 토큰으로 그 채팅에 직접 sendMessage. 채널 발송 아님 — 사용자 개인 DM.
- 없으면: 기존 개인봇 경로 app.utils.scheduler._send_telegram_long(channel=False).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any

from marketflow_claw import memory
from marketflow_claw.paths import REPORTS_DIR, ensure_dirs

TELEGRAM_CHUNK = 4000
DEFAULT_TOKEN_KEY = 'TELEGRAM_CHANNEL_BOT_TOKEN'


def _enabled() -> bool:
    return os.environ.get('CLAW_DELIVERY_ENABLED', '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def route() -> dict[str, Any]:
    """현재 발송 경로 설명 (값은 노출하지 않음)."""
    chat = os.environ.get('CLAW_TELEGRAM_CHAT_ID', '').strip()
    key = os.environ.get('CLAW_TELEGRAM_BOT_TOKEN_KEY', DEFAULT_TOKEN_KEY).strip() or DEFAULT_TOKEN_KEY
    if chat:
        return {'mode': 'direct-dm', 'token_key': key, 'token_set': bool(os.environ.get(key)), 'chat_set': True}
    return {'mode': 'legacy-personal-bot', 'token_key': 'TELEGRAM_BOT_TOKEN',
            'token_set': bool(os.environ.get('TELEGRAM_BOT_TOKEN')), 'chat_set': bool(os.environ.get('TELEGRAM_CHAT_ID'))}


def _chunks(text: str) -> list[str]:
    if len(text) <= TELEGRAM_CHUNK:
        return [text]
    out, buf = [], ''
    for line in text.split('\n'):
        if len(buf) + len(line) + 1 > TELEGRAM_CHUNK:
            out.append(buf)
            buf = line
        else:
            buf = f'{buf}\n{line}' if buf else line
    if buf:
        out.append(buf)
    return out


def _send_direct(text: str) -> tuple[bool, str | None]:
    """직접 DM. 성공 = 모든 청크가 HTTP 200 + ok=true + message_id>0."""
    import requests
    r = route()
    token = os.environ.get(r['token_key'], '')
    chat = os.environ.get('CLAW_TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        return False, 'direct_route_not_configured'
    for chunk in _chunks(text):
        try:
            resp = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                 json={'chat_id': chat, 'text': chunk, 'parse_mode': 'HTML'}, timeout=15)
        except Exception as e:  # noqa: BLE001
            return False, f'network:{type(e).__name__}'
        body = {}
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            pass
        if resp.status_code != 200 or not body.get('ok') or not (body.get('result') or {}).get('message_id'):
            desc = str(body.get('description') or '')[:80]
            return False, f'http_{resp.status_code}:{desc}'
    return True, None


def write_report(kind: str, text: str) -> str:
    ensure_dirs()
    now = datetime.now()
    d = os.path.join(REPORTS_DIR, now.strftime('%Y%m%d'))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{kind}_{now.strftime('%H%M%S')}.md")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def deliver(kind: str, text: str, *, send: bool = False) -> dict[str, Any]:
    """리포트 파일은 항상 기록. 발송은 send && CLAW_DELIVERY_ENABLED 일 때만, digest 중복 차단."""
    digest = digest_of(text)
    path = write_report(kind, text)
    result = {'kind': kind, 'digest': digest, 'path': path, 'sent': False, 'mode': 'dry-run', 'error': None}
    if not send:
        with memory.connect() as con:
            memory.save_brief(con, kind, digest, path, False, None)
        return result
    if not _enabled():
        result['error'] = 'CLAW_DELIVERY_ENABLED is not set'
        with memory.connect() as con:
            memory.save_brief(con, kind, digest, path, False, result['error'])
        return result
    with memory.connect() as con:
        if memory.brief_exists(con, digest):
            result['error'] = 'duplicate_digest'
            return result

    r = route()
    if r['mode'] == 'direct-dm':
        ok, err = _send_direct(text)
    else:
        from app.utils.scheduler import _send_telegram_long
        ok, err = bool(_send_telegram_long(text, channel=False)), None
        if not ok:
            err = 'send_failed'
    result.update({'sent': ok, 'mode': r['mode'], 'error': err})
    with memory.connect() as con:
        memory.save_brief(con, kind, digest, path, ok, err)
    return result
