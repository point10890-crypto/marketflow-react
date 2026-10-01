# Historical chart analogue forecast implementation plan

> For agentic workers: use test-driven development and focused ownership in the existing managed worktree.

**Goal:** Ship a usable independent chart-analogue forecast for AI Brain members, with shadow evidence in candidate detection and reproducible data provenance.

**Architecture:** An offline index builder processes local market prices; API requests read the prepared index and calculate deterministic historical analogue distributions. A member page shows actual data, historical neighbours and forecast bands. Scanner candidates receive shadow evidence without changing live ranking before comparative validation.

**Tech stack:** Existing Flask, NumPy/requests, React/TypeScript and SVG; no AlphaSquare scraping, paid subscription, JEV key or added LLM calls. A separate bounded NAVER completed-bar collector prepares supplier-adjusted snapshots; HTTP prediction requests remain offline.

## Constraints and contract

- Input: KR six-digit symbol, explicit UTC decision cutoff where supplied; default current time.
- Default analysis252 observed daily sessions; historical outcomes5/20/40 sessions. No future labels or captured data after cutoff. Deduplicate sessions, reject intraday rows, unknown captures, severe raw-price discontinuities and overlapping same-symbol neighbours.
- Output: symbol/target, status, mode=shadow, model_version, as_of, lookback_sessions, source metadata, diagnostics, sample_count, history[{date,close}], horizons[{sessions,median_return_pct,p10_return_pct,p90_return_pct,up_frequency_pct,median_price,lower_price,upper_price}], fan[{session,median_price,p10_price,p90_price}], neighbours[{symbol,target,start_date,end_date,similarity,returns}], warnings.
- Insufficient or stale data is visible; never fabricate probabilities or claim calibrated accuracy. Raw corporate-action uncertainty is disclosed. No performance guarantee or direct trading/order path.
- GET /api/admin/mirofish/chart-analogue/<symbol> allows admins and active AI Brain members; status is cheap, offline builder separate. Route calls no external vendor.
- Member URL /dashboard/ai-bain/chart-predict?code=003690; access through AI Brain navigation. Existing navigation and subscription gates preserved.
- Routine refreshed index runs as a dedicated scoped production task; keep generated data and secrets out of Git.
- Real-source validation found the regular14:50 CSV is intraday, leaving its most recent valid close at2026-09-10. Preserve the original source and use an independent post-close supplier-adjusted snapshot, with actual capture timestamps and partial-failure preservation. Do not relax the cutoff to hide stale data.
- Sampling must use a fixed calendar anchor so duplicate or cutoff-future records cannot change historical selection simply by changing a raw-row-dependent stride.

## Tasks and validation

- [x] Engine owner: first failing numerical/cutoff/data-quality tests, independent chart_analogue.py + offline CLI. Atomic writes, no pickle or arbitrary paths from API, bounded work and memory cache.
- [x] Scanner owner: first failing integration tests; add shadow evidence to bounded candidate pool before TOP3 selection, preserve scores/order and fail open on missing index; artifact registration with replay metadata.
- [x] Frontend owner: typed client and member page, fixed-size responsive SVG fan chart, explicit samples/horizons/source states, navigation and meaningful behaviour tests.
- [x] Root: protected API tests/routes, runtime install/refresh job, data audit, full focused backend checks, full Vitest/build, independent review.
- [ ] Commit only intentional sources after tests; push main without overwriting others. Install/build index on MiniPC, restart5003 Flask, deploy frontend and validate health, access controls and live UI with actual prediction data.
- [ ] Preserve deterministic validation examples and report what ran; efficacy versus baseline remains shadow until prospective outcomes mature.

## Pre-deployment evidence

- Focused backend:66 passed; full backend suite completed with exit0. Frontend:51 test files/313 tests passed, lint and TypeScript/Vite/prerender build passed.
- Independent review resolved capture provenance, source failure preservation, bounded streaming and stable sampling issues; no important blockers remained.
- Actual source refresh:2896/2896 symbols succeeded,2209880 completed-bar records, latest session2026-10-01; independent index contains134500 historical windows.
- Actual003690/005930/000660 results each returned20 neighbours; independent numeric, cutoff, deterministic repeat and unchanged scanner-score checks passed. Runtime reports remain ignored generated artifacts.
