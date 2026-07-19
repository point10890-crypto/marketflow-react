# Brain 13D → TradingAgents 라이브 링크 설계 (레짐 주입 매수 유력 검출 강화)

- 날짜: 2026-07-19
- 상태: 사용자 승인(설계 A + 최소 FE 버튼) → 스펙 리뷰 → writing-plans
- 참조: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0)
- 관련: [[project_tradingagents_layer]], `2026-07-17-tradingagents-deep-verification-design.md`

## 1. 목표

MiroFish 라이브 분석(store.py: TARGET→**Brain 13D**→GraphRAG→Debate→Verdict) 한 run 에 대해,
**그 run 의 Brain 13D 레짐 스냅샷을 TradingAgents 딥 검증에 주입**하여 레짐 인지 다중 에이전트
판정을 산출한다. 목적은 **매수 유력 종목 검출력 강화** — 레짐이 판정을 실제로 움직이되(강세 레짐
매수 상향 / 방어 레짐 억제) 종목 근거를 압도하지 않는 **유계 보정**.

- 온디맨드: 대시보드 버튼 → run 스코프 엔드포인트. 자동 파이프라인 단계 아님(시간/비용 이유).
- 기존 자동 워크플로우 TA 레이어(`workflow.py::_apply_tradingagents_layer`)·기존
  `/tradingagents/analyze`·`run_deep_analysis` 기본 호출은 **무변경**(신규 param 기본값 None).

## 2. Brain 13D 실제 데이터 형태 (검증됨)

`store._brain_summary(target)` → `brain_loader.load_brain_13d_snapshot`:
```
{ name, target, dimensions[13], dimension_scores{dim:{score,confidence,evidence,source}},
  alignment_score: 0~1 (예 0.62 = 62점), regime: <label>, memory_window, snapshot_at,
  sources, notes }
```
`regime` 라벨(13개 dim 평균 score 기반, `_high_level_regime`):

| 라벨 | 조건(avg) | 성격 |
|------|-----------|------|
| `constructive_bullish` | ≥70 | 강세 |
| `constructive_accumulation` | ≥55 | 완만 강세(매집) |
| `neutral_balanced` | ≥45 | 중립 |
| `defensive_caution` | ≥30 | 방어 |
| `risk_off` | <30 | 위험회피 |
| `unknown` / `data_unavailable` | 데이터 없음 | 무보정 |

## 3. 엔진 변경 (`tradingagents/`)

### 3.1 `data_hub.gather_bundle(target, *, brain=None)`
- 시그니처에 `brain: dict|None = None` 추가. 번들 계약에 `'brain': dict`(기본 `{}`) 필드 추가.
- brain 은 외부(엔진)에서 주입된 스냅샷을 그대로 담기만 함(수집 로직 없음 → data_hub 는 여전히
  종목 데이터 수집 책임만; brain 은 pass-through). 계약(LOCKED)에 `brain` 명시.

### 3.2 `run_deep_analysis(target, *, symbol=None, rounds=None, use_llm=True, brain=None)`
- `brain` 을 `data_hub.gather_bundle(target, brain=brain)` 로 전달.
- 레짐 요약을 한 번 정규화: `_regime_context(brain) -> {regime, alignment, label_ko, direction}`
  - `direction`: `bull`(constructive_*), `bear`(defensive_caution/risk_off), `neutral`(그 외/무데이터)
  - `alignment`: float 0~1 (없으면 None)
- run 레코드에 `regime_context` + `regime_adjustment`(아래) 저장. verdict 에 `regime`, `regime_adjustment` 노출.

### 3.3 레짐 주입 지점
1. **LLM 경로 (분석 강화)**: 분석가4·리서치매니저·PM 프롬프트 헤더에 레짐 1줄 주입
   예: `시장 레짐: 완만 강세(constructive_accumulation, 정렬 0.62). 종목 근거를 우선하되 레짐을 감안.`
   (analysts `_build_prompt`, research_debate `_llm_manager`/`_llm_side`, trader_risk `_llm_pm` 프롬프트에
   `bundle['brain']` / 주입된 regime_context 로부터 1줄 추가. 프롬프트만 확장, 스키마 무변경.)
2. **rule fallback (결정론 보정)**: **엔진**이 §3.4 규칙으로 조정 숫자(float)를 계산해
   `trader_risk.run_trader_and_risk(..., regime_adjustment=<float>)` 로 주입. trader_risk 는
   **PM 판정이 rule 일 때만** mean 밴드 계산 전 `mean_eff = mean + regime_adjustment` 적용
   (원본 mean 트레이스 보존). 계산 책임은 엔진, 적용 책임은 trader_risk PM.

### 3.4 레짐 보정 규칙 (유계, env 조절)
```
direction=bull  이고 alignment>=MIROFISH_TA_REGIME_ALIGN_MIN(기본 0.55):
    adjustment = +MIROFISH_TA_REGIME_BOOST (기본 +5.0)
direction=bear:
    adjustment = -MIROFISH_TA_REGIME_PENALTY (기본 -5.0)
그 외(neutral/unknown/data_unavailable/정렬 미달):
    adjustment = 0.0
```
- 보정은 **판정 밴드(STRONG_BUY≥35 / BUY≥15 / SELL≤-15)** 를 넘나들게 하되 유계(±5 기본).
- `verdict.regime_adjustment = {direction, alignment, applied}` 로 전량 트레이스.
- LLM 경로가 성공해도 rule 보정은 **적용 안 함**(LLM 은 프롬프트로 이미 레짐 인지) — 이중 반영 방지.
  즉 보정은 PM 이 rule fallback 일 때만. (verdict method 로 판별.)

## 4. 엔드포인트 (신규, `admin_mirofish_tradingagents.py`)

`POST /api/admin/mirofish/runs/<run_id>/tradingagents` (`@admin_or_aibain_required`)
1. `store.read_run(run_id)` → 없으면 404.
2. `brain = run.get('brain_summary')` (라이브 run 이 이미 산출; 없으면 `store._brain_summary(target)` 재로딩, 그래도 없으면 무보정).
3. `target = run['target']`; symbol 은 run 레코드에서 추출(정확한 키는 구현 계획에서 store 레코드
   스키마로 확정 — 없으면 None 로 진행, 엔진이 target 으로 재resolve).
4. `ta = engine.run_deep_analysis(target, symbol=symbol, brain=brain)`.
5. **run 부착**: `run['tradingagents'] = {run_id, verdict, confidence, strong_buy, regime, regime_adjustment, method, bull_case, bear_case, risk_summary}` → `write_json_atomic(run.json)` (원자적, 최근 수정된 재시도 경로 사용).
6. 200 + TA run 전체 반환.

- 실패 격리: TA 예외 시 500 + `{error}`, run 은 무손상. brain 없음/불가 → 무보정으로 정상 진행.
- 재실행 시 최신 TA 로 덮어씀(run.tradingagents 갱신).

## 5. 프론트엔드 (최소 버튼)

- `mirofishApi.ts`: `runTradingAgentsForRun(runId)` → `POST /runs/:id/tradingagents` (fetchAuthAPI).
- 라이브 run 뷰(AdminEndpointsPage 의 run 결과 영역)에 **"TradingAgents 딥검증"** 버튼 +
  결과 카드: verdict 배지(STRONG_BUY/BUY/HOLD/SELL) + confidence + 🔥매수유력(strong_buy) +
  레짐 보정 표기(`레짐 완만강세 → +5`) + bull/bear 1줄 + method(llm|rule|mixed).
- 로딩/에러 상태 처리. 기존 카드 그리드 다크 시스템(#0e0e11, 헤어라인, FA 아이콘) 준수.

## 6. env 요약

| 변수 | 기본 | 의미 |
|------|------|------|
| `MIROFISH_TA_REGIME_BOOST` | 5.0 | 강세 레짐 매수 가점 |
| `MIROFISH_TA_REGIME_PENALTY` | 5.0 | 방어 레짐 감점 |
| `MIROFISH_TA_REGIME_ALIGN_MIN` | 0.55 | 강세 가점 최소 정렬(0~1) |
| (기존) `MIROFISH_TRADINGAGENTS_DISABLED` | false | 엔진 자체는 미검사(온디맨드), 참고용 |

## 7. 테스트

1. `data_hub.gather_bundle(target, brain=...)` → 번들에 `brain` 실림 / brain=None → `{}`.
2. `run_deep_analysis(..., brain=bull_snapshot)` rule 경로 → `mean_eff = mean+boost`, verdict 밴드 상향 검증.
3. bear 스냅샷 → 감점, neutral/unknown/data_unavailable → 무보정(회귀 동일).
4. alignment 미달(<0.55) bull → 무보정.
5. LLM 경로(method=llm) → rule 보정 미적용(이중 반영 없음) 검증.
6. 엔드포인트: 정상 → 200 + run.tradingagents 부착 확인 / run 없음 → 404 / TA 예외 → 500 + run 무손상.
7. 기존 TA 스위트·`/tradingagents/analyze`·workflow 레이어 회귀 0.

## 8. 범위 제외 (YAGNI)

- 자동 파이프라인 단계 편입(온디맨드 한정).
- Brain 13D 전용 5번째 "레짐 분석가"(접근안 C) — 후속 확장으로 보류.
- US/Crypto 확장(KR 라이브 run 한정).
