"""Deterministic edge-map mining from evaluated MiroFish outcomes.

평가 완료된 outcome 을 특징 버킷별로 집계해 수익 통계를 만든다.
LLM 가설 생성의 원료 — LLM 호출 없음, lookahead-safe 표본만 사용.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

from app.services.mirofish import outcome_tracker
from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
EDGE_MAP_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'edge_map.json')

MIN_BUCKET_SAMPLES = 5
ALPHA_BANDS = (
    (0.0, 60.0, 'lt60'),
    (60.0, 70.0, '60-70'),
    (70.0, 80.0, '70-80'),
    (80.0, 1000.0, '80+'),
)


def build_edge_map(*, limit_workflows: int = 200, write: bool = True) -> dict[str, Any]:
    """Aggregate evaluated outcomes into profit-statistics buckets."""
    items = _evaluated_items(limit_workflows)
    result = {
        'schema_version': 'mirofish.edge_map.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'evaluated_count': len(items),
        'min_bucket_samples': MIN_BUCKET_SAMPLES,
        'overall': _stats(items),
        'by_tag': _group(items, _item_tags),
        'by_alpha_band': _group(items, lambda it: [_alpha_band(it)]),
        'by_market': _group(items, lambda it: [outcome_tracker._infer_market(str(it.get('symbol') or ''))]),
        'by_action': _group(items, lambda it: [str(_feature(it).get('scanner_action') or '')]),
        'by_signal_quality': _group(items, lambda it: [str(_feature(it).get('signal_quality') or '')]),
    }
    if write:
        write_json_atomic(EDGE_MAP_PATH, result, sort_keys=False)
    return result


def read_edge_map() -> dict[str, Any] | None:
    import json

    try:
        with open(EDGE_MAP_PATH, 'r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _collect_raw_items(limit_workflows: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for wf_id in outcome_tracker._recent_workflow_ids(limit_workflows):
        try:
            outcomes = outcome_tracker.read_workflow_outcomes(wf_id)
        except (ValueError, OSError, KeyError):
            continue
        if not isinstance(outcomes, dict):
            continue
        items.extend(it for it in (outcomes.get('items') or []) if isinstance(it, dict))
    return items


def _evaluated_items(limit_workflows: int) -> list[dict[str, Any]]:
    return [
        it for it in _collect_raw_items(limit_workflows)
        if it.get('status') in {'evaluated', 'partial'} and it.get('hit') is not None
    ]


def _feature(item: dict[str, Any]) -> dict[str, Any]:
    feature = item.get('feature_snapshot')
    return feature if isinstance(feature, dict) else {}


def _item_tags(item: dict[str, Any]) -> list[str]:
    tags = _feature(item).get('strategy_tags')
    if not isinstance(tags, list):
        return []
    return [str(tag).strip() for tag in tags if str(tag or '').strip()]


def _alpha_band(item: dict[str, Any]) -> str:
    try:
        alpha = float(_feature(item).get('alpha_score') or 0.0)
    except (TypeError, ValueError):
        alpha = 0.0
    for low, high, label in ALPHA_BANDS:
        if low <= alpha < high:
            return label
    return 'lt60'


def _group(
    items: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], list[str]],
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for key in key_fn(item):
            if key:
                buckets.setdefault(key, []).append(item)
    return {key: _stats(bucket) for key, bucket in sorted(buckets.items())}


def _stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(items)
    if n == 0:
        return {'n': 0, 'hit_rate': None, 'expectancy_pct': None, 'insufficient': True}
    hits = sum(1 for it in items if it.get('hit') is True)
    returns = [_num(it.get('forward_return_pct')) for it in items]
    return {
        'n': n,
        'hit_rate': round(hits / n, 4),
        'expectancy_pct': round(sum(returns) / n, 4),
        'insufficient': n < MIN_BUCKET_SAMPLES,
    }


def _num(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
