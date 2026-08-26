# MarketFlow 관측·검증 하네스 v3.1

작성일: 2026-08-24 (KST)  
상태: 구현 기준  
적용 범위: Detection Lab, MiroFish 분석 코어, MarketFlow Claw 관측 원장

## 1. 목적과 비범위

이 하네스는 검출 당시 입력과 이후 결과를 재현 가능한 형태로 기록하고, shadow
규칙의 유효성을 검증한다. 관측 자료가 쌓였다는 이유만으로 기존 검출·Telegram
전달·HALT 판단을 변경하지 않는다.

- 주문·매수·매도·출금 경로를 만들지 않는다.
- GET 요청에서 KIS 스캔, 파일 갱신, outcome 계산을 시작하지 않는다.
- 기존 `LEADER_DROP` 전달을 새 `INVALIDATED` 전달로 복제하지 않는다.
- 숫자형 confidence를 성공 확률로 해석하거나 LLM이 상향하지 않는다.

## 2. 운영 불변조건

1. 5003 Flask는 요청 전용이며 KIS 스캔 생산자가 아니다.
2. Claw는 동일 producer timestamp·동일 payload를 중복 스냅샷/이벤트로 저장하지 않는다.
3. 관측 원장 쓰기 실패는 기존 스냅샷, 이벤트 검출, heartbeat, 전달을 중단시키지 않는다.
4. 이벤트 전달 성공 전에는 `reported_at`을 기록하지 않으며 기존 delivery idempotency를 유지한다.
5. HALT 중에도 관측 사실과 차단 사유는 저장하되 양의 후보 승격·전달은 기존 규칙을 따른다.
6. 모든 시각은 timezone을 포함한 ISO-8601로 저장하고 거래세션 해석은 Asia/Seoul 기준이다.
7. 스키마 변경은 additive migration만 허용하며, 기존 DB 백업·WAL·foreign key 검증 후 배포한다.

## 3. R0 재현성 게이트

### R0a — 데이터 무결성

- `(ticker, date)`는 하나의 유효 EOD 관측이어야 한다.
- 중복은 파일 순서상 마지막 valid OHLCV 행을 선택하는 결정론 규칙으로 정규화하고,
  원본 행 수·고유 키 수·중복 키/행 수·충돌 가격 수를 manifest에 남긴다.
- OHLC 양수성·`low <= min(open, close) <= max(open, close) <= high`를 검사한다.
- 가격과 phase의 point-in-time join coverage가 95% 미만이면 정책 검증은 실패다.

### R0b — 계산 재현성

각 report는 다음 manifest를 포함한다.

- git revision, method/ruleset version, 실행 명령
- 입력 파일 경로·SHA-256·크기·mtime·최대 데이터일
- 검출 수, 가격 coverage, phase coverage, 중복 통계
- LIVE와 동일한 blocked phase 집합
- 전체 및 phase별 n, 승률, 기대수익, profit factor

같은 bundle을 두 번 실행했을 때 ID·건수·라벨은 완전 일치해야 한다. 원 입력 bundle이
없으면 과거 `+2.60% / PF 2.06`은 재현 성공이 아니라 `historical_claim_unverified`로 남긴다.

### R0c — 정책 유효성

- 규칙 선택 구간과 평가 구간을 시간순으로 분리한다.
- 동일 신호의 gate on/off를 paired 비교한다.
- 비용·슬리피지 가정, 결측률, unique sessions, 95% 신뢰구간을 공개한다.
- 초기 활성 후보 조건은 고유 20세션, 규칙별 완료 30건, outcome coverage 95% 이상이다.
- 평균이 양수이거나 하루 육안 검증만 통과한 규칙은 활성화하지 않는다.

## 4. Signal Instance 계약

Signal Instance는 일자·종목이 아니라 개별 발생을 식별한다.

- 필수 식별: `signal_instance_id`, `opened_event_id` 또는 baseline origin,
  `opened_type`, `opened_ts`, `snapshot_id`
- 기준 가격: `ref_price`, `ref_price_as_of`, `ref_price_source`, `price_status`
- 재현 메타데이터: `producer_version`, `rule_version`, `input_digest`
- 컨텍스트: immutable `regime_context_id`
- 상태 변화는 별도 append-only state-event로 기록한다.

같은 날 같은 종목의 재승격·재진입을 합치지 않는다. 단, 동시에 열린 episode 하나만
허용하는 정책이 필요하면 명시적인 open-state 제약으로 구현한다.

## 5. RegimeContext 계약

`structural_phase_d1`과 `intraday_risk_gate`는 서로 대체하지 않는 독립 축이다.

- EOD context는 `available_at <= signal_ts`인 가장 최신 전 거래일 자료만 사용한다.
- live gate/HALT는 실제 Claw gate 관측과 source watermark를 저장한다.
- `captured_at`, `available_at`, `content_hash`, `method_version`, source freshness를 저장한다.
- 둘 중 하나가 stale/unknown이어도 다른 하나로 같은 의미의 라벨을 만들어내지 않는다.

## 6. 근거·공백 규칙

공통 2-provider 하드게이트를 사용하지 않는다. 각 검출기는 필요한 evidence domain을 선언한다.

- Claw: 안전하고 완전하며 신선한 KIS snapshot transition이 핵심 필수 domain이다.
- Scanner: 가격 외에 해당 가설에 필요한 수급·공시·다일 setup domain을 별도로 선언한다.
- 동일 공급자에서 나온 여러 artifact는 독립 provider로 세지 않는다.
- 공백은 `{field, status, source, as_of, reason}`로 기록한다.
- `not_applicable`, `confirmed_absent`, `stale`, `fetch_failed`, `missing`을 구분한다.
- 기존 scanner native `confidence_cap`은 보존하고 새 공통 감산식을 이중 적용하지 않는다.

## 7. Outcome·shadow 계약

Outcome은 `(signal_instance_id, horizon_sessions, method_version)` 세로형이다.

- S0: 이벤트가 발생한 KST 거래세션
- Sh: S0 이후 h번째 거래세션
- P0: `as_of <= event_ts`인 발생 당시 가격
- Ph: Sh의 검증된 EOD 종가
- `raw_return_pct = 100 * (Ph / P0 - 1)`
- 상태: `pending`, `complete`, `missing`, `not_comparable`

17:15 updater는 당일 결과를 확정하지 않고 성숙한 horizon만 멱등 갱신한다. 거래정지,
상장폐지, 기업행동 또는 가격 부재를 0%로 대체하지 않는다.

Shadow invalidator는 append-only 관측이다. 첫 trigger가 horizon보다 빠른 경우에만
`shadow_exit_delta_pp`를 계산하고 beneficial/harmful rate, trigger rate, coverage, 95% CI를
함께 평가한다. 정책 활성화는 invalidator별 feature flag와 독립 rollback 단위를 사용한다.

## 8. API·UI 계약

- scorecard/quality API는 저장 결과만 조회한다.
- 모든 KPI는 `metric_version`, 기간, numerator/denominator, eligible/complete/pending/missing,
  unique sessions, coverage, data watermark, generated_at, stale, insufficient reason을 반환한다.
- shadow 초기 UI는 관리자/AiBain에만 공개하고 검증 후 Pro로 승격한다.
- insufficient 또는 stale이면 수치보다 상태를 우선 표시한다.

## 9. 배포 합격 조건

1. focused Python tests와 전체 Claw 회귀가 통과한다.
2. frontend Vitest·TypeScript build가 통과한다.
3. DB migration을 임시 복사본에서 먼저 검증하고 기존 row 수가 변하지 않는다.
4. 5003 `/healthz`, `/api/health`, 공개 tunnel health가 정상이다.
5. Claw PID가 하나이며 명령줄에 `--send`가 있고 heartbeat가 연속된다.
6. GET API 호출 전후 KIS producer timestamp와 snapshot 수가 변하지 않는다.
7. production 모바일 화면에서 가로 overflow가 없고 하나의 자연스러운 세로 scroller만 존재한다.

