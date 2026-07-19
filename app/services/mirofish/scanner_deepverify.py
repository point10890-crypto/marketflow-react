"""스캐너 신규 이벤트 자동 딥검증(13D 캡처 동시) + 히스토리 누적.

검출 시점에 매수후보 상위 K개를 백그라운드로 TradingAgents 딥검증(Brain 13D 주입)하고,
결과를 append-only 히스토리에 기록한다. 스캐너 폴링 스레드는 절대 블로킹하지 않는다.
env 는 호출 시점 read. 순환 임포트 회피: alpha_scanner 는 lazy import.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
HISTORY_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'scanner_tradingagents_history.json')
HISTORY_MAX = 500
BUY_ACTIONS = ('BUY_CANDIDATE', 'BUY')


# ── history store ───────────────────────────────────────────────────

def read_history() -> dict[str, Any]:
    try:
        import json
        with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('records'), list):
            return data
    except (OSError, ValueError):
        pass
    return {'version': 1, 'records': []}


def append_record(record: dict[str, Any]) -> None:
    data = read_history()
    records = data.get('records') or []
    records.append(record)
    if len(records) > HISTORY_MAX:
        records = records[-HISTORY_MAX:]
    data['version'] = 1
    data['records'] = records
    try:
        write_json_atomic(HISTORY_PATH, data, sort_keys=False)
    except Exception as exc:  # noqa: BLE001 — persistence must not raise into caller
        logger.warning('[scanner_deepverify] history write failed: %s', exc)


def latest_by_event_key() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for rec in read_history().get('records') or []:
        key = str(rec.get('event_key') or '')
        if not key:
            continue
        prev = latest.get(key)
        if prev is None or str(rec.get('verified_at') or '') >= str(prev.get('verified_at') or ''):
            latest[key] = _feed_summary(rec)
    return latest


def history(limit: int = 50) -> list[dict[str, Any]]:
    records = read_history().get('records') or []
    ordered = sorted(records, key=lambda r: str(r.get('verified_at') or ''), reverse=True)
    return ordered[: max(1, int(limit))]


def _feed_summary(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        'verdict': rec.get('verdict'),
        'confidence': rec.get('confidence'),
        'strong_buy': bool(rec.get('strong_buy')),
        'regime': rec.get('regime'),
        'regime_adjustment': rec.get('regime_adjustment'),
        'method': rec.get('method'),
        'ta_run_id': rec.get('ta_run_id'),
        'verified_at': rec.get('verified_at'),
    }
