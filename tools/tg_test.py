"""Telegram test send — explicit dotenv path, verifies both main and channel bots."""
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import requests

# POSIX/Windows 호환: 스크립트 위치 기반으로 .env 해석
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

def check(label, token, chat_id):
    if not token or not chat_id:
        print(f"[{label}] MISSING token={bool(token)} chat_id={bool(chat_id)}")
        return False
    # getMe first
    r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    print(f"[{label}] getMe {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        return False
    msg = f"[marketflow test] {label} ok @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg},
        timeout=10,
    )
    print(f"[{label}] sendMessage {r.status_code}: {r.text[:300]}")
    return r.status_code == 200

main_token = os.getenv("TELEGRAM_BOT_TOKEN")
main_chat = os.getenv("TELEGRAM_CHAT_ID")
ch_token = os.getenv("TELEGRAM_CHANNEL_BOT_TOKEN")
ch_chat = os.getenv("TELEGRAM_CHANNEL_CHAT_ID")

print(f"main token={main_token[:10] if main_token else None}... chat={main_chat}")
print(f"chan token={ch_token[:10] if ch_token else None}... chat={ch_chat}")

ok_main = check("main", main_token, main_chat)
ok_chan = check("channel", ch_token, ch_chat)

if ok_main and ok_chan:
    print("ALL OK")
    sys.exit(0)
print(f"FAIL main={ok_main} channel={ok_chan}")
sys.exit(1)
