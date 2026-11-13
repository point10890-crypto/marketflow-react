# Kongming verification continuity — 2026-11-13

## Scope and contracts
- Repair missing newly listed issuer mapping using bounded official OpenDART corpCode refresh, isolated verified cache, cooldown and lock. Keep exact issuer identity validation and old good cache on error.
- Diagnose actual daily AI spend/calls with a read-only aggregate. Preserve $1/100 ceilings, TOP3 reserved capacity and all charged/uncertain request records.
- Continue saved-evidence rule checks when optional AI interpretation is held; label the difference clearly. Resume only unfinished interpretation with durable deduplication and explicit next retry. Avoid repeated charges for unchanged facts.
- Do not modify user accounts, real orders, credentials, shared global issuer maps or unrelated worktrees. Never claim a filing/news item is confirmed without source evidence.

## Implementation sequence
1. Record production causes and immutable baseline; inspect ledger aggregates only.
2. DART worker: regression tests, official mapping cache implementation, focused tests.
3. Budget worker: read-only daily availability and specific hold reason, focused tests.
4. Parent: tests for zero-cost continuation and budget-reset recovery, minimal service/API/UI update; retain old successful receipts.
5. Freeze source; focused Python checks, affected frontend tests/build, independent review; then commit/push/PR CI.
6. Deploy committed main to MiniPC and frontend if changed. Verify health, official issuer identity, no key leakage, current APIs, displayed statuses and natural scheduler cycles.

## Completion evidence
- Regression tests pass for absent/new code, bad/oversized source, failed refresh preserving cache, budget cap, no-charge hold, uncertain/charged fence, changed evidence and previous successful receipts.
- Production task cycles complete with timestamps; 동원파츠 no longer fails issuer mapping; budget-limited interpretation exposes rule-based checks and scheduled retry without raising the budget.
- Report facts independently from outcomes: no matching filing is not proof that a news claim is false, and rule checks are not AI interpretation or a buy signal.
