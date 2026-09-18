"""LLM 실측 비용 원장 — data/llm_cost_ledger.json (KST 일자별).

리뷰(2026-09-02 §3.5 ⑦): auto_runner 는 트리거당 고정 $0.07 을 더해 일일 캡을 판정했다.
Phase 0 에서 llm_client 메타데이터에 ``est_cost_usd`` 가 붙었으므로, 트리거 한 번의
LLM 호출을 ``collect_generation_metadata()`` 로 모아 실측 합계를 기록한다.

원장 구조::

    {
      "2026-09-03": {
        "usd": 0.1234,            # 실측(또는 추정 폴백) 합계
        "calls": 17,              # 메타데이터가 잡힌 LLM 호출 수 (캐시 적중 포함)
        "cache_hits": 3,
        "triggers": 2,            # 비용을 기록한 트리거 수
        "estimated_calls": 1,     # 실측 0/None 이라 고정 추정치로 대체한 트리거 수
        "by_model": {"deepseek-v4-flash": {"usd": 0.1, "calls": 15}, ...}
      }
    }

원장은 운영 가시성용이며 청구 기준이 아니다. 모르는 모델(단가표 없음)은 usd 0 으로
집계되므로 ``by_model`` 의 calls 와 usd 가 어긋나면 llm_pricing 단가표를 보강해야 한다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic
from app.utils.paths import DATA_DIR

logger = logging.getLogger(__name__)

LEDGER_PATH = os.path.join(DATA_DIR, 'llm_cost_ledger.json')
_lock = threading.Lock()
_RETENTION_DAYS = 400

try:
    from zoneinfo import ZoneInfo

    KST = ZoneInfo('Asia/Seoul')
except Exception:  # pragma: no cover
    KST = timezone(timedelta(hours=9))


def _today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _read_ledger() -> dict[str, Any]:
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def summarize_llm_calls(llm_calls: list[dict[str, Any]] | None) -> dict[str, Any]:
    """collect_generation_metadata() 결과를 (usd, calls, by_model, cache_hits) 로 접는다."""
    usd = 0.0
    priced = 0
    cache_hits = 0
    by_model: dict[str, dict[str, Any]] = {}
    for meta in llm_calls or []:
        if not isinstance(meta, dict):
            continue
        if meta.get('cache_hit'):
            cache_hits += 1
        attempts = meta.get('attempts') or []
        # 시도별 비용이 있으면 그것을(폴백으로 두 번 지불한 경우 포함), 없으면 합계 필드를 쓴다
        if attempts:
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                model = str(attempt.get('model') or 'unknown')
                bucket = by_model.setdefault(model, {'usd': 0.0, 'calls': 0})
                bucket['calls'] += 1
                cost = attempt.get('est_cost_usd')
                if cost is not None:
                    bucket['usd'] = round(bucket['usd'] + float(cost), 6)
                    usd += float(cost)
                    priced += 1
        else:
            model = str(meta.get('model') or ('cache' if meta.get('cache_hit') else 'unknown'))
            bucket = by_model.setdefault(model, {'usd': 0.0, 'calls': 0})
            bucket['calls'] += 1
            cost = meta.get('est_cost_usd')
            if cost is not None:
                bucket['usd'] = round(bucket['usd'] + float(cost), 6)
                usd += float(cost)
                priced += 1
    return {
        'usd': round(usd, 6),
        'calls': len([m for m in (llm_calls or []) if isinstance(m, dict)]),
        'priced_calls': priced,
        'cache_hits': cache_hits,
        'by_model': by_model,
    }


def record_trigger_cost(llm_calls: list[dict[str, Any]] | None, *, fallback_usd: float,
                        date_kst: str | None = None) -> dict[str, Any]:
    """트리거 한 번의 실측 비용을 원장에 더하고 이번 트리거의 비용 요약을 돌려준다.

    실측 합계가 None/0 이면(단가표 없는 모델, usage 미제공, 캐시만 적중) ``fallback_usd``
    고정 추정치를 쓰고 ``estimated=True`` 로 표시한다 — 캡 판정이 0 으로 무력화되지 않게.
    """
    summary = summarize_llm_calls(llm_calls)
    measured = float(summary['usd'] or 0.0)
    only_cache = summary['calls'] > 0 and summary['cache_hits'] == summary['calls']
    if measured <= 0 and not only_cache:
        estimated = True
        usd = float(fallback_usd or 0.0)
        logger.info(
            '[llm_cost_ledger] measured cost unavailable (calls=%s priced=%s) — using flat estimate $%.4f',
            summary['calls'], summary['priced_calls'], usd,
        )
    else:
        estimated = False
        usd = measured

    day = date_kst or _today_kst()
    with _lock:
        ledger = _read_ledger()
        entry = ledger.get(day) if isinstance(ledger.get(day), dict) else {}
        entry = {
            'usd': round(float(entry.get('usd') or 0.0) + usd, 6),
            'calls': int(entry.get('calls') or 0) + int(summary['calls']),
            'cache_hits': int(entry.get('cache_hits') or 0) + int(summary['cache_hits']),
            'triggers': int(entry.get('triggers') or 0) + 1,
            'estimated_calls': int(entry.get('estimated_calls') or 0) + (1 if estimated else 0),
            'by_model': dict(entry.get('by_model') or {}),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        for model, bucket in summary['by_model'].items():
            prev = entry['by_model'].get(model) if isinstance(entry['by_model'].get(model), dict) else {}
            entry['by_model'][model] = {
                'usd': round(float(prev.get('usd') or 0.0) + float(bucket['usd']), 6),
                'calls': int(prev.get('calls') or 0) + int(bucket['calls']),
            }
        ledger[day] = entry
        # 오래된 날짜 정리 (원장이 무한히 자라지 않게)
        if len(ledger) > _RETENTION_DAYS:
            for stale in sorted(ledger)[:-_RETENTION_DAYS]:
                ledger.pop(stale, None)
        try:
            write_json_atomic(LEDGER_PATH, ledger, sort_keys=True)
        except Exception as exc:  # noqa: BLE001 — 원장 쓰기 실패가 트리거를 죽이면 안 된다
            logger.warning('[llm_cost_ledger] write failed: %s', type(exc).__name__)

    return {
        'usd': round(usd, 6),
        'measured_usd': round(measured, 6),
        'estimated': estimated,
        'calls': summary['calls'],
        'cache_hits': summary['cache_hits'],
        'by_model': summary['by_model'],
        'date_kst': day,
    }


def get_llm_cost_summary(days: int = 7) -> dict[str, Any]:
    """최근 ``days`` 일(KST) 원장 요약 — 관리자 status JSON 용 (비밀값 없음)."""
    days = max(1, int(days or 7))
    today = datetime.now(KST).date()
    wanted = {(today - timedelta(days=offset)).isoformat() for offset in range(days)}
    ledger = _read_ledger()
    by_date: dict[str, Any] = {}
    total_usd = 0.0
    total_calls = 0
    total_cache_hits = 0
    total_triggers = 0
    estimated_calls = 0
    by_model: dict[str, dict[str, Any]] = {}
    for day in sorted(wanted):
        entry = ledger.get(day)
        if not isinstance(entry, dict):
            continue
        by_date[day] = {
            'usd': round(float(entry.get('usd') or 0.0), 6),
            'calls': int(entry.get('calls') or 0),
            'cache_hits': int(entry.get('cache_hits') or 0),
            'triggers': int(entry.get('triggers') or 0),
            'estimated_calls': int(entry.get('estimated_calls') or 0),
        }
        total_usd += by_date[day]['usd']
        total_calls += by_date[day]['calls']
        total_cache_hits += by_date[day]['cache_hits']
        total_triggers += by_date[day]['triggers']
        estimated_calls += by_date[day]['estimated_calls']
        for model, bucket in (entry.get('by_model') or {}).items():
            if not isinstance(bucket, dict):
                continue
            agg = by_model.setdefault(str(model), {'usd': 0.0, 'calls': 0})
            agg['usd'] = round(agg['usd'] + float(bucket.get('usd') or 0.0), 6)
            agg['calls'] += int(bucket.get('calls') or 0)
    today_entry = by_date.get(today.isoformat()) or {}
    return {
        'days': days,
        'total_usd': round(total_usd, 6),
        'total_calls': total_calls,
        'total_cache_hits': total_cache_hits,
        'total_triggers': total_triggers,
        'estimated_calls': estimated_calls,
        'today_usd': round(float(today_entry.get('usd') or 0.0), 6),
        'avg_usd_per_trigger': round(total_usd / total_triggers, 6) if total_triggers else None,
        'by_date': by_date,
        'by_model': by_model,
    }
