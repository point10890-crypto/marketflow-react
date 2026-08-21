# Future MiniPC handoff and deployment

Current operation is Windows MiniPC at `C:\bitman_marketfloww` with Task
Scheduler. Linux `/srv/marketflow` and systemd are future Linux design only;
do not treat either as the current deployment target. Development stays on
5001, while the current Windows MiniPC launcher/watchdogs use 127.0.0.1:5003.
MCP HTTP is 8765; never use Spring or 8080. Existing 5001 MiniPC helper scripts
are unsafe until reconciled.

Fail closed before any future commit/push/deploy request:

1. Require reviewed, committed changes and push only with `git push origin main`.
   Never push to a direct `minipc remote`.
2. On the MiniPC, use only `git pull --ff-only origin main`. Do not use `git reset`,
   `git clean`, autostash, force commands/scripts, or routine task re-registration.
3. Confirm a predeploy backup and data parity. Then pass local health and public health
   gates before calling the handoff complete.
4. Deployment is blocked until tracked legacy documentation has completed redaction
   and credential rotation is confirmed. Never reproduce credential-like text.

Do not connect, push, deploy, restart, or re-register tasks unless separately
authorized by an explicit request.
