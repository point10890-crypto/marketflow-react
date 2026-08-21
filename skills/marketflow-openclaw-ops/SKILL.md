---
name: marketflow-openclaw-ops
description: Use when verifying MarketFlow alpha delivery on the main PC, performing an explicitly confirmed private Telegram operation, or handing off a future MiniPC deployment.
---

# MarketFlow OpenClaw Operations

Use this committed skill as the operational source of truth. It is separate from
`integrations/openclaw/workspace/skills/marketflow-readonly`, which remains an
OpenClaw runtime skill for read-only tools only.

Route to exactly one reference for the requested mode:

- Main-PC validation: [references/main-pc-validation.md](references/main-pc-validation.md)
- Explicit private Telegram operation: [references/telegram-delivery.md](references/telegram-delivery.md)
- Future MiniPC commit, push, or deploy request: [references/minipc-deployment.md](references/minipc-deployment.md)
- Current saved facts or pending blockers: [references/operational-state.md](references/operational-state.md)

No Telegram/OpenClaw coupling. Do not expose, copy, or infer secrets,
recipients, raw messages, or runtime receipts.
