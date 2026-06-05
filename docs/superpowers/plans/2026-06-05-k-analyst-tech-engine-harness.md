# K-Analyst Tech Engine Harness - 2026-06-05

## Objective

Implement K-Analyst Pro inspired analysis endpoints for MarketFlow MiroFish without turning MCP automation into the product objective. The endpoints must improve Top3 alpha candidate detection by adding deterministic data quality, technical readiness, Bayesian probability, crisis/HALT, and price strategy signals.

## Scope

- Add isolated MiroFish service code for K-Analyst style analysis packets.
- Add Flask endpoints under `/api/admin/mirofish`.
- Keep existing scanner/workflow code intact unless direct integration is necessary.
- Add focused tests proving no fabrication, confidence caps, HALT behavior, and endpoint contracts.

## Non-Goals

- No live broker order execution.
- No fabricated fallback prices, flow, or fundamentals.
- No standalone buy signal from news/social/theme evidence.
- No Spring Boot or port 8080 work.
- No generated data or secret files in git.

## Implementation Rules

1. Evidence before opinion: every verdict must expose evidence and missing data.
2. Price readiness gates pricing: `INSUFFICIENT` data cannot produce entry/target/stop.
3. Bayesian outputs must sum to 100 percent.
4. Crisis/HALT overrides bullish technical or flow signals.
5. Source grade and freshness must affect confidence.
6. Output language must be probabilistic and avoid certainty claims.
7. Endpoints must be read-only or artifact-safe; no destructive operations.

## Verification Gates

- Python compileall for new and touched files.
- Focused pytest for K-Analyst service and route contracts.
- Existing MiroFish scanner/workflow smoke tests if route exports change.
- MiniPC deploy only after local tests pass.
- MiniPC verification: git HEAD, Flask `/healthz`, Flask `/api/health`, public `marketflow-api.bit-man.net`, and route import check.

## Commit Rules

- Stage only files intentionally changed for this harness.
- Do not stage generated `data/`, logs, cache, `.env`, token, or unrelated dirty files.
- Report any pre-existing dirty worktree state separately.
