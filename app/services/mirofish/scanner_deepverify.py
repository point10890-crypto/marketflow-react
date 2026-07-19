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


# ── env ─────────────────────────────────────────────────────────────

def is_disabled() -> bool:
    return os.getenv('MIROFISH_TA_SCAN_DISABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _max_candidates() -> int:
    try:
        return max(1, int(str(os.getenv('MIROFISH_TA_SCAN_MAX', '3')).strip()))
    except (TypeError, ValueError):
        return 3


# ── selection / verify ──────────────────────────────────────────────

def _event_key(event: dict[str, Any]) -> str:
    key = event.get('event_key')
    if key:
        return str(key)
    from app.services.mirofish.alpha_scanner import _candidate_event_key  # lazy: avoid cycle
    return _candidate_event_key(event.get('candidate') or {})


def _select_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set(latest_by_event_key().keys())
    buy = [e for e in (events or [])
           if str((e.get('candidate') or {}).get('action') or '') in BUY_ACTIONS
           and _event_key(e) not in seen]
    buy.sort(key=lambda e: _num((e.get('candidate') or {}).get('alpha_score')), reverse=True)
    return buy[: _max_candidates()]


def enqueue_new_events(events: list[dict[str, Any]], run: dict[str, Any]) -> None:
    """검출 시점 호출. 킬스위치/무대상이면 즉시 반환. 대상 있으면 백그라운드 스레드로 검증."""
    if is_disabled():
        return
    selected = _select_events(events)
    if not selected:
        return
    threading.Thread(
        target=_verify_new_events, args=(selected, run or {}),
        name='ta-scan-verify', daemon=True,
    ).start()


def _verify_new_events(events: list[dict[str, Any]], run: dict[str, Any]) -> None:
    for event in events:
        try:
            _verify_one(event, run)
        except Exception as exc:  # noqa: BLE001 — isolate per-symbol failure
            logger.warning('[scanner_deepverify] verify failed for %s: %s',
                           (event.get('candidate') or {}).get('symbol'), exc)


def _verify_one(event: dict[str, Any], run: dict[str, Any]) -> None:
    from app.services.mirofish import store  # lazy: avoid heavy import at module load
    from app.services.mirofish.tradingagents import engine

    candidate = event.get('candidate') or {}
    name = candidate.get('display_name') or candidate.get('symbol')
    symbol = candidate.get('symbol')
    if not name:
        return
    try:
        brain = store._brain_summary(name)
    except Exception:  # noqa: BLE001 — brain optional; degrade to no regime
        brain = None
    ta = engine.run_deep_analysis(name, symbol=symbol, brain=brain)
    append_record(_build_record(event, run, brain, ta))


def _build_record(event: dict[str, Any], run: dict[str, Any],
                  brain: dict[str, Any] | None, ta: dict[str, Any]) -> dict[str, Any]:
    candidate = event.get('candidate') or {}
    v = (ta or {}).get('verdict') or {}
    adj = v.get('regime_adjustment') or {}
    return {
        'event_key': _event_key(event),
        'symbol': candidate.get('symbol'),
        'display_name': candidate.get('display_name'),
        'market': candidate.get('market'),
        'detected_at': run.get('generated_at') or event.get('sent_at'),
        'verified_at': datetime.now(timezone.utc).isoformat(),
        'verdict': v.get('verdict'),
        'confidence': v.get('confidence'),
        'strong_buy': bool(v.get('strong_buy')),
        'regime': v.get('regime'),
        'alignment': adj.get('alignment'),
        'regime_adjustment': adj,
        'method': ta.get('method'),
        'ta_run_id': ta.get('id'),
        'brain_snapshot_at': (brain or {}).get('snapshot_at'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
    }


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float('-inf')
