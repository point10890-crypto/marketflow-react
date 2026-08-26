# MarketFlow 국내 주식 분석 코어 재설계안 v2

작성일: 2026-08-24 (KST)
상태: 구현 전 설계 확정안
검토 대상: Claude Code 작성 `국내 주식 자율 학습·분석·종목검출 시스템 — 재설계안`

## 0. 결론

Claude 설계안의 방향은 맞지만 그대로 구현하지 않는다.

- 유지: 기존 Flask, `marketflow_claw`, MiroFish 스캐너, SQLite/JSON 산출물, Windows Task Scheduler 운영 구조
- 채택: 기존 스캐너 필드를 재사용하는 공통 관측 계약, 후보 생명주기, 실행 가능한 무효화 감시, Claw 사후성과 측정
- 수정: 4국면을 단일 정본으로 승격하는 안, 근거의 `S/A/B/C` 명칭, 임의의 숫자형 `confidence_cap`, 모든 검출에 적용하는 2출처 규칙
- 보류: 검증 없이 `INVALIDATED` 알림을 즉시 발송하는 안, USD/KRW 신규 수집, 새 API·화면의 선행 개발
- 기각: 신규 FastAPI/포트, 별도 학습기와 `weights.json`, 네이버 HTML 수집, 멀티에이전트 재구축

핵심은 새 점수표를 하나 더 만드는 것이 아니다. 스캐너의 기존 `evidence`, `evidence_quality`, `confidence_cap`, `profitability_scorecard`, `missing_confirmations`, `entry_plan.invalidation`을 보존하고, 두 검출 레인에서 빠진 **식별자·시각·상태 의미만 공통 Signal Record로 정규화**한다. 그 뒤 결과가 재현된 규칙만 승격한다.

## 1. 코드 대조 결과

| 영역 | 현재 구현 | 원안 판단 | v2 결정 |
|---|---|---|---|
| 서비스 경계 | Flask API, Claw 프로세스, 기존 스케줄러 | 신규 FastAPI 불필요 | 현 구조 유지 |
| 일간 검출 | `alpha_scanner.py`에 근거, 신선도, evidence quality, confidence cap, profitability scorecard, missing confirmations, entry invalidation, evidence ledger가 존재 | G1이 전부 비어 있다는 전제는 오류 | 새 점수 계산 없이 기존 후보를 공통 Signal Record로 투영 |
| 장중 검출 | Claw가 snapshot diff, HALT, 중복 억제, 전달 상태를 관리 | 무효화·outcome 부재 | 기존 이벤트는 유지하고 후보 생명주기와 outcome을 옆에 추가 |
| 학습 안전성 | replay/policy/bounded action/rollback이 있고 outcome·TA memory 경로도 병존 | 단순 Bayesian learner 기각 | scanner 변경은 기존 guarded 경로만 사용; Claw outcome은 관찰 전용 |
| 레짐 | `intelligence/regime.py`는 breadth 기반 3상태, 4국면은 `detection_lab.py`와 `paper_orchestrator.py`가 파생 | 4국면을 정본으로 승격 | EOD 국면과 실시간 gate를 함께 담는 `RegimeContext`를 정본으로 사용 |
| 결측 처리 | 스캐너 freshness 차단과 Claw partial/HALT가 각각 존재 | 통합 필요 | 공통 상태명만 맞추고 레인별 안전 규칙은 유지 |
| 성과 | 스캐너·paper는 성과 측정 경로가 있으나 Claw 이벤트에는 없음 | G3 타당 | 가격 기준과 거래일을 먼저 고정한 범용 horizon outcome 도입 |

### 반드시 바로잡을 사실

1. `app/services/mirofish/intelligence/regime.py`는 4국면 정본이 아니다. 이 파일은 `RISK_ON / NEUTRAL / RISK_OFF`를 생성하고, 4국면은 다른 모듈에서 파생된다.
2. `paper_orchestrator.market_phase()`는 타임라인이 없을 때 `leader_market`으로 폴백한다. 이 값은 데이터 확인 결과가 아니므로 승격·발송 판단에 사용하면 안 된다.
3. 저장된 `report_20260817_100036.json`은 `detections=603`이지만 baseline 실제 거래는 367건이다. 367건 모두 phase가 `unknown`이고 `V1_regime_gate`도 baseline과 동일한 승률 37.3%, 기대수익 -1.43%, PF 0.67이다. 원안의 “게이트 후 +2.60%, 승률 63%, PF 2.06”은 이 저장 산출물로 재현되지 않는다.
4. 이번 검토 중 현재 데이터로 읽기 전용 재실행한 참고치는 623 detections였다. live식 차단(negative phase 차단, unknown 허용)은 120 trades·승률 44.2%·기대수익 -0.32%·PF 0.92, positive phase만 남기면 73 trades·52.1%·+0.90%·PF 1.28이었다. 과거 주장과 다르고 아직 버전된 산출물이 아니므로 운영 근거로 채택하지 않는다.
5. 따라서 “양의 국면에만 알파가 존재한다”는 문장을 운영 규칙의 근거로 사용할 수 없다. 먼저 phase coverage를 복구하고 동일 입력·코드 버전으로 리포트를 재생성해야 한다.
6. 스캐너에는 이미 evidence/freshness뿐 아니라 confidence cap, 결측 확인, 수익성 scorecard와 문자열 invalidation도 있다. `facts[]`와 새 scorecard를 별도 체계로 만들면 동일 판단이 두 번 관리된다.
7. Claw의 `events`는 `UNIQUE(day, type, code)`와 전달 상태를 중심으로 설계됐다. 여러 차례의 후보 생성·무효화·재활성화를 이 테이블 하나에 억지로 넣지 않는다.
8. 기존 `top3_metrics.json`은 생성 시각이 2026-06-20이고 qualified run 3건, `insufficient=true`다. 계산 코드가 있다는 사실만으로 최신 KPI가 노출 가능한 것은 아니며 freshness와 재생성 주기가 먼저 필요하다.
9. replay/learning policy/rollback 경로는 존재하지만 outcome memory와 TradingAgents memory도 별도 경로로 점수에 관여한다. 이를 “유일한 단일 5단계 학습 체인”이라고 부르지 않는다. Claw outcome은 어느 경로에도 자동 연결하지 않는다.

## 2. 목표와 비목표

### 목표

- 모든 후보가 무엇을 관측했고 무엇을 모르는지 기계 판독 가능하게 남긴다.
- 양의 후보 알림과 위험 알림의 차단 정책을 분리한다.
- 국면·근거·무효화 규칙이 LLM 문장에 의존하지 않게 한다.
- Claw와 스캐너 결과를 같은 성과 정의로 비교할 수 있게 한다.
- 과거 시점 데이터만 사용하는 재현 가능한 검증 경로를 만든다.

### 비목표

- 자동 주문·매매 지시·실계좌 수익 보장
- 새 상주 서버, 새 포트, 새 데이터 수집 사업
- 기존 스캐너 산출물과 Claw 이벤트의 전면 교체
- 검증 전 점수 자동 보정 또는 숫자형 확률 제공
- 대시보드를 먼저 만들고 분석 계약을 나중에 맞추는 작업

## 3. 목표 구조

```text
기존 원천 데이터
  ├─ 일간 레인: alpha_scanner / workflow / paper
  └─ 장중 레인: KIS screener / marketflow_claw
          ↓
레인별 정본
  ├─ scanner: mirofish.profitability_goal.v2 (기존 v1의 호환 확장)
  └─ claw: claw.signal_episode.v1 (신규 관측 원장)
          ↓
읽기 전용 공통 어댑터: Evidence + DataGap + RegimeContext + SignalView
          ↓
후보 상태 평가: observed → watch → invalidated | expired
          ↓
Outcome 관측: D1/D5 등 거래일 horizon + 벤치마크 초과수익
          ↓
별도 OOS 검증을 통과한 규칙만 운영 승격
```

공통 어댑터 코드는 Flask나 LLM에 의존하지 않는 순수 함수로 둔다. 권장 위치는 `app/services/signal_contract.py`다. 어댑터는 기존 점수나 cap을 재계산하지 않고 필드명과 상태만 정규화한다. 저장 방식은 통합하지 않는다.

- 스캐너: `mirofish.profitability_goal.v1`을 하위 호환 `v2`로 확장한다. 기존 candidate와 evidence ledger가 정본이다.
- Claw: 기존 `events`는 그대로 두고 `signal_episodes`, `signal_state_events`, `outcome_observations`를 기존 Claw SQLite에 증분한다.
- 공통 API가 필요해질 때만 두 정본을 `marketflow.signal_view.v1`로 변환한다. 이 view는 저장하거나 다시 점수화하지 않는다.

## 4. 공통 계약

### 4.1 SignalView v1: 중복 scorecard가 아닌 읽기 모델

```json
{
  "schema_version": "marketflow.signal_view.v1",
  "signal_instance_id": "claw:20260824:005930:leader_new:090712",
  "lane": "scanner|claw",
  "symbol": "005930",
  "kind": "SCANNER_CANDIDATE|LEADER_NEW|LEADER_UPGRADE|LEADER_DROP|...",
  "lifecycle_state": "observed|watch|invalidated|expired",
  "visibility": "internal|user_visible|suppressed",
  "produced_at": "2026-08-24T09:07:12+09:00",
  "data_as_of": "2026-08-24T09:07:10+09:00",
  "expires_at": "2026-08-26T15:30:00+09:00",
  "reference_price": {"value": 81200, "source_id": "kis_quote", "as_of": "..."},
  "native_scorecard_ref": {
    "schema_version": "mirofish.profitability_goal.v2",
    "source_run_id": "..."
  },
  "regime_context": {},
  "evidence": [],
  "invalidators": [],
  "data_gaps": [],
  "quality": {},
  "provenance": {"source_run_id": "...", "source_event_id": 123}
}
```

규칙:

- `signal_instance_id`는 검출 1회를 식별한다. 종목·날짜만으로 동일시하지 않는다.
- `kind`는 기존 이벤트 의미를 보존하며, `lifecycle_state`와 혼합하지 않는다.
- `visibility`는 전달 정책 결과다. `watch`라고 해서 자동 발송되는 것은 아니다.
- `native_scorecard_ref`는 스캐너의 기존 scorecard를 가리킨다. 값 복제와 재계산을 금지한다.
- buy/sell 상태를 추가하지 않는다.
- LLM은 설명 문구를 만들 수 있지만 위 필드의 값이나 통과 여부를 변경할 수 없다.

### 4.2 Evidence

종목 등급 `S/A/B`와 혼동하지 않도록 근거 등급은 다음 이름을 쓴다.

| `source_tier` | 의미 | 예시 |
|---|---|---|
| `primary` | 원기관·원거래 데이터 | KIS 시세/수급, DART 공시, KRX 데이터 |
| `derived` | 원천값으로 결정론 계산 | breadth, RS, 이동평균, 거래대금 점수 |
| `interpretive` | 모델·문서 해석 | 뉴스 요약, LLM 논거, 애널리스트 해석 |
| `unverified` | 출처나 시점 확인 불가 | 출처 없는 텍스트, 실패한 폴백 값 |

```json
{
  "evidence_id": "kis_quote:005930:20260824T090710",
  "source_id": "kis_quote",
  "source_tier": "primary",
  "domain": "market_price",
  "field": "current_price",
  "value": 81200,
  "as_of": "2026-08-24T09:07:10+09:00",
  "observed_at": "2026-08-24T09:07:12+09:00",
  "freshness": "fresh|stale|unknown",
  "fallback_used": false
}
```

`as_of`와 `observed_at`을 분리한다. 파일 수정 시각이나 수집 시각을 실제 시장 시각처럼 취급하지 않는다. `interpretive`와 `unverified`는 통과 요건을 단독으로 충족할 수 없다.

### 4.3 DataGap

문자열 목록 대신 영향과 재시도 가능 여부를 남긴다.

```json
{
  "input": "investor_flow",
  "reason": "timeout|missing|stale|parse_error|not_applicable",
  "as_of": "2026-08-24T09:07:10+09:00",
  "impact": "score_omitted|invalidator_unknown|promotion_blocked",
  "retryable": true
}
```

결측은 0점이나 중립값으로 위장하지 않는다. 관측 자체는 보존하되, 사용자 노출 승격은 필요한 입력이 없으면 fail-closed 한다.

### 4.4 Quality와 표현 상한

스캐너에는 이미 `_confidence_cap()`과 `profitability_scorecard.confidence_cap`이 있다. 이를 없애거나 원안의 `0.75 - 0.10` 공식으로 이중 계산하지 않는다. 기존 값은 **스캐너 내부 규칙 상한**으로 보존하되 통계적 성공 확률로 표시하지 않는다. 공통 view에는 결정론 상태를 함께 제공한다.

```json
{
  "evidence_state": "complete|degraded|blocked",
  "max_claim": "watch|context_only|suppress",
  "reason_codes": ["REGIME_CONFLICT", "FLOW_MISSING"]
}
```

기존 TA confidence, 모델 점수, scanner confidence cap은 native scorecard에 원래 의미와 버전을 붙여 보존한다. 공통 확률로 합성하지 않는다. 향후 숫자형 확률을 노출하려면 별도 holdout에서 reliability curve와 calibration error를 측정하고 버전별 기준을 문서화해야 한다.

### 4.5 Thesis와 Invalidator

현재 `entry_plan.invalidation`은 문자열이다. 이를 버리지 않고 표시 문구로 유지하되, 자유문장 `cond`를 실행하지 않는다. 실행 가능한 무효화만 별도 구조화 필드로 추가한다.

```json
{
  "thesis": {
    "thesis_id": "relative_strength_with_flow.v1",
    "params": {"min_rs": 80, "flow_days": 2},
    "narrative": "표시용 설명"
  },
  "invalidators": [
    {
      "rule_id": "leader_grade_drop_3ticks",
      "rule_version": "1",
      "rule_type": "CONSECUTIVE_GRADE_EXIT",
      "params": {"allowed_grades": ["S", "A"], "ticks": 3},
      "required_inputs": ["leader_grade", "snapshot_quality"],
      "state": "unknown|clear|triggered",
      "evaluated_at": "...",
      "triggered_at": null
    }
  ]
}
```

초기 허용 타입은 현재 데이터로 결정론 평가 가능한 것만 둔다.

- `CONSECUTIVE_GRADE_EXIT`
- `LIVE_GATE_RED`
- `STOP_LEVEL` — 기준 가격이 저장된 경우만
- `EXPIRY`

`FLOW_REVERSAL`, `DART_ADVERSE`, `CREDIT_WARNING`, `BLACKLIST_HIT`, `FX_SHOCK`는 v1 범위에서 제외한다. 현재 Claw collector 행에는 이 필드들이 정규화되어 전달되지 않는다. 별도 cadence·캐시·freshness 계약 없이 Claw의 5초 루프에 추가하지 않는다. `CONSECUTIVE_GRADE_EXIT`은 기존 `LEADER_DROP` 확정 로직을 재사용하며 같은 상태 변화로 별도 중복 알림을 만들지 않는다.

## 5. RegimeContext: 하나의 값이 아니라 하나의 계약

EOD breadth와 장중 market gate는 시간 해상도와 역할이 다르므로 서로 덮어쓰지 않는다.

```json
{
  "schema_version": "marketflow.regime_context.v1",
  "eod": {
    "base_regime": "RISK_ON|NEUTRAL|RISK_OFF|UNKNOWN",
    "phase": "uptrend_broadening|leader_market|rebound_early|downtrend|UNKNOWN",
    "as_of": "2026-08-21",
    "available_at": "2026-08-21T15:50:00+09:00",
    "status": "available|stale|missing",
    "method_version": "breadth_phase.v1"
  },
  "live": {
    "gate": "GREEN|YELLOW|RED|UNKNOWN",
    "as_of": "2026-08-24T09:07:10+09:00",
    "available_at": "2026-08-24T09:07:12+09:00",
    "status": "available|stale|missing"
  },
  "resolution": {
    "positive_promotion": "allow|degrade|block",
    "risk_delivery": "allow",
    "reason_codes": []
  }
}
```

정책:

| 조건 | 신규 양의 후보 | 위험·이탈·HALT 알림 |
|---|---|---|
| live RED 또는 Claw HALT | 차단 | 허용 |
| live 데이터 stale/missing | Claw는 차단 | 상태 이상 알림 허용 |
| EOD `downtrend`/`rebound_early` | S0 재현 전에는 context/shadow만; 새 차단 근거로 사용 금지 | 허용 |
| EOD와 live 충돌 | `degraded/context_only` | 허용 |
| EOD missing | `UNKNOWN`; `leader_market`으로 폴백 금지 | 허용 가능한 원천이 있는 위험 이벤트만 허용 |

`as_of`만으로 조인하지 않는다. 신호 시각 `T`에는 `available_at <= T`인 최신 관측만 사용할 수 있다. 오전·장중 신호에 당일 14:50 이후 갱신된 일봉이나 당일 종가로 계산한 phase를 붙이는 것은 lookahead다. 따라서 장중에는 원칙적으로 전 거래일 확정 EOD context를 사용하고, 같은 날의 live gate는 별도 축으로 둔다. 검출의 현재 날짜 문자열도 완전한 KST timestamp로 교체한다.

Claw에 EOD 4국면 차단을 즉시 강제하지 않는다. 저장 리포트에서 phase gate 효과가 재현되지 않았으므로, phase coverage와 event-time join을 고친 OOS 결과가 나오기 전에는 context/shadow로만 쓴다. 이후에도 양의 이벤트 종류별로 검증해 승격한다. `LEADER_DROP`, 무효화, HALT 같은 위험 신호는 약세 국면이라는 이유로 숨기지 않는다. 기존 paper phase gate 역시 이 재현성 점검의 대상이며 새 정책의 증거로 간주하지 않는다.

## 6. 레인별 최소 근거 정책

모든 이벤트에 “서로 다른 2개 출처”를 강제하지 않는다. KIS 한 원천의 안전한 스냅샷 변화만으로 성립하는 장중 이벤트까지 막히기 때문이다. 대신 검출기별 `required_domains`를 선언한다.

### 일간 스캐너

사용자 노출 `watch`의 최소 조건:

1. 유효하고 신선한 기준 가격·거래대금
2. 스캐너가 선언한 필수 feature가 모두 과거 시점 데이터로 계산됨
3. `market_price` 외 독립 도메인 하나 이상 확인: `investor_flow`, `filing`, 또는 검증된 multi-day setup
4. `interpretive` 근거는 보조만 가능
5. EOD phase가 UNKNOWN이면 확인된 phase처럼 쓰지 않음. phase 기반 차단은 S0 OOS 재현 전까지 shadow

### Claw 장중 레인

양의 전환(`LEADER_NEW`, `LEADER_UPGRADE`, `VOLUME_SURGE`, `HIGH_BREAK`)의 최소 조건:

1. 현재 KIS scan이 safe/complete이고 점수 입력이 완전함
2. 같은 거래일의 비교 가능한 직전 snapshot 존재
3. 개장 안정화 구간·HALT·poller busy 전일 캐시가 아님
4. live gate가 RED/stale/missing이 아님

하락·위험 이벤트는 별도 정책을 사용한다. `LEADER_DROP`, HALT, 원천 장애, 후보 무효화는 양의 후보 차단 규칙과 무관하게 기록하고 필요한 경우 전달한다.

## 7. 후보 생명주기와 무효화

```text
observed ──승격 조건 충족──> watch
   │                         ├─ 무효화 규칙 적중 ─> invalidated
   └─ 만료 ────────────────> expired
                             └─ 만료 ─────────────> expired
```

- `INVALIDATED`를 기존 종목 이벤트의 새 등급처럼 만들지 않는다.
- 상태가 바뀌면 `signal_state_events`에 사유, 평가 입력 시각, 규칙 버전을 감사 로그로 남긴다.
- 동일 입력으로 재평가하면 같은 결과가 나와야 하며 중복 전환을 만들지 않는다.
- `unknown`은 `clear`가 아니다. 필요한 입력이 없으면 무효화 미발생으로 단정하지 않는다.
- 초기에는 모든 무효화를 shadow로 평가하고 Telegram은 보내지 않는다.
- replay와 장중 관찰에서 오탐·중복·지연을 확인한 규칙만 타입별 feature flag로 발송 승격한다.
- 무효화된 후보를 다시 살리려면 기존 인스턴스를 변경하지 않고 새 `signal_instance_id`를 만든다.

## 8. Outcome 계약

`event_id` 하나에 D1/D5 열을 붙이는 방식은 여러 horizon, 계산법 변경, 재계산 이력을 표현하기 어렵다. 다음 키를 사용한다.

```text
UNIQUE(signal_instance_id, horizon, method_version)
```

필수 필드:

- `signal_instance_id`, `horizon` (`D1`, `D5`, 필요 시 확장), `method_version`, `producer_version`
- `entry_price`, `entry_price_source`, `entry_observed_at`
- `exit_price`, `exit_session`, `data_as_of`, `computed_at`
- `raw_return_pct`, `benchmark_return_pct`, `excess_return_pct`
- `benchmark` (`KOSPI` 또는 `KOSDAQ`), 검출 당시 `phase`와 `phase_method_version`, `invalidated_before_horizon`
- `status` (`complete|pending|missing|not_comparable`)와 결측 사유

계산 규칙:

1. 진입 기준가는 검출 시점에 저장한다. 나중에 종가로 덮어쓰지 않는다.
2. D1/D5는 달력일이 아니라 다음 1/5 거래 세션으로 정의한다.
3. 종가와 벤치마크는 동일한 세션·조정 방식으로 계산한다.
4. 거래정지·상장폐지·기업행동 처리 실패는 0%가 아니라 `missing/not_comparable`로 남긴다.
5. `method_version`이 같으면 재실행은 upsert로 멱등이어야 한다.
6. 미래 가격이 아직 없으면 `pending`; 어떤 점수나 정책에도 사용하지 않는다.
7. 실제 주문 성과처럼 표현하지 않는다. 이는 신호의 사후 관측치다.

스캐너 기존 outcome은 유지하고 공통 뷰로 변환한다. Claw만 새 observation 저장을 추가한다.

### 8.1 학습 경계

- 스캐너의 tag/score 변경은 현재 `hypothesis_replay`와 `learning_policy` 경로만 사용한다.
- Claw outcome은 초기에는 **관찰 전용**이다. 현재 replay 체인은 Claw 이벤트 통계를 직접 학습하는 범용 인터페이스가 아니다.
- Claw 버킷 통계를 스캐너 tag나 점수로 자동 매핑하지 않는다. 필요해지면 입력 feature, 가설, OOS 비교, rollback 단위를 별도 설계한다.
- 같은 데이터에서 규칙을 고르고 성과를 보고하지 않는다. 시간순 train/validation을 분리하고, 비용·슬리피지 가정은 리포트에 고정한다.

## 9. 구현 순서와 승격 게이트

| 단계 | 작업 | 운영 영향 | 완료 조건 |
|---|---|---|---|
| S0 | Detection Lab 재현성 복구: KST event-time, `available_at` 조인, phase coverage, 시간순 train/validation, 비용·슬리피지 | 없음 | 데이터/코드 버전·명령·기간·603→거래 변환 사유를 담은 리포트 저장, eligible phase coverage ≥95% |
| S1 | `mirofish.profitability_goal.v2` 호환 확장 + SignalView adapter + UNKNOWN 수정 | 없음 | 기존 score/cap 불변, native artifact와 view 1:1 추적, 계약 테스트 통과 |
| S2 | Claw episode에 이벤트 당시 가격·시각·품질 저장 + outcome observation | 없음 | 거래일·가격 기준 lookahead 테스트, 멱등 재계산 통과 |
| S3 | RegimeContext shadow 집계 | 없음 | 이벤트 시점 이용 가능 데이터만 조인, OOS 국면별 결과와 결측률 공개 |
| S4 | `expiry`, 기존 `LEADER_DROP`, `STOP_LEVEL`만 invalidator shadow 평가 | 알림 없음 | 최소 20 거래일, 중복 전환 0, unknown/clear 진리표, 유형별 표본 공개 |
| S5 | 검증된 양의 후보 규칙만 적용한 뒤 KPI 재생성 주기와 필요한 GET/API·화면 추가 | 제한적 | holdout 개선, 독립 kill switch, stale/insufficient 숨김 없음, 기존 인증·전달 회귀 통과 |

S0가 실패하면 phase 기반 단계는 진행하지 않는다. **실제 알림 정책 변경은 S2~S4의 관측이 끝난 뒤**로 둔다. outcome 집계 시각은 16:30으로 고정하지 않는다. 현재 같은 시각에 예약된 작업이 있으므로 기존 Scheduler 슬롯을 대조해 비충돌 시각을 정하거나 기존 EOD 파이프라인에 합친다.

## 10. 구현 위치

| 파일/영역 | 변경 범위 |
|---|---|
| `app/services/signal_contract.py` | native artifact를 읽기용 SignalView로 투영하는 순수 adapter와 enum; 점수 계산 금지 |
| `app/services/mirofish/alpha_scanner.py` | 기존 `profitability_goal.v1`을 호환 v2로 확장: provenance 시각, typed gap, typed invalidator |
| `app/services/mirofish/paper_orchestrator.py` | 데이터 없음의 낙관적 `leader_market` 폴백 제거, UNKNOWN 반환 |
| `app/services/mirofish/detection_lab.py` | full KST event-time 보존, point-in-time phase 조인, versioned OOS 리포트 생성 |
| `marketflow_claw/gateway.py` | episode 관측과 최소 invalidator shadow 호출; 기존 이벤트·전달 흐름 유지 |
| `marketflow_claw/memory.py` | signal episode/state/outcome 증분 테이블과 멱등 API |
| `marketflow_claw/overview.py` | shadow 품질·결측·outcome 요약 추가 |
| `scheduler.py` | 기존 16:30 Wave/Alpha Brain 작업과 겹치지 않는 EOD 집계 슬롯 또는 기존 일일 작업 내부 호출 |
| `app/routes/kr_claw.py` | 필요할 때 기존 `@pro_required` GET 표면만 증분 |
| `app/routes/admin_mirofish.py` | 필요할 때 기존 `@admin_or_aibain_required` 품질 GET만 증분 |

새 POST 학습 엔드포인트, 새 서버, 새 포트는 만들지 않는다.

## 11. 필수 테스트

### 계약

- 같은 입력은 같은 `signal_instance_id`와 quality 판정을 생성
- `as_of`와 `observed_at` 누락/역전 차단
- `unverified` 또는 LLM 근거만으로 watch 승격 불가
- 데이터 공백이 0점·중립값으로 변환되지 않음
- 기존 리더 등급과 evidence tier가 혼동되지 않음
- 기존 scanner score·confidence cap·profitability verdict가 adapter에서 재계산되거나 달라지지 않음

### 레짐

- 타임라인 없음/빈 파일/오래된 파일은 `UNKNOWN`
- live RED는 양의 Claw 승격만 막고 DROP/HALT를 막지 않음
- EOD/live 충돌은 `degraded`, 낙관적 폴백 없음
- `available_at <= signal.produced_at`인 phase만 조인
- 장중 신호에 그 뒤 갱신된 당일 일봉이 붙지 않음
- 재현 리포트의 detection/trade/제외 수 합계와 phase coverage가 고정됨

### 무효화

- 연속 N틱 규칙 경계값과 partial snapshot 처리
- 입력 missing이면 `unknown`, `triggered`나 `clear`로 오판하지 않음
- 동일 tick 재처리 시 중복 상태 이벤트·중복 알림 없음
- expiry와 invalidation 경쟁 시 먼저 발생한 전환만 유효

### Outcome

- 주말·공휴일을 제외한 D1/D5 거래 세션
- 미래 세션 미도래는 pending
- 기업행동/거래정지 결측 명시
- benchmark 날짜 정렬과 method-version 멱등성
- 신호 이후 데이터만 사용하는 lookahead 회귀 테스트

### 운영 회귀

- 기존 Claw 이벤트 생성·pending/reported·digest dedupe 불변
- 기존 스캐너 TOP3, evidence ledger, learning gate 불변
- shadow 단계에서 Telegram 건수 0 증가
- kill switch가 정책 승격과 invalidation 전달을 각각 끌 수 있음

## 12. 품질 지표

운영 안전성과 모델 유효성을 분리한다.

| 구분 | 지표 |
|---|---|
| 운영 안전 | 검출기별 필수 입력 manifest 대비 관측/결측/차단 비율, point-in-time join 완비율, stale 승격 0건, 중복 상태전환 0건 |
| 검출 품질 | horizon별 precision, 평균/중앙 초과수익, rank IC, 국면·이벤트 종류별 표본 수 |
| 무효화 품질 | 적중률, 오탐률, 적중 전/후 최대불리폭, 조기 제외 효과 |
| 보정 품질 | 향후 숫자형 확률 도입 시 calibration error와 reliability curve |

분모는 승격된 watch만이 아니라 **게이트 전 전체 후보 모집단**으로 고정한다. 통과 후보만 놓고 “근거 완비율 100%”를 보고하거나, 출력된 gap만으로 숨겨진 결측을 측정하지 않는다. 필수 입력 manifest와 수집 상태를 대조해야 한다.

`top3_metrics`는 `generated_at`, `qualified_runs`, `insufficient`, 원천 run의 최신성을 함께 노출한다. 현재 저장 artifact처럼 `insufficient=true`이거나 오래된 값은 KPI 숫자 대신 `unavailable/stale`로 표시한다. API를 추가하기 전에 비충돌 재생성 주기와 실패 상태부터 정의한다.

실계좌 손익을 제품 약속으로 쓰지 않지만, forward return과 precision을 버리지는 않는다. 이 값은 규칙의 유효성을 검증하는 수단이며 매매 성과 보장이 아니다.

## 13. 완료 정의

재설계 구현 완료는 다음을 모두 만족할 때다.

1. 저장된 Detection Lab 리포트가 phase coverage와 OOS 성과를 재현하며, 원안 수치의 채택 또는 폐기 근거가 남는다.
2. 기존 두 레인의 점수와 전달 동작을 깨지 않고 native 계약이 확장되고 SignalView가 계산된다.
3. 데이터 없음이 `leader_market`, 0점, 정상 상태로 위장되지 않는다.
4. 모든 사용자 노출 후보는 어떤 근거와 정책으로 승격됐는지 역추적 가능하다.
5. 모든 무효화 판단은 규칙 버전·입력 시각·상태 전환 로그로 재현된다.
6. Claw outcome이 거래일 기준으로 멱등 계산되고 미래 데이터 누수가 없다.
7. 정책 변경은 OOS 검증과 kill switch를 통과한다. Claw 관측치가 기존 scanner 학습 체인에 암묵적으로 유입되지 않는다.
8. 새 프로세스·포트·주문 경로가 추가되지 않는다.

## 14. 확정 결정

- 도입 순서는 `재현성 복구 → 기존 계약 확장 → Claw 원장/outcome → regime shadow → 최소 invalidation shadow → 정책/API`로 고정한다.
- 4국면 단독 정본 대신 versioned `RegimeContext`를 정본으로 한다.
- phase 기반 신규 차단은 OOS 효과가 재현된 뒤 양의 후보에만 적용하며 DROP/HALT/무효화 같은 위험 신호를 숨기지 않는다.
- 기존 scanner confidence cap은 내부 규칙값으로 유지하고, 새 공통 숫자 cap이나 확률로 재해석하지 않는다.
- `FX_SHOCK`와 신규 외부 수집은 별도 필요성이 입증될 때까지 제외한다.
- API 인증은 새 체계를 만들지 않고 각 기존 Blueprint의 인증 수준을 그대로 따른다.

## 15. 주요 검토 근거

- 기존 scanner 계약: `app/services/mirofish/alpha_scanner.py`
- 저장 Detection Lab 결과: `data/admin_mirofish/detection_lab/report_20260817_100036.json`
- detection event-time/phase 파생: `app/services/mirofish/detection_lab.py`
- 3상태 breadth 정본: `app/services/mirofish/intelligence/regime.py`
- 4국면 파생과 낙관 폴백: `app/services/mirofish/paper_orchestrator.py`
- paper phase gate: `app/services/mirofish/paper_positions.py`
- Claw 원장·이벤트·수집 입력: `marketflow_claw/memory.py`, `marketflow_claw/events.py`, `marketflow_claw/collectors.py`
- Claw 장중 흐름: `marketflow_claw/gateway.py`
- KPI artifact/계산: `data/admin_mirofish/intelligence/top3_metrics.json`, `app/services/mirofish/intelligence/top3_metrics.py`
- 예약 충돌: `scheduler.py`
