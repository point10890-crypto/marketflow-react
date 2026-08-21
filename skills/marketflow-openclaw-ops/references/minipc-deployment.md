# Future MiniPC handoff and deployment

Current operation is Windows MiniPC at `C:\bitman_marketfloww` with Task
Scheduler. Linux `/srv/marketflow` and systemd are future Linux design only;
do not treat either as the current deployment target. Development stays on
5001, while the current Windows MiniPC launcher/watchdogs use 127.0.0.1:5003.
MCP HTTP is 8765; never use Spring or 8080. Existing 5001 MiniPC helper scripts
are unsafe until reconciled. `INFRASTRUCTURE.md` is authoritative for the
launcher, Flask/tunnel watchdogs, tunnel route, and health endpoints.

Core commit `6fb75cb` leaves automated Telegram transport disabled by default,
but legacy boolean sender paths still have timeout-after-accept ambiguity and
are not integrated with the shared verified-delivery ledger. MiniPC deployment
is blocked until that follow-up is resolved, the full test gate passes, and the
pending verified Telegram operation is completed or explicitly waived.

Fail closed before any future commit/push/deploy request:

1. Require reviewed, committed changes and push only with `git push origin main`.
   Never push to a direct `minipc remote`.
2. On the MiniPC, use only `git pull --ff-only origin main`. Do not use `git reset`,
   `git clean`, autostash, force commands/scripts, or routine task re-registration.
3. Confirm a predeploy backup and data parity. Then pass local health and public health
   gates at both `/healthz` and `/api/health` before calling the handoff
   complete: local is `http://127.0.0.1:5003`; public is
   `https://marketflow-api.bit-man.net`.
4. Deployment is blocked until tracked legacy documentation has completed redaction
   and credential rotation is confirmed. Never reproduce credential-like text.
5. Never copy the main-PC `verified_delivery_receipt.json` ledger, Telegram
   runtime data, raw receipts, or message IDs into Git or the MiniPC handoff.
6. Keep `ALPHA_SCANNER_TELEGRAM_ENABLED=false`,
   `MIROFISH_WORKFLOW_TELEGRAM_ENABLED=false`,
   `ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED=false`, and
   `MIROFISH_AUTO_RUNNER_DRY_RUN=true` unless a separately reviewed follow-up
   replaces every legacy sender with the shared verified-delivery ledger.

Do not connect, push, deploy, restart, or re-register tasks unless separately
authorized by an explicit request.
