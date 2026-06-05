"""Kiwoom .env 키 head/tail 출력 (사용자 검증용)"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = (ROOT / '.env').read_text(encoding='utf-8')
for line in env.splitlines():
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.strip()
        if k in ('KIWOOM_APP_KEY', 'KIWOOM_APP_SECRET', 'KIWOOM_BASE_URL'):
            if len(v) >= 12:
                head = v[:6]
                tail = v[-6:]
                print(f'{k}: head={head} tail={tail} len={len(v)}')
            else:
                print(f'{k}: {v}')
