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

## 2026-08-21 KST validation snapshot

- Verified code state: through `33dc203`. Focused tests exited 0; a full pytest
  rerun reached 100% and exited 0 with five pre-existing unawaited-coroutine
  warnings. Two separate CPython 3.12 native intermittent crashes (access
  violation/illegal instruction) were also observed and remain an environment
  risk.
- Frontend verification passed: 17 files / 90 tests and the production build.
- OpenClaw `2026.7.1-2` config validated; MCP doctor/probe passed; inventory is
  exactly 19 read-only tools, zero bindings, mutation false, sandbox `all`, and
  workspace `none`. Security audit reported critical 0 and warn 1
  (trusted-proxy warning). The Codex skill Junction is installed and validated.
- Scanner alert-required source data was stale. A safe price refresh hung and
  was interrupted without changing data, so the outcome is zero candidates and
  `검출 보류` only.
- Telegram authentication and private-chat lookup were valid, but both guarded
  sends and the write-capability probe returned 403 because the recipient has
  blocked the configured bot. There is no message ID and no delivery. The
  ledger contains known failed retryable records; do not retry until the
  recipient unblocks the bot.
- MiniPC deployment is not authorized. It remains blocked by legacy credential
  redaction/rotation and port-SSOT reconciliation. A read-only predeploy audit
  exited 0: database `quick_check=ok` and required user schema is present, but
  11 foreign-key violations remain (`post_images -> posts`); no configured
  backup roots/candidates were found; community file references have 0 missing
  and 8 unreferenced files; workflows completed 6/6 with no JSON errors; disk
  free is 63.15%. Deployment remains blocked until the FK violations and a
  verified backup are resolved/approved. No push or deployment was performed.

## Host runtime stability gate

- Host runtime stability risk is **HIGH** and predates this feature: Windows
  evidence showed 15 Python crashes and 93 WHEA hardware errors before feature
  work. Recent WHEA errors are predominantly CPU internal parity/TLB on APIC
  16/17; crashes span multiple Python distributions and other applications.
- This change touched no dependency, pytest, or native-FFI configuration, so
  rollback is not indicated. Before MiniPC deployment, independently rerun on a
  stable PC/CI. After main-PC hardware stabilization, require `pytest -q` and
  `pytest --collect-only -q` three consecutive times with no new WHEA or
  Application Error.
- Concise remediation: save work, use BIOS defaults/standard performance and a
  cold boot, run vendor/Intel CPU diagnostics, preserve event logs, and service
  or RMA if WHEA recurs. Do not alter logs or system settings as part of this
  operational handoff.
