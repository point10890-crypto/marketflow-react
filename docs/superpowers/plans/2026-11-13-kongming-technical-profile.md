# Kongming 20-session technical agent

> Implementation follows the existing authorized end-to-end workflow; no renewed approval gate. Parallel ownership: deterministic engine/provider, UI, and orchestration/routes.

**Goal:** Add a separate, automatically refreshed technical agent to Kongming that estimates 20 completed trading sessions of volume by price and shows support/resistance candidates with shares, traded value and percentage.

**Design:** Use KIS KRX raw daily OHLCV and traded value, not an LLM. Obtain the last 20 actual KOSPI trading-session dates through the 20:30 KST acquisition cutoff; require the stock's matching 20 dates. Uniformly allocate each daily bar's volume and turnover across its low/high overlap with 24 price bins; a flat-price window has one bin. Preserve both totals. Select POC, strongest occupied bin wholly below/above the latest completed close, and the current-price bin. No level is invented when absent. These are estimated historical traded volumes, not remaining holdings or order-book liquidity.

**Tech stack:** Existing Flask, atomic JSON + FileLock, KIS shared read-only transport, React/TypeScript/Tailwind. No new paid API/LLM dependency or order execution.

## Contract

GET `/api/admin/mirofish/kongming/technical-profiles` (optional `symbol`, six uppercase alphanumeric characters) reads saved state only. POST same path accepts only `{symbol}` and queues a bounded asynchronous lookup. Admin or active Kongming entitlement required; no arbitrary refresh/provider arguments. Public projection is explicit and tested.

View: `schema_version:1, agent:'volume_profile_20d_v1', status, last_run_at, items:Profile[]`.
Profile: `symbol,name,status,reason,as_of,fetched_at,window_start,window_end,sessions_required:20,sessions_used,reference_price,total_volume,total_traded_value,poc,support,resistance,current_zone,bins,method,source,calendar_source,price_basis,limitations,fingerprint`.
Zone: `index,low,high,volume,volume_pct,traded_value`. Nullable numeric/zone fields for pending, unavailable or insufficient history; no fabricated zero-levels. Profile statuses: `ready,pending,insufficient_history,source_unavailable,price_event_review,stale`.

## Files / tasks

- [x] Engine/provider: `app/services/mirofish/kongming_technical/{__init__,profile,provider}.py`; `tests/test_kongming_technical_{profile,provider}.py`. Interfaces: `build_profile(symbol, name, bars, sessions, *, fetched_at, source, calendar_source) -> dict`; `TechnicalProvider.fetch_sessions(now) -> {sessions,source,captured_at,through}`; `fetch_history(symbol,sessions,now) -> {bars,name,source,fetched_at}`. Shared `ProfileError.code`; provider validates identity, dates, finite OHLCV, raw price basis and flags. `completed_through(now) -> YYYY-MM-DD`.
- [x] Store/worker: `app/services/mirofish/kongming_technical/service.py`, own minute scheduled task/CLI/installer. Discover deduplicated recent article symbols; explicit queue priority; at most three due symbols/tick and one session-index request per acquisition day. Atomic stage receipts, failure cooldown, shared worker lock, preserve prior successful profile on refresh failure but mark stale. GET never performs provider I/O. Add route, entitlement and public allowlist tests.
- [x] UI: typed parser/client and `KongmingTechnicalPanel.tsx` in existing page, selected symbol/name search, recent candidate shortcuts, mobile stacked level cards and readable horizontal bars. Reference completed close/date and method limitation always visible. Poll saved status only while visible; do not auto-queue on timer. No changes to TOP3 verdicts or paid interpretation fingerprints.
- [ ] Integration: focused tests first, existing route/CLI/membership/UI regressions, full frontend lint/test/build and CI. Commit only intended files. Deploy under persistent user authorization and verify real KIS data, API permissions/projection, natural scheduled refresh and PC/mobile display.

## Failure/review cases

1. New/alphanumeric symbol with fewer than 20 official sessions: insufficient history, no invented support.
2. Split/rights/provider price event inside window: withhold blended price levels; preserve raw evidence for review.
3. Wrong identity, future/duplicate/conflicting bars, NaN/negative volume: reject and retain prior successful record as stale.
4. Sparse or zero volume, flat bars, reference at bin boundary: conserve totals and return null absent levels.
5. Incomplete today, cached pre-cutoff bars, worker crash/overlapping runs, queued lookup flood: bounded fetching, persisted cooldown/dedup, no request-path network.

## Sources

- KIS official contract: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py (J/D/1, maximum100 daily rows).
- Volume-profile concepts: https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/ . TradingView uses lower timeframe bars; our daily uniform model is explicitly a coarser estimate, not equivalence to its implementation.
