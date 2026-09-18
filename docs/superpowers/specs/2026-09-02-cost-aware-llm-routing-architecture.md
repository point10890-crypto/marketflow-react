# MarketFlow 비용 최적화 LLM 라우팅 아키텍처

작성일: 2026-09-02 (KST)

상태: 사용자 승인 완료(1단계 전체 범위, 2단계 비용 최적화 파이프라인, 3단계 장애·비용·결과 계약)

적용 범위: MiroFish, TradingAgents, Multi-MCP, 자동 workflow, 종가/Jongga, 차트 이미지, 암호화폐 분석, 관리자 채팅

## 1. 목표

OpenAI에 집중된 토큰과 비용을 줄이되, 분석 실패를 숨기거나 투자 판단 품질을 낮추지 않는다.

확정된 운영 원칙은 다음과 같다.

1. 일반 텍스트 분석은 DeepSeek 저비용 모델을 우선 사용한다.
2. 최종·결정 분석은 사용 가능한 최고 등급 DeepSeek 모델을 사용한다.
3. DeepSeek 호출이 실패하면 OpenAI를 순차 백업으로 사용한다.
4. 이미지·차트 분석은 Gemini Vision을 기본으로 사용한다.
5. 결정 분석의 모든 백업까지 실패하면 임의의 정상 판정을 만들지 않고 `HOLD_REVIEW`를 반환한다. 일반 분석 실패는 `DEGRADED`, 이미지 분석 실패는 명시적 unavailable/technical 상태로 구분한다.
6. 숫자, 종목, 시장, 가격, 점수와 위험 게이트의 소유자는 결정론적 코드와 원천 데이터다. LLM은 이를 생성하거나 변경하지 않는다.
7. 동일 근거를 여러 에이전트가 반복 전송하지 않도록 하나의 EvidencePacket을 재사용한다.

## 2. 현재 기준선과 문제

### 2.1 호출 집중

- 현재 TradingAgents 기본 경로는 종목당 14개의 논리 LLM 호출과 최대 16,384개의 출력 토큰 상한을 가진다. 산식은 analysts 8,192 + 기본 2-round debate/manager 5,120 + trader/3-risk/PM 3,072이다.
- 자동 workflow는 후보별 legacy GraphRAG/토론/CIO를 수행한 뒤 상위 후보를 TradingAgents로 다시 분석한다. 후보 20개와 TA 5개 기준 이론상 약 130개의 논리 호출이 발생할 수 있다.
- Multi-MCP는 후보 20개에 전체 TradingAgents를 적용하면 기본 약 280개의 논리 호출을 만들 수 있다.
- 차트 분석은 Gemini 장애 시 종목별 OpenAI Vision을 호출하며, 파라미터 협상 재시도까지 포함하면 100개 차트에서 약 100~200회의 OpenAI 시도가 발생할 수 있다.
- 기존 provider metadata에는 공급자, 성공 여부와 시도 순서는 있으나 대부분 실제 입력·출력 토큰과 비용이 없다.

### 2.2 현재 공급자 상태

2026-09-02 로컬 자격 증명 상태를 비밀값을 출력하지 않고 재점검한 결과:

- `.env`의 DeepSeek 키는 플랫폼의 기존 프로젝트 키 항목과 일치한다.
- `GET /models`가 HTTP 200으로 성공했으며 `deepseek-v4-flash`, `deepseek-v4-pro`, `deepseek-v4-flash-vision-exp` 접근이 확인됐다.
- Flash와 Pro에 각각 최소 생성 요청을 실행해 모두 HTTP 200을 확인했다. 각 검증은 총 9토큰만 사용했다.
- 플랫폼 Usage 화면의 topped-up balance는 점검 시점에 `$49.84`였다.
- 앞서 관측된 HTTP 401은 재현되지 않았으므로 현재 credential 장애로 취급하지 않는다. 운영 전 health check는 계속 필수다.
- OpenAI 키도 인증되며, 확인된 사용 가능 모델은 `gpt-5.5`이다.

이 상태는 시점에 따라 바뀌므로 코드 상수로 취급하지 않는다. 라우터의 health check 결과와 운영 metadata로 관리한다.

## 3. 중앙 라우팅 구조

전체 앱에서 사용할 중립 패키지 `app/services/ai_routing/`을 둔다. 기존 `app/services/mirofish/llm_client.py`는 공개 함수 호환성을 유지하는 어댑터가 된다.

```text
caller
  -> operation policy
  -> cache/dedup
  -> budget reservation
  -> circuit breaker
  -> primary provider
  -> retry classification
  -> sequential fallback
  -> schema/numeric validation
  -> usage ledger
  -> RoutingResult
```

중앙 요청은 최소한 다음 필드를 가진다.

```python
RoutingRequest(
    operation="decisive_text",
    prompt=...,
    system=...,
    run_id=...,
    request_id=...,
    symbol="005930",
    market="KOSPI",
    json_mode=True,
    max_output_tokens=1200,
    evidence_fingerprint="...",
)
```

중앙 결과는 텍스트와 함께 실제 공급자, 모델, fallback, token usage, 비용, validation과 상태를 반환한다. 기존 호출자를 깨지 않도록 legacy wrapper는 텍스트만 반환할 수 있지만 전체 metadata는 항상 원장에 기록한다.

## 4. 작업별 모델 정책

| 작업 | 기본 공급자 | 순차 백업 | 후보/호출 제한 | 기본 출력 상한 |
|---|---|---|---:|---:|
| `bulk_text` 증거 요약 | DeepSeek Flash 계열 | OpenAI | 결정론적 상위 20개 이내 | 768 |
| `compact_debate` 찬반 요약 | DeepSeek Flash 계열 | OpenAI | 상위 5개 이내 | 768 |
| `decisive_text` 최종 결정 | 최고 등급 DeepSeek Pro 계열 | OpenAI 1회 | 상위 3~5개 | 1,200 |
| `vision` 차트 분석 | Gemini Vision | OpenAI Vision; 검증된 DeepSeek Vision은 선택적 중간 단계 | 일반 20개, OpenAI는 상위 5개 | 768 |
| `interactive_text` 관리자 채팅 | DeepSeek Flash/Pro 정책 선택 | OpenAI | 기본 2회, 절대 3회 | 1,200 |
| `specialized_gemini` grounding/code | Gemini 전용 기능 | 원천 어댑터 + DeepSeek 텍스트, 필요 시 OpenAI | 기능별 | 기능별 |

모델 ID는 환경변수로 주입하되 작업 등급을 우회할 수 없다.

- `AI_DEEPSEEK_FAST_MODEL`
- `AI_DEEPSEEK_DECISIVE_MODEL`
- `AI_OPENAI_FALLBACK_MODEL`
- `AI_GEMINI_VISION_MODEL`
- `AI_DEEPSEEK_VISION_MODEL` — startup capability check가 통과한 경우에만 활성

`MIROFISH_LLM_PROVIDER_ORDER` 같은 기존 전역 설정이 `decisive_text`의 DeepSeek → OpenAI 순서를 뒤집어서는 안 된다. 모든 실제 model ID는 startup/operator health check에서 접근 가능성이 확인되어야 하며, 확인되지 않은 legacy `gpt-4o`/`gpt-4o-mini` 하드코딩이 새 라우터를 우회해서도 안 된다.

## 5. 비용 최적화 분석 파이프라인

```text
KIS/DART/가격/거래량/수급/리스크
  -> 결정론적 필터와 risk gate
  -> 상위 20개
  -> canonical EvidencePacket 생성/캐시
  -> 후보별 DeepSeek Flash 증거 digest
  -> Gemini 차트 분석
  -> 상위 5개
  -> 후보별 한 호출의 구조화된 bull_case + bear_case
  -> 상위 3~5개에 후보별 DeepSeek Pro 결정
  -> 실패 시 OpenAI 한 번
  -> 숫자·근거·허용 verdict 검증
  -> BUY/WATCH/HOLD 또는 HOLD_REVIEW
```

### 5.1 EvidencePacket

EvidencePacket은 다음을 포함하는 유일한 LLM 입력 기준이다.

- symbol, display_name, market, as_of
- 가격, 거래량, 수급, 재무, 공시와 기술 지표
- deterministic alpha/risk score와 허용 verdict 집합
- source, fetched_at, freshness, confidence
- 차트 분석의 구조화된 결과
- 위험 플래그와 무효화 조건
- 짧은 `evidence_id`

각 packet은 한 symbol에만 속하며 다른 후보의 근거를 섞지 않는다. `as_of`는 packet 생성 시간이 아니라 **시장·원천 데이터 cutoff timestamp**를 뜻한다. 캐시 키는 최소한 `symbol + data_cutoff + source_fingerprint + operation + model + prompt_version + schema_version`으로 구성한다. source별 fetched_at/freshness도 packet 안에 고정하고, 이후에 수집된 데이터로 과거 packet을 덮어쓰지 않는다. `force` 또는 source freshness 변화가 있을 때만 새 버전을 생성한다.

### 5.2 Compact와 Full

- `compact`는 기본 목표 경로다. **후보 종목당** 증거 digest 1회, bull/bear 1회, decisive 1회로 3회의 텍스트 호출을 목표로 한다. 호출 결과는 같은 symbol의 evidence ID만 인용해야 한다.
- `full`은 현재 4 analysts, 다중 debate, trader/risk/PM 구조를 유지한다.
- 전환 전에는 저장된 동일 EvidencePacket에 대해 두 경로를 shadow 비교한다.
- deterministic role score와 risk gate는 compact에서도 유지한다.
- bull/bear는 서로 분리된 JSON 필드와 evidence ID를 가져야 하며 원천 숫자를 바꿀 수 없다.

### 5.3 중복 제거

- 자동 workflow에서는 legacy GraphRAG/토론/CIO와 TradingAgents를 같은 후보에 연속 수행하지 않는다.
- compact TradingAgents 결과로 기존 `analysis_runs`, graph, report 호환 필드를 생성한다. adapter는 legacy layer/status/link 필드와 새 `source_run_id`, `analysis_status`, evidence reference의 명시적 매핑표를 가지며, 만들 수 없는 legacy 의미를 빈 정상값으로 위장하지 않는다.
- 독립적인 legacy `POST /runs`는 기존 의미를 유지한다.
- scanner rerank와 chart 결과를 EvidencePacket에 첨부해 후속 프롬프트에서 재생성하지 않는다.
- 동일 종목의 직접 TA, decision API와 Multi-MCP는 data cutoff와 source fingerprint가 같은 경우 실행 artifact를 재사용한다.
- shadow 기간에는 legacy artifact 개수, 상태, 링크와 기존 consumer의 조회 결과가 회귀하지 않는지 검증한다.

## 6. 실패와 회로 차단

| 오류 분류 | 재시도 | breaker | 후속 처리 |
|---|---:|---|---|
| `authentication` 401/403 | 0 | 즉시 open | 다음 공급자 |
| `insufficient_balance` 402 | 0 | 즉시 open | 다음 공급자 |
| `rate_limit` 429 | jitter 후 1회 | 반복 시 open | 다음 공급자 |
| `timeout`/`connection`/5xx | 1회 | 임계치 도달 시 open | 다음 공급자 |
| `model_unavailable` | 0 | 모델 단위 open | 다음 공급자 |
| `invalid_json` | 로컬 복구 1회 | 열지 않음 | 다음 공급자 |
| `numeric_mismatch` | 0 | 열지 않음 | 결과 폐기 후 다음 공급자 |
| `empty`/`refusal` | 0 | 열지 않음 | 다음 공급자 |

breaker 키는 `provider + modality(text/vision) + model tier`이다. 인증·잔액 오류는 해당 실행과 기본 cooldown 동안 열고, transient 오류는 제한 시간 내 연속 실패 임계치에 도달할 때만 연다. cooldown 후 단 한 개의 half-open probe를 허용한다.

실행 순서는 `candidate admission → 전체 chain budget reservation → primary → retry classification → 승인된 1회 fallback → 상태 확정`이다. 모든 예약된 논리 호출은 주 공급자 실패 시 승인된 백업을 시도한다. 예산 예약에 실패하면 primary도 호출하지 않는다. budget gate를 통과하지 못한 저우선 후보는 애초에 LLM 호출로 예약하지 않고 결정론적 결과로 남긴다. 이 구분으로 “호출 실패 시 백업”과 “장애 시 무제한 OpenAI 팬아웃 금지”를 동시에 만족한다.

## 7. 예산 계약

초기 hard cap:

- 자동 실행 OpenAI fallback: 실행당 최대 5회
- OpenAI 입력 토큰 예약: 실행당 최대 30,000
- OpenAI 출력 토큰 예약: 실행당 최대 6,000
- 하나의 논리 요청에서 OpenAI는 최대 1회
- 전체 fallback chain은 텍스트 2회, vision은 검증된 공급자 수 이내
- 일일 비용은 `AI_OPENAI_DAILY_BUDGET_USD`가 설정된 경우 추가 hard cap으로 적용
- 사용률 80%: 신규 저우선 호출을 rule/cache-only로 전환
- 사용률 100%: 추가 OpenAI 호출 차단

예산은 future/task 제출 전에 원자적으로 예약하고, 완료 후 실제 usage로 정산한다. 동시 호출이 남은 예산을 중복 사용하는 것을 허용하지 않는다.

결정 호출의 우선순위가 가장 높다. vision이나 일반 enrichment가 결정 fallback용 예약분을 선점하지 못하도록 operation별 pool을 둔다.

## 8. 결과 상태 계약

```json
{
  "analysis_status": "SUCCESS_FALLBACK",
  "decision": "WATCH",
  "rule_candidate_verdict": "BUY",
  "primary_provider": "deepseek",
  "actual_provider": "openai",
  "model": "gpt-5.5",
  "fallback_used": true,
  "fallback_reason": "authentication",
  "evidence_validated": true,
  "numeric_validation": "passed",
  "usage": {
    "input_tokens": 4210,
    "cached_input_tokens": 0,
    "output_tokens": 730,
    "reasoning_tokens": 0,
    "usage_estimated": false
  }
}
```

- `SUCCESS_PRIMARY`: 주 공급자의 검증된 결과
- `SUCCESS_FALLBACK`: 백업 공급자의 검증된 결과
- `DEGRADED`: 캐시 또는 규칙만으로 제공한 비결정 결과
- `HOLD_REVIEW`: 결정 공급자와 백업 모두 실패하거나 결과 검증에 실패
- `FAILED_TECHNICAL`: 분석 이전 시스템 자체 실패

`HOLD`는 정상 결정 분석 결과이고 `HOLD_REVIEW`는 결정 분석 미완료 상태다. ordinary/bulk/interactive 실패는 `DEGRADED` 또는 기존 명시적 오류로, vision 실패는 `image_analysis_status=unavailable` 또는 `FAILED_TECHNICAL`로 처리한다. 자동 후보 확정, 알림과 후속 매매 로직은 `HOLD_REVIEW`를 BUY/STRONG_BUY로 승격할 수 없다. 규칙 후보를 보존해야 하면 `rule_candidate_verdict`에만 기록한다.

## 9. Token Usage 원장

원장은 prompt/response 본문과 비밀값 없이 attempt 단위로 저장한다.

필수 필드:

- `event_ts_utc`, `request_id`, `run_id`
- `provider`, `model`, `endpoint`, `operation`, `attempt_number`
- `selected`, `status`, `latency_ms`, `max_output_tokens`
- `input_tokens`, `cached_input_tokens`, `uncached_input_tokens`
- `output_tokens`, `reasoning_tokens`, `total_tokens`
- `estimated_cost_usd`, `pricing_version`, `usage_estimated`
- `error_class`, `fallback_from`, `breaker_state`, `cache_hit`
- `symbol`, `market`, `caller_endpoint`

불변식:

- `uncached_input_tokens = max(0, input_tokens - cached_input_tokens)`
- normalized `total_tokens`는 일반적으로 `input_tokens + output_tokens`와 일치해야 한다. provider raw contract가 다르면 mapping version과 raw total을 별도로 기록하고, 설명되지 않는 불일치는 quarantine한다.
- provider adapter는 raw usage shape와 mapping version을 기록한다. reasoning token이 output detail의 부분집합인지 별도 항목인지 해당 provider contract로 판단하고 중복 합산하지 않는다.
- provider가 usage를 주지 않으면 0으로 위장하지 않고 `unknown`/`usage_estimated`로 표시한다. 비용 계산이 불가능하면 cost도 `unknown`으로 둔다.
- 재전송은 `request_id + attempt_number`로 중복 방지한다.
- 실패한 primary, compact retry와 fallback attempt도 모두 원장에 남겨 비용 누락을 방지한다.

관리자 집계는 `provider × model × caller_endpoint × operation × day`별 호출, 성공률, fallback률, 토큰, 비용과 p50/p95 latency를 반환한다. 가장 많은 토큰과 비용을 쓴 엔드포인트가 첫 화면에 정렬되어야 한다.

## 10. 전 앱 마이그레이션 정책

### MiroFish와 TradingAgents

- 기존 `llm_client` 호출을 중앙 라우터로 위임한다.
- `full` profile의 Research Manager, standalone CIO와 PM은 `decisive_text`를 사용한다.
- `compact` profile은 별도 LLM Research Manager를 호출하지 않는다. 구조화된 bull/bear와 결정론적 점수를 PM 입력으로 합성하고, PM 한 번만 decisive LLM을 호출한다.
- compact profile을 opt-in으로 추가하고 기존 기본은 shadow 검증 전까지 `full`로 유지한다.

### Workflow와 Multi-MCP

- 실행 전에 candidate/call/token 예산을 예약한다.
- 자동 workflow에서 legacy + TA 중복을 제거한다.
- Multi-MCP는 전체 후보를 full TA에 팬아웃하지 않는다.

### 종가/Jongga와 Multi-AI consensus

- 뉴스 해석은 DeepSeek-first ordinary policy를 사용하되 기존 source attribution을 보존한다.
- Gemini grounding 같은 공급자 고유 검색 기능은 specialized policy로 유지한다.
- grounding 실패 시 원천 adapter/cache/rule을 먼저 사용한다. 이후 DeepSeek/OpenAI 텍스트는 `non_grounded_summary`로 명시하며 citation/freshness가 없는 결과는 BUY 또는 decisive 입력으로 사용하지 않는다.
- OpenAI는 상시 병렬 voter가 아니라, 승인된 슬롯이 실패했을 때만 대체한다.
- 독립성 품질 비교가 끝나기 전에는 기존 consensus를 shadow 기준으로 보존한다.

### 이미지와 차트

- Gemini Vision이 primary다.
- DeepSeek Vision은 실제 모델·endpoint capability check와 fixture 테스트가 통과할 때만 중간 fallback이다.
- 미지원이면 `Gemini Vision → OpenAI Vision`으로 바로 진행한다.
- OpenAI Vision fallback은 실행당 상위 5개와 별도 예산을 넘지 않는다.

### Crypto

- 직접 하드코딩된 OpenAI 호출을 제거하고 `bulk_text` 정책으로 이동한다.
- 기존 `{analysis, symbol, model}` 응답은 유지하고 metadata를 additive하게 추가한다.

### 관리자 채팅

- 기존 최대 5회 계약은 compatibility 기간에 유지한다. compact chat을 opt-in으로 추가해 history/tool evidence 압축이 검증된 뒤 기본 2회, 절대 3회로 전환한다.
- 대화 원문 전체 대신 압축된 history와 필요한 tool evidence만 전달한다.
- 채팅 예산은 자동 TradingAgents 결정 예산과 별도 pool로 관리한다.

## 11. 관리자 관측면

신규 읽기 전용 API:

- `GET /api/admin/mirofish/llm-routing/status`
- `GET /api/admin/mirofish/llm-usage?days=7&limit=20`

관리자 UI에는 다음을 한 카드로 표시한다.

- 공급자·모델 health와 breaker 상태
- 오늘 입력/출력/추론 토큰과 예상 비용
- 엔드포인트별 비용 TOP 목록
- OpenAI token/call 비중
- fallback과 `HOLD_REVIEW` 비율
- budget 사용률과 잔여량
- usage completeness와 데이터 freshness

## 12. 검증과 롤아웃

### Gate 0 — 운영 준비

- DeepSeek credential과 decisive 모델 health check 성공
- OpenAI fallback 모델 health check 성공
- 키, header와 prompt 원문이 로그·artifact·테스트 출력에 없음
- provider order와 예산이 status API에 secret-free 형태로 표시
- health snapshot은 checked_at과 TTL을 가지며 오래된 성공/401 상태를 현재 상태로 재사용하지 않음

### Gate 1 — 계측 전용

- 현재 호출 경로에 결과 변경 없이 usage ledger를 붙인다.
- 실제 usage가 제공되는 호출과 unknown usage를 구분한다.
- endpoint/operation별 비용 순위가 재현 가능해야 한다.

### Gate 2 — Shadow compact

- 동일 EvidencePacket으로 `compact`와 `full` 결과를 비교한다.
- symbol/market/price hallucination 0건
- deterministic alpha/risk gate 위반 0건
- source/freshness 누락 0건
- 정상 verdict로 숨겨진 decisive failure 0건
- 출력 토큰 상한 80% 이상 감소 목표

### Gate 3 — Canary

- 관리자 on-demand와 소수 자동 실행부터 10% → 50%로 확대한다.
- OpenAI fallback 폭증, breaker 오작동, 비용 초과 또는 `HOLD_REVIEW` 급증 시 즉시 `full`/rule 경로로 복귀한다.
- DeepSeek decisive health가 실패하면 compact canary를 시작하거나 계속하지 않는다.

### Gate 4 — 기본 전환

- compact schema 성공률 98% 이상
- 숫자·종목 검증 오류 0건
- fallback 순서 테스트 100% 통과
- token usage 수집률 95% 이상
- OpenAI token share 정상 운영 5% 이하, call share 10% 이하
- replay-safe 1/3/5일 품질과 false-positive가 full 대비 2%p를 초과해 악화하지 않음
- OpenAI fallback만으로 운영되는 기간은 비용 절감 성공으로 판정하지 않음

## 13. 호환성·보안·운영 경계

- 공개 API 필드는 삭제하지 않고 metadata를 additive하게 추가한다.
- `.env`, API key, token cache와 원문 prompt/response를 commit하거나 usage DB에 저장하지 않는다.
- usage SQLite와 WAL/SHM은 생성 데이터이며 Git에 포함하지 않는다.
- Spring backend와 포트 8080은 변경하지 않는다.
- 배포는 별도 사용자 요청이 있을 때만 수행한다.
- DeepSeek 인증은 현재 정상이다. 다만 실행 시점 health check가 실패하면 canary/default 전환을 중단하며, OpenAI fallback-only 상태를 비용 절감 완료로 판정하지 않는다.

## 14. 확정 사항과 남은 운영 값

확정:

- 전체 앱 범위
- DeepSeek text primary
- 최고 등급 DeepSeek decisive
- decisive 실패 시 OpenAI 백업
- Gemini Vision primary
- 명시적 fallback/degraded/HOLD_REVIEW 상태
- 중앙 token/cost ledger와 hard cap

운영자가 배포 전 지정할 값:

- `AI_OPENAI_DAILY_BUDGET_USD`
- health check가 확인한 실제 DeepSeek/OpenAI/Gemini model IDs
- shadow 표본 기간과 production canary 비율
