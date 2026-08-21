# MarketFlow OpenClaw integration

This integration registers the existing MiroFish MCP server with a dedicated,
read-only OpenClaw agent. It does not replace MarketFlow's scheduler and it does
not enable Telegram delivery, file or shell access, browser control, workflow
mutation, or order execution.

## Prerequisites

- Install OpenClaw with a Node.js version supported by the current OpenClaw
  release. Follow the official installation guide rather than copying an old
  version pin: <https://docs.openclaw.ai/install>.
- Install the MarketFlow Python dependencies in `.venv`.
- Run these commands from the repository root.

## Preview

Preview the exact agent, MCP server, tool filter, and commands without changing
OpenClaw:

```powershell
.\.venv\Scripts\python.exe scripts\setup_openclaw_mcp.py --json
```

Review the following invariants in the output:

- `MIROFISH_MCP_ALLOW_MUTATION` is `false`.
- `toolFilter.include` contains observation-only tools.
- the agent sandbox uses `workspaceAccess: none`.
- host runtime, filesystem, browser, cron, gateway, messaging, and subagents are
  denied.

## Apply and verify

After installing OpenClaw and initializing its baseline configuration:

```powershell
openclaw setup --baseline
openclaw doctor --generate-gateway-token --non-interactive --yes
.\.venv\Scripts\python.exe scripts\setup_openclaw_mcp.py --apply --json
openclaw config validate
openclaw mcp doctor marketflow --probe
openclaw skills check --agent marketflow
openclaw agents list --json
openclaw security audit
```

Before writing, the setup script verifies the local virtualenv, MCP entrypoint,
managed workspace files, current config, target agent workspace/default/binding
state, workspace and agent-state-directory overlap, and MCP server ownership.
On a fresh baseline it materializes OpenClaw's implicit default agent before
adding MarketFlow, so MarketFlow cannot accidentally become the default. It
then dry-runs and applies one atomic config batch. A conflicting `marketflow`
agent or server is rejected rather than repurposed.

The atomic update is transported through a short-lived UTF-8 batch file, not an
inline command-line payload. The file is removed after both the dry run and
apply attempt, including failures, and setup output reports only a placeholder.
Machine-readable output separates `config_applied` from `verified`, so a
post-write validation or probe failure cannot be mistaken for a no-op.

OpenClaw's `mcp.servers` registry is global. The batch therefore preserves each
existing non-target agent and adds `marketflow__*` to its deny list, while the
target agent sees only the `marketflow-readonly` skill and the 19 exact MCP
tools. Re-run setup after adding another OpenClaw agent; future agents are not
automatically denied by the platform. The script changes no global sandbox MCP
allow-list.

A complete agent turn additionally requires a configured model provider and a
working Docker runtime because this profile intentionally uses
`sandbox.mode: all`. MCP registration and probing do not require either. Do not
weaken the sandbox merely to bypass a missing Docker installation.

## Deliberate boundaries

The OpenClaw profile can inspect scanner state, source freshness, stored
research, Top 3 evidence, and replay-safe performance. All state-changing
MiroFish tools remain excluded, including scan execution, learning refresh,
Telegram sending, and live research workflows. MarketFlow's existing Flask and
scheduler processes continue to own those operations.

Safe artifact reads redact credential-shaped keys and text before returning
content. Starting the MCP process can still refresh existing local GraphRAG
registration/telemetry state; it does not run a scan, workflow, delivery, or
order.
