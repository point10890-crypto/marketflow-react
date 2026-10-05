# Profit Opportunity Engine — approved implementation plan

**Goal:** Show zero to three concrete, cost-qualified stock opportunities with coherent entry conditions, fractional Kelly references, explainable ranking, and immutable issued-opportunity tracking.
**Architecture:** Existing Flask research/scheduled-monitor pipeline; deterministic all-survivor challenger; independent journal; pure saved-status projection; React board inside existing chart-analogue page. No paid LLM/new framework required.
**Stack:** Python standard-library calculations, existing FileLock/atomic JSON helpers, React/TypeScript/Vite/Vitest.
**Approved specification:** `data/kelly_research/profit-agent-design-20261005/report.html`; implementation contract `data/implementation/profit-opportunity-20261005/contract.md`.

## Scope rulings

- Preserve original research, BUY3 selection, proposal policy, audit hashes, both forward journals, auth and routes. The new policy has a separate version and ledger.
- Evaluate all qualified survivors within the existing maximum100 quality-stock universe. Rank calibration doubled-cost returns with an explicit uncertainty penalty; confirmation is a filter, never future probability or an independently untouched validation claim.
- Penalize correlated exposure using only bars available at the decision. Keep maximum3 unique symbols, per-symbol5% quarter-Kelly reference, account-risk1% cap and total15% ceiling. There is no automatic brokerage order.
- Actual current price must pass the original calendar/session/expiry, source binding/freshness and chase/stop/target gates. Observed current quote is a reference, not an assumed historical same-open fill.
- Persist issued decisions independently; unknown execution remains unknown, not a known nonfill or realized investment return. No model promotion or guaranteed profit is claimed.
- Commit only after verification under the desktop commit instruction `테스트를 모두 통과시 커밋`. Push and production deployment remain outside this implementation request. Preserve unrelated working-tree changes.

## Task1 — deterministic engine (core worker)

Own `app/services/mirofish/alpha_lab/decision_engine.py`, additive `discovery.py` bounded candidate_limit and `tests/test_alpha_lab_decision_engine.py`.
1. Write failing tests for default discovery preservation, cost/uncertainty ranking, correlation diversification, future-bar exclusion, finite plans/Kelly bounds and sparse/malformed evidence.
2. Add pure board construction and time-sensitive projection. Give every decision/row reproducible identity and explicit why-stock/why-now/next-action fields.
3. Exercise closed/open/expired sessions, stale/future quotes, ceiling breaches and source mismatches. Run focused pytest.

## Task2 — immutable persistence and scan/monitor integration (store worker)

Own `opportunity_store.py`, `service.py`, additive `monitor.py` wrapper and new persistence/integration tests.
1. Obtain complete candidate pool, restore original top3 before legacy hashing/freezing, build/store independent board.
2. Freeze immutable decision files, idempotent evaluations and bound saved quotes under `root/decision_engine`; keep reads cheap and read-only.
3. Reuse certified calendar; collect at most3 selected quote references only in scheduled monitor. Preserve all original outputs/journals. Recheck source after external requests.
4. Test replay, corruption, failure preservation, expiry, races and no GET network/writes.

## Task3 — investor decision board (UI worker)

Own `opportunityEngine.ts`, `OpportunityBoard.tsx`, `AlphaLabPanel.tsx`, additive `alphaLabApi.ts`, and new UI tests.
1. Validate optional new contract with exact identity, finite prices, time, weights, uniqueness and explicit source markers.
2. Reuse existing poll/account/time lifecycle. Show new primary board; retain prior candidate cards in disclosure when new board exists.
3. Dense dark dashboard: stock/action first, why/entryband/stop/target/weight next, source and evidence in disclosure. Preserve routing and admin gate.
4. Red/green component/parser tests, existing panel/navigation regression, full Vitest/build.

## Coordinator verification

- Review all task diffs and interfaces, fix integration failures, run related AlphaLab Python tests and full frontend tests/build after focused checks.
- Rebuild new board from the existing real price snapshot in isolated output storage. Record input hash, cutoff, pool/selection and realistic held states without provider credentials.
- Exercise Flask API through injected local test service/auth; verify JSON, no-store and read-only GET. Render actual new component in the local app using that fixture; desktop/mobile screenshots and navigation checks.
- Independent code review specifically for look-ahead, source/expiry forgery, legacy journal mutation, inferred fills and account/token leaks. Fix important findings before completion.
- Final report identifies implemented functionality, exact verification, visible local result and remaining statistical limitations. Deployment is not claimed.

## Progress ledger

2026-10-05: Existing attached isolated worktree reused at e1e73517; branch `codex/profit-opportunity-engine` created. Three file-owned implementation workers dispatched. Contract clarified: board entry_session; candidate fetched_at/quote_source plus repeated source binding. Historical source_at is separate from live quote fetch time.

2026-10-05 completion evidence: Python AlphaLab and signal-contract suite544/544; full frontend721/721; TypeScript/Vite build and18-route prerender passed. Real52-stock service execution issued3 independent opportunity rows (196170,402340,007660), all currently price/calendar check pending; original discovery audit remained41b7348c2d9d5712a2af4aeb765aecfc78a5d71418758778b5dc75ef74a08821. Original data output hashes unchanged; GET wrote no files; provider calls0, live orders0. Desktop1440 and mobile390 browser checks passed with no horizontal overflow, page errors or external requests; detail selection and evidence disclosure worked; authenticatedAPI200/private-no-store, anonymous401. Independent20-case review regression passed after full-response privacy and missing-observation integrity fixes; no remaining important findings. Generated local fixtures/screenshots remain outside staged source files. Commit follows verified desktop instruction; no push/production deployment performed.
