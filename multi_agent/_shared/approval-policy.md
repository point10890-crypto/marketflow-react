# Approval Policy

## Allowed Without Extra Approval

- Read source files, docs, tests, and safe generated summaries.
- Add or edit source files inside the repository when requested.
- Run focused tests, compile checks, and local smoke checks.
- Generate dry-run plans, endpoint manifests, and operator runbooks.

## Requires Explicit Operator Approval

- Run official installers such as `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`.
- Install system-wide tools or modify PATH.
- Write to `~/.hermes/config.yaml` outside a dry-run preview.
- Send Telegram, Kakao, email, or other external notifications.
- Restart MiniPC services or schedulers unless deployment was requested.
- Touch `.env`, API keys, token caches, production databases, or member data.

## Forbidden

- Broker order execution.
- Secret echoing or committing.
- Destructive git cleanup of unrelated work.
- Treating C/D-grade sources as standalone investment evidence.
