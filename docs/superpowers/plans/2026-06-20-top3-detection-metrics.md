# TOP3 Detection Scorecard (top3_metrics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lookahead-safe, read-only module that measures TOP3 (top-K) detection quality from evaluated workflow outcomes and attaches a compact summary to the alpha brain agent observation — without changing any scoring/ranking/alert behavior.

**Architecture:** New `app/services/mirofish/intelligence/top3_metrics.py` sits beside `regime.py`/`dataset.py`/`interactions.py`. It groups already-evaluated workflow outcome items per run (preserving `rank`), computes per-run top-K metrics (precision@k, NDCG@3, MAP@3, Rank IC, baseline lift), aggregates across runs (pooled micro + macro mean-of-runs), and writes `data/admin_mirofish/intelligence/top3_metrics.json`. `alpha_brain_agent._intelligence_summary()` attaches the compact summary via the existing try/except isolation pattern.

**Tech Stack:** Python 3.13, stdlib only (`math`, `json`, `os`, `datetime`), `app.utils.atomic_json.write_json_atomic`, pytest. No new dependencies, no LLM, no network.

**Environment (every command):**
```bash
PROJECT="/c/bitman_marketfloww"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
```

**Absolute rules:** Fixed paths via module `__file__`; never edit `outcome_tracker.py` (read-only consumer); deterministic sorting; isolated try/except in agent wiring; no behavior change to scoring/ranking/alerts.

---

## File Structure

- **Create:** `app/services/mirofish/intelligence/top3_metrics.py` — all metric logic + IO (one responsibility: measure TOP3 detection quality).
- **Create:** `tests/test_intelligence_top3_metrics.py` — unit tests for pure functions + envelope.
- **Modify:** `app/services/mirofish/alpha_brain_agent.py:370-396` (`_intelligence_summary`) and `:88-89` (`build_agent_observation` return) — attach `top3_metrics`.
- **Modify:** `tests/test_mirofish_alpha_brain_agent.py` — add isolation/attachment test.

---

### Task 1: Pure metric helpers + per-run metrics

**Files:**
- Create: `app/services/mirofish/intelligence/top3_metrics.py`
- Test: `tests/test_intelligence_top3_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intelligence_top3_metrics.py`:

```python
"""TOP3 detection scorecard tests — deterministic, lookahead-safe, no network."""
from app.services.mirofish.intelligence import top3_metrics


def _item(rank, ret, hit, *, symbol=None, ranking_score=0.0, status='evaluated'):
    return {
        'rank': rank,
        'symbol': symbol or f'{rank:06d}',
        'status': status,
        'hit': hit,
        'forward_return_pct': ret,
        'entry_date': '2026-06-10',
        'feature_snapshot': {'ranking_score': ranking_score},
    }


def test_ordered_items_filters_and_sorts():
    items = [
        _item(3, 1.0, True),
        _item(1, 9.0, True),
        {'rank': 2, 'symbol': 'x', 'status': 'pending', 'hit': None, 'forward_return_pct': None},
        _item(2, 4.0, False),
    ]
    ordered = top3_metrics._ordered_items(items)
    assert [it['rank'] for it in ordered] == [1, 2, 3]  # pending dropped, rank-sorted


def test_perfect_ranking_scores_top():
    # rank 1..4 with monotonically decreasing returns, top3 all hits
    items = [_item(1, 12.0, True), _item(2, 8.0, True), _item(3, 5.0, True), _item(4, -3.0, False)]
    m = top3_metrics._compute_run_metrics(items, workflow_id='wf1', entry_date='2026-06-10')
    assert m['n'] == 4
    assert m['precision_at_3'] == 1.0
    assert m['ndcg_at_3'] == 1.0
    assert m['rank_ic'] == 1.0
    assert m['baseline_hit_rate'] == 0.75
    assert m['hit_lift_at_3'] == 0.25
    assert m['insufficient'] is False


def test_reverse_ranking_negative_rank_ic():
    # scanner ranks ascending but realized returns ascending → bad ordering
    items = [_item(1, -3.0, False), _item(2, 5.0, True), _item(3, 8.0, True), _item(4, 12.0, True)]
    m = top3_metrics._compute_run_metrics(items, workflow_id='wf2')
    assert m['rank_ic'] == -1.0
    assert m['precision_at_3'] < 1.0


def test_small_run_marks_insufficient_and_null_rank_ic():
    items = [_item(1, 5.0, True), _item(2, -2.0, False)]
    m = top3_metrics._compute_run_metrics(items, workflow_id='wf3')
    assert m['n'] == 2
    assert m['insufficient'] is True
    assert m['rank_ic'] is None
    assert m['precision_at_1'] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_intelligence_top3_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.mirofish.intelligence.top3_metrics'`

- [ ] **Step 3: Write minimal implementation**

Create `app/services/mirofish/intelligence/top3_metrics.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_intelligence_top3_metrics.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd "$PROJECT" && git add app/services/mirofish/intelligence/top3_metrics.py tests/test_intelligence_top3_metrics.py
git commit -m "feat: add top3_metrics per-run metric helpers (TDD)"
```

---

### Task 2: Cross-run aggregation + envelope + IO

**Files:**
- Modify: `app/services/mirofish/intelligence/top3_metrics.py` (append functions)
- Test: `tests/test_intelligence_top3_metrics.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intelligence_top3_metrics.py`:

```python
def _run(wf, triples):
    # triples: list of (rank, ret, hit)
    return {'workflow_id': wf, 'entry_date': '2026-06-10',
            'items': [_item(r, ret, hit) for (r, ret, hit) in triples]}


def test_aggregate_pooled_and_macro():
    runs = [
        _run('wf1', [(1, 10.0, True), (2, 6.0, True), (3, 4.0, True), (4, -2.0, False)]),
        _run('wf2', [(1, 8.0, True), (2, -1.0, False), (3, 3.0, True), (4, -5.0, False)]),
    ]
    agg = top3_metrics._aggregate_runs(runs)
    assert agg['evaluated_runs'] == 2
    assert agg['qualified_runs'] == 2
    assert agg['total_evaluated_items'] == 8
    # pooled top3 = 6 items (3 per run), 5 hits → 0.8333
    assert agg['pooled']['top3_item_count'] == 6
    assert agg['pooled']['top3_hit_rate'] == round(5 / 6, 4)
    assert agg['pooled']['baseline_item_count'] == 8
    assert agg['pooled']['top3_hit_lift'] is not None
    assert agg['macro']['run_count'] == 2
    assert agg['macro']['precision_at_3'] is not None


def test_build_envelope_empty_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 't3.json'))
    env = top3_metrics.build_top3_metrics(runs=[], write=True)
    assert env['schema_version'] == 'mirofish.top3_metrics.v1'
    assert env['evaluated_runs'] == 0
    assert env['insufficient'] is True
    assert env['pooled']['top3_hit_rate'] is None
    assert env['macro']['precision_at_3'] is None
    # round-trips from disk
    assert top3_metrics.read_top3_metrics()['evaluated_runs'] == 0


def test_min_runs_gate_flags_insufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 't3.json'))
    runs = [_run(f'wf{i}', [(1, 5.0, True), (2, 3.0, True), (3, 1.0, False)]) for i in range(3)]
    env = top3_metrics.build_top3_metrics(runs=runs, write=False)
    assert env['qualified_runs'] == 3
    assert env['insufficient'] is True  # 3 < MIN_RUNS (5)
    assert len(env['runs']) == 3


def test_summary_compact_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 't3.json'))
    top3_metrics.build_top3_metrics(runs=[_run('wf1', [(1, 5.0, True), (2, 3.0, True), (3, 1.0, False)])], write=True)
    s = top3_metrics.top3_metrics_summary()
    assert set(['evaluated_runs', 'qualified_runs', 'insufficient', 'pooled', 'macro']).issubset(s.keys())
    assert 'runs' not in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_intelligence_top3_metrics.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_aggregate_runs'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/services/mirofish/intelligence/top3_metrics.py`:

```python
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
        runs.append({
            'workflow_id': str(wf_id),
            'entry_date': str(outcomes.get('entry_date') or ''),
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
                'insufficient': True, 'pooled': {}, 'macro': {}}
    return {
        'evaluated_runs': data.get('evaluated_runs', 0),
        'qualified_runs': data.get('qualified_runs', 0),
        'total_evaluated_items': data.get('total_evaluated_items', 0),
        'insufficient': data.get('insufficient', True),
        'pooled': data.get('pooled') or {},
        'macro': data.get('macro') or {},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_intelligence_top3_metrics.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
cd "$PROJECT" && git add app/services/mirofish/intelligence/top3_metrics.py tests/test_intelligence_top3_metrics.py
git commit -m "feat: add top3_metrics cross-run aggregation + envelope IO (TDD)"
```

---

### Task 3: Wire compact summary into the agent observation (isolated)

**Files:**
- Modify: `app/services/mirofish/alpha_brain_agent.py` (`_intelligence_summary` ~line 370-396; `build_agent_observation` return ~line 88-89)
- Test: `tests/test_mirofish_alpha_brain_agent.py` (append test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mirofish_alpha_brain_agent.py`:

```python
def test_observation_includes_top3_metrics(agent_env, monkeypatch):
    from app.services.mirofish import alpha_brain_agent as agent
    from app.services.mirofish.intelligence import top3_metrics as t3

    monkeypatch.setattr(t3, 'top3_metrics_summary', lambda: {
        'evaluated_runs': 4, 'qualified_runs': 3, 'total_evaluated_items': 24,
        'insufficient': True,
        'pooled': {'top3_hit_rate': 0.66, 'baseline_hit_rate': 0.5, 'top3_hit_lift': 0.16},
        'macro': {'precision_at_3': 0.66, 'rank_ic_mean': 0.21, 'run_count': 3},
    })

    obs = agent.build_agent_observation(now_iso='2026-06-20T08:00:00+00:00')

    assert obs['top3_metrics']['evaluated_runs'] == 4
    assert obs['top3_metrics']['pooled']['top3_hit_lift'] == 0.16
    assert obs['top3_metrics']['macro']['rank_ic_mean'] == 0.21
    # existing observation surface preserved
    assert 'interaction_map' in obs and 'regime_distribution' in obs and 'edge_map' in obs


def test_observation_survives_top3_metrics_failure(agent_env, monkeypatch):
    from app.services.mirofish import alpha_brain_agent as agent
    from app.services.mirofish.intelligence import top3_metrics as t3

    def boom():
        raise RuntimeError('top3 exploded')

    monkeypatch.setattr(t3, 'top3_metrics_summary', boom)

    obs = agent.build_agent_observation(now_iso='2026-06-20T08:00:00+00:00')

    assert obs['top3_metrics'] == {}  # isolated: empty, not a crash
    assert 'edge_map' in obs and 'regime_distribution' in obs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_alpha_brain_agent.py::test_observation_includes_top3_metrics tests/test_mirofish_alpha_brain_agent.py::test_observation_survives_top3_metrics_failure -v`
Expected: FAIL — `KeyError: 'top3_metrics'`

- [ ] **Step 3: Write minimal implementation**

In `app/services/mirofish/alpha_brain_agent.py`, modify `_intelligence_summary()`. Change the final block from:

```python
    try:
        from app.services.mirofish.intelligence import dataset as _dataset

        summary = _dataset.dataset_summary()
        if isinstance(summary, dict):
            regime_distribution = summary.get('regime_distribution') or {}
    except Exception as exc:
        logger.warning('[alpha_brain_agent] regime distribution unavailable: %s', exc)
    return {'interaction_map': interaction_map, 'regime_distribution': regime_distribution}
```

to:

```python
    try:
        from app.services.mirofish.intelligence import dataset as _dataset

        summary = _dataset.dataset_summary()
        if isinstance(summary, dict):
            regime_distribution = summary.get('regime_distribution') or {}
    except Exception as exc:
        logger.warning('[alpha_brain_agent] regime distribution unavailable: %s', exc)
    top3_metrics: dict[str, Any] = {}
    try:
        from app.services.mirofish.intelligence import top3_metrics as _top3_metrics

        summary = _top3_metrics.top3_metrics_summary()
        if isinstance(summary, dict):
            top3_metrics = summary
    except Exception as exc:
        logger.warning('[alpha_brain_agent] top3 metrics unavailable: %s', exc)
    return {
        'interaction_map': interaction_map,
        'regime_distribution': regime_distribution,
        'top3_metrics': top3_metrics,
    }
```

Also update the declarations near the top of `_intelligence_summary` are unchanged; only add `top3_metrics` local above (already added in the return block).

In `build_agent_observation()`, change the tail of the returned dict from:

```python
        'interaction_map': intelligence['interaction_map'],
        'regime_distribution': intelligence['regime_distribution'],
    }
```

to:

```python
        'interaction_map': intelligence['interaction_map'],
        'regime_distribution': intelligence['regime_distribution'],
        'top3_metrics': intelligence.get('top3_metrics', {}),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_alpha_brain_agent.py -v`
Expected: PASS (all existing + 2 new)

- [ ] **Step 5: Commit**

```bash
cd "$PROJECT" && git add app/services/mirofish/alpha_brain_agent.py tests/test_mirofish_alpha_brain_agent.py
git commit -m "feat: attach top3_metrics summary to alpha brain agent observation"
```

---

### Task 4: Verification (regression + smoke)

**Files:** none (verification only)

- [ ] **Step 1: Run the new + related intelligence/agent suites**

Run:
```bash
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest \
  tests/test_intelligence_top3_metrics.py \
  tests/test_intelligence_dataset.py \
  tests/test_intelligence_interactions.py \
  tests/test_intelligence_regime.py \
  tests/test_mirofish_alpha_brain_agent.py \
  tests/test_mirofish_edge_map.py -v
```
Expected: ALL PASS

- [ ] **Step 2: Confirm no behavior change to scoring (read-only guard)**

Run: `cd "$PROJECT" && git diff --stat main -- app/services/mirofish/alpha_scanner.py app/services/mirofish/outcome_tracker.py`
Expected: EMPTY output (these files untouched)

- [ ] **Step 3: Observation smoke test (real build path, no LLM)**

Run:
```bash
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
from app.services.mirofish.intelligence import top3_metrics as t3
env = t3.build_top3_metrics(write=False)
print('schema', env['schema_version'], 'runs', env['evaluated_runs'], 'insufficient', env['insufficient'])
s = t3.top3_metrics_summary()
assert set(['evaluated_runs','pooled','macro']).issubset(s.keys())
print('summary keys OK')
"
```
Expected: prints schema line + `summary keys OK`, no traceback.

- [ ] **Step 4: CLAUDE.md Skill 4 (imports + routes) regression**

Run the validation snippet from `CLAUDE.md` §10 Skill 4.
Expected: `ALL CHECKS PASSED`

- [ ] **Step 5: Commit (if any verification artifacts) / finalize**

No code change expected in Task 4. If clean, proceed to review.

---

## Self-Review

**Spec coverage:**
- §3 data source (workflow outcomes, rank preserved) → Task 2 `_load_runs`, Task 1 `_ordered_items`. ✓
- §4 interface (build/read/summary + pure fns) → Tasks 1-2. ✓
- §5 metrics (precision@k, lift, ndcg, rank_ic, map) → Task 1. ✓
- §5.2/5.3 aggregation + gates → Task 2 `_aggregate_runs`/`_macro_block` + `MIN_RUNS`. ✓
- §6 schema → Task 2 envelope + empty-safe test. ✓
- §7 agent wiring (isolated) → Task 3 + isolation test. ✓
- §8 tests (perfect/reverse/small/empty/aggregate/isolation) → Tasks 1-3. ✓
- §9 verification → Task 4. ✓

**Placeholder scan:** none.

**Type consistency:** `_ordered_items`, `_compute_run_metrics(items, *, workflow_id, entry_date)`, `_aggregate_runs(runs)`, `build_top3_metrics(*, limit_workflows, runs, write)`, `read_top3_metrics()`, `top3_metrics_summary()` used consistently across tasks and tests. Envelope keys in §6 match `_aggregate_runs` + `build_top3_metrics` output. Agent return key `top3_metrics` matches test assertions.
