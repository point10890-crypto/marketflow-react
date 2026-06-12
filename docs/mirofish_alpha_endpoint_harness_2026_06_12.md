# MiroFish Alpha Endpoint Harness - 2026-06-12

## Mission Lock

MiroFish MCP work is valid only when it improves the detection, ranking, risk filtering, replay, or monitoring of high-forward-profit stock candidates. MCP automation is a support layer, not the goal.

## Agent Team Split

| Team | Scope | Guardrail |
|---|---|---|
| Backend evidence team | MCP resource catalog, source readiness, alpha endpoint contracts | Deterministic source metadata only; no LLM-created tickers, prices, or filings |
| Frontend operator team | Admin endpoint visibility and operational health cards | Dense admin UI; show readiness and missing evidence instead of decorative status |
| Subscription workflow team | Duplicate approval and admin notification safety | Idempotent approval path; no repeated Telegram/admin notification for already satisfied renewals |
| Verification team | Focused tests, full frontend test, build, deployment smoke | Tests must pass before commit, push, deploy, and MiniPC restart |

## Harness Rules

1. Scope the alpha objective before edits.
2. Add source-grade, freshness, readiness, and risk-control fields before exposing UI.
3. Keep weak data such as news/social/search attention as secondary evidence only.
4. Treat KIS, DART/KIND, KRX short/credit, macro/FX, and outcome memory as separate evidence gates.
5. Run focused backend and frontend tests before broad tests/build.
6. Stage only intentional source, test, and documentation files.

## Skill Structure Applied

| Skill | Applied Use |
|---|---|
| bitman-ai-agent-workflow | Kept alpha detection as the primary objective and enforced deterministic facts |
| bitman-service-ops | Preserved production/runtime safety and avoided unrelated generated artifacts |

## Implemented Endpoint Blueprint

The implementation adds a read-only alpha endpoint blueprint exposed through Flask and MCP:

- `GET /api/admin/mirofish/mcp/alpha-endpoints`
- MCP tool: `get_alpha_endpoint_blueprint`
- MCP resource: `mirofish://mcp/alpha-endpoints`

The blueprint prioritizes:

1. KR capital-flow confirmation
2. DART/KIND disclosure risk
3. KRX short/credit pressure
4. BOK/FRED macro and FX regime cap
5. Naver/news attention as secondary signal only
6. Outcome-memory similar-case retrieval

## Verification Contract

Required checks for this change set:

- `python -m pytest tests/test_mirofish_mcp_resource_catalog.py -q`
- `python -m pytest tests/test_auth_subscription_workflow.py -q`
- `python -m pytest tests/test_admin_mirofish_alpha_scanner.py -q`
- `python -m pytest tests/test_signal_contract.py -v`
- `npm run test -- adminEndpointsEnter.test.tsx`
- `npm run test`
- `npm run build`

