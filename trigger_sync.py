#!/usr/bin/env python3
"""GitHub Actions sync-data.yml 수동 트리거

사용법:
  python trigger_sync.py           # 전체 sync
  python trigger_sync.py --check   # Flask 헬스체크 후 필요시만 트리거

Flask 시작/재시작 시 start-local-deploy.bat / watchdog.bat에서 자동 호출됨.
"""

import os
import sys
import json
import time
import requests
from pathlib import Path

BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / '.env'

# ── .env 로드 ──
env = {}
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

GITHUB_PAT   = env.get('GITHUB_PAT', '')
REPO         = env.get('GITHUB_REPO', 'point10890-crypto/marketflow-react')
NGROK_DOMAIN = env.get('NGROK_DOMAIN', 'nonalliterated-sunshine-unaffiliated.ngrok-free.dev')
TG_TOKEN     = env.get('TELEGRAM_BOT_TOKEN', '')
TG_CHAT      = env.get('TELEGRAM_CHAT_ID', '')


def send_telegram(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception:
        pass


def check_flask_alive() -> bool:
    """Flask 헬스체크"""
    try:
        r = requests.get('http://localhost:5001/api/health', timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def check_snapshots_fresh() -> bool:
    """public/data/_meta.json이 6시간 이내인지 확인"""
    meta_path = BASE_DIR / 'frontend-react' / 'public' / 'data' / '_meta.json'
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        updated_at = meta.get('updated_at', '')
        if not updated_at:
            return False
        from datetime import datetime, timezone
        updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        age_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
        return age_hours < 6
    except Exception:
        return False


def trigger_workflow(scope: str = 'all') -> bool:
    """GitHub Actions sync-data.yml workflow_dispatch 트리거"""
    if not GITHUB_PAT:
        print("⚠️  GITHUB_PAT not set in .env — 자동 트리거 건너뜀")
        print("   설정법: .env에 GITHUB_PAT=ghp_xxxx 추가")
        print("   발급: https://github.com/settings/tokens → workflow 권한")
        return False

    url = f'https://api.github.com/repos/{REPO}/actions/workflows/sync-data.yml/dispatches'
    headers = {
        'Authorization': f'token {GITHUB_PAT}',
        'Accept': 'application/vnd.github.v3+json'
    }
    payload = {'ref': 'main', 'inputs': {'scope': scope}}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code == 204:
            print(f"✅ sync-data.yml 트리거 성공 (scope={scope})")
            return True
        else:
            print(f"❌ 트리거 실패: HTTP {r.status_code} — {r.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ 트리거 오류: {e}")
        return False


def main():
    check_mode = '--check' in sys.argv
    scope = 'all'
    for arg in sys.argv[1:]:
        if arg in ('kr', 'us', 'crypto'):
            scope = arg

    if check_mode:
        # Flask 살아있고 스냅샷이 오래됐을 때만 트리거
        if not check_flask_alive():
            print("⚠️  Flask 오프라인 — 트리거 생략")
            return
        if check_snapshots_fresh():
            print("✅ 스냅샷 최신 (6시간 이내) — 트리거 불필요")
            return
        print("⚠️  스냅샷 오래됨 → 트리거 실행")

    success = trigger_workflow(scope)

    if success:
        send_telegram(
            f"🔄 <b>MarketFlow 스냅샷 갱신 트리거</b>\n"
            f"GitHub Actions sync-data.yml 실행 시작\n"
            f"scope: {scope} | 약 2분 후 반영"
        )


if __name__ == '__main__':
    main()
