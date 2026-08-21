# Verified Alpha Telegram Operations Design

## Goal

Run the MarketFlow alpha scanner on the main Windows PC, verify the exact
persisted result, and deliver one private Telegram report with durable,
secret-free evidence. Preserve the read-only OpenClaw boundary and prepare a
future Windows MiniPC handoff without pushing or deploying in this change.

## Safety decisions

- OpenClaw remains read-only. It never receives scan, Telegram, order, wallet,
  deployment, or generic message tools.
- The one-shot operator command defaults to preview. A real send requires an
  explicit confirmation string and targets only the personal Telegram chat.
- Candidate delivery requires a completed, replayable scanner run and fresh
  alert-required sources. If the run is blocked, the command may send one
  clearly labelled `검출 보류` status report instead of directional candidates.
- The exact send unit is `run_id + SHA-256(message)`. A successful receipt makes
  an identical resend fail closed.
- Telegram success requires `HTTP 200`, `ok=true`, and a positive
  `result.message_id`. Secrets and chat identifiers are never persisted.
- Scanner alert state is committed only after a verified Telegram delivery.
- No KIS order, brokerage mutation, public Telegram channel, AIbain delivery,
  Git push, MiniPC connection, service restart, or deployment is in scope.

## One-shot flow

1. Load `.env` without displaying values and confirm that the personal bot
   token and chat ID are configured.
2. Optionally refresh only the alert-required price and leading-screener
   sources. Do not call the broad KR update because it posts community content,
   sends unrelated Telegram messages, and can push Git state.
3. Run `alpha_scanner.run_scanner_alert_check` with deterministic reranking,
   `commit_state=False`, and `block_on_stale=True`.
4. Re-read the persisted run and analysis artifacts and validate identity,
   counts, finite scores, target identity, evidence, price date, and
   look-ahead-safe markers.
5. Build either the verified candidate report or the blocked-status report.
6. In preview mode, print only a sanitized JSON summary. In send mode, enforce
   confirmation and deduplication before calling Telegram once.
7. Atomically persist a receipt containing timestamps, run ID, digest,
   delivery status, message ID, candidate/event counts, symbols, and freshness.
   Never persist tokens, chat IDs, raw environment values, or the full message.

## OpenClaw hardening

- Reject an existing target agent whose `agentDir` equals or overlaps any
  non-target agent directory. Auth profiles, model registries, and sessions must
  never be shared.
- Use OpenClaw's UTF-8 batch-file configuration path instead of embedding large
  JSON in a Windows command line. Remove temporary payload files on success and
  failure and never echo the payload in JSON output.
- Preserve existing deny rules and add `marketflow__*` to every non-target
  configured agent. Record that future agents must receive the same deny rule.
- Preserve the target's zero bindings, sandbox-all/workspace-none profile,
  mutation-disabled environment, and exact read-only tool inventory.

## Durable operations memory

The committed Codex skill is `skills/marketflow-openclaw-ops`. Its references
cover main-PC verification, Telegram delivery, Windows MiniPC handoff, and a
sanitized operational-state snapshot. A PowerShell installer exposes the
committed skill under the user's Codex skill directory without using the
repository's unrelated untracked `.codex` directory.

The existing OpenClaw runtime skill at
`integrations/openclaw/workspace/skills/marketflow-readonly` remains separate
and unchanged in responsibility.

## Future deployment gates

- Current production target: Windows MiniPC `C:\bitman_marketfloww` under the
  normal operator account, with Flask on `127.0.0.1:5003`.
- Development default remains port `5001`; port `8080` belongs to another
  project and is forbidden.
- Some legacy docs/scripts still point MiniPC operations at port `5001`; future
  deployment is blocked until the live target and tunnel are rechecked and the
  operational SSOT is reconciled.
- Push only to `origin`; MiniPC pulls `origin/main` with `--ff-only`. Never push
  directly to the working-tree `minipc` remote and never use reset/clean force
  scripts.
- Tracked legacy documentation contains credential-like plaintext. Values must
  not be copied into the skill or evidence; redaction and credential rotation
  remain a deployment gate.

## Verification

- Focused TDD for the one-shot operator and OpenClaw setup hardening.
- Skill structure validation and pressure tests.
- Existing MiroFish/OpenClaw regression suites.
- Full Python test suite and relevant frontend build when repository changes
  can affect the already-ahead frontend commit.
- Local OpenClaw config validation, MCP doctor/probe, skill visibility, agent
  bindings, and security audit.
- One final main-PC operator run. If fresh, send verified candidates; if
  blocked, send the truthful hold report. Record the Telegram receipt.

## Execution outcome — 2026-08-21 KST

- Code was validated through `ed65734`. Focused gates passed: 71
  verified-delivery tests and 149 related regression tests. A historical full
  pytest rerun through `33dc203` reached 100% and exited 0 with five
  pre-existing unawaited-coroutine warnings; a final full pytest rerun is not
  yet claimed through `ed65734`.
- Frontend validation passed: 17 files / 90 tests and the build. OpenClaw
  `2026.7.1-2` config validated; MCP doctor/probe passed; its boundary remains
  19 read-only tools, zero bindings, mutation false, sandbox `all`, workspace
  `none`, and audit critical 0 / warn 1 (trusted-proxy warning). The Codex skill
  Junction is installed and validated.
- Scanner source data was stale. The safe price refresh hung and was interrupted
  without changing data, producing zero candidates and `검출 보류` only.
- Telegram authentication and private-chat lookup succeeded, but guarded sends
  and a write-capability probe returned 403 because the recipient blocked the
  configured bot. No message ID or delivery exists; known failed retryable
  ledger records must not be retried until the recipient unblocks the bot.
- Tasks 1–3 are complete. Task 4 is blocked only on that external Telegram
  unblock. MiniPC deployment remains unauthorized and blocked by legacy
  credential redaction/rotation plus port-SSOT reconciliation. A read-only
  predeploy audit exited 0: database `quick_check=ok` and required user schema
  is present, but 11 foreign-key violations remain (`post_images -> posts`);
  no configured backup roots/candidates were found; community file references
  have 0 missing and 8 unreferenced files; workflows completed 6/6 with no JSON
  errors; disk free is 63.15%. Deployment remains blocked until the FK
  violations and a verified backup are resolved/approved; no push or deployment
  occurred.
- Host runtime stability risk is **HIGH** and predates this feature: Windows
  evidence at 2026-08-21 18:02:38 KST showed 17 Python Application Error
  crashes (python.exe 15 + python3.13.exe 2) and 93 WHEA hardware errors before
  feature work. Recent WHEA errors are predominantly CPU internal parity/TLB on
  APIC 16/17; crashes span multiple Python distributions and other applications.
  Historical diagnostic baseline at 2026-08-21 18:02:38 KST: Application Error
  max RecordId 3440795 and WHEA-Logger max RecordId 101636. Immediately before
  the three consecutive `pytest -q` and `pytest --collect-only -q` runs, capture
  the current maxima for matching events as the fresh release-test baseline.
  After all runs, FAIL if any matching Python Application Error Event ID 1000 or
  WHEA-Logger event has RecordId greater than its fresh pre-test maximum; pass
  only if none do. System time is not primary. No dependency, pytest, or
  native-FFI configuration changed here, so rollback is not indicated. Future
  MiniPC release requires an independent stable-PC/CI rerun.
  BIOS defaults/standard performance and a cold boot are an operator-only
  recommendation, never an agent action. Any system-setting or reboot action
  requires separate explicit authorization and vendor recovery/BitLocker/virtualization prep.
  This handoff performs none. Save work, run vendor/Intel
  CPU diagnostics, preserve event logs, and service or RMA if WHEA recurs.
