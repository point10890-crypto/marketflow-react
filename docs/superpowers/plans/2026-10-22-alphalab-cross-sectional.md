# AlphaLab cross-sectional desk implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Preserve completed tasks and recover only failed stages.

**Goal:** Deliver source-defined, cost-checked conditional stock proposals with explicit reasons and production evidence.

**Architecture:** Separate KIS daily snapshots, pure pooled detector and candidate-desk service/store. Compose unchanged v2 via new entry-point wrapper; add a strict mobile panel.

**Tech Stack:** Existing Python/Flask/filelock/atomic JSON, React/TypeScript/Vitest/Vite, Windows Task Scheduler.

**Spec:** `docs/superpowers/specs/2026-10-22-alphalab-cross-sectional-design.md`

## Global constraints

- Do not edit any `detection_v2_store._CODE_FILES`; zero approved exposure/live orders false.
- No secret output, unrelated edits, NAVER/KIS joins, fake candidates or outcome-driven parameter search.
- Current research window is retrospective; preserve exact source/decision/terminal evidence.

## Review focus

- A symbol/page/source change must invalidate only dependent new work, never old decisions.
- Correlated peers and labels crossing the chronological boundary cannot inflate evidence.
- Overnight acquisition must not backdate the decision or simulate an already passed opening.
- Failed/stale/corrupt saved desk must not expose an actionable retained buy.
- Mobile rendering and authenticated production payload must match the tested release.

### Task1: KIS source collection (source worker)

Files: new `daily_source.py`, `candidate_inputs.py`, focused tests. Interface: `collect_inputs(root, symbols, *, latest_session, scope_hash, names, provider=None, now=None)` and `load_inputs(root)` return `{prices_by_symbol,names,latest_session,input_fingerprint,provenance,capture_audit}`. Provider `fetch_history(symbol, end_session, *, count=756)` returns validated bars+source/capture metadata.

- [ ] Add failing tests for backward pages, conflicting duplicate, malformed OHLCV/identity, bounded failure and partial resume/hash tampering.
- [ ] Implement fixed KIS J/D/0 request, isolated immutable snapshots and atomic pointer. Run focused tests.

### Task2: Pure pooled detector (engine worker)

Files: new `candidate_detection.py`, focused tests. Interface: `discover_candidates(prices_by_symbol, *, names=None, as_of=None)` returns `{policy_version,latest_session,inspected_count,eligible_count,candidates,funnel,evidence,audit}`. Candidate fields: `symbol,name,rank,strength_score,quote_session,reason_facts,plan,risk`; plan `entry_price,entry_upper,stop_price,target_price,horizon_sessions,loss_fraction`; risk `reference_weight,kelly_fraction,approved_exposure,live_orders`.

- [ ] Freeze fixed policy/spec before any new real-data outcome run.
- [ ] Add failing future-peer mutation, cutoff/embargo, correlated block coverage, losses/no-padding and causal plan tests.
- [ ] Implement exact fixed setup/ranking and chronological pooled evidence, reuse pure frozen execution helpers without editing them. Run focused tests.

### Task3: Service, immutable evidence, API/scheduling (root)

Files: new `candidate_service.py`, `candidate_store.py`; change route/CLI dispatch only outside frozen files; tests.

- [ ] Add failing tests for first-decision/terminal preservation, source correction quarantine, no backdated next-open, failed refresh and saved-only reads.
- [ ] Implement wrapper and strict sanitized candidate_desk contract with source/protocol identity, creation/expiry, forward stage and new-event dedupe.
- [ ] Wire scheduled research/monitor/Telegram to new desk without replaying old events. Test bounded failures and legacy hash preservation.

### Task4: Mobile candidate view (frontend worker)

Files: new validator/panel/tests; change `alphaLabApi.ts` and `AlphaLabPanel.tsx` only for additive candidate_desk. New contract supplied by root before implementation.

- [ ] Add failing validator, stale/corrupt suppression, empty/funnel and one/two/three candidate view tests.
- [ ] Build readable single-column cards with selection facts/price plan/source/weight, preserve navigation and collapse legacy diagnostics. Run Vitest/build.

### Task5: Whole-system verification and deployment (root + independent reviewer)

- [ ] Acquire real project-owned KIS input, run frozen new hypothesis once, record exact actual candidates and limitations; no repeat optimization.
- [ ] Run focused then full Python/frontend suites/build, branch review and CI. Verify old hashes unchanged.
- [ ] Commit/push/merge tested source; update MiniPC exact merged commit through current5003 watchdog contract, frontend npm deploy.
- [ ] Verify local/public health, scheduled task state, saved actual API, source/decision binding, authenticated390px/desktop UI and current assets. Record remaining uncertainty honestly.
