# AI Brain Dashboard Redesign Harness - 2026-06-06

## Objective

Improve `/dashboard/ai-bain` so the page serves the alpha objective first:
detect, review, and validate the most profitable Top 3 stock candidates.

MCP automation, GraphRAG, Hermes, and chat panels are supporting systems. They
must not make the subscriber dashboard harder to scan.

## Team Split

- Frontend: simplify the AI Brain subscriber console, reduce admin-only surface,
  move analysis input into the first viewport, and keep Top 3 / scanner /
  outcome information prominent.
- Backend/API: keep existing endpoints stable. Only add or modify API behavior
  if the UI cannot truthfully show source freshness, runtime status, or Top 3
  evidence from existing payloads.
- QA/Ops: run focused frontend tests, build, browser smoke, then MiniPC deploy
  and health checks after green verification.

## Rules

1. Preserve admin functionality under `/admin/endpoints`.
2. Subscriber mode must hide operator-only controls such as forced automation and
   autonomous MCP maintenance panels.
3. The first viewport must answer: "Is scanner data fresh?", "Can I run or
   review Top 3?", and "Which target can I analyze now?"
4. Do not fabricate metrics. All numbers must come from current API state or
   deterministic UI derivation.
5. Keep changes scoped to AI Brain dashboard UX unless a route/API defect is
   discovered during testing.

## Verification Loop

1. `npm run test -- adminEndpointsEnter.test.tsx`
2. `npm run build`
3. Browser smoke check for `/dashboard/ai-bain`
4. Commit/push/deploy/MiniPC verification after green checks

