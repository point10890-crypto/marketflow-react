# Alpha Intelligence Foundation (L0+L1+L2) — 설계 문서

- 날짜: 2026-06-15
- 하네스: `docs/superpowers/harness/2026-06-15-alpha-intelligence-harness.md`
- 범위: Alpha Intelligence 계층의 첫 하위 프로젝트 — 데이터셋(L0) + 레짐 분류기(L1) + 피처 상호작용 발견(L2)
- 상태: /goal 지시에 따라 하네스 준수 실행

## 1. 목적

`alpha_brain_agent`의 엣지맵은 현재 단일축(태그/점수대/수급) 버킷만 집계한다. 이를 강화하기 위해:
- **L0**: 평가 완료 outcome을 버전관리된 lookahead-safe 학습 행렬로 정규화 (이후 L3 모델의 기반, 지금은 통계의 단일 진실원).
- **L1**: 각 표본에 entry_date 시점 시장 레짐(RISK_ON/NEUTRAL/RISK_OFF)을 태깅 — 모든 상위 분석의 조건 변수.
- **L2**: 피처 **조합**(2~3축)의 수익 통계를 발견 — "외인매수 × 신고가 × RISK_ON" 같은 상호작용 엣지.

미션 락: 이 산출물은 brain agent 관찰(observation)에 연결되어 LLM 가설의 증거 품질을 즉시 높인다. 분석 자체가 목적이 아니라 검출 개선의 수단.

## 2. 비대상 (SCOPE — 건드리지 않음)

- L3 학습 모델, L4 추론 강화 (다음 하위 프로젝트)
- 기존 `alpha_scanner` 스코어링 로직 변경 (Foundation은 **읽기 전용 분석**; 스코어 영향은 L3에서 게이트와 함께)
- `edge_map.py` 기존 동작 변경 (상호작용은 별도 모듈)
- 실주문/매매, 신규 외부 데이터 소스

## 3. 아키텍처

신규 서브패키지 `app/services/mirofish/intelligence/`:

```
intelligence/
├── __init__.py
├── regime.py        # L1 — entry_date 시점 시장폭 레짐 (결정론, lookahead-safe)
├── dataset.py       # L0 — 학습 행렬 빌더 (L1 레짐 태깅 포함)
└── interactions.py  # L2 — 피처 조합 수익 통계
```

데이터 산출물 (전부 `data/admin_mirofish/intelligence/`):
- `training_dataset.json`, `regime_timeline.json`, `interaction_map.json`

모두 결정론적, LLM·네트워크 없음, 개별 테스트 가능.

## 4. L1 — 레짐 분류기 (`regime.py`)

entry_date에 지수 데이터가 없으므로 **유니버스 시장폭 프록시** 사용. date D의 레짐은 date ≤ D 행만 사용(lookahead-safe).

- `build_regime_timeline(price_history, *, ma_window=20) -> dict[date,str]`
  - 각 거래일 D에 대해: 유니버스에서 D에 가격이 있는 종목 중, `current_price > 직전 ma_window 일 단순이동평균`인 비율 = breadth.
  - 매핑: breadth ≥ 0.60 → `RISK_ON`, ≤ 0.40 → `RISK_OFF`, 그 외 `NEUTRAL`.
  - 효율: 종목별 시계열을 1회 순회하며 누적, 날짜별 (above, total) 집계.
- `classify_regime(entry_date, timeline) -> str` — timeline에서 조회, 없으면 가장 가까운 과거 거래일, 그것도 없으면 `NEUTRAL`.
- `price_history` 로더는 `outcome_tracker`/backtest의 daily_prices.csv 파서 패턴 재사용 (컬럼: ticker,date,current_price). 신규 파서 발명 금지 — 기존 함수 재사용 또는 동일 포맷 최소 로더.
- 임계값은 모듈 상수(env 오버라이드 불필요 — 결정론 통계).

## 5. L0 — 데이터셋 빌더 (`dataset.py`)

- `build_training_dataset(*, limit_workflows=200, write=True) -> dict`
  - 표본: `edge_map._evaluated_items` 재사용 (status∈{evaluated,partial} ∧ hit≠None) — DRY.
  - 각 행:
    - `features` (numeric): alpha_score, risk_score, ranking_score, goal_fit_score, source_count, trend_20d_pct, volume_ratio, cio_confidence_pct (feature_snapshot에서, 결측 0.0)
    - `categoricals`: signal_quality, scanner_action, market(`outcome_tracker._infer_market`), regime(L1)
    - `tags`: strategy_tags 리스트
    - `label`: hit(bool), forward_return_pct(float)
    - `meta`: symbol, entry_date, horizon(있으면)
  - 엔벨로프: schema_version `mirofish.training_dataset.v1`, generated_at, lookahead_safe True, row_count, feature_names, regime_distribution.
  - regime: L1 timeline을 1회 빌드해 각 행 entry_date로 태깅.
- `read_training_dataset()` / `dataset_summary()` (row_count, label balance, regime_distribution).

## 6. L2 — 피처 상호작용 발견 (`interactions.py`)

- `build_interaction_map(dataset=None, *, max_order=3, write=True) -> dict`
  - dataset 없으면 `dataset.build_training_dataset(write=False)` 호출.
  - 각 행에서 **이진 조건 집합** 생성 (조합 폭발 억제 — 큐레이트된 base conditions만):
    - `tag:<each strategy_tag>`
    - `alpha:80+`, `alpha:70-80`, `alpha:lt70` (밴드)
    - `regime:RISK_ON|NEUTRAL|RISK_OFF`
    - `quality:<signal_quality>`
    - `action:<scanner_action>`
    - `supply_pos` (외인+기관 수급 양수 — feature에 있으면; 없으면 생략)
  - 2-way·3-way 조합(`max_order`)의 동시 충족 표본 집계: n, hit_rate, expectancy_pct.
  - `MIN_COMBO_SAMPLES=5` 미만 버킷은 `insufficient=True` 표기(LLM 과신 방지).
  - 상위 엣지 추출: 충분표본 중 expectancy 내림차순 `top_positive`, 오름차순 `top_negative` (각 최대 15).
  - 엔벨로프: schema_version `mirofish.interaction_map.v1`, lookahead_safe True, generated_at, evaluated_count, max_order, top_positive, top_negative.
- `read_interaction_map()`.

## 7. brain agent 연결 (미션 락 충족 — 최소 통합)

`alpha_brain_agent.build_agent_observation`에 `interaction_map` 요약(top_positive/top_negative 충분표본만)과 `regime_distribution`을 추가 첨부. LLM Think 프롬프트가 단일축 엣지맵을 넘어 조합·레짐 증거를 본다. **스코어 영향 없음(읽기 전용)** — 채택은 기존 게이트가 L3에서 담당. 기존 관찰 키는 보존(하위호환).

## 8. 에러 핸들링

- 표본 0 / 파일 없음 → 빈 엔벨로프(row_count 0, 빈 맵) 반환, 예외 전파 금지.
- daily_prices.csv 없음 → regime_timeline 빈 dict, 모든 표본 `NEUTRAL` 폴백.
- 모든 JSON 쓰기 `write_json_atomic`. 디렉토리 없으면 생성.
- brain agent 통합부는 try/except로 격리 — Foundation 실패가 사이클을 죽이지 않음.

## 9. 테스트 전략 (LLM·네트워크 없음, 합성 데이터)

- `test_intelligence_regime.py`: breadth 계산 정확성, 임계값 경계(RISK_ON/OFF/NEUTRAL), lookahead-safe(미래행 무시), 결측 폴백.
- `test_intelligence_dataset.py`: 행 구성·필드 매핑, 미평가 표본 제외, regime 태깅, 빈 입력, 엔벨로프 스키마.
- `test_intelligence_interactions.py`: 2/3-way 집계 정확성, MIN_COMBO_SAMPLES insufficient, top_positive/negative 정렬, 빈 입력.
- `test_mirofish_alpha_brain_agent.py`(기존): 관찰에 interaction_map/regime_distribution 첨부 + 기존 키 보존 회귀.

## 10. Definition of Done

- 포커스 테스트 전부 통과(증거) → 광역 `-k "mirofish or agent or intelligence"` 회귀 없음
- 신규 모듈 결정론·lookahead-safe 단위 테스트 포함
- brain agent import + 드라이런 사이클 PASS 유지
- 읽기 전용(스코어 미변경) — 활성화 게이트 불필요(observe-only by construction)
- 의도한 파일만 스테이징
