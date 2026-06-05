# Hermes Sidecar Harness - 2026-06-05

## Objective

Attach NousResearch Hermes Agent as a safe sidecar around the existing MiroFish MCP control-plane. Hermes must improve automation, memory, scheduled checks, and operator review. It must not replace the alpha scanner, scoring engine, GraphRAG workflow, risk filters, or outcome feedback logic.

## Harness Rules

1. Keep alpha detection first: candidate quality, risk filtering, Top 3 ranking, and replayable outcomes matter more than generic agent features.
2. Do not vendor the Hermes repository into MarketFlow.
3. Expose a small MCP whitelist for Hermes. Default to read-only tools.
4. Mutation tools stay guarded by environment flag, API key, and confirmation phrase.
5. No broker order execution, secret reading, destructive file work, or generated artifact staging.
6. Telegram send and workflow mutation are operational actions and require explicit gates.
7. Every final Top 3 item must identify name, symbol, market, evidence freshness, missing data, and confidence.

## Implementation Plan

1. Add `app.services.mirofish.hermes_bridge` with status, manifest, runbook, prompt pack, and dry-run preview contracts.
2. Add `/api/admin/mirofish/hermes/*` endpoints as a separate Blueprint to avoid modifying the already large `admin_mirofish.py`.
3. Register the Blueprint in the central route registry.
4. Expose Hermes manifest/runbook through the existing MiroFish FastMCP server.
5. Add focused unit tests for the service contract and route registration.

## Verification

- Compile the new service and route files.
- Run focused pytest for Hermes bridge and route registration.
- Run the MiroFish signal contract smoke baseline if the focused checks pass.

## Deployment Note

This change prepares MarketFlow for Hermes. It does not install Hermes, start a Hermes daemon, or enable mutations on the MiniPC. Those are separate operator steps after this contract is reviewed.
