"""키움 AI전략 테마 TOP N → 텔레그램 전송.

스케줄러가 _run_kiwoom_ai_theme() 성공 후 호출하거나,
수동으로 즉시 재전송할 때 쓰는 스크립트.

정책:
- 개인봇으로만 전송 (시스템 상태성 — 채널 노이즈 방지)
- 시간당 1회 쿨다운 (data/.kiwoom_tg_last.txt)
- --force 플래그로 쿨다운 우회 (수동 검증/재발송용)
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
        chg = s.get('change_pct', 0.0)
        price = s.get('price', 0)
        hit = s.get('hit_count', 0)
        lines.append(f"{i:2d}. <b>{name}</b>  [{hit}/7]  {chg:+.2f}%  ({price:,})")
    ts = data.get('generated_at') or data.get('timestamp') or ''
    if ts:
        lines.append("")
        lines.append(f"<i>생성: {ts}</i>")
    return "\n".join(lines)


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
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat:
        print("[ERR] telegram creds missing")
        return 1

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    text = build_message(data, top_n=top_n)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={'chat_id': chat, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True},
            timeout=10,
        )
        ok = r.json().get('ok', False)
        print(f"[TG] status={r.status_code} ok={ok}")
        if ok:
            _save_cooldown(now)
            return 0
        print(f"[TG] body: {r.text[:200]}")
        return 1
    except Exception as e:
        print(f"[TG] failed: {type(e).__name__}: {e}")
        return 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='cooldown 우회')
    ap.add_argument('--top', type=int, default=15)
    args = ap.parse_args()
    sys.exit(send(force=args.force, top_n=args.top))
