---
name: marketflow-openclaw-ops
description: Use when verifying MarketFlow alpha delivery on the main PC, performing an explicitly confirmed private Telegram operation, or handing off a future MiniPC deployment.
---

# MarketFlow OpenClaw Operations

Use this committed skill as the operational source of truth. It is separate from
`integrations/openclaw/workspace/skills/marketflow-readonly`, which remains an
OpenClaw runtime skill for read-only tools only.

Read every relevant reference in this safe order; combined requests can require
more than one:

1. Current saved facts or pending blockers: [references/operational-state.md](references/operational-state.md)
2. Main-PC validation: [references/main-pc-validation.md](references/main-pc-validation.md)
3. Explicit private Telegram operation: [references/telegram-delivery.md](references/telegram-delivery.md)
4. Future MiniPC commit, push, or deploy request: [references/minipc-deployment.md](references/minipc-deployment.md)

No Telegram/OpenClaw coupling. Do not expose, copy, or infer secrets,
recipients, raw messages, or runtime receipts.
