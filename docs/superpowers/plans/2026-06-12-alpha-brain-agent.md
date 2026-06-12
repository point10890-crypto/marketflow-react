# MiroFish Alpha Brain Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 알파 파이프라인의 죽어있는 학습 루프를 되살리고, 엣지맵 통계 → LLM 가설 → 오프라인 리플레이 검증 → bounded 적용 → 자동 롤백으로 검출 수익률(Top3 전방 expectancy)을 스스로 개선하는 사이클형 자율 에이전트를 구축한다.

**Architecture:** `app/services/mirofish/` 안에 4개 신규 모듈(edge_map, hypothesis_replay, agent_actions, alpha_brain_agent)을 추가하고, 기존 3곳(autonomous_mcp, auto_runner, alpha_scanner)에 소비 지점을 끼워 넣는다. 에이전트는 scheduler가 16:30/23:30 KST에 호출하는 인프로세스 사이클(Sense→Think→Act→Learn)이며, LLM은 `llm_client.generate_text` 폴백 체인을 사이클당 최대 3회 사용한다. 모든 변형은 결정론적 실행기가 하드 바운드로 재검증하고, 성과 악화 시 결정론적으로 롤백한다.

**Tech Stack:** Python 3.13, Flask Blueprint, pytest, 기존 `llm_client`(deepseek→openai→gemini), `write_json_atomic`, `schedule` 라이브러리.

**Spec:** `docs/superpowers/specs/2026-06-12-alpha-brain-agent-design.md`

**스코프 결정 (스펙 대비 1건 조정):** 스펙 4.6의 `trigger_reanalysis`(손실 종목 워크플로우 재실행)와 별도 부검 액션은 v1에서 구현하지 않는다. 손실 패턴 환류는 v1에서 **엣지맵의 음수 expectancy 버킷 → LLM이 음수 `apply_scoring_delta` 제안 → 리플레이 게이트 통과 시 적용** 경로로 충족된다 (Think 프롬프트에 엣지맵 손실 버킷이 포함되므로). 전용 부검 액션과 워크플로우 재실행은 outcome 표본이 쌓인 뒤 후속 작업으로 미룬다.

---

## 사전 지식 (모든 태스크 공통)

- 실행 환경: `PROJECT="/c/bitman_marketfloww"`, `PYTHON="$PROJECT/.venv/Scripts/python.exe"`, 모든 Python 실행에 `PYTHONIOENCODING=utf-8` 필수 (CLAUDE.md §1).
- 테스트 실행: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/<file> -q`
- 데이터 루트: `data/admin_mirofish/` (이하 "DATA"). 모든 JSON 쓰기는 `app.utils.atomic_json.write_json_atomic` 사용.
- 기존 핵심 구조 (이 계획에서 사용하는 것만):
  - `outcome_tracker.read_workflow_outcomes(wf_id)` → `{'items': [...], 'summary': {...}}`. item 필드: `symbol, entry_date, entry_price, status('evaluated'|'partial'|'pending'|'missing_entry'), hit(bool|None), forward_return_pct, feature_snapshot{alpha_score, risk_score, strategy_tags[], scanner_action, signal_quality, ...}`
  - `outcome_tracker.get_advisory_feedback(horizon_days=5, limit_workflows=200)` → `{'evaluated_count', 'hit_rate_recent', 'by_strategy_tag', 'recommendations': {'tag_score_adjust': {tag: delta}, 'baseline_hit_rate'}, 'lookahead_safe', 'asof'}`
  - `outcome_tracker._recent_workflow_ids(limit)`, `outcome_tracker._infer_market(symbol)` — 같은 패키지 내 재사용 허용
  - `autonomous_mcp.refresh_learning_feedback(payload)` — 533~567행 루프가 workflow별 `refresh_workflow_outcomes` 호출 + `learning_feedback.json` 기록. `commit=True`일 때 `_require_mutation` 게이트 (env `MIROFISH_MCP_ALLOW_MUTATION`).
  - `scripts/backtest_alpha_signals.py` — 패키지 아님. `_load_price_dates, _mature_cutoff_date, _load_runs, _load_prices, _sample, _correlation, _float, evaluate_runs, write_report, write_rolling_report` 보유. `_sample` 반환: `{symbol, action, alpha_score, risk_score, ranking_score, entry_date, exit_date, entry_price, exit_price, return_pct, r_multiple}`. 테스트에서 importlib로 로드하는 선례: `tests/scripts/test_backtest_alpha_signals.py`
  - `learning_policy.build_learning_policy(advisory)` → `{'score_control': {'outcome_memory_enabled', 'status', ...}, 'backtest_gate': {'status': 'missing|stale|insufficient_sample|defensive|watch|ready|validated|unsafe', ...}, 'outcome_memory': {...}}`
  - `alpha_scanner._performance_advisory()` (3332행) — advisory + learning_policy 병합. `recommendations.tag_score_adjust`가 스캐너 태그 델타의 단일 소스. 적용 시 `learning_policy.tag_delta_bounds`로 클램프됨(±2.0).
  - `auto_runner._tunables()` (100~120행) — env 기반 튜너블. `min_alpha`(기본 70.0), `max_risk`(45.0), `min_top_score`(50.0)
  - `scheduler.py` — `Config` 클래스(380행~)에 env 설정, `run_alpha_backtest_daily()`(801행), 스케줄 등록부(3340행~, `getattr(schedule.every(), day).at(hm).do(...)` 주중 패턴 / `schedule.every().day.at(...)` 매일 패턴, `self._with_record(fn, name, ...)` 래퍼)
  - `app/routes/admin_mirofish.py` — `admin_mirofish_bp` Blueprint, `@admin_or_aibain_required` 데코레이터
  - `app/services/mirofish/mcp_server.py` — `@mcp.tool()` 등록 패턴
  - 텔레그램: `from app.utils.scheduler import _send_telegram_long; _send_telegram_long(msg, channel=False)` (개인봇 전용)
  - `llm_client.generate_text(prompt, system=..., json_mode=True, max_tokens=...) -> str | None` — 폴백 체인 내장, 전부 실패 시 None

**신규 파일 구조:**

| 파일 | 책임 |
|---|---|
| `app/services/mirofish/edge_map.py` | 평가된 outcome → 버킷별 수익 통계 (결정론적) |
| `app/services/mirofish/hypothesis_replay.py` | 태그 델타 가설의 lookahead-safe 오프라인 리플레이 검증 |
| `app/services/mirofish/agent_actions.py` | 오버라이드/오버레이 스토어 + 하드 바운드 + 화이트리스트 실행기 + 롤백 |
| `app/services/mirofish/alpha_brain_agent.py` | 사이클 오케스트레이터 (Sense→Think→Act→Learn), 저널, 서킷 브레이커 |

**신규 데이터 파일 (전부 DATA 하위):** `edge_map.json`, `agent_overrides.json`, `agent_scoring_overlay.json`, `agent_state.json`, `agent_journal.jsonl`

---

### Task 1: Edge Map 모듈 (결정론적 패턴 마이닝)

**Files:**
- Create: `app/services/mirofish/edge_map.py`
- Test: `tests/test_mirofish_edge_map.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_mirofish_edge_map.py
"""Edge map mining tests — deterministic, no LLM, no network."""
import json

from app.services.mirofish import edge_map


def _item(symbol='005930', hit=True, ret=6.0, tags=('volume_surge',), alpha=78.0,
          action='BUY_CANDIDATE', status='evaluated'):
    return {
        'symbol': symbol,
        'status': status,
        'hit': hit,
        'forward_return_pct': ret,
        'feature_snapshot': {
            'alpha_score': alpha,
            'strategy_tags': list(tags),
            'scanner_action': action,
            'signal_quality': 'A',
        },
    }


def test_build_edge_map_aggregates_by_tag_and_band(tmp_path, monkeypatch):
    items = (
        [_item(hit=True, ret=8.0, tags=('volume_surge', 'foreign_buy'), alpha=82.0)] * 6
        + [_item(hit=False, ret=-4.0, tags=('volume_surge',), alpha=65.0)] * 4
    )
    monkeypatch.setattr(edge_map, '_evaluated_items', lambda limit_workflows: items)
    out_path = tmp_path / 'edge_map.json'
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(out_path))

    result = edge_map.build_edge_map(limit_workflows=50)

    assert result['schema_version'] == 'mirofish.edge_map.v1'
    assert result['lookahead_safe'] is True
    assert result['evaluated_count'] == 10
    surge = result['by_tag']['volume_surge']
    assert surge['n'] == 10
    assert surge['hit_rate'] == 0.6
    assert surge['expectancy_pct'] == round((8.0 * 6 - 4.0 * 4) / 10, 4)
    assert surge['insufficient'] is False
    # foreign_buy: n=6 → 충분, 80+ 밴드만 존재
    assert result['by_tag']['foreign_buy']['n'] == 6
    assert result['by_alpha_band']['80+']['n'] == 6
    assert result['by_alpha_band']['60-70']['n'] == 4
    assert result['by_action']['BUY_CANDIDATE']['n'] == 10
    # 파일이 기록되었는지
    saved = json.loads(out_path.read_text(encoding='utf-8'))
    assert saved['evaluated_count'] == 10


def test_build_edge_map_marks_insufficient_buckets(monkeypatch, tmp_path):
    items = [_item(tags=('rare_tag',))] * 3  # MIN_BUCKET_SAMPLES(5) 미만
    monkeypatch.setattr(edge_map, '_evaluated_items', lambda limit_workflows: items)
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(tmp_path / 'edge_map.json'))

    result = edge_map.build_edge_map()

    assert result['by_tag']['rare_tag']['insufficient'] is True


def test_build_edge_map_skips_unevaluated_items(monkeypatch, tmp_path):
    items = [
        _item(status='evaluated'),
        _item(status='pending', hit=None, ret=None),
        _item(status='missing_entry', hit=None, ret=None),
    ]
    monkeypatch.setattr(
        edge_map, '_collect_raw_items', lambda limit_workflows: items
    )
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(tmp_path / 'edge_map.json'))

    result = edge_map.build_edge_map()

    assert result['evaluated_count'] == 1


def test_build_edge_map_empty_outcomes(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_map, '_collect_raw_items', lambda limit_workflows: [])
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(tmp_path / 'edge_map.json'))

    result = edge_map.build_edge_map()

    assert result['evaluated_count'] == 0
    assert result['by_tag'] == {}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_edge_map.py -q`
Expected: FAIL — `ModuleNotFoundError` 또는 `ImportError: cannot import name 'edge_map'`

- [ ] **Step 3: 구현**

```python
# app/services/mirofish/edge_map.py
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_edge_map.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/edge_map.py tests/test_mirofish_edge_map.py
git commit -m "feat: add edge map outcome pattern mining for alpha brain agent"
```

---

### Task 2: Hypothesis Replay 모듈 (오프라인 리플레이 검증)

**Files:**
- Create: `app/services/mirofish/hypothesis_replay.py`
- Test: `tests/test_mirofish_hypothesis_replay.py`

검증 로직: 과거 스캐너 런의 후보들에 "tag 보유 시 alpha_score + delta"를 적용해 점수를 재계산하고, 점수↔전방수익 IC와 상위 25% 평균수익이 **둘 다** baseline 대비 개선될 때만 `passed=True`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_mirofish_hypothesis_replay.py
"""Hypothesis replay validation tests — synthetic samples, no disk scan."""
from app.services.mirofish import hypothesis_replay as hr


def _sample(symbol, ret, alpha, tags):
    return {
        'symbol': symbol,
        'return_pct': ret,
        'alpha_score': alpha,
        'strategy_tags': list(tags),
    }


def _good_tag_samples():
    # 두 그룹 모두 alpha 60..89 균등 분포 (그룹 내 변동 필수 — 그룹 내 alpha 가
    # 상수면 점수가 2값 변수가 되어 상관계수가 델타에 불변이라 검증 불가).
    # baseline IC ≈ 0. good_tag 그룹은 수익(+), other 그룹은 손실(-) 이므로
    # good_tag 에 양수 델타를 주면 IC 가 양수로 개선된다.
    samples = []
    for i in range(30):
        samples.append(_sample(f'A{i:04d}', 5.0 + (i % 3), 60.0 + i, ('good_tag',)))
    for i in range(30):
        samples.append(_sample(f'B{i:04d}', -5.0 - (i % 3), 60.0 + i, ('other_tag',)))
    return samples


def test_replay_passes_when_delta_improves_ranking(monkeypatch):
    monkeypatch.setattr(hr, '_collect_samples', lambda **kw: _good_tag_samples())
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('good_tag', 2.0)

    assert report['passed'] is True
    assert report['sample_count'] == 60
    assert report['tagged_count'] == 30
    assert report['adjusted']['ic'] > report['baseline']['ic']
    assert report['lookahead_safe'] is True


def test_replay_fails_when_delta_hurts_ranking(monkeypatch):
    # good_tag 종목이 수익인데 음수 델타 → 랭킹 악화 → 기각
    monkeypatch.setattr(hr, '_collect_samples', lambda **kw: _good_tag_samples())
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('good_tag', -2.0)

    assert report['passed'] is False


def test_replay_fails_on_insufficient_samples(monkeypatch):
    monkeypatch.setattr(hr, '_collect_samples', lambda **kw: _good_tag_samples()[:10])

    report = hr.replay_tag_delta('good_tag', 1.0)

    assert report['passed'] is False
    assert report['reason'] == 'insufficient_samples'


def test_replay_fails_on_insufficient_tagged_samples(monkeypatch):
    samples = _good_tag_samples()
    for s in samples:
        s['strategy_tags'] = ['other_tag']
    samples[0]['strategy_tags'] = ['good_tag']
    monkeypatch.setattr(hr, '_collect_samples', lambda **kw: samples)
    monkeypatch.setattr(hr, 'PASS_MIN_SAMPLES', 40)

    report = hr.replay_tag_delta('good_tag', 1.0)

    assert report['passed'] is False
    assert report['reason'] == 'insufficient_tagged_samples'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_hypothesis_replay.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

```python
# app/services/mirofish/hypothesis_replay.py
"""Offline lookahead-safe replay validation for agent scoring hypotheses.

scripts/backtest_alpha_signals.py 의 성숙 컷오프/가격 리플레이 로직을 재사용해
"태그 X 에 델타 d 적용" 가설이 과거 데이터에서 랭킹 품질(IC)과 상위 버킷
수익을 함께 개선하는지 검증한다. 통과한 가설만 적용 자격을 얻는다.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
BACKTEST_SCRIPT = os.path.join(REPO_ROOT, 'scripts', 'backtest_alpha_signals.py')

PASS_MIN_SAMPLES = 60
PASS_MIN_TAGGED = 10
PASS_MIN_IC_GAIN = 0.01
TOP_FRACTION = 0.25


@lru_cache(maxsize=1)
def _backtest_module():
    """scripts/ 는 패키지가 아니므로 importlib 로 로드 (기존 테스트 선례와 동일)."""
    spec = importlib.util.spec_from_file_location('backtest_alpha_signals', BACKTEST_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def replay_tag_delta(
    tag: str,
    delta: float,
    *,
    horizon_days: int = 5,
    limit_runs: int = 4000,
) -> dict[str, Any]:
    """Validate a tag-delta hypothesis against historical scanner runs."""
    tag = str(tag or '').strip()
    delta = float(delta)
    samples = _collect_samples(horizon_days=horizon_days, limit_runs=limit_runs)
    base = {
        'schema_version': 'mirofish.hypothesis_replay.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'tag': tag,
        'delta': delta,
        'horizon_days': horizon_days,
        'sample_count': len(samples),
        'tagged_count': sum(1 for s in samples if tag in (s.get('strategy_tags') or [])),
    }
    if len(samples) < PASS_MIN_SAMPLES:
        return {**base, 'passed': False, 'reason': 'insufficient_samples'}
    if base['tagged_count'] < PASS_MIN_TAGGED:
        return {**base, 'passed': False, 'reason': 'insufficient_tagged_samples'}

    baseline_scores = [_num(s.get('alpha_score')) for s in samples]
    adjusted_scores = [
        _num(s.get('alpha_score')) + (delta if tag in (s.get('strategy_tags') or []) else 0.0)
        for s in samples
    ]
    returns = [_num(s.get('return_pct')) for s in samples]

    baseline = _ranking_quality(baseline_scores, returns)
    adjusted = _ranking_quality(adjusted_scores, returns)
    passed = (
        adjusted['ic'] is not None
        and baseline['ic'] is not None
        and adjusted['ic'] >= baseline['ic'] + PASS_MIN_IC_GAIN
        and adjusted['top_bucket_avg_return_pct'] >= baseline['top_bucket_avg_return_pct']
    )
    return {
        **base,
        'passed': bool(passed),
        'reason': 'replay_improves_ranking' if passed else 'replay_does_not_improve_ranking',
        'baseline': baseline,
        'adjusted': adjusted,
        'ic_gain': round((adjusted['ic'] or 0.0) - (baseline['ic'] or 0.0), 4),
    }


def _ranking_quality(scores: list[float], returns: list[float]) -> dict[str, Any]:
    module = _backtest_module()
    ic = module._correlation(scores, returns) if len(scores) >= 3 else None
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    top_n = max(1, int(len(order) * TOP_FRACTION))
    top_returns = [returns[i] for i in order[:top_n]]
    return {
        'ic': round(ic, 4) if ic is not None else None,
        'top_bucket_n': top_n,
        'top_bucket_avg_return_pct': round(sum(top_returns) / top_n, 4),
    }


def _collect_samples(*, horizon_days: int, limit_runs: int) -> list[dict[str, Any]]:
    """Load mature scanner-run candidates joined with forward returns + tags."""
    module = _backtest_module()
    price_dates = module._load_price_dates(module.DEFAULT_PRICES)
    cutoff = module._mature_cutoff_date(price_dates, horizon_days)
    runs = module._load_runs(
        module.DEFAULT_SCANNER_ROOT, limit_runs=limit_runs, mature_cutoff_date=cutoff
    )
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    symbols: set[str] = set()
    for run in runs:
        for candidate in run.get('candidates') or []:
            if not isinstance(candidate, dict):
                continue
            if candidate.get('action') not in {'BUY_CANDIDATE', 'WATCH'}:
                continue
            symbol = module._symbol(candidate.get('symbol'))
            if not symbol:
                continue
            pairs.append((run, candidate))
            symbols.add(symbol)
    prices = module._load_prices(module.DEFAULT_PRICES, symbols=symbols)

    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for _run, candidate in pairs:
        sample = module._sample(candidate, prices, horizon_days)
        if not sample:
            continue
        key = (str(sample.get('symbol') or ''), str(sample.get('entry_date') or ''))
        if key in seen:
            continue
        seen.add(key)
        sample['strategy_tags'] = [
            str(t) for t in (candidate.get('strategy_tags') or []) if str(t or '').strip()
        ]
        samples.append(sample)
    return samples


def _num(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_hypothesis_replay.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/hypothesis_replay.py tests/test_mirofish_hypothesis_replay.py
git commit -m "feat: add lookahead-safe hypothesis replay validation"
```

---

### Task 3: 신뢰 경로 learning feedback 갱신 (autonomous_mcp 리팩터)

에이전트는 auto_runner와 같은 인프로세스 신뢰 코드이므로 HTTP 뮤테이션 게이트를 우회해야 한다. 기존 `refresh_learning_feedback`(522행)의 본문 루프를 게이트 없는 코어로 추출한다.

**Files:**
- Modify: `app/services/mirofish/autonomous_mcp.py:522-567`
- Test: `tests/test_mirofish_autonomous_mcp.py` (기존 파일에 테스트 추가)

- [ ] **Step 1: 실패하는 테스트 작성** — 기존 `tests/test_mirofish_autonomous_mcp.py` 끝에 추가

```python
def test_refresh_learning_feedback_trusted_skips_mutation_gate(monkeypatch, tmp_path):
    """In-process trusted path must not require MIROFISH_MCP_ALLOW_MUTATION."""
    from app.services.mirofish import autonomous_mcp

    monkeypatch.delenv('MIROFISH_MCP_ALLOW_MUTATION', raising=False)
    monkeypatch.setattr(autonomous_mcp, 'LEARNING_FEEDBACK_PATH', tmp_path / 'learning_feedback.json')
    monkeypatch.setattr(autonomous_mcp.workflow, 'list_workflows', lambda limit: [])

    feedback = autonomous_mcp.refresh_learning_feedback_trusted(limit=10)

    assert isinstance(feedback, dict)
    assert (tmp_path / 'learning_feedback.json').is_file()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_autonomous_mcp.py::test_refresh_learning_feedback_trusted_skips_mutation_gate -q`
Expected: FAIL — `AttributeError: ... has no attribute 'refresh_learning_feedback_trusted'`

- [ ] **Step 3: 구현** — `refresh_learning_feedback`의 533~567행 루프를 `_refresh_learning_feedback_core`로 추출하고 두 진입점이 공유

```python
# autonomous_mcp.py — refresh_learning_feedback(522행) 를 아래로 교체

def refresh_learning_feedback(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh outcome-derived learning feedback without changing live weights."""
    payload = dict(payload or {})
    commit = _bool(payload.get('commit'), True)
    if commit:
        try:
            _require_mutation(payload, 'refresh_learning_feedback')
        except Exception as exc:
            _audit('refresh_learning_feedback', payload, _error_result(exc), status='rejected')
            raise
    limit = _int(payload.get('limit'), 20, 1, MAX_LIMIT)
    feedback = _refresh_learning_feedback_core(limit=limit, commit=commit)
    _audit('refresh_learning_feedback', payload, _learning_summary(feedback), status='completed')
    return feedback


def refresh_learning_feedback_trusted(limit: int = 50) -> dict[str, Any]:
    """In-process trusted refresh for scheduler/agent callers (auto_runner pattern).

    HTTP 뮤테이션 게이트를 우회한다 — 외부 MCP 호출 경로에서는 사용 금지.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    feedback = _refresh_learning_feedback_core(limit=limit, commit=True)
    _audit(
        'refresh_learning_feedback', {'limit': limit, 'trusted': True},
        _learning_summary(feedback), status='completed',
    )
    return feedback


def _refresh_learning_feedback_core(*, limit: int, commit: bool) -> dict[str, Any]:
    workflows = workflow.list_workflows(limit=limit)
    refreshed: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for summary in workflows:
        workflow_id = str(summary.get('id') or '')
        if not workflow_id:
            continue
        record = workflow.read_workflow(workflow_id)
        if not isinstance(record, dict) or record.get('status') != 'completed':
            continue
        try:
            outcomes = (
                outcome_tracker.refresh_workflow_outcomes(workflow_id, workflow=record)
                if commit
                else outcome_tracker.read_workflow_outcomes(workflow_id)
            )
        except Exception as exc:
            errors.append({'workflow_id': workflow_id, 'error': f'{type(exc).__name__}: {exc}'})
            continue
        if not isinstance(outcomes, dict):
            continue
        refreshed.append({
            'workflow_id': workflow_id,
            'status': outcomes.get('status'),
            'summary': outcomes.get('summary') or {},
        })
        all_items.extend([item for item in (outcomes.get('items') or []) if isinstance(item, dict)])

    feedback = _build_learning_feedback(refreshed, all_items, errors)
    if commit:
        write_json_atomic(str(LEARNING_FEEDBACK_PATH), feedback, sort_keys=False)
    return feedback
```

(주의: 기존 함수 내 `_audit(...)` 1회 호출 위치가 바뀌므로 기존 테스트가 audit 횟수를 검증한다면 함께 확인할 것.)

- [ ] **Step 4: 신규 + 기존 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_autonomous_mcp.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/autonomous_mcp.py tests/test_mirofish_autonomous_mcp.py
git commit -m "refactor: extract trusted learning feedback refresh path"
```

---

### Task 4: Agent Actions — 스토어, 바운드, 실행기, 롤백

**Files:**
- Create: `app/services/mirofish/agent_actions.py`
- Test: `tests/test_mirofish_agent_actions.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_mirofish_agent_actions.py
"""Agent action executor tests — bounds, replay gate, rollback. No LLM."""
import json

import pytest

from app.services.mirofish import agent_actions as aa


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, 'OVERRIDES_PATH', str(tmp_path / 'agent_overrides.json'))
    monkeypatch.setattr(aa, 'OVERLAY_PATH', str(tmp_path / 'agent_scoring_overlay.json'))
    return tmp_path


def _backtest_metrics(expectancy=0.4, ic=0.1):
    return {'expectancy_r': expectancy, 'information_coefficient': ic}


# --- 파라미터 오버라이드 바운드 ---

def test_adjust_parameter_within_bounds(stores):
    result = aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'edge'}],
        dry_run=False, backtest_metrics=_backtest_metrics(),
    )
    assert result[0]['status'] == 'applied'
    assert aa.param_override('min_alpha') == 72.0


def test_adjust_parameter_rejects_out_of_range(stores):
    result = aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 90.0, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(),
    )
    assert result[0]['status'] == 'rejected'
    assert aa.param_override('min_alpha') is None


def test_adjust_parameter_rejects_oversized_step(stores):
    aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(),
    )
    result = aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 80.0, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(),
    )  # 72 → 80 은 max_step 3 초과
    assert result[0]['status'] == 'rejected'
    assert aa.param_override('min_alpha') == 72.0


def test_unknown_action_rejected(stores):
    result = aa.execute_decisions(
        [{'action': 'delete_everything', 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(),
    )
    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'unknown_action'


# --- 스코어링 델타: 리플레이 게이트 ---

def test_apply_scoring_delta_requires_passed_replay(stores, monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay, 'replay_tag_delta',
        lambda tag, delta, **kw: {'passed': False, 'reason': 'replay_does_not_improve_ranking'},
    )
    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.5, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(),
    )
    assert result[0]['status'] == 'rejected'
    assert aa.scoring_overlay() == {}


def test_apply_scoring_delta_applies_after_replay_pass(stores, monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay, 'replay_tag_delta',
        lambda tag, delta, **kw: {'passed': True, 'ic_gain': 0.03},
    )
    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.5, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(0.4, 0.1),
    )
    assert result[0]['status'] == 'applied'
    overlay = aa.scoring_overlay()
    assert overlay['volume_surge']['delta'] == 1.5
    assert overlay['volume_surge']['baseline']['expectancy_r'] == 0.4


def test_apply_scoring_delta_rejects_over_cap(stores, monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay, 'replay_tag_delta',
        lambda tag, delta, **kw: {'passed': True},
    )
    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 5.0, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(),
    )
    assert result[0]['status'] == 'rejected'


# --- 드라이런 ---

def test_dry_run_blocks_mutations_but_records_proposal(stores, monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay, 'replay_tag_delta', lambda tag, delta, **kw: {'passed': True},
    )
    results = aa.execute_decisions(
        [
            {'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'x'},
            {'action': 'apply_scoring_delta', 'tag': 't1', 'delta': 1.0, 'reason': 'x'},
        ],
        dry_run=True, backtest_metrics=_backtest_metrics(),
    )
    assert all(r['status'] == 'proposed_only' for r in results)
    assert aa.param_override('min_alpha') is None
    assert aa.scoring_overlay() == {}


# --- 자동 롤백 ---

def test_rollback_after_two_consecutive_worse_backtests(stores, monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay, 'replay_tag_delta', lambda tag, delta, **kw: {'passed': True},
    )
    aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 't1', 'delta': 1.0, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(0.4, 0.10),
    )
    # 1번째 악화 백테스트 → worse_count 1, 유지
    reverted = aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02), backtest_generated_at='2026-06-13T14:00:00+00:00',
    )
    assert reverted == []
    assert aa.scoring_overlay()['t1']['worse_count'] == 1
    # 같은 백테스트 재평가는 카운트 안 됨
    again = aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02), backtest_generated_at='2026-06-13T14:00:00+00:00',
    )
    assert again == [] and aa.scoring_overlay()['t1']['worse_count'] == 1
    # 2번째 악화 (새 백테스트) → revert
    reverted = aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02), backtest_generated_at='2026-06-14T14:00:00+00:00',
    )
    assert reverted == [{'kind': 'scoring_delta', 'key': 't1'}]
    assert aa.scoring_overlay() == {}


def test_rollback_resets_worse_count_on_recovery(stores, monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay, 'replay_tag_delta', lambda tag, delta, **kw: {'passed': True},
    )
    aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 't1', 'delta': 1.0, 'reason': 'x'}],
        dry_run=False, backtest_metrics=_backtest_metrics(0.4, 0.10),
    )
    aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02), backtest_generated_at='2026-06-13T14:00:00+00:00',
    )
    # 회복 → worse_count 리셋
    aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.5, 0.12), backtest_generated_at='2026-06-14T14:00:00+00:00',
    )
    assert aa.scoring_overlay()['t1']['worse_count'] == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_agent_actions.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

```python
# app/services/mirofish/agent_actions.py
"""Whitelist action executor + bounded stores for the Alpha Brain Agent.

LLM 결정을 그대로 신뢰하지 않는다. 모든 변형은 여기서 하드 바운드로
재검증되고, 검증 실패는 기각으로 기록된다. 성과 악화 시 롤백은
enforce_rollbacks() 가 LLM 없이 결정론적으로 수행한다.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.services.mirofish import hypothesis_replay
from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_DIR = os.path.join(REPO_ROOT, 'data', 'admin_mirofish')
OVERRIDES_PATH = os.path.join(DATA_DIR, 'agent_overrides.json')
OVERLAY_PATH = os.path.join(DATA_DIR, 'agent_scoring_overlay.json')

# 파라미터 하드 바운드 — 스펙 §4.4. env 가 명시되면 항상 env 가 이긴다 (소비측 구현).
PARAM_BOUNDS: dict[str, dict[str, float]] = {
    'min_alpha': {'min': 60.0, 'max': 85.0, 'max_step': 3.0, 'default': 70.0},
    'max_risk': {'min': 35.0, 'max': 55.0, 'max_step': 3.0, 'default': 45.0},
    'min_top_score': {'min': 40.0, 'max': 70.0, 'max_step': 5.0, 'default': 50.0},
}
TAG_DELTA_CAP = 2.0          # learning_policy tag cap 과 일치
ROLLBACK_WORSE_LIMIT = 2     # 연속 악화 백테스트 횟수
ROLLBACK_TOLERANCE = 0.02    # 악화 판정 허용 오차

MUTATING_ACTIONS = {'adjust_parameter', 'apply_scoring_delta'}
ALLOWED_ACTIONS = MUTATING_ACTIONS | {
    'refresh_backtest', 'refresh_outcomes', 'revert_parameter', 'revert_scoring_delta',
}


# ─── 스토어 읽기 ───

def param_override(name: str) -> float | None:
    entry = (_read(OVERRIDES_PATH).get('params') or {}).get(name)
    if not isinstance(entry, dict):
        return None
    try:
        return float(entry.get('value'))
    except (TypeError, ValueError):
        return None


def param_value(name: str, default: float) -> float:
    """에이전트 오버라이드 값 또는 기본값. 소비측에서 env 우선 적용 후 호출할 것."""
    value = param_override(name)
    return value if value is not None else default


def scoring_overlay() -> dict[str, Any]:
    tags = _read(OVERLAY_PATH).get('tags')
    return tags if isinstance(tags, dict) else {}


def scoring_overlay_deltas() -> dict[str, float]:
    """tag -> delta 만 추출 (alpha_scanner 병합용)."""
    out: dict[str, float] = {}
    for tag, entry in scoring_overlay().items():
        try:
            delta = float((entry or {}).get('delta'))
        except (TypeError, ValueError):
            continue
        if delta:
            out[str(tag)] = max(-TAG_DELTA_CAP, min(TAG_DELTA_CAP, delta))
    return out


# ─── 실행기 ───

def execute_decisions(
    decisions: list[dict[str, Any]],
    *,
    dry_run: bool,
    backtest_metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate and execute whitelisted decisions; return per-decision results."""
    results: list[dict[str, Any]] = []
    for decision in decisions or []:
        if not isinstance(decision, dict):
            continue
        action = str(decision.get('action') or '').strip()
        if action not in ALLOWED_ACTIONS:
            results.append(_result(decision, 'rejected', 'unknown_action'))
            continue
        if dry_run and action in MUTATING_ACTIONS:
            results.append(_result(decision, 'proposed_only', 'dry_run'))
            continue
        try:
            results.append(_HANDLERS[action](decision, backtest_metrics or {}))
        except Exception as exc:  # 액션 실패는 사이클을 죽이지 않는다
            logger.warning('[agent_actions] %s failed: %s', action, exc, exc_info=True)
            results.append(_result(decision, 'error', f'{type(exc).__name__}: {exc}'))
    return results


def _do_adjust_parameter(decision: dict[str, Any], backtest: dict[str, Any]) -> dict[str, Any]:
    name = str(decision.get('param') or '').strip()
    bounds = PARAM_BOUNDS.get(name)
    if not bounds:
        return _result(decision, 'rejected', 'unknown_param')
    try:
        target = float(decision.get('to'))
    except (TypeError, ValueError):
        return _result(decision, 'rejected', 'invalid_target_value')
    if not (bounds['min'] <= target <= bounds['max']):
        return _result(decision, 'rejected', 'out_of_bounds')
    current = param_value(name, bounds['default'])
    if abs(target - current) > bounds['max_step']:
        return _result(decision, 'rejected', 'step_too_large')
    store = _read(OVERRIDES_PATH)
    params = store.setdefault('params', {})
    params[name] = {
        'value': target,
        'applied_at': _now(),
        'reason': str(decision.get('reason') or ''),
        'baseline': _baseline(backtest),
        'worse_count': 0,
        'last_eval_backtest_at': None,
    }
    _write(OVERRIDES_PATH, store, 'mirofish.agent_overrides.v1')
    return _result(decision, 'applied', f'{name}: {current} -> {target}')


def _do_revert_parameter(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    name = str(decision.get('param') or '').strip()
    store = _read(OVERRIDES_PATH)
    if name not in (store.get('params') or {}):
        return _result(decision, 'rejected', 'no_active_override')
    del store['params'][name]
    _write(OVERRIDES_PATH, store, 'mirofish.agent_overrides.v1')
    return _result(decision, 'applied', f'{name} override removed')


def _do_apply_scoring_delta(decision: dict[str, Any], backtest: dict[str, Any]) -> dict[str, Any]:
    tag = str(decision.get('tag') or '').strip()
    if not tag:
        return _result(decision, 'rejected', 'missing_tag')
    try:
        delta = float(decision.get('delta'))
    except (TypeError, ValueError):
        return _result(decision, 'rejected', 'invalid_delta')
    if not delta or abs(delta) > TAG_DELTA_CAP:
        return _result(decision, 'rejected', 'delta_over_cap')
    replay = hypothesis_replay.replay_tag_delta(tag, delta)
    if not replay.get('passed'):
        return _result(decision, 'rejected', f"replay_failed: {replay.get('reason')}")
    store = _read(OVERLAY_PATH)
    tags = store.setdefault('tags', {})
    tags[tag] = {
        'delta': delta,
        'applied_at': _now(),
        'reason': str(decision.get('reason') or ''),
        'replay': {k: replay.get(k) for k in ('passed', 'ic_gain', 'sample_count', 'tagged_count')},
        'baseline': _baseline(backtest),
        'worse_count': 0,
        'last_eval_backtest_at': None,
    }
    _write(OVERLAY_PATH, store, 'mirofish.agent_scoring_overlay.v1')
    return _result(decision, 'applied', f'tag {tag} delta {delta:+.2f} (replay passed)')


def _do_revert_scoring_delta(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    tag = str(decision.get('tag') or '').strip()
    store = _read(OVERLAY_PATH)
    if tag not in (store.get('tags') or {}):
        return _result(decision, 'rejected', 'no_active_delta')
    del store['tags'][tag]
    _write(OVERLAY_PATH, store, 'mirofish.agent_scoring_overlay.v1')
    return _result(decision, 'applied', f'tag {tag} delta removed')


def _do_refresh_backtest(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    module = hypothesis_replay._backtest_module()
    report = module.evaluate_runs(horizon_days=5)
    module.write_report(report)
    module.write_rolling_report(current_report=report)  # keyword-only 시그니처
    enhanced = report.get('enhanced') or {}
    return _result(
        decision, 'applied',
        f"backtest refreshed: samples={enhanced.get('sample_count')}",
    )


def _do_refresh_outcomes(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    from app.services.mirofish import autonomous_mcp

    limit = 50
    feedback = autonomous_mcp.refresh_learning_feedback_trusted(limit=limit)
    return _result(
        decision, 'applied',
        f"outcomes refreshed: evaluated={feedback.get('evaluated_count')}",
    )


_HANDLERS = {
    'adjust_parameter': _do_adjust_parameter,
    'revert_parameter': _do_revert_parameter,
    'apply_scoring_delta': _do_apply_scoring_delta,
    'revert_scoring_delta': _do_revert_scoring_delta,
    'refresh_backtest': _do_refresh_backtest,
    'refresh_outcomes': _do_refresh_outcomes,
}


# ─── 결정론적 자동 롤백 ───

def enforce_rollbacks(
    *,
    backtest_metrics: dict[str, Any],
    backtest_generated_at: str,
) -> list[dict[str, str]]:
    """적용된 오버라이드/델타를 최신 백테스트와 비교, 2회 연속 악화 시 강제 revert.

    LLM 판단과 무관한 결정론적 안전장치. 같은 백테스트(generated_at 동일)는
    한 번만 카운트한다.
    """
    reverted: list[dict[str, str]] = []
    current = _baseline(backtest_metrics)

    for path, schema, kind, container_key in (
        (OVERLAY_PATH, 'mirofish.agent_scoring_overlay.v1', 'scoring_delta', 'tags'),
        (OVERRIDES_PATH, 'mirofish.agent_overrides.v1', 'parameter', 'params'),
    ):
        store = _read(path)
        entries = store.get(container_key) or {}
        changed = False
        for key in list(entries.keys()):
            entry = entries[key]
            if not isinstance(entry, dict):
                continue
            if entry.get('last_eval_backtest_at') == backtest_generated_at:
                continue  # 같은 백테스트 중복 평가 방지
            baseline = entry.get('baseline') or {}
            worse = _is_worse(current, baseline)
            entry['last_eval_backtest_at'] = backtest_generated_at
            entry['worse_count'] = int(entry.get('worse_count') or 0) + 1 if worse else 0
            changed = True
            if entry['worse_count'] >= ROLLBACK_WORSE_LIMIT:
                del entries[key]
                reverted.append({'kind': kind, 'key': key})
                logger.warning('[agent_actions] auto-rollback %s %s', kind, key)
        if changed:
            _write(path, store, schema)
    return reverted


def _is_worse(current: dict[str, Any], baseline: dict[str, Any]) -> bool:
    def n(d, k):
        try:
            return float(d.get(k))
        except (TypeError, ValueError):
            return 0.0
    return (
        n(current, 'expectancy_r') < n(baseline, 'expectancy_r') - ROLLBACK_TOLERANCE
        or n(current, 'information_coefficient') < n(baseline, 'information_coefficient') - ROLLBACK_TOLERANCE
    )


# ─── 내부 유틸 ───

def _baseline(backtest: dict[str, Any]) -> dict[str, Any]:
    def n(k):
        try:
            return float(backtest.get(k))
        except (TypeError, ValueError):
            return 0.0
    return {'expectancy_r': n('expectancy_r'), 'information_coefficient': n('information_coefficient')}


def _result(decision: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        'action': str(decision.get('action') or ''),
        'status': status,
        'reason': reason,
        'decision': {k: v for k, v in decision.items() if k != 'action'},
        'at': _now(),
    }


def _read(path: str) -> dict[str, Any]:
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: str, store: dict[str, Any], schema: str) -> None:
    store['schema_version'] = schema
    store['updated_at'] = _now()
    write_json_atomic(path, store, sort_keys=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_agent_actions.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/agent_actions.py tests/test_mirofish_agent_actions.py
git commit -m "feat: add bounded agent action executor with replay gate and auto-rollback"
```

---

### Task 5: 오버라이드 소비 — auto_runner + scheduler 스캐너 경로

env 명시 > 에이전트 오버라이드 > 코드 기본값.

**Files:**
- Modify: `app/services/mirofish/auto_runner.py:100-120` (`_tunables`)
- Modify: `scheduler.py:708-720` (`run_alpha_scanner_monitor`)
- Test: `tests/test_mirofish_auto_runner.py` (기존 파일에 추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_mirofish_auto_runner.py` 끝에 추가

```python
def test_tunables_use_agent_override_when_env_unset(monkeypatch):
    from app.services.mirofish import agent_actions, auto_runner

    monkeypatch.delenv('MIROFISH_AUTO_RUNNER_MIN_ALPHA', raising=False)
    monkeypatch.setattr(agent_actions, 'param_override', lambda name: 73.0 if name == 'min_alpha' else None)

    assert auto_runner._tunables()['min_alpha'] == 73.0


def test_tunables_env_beats_agent_override(monkeypatch):
    from app.services.mirofish import agent_actions, auto_runner

    monkeypatch.setenv('MIROFISH_AUTO_RUNNER_MIN_ALPHA', '68')
    monkeypatch.setattr(agent_actions, 'param_override', lambda name: 73.0)

    assert auto_runner._tunables()['min_alpha'] == 68.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_auto_runner.py -q -k agent_override or env_beats`
Expected: 신규 2개 FAIL

- [ ] **Step 3: 구현**

`auto_runner.py` import 에 추가:
```python
from app.services.mirofish import agent_actions
```

`_tunables()` 의 세 줄 교체 (`_env_float`는 env 미설정 시 default 반환이므로 default 자리에 오버라이드 인지 값을 넣으면 env 우선이 자동 성립):
```python
        'min_alpha': _env_float('MIROFISH_AUTO_RUNNER_MIN_ALPHA',
                                agent_actions.param_value('min_alpha', 70.0)),
        'max_risk': _env_float('MIROFISH_AUTO_RUNNER_MAX_RISK',
                               agent_actions.param_value('max_risk', 45.0)),
        ...
        'min_top_score': _env_float('MIROFISH_AUTO_RUNNER_MIN_TOP_SCORE',
                                    agent_actions.param_value('min_top_score', 50.0)),
```

`scheduler.py` `run_alpha_scanner_monitor()` 의 호출 인자 부분(716~719행) 교체:
```python
        from app.services.mirofish.agent_actions import param_value

        min_alpha = Config.ALPHA_SCANNER_MIN_ALPHA
        if os.environ.get('ALPHA_SCANNER_MIN_ALPHA') is None:
            min_alpha = param_value('min_alpha', min_alpha)
        max_risk = Config.ALPHA_SCANNER_MAX_RISK
        if os.environ.get('ALPHA_SCANNER_MAX_RISK') is None:
            max_risk = param_value('max_risk', max_risk)
        # ... 기존 run_scanner_alert_check 호출에서 min_alpha=min_alpha, max_risk=max_risk 사용
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_auto_runner.py -q`
Expected: all passed (기존 포함)

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/auto_runner.py scheduler.py tests/test_mirofish_auto_runner.py
git commit -m "feat: consume agent parameter overrides with env precedence"
```

---

### Task 6: 스코어링 오버레이 소비 — alpha_scanner

에이전트 오버레이 델타를 advisory 의 `tag_score_adjust`에 병합. 합산 후에도 기존 `learning_policy` 캡(±2.0)이 적용 시점에 클램프하므로 안전.

**Files:**
- Modify: `app/services/mirofish/alpha_scanner.py:3332-3373` (`_performance_advisory`)
- Test: `tests/test_admin_mirofish_alpha_scanner.py` (기존 파일에 추가)

- [ ] **Step 1: 실패하는 테스트 작성** — 기존 테스트 파일 끝에 추가

```python
def test_performance_advisory_merges_agent_overlay(monkeypatch):
    from app.services.mirofish import alpha_scanner, agent_actions, outcome_tracker

    monkeypatch.setattr(
        outcome_tracker, 'get_advisory_feedback',
        lambda **kw: {
            'evaluated_count': 20, 'hit_rate_recent': 0.6, 'horizon_days': 5,
            'lookahead_safe': True, 'asof': '2026-06-12T00:00:00+00:00',
            'workflow_count_scanned': 10,
            'recommendations': {'tag_score_adjust': {'volume_surge': 0.5}, 'baseline_hit_rate': 0.5},
        },
    )
    monkeypatch.setattr(
        agent_actions, 'scoring_overlay_deltas',
        lambda: {'volume_surge': 1.0, 'agent_only_tag': -1.5},
    )

    advisory = alpha_scanner._performance_advisory()
    adjust = advisory['recommendations']['tag_score_adjust']
    assert adjust['volume_surge'] == 1.5   # 0.5 + 1.0
    assert adjust['agent_only_tag'] == -1.5
    assert advisory['recommendations']['agent_overlay_applied'] is True


def test_performance_advisory_clamps_merged_overlay(monkeypatch):
    from app.services.mirofish import alpha_scanner, agent_actions, outcome_tracker

    monkeypatch.setattr(
        outcome_tracker, 'get_advisory_feedback',
        lambda **kw: {
            'evaluated_count': 20, 'hit_rate_recent': 0.6, 'horizon_days': 5,
            'lookahead_safe': True, 'asof': 'x', 'workflow_count_scanned': 10,
            'recommendations': {'tag_score_adjust': {'volume_surge': 1.8}, 'baseline_hit_rate': 0.5},
        },
    )
    monkeypatch.setattr(agent_actions, 'scoring_overlay_deltas', lambda: {'volume_surge': 1.8})

    advisory = alpha_scanner._performance_advisory()
    assert advisory['recommendations']['tag_score_adjust']['volume_surge'] == 2.0  # cap
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_alpha_scanner.py -q -k overlay`
Expected: 신규 2개 FAIL

- [ ] **Step 3: 구현** — `_performance_advisory()` 의 `base` dict 구성 직후(3356행 `recommendations` 라인 이후, learning_policy 빌드 전)에 삽입

```python
    # Alpha Brain Agent 가 리플레이 검증 후 적용한 태그 델타 오버레이 병합.
    # 합산값도 ±2.0 으로 클램프 — learning_policy tag cap 과 동일 한도.
    try:
        from app.services.mirofish import agent_actions

        overlay = agent_actions.scoring_overlay_deltas()
    except Exception:
        overlay = {}
    if overlay:
        merged = dict(base['recommendations'].get('tag_score_adjust') or {})
        for tag, delta in overlay.items():
            merged[tag] = round(max(-2.0, min(2.0, _float(merged.get(tag)) + delta)), 2)
        base['recommendations'] = {
            **base['recommendations'],
            'tag_score_adjust': merged,
            'agent_overlay_applied': True,
        }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_alpha_scanner.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/alpha_scanner.py tests/test_admin_mirofish_alpha_scanner.py
git commit -m "feat: merge agent scoring overlay into scanner tag adjustments"
```

---

### Task 7: Alpha Brain Agent — Observation + 결정론적 유지보수

**Files:**
- Create: `app/services/mirofish/alpha_brain_agent.py` (1부: 관찰/유지보수/상태)
- Test: `tests/test_mirofish_alpha_brain_agent.py` (1부)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_mirofish_alpha_brain_agent.py
"""Alpha Brain Agent cycle tests — LLM fully mocked."""
import json

import pytest

from app.services.mirofish import alpha_brain_agent as agent


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, 'STATE_PATH', str(tmp_path / 'agent_state.json'))
    monkeypatch.setattr(agent, 'JOURNAL_PATH', str(tmp_path / 'agent_journal.jsonl'))
    monkeypatch.setattr(agent.agent_actions, 'OVERRIDES_PATH', str(tmp_path / 'agent_overrides.json'))
    monkeypatch.setattr(agent.agent_actions, 'OVERLAY_PATH', str(tmp_path / 'agent_scoring_overlay.json'))
    monkeypatch.setenv('MIROFISH_AGENT_DRY_RUN', '0')
    monkeypatch.setenv('MIROFISH_AGENT_BRIEF_ENABLED', '0')  # 테스트에서 텔레그램 차단
    # 외부 의존(디스크 스캔/실데이터) 전부 차단
    monkeypatch.setattr(agent.edge_map, 'build_edge_map', lambda **kw: {
        'evaluated_count': 12, 'overall': {'n': 12, 'hit_rate': 0.58, 'expectancy_pct': 1.2},
        'by_tag': {}, 'by_alpha_band': {}, 'by_market': {}, 'by_action': {}, 'by_signal_quality': {},
    })
    monkeypatch.setattr(agent, '_advisory_summary', lambda: {
        'evaluated_count': 12, 'hit_rate_recent': 0.58, 'by_strategy_tag': {}, 'baseline_hit_rate': 0.5,
    })
    monkeypatch.setattr(agent, '_read_backtest_daily', lambda: {
        'generated_at': '2026-06-12T14:00:00+00:00', 'lookahead_safe': True,
        'enhanced': {'sample_count': 120, 'expectancy_r': 0.35, 'information_coefficient': 0.09},
    })
    monkeypatch.setattr(agent.agent_actions, 'enforce_rollbacks', lambda **kw: [])
    return tmp_path


def test_observation_contains_kpi_and_freshness(agent_env, monkeypatch):
    obs = agent.build_agent_observation(now_iso='2026-06-12T08:00:00+00:00')
    assert obs['edge_map']['evaluated_count'] == 12
    assert obs['backtest']['sample_count'] == 120
    assert obs['backtest']['stale'] is False
    assert 'active_overrides' in obs and 'active_scoring_overlay' in obs


def test_observation_flags_stale_backtest(agent_env, monkeypatch):
    monkeypatch.setattr(agent, '_read_backtest_daily', lambda: {
        'generated_at': '2026-06-01T14:00:00+00:00', 'enhanced': {'sample_count': 30},
    })
    obs = agent.build_agent_observation(now_iso='2026-06-12T08:00:00+00:00')
    assert obs['backtest']['stale'] is True


def test_maintenance_refreshes_stale_backtest_without_llm(agent_env, monkeypatch):
    monkeypatch.setattr(agent, '_read_backtest_daily', lambda: {
        'generated_at': '2026-06-01T14:00:00+00:00', 'enhanced': {'sample_count': 30},
    })
    calls = []
    monkeypatch.setattr(
        agent.agent_actions, 'execute_decisions',
        lambda decisions, **kw: [calls.append(d) or {'action': d['action'], 'status': 'applied', 'reason': ''}
                                 for d in decisions],
    )
    obs = agent.build_agent_observation(now_iso='2026-06-12T08:00:00+00:00')
    results = agent.run_maintenance(obs, dry_run=False)
    actions = [c['action'] for c in calls]
    assert 'refresh_backtest' in actions
    assert 'refresh_outcomes' in actions  # evaluated_count 12 < MIN_EVALUATED_TARGET 이므로
    assert all(r['status'] == 'applied' for r in results)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_alpha_brain_agent.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현 (모듈 1부)**

```python
# app/services/mirofish/alpha_brain_agent.py
"""Alpha Brain Agent — 사이클형 자율 학습/분석 오케스트레이터.

목적 함수는 단 하나: Top3 추천의 전방 수익 기대값.
Sense(결정론) → Think(LLM 1회) → Act(화이트리스트) → Learn(저널).
유지보수(백테스트/outcome 신선도)와 롤백은 LLM 없이 결정론적으로 수행된다.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.services.mirofish import agent_actions, edge_map
from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_DIR = os.path.join(REPO_ROOT, 'data', 'admin_mirofish')
STATE_PATH = os.path.join(DATA_DIR, 'agent_state.json')
JOURNAL_PATH = os.path.join(DATA_DIR, 'agent_journal.jsonl')
BACKTEST_DAILY_PATH = os.path.join(DATA_DIR, 'alpha_backtest_daily.json')

BACKTEST_STALE_HOURS = 30          # 매일 23:00 실행 기준 + 여유
MIN_EVALUATED_TARGET = 30          # 이보다 적으면 outcome 갱신 유지보수
CIRCUIT_FAILURE_LIMIT = 3
CIRCUIT_OPEN_HOURS = 24
MAX_LLM_CALLS_PER_CYCLE = 3
JOURNAL_TAIL_FOR_PROMPT = 5


# ─── Sense ───

def build_agent_observation(*, now_iso: str | None = None) -> dict[str, Any]:
    """결정론적 상태 스냅샷 — LLM 호출 없음."""
    now_dt = _parse_dt(now_iso) or datetime.now(timezone.utc)
    backtest_raw = _read_backtest_daily()
    enhanced = backtest_raw.get('enhanced') or {}
    generated_at = str(backtest_raw.get('generated_at') or '')
    age_hours = _age_hours(generated_at, now_dt)
    edge = edge_map.build_edge_map()
    advisory = _advisory_summary()
    return {
        'observed_at': now_dt.isoformat(),
        'objective': 'maximize Top3 forward-return expectancy (5/10/20d)',
        'edge_map': edge,
        'outcome': advisory,
        'backtest': {
            'generated_at': generated_at or None,
            'age_hours': age_hours,
            'stale': age_hours is None or age_hours > BACKTEST_STALE_HOURS,
            'sample_count': _int(enhanced.get('sample_count')),
            'expectancy_r': _num(enhanced.get('expectancy_r')),
            'information_coefficient': _num(enhanced.get('information_coefficient')),
            'lookahead_safe': bool(backtest_raw.get('lookahead_safe', True)),
        },
        'active_overrides': _active_overrides(),
        'active_scoring_overlay': agent_actions.scoring_overlay(),
        'recent_journal': read_journal_tail(JOURNAL_TAIL_FOR_PROMPT),
    }


def run_maintenance(observation: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """학습 원료 신선도 유지 — LLM 실패와 무관하게 항상 수행되는 결정론 규칙."""
    decisions: list[dict[str, Any]] = []
    if observation['backtest'].get('stale'):
        decisions.append({'action': 'refresh_backtest', 'reason': 'deterministic: backtest stale'})
    evaluated = _int((observation.get('outcome') or {}).get('evaluated_count'))
    if evaluated < MIN_EVALUATED_TARGET:
        decisions.append({'action': 'refresh_outcomes', 'reason': 'deterministic: low evaluated outcomes'})
    if not decisions:
        return []
    # 유지보수는 dry_run 에서도 실행한다 (읽기 산출물 갱신일 뿐 가중치 변형이 아님)
    return agent_actions.execute_decisions(
        decisions, dry_run=False,
        backtest_metrics=observation.get('backtest') or {},
    )


# ─── 내부 헬퍼 (1부) ───

def _read_backtest_daily() -> dict[str, Any]:
    try:
        with open(BACKTEST_DAILY_PATH, 'r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _advisory_summary() -> dict[str, Any]:
    try:
        from app.services.mirofish import outcome_tracker

        advisory = outcome_tracker.get_advisory_feedback(horizon_days=5, limit_workflows=200)
    except Exception as exc:
        return {'evaluated_count': 0, 'error': f'{type(exc).__name__}: {exc}'}
    return {
        'evaluated_count': _int(advisory.get('evaluated_count')),
        'hit_rate_recent': advisory.get('hit_rate_recent'),
        'by_strategy_tag': advisory.get('by_strategy_tag') or {},
        'baseline_hit_rate': (advisory.get('recommendations') or {}).get('baseline_hit_rate'),
    }


def _active_overrides() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in agent_actions.PARAM_BOUNDS:
        value = agent_actions.param_override(name)
        if value is not None:
            out[name] = value
    return out


def read_journal_tail(limit: int = 20) -> list[dict[str, Any]]:
    try:
        with open(JOURNAL_PATH, 'r', encoding='utf-8') as handle:
            lines = handle.readlines()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines[-max(1, limit):]:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_hours(value: str, now_dt: datetime) -> float | None:
    parsed = _parse_dt(value)
    if not parsed:
        return None
    return round(max(0.0, (now_dt - parsed.astimezone(timezone.utc)).total_seconds() / 3600), 2)


def _num(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    return int(_num(value))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_alpha_brain_agent.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/alpha_brain_agent.py tests/test_mirofish_alpha_brain_agent.py
git commit -m "feat: agent observation builder and deterministic maintenance"
```

---

### Task 8: Alpha Brain Agent — Think(LLM) + 사이클 + 저널 + 서킷 브레이커

**Files:**
- Modify: `app/services/mirofish/alpha_brain_agent.py` (2부 추가)
- Test: `tests/test_mirofish_alpha_brain_agent.py` (2부 추가)

- [ ] **Step 1: 실패하는 테스트 작성** — 테스트 파일에 추가

```python
def _llm_returning(payload):
    return lambda prompt: json.dumps(payload)


def test_cycle_executes_validated_llm_decisions(agent_env, monkeypatch):
    executed = []
    monkeypatch.setattr(
        agent.agent_actions, 'execute_decisions',
        lambda decisions, **kw: [executed.append(d) or {'action': d['action'], 'status': 'applied', 'reason': ''}
                                 for d in decisions],
    )
    payload = {
        'assessment': 'edge ok',
        'confidence': 0.8,
        'decisions': [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.0, 'reason': 'edge'}],
    }
    result = agent.run_agent_cycle('post_backtest', llm_call=_llm_returning(payload))
    assert result['status'] == 'completed'
    assert any(d['action'] == 'apply_scoring_delta' for d in executed)
    journal = agent.read_journal_tail(1)[0]
    assert journal['cycle'] == 'post_backtest'
    assert journal['llm']['decision_count'] == 1


def test_cycle_rejects_invalid_llm_json_then_no_decision(agent_env, monkeypatch):
    monkeypatch.setattr(
        agent.agent_actions, 'execute_decisions',
        lambda decisions, **kw: [{'action': d['action'], 'status': 'applied', 'reason': ''} for d in decisions],
    )
    result = agent.run_agent_cycle('evening', llm_call=lambda prompt: 'not json at all')
    assert result['status'] == 'completed'
    assert result['llm']['status'] == 'no_decision'
    # 유지보수 외 변형 액션은 없어야 함
    assert result['act']['llm_results'] == []


def test_cycle_filters_non_whitelisted_actions_before_execution(agent_env, monkeypatch):
    executed = []
    monkeypatch.setattr(
        agent.agent_actions, 'execute_decisions',
        lambda decisions, **kw: [executed.append(d) or {'action': d['action'], 'status': 'applied', 'reason': ''}
                                 for d in decisions],
    )
    payload = {
        'assessment': 'x', 'confidence': 0.9,
        'decisions': [
            {'action': 'send_telegram_to_everyone', 'reason': 'bad'},
            {'action': 'revert_scoring_delta', 'tag': 't1', 'reason': 'ok'},
        ],
    }
    result = agent.run_agent_cycle('evening', llm_call=_llm_returning(payload))
    actions = [d['action'] for d in executed]
    assert 'send_telegram_to_everyone' not in actions
    assert 'revert_scoring_delta' in actions
    assert result['llm']['rejected_decisions'] == 1


def test_circuit_breaker_opens_after_three_failures(agent_env, monkeypatch):
    def boom(**kw):
        raise RuntimeError('sense exploded')
    monkeypatch.setattr(agent, 'build_agent_observation', boom)
    for _ in range(3):
        result = agent.run_agent_cycle('evening', llm_call=lambda p: None)
        assert result['status'] == 'failed'
    result = agent.run_agent_cycle('evening', llm_call=lambda p: None)
    assert result['status'] == 'skipped_circuit_open'


def test_dry_run_cycle_marks_mutations_proposed_only(agent_env, monkeypatch):
    monkeypatch.setenv('MIROFISH_AGENT_DRY_RUN', '1')
    payload = {
        'assessment': 'x', 'confidence': 0.9,
        'decisions': [{'action': 'apply_scoring_delta', 'tag': 't1', 'delta': 1.0, 'reason': 'x'}],
    }
    # 실제 agent_actions.execute_decisions 를 쓰되 리플레이는 통과시킴
    monkeypatch.setattr(
        agent.agent_actions.hypothesis_replay, 'replay_tag_delta',
        lambda tag, delta, **kw: {'passed': True},
    )
    result = agent.run_agent_cycle('post_backtest', llm_call=_llm_returning(payload))
    statuses = [r['status'] for r in result['act']['llm_results']]
    assert statuses == ['proposed_only']
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_alpha_brain_agent.py -q`
Expected: 신규 5개 FAIL (`run_agent_cycle` 미정의)

- [ ] **Step 3: 구현 (모듈 2부)** — `alpha_brain_agent.py`에 추가

```python
# ─── Think / Act / Learn ───

LLM_SYSTEM_PROMPT = (
    'You are the Alpha Brain Agent for a KR stock detection pipeline. '
    'Your single objective: improve forward-return expectancy of Top3 picks. '
    'You may only choose whitelisted actions. Never invent tickers, prices, or filings. '
    'Base every hypothesis on the provided edge-map statistics; cite bucket stats in reasons. '
    'Respond with ONE JSON object only.'
)

ALLOWED_LLM_ACTIONS = {
    'refresh_backtest', 'refresh_outcomes',
    'apply_scoring_delta', 'revert_scoring_delta',
    'adjust_parameter', 'revert_parameter',
}


def run_agent_cycle(
    cycle: str = 'evening',
    *,
    llm_call: Callable[[str], str | None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """한 사이클 실행. 실패해도 예외를 밖으로 던지지 않는다."""
    now_dt = now or datetime.now(timezone.utc)
    state = _read_state()
    if _circuit_open(state, now_dt):
        entry = {
            'at': now_dt.isoformat(), 'cycle': cycle, 'status': 'skipped_circuit_open',
            'circuit_open_until': state.get('circuit_open_until'),
        }
        _append_journal(entry)
        return entry

    dry_run = _env_bool('MIROFISH_AGENT_DRY_RUN', True)
    try:
        observation = build_agent_observation(now_iso=now_dt.isoformat())

        # 1) 결정론적 롤백 (LLM 무관)
        reverted = agent_actions.enforce_rollbacks(
            backtest_metrics=observation['backtest'],
            backtest_generated_at=str(observation['backtest'].get('generated_at') or ''),
        )

        # 2) 결정론적 유지보수
        maintenance_results = run_maintenance(observation, dry_run=dry_run)

        # 3) Think — LLM 결정 (실패 시 no_decision 으로 사이클은 계속)
        llm = llm_call or _default_llm_call
        llm_outcome = _decide(observation, cycle, llm)

        # 4) Act — 화이트리스트 필터 후 실행
        llm_results = agent_actions.execute_decisions(
            llm_outcome['decisions'], dry_run=dry_run,
            backtest_metrics=observation['backtest'],
        ) if llm_outcome['decisions'] else []

        entry = {
            'at': now_dt.isoformat(),
            'cycle': cycle,
            'status': 'completed',
            'dry_run': dry_run,
            'kpi': {
                'evaluated_count': observation['outcome'].get('evaluated_count'),
                'hit_rate_recent': observation['outcome'].get('hit_rate_recent'),
                'backtest_expectancy_r': observation['backtest'].get('expectancy_r'),
                'backtest_ic': observation['backtest'].get('information_coefficient'),
            },
            'rollbacks': reverted,
            'maintenance': maintenance_results,
            'llm': {
                'status': llm_outcome['status'],
                'provider_note': llm_outcome.get('note'),
                'assessment': llm_outcome.get('assessment'),
                'confidence': llm_outcome.get('confidence'),
                'decision_count': len(llm_outcome['decisions']),
                'rejected_decisions': llm_outcome['rejected_count'],
            },
            'act': {'llm_results': llm_results},
            'active_overrides': _active_overrides(),
            'active_scoring_overlay': agent_actions.scoring_overlay(),
        }
        _append_journal(entry)
        state['consecutive_failures'] = 0
        state['last_cycle_at'] = now_dt.isoformat()
        state['last_cycle'] = cycle
        _write_state(state)
        _maybe_send_brief(entry)
        return entry
    except Exception as exc:
        logger.error('[alpha_brain_agent] cycle failed: %s', exc, exc_info=True)
        failures = int(state.get('consecutive_failures') or 0) + 1
        state['consecutive_failures'] = failures
        if failures >= CIRCUIT_FAILURE_LIMIT:
            state['circuit_open_until'] = (now_dt + timedelta(hours=CIRCUIT_OPEN_HOURS)).isoformat()
        _write_state(state)
        entry = {
            'at': now_dt.isoformat(), 'cycle': cycle, 'status': 'failed',
            'error': f'{type(exc).__name__}: {exc}', 'consecutive_failures': failures,
        }
        _append_journal(entry)
        return entry


def _decide(
    observation: dict[str, Any],
    cycle: str,
    llm: Callable[[str], str | None],
) -> dict[str, Any]:
    prompt = _build_prompt(observation, cycle)
    for attempt in range(2):  # 1회 재시도
        raw = llm(prompt)
        if not raw:
            break
        payload = _parse_json(raw)
        if payload is None:
            continue
        clean, rejected = _validate_decisions(payload)
        return {
            'status': 'decided',
            'assessment': str(payload.get('assessment') or '')[:2000],
            'confidence': _num(payload.get('confidence')),
            'decisions': clean,
            'rejected_count': rejected,
        }
    return {'status': 'no_decision', 'decisions': [], 'rejected_count': 0,
            'note': 'llm unavailable or invalid json twice'}


def _build_prompt(observation: dict[str, Any], cycle: str) -> str:
    schema = {
        'assessment': 'string — current detection-quality assessment',
        'confidence': '0..1',
        'decisions': [{
            'action': f'one of {sorted(ALLOWED_LLM_ACTIONS)}',
            'reason': 'string citing edge-map bucket stats',
            'tag': 'for apply/revert_scoring_delta',
            'delta': f'float, |delta| <= {agent_actions.TAG_DELTA_CAP}',
            'param': f'for adjust/revert_parameter, one of {sorted(agent_actions.PARAM_BOUNDS)}',
            'to': 'float target for adjust_parameter',
        }],
    }
    return (
        f'CYCLE: {cycle}\n'
        f'OBSERVATION (deterministic, lookahead-safe):\n{json.dumps(observation, ensure_ascii=False, default=str)[:24000]}\n\n'
        f'Decide 0-4 actions. Empty decisions list is a valid answer when evidence is weak.\n'
        f'Every apply_scoring_delta will be replay-validated before taking effect; '
        f'propose only deltas supported by edge-map buckets with sufficient samples.\n'
        f'RESPONSE JSON SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}'
    )


def _validate_decisions(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    decisions = payload.get('decisions')
    if not isinstance(decisions, list):
        return [], 0
    clean: list[dict[str, Any]] = []
    rejected = 0
    for item in decisions[:6]:
        if not isinstance(item, dict):
            rejected += 1
            continue
        action = str(item.get('action') or '').strip()
        if action not in ALLOWED_LLM_ACTIONS:
            rejected += 1
            continue
        clean.append({k: item.get(k) for k in ('action', 'reason', 'tag', 'delta', 'param', 'to')
                      if item.get(k) is not None})
    return clean, rejected


def _default_llm_call(prompt: str) -> str | None:
    from app.services.mirofish import llm_client

    return llm_client.generate_text(
        prompt, system=LLM_SYSTEM_PROMPT, json_mode=True, max_tokens=2048, temperature=0.2,
    )


def _parse_json(raw: str) -> dict[str, Any] | None:
    text = str(raw or '').strip()
    if text.startswith('```'):
        text = text.strip('`')
        if text.startswith('json'):
            text = text[4:]
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# ─── 상태 / 저널 / 알림 ───

def _circuit_open(state: dict[str, Any], now_dt: datetime) -> bool:
    until = _parse_dt(state.get('circuit_open_until'))
    return bool(until and now_dt < until)


def _read_state() -> dict[str, Any]:
    try:
        with open(STATE_PATH, 'r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    state['schema_version'] = 'mirofish.agent_state.v1'
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(STATE_PATH, state, sort_keys=False)


def _append_journal(entry: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    with open(JOURNAL_PATH, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def _maybe_send_brief(entry: dict[str, Any]) -> None:
    """사이클 요약 — 개인봇 전용 (시스템 메시지 라우팅 규칙)."""
    if not _env_bool('MIROFISH_AGENT_BRIEF_ENABLED', True):
        return
    try:
        from app.utils.scheduler import _send_telegram_long

        kpi = entry.get('kpi') or {}
        llm = entry.get('llm') or {}
        lines = [
            f"[AlphaBrain] {entry.get('cycle')} cycle {entry.get('status')}"
            + (' (dry-run)' if entry.get('dry_run') else ''),
            f"KPI eval={kpi.get('evaluated_count')} hit={kpi.get('hit_rate_recent')} "
            f"expR={kpi.get('backtest_expectancy_r')} IC={kpi.get('backtest_ic')}",
            f"decisions={llm.get('decision_count', 0)} rollbacks={len(entry.get('rollbacks') or [])}",
        ]
        if llm.get('assessment'):
            lines.append(str(llm['assessment'])[:300])
        _send_telegram_long('\n'.join(lines), channel=False)
    except Exception as exc:
        logger.warning('[alpha_brain_agent] brief send failed: %s', exc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def get_agent_status() -> dict[str, Any]:
    """Admin/MCP 노출용 상태 스냅샷."""
    state = _read_state()
    return {
        'service': 'mirofish-alpha-brain-agent',
        'enabled': _env_bool('MIROFISH_AGENT_ENABLED', True),
        'dry_run': _env_bool('MIROFISH_AGENT_DRY_RUN', True),
        'state': state,
        'circuit_open': _circuit_open(state, datetime.now(timezone.utc)),
        'active_overrides': _active_overrides(),
        'active_scoring_overlay': agent_actions.scoring_overlay(),
        'edge_map_generated_at': (edge_map.read_edge_map() or {}).get('generated_at'),
        'recent_journal': read_journal_tail(20),
    }
```

- [ ] **Step 4: 전체 에이전트 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_mirofish_alpha_brain_agent.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/mirofish/alpha_brain_agent.py tests/test_mirofish_alpha_brain_agent.py
git commit -m "feat: alpha brain agent cycle with LLM decisions, journal, circuit breaker"
```

---

### Task 9: 스케줄러 등록

**Files:**
- Modify: `scheduler.py` — Config(~411행 부근), run 함수(run_alpha_backtest_daily 아래), 등록부(3358행 `ALPHA_BACKTEST_TIME` 등록 근처)
- Test: `tests/test_scheduler_with_record.py` (기존 파일에 추가 — run 함수 단위 검증)

- [ ] **Step 1: 실패하는 테스트 작성** — 기존 파일 끝에 추가

```python
def test_run_alpha_brain_agent_cycles_invoke_agent(monkeypatch):
    import scheduler as sched

    calls = []
    import app.services.mirofish.alpha_brain_agent as agent_mod
    monkeypatch.setattr(
        agent_mod, 'run_agent_cycle',
        lambda cycle, **kw: calls.append(cycle) or {'status': 'completed'},
    )
    assert sched.run_alpha_brain_agent_evening() is True
    assert sched.run_alpha_brain_agent_night() is True
    assert calls == ['evening', 'post_backtest']


def test_run_alpha_brain_agent_reports_failure(monkeypatch):
    import scheduler as sched
    import app.services.mirofish.alpha_brain_agent as agent_mod

    monkeypatch.setattr(agent_mod, 'run_agent_cycle', lambda cycle, **kw: {'status': 'failed'})
    assert sched.run_alpha_brain_agent_evening() is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scheduler_with_record.py -q -k alpha_brain`
Expected: 2 FAIL — AttributeError

- [ ] **Step 3: 구현**

Config 클래스에 추가 (ALPHA_BACKTEST_* 설정 아래):
```python
    MIROFISH_AGENT_ENABLED = os.environ.get('MIROFISH_AGENT_ENABLED', 'true').lower() == 'true'
    MIROFISH_AGENT_EVENING_TIME = os.environ.get('MIROFISH_AGENT_EVENING_TIME', '16:30')
    MIROFISH_AGENT_NIGHT_TIME = os.environ.get('MIROFISH_AGENT_NIGHT_TIME', '23:30')
```

run 함수 추가 (`run_alpha_backtest_daily` 정의 아래):
```python
def _run_alpha_brain_agent(cycle: str) -> bool:
    """Run one Alpha Brain Agent cycle (in-process trusted path)."""
    try:
        from app.services.mirofish import alpha_brain_agent

        result = alpha_brain_agent.run_agent_cycle(cycle)
        status = result.get('status')
        logger.info('Alpha brain agent cycle=%s status=%s', cycle, status)
        return status in {'completed', 'skipped_circuit_open'}
    except Exception as exc:
        logger.error('Alpha brain agent cycle failed: %s', exc, exc_info=True)
        return False


def run_alpha_brain_agent_evening() -> bool:
    return _run_alpha_brain_agent('evening')


def run_alpha_brain_agent_night() -> bool:
    return _run_alpha_brain_agent('post_backtest')
```

등록부 — `ALPHA_BACKTEST_TIME` 등록(3358행) 바로 아래에 추가:
```python
        if Config.MIROFISH_AGENT_ENABLED:
            # 장 마감 사이클 — 주중만 (weekdays 변수는 등록부에 이미 존재)
            for day in weekdays:
                getattr(schedule.every(), day).at(Config.MIROFISH_AGENT_EVENING_TIME).do(
                    self._with_record(run_alpha_brain_agent_evening, 'alpha_brain_agent_evening',
                                      max_retries=1, retry_delay=300))
            # 백테스트 후 사이클 — 백테스트(매일 23:00)와 동일하게 매일
            schedule.every().day.at(Config.MIROFISH_AGENT_NIGHT_TIME).do(
                self._with_record(run_alpha_brain_agent_night, 'alpha_brain_agent_night',
                                  max_retries=1, retry_delay=300))
```
(인접 `alpha_backtest_daily` 등록(3357~3360행)과 동일한 `max_retries=1, retry_delay=300` 형식.)

- [ ] **Step 4: 테스트 통과 + 임포트 검증**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scheduler_with_record.py -q`
Expected: all passed

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -c "import scheduler; print('scheduler import OK')"`
Expected: `scheduler import OK`

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler_with_record.py
git commit -m "feat: schedule alpha brain agent evening and post-backtest cycles"
```

---

### Task 10: Admin 라우트 + MCP 도구

**Files:**
- Modify: `app/routes/admin_mirofish.py` (라우트 추가)
- Modify: `app/services/mirofish/mcp_server.py` (`get_alpha_endpoint_blueprint` 도구 아래에 추가)
- Test: `tests/test_admin_mirofish_workflow.py` (기존 admin 테스트 파일 패턴에 추가) 또는 신규 `tests/test_admin_mirofish_agent_status.py`

- [ ] **Step 1: 실패하는 테스트 작성**

기존 admin 테스트는 인증 왕복 대신 **블루프린트 라우트 등록 검증 + 서비스 함수 직접 호출** 패턴을 쓴다 (`tests/test_admin_mirofish_workflow.py:473-485` 참조). 동일 패턴 적용:

```python
# tests/test_admin_mirofish_agent_status.py
"""Admin agent status endpoint + status snapshot tests."""
from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp


def test_agent_status_route_is_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/agent/status' in rules


def test_get_agent_status_snapshot_shape(monkeypatch, tmp_path):
    from app.services.mirofish import agent_actions, alpha_brain_agent as agent

    monkeypatch.setattr(agent, 'STATE_PATH', str(tmp_path / 'agent_state.json'))
    monkeypatch.setattr(agent, 'JOURNAL_PATH', str(tmp_path / 'agent_journal.jsonl'))
    monkeypatch.setattr(agent_actions, 'OVERRIDES_PATH', str(tmp_path / 'o.json'))
    monkeypatch.setattr(agent_actions, 'OVERLAY_PATH', str(tmp_path / 'ov.json'))
    monkeypatch.setattr(agent.edge_map, 'read_edge_map', lambda: {'generated_at': '2026-06-12T00:00:00+00:00'})

    status = agent.get_agent_status()

    assert status['service'] == 'mirofish-alpha-brain-agent'
    assert 'dry_run' in status and 'circuit_open' in status
    assert status['active_overrides'] == {}
    assert status['recent_journal'] == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_agent_status.py -q`
Expected: FAIL — `/agent/status` 가 rules 에 없어 AssertionError

- [ ] **Step 3: 구현**

`app/routes/admin_mirofish.py` 에 추가:
```python
@admin_mirofish_bp.route('/agent/status', methods=['GET'])
@admin_or_aibain_required
def agent_status():
    from app.services.mirofish import alpha_brain_agent

    return jsonify(alpha_brain_agent.get_agent_status())
```

`app/services/mirofish/mcp_server.py` — `get_alpha_endpoint_blueprint` 도구 아래에 추가:
```python
    @mcp.tool()
    def get_agent_brain_status() -> dict[str, Any]:
        """Return Alpha Brain Agent state, overrides, overlay, and recent journal."""
        from app.services.mirofish import alpha_brain_agent

        return alpha_brain_agent.get_agent_status()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_agent_status.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/routes/admin_mirofish.py app/services/mirofish/mcp_server.py tests/test_admin_mirofish_agent_status.py
git commit -m "feat: expose alpha brain agent status via admin route and MCP tool"
```

---

### Task 11: 통합 검증 + 문서

**Files:**
- Modify: `CLAUDE.md` §14 변경 이력 (v3.3.0 항목 추가)
- 검증만: 전체 테스트 + 임포트 체크

- [ ] **Step 1: mirofish 전체 테스트**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -q -k mirofish`
Expected: all passed

- [ ] **Step 2: 전체 백엔드 테스트**

Run: `PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -q`
Expected: all passed (기존 실패가 있다면 본 작업과 무관함을 확인하고 기록)

- [ ] **Step 3: 임포트/경로 전체 검증 (CLAUDE.md 스킬 4)**

Run:
```bash
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
from app.services.mirofish.alpha_brain_agent import run_agent_cycle, get_agent_status
from app.services.mirofish.edge_map import build_edge_map
from app.services.mirofish.hypothesis_replay import replay_tag_delta
from app.services.mirofish.agent_actions import execute_decisions, enforce_rollbacks
from app import create_app
app = create_app()
print('ALL IMPORTS OK')
"
```
Expected: `ALL IMPORTS OK`

- [ ] **Step 4: 드라이런 실사이클 1회 (수동 스모크)**

Run:
```bash
cd "$PROJECT" && MIROFISH_AGENT_DRY_RUN=1 PYTHONIOENCODING=utf-8 "$PYTHON" -c "
from app.services.mirofish.alpha_brain_agent import run_agent_cycle
import json
result = run_agent_cycle('evening')
print(json.dumps({'status': result['status'], 'llm': result.get('llm', {}).get('status'),
                  'maintenance': len(result.get('maintenance', []))}, ensure_ascii=False))
"
```
Expected: `{"status": "completed", ...}` — LLM 키가 없으면 `llm: no_decision`이어도 completed.
저널 확인: `data/admin_mirofish/agent_journal.jsonl` 1줄 생성.

- [ ] **Step 5: CLAUDE.md 변경 이력 추가** — §14 맨 위에:

```markdown
### v3.3.0 (2026-06-XX) — Alpha Brain Agent (자율 학습 사이클)
- `alpha_brain_agent.py` — Sense→Think→Act→Learn 사이클 (16:30/23:30 KST)
- `edge_map.py` — outcome 버킷별 수익 통계 (LLM 가설의 원료)
- `hypothesis_replay.py` — 태그 델타 가설 lookahead-safe 리플레이 검증
- `agent_actions.py` — 화이트리스트 실행기 + 하드 바운드 + 2회 연속 악화 자동 롤백
- 오버라이드 소비: auto_runner `_tunables` / scheduler 스캐너 (env > agent > default)
- 오버레이 소비: `_performance_advisory` tag_score_adjust 병합 (±2.0 캡)
- 첫 주 `MIROFISH_AGENT_DRY_RUN=1` 기본 — 저널 검토 후 완전 자율 전환
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record alpha brain agent in changelog"
```

---

## 배포 메모 (구현 완료 후, 별도 승인 항목)

- 운영 머신은 **miniPC** (192.168.55.103). 본PC 구현 → GitHub 푸시 → miniPC pull → scheduler 재시작이 표준 경로 (memory: feedback_local_vs_service, reference_minipc_ssh).
- 첫 주는 `MIROFISH_AGENT_DRY_RUN` 미설정(기본 true) 유지. `agent_journal.jsonl` 검토 후 miniPC env 에 `MIROFISH_AGENT_DRY_RUN=0` 설정해 완전 자율 전환.
- outcome 표본이 30건 이상 쌓일 때까지(약 1~2주) 에이전트는 주로 유지보수+관찰만 수행하는 것이 정상 동작.
```
