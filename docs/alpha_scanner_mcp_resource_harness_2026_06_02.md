# Alpha Scanner MCP Resource Harness - 2026-06-02

## Objective

Strengthen MiroFish alpha candidate detection by adding a clean MCP resource
catalog and source-gap evaluation layer. MCP integration is a support layer, not
the product goal. A resource is useful only if it improves candidate discovery,
risk filtering, evidence quality, timing, or replayable outcome learning.

## Team Roles

- Alpha Lead: keep every change tied to Top 3 stock detection quality.
- Backend Lead: keep the implementation modular under `app/services/mirofish/`.
- Security Lead: keep all external resource metadata read-only and redacted.
- QA Lead: add focused tests before broad checks.
- Ops Lead: avoid MiniPC, scheduler, production data, and secrets unless deploy
  is explicitly requested.

## Harness Rules

1. Do not hard-code external MCP calls directly into scanner scoring.
2. Add a small registry/evaluation layer that the scanner, workflow, UI, and MCP
   server can consume later.
3. Mark every resource with alpha value, required evidence role, data grade,
   risk controls, and adoption phase.
4. Treat social/news/search resources as secondary evidence only.
5. Keep mutating or trading/order capabilities disabled from this catalog.
6. Do not read, print, or commit API keys or token files.
7. Do not touch unrelated dirty files.
8. Focused tests must pass before claiming completion.

## Implementation Boundary

This change may add:

- `app/services/mirofish/mcp_resource_catalog.py`
- read-only Flask endpoints under `/api/admin/mirofish/mcp/resources`
- read-only MCP tools/resources exposing the same catalog
- focused tests for catalog scoring, source-gap evaluation, and endpoint output

This change must not add:

- direct order/trading endpoints
- new external network calls in the scanner
- frontend-only fake status
- MiniPC deployment or scheduler changes without explicit request

## Acceptance Criteria

- The catalog ranks KIS, Korea Stock/KRX-DART, and Alpha Vantage as the primary
  alpha-relevant MCP candidates.
- The latest scanner/workflow source gap can be summarized without failing when
  no run exists.
- Resource output is deterministic, redacted, and JSON serializable.
- Focused unit tests pass.
