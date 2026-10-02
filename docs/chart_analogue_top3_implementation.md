# Chart analogue automatic TOP3

Requested outcome: return three automatically selected Korean chart-analogue
candidates, with an accessible explanation and one-click individual analysis.
This independent research shortlist does not replace existing AI Brain ranks.

## Selection contract

- Inspect every symbol in one pinned adjusted-close index at one explicit cutoff.
- Keep the existing 252-session inputs and historical capture/overlap checks.
- Rank the 20-session horizon only. Require 20 samples, at least 5 distinct
  historical symbols, median similarity >= 0.8 and the newest corpus session.
- Reject target collection fallback, old observations, non-finite numbers,
  low upward frequency (<60%) and adverse 10th-percentile returns (<-12%).
- Score = median return - 0.33 percentage points assumed roundtrip costs
  - 0.5 × absolute negative 10th-percentile return. Require score > 0.
- Sort by descending score, descending upward frequency, ascending symbol.
  Return up to three; never fill missing slots with rejected candidates.

These fixed research thresholds have not been validated as an optimal trading
strategy. Similarity and sample upward frequency are not calibrated success
probabilities. This source has no volume/flow/disclosure/liquidity screens and
its indexed universe is not guaranteed to cover the entire exchange.

## Operations

- `GET /api/admin/mirofish/chart-analogue/top3`: cheap saved result/progress.
- `POST` to the same path: immediate asynchronous start or reuse of current
  results. Admin or explicit AI Brain subscription required; private/no-store.
- File lock excludes duplicate API and nightly scans across processes.
  The offline nightly stage waits for active API work and rechecks the newest
  source after acquiring the lock, so an older in-flight scan cannot cause it
  to silently skip a newly built index.
- Persist progress and atomic latest reports. Interrupted jobs become retryable
  errors. Immutable runs retain full eligible ranking and selected forecasts.
- Daily refresh invokes the local scan after price/index preparation. It needs
  no external model, new API key, paid inference or automatic orders.
- One 45-minute scan ceiling; incomplete scans cannot publish a TOP3 result.

## Verification

Focused tests exercise exact ranking and tie breaks, missing/stale/cache inputs,
future capture rejection, incomplete scans, JSON finiteness, source pinning,
real synthetic engine returns, locks and restart recovery. Route tests cover
authorization, invalid requests, no-store and safe errors. Frontend tests cover
running-to-result polling, partial results, malformed results and retry.

Before deployment: run related Python regressions and the full frontend suite,
lint and build. Run the real prepared universe, inspect selected forecasts and
source coverage. After commit/push: pull on the MiniPC, restart only the guarded
Flask task, verify health and protected endpoints, deploy frontend and verify
the actual authenticated screen and mobile layout.

Pre-deployment verification on 2026-10-02:

- Full Python regression: 2,823 passed, 4 skipped. Final TOP3 focused service,
  route and CLI checks: 90 passed, including scheduler waiting/cache reuse.
- Frontend: 399 passed; ESLint, TypeScript, Vite and prerender passed.
- Prepared provider-adjusted 2026-10-01 corpus: all 2,896 symbols inspected,
  41 eligible, three selected. First local scan took 71.235 seconds.
- Existing manual-loop tests were isolated from host browser cleanup after
  their one-second progress wait proved sensitive to real OS cleanup latency.
  Production manual-loop code was not changed.

These checks establish functioning selection and delivery, not forward return
superiority. Selected forecasts and their cutoff are retained for later replay.
