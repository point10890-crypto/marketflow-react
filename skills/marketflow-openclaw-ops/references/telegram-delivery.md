# Private verified Telegram delivery

Telegram belongs only to the verified MarketFlow operator. It is private-only,
confirmation-gated, digest-deduplicated, and receipt-verified. Do not use it
for public channels, orders, wallets, AIbain, or OpenClaw.

First run the preview command from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py
```

Send only when the requester explicitly asks for this private operation and
explicitly confirms the exact command:

```powershell
.\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py --send --confirm SEND_VERIFIED_ALPHA_TELEGRAM
```

If source data is stale or invalid, send only `검출 보류`; never send
directional candidates. Do not print, persist, stage, or commit raw messages,
recipients, chat IDs, member data, secrets, or generated receipts.
