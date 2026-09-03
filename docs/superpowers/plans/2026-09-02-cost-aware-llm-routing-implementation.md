# MarketFlow 비용 최적화 LLM 라우팅 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILLS: use `superpowers:test-driven-development` for every behavior change, `superpowers:subagent-driven-development` for independent task groups, and `superpowers:verification-before-completion` before any completion claim.

**Goal:** 전체 MarketFlow AI 호출을 DeepSeek-first, Gemini-Vision-primary, OpenAI-budgeted-fallback 구조로 통합하고 종목당 기본 TradingAgents 텍스트 호출을 14회에서 3회로 줄이면서 실패와 비용을 명확하게 기록한다.

**Architecture:** 중립 패키지 `app/services/ai_routing/`이 operation policy, provider adapter, retry/fallback, circuit breaker, budget reservation과 usage ledger를 소유한다. 기존 MiroFish `llm_client`는 호환 wrapper로 유지한다. 도메인 계층은 canonical EvidencePacket과 결정론적 금융 게이트를 소유하며, LLM 결과는 additive metadata와 함께 검증된 뒤에만 사용한다.

**Tech Stack:** Python, Flask, OpenAI-compatible SDK, Google GenAI SDK, SQLite, pytest, React, TypeScript, Vitest.

**Approved specification:** `docs/superpowers/specs/2026-09-02-cost-aware-llm-routing-architecture.md`

## 실행 경계

- 2026-09-02 재검증에서 DeepSeek models API와 Flash/Pro 최소 생성 요청이 모두 HTTP 200으로 성공했다. 구현 시점에도 health check를 다시 통과해야 하며, 실패하면 live canary/default 전환을 금지한다.
- `.env` 값, API key, prompt/response 원문을 출력하거나 artifact에 저장하지 않는다.
- 기존 public response 필드는 삭제하지 않는다.
- Spring `backend/`와 포트 8080은 건드리지 않는다.
- 이 계획의 실행은 commit, push, 배포를 포함하지 않는다. 별도 사용자 요청이 있을 때만 수행한다.
- dirty worktree의 기존 untracked/generated 파일을 수정하거나 stage하지 않는다.

---

## Task 1: 중앙 계약과 operation policy

**Files:**

- Create: `app/services/ai_routing/__init__.py`
- Create: `app/services/ai_routing/contracts.py`
- Create: `app/services/ai_routing/policy.py`
- Create: `tests/test_ai_routing_policy.py`

- [ ] **Step 1: 실패 테스트 작성**

검증할 계약:

```python
def test_decisive_policy_cannot_be_reordered_by_legacy_env(monkeypatch):
    monkeypatch.setenv("MIROFISH_LLM_PROVIDER_ORDER", "openai,deepseek")
    policy = policy_for(Operation.DECISIVE_TEXT)
    assert policy.providers == ("deepseek", "openai")
    assert policy.max_output_tokens == 1200

def test_vision_policy_starts_with_gemini():
    policy = policy_for(Operation.VISION)
    assert policy.providers[0] == "gemini"

def test_result_distinguishes_hold_and_hold_review():
    assert AnalysisStatus.HOLD_REVIEW != "HOLD"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_ai_routing_policy.py -q`

Expected: package/module import failure.

- [ ] **Step 3: 최소 구현**

`Operation`, `AnalysisStatus`, `RoutingRequest`, `ProviderAttempt`, `TokenUsage`, `RoutingResult`, `RoutePolicy`를 dataclass/enum으로 정의한다. 기본 정책은 spec §4의 provider order와 output cap을 그대로 사용한다. 모델 ID는 env에서 읽되 operation 등급과 provider 순서는 고정한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_ai_routing_policy.py -q`

---

## Task 2: SQLite usage 원장과 가격 계산

**Files:**

- Create: `app/services/ai_routing/store.py`
- Create: `app/services/ai_routing/pricing.py`
- Create: `app/services/ai_routing/telemetry.py`
- Create: `tests/test_ai_routing_telemetry.py`
- Modify: `.gitignore` only if the generated usage DB pattern is not already ignored

- [ ] **Step 1: 실패 테스트 작성**

임시 SQLite 경로를 사용해 다음을 검증한다.

- 동일 `request_id + attempt_number` 중복 insert가 한 번만 집계된다.
- cached input은 전체 input보다 클 수 없다.
- reasoning token을 total token에 이중 합산하지 않는다.
- usage 없는 응답은 0이 아니라 unknown/estimated 상태가 된다.
- prompt, response, key, authorization 필드는 DB schema에 존재하지 않는다.
- provider/model/endpoint/operation/day별 합계와 비용 순위가 계산된다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_ai_routing_telemetry.py -q`

- [ ] **Step 3: 최소 구현**

`data/ai_routing/usage.sqlite3`를 기본 경로로 사용하고 테스트에서는 monkeypatch한다. WAL, busy timeout과 transaction을 사용한다. attempt table에는 spec §9의 필드만 저장한다. `pricing.py`는 provider/model rate와 `pricing_version`을 분리하고 env override를 허용한다.

핵심 집계 함수:

```python
record_attempt(attempt: ProviderAttempt) -> None
usage_summary(days: int, limit: int) -> dict
estimate_cost(provider: str, model: str, usage: TokenUsage) -> Decimal | None
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_ai_routing_telemetry.py -q`

---

## Task 3: 원자적 budget reservation과 circuit breaker

**Files:**

- Create: `app/services/ai_routing/budget.py`
- Create: `app/services/ai_routing/breaker.py`
- Create: `tests/test_ai_routing_budget.py`
- Create: `tests/test_ai_routing_breaker.py`

- [ ] **Step 1: 실패 테스트 작성**

Budget:

- 자동 실행 OpenAI 호출 5회, 입력 30,000, 출력 6,000 기본 hard cap.
- 동시 두 예약이 같은 잔여량을 중복 사용하지 않는다.
- 80% 이후 low-priority request는 예약되지 않는다.
- decisive 예약이 vision/bulk보다 우선한다.
- 실제 usage 정산 후 잔여량이 정확하다.

Breaker:

- 401/402/403은 재시도 없이 즉시 open.
- 429/timeout/5xx는 정해진 임계치 전까지 전체 provider를 닫지 않는다.
- invalid JSON과 numeric mismatch는 breaker를 열지 않는다.
- text와 vision breaker 상태가 독립이다.
- cooldown 뒤 half-open probe는 한 번만 허용된다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_ai_routing_budget.py tests/test_ai_routing_breaker.py -q`

- [ ] **Step 3: 최소 구현**

SQLite transaction으로 preflight reservation을 만든다. breaker key는 `provider + modality + model_tier`로 둔다. 오류 원문은 저장하지 않고 secret-free enum만 저장한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_ai_routing_budget.py tests/test_ai_routing_breaker.py -q`

---

## Task 4: Provider adapter와 중앙 router

**Files:**

- Create: `app/services/ai_routing/providers.py`
- Create: `app/services/ai_routing/router.py`
- Create: `app/services/ai_routing/validation.py`
- Create: `tests/test_ai_routing_router.py`

- [ ] **Step 1: 실패 테스트 작성**

mock adapter로 다음 순서를 검증한다.

```python
def test_decisive_deepseek_then_one_openai_fallback(...): ...
def test_both_decisive_providers_fail_returns_hold_review(...): ...
def test_auth_failure_opens_breaker_and_next_request_skips_dead_provider(...): ...
def test_budget_exhaustion_does_not_call_provider(...): ...
def test_invalid_json_falls_back_without_global_breaker(...): ...
def test_usage_is_recorded_for_every_billable_attempt(...): ...
def test_vision_starts_with_gemini_and_skips_unverified_deepseek_vision(...): ...
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_ai_routing_router.py -q`

- [ ] **Step 3: 최소 구현**

Provider adapter는 SDK 응답에서 text와 native usage를 함께 반환한다. 중앙 router는 다음 순서를 고정한다.

1. cache/dedup 확인
2. budget 예약
3. breaker 확인
4. provider 호출
5. 오류 분류와 제한 재시도
6. 순차 fallback
7. JSON/schema validation
8. 실제 usage 정산과 telemetry 기록
9. `RoutingResult` 반환

`route_text()`와 `route_vision()`을 분리해 이미지 오류가 텍스트 정책에 섞이지 않게 한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_ai_routing_router.py -q`

---

## Task 5: 기존 MiroFish llm_client 호환 연결

**Files:**

- Modify: `app/services/mirofish/llm_client.py`
- Modify: `tests/test_llm_provider_fallback.py`
- Modify: `tests/test_mirofish_llm_system_prompt.py` if metadata assertions require it

- [ ] **Step 1: 기존 계약 보존 테스트 추가**

- `generate_text`, `generate_text_with_provider`, `generate_text_with_metadata` signature/return shape 유지.
- ordinary call은 DeepSeek → OpenAI fallback.
- explicit operation을 전달하면 중앙 policy가 적용됨.
- 기존 `collect_generation_metadata()`가 token/cost/breaker 필드를 additive하게 수집.
- `MIROFISH_LLM_PROVIDER_ORDER=deepseek`가 암묵적으로 모든 provider를 다시 붙이는 기존 문제를 operation policy에서는 재현하지 않음.

- [ ] **Step 2: 현재 테스트 실행**

Run: `python -m pytest tests/test_llm_provider_fallback.py tests/test_mirofish_llm_system_prompt.py -q`

- [ ] **Step 3: wrapper 구현**

기존 provider helper를 한 번에 제거하지 않는다. public 함수 내부를 중앙 router로 위임하고 legacy metadata field를 새 `RoutingResult`에서 변환한다.

- [ ] **Step 4: 회귀 확인**

Run: `python -m pytest tests/test_llm_provider_fallback.py tests/test_mirofish_llm_system_prompt.py -q`

---

## Task 6: 결정 역할과 HOLD_REVIEW 계약

**Files:**

- Modify: `app/services/mirofish/tradingagents/research_debate.py`
- Modify: `app/services/mirofish/tradingagents/trader_risk.py`
- Modify: `app/services/mirofish/tradingagents/engine.py`
- Modify: `app/services/mirofish/cio_react.py`
- Modify: `tests/test_mirofish_tradingagents_debate.py`
- Modify: `tests/test_mirofish_tradingagents_trader_risk.py`
- Modify: `tests/test_mirofish_tradingagents_engine.py`
- Modify: `tests/test_mirofish_cio_react.py`

- [ ] **Step 1: 실패 테스트 작성**

- full Research Manager, PM와 standalone CIO가 `DECISIVE_TEXT`를 사용한다.
- 첫 시도 모델은 configured highest-grade DeepSeek model이다.
- DeepSeek 실패 뒤 OpenAI가 정확히 한 번 호출된다.
- 양쪽 실패 시 최종 `verdict=HOLD_REVIEW`; 정상 `HOLD`와 다르다.
- deterministic rule 결과는 `rule_candidate_verdict`에만 남는다.
- HOLD_REVIEW가 BUY/STRONG_BUY 필터나 알림으로 승격되지 않는다.
- provider order env가 결정 순서를 바꾸지 않는다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mirofish_tradingagents_debate.py tests/test_mirofish_tradingagents_trader_risk.py tests/test_mirofish_tradingagents_engine.py tests/test_mirofish_cio_react.py -q`

- [ ] **Step 3: 구현**

결정 프롬프트에는 허용 verdict 집합, 고정 symbol/name/market, 고정 numeric evidence를 포함한다. 결과가 허용 집합 밖이거나 숫자를 변조하면 폐기하고 fallback한다. run artifact에 `analysis_status`, 실제 provider/model, fallback reason과 full usage를 저장한다.

- [ ] **Step 4: 통과 확인**

Run: 위 Step 2 명령 재실행.

---

## Task 7: Canonical EvidencePacket과 TradingAgents compact profile

**Files:**

- Create: `app/services/mirofish/evidence_packet.py`
- Modify: `app/services/mirofish/multi_mcp_orchestrator.py`
- Modify: `app/services/mirofish/tradingagents/analysts.py`
- Modify: `app/services/mirofish/tradingagents/research_debate.py`
- Modify: `app/services/mirofish/tradingagents/trader_risk.py`
- Modify: `app/services/mirofish/tradingagents/engine.py`
- Create: `tests/test_mirofish_evidence_packet.py`
- Modify: `tests/test_mirofish_tradingagents_analysts.py`
- Modify: `tests/test_mirofish_tradingagents_debate.py`
- Modify: `tests/test_mirofish_tradingagents_engine.py`

- [ ] **Step 1: EvidencePacket 테스트**

- symbol/name/market/as_of가 필수.
- numeric fields와 deterministic scores는 immutable input으로 취급.
- source/fetched_at/freshness/confidence/evidence_id 보존.
- cache fingerprint가 source, model, schema 또는 as_of 변화에 따라 변경.
- stale 또는 source fingerprint가 다른 packet은 재사용하지 않음.

- [ ] **Step 2: compact profile 실패 테스트**

- `run_deep_analysis(..., profile="compact")`는 성공 primary 기준 텍스트 LLM 3회: digest, bull/bear, PM.
- digest cap 768, bull/bear cap 768, PM cap 1,200.
- compact는 별도 LLM Research Manager/trader/risk role을 호출하지 않음.
- 네 deterministic analyst score와 risk checks는 유지.
- bull/bear JSON은 별도 필드와 evidence IDs를 포함.
- full profile은 기존 구조와 response fields를 유지.

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/test_mirofish_evidence_packet.py tests/test_mirofish_tradingagents_analysts.py tests/test_mirofish_tradingagents_debate.py tests/test_mirofish_tradingagents_engine.py -q`

- [ ] **Step 4: 최소 구현**

기존 Multi-MCP `_evidence_packet()` 로직을 canonical builder로 이동하고 private wrapper는 호환성을 위해 남긴다. engine은 optional `evidence_packet`과 `profile`을 받는다. 기본 profile은 shadow 단계까지 `full`이다.

- [ ] **Step 5: 통과 확인**

Run: 위 Step 3 명령 재실행.

---

## Task 8: 분석 cache와 자동 workflow 중복 제거

**Files:**

- Create: `app/services/mirofish/tradingagents/run_cache.py`
- Modify: `app/services/mirofish/tradingagents/engine.py`
- Modify: `app/services/mirofish/workflow.py`
- Modify: `app/services/mirofish/store.py`
- Modify: `tests/test_mirofish_tradingagents_engine.py`
- Modify: `tests/test_mirofish_tradingagents_workflow.py`
- Modify: `tests/test_admin_mirofish_workflow.py`
- Modify: `tests/test_mirofish_store_attach_ta.py`
- Modify: `tests/test_mirofish_workflow_buy_filter.py`

- [ ] **Step 1: cache 테스트**

- 같은 symbol/as_of/fingerprint/profile/model/schema는 기존 run 재사용.
- source freshness, model, profile 또는 force가 다르면 새 run.
- 동시 동일 요청은 하나만 실행.

- [ ] **Step 2: workflow 중복 테스트**

- 자동 workflow top candidate는 legacy GraphRAG/CIO와 TA를 둘 다 호출하지 않음.
- compact TA 결과에서 legacy-compatible graph/report/analysis summary가 생성됨.
- 독립 `POST /runs`는 기존 legacy 동작 유지.
- HOLD_REVIEW 후보는 TOP3 확정/알림 대상이 아님.

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/test_mirofish_tradingagents_engine.py tests/test_mirofish_tradingagents_workflow.py tests/test_admin_mirofish_workflow.py tests/test_mirofish_store_attach_ta.py tests/test_mirofish_workflow_buy_filter.py -q`

- [ ] **Step 4: 구현**

workflow의 자동 경로에만 compact 결과 adapter를 적용한다. 기존 필드를 삭제하지 말고 `source_run_id`, `analysis_status`, `provider_usage`를 additive하게 붙인다.

- [ ] **Step 5: 통과 확인**

Run: 위 Step 3 명령 재실행.

---

## Task 9: Multi-MCP와 auto-runner preflight budget

**Files:**

- Modify: `app/services/mirofish/multi_mcp_orchestrator.py`
- Modify: `app/services/mirofish/auto_runner.py`
- Modify: `app/services/mirofish/workflow.py`
- Modify: `tests/test_mirofish_mcp_multi_tools.py`
- Modify: `tests/test_mirofish_auto_runner.py`
- Modify: `tests/test_admin_mirofish_workflow.py`

- [ ] **Step 1: 실패 테스트 작성**

- future 제출 전에 candidate/call/token 예산 예약.
- 예산이 5개 후보만 허용하면 20개의 future를 만들지 않음.
- 80% budget 시 low-priority enrichment를 rule/cache로 전환.
- 100% budget 시 추가 OpenAI attempt 없음.
- outer auto-runner gate와 중앙 per-call budget이 서로 다른 값을 중복 차감하지 않음.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mirofish_mcp_multi_tools.py tests/test_mirofish_auto_runner.py tests/test_admin_mirofish_workflow.py -q`

- [ ] **Step 3: 구현 및 통과 확인**

Run: 위 Step 2 명령 재실행.

---

## Task 10: Gemini-primary 이미지 라우팅과 burst 방지

**Files:**

- Modify: `main_kr.py`
- Modify: `tests/test_main_kr_chart_fallback.py`
- Modify: `tests/test_ai_chart_telegram_message.py` if result metadata reaches messages

- [ ] **Step 1: 실패 테스트 작성**

- Gemini 성공 시 다른 vision provider를 호출하지 않음.
- Gemini 실패 시 verified DeepSeek Vision만 중간 시도.
- DeepSeek Vision capability가 false면 OpenAI Vision으로 바로 이동.
- OpenAI Vision은 실행당 최대 5회이고 상위 후보만 사용.
- parameter negotiation 재시도가 budget attempt를 우회하지 않음.
- vision 실패가 text breaker를 열지 않음.
- 결과에 actual provider/model/fallback reason이 포함됨.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_main_kr_chart_fallback.py tests/test_ai_chart_telegram_message.py -q`

- [ ] **Step 3: 구현**

기존 `analyze_chart()` response schema를 유지하면서 중앙 `route_vision()`을 사용한다. DeepSeek Vision은 health/capability false가 기본이며 검증된 model ID가 있을 때만 활성화한다.

- [ ] **Step 4: 통과 확인**

Run: 위 Step 2 명령 재실행.

---

## Task 11: Crypto와 Jongga/Multi-AI 마이그레이션

**Files:**

- Modify: `app/routes/crypto.py`
- Modify: `engine/llm_analyzer.py`
- Modify: `engine/generator.py`
- Create: `tests/test_crypto_signal_analysis.py`
- Modify: `tests/test_llm_screener_token_param.py`
- Modify: `tests/test_multi_ai_consensus.py`
- Modify: `tests/test_ensure_jongga_v2.py`
- Modify: `tests/test_scheduler_jongga_idempotency.py`

- [ ] **Step 1: Crypto 실패 테스트**

- 직접 하드코딩 OpenAI 대신 `BULK_TEXT` 사용.
- DeepSeek 성공 시 OpenAI 미호출.
- DeepSeek 실패 시 OpenAI 한 번.
- 기존 `{analysis, symbol, model}` 필드 유지, metadata additive.

- [ ] **Step 2: Jongga/consensus 실패 테스트**

- source attribution 유지.
- Gemini grounding 같은 고유 기능은 specialized operation으로 보존.
- 일반 텍스트는 DeepSeek-first.
- OpenAI는 모든 consensus 실행에 병렬 참여하지 않고 실패한 승인 슬롯만 대체.
- shadow flag에서는 기존 consensus 결과도 비교용으로 보존하되 사용자 verdict에는 한 경로만 반영.

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/test_crypto_signal_analysis.py tests/test_llm_screener_token_param.py tests/test_multi_ai_consensus.py tests/test_ensure_jongga_v2.py tests/test_scheduler_jongga_idempotency.py -q`

- [ ] **Step 4: 구현 및 통과 확인**

Run: 위 Step 3 명령 재실행.

---

## Task 11B: 관리자 채팅 compact profile과 독립 예산

**Files:**

- Modify: `app/services/mirofish/chat_agent.py`
- Create: `tests/test_mirofish_chat_agent_budget.py`
- Modify: `tests/test_admin_mirofish_service.py` if route response metadata changes

- [ ] **Step 1: 실패 테스트 작성**

- compatibility profile은 기존 최대 5회 동작을 유지.
- opt-in compact profile은 기본 2회, 절대 3회.
- tool result 8,000자 원문 대신 evidence ID와 bounded summary를 전달.
- DeepSeek-first/OpenAI-fallback 순서와 usage metadata를 기록.
- 채팅 budget pool은 자동 decisive pool과 독립.
- budget 소진 또는 양 공급자 실패는 정상 답변으로 위장하지 않고 명시적 degraded/error method를 반환.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_mirofish_chat_agent_budget.py tests/test_admin_mirofish_service.py -q`

- [ ] **Step 3: 구현**

`MIROFISH_CHAT_PROFILE=compat|compact`를 도입하고 초기 기본은 `compat`로 둔다. shadow에서 답변 완결성과 tool call 성공률을 비교한 뒤에만 compact를 기본으로 전환한다.

- [ ] **Step 4: 통과 확인**

Run: 위 Step 2 명령 재실행.

---

## Task 12: 관리자 usage/status API

**Files:**

- Create: `app/services/ai_routing/reporting.py`
- Modify: `app/routes/admin_mirofish.py`
- Create: `tests/test_admin_mirofish_llm_usage.py`

- [ ] **Step 1: 실패 테스트 작성**

Endpoints:

```text
GET /api/admin/mirofish/llm-routing/status
GET /api/admin/mirofish/llm-usage?days=7&limit=20
```

검증:

- admin/aibain 인증 패턴 유지.
- days/limit strict validation과 `Cache-Control: no-store`.
- provider health, breaker, model, budget은 secret-free.
- endpoint/operation별 token/cost 내림차순.
- `usage_completeness`, `unknown_usage_attempts`, freshness 포함.
- 실제 key/value와 raw error가 response에 없음.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_admin_mirofish_llm_usage.py -q`

- [ ] **Step 3: 구현 및 통과 확인**

Run: `python -m pytest tests/test_admin_mirofish_llm_usage.py -q`

---

## Task 13: 관리자 비용 카드

**Files:**

- Create: `frontend-react/src/components/admin/LlmRoutingCostCard.tsx`
- Modify: `frontend-react/src/lib/mirofishApi.ts`
- Modify: `frontend-react/src/pages/admin/AdminEndpointsPage.tsx`
- Create: `frontend-react/src/components/admin/LlmRoutingCostCard.test.tsx`
- Modify: `frontend-react/src/pages/admin/adminEndpointsEnter.test.tsx` if page integration requires it

- [ ] **Step 1: 실패 테스트 작성**

- 오늘 token/cost, OpenAI 비중, fallback/HOLD_REVIEW, budget bar 표시.
- endpoint 비용 TOP 목록 정렬.
- DeepSeek 401이면 key 정보를 노출하지 않고 `인증 실패 · 백업 사용 중` 표시.
- 0 tokens와 usage unknown을 서로 다르게 표시.
- breaker/health 상태의 접근 가능한 텍스트 label 제공.

- [ ] **Step 2: 실패 확인**

Run: `Set-Location frontend-react; npm run test -- LlmRoutingCostCard.test.tsx`

- [ ] **Step 3: 구현**

기존 admin 페이지의 밀도 높은 운영 UI 스타일을 따른다. 대형 마케팅 카드나 장식 그래프 대신 요약 KPI, budget bar와 정렬 가능한 소형 표를 사용한다.

- [ ] **Step 4: 통과 확인**

Run: `Set-Location frontend-react; npm run test -- LlmRoutingCostCard.test.tsx adminEndpointsEnter.test.tsx`

---

## Task 14: 설정·health·shadow 비교 도구

**Files:**

- Modify: `.env.example`
- Create: `scripts/llm_routing_health.py`
- Create: `scripts/compare_tradingagents_profiles.py`
- Create: `tests/test_llm_routing_health.py`
- Create: `tests/test_compare_tradingagents_profiles.py`

- [ ] **Step 1: 실패 테스트 작성**

- health 출력은 configured/available/model/status만 포함하고 credential 값은 포함하지 않음.
- HTTP 401을 `authentication`으로 분류하고 inference 재시도를 하지 않음.
- comparison은 저장된 동일 EvidencePacket을 사용하고 look-ahead source를 읽지 않음.
- compact/full call count, tokens, verdict disagreement, numeric/source violations를 출력.
- 실제 API 호출은 명시적 `--live`가 없으면 하지 않음.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_llm_routing_health.py tests/test_compare_tradingagents_profiles.py -q`

- [ ] **Step 3: 구현**

`.env.example`에는 변수명과 안전한 설명만 추가한다. 실제 값이나 현재 키 상태를 기록하지 않는다.

- [ ] **Step 4: 통과 확인**

Run: 위 Step 2 명령 재실행.

---

## Task 15: 통합 검증과 전환 판정

- [ ] **Step 1: Backend focused suite**

```powershell
python -m pytest `
  tests/test_ai_routing_policy.py `
  tests/test_ai_routing_telemetry.py `
  tests/test_ai_routing_budget.py `
  tests/test_ai_routing_breaker.py `
  tests/test_ai_routing_router.py `
  tests/test_llm_provider_fallback.py `
  tests/test_mirofish_evidence_packet.py `
  tests/test_mirofish_tradingagents_analysts.py `
  tests/test_mirofish_tradingagents_debate.py `
  tests/test_mirofish_tradingagents_trader_risk.py `
  tests/test_mirofish_tradingagents_engine.py `
  tests/test_mirofish_tradingagents_workflow.py `
  tests/test_main_kr_chart_fallback.py `
  tests/test_crypto_signal_analysis.py `
  tests/test_mirofish_chat_agent_budget.py `
  tests/test_admin_mirofish_llm_usage.py -q
```

- [ ] **Step 2: Required baseline**

Run: `python -m pytest tests/test_signal_contract.py -v`

- [ ] **Step 3: Broader affected backend suite**

Run: `python -m pytest tests/test_admin_mirofish_service.py tests/test_admin_mirofish_workflow.py tests/test_mirofish_mcp_multi_tools.py tests/test_multi_ai_consensus.py tests/test_ensure_jongga_v2.py -q`

- [ ] **Step 4: Compile check**

Run: `python -m compileall app/services/ai_routing app/services/mirofish engine main_kr.py`

- [ ] **Step 5: Frontend checks**

```powershell
Set-Location frontend-react
npm run test -- LlmRoutingCostCard.test.tsx adminEndpointsEnter.test.tsx
npm run build
```

- [ ] **Step 6: Secret and generated-artifact audit**

확인 사항:

- diff에 `.env`, keys, usage SQLite/WAL/SHM, prompt/response payload 없음.
- 의도한 source/test/doc 파일만 변경됨.
- 기존 dirty/untracked 파일은 그대로 보존됨.

- [ ] **Step 7: Offline shadow acceptance**

저장된 replay-safe 표본에서 다음을 확인한다.

- compact text LLM calls: 종목당 3회
- output cap 감소: 80% 이상 목표
- symbol/market/price hallucination: 0
- deterministic gate violation: 0
- hidden decisive failure: 0
- schema success: 98% 이상

- [ ] **Step 8: Live 전환 조건 보고**

실행 시점 DeepSeek health가 401이면 `blocked for live canary`로 보고하고 종료한다. health가 정상이어도 bounded on-demand canary는 구현·테스트 완료 후 별도 승인 범위에서 수행한다.

---

## 완료 판정

구현 완료는 다음이 모두 충족될 때만 주장한다.

1. 중앙 policy와 실제 attempts가 DeepSeek-first/OpenAI-fallback 순서를 증명한다.
2. Gemini Vision primary가 테스트와 metadata로 확인된다.
3. 모든 decisive provider 실패가 `HOLD_REVIEW`로 노출된다.
4. endpoint/operation/provider별 actual token usage와 unknown usage가 구분된다.
5. budget과 breaker가 fan-out 및 반복 fallback을 차단한다.
6. compact path가 목표 호출 수와 품질 guardrail을 통과한다.
7. focused/backend/frontend 검증이 모두 green이다.
8. live 전환 여부와 DeepSeek credential 상태를 별도로 명시한다.
