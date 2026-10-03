# Chart Analogue Kelly Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task by task.

**Goal:** Deliver actual large-cap research TOP3 connected to historical charts, net outcome evidence, Kelly scenarios and prospective observation in AI Brain.

**Architecture:** A pure bounded extractor/quant service pins prepared local data; an offline publisher owns locks, recovery, caching and frozen decisions. A separate authenticated API and strictly validated React client render the resulting report within the existing chart page.

**Tech Stack:** Existing Python/Numpy/Flask/FileLock, React/TypeScript/Vite/Vitest, SQLite-free atomic JSON artifacts; no additional dependencies.

**Spec:** `docs/superpowers/specs/2026-10-03-chart-analogue-kelly-spec.md`

## Global Constraints

- Mode research; never manufacture certified win probability, historical vintage or approved weight.
- Scope current TOP100 financial survivors; same scope for reference owners.
- Horizon20, cost33bps, min30/cohort, similarity0.8, max3 positions, max weight0.2, max exposure0.6, cash0.4, Kelly fraction0.5.
- Preserve source/capture/price barriers and legacy contracts; no live calls or brokerage orders.
- Root owns store, routes, CLI, integration; engine agent owns engine/tests; UI agent owns typed client/panel/page/guide/tests; reviewer reads all independently.

## Review Focus

- A capture slightly after cutoff must not be accepted by rounding it down.
- An anchor/entry/exit crossing its symbol partition or invalid-price barrier must be rejected.
- A popular historical market date cannot be described as independent forward trades.
- Restart/republication must preserve the first daily decision and avoid duplicate scans.
- A stale or malformed report cannot show positive approved allocation.

### Task 1: Evidence and scenario engine

Files: create `app/services/mirofish/chart_analogue_kelly.py`, `tests/test_chart_analogue_kelly.py`.

- [x] Write failing boundary tests; verify collection/failure before implementing.
- [x] Implement `scan(universe, *, as_of=None,index_root=None,progress=None)` with fixed policy and immutable pinned index.
- [x] Reuse `empirical_kelly` for decimal validation net returns; distinguish exploratory watch ranking from stable scenario weights.
- [x] Confirm `entry_index=anchor+1`, `exit_index=anchor+1+20`, `net_return=exit/entry-1-0.0033`; full input/outcome capture <=cutoff.
- [x] Run `python -m pytest tests/test_chart_analogue_kelly.py -q`; repair only failed boundaries.

### Task 2: Recoverable publisher and member API

Files: create `app/services/mirofish/chart_analogue_kelly_store.py`, `scripts/scan_chart_analogue_kelly.py`, `tests/test_chart_analogue_kelly_store.py`, `tests/test_chart_analogue_kelly_routes.py`; modify `app/routes/admin_mirofish.py`.

- [x] Test no scan on GET, auth401/403, fixed body, private no-store, generic exceptions.
- [x] Implement `read_status`, `run_scan`, `start_scan` with bounded strict JSON, atomic writes, lock and input/source/cutoff reuse.
- [x] Freeze first daily candidates; update pending observed_outcomes separately, 33bps net cost, never overwrite decisions or claim independent validation.
- [x] Test same-input resume, changed universe/source recomputation, interrupted job, failed publication and immutable journal.
- [x] Run focused store/API/CLI tests, then real `scan_chart_analogue_kelly.py --universe <v2/report.json> --index-root <prepared index> --root <artifact directory>`; repeat to verify reuse.

### Task 3: Integrated useful viewer

Files: new `frontend-react/src/lib/chartAnalogueKellyApi.ts`, `components/aibain/ChartAnalogueKellyPanel.tsx`, `src/test/chartAnalogueKelly.test.tsx`; scoped page and guide edits.

- [x] Write invalid/null/stale report tests and scenario/selection interaction tests.
- [x] Export validated API client plus pure `ChartAnalogueKellyReportView` for actual-data preview.
- [x] Render dense names/status/metrics, factual chart comparison, allocation trace/capital calculator, universe exclusions and forward observations.
- [x] Preserve existing TOP3/search/details/navigation/subscription gates.
- [x] Run focused Vitest regression tests, then full frontend tests and build.

### Task 4: Verification and delivery

- [x] Independent review of evidence, time boundaries, source/approval and async recovery; fix findings and rerun affected tests.
- [x] Real 52-stock output inspected; log actual names, counts, gates and no synthetic data.
- [x] Browser inspect compiled actual React viewer at desktop/mobile and exercise stock/capital controls; save screenshot evidence.
- [x] Run relevant broad backend regression checks, full frontend checks; commit intended files only after passing.
- [x] Open visible result and report tested behavior with actual-data limitations and deployment state.

## Verified completion

- Engine focused 22 and store focused 15 passed; route/CLI and existing chart, agent, signal regression batch 408 passed.
- Optional nightly workflow and existing scanner CLI batch 33 passed, including canonical-scope environment conflict.
- Full frontend 427 tests passed across 56 files; TypeScript and production build passed.
- Actual dated TOP100/quality52 scan produced 25 case-bearing targets and three insufficient-sample watch candidates; stable0, research exposure0, approved exposure0.
- Real saved report accepted by the same frontend validator and isolated Flask routes; warm GET/POST reuse preserved report/decision/observation SHA256 hashes.
- Actual React view inspected at desktop and390px; capital input, comparison-case and symbol selection worked; document width equaled scroll width382px.
- Generated artifacts remain local/untracked. Source integrated in existing research branch; production deployment and scheduler installation were not performed.
