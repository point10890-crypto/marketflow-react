# Main-PC verification

Use the verified-alpha operator only from the repository root. The default is a
non-sending preview:

```powershell
.\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py
```

Do not send, deploy, restart, connect remotely, or alter runtime data during
validation. Check the preview's freshness and validity evidence; a stale or
invalid result must be handled only as `검출 보류`, never as a directional
candidate.

OpenClaw is independent of Telegram and must remain exactly 19 MarketFlow
read-only tools, zero mutation tools, zero bindings, sandbox `all`, workspace
access `none`, and mutation env false. Any future agent must deny mutations;
do not add Telegram/OpenClaw coupling.

Ports are environment-specific: development Flask is 5001, the current Windows
MiniPC Flask launcher/watchdogs are 5003, MCP HTTP is 8765, and 8080 is
forbidden for MarketFlow.
