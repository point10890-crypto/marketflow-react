# Learnings

Append-only notes for MarketFlow agent operations.

## 2026-06-05

- Hermes should be attached as an MCP sidecar, not embedded as the alpha scoring
  engine.
- MarketFlow's Hermes config should use `~/.hermes/config.yaml` with
  `mcp_servers`, not `mcpServers`.
- The first Hermes integration should be read-only and dry-run first.
- Any Top 3 automation must preserve the main objective: profitable candidate
  detection backed by fresh, source-graded, replayable data.
