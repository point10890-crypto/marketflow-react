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
    """Average precision over hits discovered within the top-k, normalized by
    the number of top-k hits (not by k)."""
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


def _pooled_block(all_items, top1, top3, top5):
    return {
        'top1_hit_rate': _hit_rate(top1),
        'top3_hit_rate': _hit_rate(top3),
        'top5_hit_rate': _hit_rate(top5),
        'baseline_hit_rate': _hit_rate(all_items),
        'top3_mean_return_pct': _mean_return(top3),
        'overall_mean_return_pct': _mean_return(all_items),
        'top3_hit_lift': _lift(_hit_rate(top3), _hit_rate(all_items)),
        'top3_return_lift': _lift(_mean_return(top3), _mean_return(all_items)),
        'top3_item_count': len(top3),
        'baseline_item_count': len(all_items),
    }


def _macro_block(run_records):
    qualified = [r for r in run_records if not r['insufficient']]

    def avg(key):
        vals = [r[key] for r in qualified if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    rank_ics = [r['rank_ic'] for r in qualified if r.get('rank_ic') is not None]
    return {
        'precision_at_1': avg('precision_at_1'),
        'precision_at_3': avg('precision_at_3'),
        'precision_at_5': avg('precision_at_5'),
        'ndcg_at_3': avg('ndcg_at_3'),
        'map_at_3': avg('map_at_3'),
        'rank_ic_mean': round(sum(rank_ics) / len(rank_ics), 4) if rank_ics else None,
        'rank_ic_run_count': len(rank_ics),
        'run_count': len(qualified),
    }


def _aggregate_runs(runs):
    """runs: list of {'workflow_id','entry_date','items'(list)}. Pure, deterministic."""
    run_records = []
    pooled_all, pooled_top1, pooled_top3, pooled_top5 = [], [], [], []
    evaluated_runs = 0
    qualified_runs = 0
    total_items = 0
    for run in (runs or []):
        if not isinstance(run, dict):
            continue
        ordered = _ordered_items(run.get('items'))
        if not ordered:
            continue
        evaluated_runs += 1
        total_items += len(ordered)
        record = _compute_run_metrics(
            run.get('items'),
            workflow_id=run.get('workflow_id'),
            entry_date=run.get('entry_date'),
        )
        run_records.append(record)
        if not record['insufficient']:
            qualified_runs += 1
        pooled_all.extend(ordered)
        pooled_top1.extend(ordered[:1])
        pooled_top3.extend(ordered[:3])
        pooled_top5.extend(ordered[:5])

    run_records.sort(key=lambda r: (r.get('entry_date') or '', r.get('workflow_id') or ''), reverse=True)
    return {
        'evaluated_runs': evaluated_runs,
        'qualified_runs': qualified_runs,
        'total_evaluated_items': total_items,
        'insufficient': qualified_runs < MIN_RUNS,
        'pooled': _pooled_block(pooled_all, pooled_top1, pooled_top3, pooled_top5),
        'macro': _macro_block(run_records),
        'runs': run_records[:MAX_RUN_RECORDS],
    }


def _load_runs(limit_workflows):
    runs = []
    try:
        wf_ids = outcome_tracker._recent_workflow_ids(limit_workflows)
    except Exception:
        return runs
    for wf_id in wf_ids:
        try:
            outcomes = outcome_tracker.read_workflow_outcomes(wf_id)
        except Exception:
            continue
        if not isinstance(outcomes, dict):
            continue
        items = outcomes.get('items')
        if not isinstance(items, list):
            continue
        # Workflow outcomes carry no top-level entry_date; it lives on each
        # item (outcome_tracker.evaluate_result_outcome). Derive it from the
        # first item so the run record's entry_date is load-bearing.
        entry_date = ''
        for it in items:
            if isinstance(it, dict) and it.get('entry_date'):
                entry_date = str(it.get('entry_date'))
                break
        runs.append({
            'workflow_id': str(wf_id),
            'entry_date': entry_date,
            'items': items,
        })
    return runs


def build_top3_metrics(*, limit_workflows=200, runs=None, write=True):
    if runs is None:
        runs = _load_runs(limit_workflows)
    aggregate = _aggregate_runs(runs)
    envelope = {
        'schema_version': SCHEMA_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'min_run_samples': MIN_RUN_SAMPLES,
        'min_runs': MIN_RUNS,
        **aggregate,
    }
    if write:
        try:
            os.makedirs(os.path.dirname(TOP3_METRICS_PATH), exist_ok=True)
            write_json_atomic(TOP3_METRICS_PATH, envelope, sort_keys=False)
        except Exception:
            pass
    return envelope


def read_top3_metrics():
    if not os.path.isfile(TOP3_METRICS_PATH):
        return None
    try:
        with open(TOP3_METRICS_PATH, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None


def _is_stale(generated_at: str) -> bool:
    """아티팩트 신선도 — 재빌드 주기(기본 24h) 초과 또는 파싱 불가면 stale."""
    try:
        refresh_hours = float(os.environ.get('MIROFISH_TOP3_REFRESH_HOURS', '24'))
    except (TypeError, ValueError):
        refresh_hours = 24.0
    try:
        ts = datetime.fromisoformat(str(generated_at).replace('Z', '+00:00'))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    return age_hours > refresh_hours


def top3_metrics_summary():
    """Compact, observation-friendly view. Builds+persists if file is missing."""
    data = read_top3_metrics()
    if not isinstance(data, dict):
        try:
            data = build_top3_metrics(write=True)
        except Exception:
            data = None
    if not isinstance(data, dict):
        return {'evaluated_runs': 0, 'qualified_runs': 0, 'total_evaluated_items': 0,
                'insufficient': True, 'pooled': {}, 'macro': {},
                'generated_at': None, 'stale': True}
    generated_at = data.get('generated_at') or None
    return {
        'evaluated_runs': data.get('evaluated_runs', 0),
        'qualified_runs': data.get('qualified_runs', 0),
        'total_evaluated_items': data.get('total_evaluated_items', 0),
        'insufficient': data.get('insufficient', True),
        'pooled': data.get('pooled') or {},
        'macro': data.get('macro') or {},
        'generated_at': generated_at,
        'stale': _is_stale(generated_at) if generated_at else True,
    }
