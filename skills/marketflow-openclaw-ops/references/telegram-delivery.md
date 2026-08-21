# Private verified Telegram delivery

Telegram belongs only to the verified MarketFlow operator. It is private-only,
confirmation-gated, digest-deduplicated, and receipt-verified. Do not use it
for public channels, orders, wallets, AIbain, or OpenClaw.

Before every preview or send, run:

```powershell
.\.venv\Scripts\python.exe skills/marketflow-openclaw-ops/scripts/verify_delivery_exclusivity.py
```

The verifier returns only each resolved sanitized boolean and its source.
Continue only when the exit code is 0 and the result is exactly
`ALPHA_SCANNER_TELEGRAM_ENABLED=false`,
`MIROFISH_WORKFLOW_TELEGRAM_ENABLED=false`,
`ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED=false`, and
`MIROFISH_AUTO_RUNNER_DRY_RUN=true`. Never reveal its `.env` path or replace
the sanitized output with raw environment inspection.

Only explicit known true/false tokens are valid. Empty, unknown, `$`-bearing,
or interpolated values fail closed with `invalid_flag_value`; do not rewrite or
expand them to make the gate pass.

First run a preview from the repository root and retain only its sanitized JSON
object in the current shell. Preview does not send, but it persists scanner run
artifacts for the run that was evaluated:

```powershell
$preview = .\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py | ConvertFrom-Json
if (-not $preview.run_id -or -not $preview.message_digest) {
    throw 'Preview did not return an approvable run and digest'
}
```

Send only when the requester explicitly asks for this private operation and
explicitly confirms the exact previewed `run_id` and `message_digest`:

```powershell
.\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py --send --run-id $preview.run_id --message-digest $preview.message_digest --confirm SEND_VERIFIED_ALPHA_TELEGRAM
```

Invalid runs never send, regardless of confirmation. A valid run that is
blocked only because alert-required data is stale may send only `검출 보류`;
it must never send a directional candidate.

`scripts/verify_auto_runner_e2e.py --send` fails closed and cannot replace this
flow. Use only the verified one-shot operator with its exact previewed run,
digest, and confirmation.

The sanitized ignored ledger at
`data/admin_mirofish/verified_delivery_receipt.json` must persist locally for
dedupe, uncertain-delivery blocking, and state recovery. Never print, copy,
stage, or commit that ledger. The public CLI reports only the sanitized status
and `delivery_verified`; it never exposes raw messages, recipients, chat IDs,
member data, secrets, Telegram response bodies, message IDs, or raw receipts.
