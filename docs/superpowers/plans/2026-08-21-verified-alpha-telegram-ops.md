# Verified Alpha Telegram Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, verify, and locally operate a fail-closed alpha-scanner-to-private-Telegram path while hardening OpenClaw and storing a reusable MiniPC handoff skill.

**Architecture:** A standalone operator module wraps the existing deterministic alpha scanner, persists and validates preview artifacts, and binds explicit-confirmation Telegram delivery to the exact previewed run ID and digest plus an atomic sanitized local ledger. OpenClaw setup remains a separate read-only boundary and is hardened against identity-directory collisions, oversized Windows command lines, and cross-agent tool exposure. A committed Codex skill and parsed verifier route future operators through the exact main-PC and MiniPC gates.

**Tech Stack:** Python 3, pytest, PowerShell, OpenClaw CLI, Markdown Codex skills, atomic JSON helpers.

**Spec:** `docs/superpowers/specs/2026-08-21-verified-alpha-telegram-ops-design.md`

## Execution status — 2026-08-21 KST

- Tasks 1–3 reached a historical local checkpoint through `ed65734`. Focused
  gates at that checkpoint passed: 71 verified-delivery tests and 149 related
  regression tests. The preview-bound approval, cross-run dedupe/recovery, and
  public CLI redaction fixes are implemented through `276e49a`; current focused
  results are recorded only after rerunning the gates below. A
  historical full pytest rerun through `33dc203` reached 100% and exited 0 with
  five pre-existing unawaited-coroutine warnings; a final full pytest rerun is
  not yet claimed through `ed65734`.
- Frontend verification passed: 17 files / 90 tests and build. OpenClaw
  `2026.7.1-2` passed the committed parsed fail-fast verifier: all nine
  setup/native checks exited 0 and live agent/config/MCP data proved the
  read-only 19-tool / zero-binding / mutation-false / sandbox-all /
  workspace-none boundary, every non-target deny, MCP ownership, and
  non-overlapping agent paths. Audit was critical 0 / warn 1 (trusted-proxy
  warning), and the Codex skill Junction is installed and validated.
- Scanner source data was stale; the safe price refresh hung and was interrupted
  with no data change, yielding zero candidates and `검출 보류` only.
- Task 4 remains incomplete at the stable-host/full verification gate, external
  Telegram unblock, and final sanitized snapshot/commit gate. Authentication
  and private-chat lookup were valid, but guarded sends and a write-capability
  probe returned 403 because the recipient blocked the configured bot. No
  message ID or delivery exists; known failed retryable records must not be
  retried until unblock. No push or deployment occurred.
- MiniPC deployment remains unauthorized and blocked by legacy credential
  redaction/rotation, the stable-host verification gate, database integrity,
  and backup proof. The port SSOT is already reconciled to Windows production
  5003; legacy 5001 MiniPC helpers remain quarantined. A read-only predeploy
  audit exited 0: database `quick_check=ok` and required user schema is present, but
  11 foreign-key violations remain (`post_images -> posts`); no configured
  backup roots/candidates were found; community file references have 0 missing
  and 8 unreferenced files; workflows completed 6/6 with no JSON errors; disk
  free is 63.15%. Deployment remains blocked until the FK violations and a
  verified backup are resolved/approved.
- Host runtime stability risk is **HIGH** and substantially predates this
  feature. Before 2026-08-21 17:05 KST, the matching count was 17 (python.exe
  15 + python3.13.exe 2). Read-only evidence captured at 2026-08-21 18:02:38 KST
  found 18 Python Application Error crashes (python.exe 16 + python3.13.exe 2)
  and 93 WHEA hardware errors. The latest matching Application Error event
  occurred at 2026-08-21 17:42 KST (17:42:03); the 18th is python.exe RecordId
  3440795 during final test work. The current total remains 18 with no later
  matching event. Recent WHEA errors are predominantly CPU internal parity/TLB
  on APIC 16/17; crashes span multiple Python distributions and other
  applications.
  Historical diagnostic baseline: Application Error max RecordId 3440795 and
  WHEA-Logger max RecordId 101636. Immediately before
  the three consecutive `pytest -q` and `pytest --collect-only -q` runs, capture
  the current maxima for matching events as the fresh release-test baseline.
  After all runs, FAIL if any matching Python Application Error Event ID 1000 or
  WHEA-Logger event has RecordId greater than its fresh pre-test maximum; pass
  only if none do. System time is not primary. This change touched no dependency,
  pytest, or native-FFI configuration, so rollback is not indicated. Before
  MiniPC deployment, independently rerun on a stable PC/CI.
  BIOS defaults/standard performance and a cold boot are an operator-only
  recommendation, never an agent action. Any system-setting or reboot action
  requires separate explicit authorization and vendor recovery/BitLocker/virtualization prep.
  This handoff performs none. Save work, run vendor/Intel
  CPU diagnostics, preserve event logs, and service or RMA if WHEA recurs.

## Global Constraints

- Never print, copy, stage, or commit `.env`, tokens, chat IDs, member data, raw credentials, messages, or Telegram response bodies. The sanitized ignored receipt ledger must persist locally for dedupe/recovery but must not leave the host.
- OpenClaw remains read-only with exactly 19 MarketFlow tools, zero mutation tools, zero bindings, sandbox `all`, workspace access `none`, and `MIROFISH_MCP_ALLOW_MUTATION=false`.
- Telegram delivery is private only, bound to the exact previewed `run_id + message_digest` (the message SHA-256), cross-run event-deduplicated, and requires an explicit confirmation string.
- Invalid runs never send. A valid run blocked only by stale alert-required data can send only `검출 보류`, never a directional candidate report.
- No public channel, AIbain, order, wallet, Git push, MiniPC connection, service restart, or deployment.
- Preserve all unrelated dirty and untracked files; stage only intentional source, test, skill, and documentation files.
- Development API port is 5001, Windows MiniPC Flask port is 5003, MCP HTTP port is 8765, and port 8080 is forbidden.

---

### Task 1: Verified one-shot scanner and Telegram delivery

**Files:**
- Create: `app/services/mirofish/verified_delivery.py`
- Create: `scripts/run_verified_alpha_telegram.py`
- Create: `tests/test_mirofish_verified_delivery.py`

**Interfaces:**
- Consumes: `alpha_scanner.run_scanner_alert_check`, persisted scanner artifacts, `write_json_atomic`, personal Telegram environment variables.
- Produces: preview `run_verified_detection(...) -> dict`, exact `run_id` + `message_digest`-bound send, `validate_scanner_run(...) -> dict`, `post_private_telegram(...) -> dict`, and a CLI returning sanitized JSON.

- [x] **Step 1: Write failing tests**

Cover preview-without-send, preview artifact persistence, exact run/digest-bound
send, stale candidate suppression, invalid-run no-send, explicit confirmation,
artifact identity/count/finite-score validation, private-only Telegram payload,
`message_id` verification, duplicate digest refusal, success-only receipt and
scanner-state commit, and secret-free output.

- [x] **Step 2: Run the focused tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/test_mirofish_verified_delivery.py -q`

Expected: collection failure because `app.services.mirofish.verified_delivery`
does not exist.

- [x] **Step 3: Implement the reviewed operator service and CLI**

Use `deepseek_rerank=False`, `commit_state=False`, and
`block_on_stale=True` for preview. A send reloads the exact persisted run and
requires the previewed digest; it must not create a replacement scanner run.
A successful Telegram response must return a positive integer `message_id`.
Store only the sanitized ignored ledger schema using the repository atomic JSON
helper; never print or copy the ledger or a raw receipt.

- [ ] **Step 4: Run focused tests and existing scanner/Telegram regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mirofish_verified_delivery.py tests/test_admin_mirofish_alpha_scanner.py tests/test_scheduler_with_record.py tests/test_screener_telegram_messages.py -q
```

Expected: all pass.

### Task 2: OpenClaw setup security and Windows transport hardening

**Files:**
- Modify: `scripts/setup_openclaw_mcp.py`
- Modify: `tests/test_setup_openclaw_mcp.py`
- Modify: `integrations/openclaw/README.md`

**Interfaces:**
- Consumes: existing OpenClaw config preview/apply reconciliation.
- Produces: collision-safe inventory validation, temporary UTF-8 batch-file config application, sanitized command reporting, and non-target deny preservation.

- [x] **Step 1: Add failing regression tests**

Add cases for target/non-target `agentDir` equality and overlap, a reconciled
configuration larger than 32 KiB with Windows metacharacters, batch-file cleanup
on success/failure, payload absence from JSON output, and deny preservation for
every non-target agent.

- [x] **Step 2: Run the focused tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/test_setup_openclaw_mcp.py -q`

Expected: new collision and batch transport assertions fail.

- [x] **Step 3: Implement one reviewed issue at a time**

First reject unsafe agent directories, then replace inline `--batch-json` with a
closed temporary UTF-8 `--batch-file`, then reconcile deny lists without
overwriting unrelated policies. Always delete the temporary file in `finally`.

- [x] **Step 4: Run focused OpenClaw tests**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/test_setup_openclaw_mcp.py tests/test_mirofish_mcp_multi_tools.py tests/test_mirofish_mcp_resource_catalog.py -q`

Expected: all pass.

### Task 3: Codex operator skill, installer, and durable handoff record

**Files:**
- Create: `skills/marketflow-openclaw-ops/SKILL.md`
- Create: `skills/marketflow-openclaw-ops/references/main-pc-validation.md`
- Create: `skills/marketflow-openclaw-ops/references/telegram-delivery.md`
- Create: `skills/marketflow-openclaw-ops/references/minipc-deployment.md`
- Create: `skills/marketflow-openclaw-ops/references/operational-state.md`
- Create: `skills/marketflow-openclaw-ops/scripts/verify_openclaw_readonly.py`
- Create: `scripts/install_marketflow_codex_skill.ps1`
- Create: `tests/test_marketflow_openclaw_ops_skill.py`
- Modify: `AGENTS.md`
- Modify: `INFRASTRUCTURE.md`

**Interfaces:**
- Consumes: the verified-delivery CLI and hardened OpenClaw setup commands.
- Produces: one discoverable `marketflow-openclaw-ops` skill, a parsed fail-fast read-only OpenClaw verifier, and a no-secret future Windows MiniPC runbook.

- [x] **Step 1: Pressure-test the missing skill and add failing structural tests**

Demonstrate that an unassisted operator can choose stale or force deployment
paths incorrectly. Add tests that require the skill's explicit ports, no-reset,
origin/FF-only, private-Telegram, OpenClaw invariants, credential-redaction gate,
and installer source-of-truth behavior.

- [x] **Step 2: Run tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe -m pytest tests/test_marketflow_openclaw_ops_skill.py -q`

Expected: fail because the skill and installer do not exist.

- [x] **Step 3: Implement the minimal skill and documentation**

Keep `SKILL.md` short and route details into one-level reference files. The
installer creates or refreshes a user-skill junction/copy from the committed
source and refuses to overwrite an unrelated destination. Add only concise
SSOT pointers to `AGENTS.md` and reconcile dev 5001 versus Windows MiniPC 5003
in `INFRASTRUCTURE.md` without changing live services.

- [x] **Step 4: Validate structure and pressure-test with the skill**

Run:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$codexSkillsRoot = Join-Path $env:USERPROFILE '.codex\skills'
$validator = Join-Path $codexSkillsRoot '.system\skill-creator\scripts\quick_validate.py'
python $validator (Join-Path (Get-Location) 'skills\marketflow-openclaw-ops')
.\.venv\Scripts\python.exe -m pytest tests/test_marketflow_openclaw_ops_skill.py -q
.\.venv\Scripts\python.exe skills/marketflow-openclaw-ops/scripts/verify_openclaw_readonly.py
```

Expected: validator and tests pass; pressure-test operator selects the safe path.

### Task 4: Main-PC integration verification, one private send, and local commit — blocked externally

**Files:**
- Update: `skills/marketflow-openclaw-ops/references/operational-state.md`
- Runtime only, ignored: `data/admin_mirofish/verified_delivery_receipt.json`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: verified local runtime evidence, one Telegram receipt, and one scoped local Git commit.

- [ ] **Step 1: Run focused and full regression gates**

Run the task-specific focused tests and `frontend-react` tests/build. Preserve
the historical full-suite evidence, but keep a final `pytest -q` rerun through
the current verified code state as an explicit release gate rather than claiming
it complete here.

- [x] **Step 2: Run local OpenClaw verification**

Run the committed parsed fail-fast verifier. It must check every native command
exit code and parse live agents/config/MCP/probe/security data. Apply setup only
when an explicitly required and authorized configuration change exists.

- [x] **Step 3: Run the one-shot operator in preview**

If alert-required sources are stale, attempt only the explicitly safe core
refresh. Re-run preview, retain the sanitized JSON object, and inspect it
without exposing environment values. Preview persists scanner run artifacts;
it is non-sending, not filesystem-non-mutating.

- [ ] **Step 4: Send exactly one private report — blocked on recipient unblock**

Use only the exact preview object:

```powershell
$preview = .\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py | ConvertFrom-Json
.\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py --send --run-id $preview.run_id --message-digest $preview.message_digest --confirm SEND_VERIFIED_ALPHA_TELEGRAM
```

Invalid runs never send. If a valid run is blocked only by stale alert-required
data, send the truthful `검출 보류` report. Verify delivery internally, but do
not expose a message ID or raw receipt. The ignored sanitized ledger must
persist locally for dedupe and recovery and must never be printed, copied,
staged, or committed. If recipient blocking returns 403, record only the
sanitized no-delivery result and do not retry until unblocked.

- [ ] **Step 5: Update the sanitized operational snapshot and commit**

Record commit/tool/test/delivery status without tokens, chat IDs, PII, or raw
messages. Re-run the final verification, stage only intentional files, and make
one local commit. Do not push or deploy.
