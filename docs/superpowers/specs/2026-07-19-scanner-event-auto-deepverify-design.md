# 스캐너 이벤트 자동 딥검증 + 13D 동시 캡처 + 히스토리화 설계

- 날짜: 2026-07-19
- 상태: 사용자 승인(설계 A + 13D 스냅샷 캡처 + 히스토리) → 스펙 리뷰 → writing-plans
- 관련: [[project_brain13d_tradingagents_link]], `2026-07-19-brain13d-tradingagents-live-link-design.md`

## 1. 목표

알파 스캐너가 **신규 이벤트 종목을 검출할 때 자동으로** TradingAgents 딥검증을 수행해
위젯 카드에 표시한다. 검출 시점의 **Brain 13D 스냅샷을 신선 캡처해 딥검증에 주입(동시 진행)** 하고,
결과를 **시간순 히스토리로 누적 저장**한다. (버튼 아님 — 검출 시점 서버 자동.)

- 비용 제어: 신규 **매수후보 상위 K개**(K 기본 3, env)만, **백그라운드 비동기**(30s 폴링 무지연),
  event_key 단위 dedupe(이벤트당 1회), 킬스위치.
- 별도 스토어에 기록 → 큰 alert_state 파일과 쓰기 레이스 0.

## 2. 트리거 지점 (검증됨)

`alpha_scanner.py`의 스캐너 모니터 사이클: 신규 이벤트(`events` delta, 각 `{candidate:{symbol,display_name,
market,action,alpha_score,rank}, event_key}`)를 `commit_scanner_alert_events(result)` 로 커밋(신규 전송 경로).
→ 커밋 직후 `scanner_deepverify.enqueue_new_events(events, run)` 를 **비동기 호출**(fire-and-forget 스레드).
기존 커밋/텔레그램/모니터 상태 로직은 무변경.

## 3. 컴포넌트

### 3.1 `scanner_deepverify.py` (신규)
- `enqueue_new_events(events, run)`: 킬스위치 검사 → 신규 이벤트 중 **매수후보**(action ∈ {BUY_CANDIDATE, BUY})
  필터 → alpha_score 내림차순 상위 K → 이미 히스토리에 있는 event_key 제외(dedupe) → 백그라운드 스레드에서 처리.
  스캐너 스레드를 절대 블로킹하지 않음(스레드 spawn 후 즉시 반환).
- 종목별 처리 `_verify_one(event, run)`:
  1. `brain = store._brain_summary(name)` — **검출 시점 Brain 13D 신선 캡처**.
  2. `ta = engine.run_deep_analysis(name, symbol=symbol, brain=brain)` — 13D 주입 딥검증.
  3. 히스토리 레코드 append(원자적).
- 개별 종목 실패 격리(try/except, 로그만). 전체 스토어는 무손상.

### 3.2 히스토리 스토어
- 파일: `data/admin_mirofish/scanner_tradingagents_history.json`
  ```
  { 'version': 1, 'records': [ <record>, ... ] }   # append-only, 최근 N=500 캡(오래된 것 drop)
  ```
- record 스키마(LOCKED):
  ```
  { event_key, symbol, display_name, market, detected_at, verified_at,
    verdict, confidence, strong_buy, regime, alignment, regime_adjustment,
    method, ta_run_id, brain_snapshot_at, alpha_score, risk_score }
  ```
- `append_record(record)`: 읽기→append→최근 N 캡→`write_json_atomic`(재시도 경로).
- `latest_by_event_key()`: records 를 event_key 별 최신으로 축약(카드 머지용).
- `history(limit)`: 최근순 records (히스토리 조회용).
- TA 전문 트레이스는 기존 `tradingagents_runs/<run_id>.json` 에 이미 영속(ta_run_id 로 링크).

### 3.3 피드 머지 (`alpha_scanner.py`)
- `read_scanner_alert_state` 가 만드는 `feed_events` 각 이벤트에, `latest_by_event_key()[event_key]` 의
  TA 요약을 `event['tradingagents'] = {verdict, confidence, strong_buy, regime, regime_adjustment, method,
  ta_run_id, verified_at}` 로 머지. 매칭 없으면 필드 없음(카드는 기존대로).
- 머지는 요약 조립부에서 read-only(스토어 미존재 시 무시).

### 3.4 히스토리 엔드포인트 (`admin_mirofish_tradingagents.py`)
`GET /api/admin/mirofish/scanner/tradingagents/history?limit=50` (`@admin_or_aibain_required`)
→ `{records: [...], count}` 최근순. limit 1~200.

### 3.5 프론트 (`mirofishApi.ts`, `ScannerEventsCard.tsx`)
- 타입 `MiroFishScannerAlertEvent` 에 `tradingagents?: {verdict, confidence, strong_buy, regime,
  regime_adjustment?, method?, verified_at?}` 추가.
- `ScannerEventRow` 에 TA 블록 렌더(자동, deepseek_brief 블록과 유사 스타일):
  verdict 배지(STRONG_BUY/BUY/HOLD/SELL) + 확신% + 🔥매수유력(strong_buy) + `레짐 <regime> · 보정 ±N`.
  `event.tradingagents` 없으면 미표시(아직 검증 전/비대상).

## 4. env

| 변수 | 기본 | 의미 |
|------|------|------|
| `MIROFISH_TA_SCAN_DISABLED` | false | 자동 딥검증 킬스위치 |
| `MIROFISH_TA_SCAN_MAX` | 3 | 신규 이벤트당 검증 상한(알파순) |
| (재사용) `MIROFISH_TA_REGIME_*` | — | 레짐 보정(기존) |

## 5. 안전장치

- 백그라운드 스레드 → 스캐너 30s 폴링/텔레그램 무지연.
- 킬스위치 시 enqueue 즉시 반환(기존 동작 그대로).
- 개별 종목 실패 격리, 별도 스토어라 alert_state 무변경(레이스 0), 원자적 write.
- dedupe(event_key) → 같은 이벤트 재검증 안 함, LLM 비용 상한.
- Brain 13D 캡처 실패 시 brain=None 로 딥검증 진행(무보정, 정상).

## 6. 테스트

1. `enqueue_new_events`: 매수후보 상위K 선정 / 비매수 제외 / dedupe(기존 event_key 스킵) / 킬스위치 시 no-op.
2. `_verify_one`: brain 캡처+run_deep_analysis 호출(모킹) → 히스토리 record 필드 확인 / 개별 실패 격리.
3. 스토어: append→최근N 캡 / latest_by_event_key 최신 선택 / history 최근순.
4. 피드 머지: latest 존재 시 event.tradingagents 부착 / 없으면 무필드.
5. 엔드포인트: 200 + records / limit 경계 / 스토어 미존재 시 빈 records.
6. 기존 스캐너/워크플로우 회귀 0.
7. FE: tsc/build 그린, tradingagents 있을 때만 블록 렌더.

## 7. 범위 제외 (YAGNI)

- 별도 히스토리 전용 UI 페이지(엔드포인트까지만; 카드는 최신만 표시).
- 같은 이벤트 주기적 재검증(1회 dedupe).
- 성과검증/적중률 집계(히스토리 스토어를 원천으로 후속 가능하게만 설계).
- 프론트에서 트리거(서버 자동 한정).
