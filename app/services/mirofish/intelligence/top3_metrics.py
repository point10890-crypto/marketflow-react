"""TOP3 detection scorecard — lookahead-safe top-K quality metrics.

Deterministic, read-only, no LLM/network. Consumes already-evaluated
workflow outcomes (themselves lookahead-safe forward-price replays) and
measures how well the scanner's top-ranked picks performed, per run and
aggregated. Does NOT change scoring/ranking/alert behavior.
"""

import os
import json
import math
from datetime import datetime, timezone

from app.utils.atomic_json import write_json_atomic
from app.services.mirofish import outcome_tracker

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
TOP3_METRICS_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'intelligence', 'top3_metrics.json')

SCHEMA_VERSION = 'mirofish.top3_metrics.v1'
MIN_RUN_SAMPLES = 3
MIN_RUNS = 5
RANK_IC_MIN_SAMPLES = 3
MAX_RUN_RECORDS = 50


def _num(value):
    try:
        if value is None or value == '':
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ordered_items(items):
    """Evaluated items in scanner rank order: (rank ASC, ranking_score DESC, symbol ASC)."""
    evaluable = [
        it for it in (items or [])
        if isinstance(it, dict)
        and it.get('status') in {'evaluated', 'partial'}
        and it.get('hit') is not None
        and it.get('forward_return_pct') is not None
    ]

    def sort_key(it):
        rank = it.get('rank')
        rank_val = float(rank) if isinstance(rank, (int, float)) else math.inf
        feature = it.get('feature_snapshot') if isinstance(it.get('feature_snapshot'), dict) else {}
        return (rank_val, -_num(feature.get('ranking_score')), str(it.get('symbol') or ''))

    return sorted(evaluable, key=sort_key)


def _hit_rate(items):
    if not items:
        return None
    return round(sum(1 for it in items if it.get('hit') is True) / len(items), 4)


def _precision_at_k(items, k):
    top = items[:k]
    if not top:
        return None
    return round(sum(1 for it in top if it.get('hit') is True) / len(top), 4)


def _mean_return(items):
    if not items:
        return None
    return round(sum(_num(it.get('forward_return_pct')) for it in items) / len(items), 4)


def _ndcg_at_k(items, k):
    gains = [max(_num(it.get('forward_return_pct')), 0.0) for it in items]
    if not gains:
        return None

    def dcg(seq):
        return sum(g / math.log2(i + 2) for i, g in enumerate(seq[:k]))

    ideal = dcg(sorted(gains, reverse=True))
    if ideal <= 0:
        return 0.0
    return round(dcg(gains) / ideal, 4)


def _map_at_k(items, k):
    top = items[:k]
    if not top:
        return None
    num_hits = 0
    precision_sum = 0.0
    for i, it in enumerate(top, start=1):
        if it.get('hit') is True:
            num_hits += 1
            precision_sum += num_hits / i
    if num_hits == 0:
        return 0.0
    return round(precision_sum / num_hits, 4)


def _rank_of(values):
    """Average (tie-corrected) 1-based ranks."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def _spearman(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    r = _pearson(_rank_of(xs), _rank_of(ys))
    return round(r, 4) if r is not None else None


def _lift(a, b):
    if a is None or b is None:
        return None
    return round(a - b, 4)


def _compute_run_metrics(items, *, workflow_id='', entry_date=''):
    ordered = _ordered_items(items)
    n = len(ordered)
    precision_3 = _precision_at_k(ordered, 3)
    baseline = _hit_rate(ordered)
    top3_mean = _mean_return(ordered[:3])
    overall_mean = _mean_return(ordered)
    predicted = [n - i for i in range(n)]
    returns = [_num(it.get('forward_return_pct')) for it in ordered]
    rank_ic = _spearman(predicted, returns) if n >= RANK_IC_MIN_SAMPLES else None
    return {
        'workflow_id': str(workflow_id or ''),
        'entry_date': str(entry_date or (ordered[0].get('entry_date') if ordered else '') or ''),
        'n': n,
        'precision_at_1': _precision_at_k(ordered, 1),
        'precision_at_3': precision_3,
        'precision_at_5': _precision_at_k(ordered, 5),
        'top3_mean_return_pct': top3_mean,
        'baseline_hit_rate': baseline,
        'overall_mean_return_pct': overall_mean,
        'hit_lift_at_3': _lift(precision_3, baseline),
        'return_lift_at_3': _lift(top3_mean, overall_mean),
        'ndcg_at_3': _ndcg_at_k(ordered, 3),
        'map_at_3': _map_at_k(ordered, 3),
        'rank_ic': rank_ic,
        'insufficient': n < MIN_RUN_SAMPLES,
    }
