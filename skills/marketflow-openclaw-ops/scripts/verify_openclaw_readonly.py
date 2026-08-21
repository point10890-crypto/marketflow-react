"""Fail-fast, read-only verification of the live MarketFlow OpenClaw boundary."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


COMMAND_TIMEOUT_SECONDS = 180
TARGET_AGENT = "marketflow"
PINNED_READ_ONLY_TOOLS = (
    "get_autonomous_status",
    "get_mcp_security_policy",
    "get_market_clock",
    "get_pipeline_operating_snapshot",
    "get_mcp_resource_snapshot",
    "get_repository_state",
    "list_recent_scanner_runs",
    "get_alpha_research_snapshot",
    "list_recent_workflows",
    "list_safe_artifacts",
    "read_safe_artifact",
    "get_top3_summary",
    "get_alpha_scanner_diagnostics",
    "get_tradingview_provider_status",
    "get_outcomes_kpi",
    "get_pipeline_today_snapshot",
    "get_backtest_summary",
    "resolve_target",
    "search_targets",
)
PINNED_MUTATING_TOOLS = (
    "run_candidate_detection_alert",
    "run_autonomous_scan_analysis",
    "refresh_learning_feedback",
    "send_latest_workflow_telegram",
    "run_multi_mcp_deep_research",
    "run_multi_mcp_live_market_scan",
)


class _CheckFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def verify_openclaw_readonly(
    *,
    repo_root: str | os.PathLike[str],
    openclaw_command: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Run and parse the complete native read-only verification surface."""
    repo = Path(repo_root).resolve()
    commands: list[dict[str, Any]] = []

    try:
        setup_tools, setup_mutating_tools = _load_canonical_tool_policy(repo)
        _validate_pinned_tool_policy(setup_tools, setup_mutating_tools)
        canonical_tools = list(PINNED_READ_ONLY_TOOLS)
        mutating_tools = list(PINNED_MUTATING_TOOLS)
        setup = _run_json(
            [
                sys.executable,
                str(repo / "scripts" / "setup_openclaw_mcp.py"),
                "--repo-root",
                str(repo),
                "--openclaw-command",
                openclaw_command,
                "--json",
            ],
            name="setup_preview",
            commands=commands,
            runner=runner,
        )
        desired_server, desired_profile = _validate_setup_preview(
            setup,
            canonical_tools=canonical_tools,
            mutating_tools=mutating_tools,
        )

        prefix = _native_prefix(openclaw_command)
        config_validation = _run_json(
            [*prefix, "config", "validate", "--json"],
            name="config_validate",
            commands=commands,
            runner=runner,
        )
        if not isinstance(config_validation, dict) or config_validation.get("valid") is not True:
            raise _CheckFailure("config_invalid")

        inventory = _run_json(
            [*prefix, "agents", "list", "--bindings", "--json"],
            name="agents_list",
            commands=commands,
            runner=runner,
        )
        configured_agents = _run_json(
            [*prefix, "config", "get", "agents.list", "--json"],
            name="agents_config",
            commands=commands,
            runner=runner,
        )
        binding_count = _validate_agents(inventory, configured_agents, desired_profile)

        actual_server = _run_json(
            [*prefix, "mcp", "show", TARGET_AGENT, "--json"],
            name="mcp_show",
            commands=commands,
            runner=runner,
        )
        _validate_mcp_config(actual_server, desired_server)

        _run_text(
            [*prefix, "mcp", "doctor", TARGET_AGENT, "--probe"],
            name="mcp_doctor",
            commands=commands,
            runner=runner,
        )
        probe = _run_json(
            [*prefix, "mcp", "probe", TARGET_AGENT, "--json"],
            name="mcp_probe",
            commands=commands,
            runner=runner,
        )
        _validate_probe(probe, canonical_tools)

        _run_text(
            [*prefix, "skills", "check", "--agent", TARGET_AGENT],
            name="skills_check",
            commands=commands,
            runner=runner,
        )
        security = _run_json(
            [*prefix, "security", "audit", "--json"],
            name="security_audit",
            commands=commands,
            runner=runner,
        )
        critical = _security_critical(security)
        if critical != 0:
            raise _CheckFailure("security_critical_present")

        live_tools = actual_server.get("toolFilter", {}).get("include") or []
        mutation_count = len(set(live_tools).intersection(mutating_tools))
        non_target_count = len(inventory) - 1
        return {
            "ok": True,
            "status": "verified_read_only",
            "commands": commands,
            "invariants": {
                "tool_count": len(canonical_tools),
                "mutation_tool_count": mutation_count,
                "binding_count": binding_count,
                "sandbox": desired_profile["sandbox"]["mode"],
                "workspace_access": desired_profile["sandbox"]["workspaceAccess"],
                "mutation_env": False,
                "non_target_deny_count": non_target_count,
                "security_critical": critical,
            },
        }
    except _CheckFailure as exc:
        return {
            "ok": False,
            "status": "verification_failed",
            "failed_check": exc.code,
            "commands": commands,
        }


def _run_json(
    command: list[str],
    *,
    name: str,
    commands: list[dict[str, Any]],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Any:
    text = _run_text(command, name=name, commands=commands, runner=runner)
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        raise _CheckFailure("invalid_json") from None


def _run_text(
    command: list[str],
    *,
    name: str,
    commands: list[dict[str, Any]],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    try:
        completed = runner(
            command,
            cwd=None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        commands.append({"name": name, "exit_code": None})
        raise _CheckFailure("command_execution_failed") from None
    commands.append({"name": name, "exit_code": completed.returncode})
    if completed.returncode != 0:
        raise _CheckFailure("command_failed")
    return completed.stdout


def _load_canonical_tool_policy(repo: Path) -> tuple[list[str], list[str]]:
    """Load the one committed tool policy used by the configuration writer."""
    source = repo / "scripts" / "setup_openclaw_mcp.py"
    try:
        spec = importlib.util.spec_from_file_location(
            "marketflow_openclaw_canonical_setup",
            source,
        )
        if spec is None or spec.loader is None:
            raise ImportError
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        canonical = getattr(module, "READ_ONLY_TOOLS")
        mutating = getattr(module, "MUTATING_TOOLS")
    except Exception:
        raise _CheckFailure("canonical_tool_policy_invalid") from None
    if (
        not isinstance(canonical, list)
        or len(canonical) != 19
        or len(set(canonical)) != 19
        or not all(isinstance(name, str) and name for name in canonical)
        or not isinstance(mutating, list)
        or not mutating
        or len(set(mutating)) != len(mutating)
        or not all(isinstance(name, str) and name for name in mutating)
        or set(canonical).intersection(mutating)
    ):
        raise _CheckFailure("canonical_tool_policy_invalid")
    return list(canonical), list(mutating)


def _validate_pinned_tool_policy(
    setup_tools: list[str],
    setup_mutating_tools: list[str],
) -> None:
    if (
        setup_tools != list(PINNED_READ_ONLY_TOOLS)
        or setup_mutating_tools != list(PINNED_MUTATING_TOOLS)
    ):
        raise _CheckFailure("canonical_tool_policy_mismatch")


def _validate_setup_preview(
    setup: Any,
    *,
    canonical_tools: list[str],
    mutating_tools: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(setup, dict):
        raise _CheckFailure("setup_preview_invalid")
    required_false = ("apply_requested", "applied", "config_applied", "verified")
    required_true = ("workspace_ready", "mcp_entrypoint_exists", "python_command_exists")
    if (
        setup.get("service") != "marketflow-openclaw-mcp-setup"
        or setup.get("server_name") != TARGET_AGENT
        or setup.get("agent_id") != TARGET_AGENT
        or setup.get("non_target_deny") != "marketflow__*"
        or any(setup.get(key) is not False for key in required_false)
        or any(setup.get(key) is not True for key in required_true)
    ):
        raise _CheckFailure("setup_preview_invalid")

    server = setup.get("server_config")
    profile = setup.get("agent_profile")
    if not isinstance(server, dict) or not isinstance(profile, dict):
        raise _CheckFailure("setup_preview_invalid")
    tool_filter = server.get("toolFilter")
    if not isinstance(tool_filter, dict):
        raise _CheckFailure("setup_preview_invalid")
    tools = tool_filter.get("include")
    excludes = tool_filter.get("exclude")
    if (
        not isinstance(tools, list)
        or len(tools) != 19
        or len(set(tools)) != 19
        or not all(isinstance(name, str) and name for name in tools)
        or not isinstance(excludes, list)
        or set(tools).intersection(excludes)
        or server.get("env", {}).get("MIROFISH_MCP_ALLOW_MUTATION") != "false"
        or server.get("codex", {}).get("agents") != [TARGET_AGENT]
    ):
        raise _CheckFailure("setup_preview_invalid")
    if tools != canonical_tools or excludes != mutating_tools:
        raise _CheckFailure("canonical_tool_policy_mismatch")
    expected_prefixed = [f"{TARGET_AGENT}__{name}" for name in canonical_tools]
    if (
        profile.get("sandbox")
        != {"mode": "all", "scope": "agent", "workspaceAccess": "none"}
        or profile.get("tools", {}).get("allow") != expected_prefixed
        or profile.get("tools", {}).get("sandbox", {}).get("tools", {}).get("alsoAllow")
        != expected_prefixed
    ):
        raise _CheckFailure("setup_preview_invalid")
    return server, profile


def _validate_agents(inventory: Any, configured: Any, profile: dict[str, Any]) -> int:
    if not isinstance(inventory, list) or not isinstance(configured, list) or not inventory:
        raise _CheckFailure("agent_inventory_invalid")
    inventory_by_id = _rows_by_id(inventory, "agent_inventory_invalid")
    configured_by_id = _rows_by_id(configured, "agent_config_invalid")
    if set(inventory_by_id) != set(configured_by_id) or TARGET_AGENT not in inventory_by_id:
        raise _CheckFailure("agent_inventory_mismatch")

    default_ids = [row["id"] for row in inventory if row.get("isDefault") is True]
    if len(default_ids) != 1 or default_ids[0] == TARGET_AGENT:
        raise _CheckFailure("default_agent_invalid")
    try:
        binding_count = sum(_binding_count(row.get("bindings")) for row in inventory)
    except (TypeError, ValueError):
        raise _CheckFailure("binding_inventory_invalid") from None
    if binding_count:
        raise _CheckFailure("binding_present")

    target = inventory_by_id[TARGET_AGENT]
    if target.get("isDefault") is not False or not _paths_equal(
        target.get("workspace"), profile.get("workspace")
    ):
        raise _CheckFailure("target_agent_mismatch")
    _validate_non_overlapping_agent_paths(inventory)

    marker = "marketflow__*"
    for agent_id, row in configured_by_id.items():
        if agent_id == TARGET_AGENT:
            continue
        deny = row.get("tools", {}).get("deny")
        if not isinstance(deny, list) or marker not in deny:
            raise _CheckFailure("non_target_deny_missing")

    actual_target = configured_by_id[TARGET_AGENT]
    for field in ("name", "skills", "sandbox", "tools"):
        if actual_target.get(field) != profile.get(field):
            raise _CheckFailure("target_profile_mismatch")
    if not _paths_equal(actual_target.get("workspace"), profile.get("workspace")):
        raise _CheckFailure("target_profile_mismatch")
    if not _paths_equal(actual_target.get("agentDir"), target.get("agentDir")):
        raise _CheckFailure("target_profile_mismatch")
    return binding_count


def _rows_by_id(rows: list[Any], code: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise _CheckFailure(code)
        if row["id"] in result:
            raise _CheckFailure(code)
        result[row["id"]] = row
    return result


def _binding_count(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, list):
        return len(value)
    raise TypeError


def _validate_non_overlapping_agent_paths(inventory: list[dict[str, Any]]) -> None:
    labeled: list[tuple[str, str]] = []
    for row in inventory:
        for field in ("workspace", "agentDir"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise _CheckFailure("agent_path_missing")
            labeled.append((f"{row['id']}:{field}", value))
    for index, (left_label, left) in enumerate(labeled):
        for right_label, right in labeled[index + 1 :]:
            if left_label == right_label or not _paths_overlap(left, right):
                continue
            raise _CheckFailure("agent_paths_overlap")


def _validate_mcp_config(actual: Any, desired: dict[str, Any]) -> None:
    if not isinstance(actual, dict):
        raise _CheckFailure("mcp_config_mismatch")
    for field, expected in desired.items():
        observed = actual.get(field)
        if field in {"command", "cwd"}:
            if not _paths_equal(observed, expected):
                raise _CheckFailure("mcp_config_mismatch")
        elif observed != expected:
            raise _CheckFailure("mcp_config_mismatch")
    if (
        actual.get("env", {}).get("MIROFISH_MCP_ALLOW_MUTATION") != "false"
        or actual.get("codex", {}).get("agents") != [TARGET_AGENT]
        or len(actual.get("toolFilter", {}).get("include") or []) != 19
    ):
        raise _CheckFailure("mcp_config_mismatch")


def _validate_probe(probe: Any, tools: list[str]) -> None:
    if not isinstance(probe, dict):
        raise _CheckFailure("probe_invalid")
    diagnostics = probe.get("diagnostics")
    if diagnostics != []:
        raise _CheckFailure("probe_diagnostics_present")
    expected = sorted(f"{TARGET_AGENT}__{name}" for name in tools)
    observed = probe.get("tools")
    server = probe.get("servers", {}).get(TARGET_AGENT, {})
    if not isinstance(observed, list) or sorted(observed) != expected or server.get("tools") != 19:
        raise _CheckFailure("probe_tool_inventory_mismatch")


def _security_critical(security: Any) -> int:
    value = security.get("summary", {}).get("critical") if isinstance(security, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _CheckFailure("security_audit_invalid")
    return value


def _paths_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, str) or not isinstance(right, str) or not left or not right:
        return False
    return _normalized_path(left) == _normalized_path(right)


def _paths_overlap(left: str, right: str) -> bool:
    left_norm = _normalized_path(left)
    right_norm = _normalized_path(right)
    try:
        common = os.path.commonpath([left_norm, right_norm])
    except ValueError:
        return False
    return common in {left_norm, right_norm}


def _normalized_path(value: str) -> str:
    expanded = os.path.expanduser(value)
    return os.path.normcase(os.path.abspath(os.path.realpath(expanded)))


def _native_prefix(command: str) -> list[str]:
    suffix = Path(command).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]
    return [command]


def _default_openclaw_command() -> str | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        portable = Path(local_app_data) / "OpenClaw" / "deps" / "portable-node" / "openclaw.cmd"
        if portable.is_file():
            return str(portable)
    return shutil.which("openclaw")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--openclaw-command", default=None)
    args = parser.parse_args(argv)
    openclaw = args.openclaw_command or _default_openclaw_command()
    if not openclaw:
        result = {
            "ok": False,
            "status": "verification_failed",
            "failed_check": "openclaw_cli_absent",
            "commands": [],
        }
    else:
        result = verify_openclaw_readonly(
            repo_root=args.repo_root,
            openclaw_command=openclaw,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
