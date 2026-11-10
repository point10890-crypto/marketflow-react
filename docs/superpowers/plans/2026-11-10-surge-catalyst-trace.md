# Surge catalyst trace implementation plan

> For agentic workers: use superpowers:subagent-driven-development. Existing user delegation authorizes continuous implementation and review.

Goal: Explain observed surges with attributed, time-aware catalyst evidence.
Architecture: Saved screener -> bounded independent trace worker -> immutable observation + recoverable evidence stages -> read-only member UI.
Tech: Flask/Python, atomic JSON/FileLock, existing OpenDART/Omni, React/TypeScript.
Spec: ../specs/2026-11-10-surge-catalyst-trace-design.md

## Global constraints and review focus

No orders, new paid APIs or modifications to AlphaLab decisions. Preserve original source clocks; unknown is not success. Validate exact issuer, safe URLs, chronological windows, partial failures, stale market inputs and bounded repeated execution.

## Tasks

1. Backend owner: `app/services/surge_trace/` and `tests/test_surge_trace*.py`.
   - [x] Failing tests for price validity, event dedupe, PIT classification, duplicate/negative news, source recovery and no fabricated cause.
   - [x] Implement `service.run_once(root=ROOT, project_root=PROJECT_ROOT, now=None, deadline=None)` and `service.read_view(root=ROOT, now=None)` using the public contract in spec.
   - [x] Isolated source adapters for saved screener, readonly Omni/BusinessPost, bounded Google RSS and OpenDART list. Test transports without real calls.
2. Frontend owner: `SurgeTracePanel.tsx`, `surgeTrace.ts`, frontend tests; integrate before existing article list.
   - [x] Failing rendering/HTTP tests, authenticated polling with no stale prior-user data, search/filter, safe links, missing/failed sources.
   - [x] Existing mobile readable styles; no new design library or hero.
3. Controller: API route/access tests, CLI, independent scheduled task installer, operations documentation.
   - [x] Tests first for no-provider GET, denial cases, empty input and worker exceptions.
   - [ ] Focused tests, frontend tests/build/lint, independent review, CI.
   - [ ] Commit/push/deploy; actual source replay, task and public API, PC/mobile verification; record actual coverage and limitations.
