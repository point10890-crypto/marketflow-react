"""키움 AI전략 테마 TOP N → 텔레그램 전송.

스케줄러가 _run_kiwoom_ai_theme() 성공 후 호출하거나,
수동으로 즉시 재전송할 때 쓰는 스크립트.

정책:
- **분석 결과 → 개인 DM + 채널 양쪽 전송** (feedback_telegram_routing.md)
- 시간당 1회 쿨다운 (data/.kiwoom_tg_last.txt)
- --force 플래그로 쿨다운 우회 (수동 검증/재발송용)
- 한쪽 전송 실패해도 다른 쪽은 계속 시도 — 쿨다운은 어느 한쪽이라도 성공하면 갱신
"""
import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, 'data', 'kiwoom_ai_theme_latest.json')
COOLDOWN_FILE = os.path.join(BASE_DIR, 'data', '.kiwoom_tg_last.txt')
COOLDOWN_SEC = 3600  # 1 hour


def _load_cooldown() -> float:
    try:
        with open(COOLDOWN_FILE, 'r') as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def _save_cooldown(ts: float) -> None:
    try:
        with open(COOLDOWN_FILE, 'w') as f:
            f.write(str(ts))
    except Exception:
        pass


def build_message(data: dict, top_n: int = 15) -> str:
    lines = [
        "<b>🤖 키움 AI전략 테마 TOP " + str(top_n) + "</b>",
        f"조건식: {data.get('executed', 0)}/{data.get('total_conditions', 0)}  "
        f"종목: {data.get('unique_stocks', 0)}",
        "",
    ]
    for i, s in enumerate(data.get('stocks', [])[:top_n], 1):
        name = s.get('name', '?')
        chg = s.get('change_pct', 0.0) or 0.0
        try:
            price = int(str(s.get('price', 0)).replace(',', '').strip() or 0)
        except (ValueError, TypeError):
            price = 0
        hit = s.get('hit_count', 0)
        lines.append(f"{i:2d}. <b>{name}</b>  [{hit}/7]  {chg:+.2f}%  ({price:,})")
    ts = data.get('generated_at') or data.get('timestamp') or ''
    if ts:
        lines.append("")
        lines.append(f"<i>생성: {ts}</i>")
    return "\n".join(lines)


def _post(token: str, chat_id: str, text: str, label: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True},
            timeout=10,
        )
        body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
        ok = body.get('ok', False)
        msg_id = (body.get('result') or {}).get('message_id')
        print(f"[TG/{label}] status={r.status_code} ok={ok} msg_id={msg_id}")
        if not ok:
            print(f"[TG/{label}] body: {r.text[:200]}")
        return ok and bool(msg_id)
    except Exception as e:
        print(f"[TG/{label}] failed: {type(e).__name__}: {e}")
        return False


def send(force: bool = False, top_n: int = 15) -> int:
    if not os.path.exists(DATA_FILE):
        print(f"[ERR] no data file: {DATA_FILE}")
        return 2

    now = time.time()
    last = _load_cooldown()
    if not force and (now - last) < COOLDOWN_SEC:
        remain = int(COOLDOWN_SEC - (now - last))
        print(f"[SKIP] cooldown ({remain}s remaining, use --force to override)")
        return 0

    load_dotenv(os.path.join(BASE_DIR, '.env'))
    personal_token = os.getenv('TELEGRAM_BOT_TOKEN')
    personal_chat = os.getenv('TELEGRAM_CHAT_ID')
    channel_token = os.getenv('TELEGRAM_CHANNEL_BOT_TOKEN') or personal_token
    channel_chat = os.getenv('TELEGRAM_CHANNEL_CHAT_ID')

    targets: list[tuple[str, str, str]] = []
    if personal_token and personal_chat:
        targets.append(('personal', personal_token, personal_chat))
    if channel_token and channel_chat:
        targets.append(('channel', channel_token, channel_chat))

    if not targets:
        print("[ERR] telegram creds missing (personal/channel 둘 다 설정 안 됨)")
        return 1

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    text = build_message(data, top_n=top_n)
    any_ok = False
    for label, tok, cid in targets:
        if _post(tok, cid, text, label):
            any_ok = True
    if any_ok:
        _save_cooldown(now)
        return 0
    return 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='cooldown 우회')
    ap.add_argument('--top', type=int, default=15)
    args = ap.parse_args()
    sys.exit(send(force=args.force, top_n=args.top))
