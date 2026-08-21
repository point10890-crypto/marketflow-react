# Main-PC verification

Use the verified-alpha operator only from the repository root. Before every
verified one-shot preview or send, run the read-only exclusivity verifier:

```powershell
.\.venv\Scripts\python.exe skills/marketflow-openclaw-ops/scripts/verify_delivery_exclusivity.py
```

It reads only the four relevant values from process environment and `.env`,
then returns each resolved sanitized boolean and its source without raw values,
paths, or secrets. Continue only when it exits 0 and reports exactly:

- `ALPHA_SCANNER_TELEGRAM_ENABLED=false`
- `MIROFISH_WORKFLOW_TELEGRAM_ENABLED=false`
- `ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED=false`
- `MIROFISH_AUTO_RUNNER_DRY_RUN=true`

Only explicit known true/false tokens are valid. Empty, unknown, `$`-bearing,
or interpolated values fail closed with `invalid_flag_value`; do not rewrite or
expand them to make the gate pass.

The default operator action is a non-sending preview, but preview persists
scanner run artifacts for validation and later run/digest-bound approval:

```powershell
.\.venv\Scripts\python.exe scripts/run_verified_alpha_telegram.py
```

Do not send, deploy, restart, or connect remotely during validation. Check the
preview's freshness and validity evidence. Invalid runs never send. A valid run
blocked only by stale alert-required data is `검출 보류`, never a directional
candidate.

`scripts/verify_auto_runner_e2e.py --send` fails closed and is not an alternate
delivery path. Any real delivery uses only the verified one-shot operator and
its preview/run/digest/confirmation contract.

Verify OpenClaw with the committed parsed fail-fast verifier:

```powershell
.\.venv\Scripts\python.exe skills/marketflow-openclaw-ops/scripts/verify_openclaw_readonly.py
```

The verifier checks every command exit code and parses the setup preview plus
live `agents.list`, configured agents, live `mcp show`, doctor/probe, skills,
and security results. It fails on a nonzero exit, malformed JSON, any binding,
target/default mismatch, agentDir/workspace non-overlap violation, missing
`marketflow__*` deny on every non-target agent, wrong MCP ownership/config,
mutation env true, tool drift, probe diagnostics, or security critical finding.

Pass only when the sanitized result is `ok: true` and reports
19/0/0/all/none/mutation false: 19 read-only MarketFlow tools, 0 mutation tools,
0 bindings, sandbox `all`, workspace access `none`, and mutation env false.
The verifier has no apply or mutation command. Use no apply unless a future
explicitly authorized configuration change requires it.

OpenClaw is independent of Telegram and must remain exactly 19 MarketFlow
read-only tools, zero mutation tools, zero bindings, sandbox `all`, workspace
access `none`, and mutation env false. Any future agent must deny mutations;
do not add Telegram/OpenClaw coupling.

Ports are environment-specific: development Flask is 5001, the current Windows
MiniPC Flask launcher/watchdogs are 5003, MCP HTTP is 8765, and 8080 is
forbidden for MarketFlow.
