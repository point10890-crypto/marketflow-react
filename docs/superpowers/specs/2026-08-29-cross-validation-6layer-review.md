# 교차검증 6계층 제안 — 실증 대조 및 실행 설계

작성일: 2026-08-29 (KST)
성격: 사용자 제안 "Orca 교차검증 6계층 주식 투자 판단 시스템"을 **저장소 실측과 대조**해
      실제로 만들 것과 이미 있는 것을 가른 실행 설계
상위 문서: `2026-08-24-goal-definition-master-plan.md` (목표: 검출 정밀도)
관련: `2026-08-24-alphaclaw-integration-review.md` (B4 = 본 문서 L4 의 원안)

---

## 0. 판정 한 줄

제안의 **틀은 타당하고 L4(기계적 검증)는 진짜 빠져 있다.** 그러나 L2·L3·L5 는 이미
구현·가동 중이고, L6 의 제안 스택은 운영 프론트와 충돌하며, 인프라 개념(Orca ADE +
worktree 로 런타임 분석 오케스트레이션)은 범주 오류다. **L4 하나에 집중하면 제안의
핵심 가치(AI 환각·수치 왜곡 차단)를 실제로 얻는다.**

---

## 1. 계층별 실증 대조

| 계층 | 제안 내용 | 저장소 실측 | 판정 |
|---|---|---|---|
| **L1** 근거 수집 | 재무·뉴스·공시 병렬 수집, MD+JSON 이원화 | KIS 스크리너·`dart_collector`·뉴스 수집기·`data_hub` 가동 중. 확장안은 옴니소스 설계(P4)에 이미 명세 | **대체로 존재** — 확장은 P4 순서 유지 |
| **L2** 독립 판단 | 두 팀이 서로 안 보고 bull/bear/risk 분석 | `tradingagents/engine.py`: `data_hub → analysts(4) → research_debate → trader_risk → verdict`. 별도로 `MultiAIConsensusScreener`(Gemini·OpenAI·Grok·Claude 스크리너 + `_build_consensus` 교집합) | **이미 존재** |
| **L3** 교차 반박 | 최대 3라운드 루프 | `research_debate.run_research_debate(rounds=2)` — env `MIROFISH_TA_DEBATE_ROUNDS`, clamp 1~4. 라운드별 bull/bear + manager 판정 | **이미 존재** (라운드 수는 env 한 줄) |
| **L4** 기계적 검증 | Python 으로 수치·출처·기준일 정합성 검증 | **없음.** `numbers_used` 0건, LLM 출력 수치 대조·폐기 로직 0건. `analysts.evidence` 는 문자열 리스트일 뿐 원천 대조 없음 | **진짜 갭 — 최우선 구축** |
| **L5** 최종 종합 | 공통 사실·의견 대조·신뢰도 수치화 | `decision_brief.py` (2026-08-29 배포) — 근거 7종 팬아웃, `summarize_agreement`, 결정론 `confidence_cap` | **어제 구축됨** |
| **L6** 웹 대시보드 | FastAPI + Jinja2 + Tailwind + ECharts | Vite React + Cloudflare Pages 운영 중(SEO 프리렌더 포함). 제안 스택은 **병렬 프론트가 되어 충돌** | **스택 기각** — 기존 대시보드에 카드 추가 |

### 1.1 인프라 개념에 대한 판정

- **Orca ADE + Git worktree + 코디네이터/워커** — Orca 는 *코딩 에이전트*를 worktree 에
  격리 실행해 **코드를 쓰게 하는** 개발 도구다. 일일 주식 분석을 worktree 로 돌리는 것은
  범주 오류이며, 런타임 파이프라인은 이미 `scheduler.py` + SYSTEM 태스크 + 워치독 4종으로
  무인 가동 중이다(8/27 장중 612틱 완주, 5001 프로듀서 자동복구 실증).
- 다만 **개발 단계에서 Orca 를 쓰는 것은 타당하다** — 이 설계를 구현하는 작업 자체를
  병렬화하는 용도. 런타임 아키텍처에 넣지 않는다.
- **"두 팀 독립 판단"의 제약**: Anthropic 크레딧 소진으로 Claude 레인은 비활성이고
  `llm_client.SUPPORTED_PROVIDERS = (deepseek, openai, gemini)` 다. 실질 2팀은
  **Gemini vs DeepSeek/OpenAI** 로 구성해야 한다(이미 `MultiAIConsensusScreener` 가 그 구조).

---

## 2. L4 기계적 검증 계층 — 상세 설계 (본 문서의 본체)

제안에서 유일하게 미구현이며, 프로젝트의 확립된 원칙 **"LLM 은 숫자를 소유하지 않는다"**를
지금까지 *규칙*으로만 적었지 코드로 강제한 적이 없다. L4 가 그 강제 장치다.

### 2.1 모듈 `app/services/mirofish/number_guard.py`

```
extract_claims(text)              → [NumericClaim{raw, value, unit, context}]
verify_claims(claims, bundle)     → Verdict{verified[], unverified[], contradicted[]}
guard_output(text, bundle)        → (accepted: bool, verdict, reason)
```

- **대조 원천(bundle)**: `data_hub` 번들의 가격·재무·수급·공시 수치, `daily_prices.csv`,
  스냅샷 필드. LLM 이 만든 값이 아니라 **수집기가 가져온 값만** 진실로 취급한다.
- **허용 오차**: 반올림 표기 차이만 허용(상대 1% 또는 표기 자릿수 이내). 그 밖은 미검증.
- **판정**:
  - `contradicted` ≥ 1 → **산출 폐기**, 결정론 템플릿으로 대체 (기존 Claw analyst 규칙의 코드화)
  - `unverified` 만 존재 → 산출은 유지하되 `confidence_cap` 감산 + `data_gaps` 기록
  - 전부 `verified` → 통과

### 2.2 기준일(lookahead) 검증

수치마다 `as_of` 를 요구하고, 번들 워터마크(`source_watermark`)보다 **미래 데이터가 인용되면
무조건 contradicted**. 관측 원장이 이미 `source_watermark` 를 보유하므로 재사용한다.

### 2.3 적용 지점 (기존 경로에 얹기 — 신규 파이프라인 없음)

| 적용 대상 | 효과 |
|---|---|
| `tradingagents/analysts.py` 산출 | 애널리스트 리포트의 수치 환각 차단 |
| `tradingagents/research_debate.py` | 토론 라운드에서 창작된 수치 차단 (L3 품질의 실질 상승) |
| `marketflow_claw/reporter.py` 서술 | 텔레그램 브리핑 수치 보증 |
| `decision_brief.py` | 검증 결과를 `confidence_cap` 에 반영 |

### 2.4 산출 스키마 (`mirofish.number_guard.v1`)

```json
{"accepted": true, "verified": 7, "unverified": 1, "contradicted": 0,
 "claims": [{"raw": "+8.4%", "value": 8.4, "status": "verified",
             "matched_field": "chg_pct", "source": "kis_snapshot",
             "as_of": "2026-08-28T15:20:00+09:00"}],
 "policy": "discard_on_contradiction"}
```

---

## 3. 실행 순서 (목표 = 검출 정밀도 기여도 순)

| 단계 | 내용 | 근거 |
|---|---|---|
| **A** | `number_guard` 코어 + TradingAgents 적용 (TDD) | 유일한 실제 갭, 환각 차단은 정밀도에 직결 |
| **B** | `decision_brief` 에 검증 결과 반영 — 미검증 수치 있으면 cap 감산 | L5 와 L4 결합 |
| **C** | L3 라운드 2 → 3 (`MIROFISH_TA_DEBATE_ROUNDS=3`) + 비용 측정 | env 한 줄, 효과는 측정 후 판단 |
| **D** | L6 — 기존 React 대시보드에 판단 브리프 카드(합의/이견/검증 배지) | FastAPI 신설 대신 기존 스택 |
| **E** | L1 확장 = 옴니소스 O1 (뉴스 RSS 상시화) | 기존 P4 순서 유지 |

**하지 않을 것**: FastAPI/Jinja2 병렬 프론트, 런타임 worktree 오케스트레이션,
"Claude 팀" 전제(크레딧 부재), L2/L3 재구축.

---

## 3-A. C단계 실측 판정 — **기각 (rounds=2 유지)** (2026-08-29)

토론 라운드 2→3 을 값만 올리지 않고 A/B 실측했다. 저장된 TA run 의 `analyst_reports` 를
입력으로 고정해 토론 단계만 두 설정으로 돌렸다(운영 상태 미오염, run 저장 없음).

**측정 무효 1회**: 첫 실행이 `method=rule` 로 나왔다 — 스크립트가 `.env` 를 로드하지 않아
LLM 키 없이 결정론 폴백을 측정한 것. 규칙 경로는 라운드 수와 무관하므로 "변화 0"이라는
그럴듯하지만 틀린 결론이 나왔다. dotenv 로드 후 재측정.

**n=6 결과 (실제 LLM 경로)**

| 지표 | 결과 |
|---|---|
| 판정(stance) 변화 | **1/6** (bull 65 → bear 70, 경계 사례 1건) |
| 확신도 델타 | **5/6 이 0.0** |
| 3라운드 신규성 | 0.32~0.55 (새 논거는 실제로 추가됨) |
| 비용 | LLM 호출 **+2/건 (+40%)**, 지연 **+5.7~6.5초** (일관) |

**정정**: n=2 예비 측정에서 관찰된 확신도 하락(−2.0, −5.0)을 "과신 교정 효과"로 해석했으나
**n=6 에서 재현되지 않았다**(5/6 델타 0). 같은 종목 재측정에서 R2 자체가 82→80, 75→70 으로
움직인 것으로 보아 그 하락은 **3라운드 효과가 아니라 LLM 호출 간 변동성**이었다. 해석을 철회한다.

**판정 근거**
1. 확신 교정 효과 미재현 — 편익의 주요 후보가 사라짐
2. 유일한 변화(판정 뒤집힘 1/6)가 개선인지 불안정인지 **forward outcome 없이 판별 불가**
3. 비용은 확실하게 측정됨(+40% 호출, +6초)
4. ⇒ **비용은 확정, 편익은 미확인** → "측정 없이는 정책 없다" 규율상 채택 불가

**재론 조건**: 관측 원장 세션 게이트(20세션) 도달 후, 라운드 상향 검출의 forward outcome 이
2라운드 대비 유의하게 나은지 확인될 때. 그 전에는 `MIROFISH_TA_DEBATE_ROUNDS=2` 유지.

**부수 발견 (후속 과제)**: 같은 입력·같은 설정에서도 판정 확신이 흔들린다(R2 재측정 시
82→80, 75→70). 딥검증 판정의 재현성 자체가 측정 대상이며, `decision_brief` 의
tradingagents 소스 신뢰도에 영향을 준다. 동일 설정 반복 실행의 일관성 측정을 별도 과제로 둔다.

## 3-B. 판정 재현성 측정 — **stance 안정 확인, 매니저 판정 결정론화 채택** (2026-08-29)

3-A 에서 "같은 입력인데 확신이 흔들린다"를 후속 과제로 남겼다. 원인을 코드에서 특정하고
(매니저 판정 `temperature=0.3`, 토론 메시지 0.5) 반복 실행으로 분산을 측정했다.
같은 `analyst_reports` 입력 고정, 종목 2 × 반복 5 × 2설정 = 20회.

| 설정 | stance 일치 | confidence | 표준편차 |
|---|---|---|---|
| A `temp=0.3` (현행) | **10/10** | [80,85,80,80,80] / [75,70,70,75,70] | 2.23 |
| B `temp=0.0` | **10/10** | [80,80,80,80,80] / [70,70,70,70,75] | **1.00** |

**핵심: 방향(stance)은 흔들리지 않는다.** 두 설정·두 종목 모두 10/10 일치.
따라서 `decision_brief` 의 tradingagents **stance 신호는 신뢰 가능**하다.
3-A 에서 관찰된 "판정 뒤집힘 1/6"은 반복 노이즈가 아니라 **라운드 수(2 vs 3) 차이의 결과**였다.

**정정**: 3-A 부수 발견을 "판정 재현성 문제"로 적었으나, 실제로 흔들린 것은 confidence 뿐이고
stance 는 안정적이었다. 우려를 과하게 표현했던 것을 정정한다.

**남은 실질 리스크**: confidence 가 ±5 흔들리므로 **임계값 경계 사례**가 뒤집힐 수 있다.
`MIROFISH_TA_SELL_EXCLUDE_MIN_CONFIDENCE=65` 근처에서 포함/제외가 갈린다.

**채택 조치**: 매니저 판정 `temperature 0.3 → 0.0` (`research_debate.py`).
- 근거: 기계가 소비하는 값(decision_brief 근거·TA 가점·SELL 제외 임계)이므로 결정론이 옳다.
  실측상 확신 표준편차 2.23 → 1.00 으로 절반 감소. **추가 비용 0.**
- 토론 메시지(0.5)는 논거 다양성이 유용하므로 **유지**한다.
- 한계: temp=0.0 에서도 완전 결정론은 아니다(종목 2 는 70/75 혼재) — provider 특성.
  품질 영향은 측정하지 않았다(구조화 JSON 판정에서 결정론 디코딩은 표준 관행).
- 계약 테스트 `tests/test_tradingagents_determinism.py` 로 고정.

**후속 과제**: 임계값 경계 완충(히스테리시스 또는 confidence 밴드 처리) — 표본 축적 후 판단.

## 4. 제안에서 채택한 것 (설계 기여)

1. **기계적 검증을 독립 계층으로 승격** — 지금까지 규칙 문장이던 것을 강제 코드로.
2. **기준일 정합성**을 검증 대상에 포함 — lookahead 를 산출물 단계에서도 막는다.
3. **"인위적 추가 판단 배제"**(L5) — `decision_brief` 가 이미 따르는 원칙의 재확인:
   종합 계층은 새 의견을 만들지 않고 대조만 한다.

## 5. 결정 필요 사항

1. 실행 순서 A→E 동의 여부 (A 부터 착수 권장)
2. L3 라운드 3 상향 시 LLM 비용 증가 허용 범위
3. `unverified` 수치 정책 — cap 감산(권장) vs 해당 문장 삭제
