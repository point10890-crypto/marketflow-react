"""알림 — 사건이 열리고 닫힐 때만, 개인 Telegram 봇으로.

기본은 꺼져 있다(`CONTROL_CENTER_TELEGRAM_ENABLED=1` 일 때만 발송). 채널 봇으로는 보내지 않는다.
메시지에는 비밀값·내부 경로를 넣지 않는다. 보낸 기록은 events 테이블에 남긴다(중복 방지 근거).
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any

import requests

from app.services.control_center import store
from app.services.control_center.incidents import should_alert

ICON = {'open': '🚨', 'resolve': '✅'}
SEVERITY_KO = {'critical': '치명', 'standard': '일반', 'info': '참고'}


def enabled_by_env() -> bool:
    return (os.environ.get('CONTROL_CENTER_TELEGRAM_ENABLED') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def format_change(change: dict[str, Any], snapshot: dict[str, Any]) -> str:
    head = '사건 발생' if change['kind'] == 'open' else '복구'
    lines = [f"{ICON[change['kind']]} MarketFlow 관제 · {head} [{SEVERITY_KO.get(change['severity'], change['severity'])}]",
             f"{change['family']} · {change['check_id']}"]
    if change['kind'] == 'resolve' and change.get('opened_at'):
        lines.append(f"발생 {change['opened_at']}")
    c = snapshot.get('counts') or {}
    lines.append(f"전체 {snapshot.get('overall')} · 실패 {c.get('fail', 0)} · 열린 사건 {c.get('open_incidents', 0)}")
    return '\n'.join(lines)


def send_telegram(text: str) -> bool:
    token = (os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip()
    chat = (os.environ.get('TELEGRAM_CHAT_ID') or '').strip()
    if not token or not chat:
        return False
    try:
        resp = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                             json={'chat_id': chat, 'text': text, 'disable_web_page_preview': True}, timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def dispatch(conn: sqlite3.Connection, changes: list[dict[str, Any]], snapshot: dict[str, Any],
             enabled: bool | None = None, sender=send_telegram, *, commit_each: bool = False) -> int:
    enabled = enabled_by_env() if enabled is None else enabled
    sent = 0
    for ch in changes:
        if not should_alert(ch):
            store.add_event(conn, 'alert_suppressed', ch['check_id'], {'kind': ch['kind'], 'reason': 'info_or_flapping'})
            continue
        col = 'alerted_open' if ch['kind'] == 'open' else 'alerted_resolve'
        row = conn.execute(f'SELECT {col} FROM incidents WHERE id=?', (ch['incident_id'],)).fetchone()
        if row and row[0]:
            continue
        if ch['kind'] == 'resolve':
            opened = conn.execute('SELECT alerted_open FROM incidents WHERE id=?', (ch['incident_id'],)).fetchone()
            if not opened or not opened[0]:
                continue          # 열림 알림을 안 보낸 사건은 복구 알림도 보내지 않는다
        if not enabled:
            store.add_event(conn, 'alert_disabled', ch['check_id'], {'kind': ch['kind']})
            continue
        if commit_each:
            conn.commit()
        ok = sender(format_change(ch, snapshot))
        store.add_event(conn, 'alert_sent' if ok else 'alert_failed', ch['check_id'], {'kind': ch['kind']})
        if ok:
            conn.execute(f'UPDATE incidents SET {col}=1 WHERE id=?', (ch['incident_id'],))
            sent += 1
    return sent
