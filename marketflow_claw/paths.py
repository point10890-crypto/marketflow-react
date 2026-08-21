"""고정 경로 — 저장소 기준 상대 계산만 사용한다."""
from __future__ import annotations

import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_DIR = os.path.join(REPO_ROOT, 'data')
CLAW_DIR = os.path.join(DATA_DIR, 'claw')
DB_PATH = os.path.join(CLAW_DIR, 'claw.db')
HEARTBEAT_PATH = os.path.join(CLAW_DIR, 'heartbeat.json')
REPORTS_DIR = os.path.join(CLAW_DIR, 'reports')
LEADERS_LATEST = os.path.join(DATA_DIR, 'screener_leading_latest.json')
MARKET_GATE_CACHE = os.path.join(DATA_DIR, 'market_gate_cache.json')
DAILY_PRICES = os.path.join(DATA_DIR, 'daily_prices.csv')


def ensure_dirs() -> None:
    os.makedirs(CLAW_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
