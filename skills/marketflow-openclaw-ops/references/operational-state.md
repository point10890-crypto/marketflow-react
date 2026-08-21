# Operational state

- Current platform: Windows MiniPC, `C:\bitman_marketfloww`, Task Scheduler;
  Flask launcher/watchdogs bind 127.0.0.1:5003.
- Local development Flask remains 5001. MCP HTTP is 8765. MarketFlow must never
  use 8080 or Spring.
- `/srv/marketflow` and systemd are future Linux design, not current operation.
  The older 5001 MiniPC helper scripts are unsafe until reconciled.
- OpenClaw remains 19 MarketFlow read-only tools, zero mutation tools, zero
  bindings, sandbox `all`, workspace access `none`, and mutation env false.
  Future agent behavior must deny mutation. There is no Telegram/OpenClaw
  coupling.
- Telegram remains private, confirmation-gated, digest-deduplicated, and
  receipt-verified; stale/invalid results are `검출 보류` only.
- Deployment is blocked: tracked legacy documentation needs redaction and
  credential rotation confirmation. Do not copy credential-like plaintext,
  tokens, chat IDs, raw messages, member data, or receipts into this state.
