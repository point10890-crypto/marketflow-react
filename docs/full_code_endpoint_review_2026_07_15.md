# MarketFlow Full Code and Endpoint Review — 2026-07-15

## Executive result

- Flask route inventory: 324 route rules; no duplicate route signatures found.
- Production read-only smoke: health, KR/US/Crypto, briefing, VCP, closing-bet V2,
  Wave, community, stock search/manual analysis, and MiroFish/AI Brain status
  endpoints all returned HTTP 200 from the MiniPC authenticated context.
- Python final regression: 528 tests passed.
- Frontend: 26 tests passed; production TypeScript/Vite build passed.
- Frontend lint: ESLint 9 flat configuration restored; lint passed with zero warnings.
- Full npm dependency audit (production and development tooling): 0 vulnerabilities.
- This review batch is implemented and tested locally. It has not been committed,
  pushed, or deployed as part of this review.

## Production smoke observations

The audit was read-only. It generated the admin token inside the MiniPC process
and did not print the token or any secret.

| Area | Result | Observed latency / note |
| --- | --- | --- |
| healthz / api health | 200 | 6 ms / 44 ms on MiniPC loopback |
| KR signals / closing-bet / VCP | 200 | 948 ms / 21 ms / 24 ms |
| Briefing latest/morning/closing | 200 | 14–21 ms |
| US portfolio | 200 | 2.145 s; external-data path remains relatively slow |
| Crypto overview | 200 | 2.214 s; external-data path remains relatively slow |
| Wave latest | 200 | 72 ms; response about 236 KB |
| Community boards | 200 | 29 ms on current production state |
| Stock search / manual runs | 200 | 211 ms / 938 ms |
| AI Brain overview | 200 | 9.38–10.00 s before the local fix |
| MiroFish workflow status | 200 | about 231 KB response |
| MiroFish autonomous status | 200 | 3.714 s, about 248 KB response |

The AI Brain overview delay was reproduced twice. The local implementation now
uses persisted read-only learning summaries instead of rebuilding and writing
the complete agent observation on every GET. Local latency fell from about 6.7
seconds to 0.008 seconds with the same workspace data.

## P0 — completed

1. **Bearer token forgery prevention**
   - Removed repository-known `SECRET_KEY` fallbacks.
   - Missing production configuration now uses a process-local random key and
     emits a critical warning rather than accepting forgeable signatures.
   - Local helper scripts refuse to mint a token without the configured key.

2. **Windows path traversal prevention**
   - Strict run-id validation and resolved-parent checks for manual stock runs.
   - Strict date/ticker validation before KR history and stock-analysis paths are
     combined with filesystem cache paths.

3. **Production dependency vulnerabilities**
   - Updated DOMPurify, React Router, markdown-it, linkify-it, Vite, Wrangler,
     and affected build-tool dependency chains. Full `npm audit` now reports
     zero vulnerabilities.
   - Migrated the existing chunk split to the Vite 8 compatible function form;
     the production build remains green.

4. **Unauthenticated external-data workload**
   - Protected common portfolio, stock, realtime-price, and market-index APIs
     with Pro access.
   - Realtime price input is validated, deduplicated, and capped at 50 symbols;
     Yahoo access uses the bounded wrapper.

5. **Misleading closing-bet backtest**
   - Removed the fabricated `+5%/-3%` performance calculation based on the
     signal-day price change.
   - Until forward OHLCV outcomes, entry date, horizon, and costs are available,
     the API returns `Unavailable` with null performance and the UI shows
     `검증 대기` instead of a false 0% or successful backtest.

## P1 — completed

1. **Community timeout and data exposure**
   - `/api/community/boards` now uses SQL `COUNT`/latest aggregation rather than
     materializing every visible post.
   - Added pagination/list limits and eager loading to avoid N+1 queries.
   - Protected inaccessible-board latest-title/count and community-summary data.
   - Added title/content/comment size limits and retry UX.

2. **Upload and request resource controls**
   - Bounded upload reads (`max + 1`), video container signatures, UUID filename
     validation, protected formula references, 1 MiB JSON limit, and 110 MiB
     overall request limit.

3. **Account and administration safety**
   - Suspended/rejected accounts are blocked before admin/tier bypasses.
   - First-admin creation requires an explicit one-time bootstrap secret.
   - Retired the static `X-Admin-Secret` tier-change endpoint.
   - Blocked self/last-admin demotion and self-suspension.
   - Validated trusted proxy IP handling and capped rate-limit maps.

4. **Cache isolation**
   - Credentialed, error, mutation, auth/admin/community/Stripe JSON responses are
     `no-store`; other JSON is browser-private rather than shared-public.

5. **Scheduler and MiniPC lifecycle**
   - Closing-bet V2 preflight now checks imports without constructing providers;
     timeout language no longer falsely reports a source-code bug.
   - Durable daily artifact prevents a restart/catch-up from rerunning V2 and
     resending alerts when the scheduler manifest was not yet recorded.
   - Flask watchdog honors startup grace and targets only the project Flask
     process, avoiding boot-time restart races and unrelated Python processes.
   - Flask task is request-only; expensive in-process alpha/manual auto loops are
     disabled on the MiniPC startup path.

6. **Frontend request lifecycle**
   - Shared auth-aware timeout/Abort helper with typed timeout errors.
   - Prevented overlapping polling and duplicate VCP/manual-analysis requests.
   - Applied bounded requests to auth, stock analysis/search/export, and manual
     analysis endpoints.
   - Added same-origin redirect validation and hardened community HTML/iframes.
   - Restored the previously non-runnable ESLint 9 configuration and removed
     duplicate imports/obsolete disable comments; lint now completes cleanly.

7. **AI Brain read path**
   - Dashboard GET no longer runs the full agent observation or writes edge-map
     artifacts. Missing training data is not rebuilt inside the HTTP request.

## Remaining prioritized work

### P0 — rollout blocker

1. MiniPC verification returned `SECRET_KEY_CONFIGURED=0`. Before restarting
   with the hardened auth code, generate and persist a strong production-only
   `SECRET_KEY`. This necessarily invalidates every existing Bearer token and
   logs users out, so it must be included explicitly in the rollout window.

### P1 — next

1. Add `/readyz` with bounded DB `SELECT 1`, scheduler heartbeat, and critical
   artifact freshness. `/healthz` alone cannot detect a community DB stall.
2. Isolate Yahoo operations in killable subprocesses or enforce transport-level
   deadlines. Cancelling a running thread does not free a stuck worker.
3. Add single-flight and subprocess timeout to `/api/run-analysis`.
4. Move stock-analyzer live Yahoo/Gemini work behind an overall deadline or an
   asynchronous job; cache misses can still occupy a Flask worker too long.
5. Add source time, age, stale/fallback, and confidence fields consistently to
   latest briefing, closing-bet, VCP, and analysis contracts.
6. Reduce MiroFish workflow/autonomous status payloads with explicit summary and
   detail modes; current responses are roughly 231–248 KB.
7. Repair provider configuration: the observed Gemini credential was rejected
   and the OpenAI project did not have access to the configured `gpt-4o` model,
   which can reduce Multi-AI consensus to zero.
8. Replace the Flask development server with a production WSGI host appropriate
   for Windows/MiniPC operation, with bounded workers and graceful restarts.
9. Ensure subscription and AI Brain expiry maintenance has a dedicated
   scheduler task before relying permanently on request-only Flask mode.

### P2 — hardening / maintainability

1. Replace SSE token query parameters with an HttpOnly-cookie or authenticated
   fetch-stream contract to avoid URL/log token leakage.
2. Consolidate Wave/DART and MiroFish card polling through the shared non-overlap
   poller; stage the dashboard's first-load API fan-out.
3. Reduce broad `except Exception` blocks in critical auth, scheduler, and data
   paths and attach structured error codes/metrics.
4. Add route-contract tests for freshness and response-size budgets.

## Deployment boundary

No commit, push, production DB change, frontend deployment, or full backend
deployment was performed by this review batch. The MiniPC audit helper was copied
only to run the read-only authenticated smoke. A production rollout should be a
separate controlled step with a scoped commit, MiniPC pull/restart, `/healthz`
and `/api/health` checks, authenticated endpoint smoke, and frontend build
verification. The persistent production `SECRET_KEY` and expected user logout
must be handled before that restart.
