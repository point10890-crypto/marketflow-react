# AGENTS.md

This file is the repository guide for AI coding agents working on MarketFlow.
Treat it as living operational documentation. User chat instructions always take
precedence over this file.

## Mission

MarketFlow's MiroFish work is not a generic AI research demo. The primary goal is
to use AI stock-analysis tools to detect, rank, validate, and monitor stocks with
the highest forward profit potential.

Every MiroFish change should answer at least one of these questions:

- Does it find better alpha candidates across the market?
- Does it filter bad or risky candidates earlier?
- Does it improve entry timing, horizon, risk, or evidence quality?
- Can the result be replayed or backtested without look-ahead bias?

GraphRAG, agent debate, CIO verdicts, news/social analysis, and UI polish are
support systems for alpha detection. Do not let them become the main objective.

## Operating Architecture

- Main API: Flask app at `flask_app.py`, exposed locally on port `5001`.
- Frontend: React + Vite app in `frontend-react/`, local dev port `5173`.
- MiroFish backend routes: `app/routes/admin_mirofish.py`.
- MiroFish services: `app/services/mirofish/`.
- MiroFish UI: `frontend-react/src/pages/admin/AdminEndpointsPage.tsx`.
- MiroFish API client: `frontend-react/src/lib/mirofishApi.ts`.
- Run artifacts: `data/admin_mirofish/runs/{run_id}/`.
- Spring `backend/` is dead code for MarketFlow operation. Do not run or modify
  Spring Boot unless the user explicitly asks.
- Port `8080` belongs to another project on the MiniPC. Do not use it for
  MarketFlow.

## Harness Workflow

Before coding, route the task:

1. If the request is ambiguous or the alpha objective is unclear, ask a concise
   clarification.
2. If the request is actionable, scope the files and constraints first.
3. Read only relevant context, plus project-wide constraints in this file.
4. Implement the smallest useful change.
5. Run focused checks first.
6. If checks fail, use the exact error output as feedback and loop until green.
7. Only run broad tests/builds after focused checks pass.
8. Report what changed, what was verified, and any remaining risk.

For substantial code work, prefer this loop:

```text
scope -> edit -> focused test -> fix -> broader test/build -> deploy only if asked
```

## Setup Commands

Python:

```powershell
python -m pip install -r requirements.txt
```

Frontend:

```powershell
Set-Location frontend-react
npm ci
```

Start Flask locally:

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe flask_app.py
```

Start frontend locally:

```powershell
Set-Location frontend-react
npm run dev
```

## Testing Commands

Use focused checks for the area you changed.

MiroFish service:

```powershell
python -m pytest tests/test_admin_mirofish_service.py -q
python -m compileall app/services/mirofish/store.py
```

MiroFish/frontend admin page:

```powershell
Set-Location frontend-react
npm run test -- adminEndpointsEnter.test.tsx
```

Full frontend check:

```powershell
Set-Location frontend-react
npm run test
npm run build
```

CI smoke baseline:

```powershell
python -m pytest tests/test_signal_contract.py -v
```

Run deployment only when the user explicitly asks:

```powershell
Set-Location frontend-react
npm run deploy
```

## MiroFish Development Rules

- Alpha detection comes first: scanner, ranking, risk filters, backtests, and
  evidence quality outrank decorative UI.
- Final verdicts must always identify the exact target symbol/name/market.
- Numeric values must come from APIs, files, or deterministic calculations. LLMs
  may interpret numbers but must not invent them.
- Weak signals such as social/news/search interest must not become standalone
  buy signals. Combine them with price, volume, disclosure, flow, and risk data.
- Track source, fetched time, freshness, and confidence for every data source.
- If KIS, OpenDART, KRX, or LLM calls fall back to cached/rule data, show that in
  the UI or run metadata.
- Backtests must avoid look-ahead bias and include the entry date, horizon,
  benchmark, costs/slippage assumptions, and false positives/false negatives.

## Data and Security

- Do not print or commit `.env`, API keys, KIS secrets, token caches, or
  Cloudflare credentials.
- Treat `data/kis_token_cache.json`, `.env`, and local Cloudflare files as
  sensitive.
- Many `data/`, `logs/`, crypto output, cache, and SQLite WAL/SHM files are
  generated artifacts. Do not stage them unless the user explicitly asks.
- The worktree may already be dirty. Do not revert unrelated user changes.
- Stage only files you intentionally changed.

## Frontend Guidelines

- Use React + TypeScript patterns already present in `frontend-react`.
- Keep admin tools dense, operational, and scan-friendly.
- Avoid marketing-style landing-page composition for admin/analysis tools.
- Use stable dimensions for graphs, cards, tables, toolbars, and buttons.
- For UI changes, run Vitest and `npm run build`.
- If the user asks to inspect the UI, use the in-app browser or local server.

## Backend Guidelines

- Prefer existing Flask route/service patterns.
- Keep MiroFish service changes inside `app/services/mirofish/` unless a route or
  shared utility change is necessary.
- Use structured JSON artifacts and typed fields instead of ad hoc text parsing.
- For file writes in services, prefer the repository's atomic write helpers where
  available.
- Keep live external calls optional and testable with mocked data.

## Community Posting Workflow

When the user asks Codex to register, update, or publish a community post or
notice, Codex owns the full posting workflow. Do not stop at a local DB insert or
localhost verification unless the user explicitly says the post is local-only.

- Production community posts must be created against the deployed MarketFlow API:
  `https://marketflow-api.bit-man.net`.
- The deployed frontend URL the user expects to see is
  `https://bit-man.net/dashboard/community/notice` for notices.
- Do not use `https://bit-man.net/api/*` as the production API. That domain is
  the Cloudflare Pages frontend; production API calls go to
  `marketflow-api.bit-man.net`.
- For notices, create the post through the community API, then mark it as a
  notice through the notice endpoint:
  - `POST /api/community/boards/notice/posts`
  - `PUT /api/community/posts/{post_id}/notice`
- Verify before claiming completion:
  - `GET /api/community/boards/notice/posts?page=1` on
    `marketflow-api.bit-man.net` returns the new title in `notices`.
  - `GET /api/community/posts/{post_id}` returns the expected title, content,
    `board.slug == "notice"`, and `is_notice == true`.
  - The deployed frontend bundle still points at `marketflow-api.bit-man.net`.
- If a bad or broken local post was created while troubleshooting, hide or fix it
  and clearly report which production post ID is the visible one.
- Never say a community post is done until the deployed app's backing API has the
  visible post. Localhost success alone is not completion.

## Git and Deployment

- Do not commit, push, or deploy unless the user asks.
- Before committing, run the relevant tests and summarize the results.
- For frontend deployment, use `frontend-react/npm run deploy`.
- For MiniPC backend deployment, pull the committed branch on the MiniPC and
  restart the Flask scheduled task, then verify `/healthz` and `/api/health`.

## Verified Alpha / OpenClaw Operations

- The committed source of truth for OpenClaw, main-PC verified Telegram, and
  future MiniPC handoff is `skills/marketflow-openclaw-ops/`; install it only
  through its safe junction installer when an operator explicitly requests it.
- Development Flask remains port `5001`. The current Windows MiniPC launcher and
  watchdog contract is `127.0.0.1:5003`; older `5001` MiniPC helper scripts are
  unsafe until reconciled. MCP HTTP is `8765`.
- Windows `C:\bitman_marketfloww` with Task Scheduler is current. Linux
  `/srv/marketflow` and systemd are future-only design. Never use Spring or
  port `8080` for MarketFlow.

## Useful References

- `docs/mirofish_alpha_stock_detection_master_plan_2026_05_04.md`
- `docs/mirofish_ascii_brain_admin_plan.md`
- `INFRASTRUCTURE.md`
- `.github/workflows/test.yml`
- `.github/workflows/deploy-frontend.yml`
