# Routing Rules

Use the smallest useful team. Route by task type:

| Task type | Primary | Review | Notes |
|---|---|---|---|
| Alpha scanner scoring, filters, Top 3 ranking | codex-main | codex-critic | Require deterministic data and tests. |
| GraphRAG / MCP endpoint design | codex-main | codex-critic | Keep endpoints replayable and source-graded. |
| External research, papers, GitHub resources | gemini-research | codex-critic | Convert findings into implementable contracts. |
| MiniPC deploy / scheduler / Telegram | codex-main | operator | Production mutation requires explicit request. |
| Prompt/system-message tuning | codex-main | gemini-research | Prompts must not invent numbers or hype signals. |
| UI/UX for admin or scanner dashboards | codex-main | codex-critic | Dense operational UI, no marketing layout. |

## Escalation

Ask the operator before:

- installing Hermes or any external toolchain
- sending Telegram
- changing `.env`, token caches, scheduled tasks, or production secrets
- migrating databases or member/subscription records
- enabling mutating MCP tools
