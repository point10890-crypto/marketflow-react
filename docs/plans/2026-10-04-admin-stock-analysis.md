# Administrator single-stock proposal pipeline

Date: 2026-10-04
Branch: codex/admin-stock-proposals

## Outcome
Administrators search a Korean listed stock by name, initials, or six-digit code, explicitly select it, and run a separate analysis. The page shows the same conditional setup, ATR bracket and quarter-Kelly calculation policy as AlphaLab BUY proposals, including proposed weight and reference entry/stop/target. A stock outside the global BUY3 remains analyzable. Unqualified evidence produces WAIT and zero allocation; available reference prices remain visible.

## Isolation and contract
- Page /admin/stock-analysis under existing AdminGuard; administrator-only navigation.
- All /api/admin/mirofish/stock-analysis search/start/status endpoints enforce admin_required and private no-store, including error responses.
- Exact resolved KR stock identity; no arbitrary file paths, provider options, or global scan options accepted.
- Independent saved jobs/artifacts under data/admin_mirofish/symbol_alpha. No changes to global AlphaLab report, inputs, monitor registries or forward journals.
- Prefer validated canonical price snapshot; otherwise collect only the selected stock with existing source adapters. Record source capture/fingerprint, financial quality, source limitations and closed session.
- Shared discovery/ATR/Kelly code. Preserve a canonical reference session calendar for sparse-history checks. Positive allocation goes through existing proposal evidence/source gates.
- GET only reads saved results. POST starts a bounded deduplicated worker. Failed/running updates never reuse an earlier BUY as current. Repeated identical input does not renew the sealed decision validity.
- schema_version 1, policy_version admin-symbol-alpha-v1 envelope: state, target, generated_at, error, result. Result: candidate with proposal, latest_session, analyzed_at, input_fingerprint, source, quality, stages, warnings and per-strategy diagnostics. Frontend validates identity, finite values, plan geometry, allocation caps, capture and expiry.

## Interface
Dense existing dark admin layout: searchable target first, status and numeric proposal card, then compact evidence/source panels. Four required values remain directly visible for valid plans. Distinguish reference close from next-open recalculation. Reuse accessible IME/keyboard autocomplete with a configurable admin-only candidate loader. Restore saved target from code query; poll running analysis without re-computation. Guard target changes, late responses, unmount and auth changes.

## Execution and validation
1. Focused backend and frontend tests fail before implementation, then pass: admin auth matrix, strict input, arbitrary/outside3 stock, engine parity, sparse sessions, read-only GET, failure retention, source freshness/expiry, unchanged global artifacts, accessible/race-safe UI.
2. Independent security/calculation review; resolve material findings.
3. Relevant Python tests, complete Python suite, frontend tests, lint and production build.
4. Explicit source-only commit/push; CI-green PR merge to main; preserve exact verified source tree.
5. MiniPC pulls main, focused deployment checks, restart MarketFlow-Flask on5003, health verification. Frontend npm run deploy.
6. Deployed admin browser: known BUY parity plus a different stock outside BUY3, name search, saved refresh, numeric values and 390px layout; backend non-admin denial; unchanged global journal hashes. Save proof and report actual limitations.

No broker orders or new paid services are part of this feature.
