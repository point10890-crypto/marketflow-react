# Autonomous Alpha Agent Lab Implementation Plan

> For agentic workers: apply subagent-driven-development and focused red-green tests. The user selected autonomous team execution and delegated routine implementation decisions.

Goal: Deliver four competing causal stock detectors, truthful net-cost paper replay, dated top3 observations and a deployed workflow.
Architecture: Independent alpha_lab package; existing immutable operating CIO remains untouched. Root owns integration and deployment; two compute workers and one frontend worker own disjoint files.
Tech Stack: Flask/Python3.11+, original purePython/NumPy computation, SQLite/filelock/atomicJSON where appropriate, React/TypeScript/Vite.
Spec: docs/superpowers/specs/2026-10-04-alpha-agent-lab.md

## Global constraints

No real orders, paid LLM calls, external posting, secrets or generated artifacts in commits. Current quality cohort only; unknown history remains unverified. No pandas in new replay. Frozen policies; selection validation-only. Preserve existing source/route/subscription and60%/40% operating boundaries. Primary checkout is dirty; use the attached jev-shadow-pipeline worktree on codex/alpha-agent-lab.

## Review focus

- Historical capture/vintage unknown must remain visible and cannot authorize investment.
- Intraday exit proceeds cannot fund a preceding opening buy.
- Missing/zero-volume bars cannot create profits or remove held asset value.
- Future labels/test results cannot affect fitted preprocessing or validation champion selection.
- Refresh/restart/file failures cannot replace a frozen forward decision or previously valid report.

## Task1 — audit/storage/integration (root)

Files: alpha_lab/__init__.py,data.py,store.py,service.py; scripts/run_alpha_lab.py; existing admin_mirofish.py and refresh_chart_analogue_index.ps1; tests/test_alpha_lab_data.py,test_alpha_lab_store.py,test_alpha_lab_service.py,test_alpha_lab_routes.py,test_alpha_lab_cli.py.
- [ ] Write failing tests for hash/scope/OHLC/duplicate/freshness audit and missing-quality fail-closed behavior.
- [ ] Implement audited loader, atomic source-fingerprinted run persistence and frozen dated observation journal.
- [ ] Add fixed-policy async GET/POST status route with existing AI Brain access and no-store.
- [ ] Add CLI actual run and optional existing scheduled refresh stage; preserve results and recover only failed stage.

## Task2 — execution/risk (handoff_bracket_review)

Files: alpha_lab/execution.py,risk.py and execution/risk tests.
Interfaces: ExecutionPolicy; build_bracket_plan(rows,signal_index=None,policy=None); simulate_trade(rows,signal_index,policy=None); simulate_portfolio(prices_by_symbol,decisions,policy=None,initial_cash=1,cash_buffer=.4,max_positions=3,position_cap=.2); size_from_returns(returns,stop_fraction,stress_returns=None).
- [ ] Red tests for next-open causality, zero volume, fees, ambiguous bars, unfinished trades, last marks and cash budget.
- [ ] Pure arithmetic implementation and green tests; share final response keys with learner.

## Task3 — creative factors/learner (handoff_agents_review)

Files: alpha_lab/features.py,research.py and factor/research tests.
Interfaces: features_at(rows,index); score_strategy(strategy_id,features,model=None); ResearchConfig; run_research(prices_by_symbol,names=None,config=None).
- [ ] Red tests for prefix-only factors, chronological fitted normalization and matured net outcomes.
- [ ] Original causal factor/ridge learner and fixed strategy comparison; validation champion, untouched test and doubled-cost stress.
- [ ] Return actual ranked identities, risk qualifications and independent research diagnostics; test future mutation isolation.

## Task4 — visible workflow (alpha_system_ui_scope)

Files: alphaLabApi.ts,AlphaLabPanel.tsx,ChartAnaloguePage.tsx insertion and src/test/alphaLabPanel.test.tsx.
Interface: GET/POST /api/admin/mirofish/alpha-lab; schema1 status/report documented in worker brief.
- [ ] Red tests for valid/invalid/missing/held/running results, explicit refresh and candidate selection.
- [ ] Dense readable report with score versus probability, paper versus approval, null-safe quantities and lineage.
- [ ] Focused tests, full Vitest/lint/build and browser390px/desktop proof.

## Task5 — independent review and actual delivery (root + reviewers)

- [ ] Review new execution timing, data exclusions, trial-count/heldout claims and mutable journal behavior.
- [ ] Run actual audited quality universe; record hashes, actual results and held reasons, no fabricated candidates.
- [ ] Full CI after focused green; stage source/tests/docs only, commit/push/PR attach and merge.
- [ ] MiniPC ff-only update, source/report execution, controlled Flask5003 restart, production health/API; frontend npm run deploy preserving newer legitimate UI work.
- [ ] Verify displayed real results, source version, scheduled task and prospective observation continuity.