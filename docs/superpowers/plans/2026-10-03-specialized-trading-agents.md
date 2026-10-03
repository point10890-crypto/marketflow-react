# Specialized trading agents implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Follow the checked progress ledger and do not restart completed data acquisition.

**Goal:** Implement four deterministic specialized agents and a CIO orchestrator with asynchronous message passing, resumable validation and atomic paper execution.

**Architecture:** Immutable hashed messages connect independent asyncio actors. Existing empirical Kelly/quality engines supply calculations; SQLite persists completed stages and paper transactions. A CLI runs supplied evidence or explicit synthetic demonstrations.

**Tech Stack:** Python 3.12, asyncio, SQLite, existing filelock, existing MarketFlow research modules.

**Spec:** `docs/superpowers/specs/2026-10-03-specialized-trading-agents-design.md`.

## Global constraints

- Same managed worktree and branch; unrelated changes must be preserved.
- At most 100 ranked stocks, no refill after quality exclusions, at most three positions.
- No production route/index change, network/model call, credential persistence, live broker, push, or deployment.
- Current captured data retains unverified source flags. Synthetic performance is never real performance.
- Existing train/validation gates remain independent of holdout returns.
- Hard limits: 20% per position, 60% total, 40% cash, half Kelly at most 0.5.
- Messages and account transactions are durable, content-verified and idempotent.

## Review focus

- Provenance flag is false, source clock is in the future or prices are malformed: no invented facts or executable approval.
- A stale or post-validation signal is mixed with future holdout outcomes: no eligibility/weight change from holdout labels.
- A caller tampers with CIO targets or risk identity: execution rejects the unstored or mismatched plan.
- Two runs target the same paper account/date or a process restarts: at most one account mutation and consistent replay.
- Fees, sparse quotes, zero volume or a storage failure occur: no overspending, partial fills or claimed successful rebalance.

## Tasks

### 1. Shared messages and DataAgent

Files: `trading_agents/models.py`, `data_agent.py`, `__init__.py`, `tests/test_trading_data_agent.py`.

- [x] Write and observe failing immutable-message/provenance/quality/scope tests.
- [x] Implement strict message IDs, credential rejection, fixed TOP100 quality gating and blocked-data propagation.
- [x] Pass focused tests and hand off exact interfaces for independent review.

### 2. QuantAgent and RiskAgent

Files: `trading_agents/quant_agent.py`, `risk_agent.py`, `tests/test_trading_quant_risk_agents.py`.

- [x] Observe failing tests for qualification freeze, fresh signals and hard risk limits.
- [x] Reuse existing research math, omit test-driven selection, independently calculate conservative target weights.
- [x] Verify held/new position behavior, invalid quotes and no-data propagation; review independently.

### 3. Durable store and ExecutionAgent

Files: `trading_agents/store.py`, `execution_agent.py`, `tests/test_trading_execution_store.py`.

- [x] Observe failing tests for immutable stages, SQLite transaction rollback, approval hashes and daily idempotency.
- [x] Implement AgentStore APIs and paper-only sell/buy ledger with persisted CIO checks.
- [x] Verify fees, cash floor, replay, stale portfolio and concurrent daily transactions; review independently.

### 4. CIO queues, CLI and complete verification

Files: `trading_agents/orchestrator.py`, `scripts/run_specialized_trading_agents.py`, `tests/test_trading_orchestrator.py`, `tests/scripts/test_run_specialized_trading_agents.py`, `docs/specialized_trading_agents.md`.

- [x] Observe failing end-to-end, timeout, wrong-parent/stage and interruption/resume tests.
- [x] Implement actor queues, persisted-stage reuse, independent CIO checks and final reports.
- [x] Implement explicit supplied-request, synthetic-demo and acquired-data blocked runs.
- [x] Run all focused suites, then the repository Python suite; fix new failures and record unrelated failures accurately.
- [x] Run real CLI synthetic/blocked/resume proofs, inspect persisted paper balances and message identities.
- [x] Commit only deliberate source/tests/docs after required verification is green.

## Progress / rulings

- Data acquisition was completed before this expansion: current v2 TOP100 prices 421,295 rows; historical caps 257,576 scoped rows; financials 6,880 records. Raw provenance hashes and source limitations are preserved.
- Ruling: use asyncio instead of a new service framework — deterministic calculation and local persistence satisfy the message requirement without account/package overhead.
- Ruling: paper execution only — the user requested architecture implementation, while live account/broker contracts and validated forward evidence are absent.
- Ruling: the user explicitly provided the architecture and instructed implementation — proceed with the specified reversible implementation rather than requesting another design approval.

## Final verification

- Python repository suite: 3,279 passed, 4 skipped, no failures/errors; final process exit 0. JUnit: `data/kelly_research/verification/specialized-full-retry.xml`.
- Initial full-suite process ended with Windows native exception `0xc000001d` during OpenAI/Pydantic schema import. Cause was not established; fresh full retry passed without changing code or dependencies for this event.
- Compileall and whitespace checks passed. Independent reviews resolved CIO statistical/sizing/replay, complete persisted execution chain and old-date duplicate snapshot defects.
- Actual CLI synthetic/replay/daily-duplicate and acquired-data held proofs: `data/kelly_research/trading_agents/verification/final_runtime_verification.json`. Real-data source flags remain unverified.
- Commit includes source/tests/docs only. Generated data, secrets and operating deployment are excluded.
