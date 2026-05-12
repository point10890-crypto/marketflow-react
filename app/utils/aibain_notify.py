"""AIbain_bot (t.me/AIbain_bot) 전용 텔레그램 알림 헬퍼.

전송 대상:
- 스캐닝된 신규 종목 5종 알림
- 워크플로우 TOP 3 신규 이벤트 알림

기존 시스템(개인봇/채널봇)과 독립적으로 동작 — AIbain_bot 만의 사일로.

환경변수:
- TELEGRAM_AIBAIN_BOT_TOKEN: 봇 토큰
- TELEGRAM_AIBAIN_CHAT_ID:    수신자/그룹/채널 chat_id
- AIBAIN_NOTIFY_ENABLED=1 로 활성화 (기본 0 — 안전)

키 누락 / disabled 시 silent skip (다른 알림 흐름 영향 0).
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv('AIBAIN_NOTIFY_ENABLED', '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def _token() -> str:
    return os.getenv('TELEGRAM_AIBAIN_BOT_TOKEN', '').strip()


def _chat_id() -> str:
    return os.getenv('TELEGRAM_AIBAIN_CHAT_ID', '').strip()


def is_configured() -> bool:
    return bool(_enabled() and _token() and _chat_id())


def send(message: str, *, parse_mode: str = 'HTML', disable_preview: bool = True) -> bool:
    """AIbain_bot 으로 메시지 전송. 미설정/비활성 시 silent False."""
    if not is_configured():
        return False
    token = _token()
    chat_id = _chat_id()
    # Telegram message limit 4096
    if len(message) > 4000:
        message = message[:3990] + '\n[…잘림]'
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': disable_preview,
            },
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get('ok'):
            return True
        logger.warning(f'[aibain] send failed: HTTP {resp.status_code} {resp.text[:200]}')
        return False
    except Exception as exc:
        logger.warning(f'[aibain] send exception: {type(exc).__name__}: {exc}')
        return False


def send_scanner_alert(message: str) -> bool:
    """스캐너 신규 5종 후보 알림 (header 자동 부착)."""
    if not is_configured():
        return False
    decorated = f'🆕 <b>신규 스캐닝 후보 5종</b>\n\n{message}'
    return send(decorated)


def send_workflow_top3(message: str) -> bool:
    """워크플로우 TOP 3 신규 이벤트 알림."""
    if not is_configured():
        return False
    decorated = f'🏆 <b>MCP TOP 3 신규 이벤트</b>\n\n{message}'
    return send(decorated)
