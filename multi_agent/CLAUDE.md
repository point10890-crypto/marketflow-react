# MarketFlow Multi-Agent Orchestration

This folder contains coordination rules for multi-agent stock-analysis work.
The target repository is `C:/bitman_marketfloww`.

## Mission

MarketFlow's agent work exists to improve alpha candidate detection:

- find better Top 3 candidates across the market
- filter weak or risky candidates earlier
- improve timing, horizon, evidence quality, and replayability
- feed outcome data back into the scanner without look-ahead bias

MCP, Hermes, GraphRAG, LLM summaries, and UI tools are support systems. They are
not the objective by themselves.

## Roles

- `codex-main`: implementation, tests, repository-safe operations, MiniPC deploy
  when explicitly requested.
- `codex-critic`: code review, failure-mode search, data leakage checks,
  look-ahead bias checks, and endpoint contract review.
- `gemini-research`: external research synthesis, prompt alternatives, and
  strategy critique. Research output must be translated into deterministic
  implementation requirements before coding.
- `operator`: human approval for external installs, Telegram sends, production
  mutations, account/order actions, or secret handling.

## Default Workflow

```text
scope -> route -> brief -> implement -> focused test -> critique -> fix -> verify -> report
```

For MarketFlow production changes, preserve member data, secrets, generated
artifacts, MiniPC runtime config, and unrelated dirty worktree files.

## Target Repo

```yaml
target_repo: C:/bitman_marketfloww
runtime:
  api: flask_app.py on 5001
  frontend: frontend-react
  mcp: mirofish_mcp_server.py
  minipc: dynas@192.168.55.103:C:/bitman_marketfloww
```

## Hard Limits

- Do not execute broker orders.
- Do not read, print, copy, or commit secrets.
- Do not let news/social/search interest become a standalone buy signal.
- Do not mutate production or send Telegram messages without explicit operator
  approval and the existing MarketFlow mutation gates.
- Do not stage generated data unless explicitly requested.
