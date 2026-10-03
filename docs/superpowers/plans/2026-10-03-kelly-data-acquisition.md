# Large-cap historical data acquisition implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Acquire reproducible long prices, dated market caps, and historical financial disclosures for the user's fixed market-cap-leading cohort, rather than scanning all stock price patterns.

**Architecture:** Three independent, opt-in research collectors read the same existing TOP100 report. Each preserves raw source snapshots, actual capture time, SHA-256, request identity, coverage, and unresolved data-quality flags. Raw acquisition is separate from approved backtest inputs: an old reporting period or an undocumented adjustment method never implies point-in-time validation.

**Tech Stack:** Python 3.12, standard library HTTP/CSV/JSON, existing python-dotenv, optional research-only PyArrow for Parquet.

**Spec:** User requests “전종목을 검사 하지 말고 시총상위 우량주를 대상으로 검사” and “확보 할 수 있는 방법을 찾아 그럼”; existing research contract in `docs/kelly_winrate_backtest.md`.

## Global constraints

- Write only in the managed `jev-shadow-pipeline/bitman_marketfloww` worktree.
- Freeze the corrected 2026-10-01 ranked TOP100 (`large_cap_20261001_v2/report.json`) before fetching; never replace quality exclusions with stocks below rank 100. Normalize KOSDAQ GLOBAL to KOSDAQ while preserving the source market label.
- Do not print or commit `.env`, API keys, token caches, or generated financial/source data.
- Preserve unrelated changes and existing production collectors, scanners, indexes, and deployment state.
- No orders, production API changes, scheduler jobs, pushes, or deployments in this acquisition task.
- Source money units, reporting periods, price adjustment basis, and disclosure vintage require evidence, not assumptions.
- Current TOP100 remains a survivor cohort; its historical study is not a historical-universe backtest.
- A larger dataset does not prove 60% future win probability or produce automatic qualifying stocks.

## Review focus

- Server returns fewer dates, mixed-width NAVER rows, duplicates, or malformed payload: show coverage or explicit failure; never invent bars.
- Halted bars or inconsistent OHLC: preserve source numbers and quality flags; do not treat zero-volume bars as executable.
- Existing cache is interrupted, mismatched, or corrupted: validate identity/hash and resume only completed valid requests.
- A historical DART response contains later amendments or missing quarters: retain the exact receipt, period and capture; keep vintage unverified.
- Parquet schema and units differ by year: require expected fields, valid symbols, and the observed `Close * Stocks` relationship before labeling KRW.

## Task 1: Fixed-cohort long daily price snapshots

**Files:** `scripts/collect_large_cap_price_history.py`, `tests/scripts/test_collect_large_cap_price_history.py`.

**Interfaces:** CLI accepts `--universe-report`, `--start`, `--end`, `--out`, explicit fetch, and bounded worker/retry settings; outputs raw snapshots, scoped OHLCV CSV, and coverage/quality JSON.

- [x] Write failing tests for fixed TOP100 scope, mixed 6/7-column literals, date/type/duplicate validation, zero-volume/invalid OHLC flags, bounded response errors, hash-checked resume, and unverified adjustment metadata.
- [x] Run the focused test and inspect the expected RED failure.
- [x] Implement the minimum collector using the date-range NAVER endpoint verified by source probes.
- [x] Pass focused tests; fetch the frozen TOP100 from 2005-01-01 through 2026-10-02. Preserve raw data and per-symbol failures.

## Task 2: Dated market-cap snapshots

**Files:** `scripts/collect_large_cap_market_caps.py`, `tests/scripts/test_collect_large_cap_market_caps.py`.

**Interfaces:** CLI reads the fixed cohort and explicit year range; downloads only annual FinanceData/marcap Parquet files; emits scoped daily market caps with source manifests and unit checks.

- [x] Write failing tests for cohort bounds, required fields, `Marcap ≈ Close * Stocks`, unknown units, schema variations, bounded download, and cache identity/hash validation.
- [x] Verify RED, implement, and pass focused tests.
- [x] Reuse the acquired 2015/2020/2026 snapshots, then collect missing years through 2026 within 400 MB total and three workers.
- [x] Check date coverage and units per year; label source rank as including potentially excluded share classes, not the established common-stock quality cohort rank.

## Task 3: Historical disclosed fundamentals and original-source proof

**Files:** `scripts/collect_large_cap_dart_history.py`, `tests/scripts/test_collect_large_cap_dart_history.py`.

**Interfaces:** CLI takes the fixed cohort, corpus-code mapping, same-project env path, dates, explicit fetch, output path, and call budget; emits raw batch envelopes, scoped financial records, completeness/period/receipt metadata, and original receipt ZIP proof.

- [x] Write failing tests for 46 report periods, TOP100-only scope, missing `013` periods, period identity, cumulative income, immutable capture/hash resume, safe secret-free failures, and a bounded call budget.
- [x] Verify RED, implement, and pass focused tests.
- [x] Fetch at most 92 sequential multi-company batches for 2015–2025 and 2026 Q1/H1, reusing complete snapshots after interruptions.
- [x] Fetch at most four original/XBRL proof files for already identified 2015 annual receipts; validate archive integrity without claiming extracted numeric/vintage validation.
- [x] Keep `historical_vintage_verified=false` for current historical API records; receipt date + one calendar day is an availability candidate, not original-filing proof.

## Task 4: Review, durable acquisition guide, and verification

**Files:** `docs/kelly_historical_data_acquisition.md`, optional research dependency specification.

- [x] Review collectors for source contracts, scope, failures, cache integrity, and unresolved claims.
- [x] Run collector tests and the existing Kelly/large-cap/signal-contract suites. Inspect exact failures before repairs.
- [x] Confirm actual rows, dates, selected code counts, financial missingness, and source hashes in generated artifacts.
- [x] Document reproducible commands, the observed 800-day constraint resolution, and the remaining original filing/adjustment/survivorship checks.
- [x] Commit only deliberate source/tests/docs once required checks pass; do not push or deploy.

## Final verification

- Python repository suite: 3,279 passed, 4 skipped, no failures/errors; final process exit 0. JUnit: `data/kelly_research/verification/specialized-full-retry.xml`.
- Initial full-suite process ended with Windows native exception `0xc000001d` during OpenAI/Pydantic schema import. Cause was not established; fresh full retry passed without changing code or dependencies for this event.
- Compileall and whitespace checks passed. Independent reviews resolved CIO statistical/sizing/replay, complete persisted execution chain and old-date duplicate snapshot defects.
- Actual CLI synthetic/replay/daily-duplicate and acquired-data held proofs: `data/kelly_research/trading_agents/verification/final_runtime_verification.json`. Real-data source flags remain unverified.
- Commit includes source/tests/docs only. Generated data, secrets and operating deployment are excluded.
