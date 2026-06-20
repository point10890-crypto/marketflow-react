# TOP3 검출 스코어카드 (top3_metrics) — 설계 스펙

- **날짜**: 2026-06-20
- **상태**: 승인됨 (brainstorming)
- **범위**: 측정 모듈 + 에이전트 관찰 연결 (1 단위)
- **관련**: [[project_alpha_intelligence]], `docs/superpowers/specs/2026-06-15-alpha-intelligence-foundation-design.md`
- **딥리서치 근거**: learn-to-rank top-K 정밀도 최적화, Rank IC 평가 (Qlib/AlphaForge), TOP3 expectancy를 측정 가능하게 만드는 것이 후속(conformal/learn-to-rank)의 보상 기반.

## 1. 배경 / 문제

알파 스캐너는 `ranking_score` 정렬의 상단을 TOP3로 내보내지만, **그 TOP3가 실제로 얼마나 잘 맞는지 측정하는 지표가 없다.**

- `outcome_tracker.summarize_outcomes`는 단일 워크플로우 한정으로 `top3_hit_rate_pct`만 계산 (`outcome_tracker.py:386-399`). 교차-런 집계·top-K 정밀도·NDCG·Rank IC·baseline 대비 lift가 전무.
- 자율 에이전트의 목적함수는 명시적으로 *"improve Top3 forward-return expectancy"* (`alpha_brain_agent.py:67`)인데, **그 목표를 측정하는 스코어카드가 없어 학습 루프가 깜깜이로 돈다.**

이 스펙은 TOP3 검출 품질을 **결정론·lookahead-safe·읽기전용**으로 측정해 에이전트 관찰에 부착한다. 스코어링/랭킹/알림 로직은 일절 변경하지 않는다 (회귀 0).

## 2. 비범위 (YAGNI)

- FE 카드 / admin 엔드포인트 노출 — 다음 단위
- conformal 확신도 게이팅 — 다음 단위
- learn-to-rank 가중 대체 — 다음 단위
- 스코어/랭킹/알림 동작 변경 — **하지 않음**
- `outcome_tracker` 수정 — 읽기만, 수정 안 함

## 3. 데이터 소스

`outcome_tracker._recent_workflow_ids(limit_workflows)` → `read_workflow_outcomes(wf_id)` 로 **런 그룹핑을 보존**하여 소비한다 (평탄화된 `edge_map._evaluated_items`는 rank/런 경계를 잃으므로 쓰지 않는다).

각 평가 아이템이 제공하는 필드 (`outcome_tracker.evaluate_result_outcome` 결과):
- `rank` (런 내 순위, 1=최상위), `forward_return_pct`, `hit` (bool|null), `status`, `symbol`, `feature_snapshot.ranking_score`.

평가 대상 = `status in {'evaluated','partial'}` 이고 `hit is not None` 인 아이템.

**lookahead-safe**: 소비하는 outcome 자체가 strict forward-price replay(entry_date 이후 가격만)로 산출되므로 안전. 모듈은 미래 정보를 새로 끌어오지 않는다.

## 4. 모듈 인터페이스

신규 파일: `app/services/mirofish/intelligence/top3_metrics.py`

```python
# 공개 API
build_top3_metrics(*, limit_workflows=200, runs=None, write=True) -> dict
read_top3_metrics() -> dict | None
top3_metrics_summary() -> dict          # 관찰 임베드용 컴팩트 뷰

# 순수함수 (단위테스트 1차 표적)
_compute_run_metrics(items: list[dict]) -> dict   # 한 런의 top-K 지표
_aggregate_runs(run_metrics: list[dict]) -> dict  # 교차-런 pooled/macro
```

- `runs=` 주입(테스트용): 각 원소는 `{'workflow_id': str, 'items': [outcome_item, ...]}` 형태. `None`이면 워크플로우에서 로드.
- 출력 파일: `data/admin_mirofish/intelligence/top3_metrics.json` (`write_json_atomic`, `sort_keys=False`).
- 결정론: 정렬 키 `(rank ASC, ranking_score DESC, symbol ASC)`. LLM/네트워크 없음.

## 5. 지표 정의

### 5.1 런 단위 (`_compute_run_metrics`)
평가 아이템 n개를 `(rank, -ranking_score, symbol)`로 정렬 후:

- `precision_at_k` (k=1,3,5) = top-k 중 `hit is True` 비율 (분모 `min(k, n)`)
- `top3_mean_return_pct` = top-3 `forward_return_pct` 평균
- `baseline_hit_rate` = 전체 n개 hit 비율
- `overall_mean_return_pct` = 전체 평균 수익
- `hit_lift_at_3` = `precision_at_3 - baseline_hit_rate`
- `return_lift_at_3` = `top3_mean_return_pct - overall_mean_return_pct`
- `ndcg_at_3` = gain `g_i = max(forward_return_pct, 0)` 기준 `DCG@3 / IDCG@3` (IDCG=0이면 0.0)
- `rank_ic` = 스캐너 순위(예측: `-rank`) vs 실현 `forward_return_pct` Spearman 상관. **n < 3 또는 분산 0이면 `None`**.
- `map_at_3` = top-3 위치 기준 average precision

레코드: `{workflow_id, entry_date, n, precision_at_1/3/5, top3_mean_return_pct, baseline_hit_rate, overall_mean_return_pct, hit_lift_at_3, return_lift_at_3, ndcg_at_3, rank_ic, map_at_3, insufficient}`. `insufficient = n < MIN_RUN_SAMPLES`.

### 5.2 교차-런 집계 (`_aggregate_runs`)
- **pooled (micro)**: 모든 런의 top-3 아이템 풀링 → `top3_hit_rate`, `top3_mean_return_pct`; 전체 풀링 → `baseline_hit_rate`, `overall_mean_return_pct`; `top3_hit_lift`, `top3_return_lift`; `top1_hit_rate`, `top5_hit_rate`; `top3_item_count`, `baseline_item_count`.
- **macro (mean-of-runs)**: 자격 런(`n >= MIN_RUN_SAMPLES`)에 대해 `precision_at_1/3/5`, `ndcg_at_3`, `map_at_3` 평균; `rank_ic_mean`은 `rank_ic is not None`인 런만 평균 + `rank_ic_run_count`; `run_count`.

### 5.3 표본 게이트
- `MIN_RUN_SAMPLES = 3` (런 자격 — top3 의미를 가지려면 최소 3)
- `MIN_RUNS = 5` (집계 신뢰)
- `insufficient = qualified_runs < MIN_RUNS` → **숫자는 그대로 노출하되 신뢰부족 플래그만 표기**. (현 26표본·RISK_ON 편중 상황에서 과신 방지)

## 6. 출력 스키마

파일: `data/admin_mirofish/intelligence/top3_metrics.json`

```jsonc
{
  "schema_version": "mirofish.top3_metrics.v1",
  "generated_at": "<iso>",
  "lookahead_safe": true,
  "evaluated_runs": 0,        // 평가 아이템 >=1 인 런 수
  "qualified_runs": 0,        // n>=MIN_RUN_SAMPLES 인 런 수
  "total_evaluated_items": 0,
  "min_run_samples": 3,
  "min_runs": 5,
  "insufficient": true,
  "pooled": {
    "top1_hit_rate": null, "top3_hit_rate": null, "top5_hit_rate": null,
    "baseline_hit_rate": null, "top3_mean_return_pct": null,
    "overall_mean_return_pct": null, "top3_hit_lift": null, "top3_return_lift": null,
    "top3_item_count": 0, "baseline_item_count": 0
  },
  "macro": {
    "precision_at_1": null, "precision_at_3": null, "precision_at_5": null,
    "ndcg_at_3": null, "map_at_3": null,
    "rank_ic_mean": null, "rank_ic_run_count": 0, "run_count": 0
  },
  "runs": [ /* 런별 레코드, 최신 최대 50개 */ ]
}
```

빈 입력 시 위 형태 그대로 (예외 없이) 반환한다.

## 7. 에이전트 연결 (읽기전용·격리)

`alpha_brain_agent._intelligence_summary()` (`alpha_brain_agent.py:370`)에 `top3_metrics` 키 추가:
- 기존 `interactions`/`dataset` 와 **동일한 try/except 격리 패턴** — 결손/예외 시 관찰을 깨뜨리지 않음.
- `top3_metrics.read_top3_metrics()` 우선, 없으면 `build_top3_metrics(write=True)` 1회 생성. 컴팩트 요약(`top3_metrics_summary()`)만 부착.
- `build_agent_observation` 반환 dict에 `'top3_metrics': intelligence['top3_metrics']` 추가 (`alpha_brain_agent.py:88-89` 인근).
- **스코어/오버라이드/액션에 일절 영향 없음** — 관찰(Sense) 표면에만 노출.

## 8. 테스트 (TDD)

`tests/` 신규 (기존 mirofish 테스트 컨벤션 따름):
1. 완벽 순위(top3=실제 최고수익 hit) → `precision_at_3=1.0`, `ndcg_at_3=1.0`, `rank_ic≈+1`
2. 역순위 → `precision_at_3` 낮음, `rank_ic≈-1`
3. n<3 런 → `insufficient=True`, `rank_ic is None` 경계
4. 빈 입력 → 안전한 0/null envelope, 예외 없음
5. 교차-런 집계: pooled vs macro 분리 검증, `MIN_RUNS` 게이트
6. `_intelligence_summary()` 격리: top3_metrics 결손/예외 시에도 관찰 정상 반환

## 9. 검증 (Verify)

- 신규 단위테스트 전부 통과
- 전체 mirofish 테스트 스위트 회귀 0
- CLAUDE.md 스킬 4 (엔진/앱 임포트 + 라우트) 통과
- `build_agent_observation()` 1회 실드런 → `top3_metrics` 키 존재 + 예외 없음
- `outcome_tracker`/스코어링 미변경 확인 (diff 검토)

## 10. 팀 실행 (Router/Worker/Repair)

- **Worker 1**: §4~6 모듈 + §8(1~5) 단위테스트 (TDD)
- **Worker 2**: §7 연결 + §8(6) 통합테스트 (Worker 1 의존)
- **Repair/Review**: §9 검증 + 코드리뷰 + 회귀

각 워커는 14조 절대규칙·고정경로(`"$PYTHON"`, `PYTHONIOENCODING=utf-8`)·하네스 프로토콜 준수.
