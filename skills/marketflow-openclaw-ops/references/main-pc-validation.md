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

Verify OpenClaw without applying configuration. From the repository root, run
this non-mutating setup preview:

```powershell
.\.venv\Scripts\python.exe scripts/setup_openclaw_mcp.py --json
```

Derive the portable CLI and fail if absent before running its read-only checks:

```powershell
$openClaw = Join-Path $env:LOCALAPPDATA 'OpenClaw\deps\portable-node\openclaw.cmd'
if (-not (Test-Path -LiteralPath $openClaw -PathType Leaf)) {
    throw 'OpenClaw portable CLI is absent'
}
& $openClaw config validate --json
& $openClaw mcp doctor marketflow --probe
& $openClaw mcp probe marketflow --json
& $openClaw skills check --agent marketflow
& $openClaw agents list --bindings --json
& $openClaw security audit --json
```

Pass only when the reported invariant is 19/0/0/all/none/mutation false:
19 read-only MarketFlow tools, 0 mutation tools, 0 bindings, sandbox `all`,
workspace access `none`, and mutation env false. Use no apply command unless a
future explicitly authorized configuration change requires it.

OpenClaw is independent of Telegram and must remain exactly 19 MarketFlow
read-only tools, zero mutation tools, zero bindings, sandbox `all`, workspace
access `none`, and mutation env false. Any future agent must deny mutations;
do not add Telegram/OpenClaw coupling.

Ports are environment-specific: development Flask is 5001, the current Windows
MiniPC Flask launcher/watchdogs are 5003, MCP HTTP is 8765, and 8080 is
forbidden for MarketFlow.
