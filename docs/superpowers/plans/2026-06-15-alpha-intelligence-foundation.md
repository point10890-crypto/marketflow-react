# Alpha Intelligence Foundation — Implementation Plan

> **For agentic workers:** TDD per task (실패 테스트 → 구현 → 통과 → 커밋). 하네스: `docs/superpowers/harness/2026-06-15-alpha-intelligence-harness.md`. 스펙: `docs/superpowers/specs/2026-06-15-alpha-intelligence-foundation-design.md`.

**Goal:** 평가 완료 outcome을 lookahead-safe 학습 행렬(L0)·시장폭 레짐(L1)·피처 상호작용 통계(L2)로 정규화하고 brain agent 관찰에 연결한다.

**Architecture:** 신규 서브패키지 `app/services/mirofish/intelligence/` (regime, dataset, interactions). 전부 결정론·LLM/네트워크 없음. 읽기 전용(스코어 미변경).

**Tech Stack:** Python 3.13, pytest, `write_json_atomic`, 기존 `outcome_tracker`/`edge_map` 재사용.

## 공통 사전지식

- 실행: `PROJECT="/c/bitman_marketfloww"; PYTHON="$PROJECT/.venv/Scripts/python.exe"; cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest <file> -q`
- 브랜치: `feature/alpha-intelligence` (Task 1 시작 전 생성)
- `daily_prices.csv` 컬럼: `ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time` (검증됨)
- `edge_map._evaluated_items(limit_workflows)` → status∈{evaluated,partial} ∧ hit≠None 인 outcome item 리스트 (재사용)
- outcome item 필드: `symbol, status, hit(bool), forward_return_pct, feature_snapshot{alpha_score,risk_score,ranking_score,goal_fit_score,source_count,trend_20d_pct,volume_ratio,cio_confidence_pct,signal_quality,scanner_action,strategy_tags[]}, entry_date`
- `outcome_tracker._infer_market(symbol)` → 'KR'|'US'|'CRYPTO'|''
- `write_json_atomic(path, data, sort_keys=False)` (from `app.utils.atomic_json`)
- 데이터 산출 디렉토리: `data/admin_mirofish/intelligence/`

---

### Task 1: 레짐 분류기 (L1) — `intelligence/regime.py`

**Files:** Create `app/services/mirofish/intelligence/__init__.py` (빈 파일), `app/services/mirofish/intelligence/regime.py`; Test `tests/test_intelligence_regime.py`

**계약:**
- `REPO_ROOT`, `PRICE_HISTORY_PATH = data/daily_prices.csv`, `REGIME_TIMELINE_PATH = data/admin_mirofish/intelligence/regime_timeline.json`
- 상수: `MA_WINDOW=20`, `RISK_ON_BREADTH=0.60`, `RISK_OFF_BREADTH=0.40`
- `load_universe_prices(path=PRICE_HISTORY_PATH) -> dict[str, list[dict]]` — 전체 유니버스 {ticker: [{date,current_price}...(date 오름차순)]}. csv.DictReader, 인코딩 utf-8-sig. 파일 없으면 {}.
- `build_regime_timeline(prices=None, *, ma_window=MA_WINDOW, write=True) -> dict`
  - prices None이면 load_universe_prices().
  - 각 종목 시계열에서 인덱스 i(=date D)마다, 직전 ma_window일(i-ma_window..i-1) 단순이동평균 계산 가능하면, `current_price[i] > MA` 여부를 그 날짜 집계에 (above, total) 누적. (미래행 미사용 — lookahead-safe)
  - 날짜별 breadth = above/total (total>0). 매핑: ≥RISK_ON_BREADTH→'RISK_ON', ≤RISK_OFF_BREADTH→'RISK_OFF', else 'NEUTRAL'.
  - 엔벨로프: `{schema_version:'mirofish.regime_timeline.v1', generated_at, lookahead_safe:True, ma_window, by_date:{date:{breadth,regime,above,total}}}`. write 시 REGIME_TIMELINE_PATH.
- `classify_regime(entry_date, timeline) -> str` — timeline['by_date']에서 entry_date 조회; 없으면 entry_date보다 작거나 같은 최대 날짜; 그것도 없으면 'NEUTRAL'.
- `read_regime_timeline() -> dict | None`.
- 에러: 빈/결측 안전, 예외 전파 금지.

**TDD 스텝:**
1. 실패 테스트 작성:
```python
# tests/test_intelligence_regime.py
"""Regime classifier tests — deterministic, lookahead-safe, no network."""
from app.services.mirofish.intelligence import regime


def _series(start_price, deltas, start_idx=1):
    # 연속 거래일 시계열 생성 (date = 2026-01-0X)
    rows, price = [], start_price
    for i, d in enumerate(deltas):
        price += d
        rows.append({'date': f'2026-02-{start_idx + i:02d}', 'current_price': float(price)})
    return rows


def test_breadth_risk_on_when_most_above_ma(monkeypatch):
    # 22 거래일, 마지막 날 대부분 종목이 상승추세(가격 > 20MA)
    prices = {}
    for t in range(10):  # 10 종목 모두 우상향
        prices[f'{t:06d}'] = _series(1000, [10] * 22)
    tl = regime.build_regime_timeline(prices, write=False)
    last_date = max(tl['by_date'])
    assert tl['by_date'][last_date]['regime'] == 'RISK_ON'
    assert tl['by_date'][last_date]['breadth'] >= 0.60


def test_breadth_risk_off_when_most_below_ma(monkeypatch):
    prices = {}
    for t in range(10):  # 10 종목 모두 우하향
        prices[f'{t:06d}'] = _series(1000, [-10] * 22)
    tl = regime.build_regime_timeline(prices, write=False)
    last_date = max(tl['by_date'])
    assert tl['by_date'][last_date]['regime'] == 'RISK_OFF'


def test_classify_regime_uses_past_date_fallback():
    timeline = {'by_date': {
        '2026-02-10': {'breadth': 0.7, 'regime': 'RISK_ON', 'above': 7, 'total': 10},
        '2026-02-12': {'breadth': 0.3, 'regime': 'RISK_OFF', 'above': 3, 'total': 10},
    }}
    assert regime.classify_regime('2026-02-12', timeline) == 'RISK_OFF'
    assert regime.classify_regime('2026-02-11', timeline) == 'RISK_ON'   # 가장 가까운 과거
    assert regime.classify_regime('2026-02-01', timeline) == 'NEUTRAL'   # 과거 없음


def test_empty_prices_safe():
    tl = regime.build_regime_timeline({}, write=False)
    assert tl['by_date'] == {}
    assert regime.classify_regime('2026-02-10', tl) == 'NEUTRAL'
```
2. 실패 확인: `pytest tests/test_intelligence_regime.py -q` → ImportError.
3. 구현 (계약대로). lookahead-safe 필수: date D의 MA는 D 이전 ma_window일만.
4. 통과 확인: 4 passed.
5. 커밋: `git add app/services/mirofish/intelligence/__init__.py app/services/mirofish/intelligence/regime.py tests/test_intelligence_regime.py && git commit -m "feat: lookahead-safe market-breadth regime classifier (L1)"`

---

### Task 2: 데이터셋 빌더 (L0) — `intelligence/dataset.py`

**Files:** Create `app/services/mirofish/intelligence/dataset.py`; Test `tests/test_intelligence_dataset.py`

**계약:**
- `TRAINING_DATASET_PATH = data/admin_mirofish/intelligence/training_dataset.json`
- `NUMERIC_FEATURES = ('alpha_score','risk_score','ranking_score','goal_fit_score','source_count','trend_20d_pct','volume_ratio','cio_confidence_pct')`
- `build_training_dataset(*, limit_workflows=200, items=None, timeline=None, write=True) -> dict`
  - items None이면 `edge_map._evaluated_items(limit_workflows)`.
  - timeline None이면 `regime.read_regime_timeline()` 또는 `regime.build_regime_timeline(write=False)`; 없으면 빈 timeline.
  - 각 행: `{features:{numeric...}, categoricals:{signal_quality,scanner_action,market,regime}, tags:[...], label:{hit,forward_return_pct}, meta:{symbol,entry_date}}`. 결측 numeric=0.0.
  - regime = `regime.classify_regime(entry_date, timeline)`.
  - 엔벨로프: `{schema_version:'mirofish.training_dataset.v1', generated_at, lookahead_safe:True, row_count, feature_names:NUMERIC_FEATURES, regime_distribution:{RISK_ON:n,...}, rows:[...]}`. write 시 경로.
- `read_training_dataset()`, `dataset_summary() -> {row_count, hit_count, hit_rate, regime_distribution}`.
- 빈 입력 → row_count 0, rows [].

**TDD 스텝:**
1. 실패 테스트:
```python
# tests/test_intelligence_dataset.py
"""Training dataset builder tests — deterministic, no LLM."""
from app.services.mirofish.intelligence import dataset


def _item(symbol='005930', hit=True, ret=6.0, entry='2026-02-10',
          tags=('volume_surge',), alpha=78.0, status='evaluated'):
    return {
        'symbol': symbol, 'status': status, 'hit': hit, 'forward_return_pct': ret,
        'entry_date': entry,
        'feature_snapshot': {
            'alpha_score': alpha, 'risk_score': 30.0, 'ranking_score': 60.0,
            'goal_fit_score': 70.0, 'source_count': 4, 'trend_20d_pct': 12.0,
            'volume_ratio': 1.8, 'cio_confidence_pct': 65.0,
            'signal_quality': 'high_conviction', 'scanner_action': 'BUY_CANDIDATE',
            'strategy_tags': list(tags),
        },
    }


_TL = {'by_date': {'2026-02-10': {'breadth': 0.7, 'regime': 'RISK_ON', 'above': 7, 'total': 10}}}


def test_build_dataset_maps_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    out = dataset.build_training_dataset(items=[_item()], timeline=_TL)
    assert out['schema_version'] == 'mirofish.training_dataset.v1'
    assert out['lookahead_safe'] is True
    assert out['row_count'] == 1
    row = out['rows'][0]
    assert row['features']['alpha_score'] == 78.0
    assert row['categoricals']['regime'] == 'RISK_ON'
    assert row['categoricals']['market'] == 'KR'
    assert row['label']['hit'] is True
    assert 'volume_surge' in row['tags']
    assert out['regime_distribution']['RISK_ON'] == 1


def test_missing_numeric_defaults_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    it = _item()
    del it['feature_snapshot']['volume_ratio']
    out = dataset.build_training_dataset(items=[it], timeline=_TL)
    assert out['rows'][0]['features']['volume_ratio'] == 0.0


def test_empty_items(monkeypatch, tmp_path):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    out = dataset.build_training_dataset(items=[], timeline=_TL)
    assert out['row_count'] == 0 and out['rows'] == []


def test_summary_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    items = [_item(hit=True), _item(hit=False, ret=-3.0)]
    dataset.build_training_dataset(items=items, timeline=_TL)
    s = dataset.dataset_summary()
    assert s['row_count'] == 2 and s['hit_count'] == 1 and s['hit_rate'] == 0.5
```
2. 실패 확인 → ImportError.
3. 구현. `from app.services.mirofish import edge_map` + `from app.services.mirofish.intelligence import regime`.
4. 통과 확인: 4 passed.
5. 커밋: `git add app/services/mirofish/intelligence/dataset.py tests/test_intelligence_dataset.py && git commit -m "feat: lookahead-safe training dataset builder with regime tagging (L0)"`

---

### Task 3: 피처 상호작용 발견 (L2) — `intelligence/interactions.py`

**Files:** Create `app/services/mirofish/intelligence/interactions.py`; Test `tests/test_intelligence_interactions.py`

**계약:**
- `INTERACTION_MAP_PATH = data/admin_mirofish/intelligence/interaction_map.json`, `MIN_COMBO_SAMPLES=5`, `TOP_K=15`
- `_row_conditions(row) -> list[str]` — 한 행의 이진 조건 집합:
  - `f'tag:{t}'` for each tag
  - alpha 밴드: alpha≥80→'alpha:80+', 70≤alpha<80→'alpha:70-80', else 'alpha:lt70'
  - `f'regime:{regime}'`, `f'quality:{signal_quality}'`(공백 아닐 때), `f'action:{scanner_action}'`(공백 아닐 때)
- `build_interaction_map(dataset_obj=None, *, max_order=3, write=True) -> dict`
  - dataset_obj None이면 `dataset.build_training_dataset(write=False)`.
  - 각 행 조건들의 2..max_order 조합(itertools.combinations, 정렬된 tuple key)을 그 행의 (hit, return)으로 집계.
  - 버킷: `{n, hit_rate, expectancy_pct, insufficient(n<MIN_COMBO_SAMPLES)}`. key는 `' & '.join(sorted(combo))`.
  - `top_positive` = 충분표본(insufficient False) 중 expectancy_pct 내림차순 TOP_K, `top_negative` = 오름차순 TOP_K. 각 항목 `{combo, n, hit_rate, expectancy_pct}`.
  - 엔벨로프: `{schema_version:'mirofish.interaction_map.v1', generated_at, lookahead_safe:True, evaluated_count, max_order, min_combo_samples, top_positive, top_negative}`. (전체 combos는 크면 생략 가능 — top_*만 영구화해도 됨. by_combo는 포함하되 insufficient도 유지.)
- `read_interaction_map()`.
- 빈 입력 → evaluated_count 0, top_* [].

**TDD 스텝:**
1. 실패 테스트:
```python
# tests/test_intelligence_interactions.py
"""Feature-interaction mining tests — deterministic, no LLM."""
from app.services.mirofish.intelligence import interactions


def _row(hit, ret, regime='RISK_ON', alpha=82.0, tags=('volume_surge', 'foreign_buy'),
         quality='high_conviction', action='BUY_CANDIDATE'):
    return {
        'features': {'alpha_score': alpha},
        'categoricals': {'regime': regime, 'signal_quality': quality, 'scanner_action': action},
        'tags': list(tags),
        'label': {'hit': hit, 'forward_return_pct': ret},
    }


def _dataset(rows):
    return {'schema_version': 'mirofish.training_dataset.v1', 'row_count': len(rows), 'rows': rows}


def test_row_conditions_includes_band_and_regime():
    conds = interactions._row_conditions(_row(True, 5.0))
    assert 'tag:volume_surge' in conds and 'tag:foreign_buy' in conds
    assert 'alpha:80+' in conds and 'regime:RISK_ON' in conds
    assert 'quality:high_conviction' in conds and 'action:BUY_CANDIDATE' in conds


def test_interaction_aggregates_and_marks_insufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(interactions, 'INTERACTION_MAP_PATH', str(tmp_path / 'im.json'))
    rows = [_row(True, 8.0)] * 6 + [_row(False, -4.0, tags=('volume_surge',))] * 4
    out = interactions.build_interaction_map(_dataset(rows), max_order=2)
    assert out['schema_version'] == 'mirofish.interaction_map.v1'
    assert out['evaluated_count'] == 10
    # 'tag:volume_surge & regime:RISK_ON' 는 10건 모두 → 충분
    key = 'regime:RISK_ON & tag:volume_surge'
    assert out['by_combo'][key]['n'] == 10
    assert out['by_combo'][key]['insufficient'] is False
    # 'tag:foreign_buy & regime:RISK_ON' 는 6건만(첫 그룹) → 충분, hit_rate 1.0
    fk = 'regime:RISK_ON & tag:foreign_buy'
    assert out['by_combo'][fk]['n'] == 6
    assert out['by_combo'][fk]['hit_rate'] == 1.0


def test_top_positive_sorted_desc(tmp_path, monkeypatch):
    monkeypatch.setattr(interactions, 'INTERACTION_MAP_PATH', str(tmp_path / 'im.json'))
    rows = ([_row(True, 9.0, tags=('a',))] * 6 + [_row(False, -2.0, tags=('b',), alpha=72.0)] * 6)
    out = interactions.build_interaction_map(_dataset(rows), max_order=2)
    assert out['top_positive'][0]['expectancy_pct'] >= out['top_positive'][-1]['expectancy_pct']
    assert out['top_negative'][0]['expectancy_pct'] <= out['top_negative'][-1]['expectancy_pct']


def test_empty_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(interactions, 'INTERACTION_MAP_PATH', str(tmp_path / 'im.json'))
    out = interactions.build_interaction_map(_dataset([]), max_order=3)
    assert out['evaluated_count'] == 0 and out['top_positive'] == []
```
2. 실패 확인 → ImportError.
3. 구현. `import itertools`, `from app.services.mirofish.intelligence import dataset`.
4. 통과 확인: 4 passed.
5. 커밋: `git add app/services/mirofish/intelligence/interactions.py tests/test_intelligence_interactions.py && git commit -m "feat: feature-interaction profit mining (L2)"`

---

### Task 4: brain agent 관찰 연결 (미션 락 최소 통합)

**Files:** Modify `app/services/mirofish/alpha_brain_agent.py` (`build_agent_observation`); Test `tests/test_mirofish_alpha_brain_agent.py` (추가)

**계약:** `build_agent_observation` 반환 dict에 키 추가:
- `interaction_map`: `interactions.read_interaction_map()` 의 top_positive/top_negative + evaluated_count (없으면 build, 실패 시 빈 dict). top_*는 각 최대 10개로 절단.
- `regime_distribution`: training_dataset의 regime_distribution (없으면 dataset.dataset_summary 경유, 실패 시 {}).
- 기존 키(edge_map, outcome, backtest, active_overrides, active_scoring_overlay, recent_journal) 전부 보존.
- 통합부는 try/except 격리 — 실패가 관찰/사이클을 죽이지 않음. 읽기 전용, 스코어 영향 없음.

**TDD 스텝:**
1. 실패 테스트 추가 (기존 `agent_env` fixture 재사용):
```python
def test_observation_includes_interaction_map_and_regime(agent_env, monkeypatch):
    from app.services.mirofish.intelligence import interactions as ix
    from app.services.mirofish.intelligence import dataset as ds
    monkeypatch.setattr(ix, 'read_interaction_map', lambda: {
        'evaluated_count': 10,
        'top_positive': [{'combo': 'regime:RISK_ON & tag:foreign_buy', 'n': 6, 'hit_rate': 1.0, 'expectancy_pct': 8.0}],
        'top_negative': [],
    })
    monkeypatch.setattr(ds, 'dataset_summary', lambda: {'row_count': 10, 'regime_distribution': {'RISK_ON': 7, 'NEUTRAL': 3}})
    obs = __import__('app.services.mirofish.alpha_brain_agent', fromlist=['x']).build_agent_observation(
        now_iso='2026-06-15T08:00:00+00:00')
    assert obs['interaction_map']['evaluated_count'] == 10
    assert obs['interaction_map']['top_positive'][0]['combo'].startswith('regime:RISK_ON')
    assert obs['regime_distribution']['RISK_ON'] == 7
    # 기존 키 보존
    assert 'edge_map' in obs and 'backtest' in obs and 'active_scoring_overlay' in obs
```
(주의: 기존 `agent_env` fixture가 `_advisory_summary`, `_read_backtest_daily`, `edge_map.build_edge_map`, `enforce_rollbacks` 등을 모킹함. interaction/dataset 모킹만 추가.)
2. 실패 확인 → KeyError('interaction_map').
3. 구현: `build_agent_observation`에 import + 키 추가 (try/except 격리).
4. 통과 확인: `pytest tests/test_mirofish_alpha_brain_agent.py -q` 전부 통과(회귀 없음).
5. 커밋: `git add app/services/mirofish/alpha_brain_agent.py tests/test_mirofish_alpha_brain_agent.py && git commit -m "feat: surface interaction map and regime distribution in agent observation"`

---

### Task 5: 통합 검증 + 문서

1. 포커스: `pytest tests/test_intelligence_regime.py tests/test_intelligence_dataset.py tests/test_intelligence_interactions.py tests/test_mirofish_alpha_brain_agent.py -q` → 전부 통과.
2. 광역 회귀: `pytest tests/ -q -k "mirofish or agent or intelligence"` → 실패 0.
3. import + 드라이런 스모크: `MIROFISH_AGENT_DRY_RUN=1 "$PYTHON" scripts/verify_alpha_brain_agent.py` → VERIFY_RESULT PASS (관찰에 interaction_map 포함 확인).
4. 실데이터 산출 스모크: `"$PYTHON" -c "from app.services.mirofish.intelligence import dataset,interactions; print(dataset.dataset_summary()); print(len(interactions.build_interaction_map()['top_positive']))"` → 예외 없이 숫자 출력.
5. CLAUDE.md §14에 v3.4.0 항목 추가 (Alpha Intelligence Foundation L0/L1/L2).
6. 커밋: `git add CLAUDE.md && git commit -m "docs: record alpha intelligence foundation in changelog"`

## DoD (하네스 §6)
- 포커스 + 광역 테스트 통과(증거) · lookahead-safe 단위테스트 포함 · brain agent 드라이런 PASS · 읽기전용(스코어 미변경) · 의도 파일만 스테이징
