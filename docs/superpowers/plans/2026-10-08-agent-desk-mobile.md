# Agent desk mobile implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Connect auditable agent roles and account-aware risk checks to the stock desk and make the primary experience readable on a portrait phone.

**Architecture:** Add a read-only evidence contract beside the existing immutable opportunity engine. A protected, request-only account calculator consumes server decisions. The shared frontend progressively enhances old-server responses and preserves expiry and generation guards.

**Tech Stack:** Python 3.11+, Flask, React 18, TypeScript, Tailwind, Vitest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-08-agent-desk-mobile.md`

## Global constraints

- No live orders, new paid API or messaging; `order_allowed:false` always.
- Frozen research decisions/ranking remain intact. Existing quarter Kelly and 5% cap cannot be loosened.
- GET projections are read-only and bounded. Account values are request-only.
- Missing data and probabilities are explicit. Mobile first at 360/390/430px.

## Review focus

- Copied evidence or future source availability must not pass independent-source audit.
- Refresh/poll/error/expiry must invalidate an in-flight personal plan.
- Boolean, nonfinite or missing account values must not become numeric balances.
- Existing holdings and shared theme exposure must consume aggregate budgets.
- An old backend without the optional contract must preserve research UI and withhold account quantity.

## Task 1: Evidence contract (worker owns module/tests)

Files: `app/services/mirofish/alpha_lab/decision_contract.py`, `tests/test_alpha_lab_decision_contract.py`.
Interface: `build_agent_desk(status, *, now=None, evidence=None)` as specified.

- [x] Write failing tests using hand-checked existing-opportunity fixtures: two copied URLs with one lineage cannot pass; social-only and future availability cannot authorize; missing flow+FX yields held audit; previous frozen board is unchanged.
- [x] Run the new test file and confirm the missing implementation fails.
- [x] Implement deterministic twelve-role projection, explicit unknown forecast, lineage/temporal audit and matched identity.
- [x] Run focused tests, inspect malformed/future/stale paths and report exact result.

## Task 2: Account risk contract (worker owns module/tests)

Files: `app/services/mirofish/alpha_lab/account_plan.py`, `tests/test_alpha_lab_account_plan.py`.
Interface: `build_account_plan(status, account, *, now=None)` as specified.

- [x] Write failing tests: equity 1,000,000, entry100, stop90 and a 5% reference produces at most500 shares before aggregate constraints; missing equity produces no quantity; daily -15,000 and weekly -40,000 halt at equality; same-theme holdings reduce the remaining cap.
- [x] Run and confirm the missing implementation fails.
- [x] Implement strict finite validation, fresh server-only plans, audit holds, 0.5% planned loss, existing quarter-Kelly ceiling, 40% cash floor and portfolio caps. M0 remains unpromoted but does not block pure account arithmetic once current audits pass.
- [x] Run focused tests and independently check quantity arithmetic, hostile values and state mutation.

## Task 3: Mobile stock desk (worker owns frontend files/tests)

Files: shared `AlphaLabPanel.tsx`, `OpportunityBoard.tsx`, new `AgentDesk.tsx`, `AccountPlanForm.tsx`, `lib/agentDeskApi.ts`, optional contract validation in `lib/alphaLabApi.ts`, associated Vitest files.

- [x] Test missing contract compatibility, explicit account inputs, invalidation on edits/identity/expiry, stale response suppression, keyboard-readable mobile disclosures.
- [x] Implement readable card hierarchy and portrait watchlist, validated contract, role/audit details and protected account request.
- [x] Run focused Vitest and type/build checks; preserve existing panel polling/admin search.

## Task 4: Flask integration, review and release (root)

Files: `service.py`, `app/routes/admin_mirofish.py`, route/service tests and `docs/alpha_lab_operations.md`.

- [x] Add failing route tests for auth, stale opportunity IDs, unknown body fields and bounded read-only requests.
- [x] Attach the contract after current saved projections; POST validates identity and delegates risk calculation without scanning/writes.
- [x] Independently review workers and fix material findings; exercise native saved report and mobile widths with Playwright.
- [ ] Run full frontend lint/test/build plus required Python checks and full CI; stage only intended files, commit/push/PR/merge under existing authorization.
- [ ] Deploy frontend via `npm run deploy`, pull production main and restart the 5003 Flask task; verify health, saved API and deployed portrait UI.

## Rulings and evidence

Ruling: No new model or speculative source collector is added. Missing source roles are surfaced; existing research recommendations are retained. This avoids inventing evidence or silently certifying the already-inspected historical interval.
Ruling: Prior explicit commit/push/deploy authorization remains applicable to the requested implementation. No redundant approval is needed.
Ruling: Account calculation readiness is distinct from strategy/CIO approval. Unknown future probabilities are not invented and M0 remains unpromoted; deterministic sizing with explicit accounts and passed current audits can still be calculated as a research reference.

Verification before commit: related Python suite 829 tests passed; full frontend 67 files / 795 tests passed, lint and production build passed. Independent backend and frontend reviews have no unresolved findings. Native full pytest collection is blocked by Windows application-control rejection of an existing PyArrow DLL; full Linux CI must pass before merge. Production release/portrait QA remains pending.
