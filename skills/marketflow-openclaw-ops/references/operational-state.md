# Operational state

- Current platform: Windows MiniPC, `C:\bitman_marketfloww`, Task Scheduler;
  Flask launcher/watchdogs bind 127.0.0.1:5003.
- Local development Flask remains 5001. MCP HTTP is 8765. MarketFlow must never
  use 8080 or Spring.
- `/srv/marketflow` and systemd are future Linux design, not current operation.
  The older 5001 MiniPC helper scripts remain quarantined and are not deployment
  inputs; the authoritative Windows production contract is already 5003.
- OpenClaw remains 19 MarketFlow read-only tools, zero mutation tools, zero
  bindings, sandbox `all`, workspace access `none`, and mutation env false.
  Future agent behavior must deny mutation. There is no Telegram/OpenClaw
  coupling.
- Telegram remains private and requires the exact previewed `run_id` plus
  `message_digest` and confirmation phrase. Invalid runs never send. A valid
  stale-blocked run is `검출 보류` only. The ignored sanitized receipt ledger
  must persist locally for dedupe and recovery but must never be printed,
  copied, staged, or committed. The public CLI exposes `delivery_verified` but
  never exposes a raw message, message ID, or receipt.
- Core commit `6fb75cb` makes scheduler and Flask realtime Telegram transport
  explicit opt-in. Before the verified one-shot operator, require
  `ALPHA_SCANNER_TELEGRAM_ENABLED=false`,
  `MIROFISH_WORKFLOW_TELEGRAM_ENABLED=false`,
  `ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED=false`, and
  `MIROFISH_AUTO_RUNNER_DRY_RUN=true`, verified only through the sanitized
  read-only exclusivity script.
- Deployment is blocked: tracked legacy documentation needs redaction and
  credential rotation confirmation. Do not copy credential-like plaintext,
  tokens, chat IDs, raw messages, member data, or receipts into this state.

## 2026-08-21 KST validation snapshot

- Historical focused checkpoint: through `ed65734`. Its gates passed: 71
  verified-delivery tests and 149 related regression tests. A historical full
  pytest rerun through `33dc203` reached 100% and exited 0 with five
  pre-existing unawaited-coroutine warnings.
- Core serialization and opt-in defaults are committed through `6fb75cb`; its
  focused bundle reported 269 green.
- The local read-only exclusivity verifier exited 0 with the required
  false/false/false/true values, each resolved from its safe default; it emitted
  no raw environment value or path.
- Fresh functional verification used the repository `.venv`. The fresh baseline
  at 2026-08-21 20:16:40 KST was Python count 18 / max RecordId 3440795 and WHEA
  count 94 / max RecordId 102348. `pytest -q` three times and
  `pytest --collect-only -q` three times all passed; all six invocations passed.
  Each invocation reported five existing `ensure_jongga_v2`
  unawaited-coroutine warnings and two existing ops symlink skips. Frontend
  verification also passed 17 files / 90 tests and the production build; the
  package-lock hash remained unchanged. The functional gate is GREEN.
- OpenClaw `2026.7.1-2` passed the committed parsed fail-fast verifier. All nine
  setup/native checks exited 0; live agent/config/MCP data proves exactly 19
  read-only tools, zero mutation tools, zero bindings, mutation false, sandbox
  `all`, workspace `none`, one non-target deny, non-overlapping agent paths, and
  security critical 0. The Codex skill Junction is installed and validated.
- Scanner alert-required source data was stale. A safe price refresh hung and
  was interrupted without changing data, so the outcome is zero candidates and
  `검출 보류` only.
- Telegram authentication and private-chat lookup were valid, but both guarded
  sends and the write-capability probe returned 403 because the recipient has
  blocked the configured bot. There is no message ID and no delivery. The
  ledger contains known failed retryable records; do not retry until the
  recipient unblocks the bot. Telegram was not sent; the recipient remains
  blocked.
- MiniPC deployment is not authorized. It remains blocked by legacy credential
  redaction/rotation; older 5001 MiniPC helpers remain quarantined. The final
  read-only predeploy audit exited 0. Database `quick_check=ok` and the
  required user schema is present, but 11 foreign-key violations remain
  (`post_images -> posts`). Backup roots/files remain 0/0; community references
  remain missing 0 / unreferenced 8; disk free is 63.24%; scanner runs total
  4097. Workflow directories total 7: completed 6 and running 1, with running
  age bucket `1h_to24h`; workflow JSON/outcomes errors remain 0. The stale
  running workflow is a MiniPC deployment-review blocker. Deployment remains
  blocked until the FK violations, stale workflow, and verified backup are
  resolved/approved. No push or deployment was performed.
- MiniPC deployment is also blocked because legacy boolean sender paths retain
  timeout-after-accept ambiguity and do not use the shared verified-delivery
  ledger. Migrating or removing those opt-in paths is a follow-up gate even
  though `6fb75cb` leaves them disabled by default.

## Host runtime stability gate

- Host runtime stability risk is **HIGH** and substantially predates this
  feature. Before 2026-08-21 17:05 KST, the matching count was 17 (python.exe
  15 + python3.13.exe 2). Read-only evidence captured at 2026-08-21 18:02:38 KST
  found 18 Python Application Error crashes (python.exe 16 + python3.13.exe 2)
  and 93 WHEA hardware errors. The latest matching Application Error event
  occurred at 2026-08-21 17:42 KST (17:42:03); the 18th is python.exe RecordId
  3440795 during final test work. **Fresh gate failed** for an earlier attempted
  release evidence window: the count became 94 WHEA hardware errors after WHEA-Logger
  Event ID 19, RecordId 102348, at 2026-08-21 19:15:51 KST. The historical
  2026-08-21 18:02:38 KST WHEA snapshot remains 93 with max RecordId 101636.
  Recent WHEA errors are predominantly CPU internal parity/TLB on APIC 16/17;
  crashes span multiple Python distributions and other applications.
- For the latest gate, the fresh baseline at 2026-08-21 20:16:40 KST was Python
  count 18 / max RecordId 3440795 and WHEA count 94 / max RecordId 102348.
  A post-run read-only check found Application Error Event ID 1000, RecordId
  3440809, at 2026-08-21 20:19:58.2780602 KST. It involved python.exe 3.12 in
  `codex-primary-runtime`, `python312.dll`, and exception `0xc0000005`; no raw
  report or full runtime path is retained. The post-check Python count is 19.
  WHEA remained 94 with max RecordId 102348. The functional gate is GREEN, but
  the host stability release gate is FAIL. Further stress reruns stopped, and
  MiniPC deployment remains blocked pending independent stable-PC/CI evidence.
- Immediately before three consecutive `pytest -q` and three consecutive
  `pytest --collect-only -q` runs, capture the current maxima for matching events
  as the fresh release-test baseline. After all runs, FAIL if any matching
  Python Application Error Event ID 1000 or WHEA-Logger event has RecordId
  greater than its fresh pre-test maximum; pass only if none do. System time is
  not primary.
- This change touched no dependency, pytest, or native-FFI configuration, so
  rollback is not indicated. Before MiniPC deployment, independently rerun on a
  stable PC/CI.
- BIOS defaults/standard performance and a cold boot are an operator-only
  recommendation, never an agent action. Any system-setting or reboot action
  requires separate explicit authorization and vendor recovery/BitLocker/virtualization prep.
  This handoff performs none. Save work, run vendor/Intel
  CPU diagnostics, preserve event logs, and service or RMA if WHEA recurs.
