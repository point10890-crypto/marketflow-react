"""Contract checks for the committed MarketFlow OpenClaw operator skill."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import re
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "marketflow-openclaw-ops"
INSTALLER = ROOT / "scripts" / "install_marketflow_codex_skill.ps1"
VERIFIER = SKILL / "scripts" / "verify_openclaw_readonly.py"
REFERENCE_NAMES = (
    "main-pc-validation.md",
    "telegram-delivery.md",
    "minipc-deployment.md",
    "operational-state.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _corpus() -> str:
    return "\n".join(_read(SKILL / "SKILL.md").lower() for _ in [0]) + "\n" + "\n".join(
        _read(SKILL / "references" / name).lower() for name in REFERENCE_NAMES
    )


def _powershell_code_lines(text: str) -> list[str]:
    """Return non-empty command lines from PowerShell markdown blocks."""
    blocks = re.findall(r"```powershell\n(.*?)```", text, flags=re.DOTALL)
    return [line.strip() for block in blocks for line in block.splitlines() if line.strip()]


def _load_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("marketflow_openclaw_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verification_payloads(tmp_path: Path) -> dict[str, Any]:
    repo = tmp_path / "repo"
    workspace = repo / "integrations" / "openclaw" / "workspace"
    main_workspace = tmp_path / "openclaw" / "workspace"
    main_agent_dir = tmp_path / "openclaw" / "agents" / "main" / "agent"
    target_agent_dir = tmp_path / "openclaw" / "agents" / "marketflow" / "agent"
    tool_names = [f"read_tool_{index:02d}" for index in range(19)]
    prefixed_tools = [f"marketflow__{name}" for name in tool_names]
    target_profile = {
        "name": "MarketFlow Read-Only",
        "workspace": str(workspace),
        "sandbox": {"mode": "all", "scope": "agent", "workspaceAccess": "none"},
        "skills": ["marketflow-readonly"],
        "tools": {
            "allow": prefixed_tools,
            "deny": ["group:runtime", "group:fs", "message"],
            "sandbox": {"tools": {"alsoAllow": prefixed_tools}},
        },
    }
    server_config = {
        "command": str(repo / ".venv" / "Scripts" / "python.exe"),
        "args": [str(repo / "mirofish_mcp_server.py"), "--transport", "stdio"],
        "cwd": str(repo),
        "env": {
            "PYTHONIOENCODING": "utf-8",
            "MIROFISH_MCP_ALLOW_MUTATION": "false",
        },
        "connectionTimeoutMs": 20_000,
        "requestTimeoutMs": 120_000,
        "supportsParallelToolCalls": False,
        "toolFilter": {
            "include": tool_names,
            "exclude": ["run_mutation"],
        },
        "codex": {"agents": ["marketflow"]},
    }
    return {
        "repo": repo,
        "setup": {
            "service": "marketflow-openclaw-mcp-setup",
            "server_name": "marketflow",
            "agent_id": "marketflow",
            "apply_requested": False,
            "applied": False,
            "config_applied": False,
            "verified": False,
            "workspace_ready": True,
            "mcp_entrypoint_exists": True,
            "python_command_exists": True,
            "non_target_deny": "marketflow__*",
            "server_config": server_config,
            "agent_profile": target_profile,
        },
        "config_validate": {"valid": True, "warnings": []},
        "inventory": [
            {
                "id": "main",
                "workspace": str(main_workspace),
                "agentDir": str(main_agent_dir),
                "bindings": 0,
                "isDefault": True,
                "routes": ["default (no explicit rules)"],
            },
            {
                "id": "marketflow",
                "workspace": str(workspace),
                "agentDir": str(target_agent_dir),
                "bindings": 0,
                "isDefault": False,
                "routes": None,
            },
        ],
        "configured_agents": [
            {"id": "main", "tools": {"deny": ["marketflow__*"]}},
            {
                "id": "marketflow",
                "agentDir": str(target_agent_dir),
                **deepcopy(target_profile),
            },
        ],
        "mcp_show": deepcopy(server_config),
        "probe": {
            "servers": {"marketflow": {"tools": 19}},
            "tools": sorted(prefixed_tools),
            "diagnostics": [],
        },
        "security": {"summary": {"critical": 0, "warn": 1, "info": 0}},
    }


class _VerifierRunner:
    def __init__(self, payloads: dict[str, Any], *, failure: tuple[str, ...] | None = None):
        self.payloads = payloads
        self.failure = failure
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        native = tuple(command[1:])
        if "setup_openclaw_mcp.py" in command[1]:
            key = "setup"
            native = ("setup-preview",)
        else:
            keys = {
                ("config", "validate", "--json"): "config_validate",
                ("agents", "list", "--bindings", "--json"): "inventory",
                ("config", "get", "agents.list", "--json"): "configured_agents",
                ("mcp", "show", "marketflow", "--json"): "mcp_show",
                ("mcp", "doctor", "marketflow", "--probe"): None,
                ("mcp", "probe", "marketflow", "--json"): "probe",
                ("skills", "check", "--agent", "marketflow"): None,
                ("security", "audit", "--json"): "security",
            }
            key = keys[native]
        if self.failure == native:
            return subprocess.CompletedProcess(command, 9, stdout="", stderr="sensitive failure")
        stdout = "ok" if key is None else json.dumps(self.payloads[key])
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_skill_routes_every_relevant_mode_to_one_level_references_in_safe_order() -> None:
    """Fails if a combined request is forced to choose only one required reference."""
    text = _read(SKILL / "SKILL.md")
    assert text.startswith("---\nname: marketflow-openclaw-ops\n")
    assert "description: Use when" in text
    for name in REFERENCE_NAMES:
        assert f"references/{name}" in text
    assert "Read every relevant reference" in text
    assert text.index("references/operational-state.md") < text.index(
        "references/main-pc-validation.md"
    )
    assert text.index("references/main-pc-validation.md") < text.index(
        "references/telegram-delivery.md"
    )
    assert text.index("references/telegram-delivery.md") < text.index(
        "references/minipc-deployment.md"
    )


def test_telegram_reference_requires_preview_confirmation_and_private_only_delivery() -> None:
    """Fails if delivery is not bound to the exact previewed run and digest."""
    text = _read(SKILL / "references" / "telegram-delivery.md")
    normalized = " ".join(text.split()).lower()
    preview = ".\\.venv\\Scripts\\python.exe scripts/run_verified_alpha_telegram.py"
    send = (
        f"{preview} --send --run-id $preview.run_id "
        "--message-digest $preview.message_digest "
        "--confirm SEND_VERIFIED_ALPHA_TELEGRAM"
    )
    verified_alpha_lines = [
        line
        for line in _powershell_code_lines(text)
        if "scripts/run_verified_alpha_telegram.py" in line
    ]
    assert f"$preview = {preview} | ConvertFrom-Json" in verified_alpha_lines
    assert send in verified_alpha_lines
    assert verified_alpha_lines == [f"$preview = {preview} | ConvertFrom-Json", send]
    assert "private" in normalized
    assert "검출 보류" in text
    assert "stale" in normalized
    assert "invalid" in normalized
    assert "directional candidate" in normalized
    assert "invalid runs never send" in normalized
    assert "persists scanner run" in normalized
    assert "artifacts" in normalized
    assert "verified_delivery_receipt.json" in text
    assert "must persist locally" in normalized
    assert "never print, copy, stage, or commit" in normalized


def test_skill_preserves_openclaw_ports_and_separation_invariants() -> None:
    """Fails if a dangerous tool, port, or Telegram/OpenClaw coupling is introduced."""
    corpus = _corpus()
    for required in (
        "19 marketflow read-only tools",
        "zero mutation tools",
        "zero bindings",
        "sandbox `all`",
        "workspace access `none`",
        "mutation env false",
        "future agent",
        "no telegram/openclaw coupling",
        "5001",
        "5003",
        "8765",
        "8080",
    ):
        assert required in corpus


def test_main_pc_reference_routes_openclaw_checks_through_the_fail_fast_verifier() -> None:
    """Fails if the operator can substitute an unparsed command transcript."""
    text = _read(SKILL / "references" / "main-pc-validation.md")
    normalized = " ".join(text.split()).lower()
    for required in (
        ".\\.venv\\Scripts\\python.exe skills/marketflow-openclaw-ops/scripts/verify_openclaw_readonly.py",
        "parsed fail-fast verifier",
        "every command exit code",
        "agents.list",
        "mcp show",
        "every non-target agent",
        "agentdir/workspace non-overlap",
        "mcp ownership",
        "19/0/0/all/none/mutation false",
        "no apply",
        "future explicitly authorized configuration change",
    ):
        assert required.lower() in normalized


def test_openclaw_verifier_parses_every_live_read_only_gate_and_sanitizes_output(
    tmp_path: Path,
) -> None:
    """Removing a native check or returning raw config must fail this contract."""
    module = _load_verifier()
    payloads = _verification_payloads(tmp_path)
    runner = _VerifierRunner(payloads)

    result = module.verify_openclaw_readonly(
        repo_root=payloads["repo"], openclaw_command="openclaw-test", runner=runner
    )

    assert result == {
        "ok": True,
        "status": "verified_read_only",
        "commands": [
            {"name": "setup_preview", "exit_code": 0},
            {"name": "config_validate", "exit_code": 0},
            {"name": "agents_list", "exit_code": 0},
            {"name": "agents_config", "exit_code": 0},
            {"name": "mcp_show", "exit_code": 0},
            {"name": "mcp_doctor", "exit_code": 0},
            {"name": "mcp_probe", "exit_code": 0},
            {"name": "skills_check", "exit_code": 0},
            {"name": "security_audit", "exit_code": 0},
        ],
        "invariants": {
            "tool_count": 19,
            "mutation_tool_count": 0,
            "binding_count": 0,
            "sandbox": "all",
            "workspace_access": "none",
            "mutation_env": False,
            "non_target_deny_count": 1,
            "security_critical": 0,
        },
    }
    rendered = json.dumps(result).lower()
    assert str(payloads["repo"]).lower() not in rendered
    assert "sensitive" not in rendered
    native_calls = [tuple(call[1:]) for call in runner.calls[1:]]
    assert native_calls == [
        ("config", "validate", "--json"),
        ("agents", "list", "--bindings", "--json"),
        ("config", "get", "agents.list", "--json"),
        ("mcp", "show", "marketflow", "--json"),
        ("mcp", "doctor", "marketflow", "--probe"),
        ("mcp", "probe", "marketflow", "--json"),
        ("skills", "check", "--agent", "marketflow"),
        ("security", "audit", "--json"),
    ]
    flattened = " ".join(part for call in runner.calls for part in call).lower()
    assert "--apply" not in flattened
    assert "config set" not in flattened


@pytest.mark.parametrize(
    ("mutate", "failed_check"),
    [
        (
            lambda payloads: payloads["configured_agents"][0]["tools"].update(deny=[]),
            "non_target_deny_missing",
        ),
        (
            lambda payloads: payloads["inventory"][1].update(bindings=1),
            "binding_present",
        ),
        (
            lambda payloads: payloads["inventory"][1].update(isDefault=True),
            "default_agent_invalid",
        ),
        (
            lambda payloads: payloads["inventory"][1].update(
                agentDir=str(Path(payloads["inventory"][0]["workspace"]) / "nested")
            ),
            "agent_paths_overlap",
        ),
        (
            lambda payloads: payloads["configured_agents"][1]["sandbox"].update(mode="host"),
            "target_profile_mismatch",
        ),
        (
            lambda payloads: payloads["configured_agents"][1]["sandbox"].update(
                workspaceAccess="read"
            ),
            "target_profile_mismatch",
        ),
        (
            lambda payloads: payloads["mcp_show"]["env"].update(
                MIROFISH_MCP_ALLOW_MUTATION="true"
            ),
            "mcp_config_mismatch",
        ),
        (
            lambda payloads: payloads["mcp_show"]["codex"].update(agents=["main"]),
            "mcp_config_mismatch",
        ),
        (
            lambda payloads: payloads["mcp_show"]["toolFilter"]["include"].pop(),
            "mcp_config_mismatch",
        ),
        (
            lambda payloads: payloads["probe"]["tools"].pop(),
            "probe_tool_inventory_mismatch",
        ),
        (
            lambda payloads: payloads["probe"]["diagnostics"].append({"error": "bad"}),
            "probe_diagnostics_present",
        ),
    ],
)
def test_openclaw_verifier_rejects_weakened_live_fixtures(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], Any],
    failed_check: str,
) -> None:
    """Each safety invariant must be enforced by parsed data, not prose."""
    module = _load_verifier()
    payloads = _verification_payloads(tmp_path)
    mutate(payloads)

    result = module.verify_openclaw_readonly(
        repo_root=payloads["repo"],
        openclaw_command="openclaw-test",
        runner=_VerifierRunner(payloads),
    )

    assert result["ok"] is False
    assert result["status"] == "verification_failed"
    assert result["failed_check"] == failed_check
    assert "error" not in result


def test_openclaw_verifier_fails_fast_on_a_native_nonzero_exit(tmp_path: Path) -> None:
    """A failed command must stop later checks without echoing stderr."""
    module = _load_verifier()
    payloads = _verification_payloads(tmp_path)
    runner = _VerifierRunner(payloads, failure=("agents", "list", "--bindings", "--json"))

    result = module.verify_openclaw_readonly(
        repo_root=payloads["repo"], openclaw_command="openclaw-test", runner=runner
    )

    assert result == {
        "ok": False,
        "status": "verification_failed",
        "failed_check": "command_failed",
        "commands": [
            {"name": "setup_preview", "exit_code": 0},
            {"name": "config_validate", "exit_code": 0},
            {"name": "agents_list", "exit_code": 9},
        ],
    }
    assert len(runner.calls) == 3
    assert "sensitive" not in json.dumps(result).lower()


def test_installer_requires_an_existing_same_target_link_to_be_a_junction() -> None:
    """Fails if a same-target symlink can masquerade as the committed junction."""
    text = _read(INSTALLER)
    assert "LinkType" in text
    assert "Junction" in text
    assert "source=" not in text
    assert "destination=" not in text
    assert "C:\\Users\\" not in text
    assert "dynas" not in text.lower()


def test_deployment_reference_fails_closed_on_unsafe_git_platform_and_health_gaps() -> None:
    """Fails if deployment can bypass origin-only, safety, or parity gates."""
    text = _read(SKILL / "references" / "minipc-deployment.md").lower()
    for required in (
        "git push origin main",
        "git pull --ff-only origin main",
        "minipc remote",
        "git reset",
        "git clean",
        "autostash",
        "force",
        "task re-registration",
        "windows",
        "future linux",
        "backup",
        "data parity",
        "local health",
        "public health",
        "redaction",
        "rotation",
    ):
        assert required in text


def test_operational_state_records_current_windows_contract_and_safe_blockers() -> None:
    """Fails if the saved handoff drops the current contract or secret blocker."""
    text = _read(SKILL / "references" / "operational-state.md").lower()
    for required in (
        "windows minipc",
        "c:\\bitman_marketfloww",
        "5003",
        "5001",
        "/srv/marketflow",
        "future linux",
        "older 5001 minipc helper",
        "redaction",
        "credential rotation",
        "blocked",
    ):
        assert required in text


def test_infrastructure_ssot_separates_windows_production_from_local_development() -> None:
    """A MiniPC command or tunnel route must never silently fall back to dev port 5001."""
    text = _read(ROOT / "INFRASTRUCTURE.md")
    normalized = " ".join(text.split())
    for required in (
        "Windows MiniPC production",
        "C:\\bitman_marketfloww",
        "127.0.0.1:5003",
        "scripts\\start_flask_task.ps1",
        "scripts\\flask_watchdog_v2.ps1",
        "scripts\\tunnel_watchdog.ps1",
        "https://marketflow-api.bit-man.net/healthz",
        "Local development only",
        "127.0.0.1:5001",
        "Future Linux design only",
        "/srv/marketflow",
    ):
        assert required in normalized
    assert "marketflow-api.bit-man.net` | → | `http://127.0.0.1:5003`" in normalized
    assert "marketflow-api.bit-man.net` | → | `http://localhost:5001`" not in normalized
    assert "현행 — JUST BUY 라인 포함" not in text
    assert "marketflow-{flask,scheduler,backup}.service" not in text
    scheduler_section = text.split("## 5. 스케줄러", 1)[1].split("## 6.", 1)[0]
    assert "Get-ScheduledTask -TaskName MarketFlow-Scheduler" in scheduler_section
    assert "scheduler.py --daemon &" not in scheduler_section
    assert "taskkill" not in scheduler_section.lower()
    change_section = text.split("## 8. 변경 절차", 1)[1]
    assert "별도로 명시적으로" in change_section
    assert "재배포" not in change_section


def test_release_docs_preserve_hardware_gate_and_truthful_task_status() -> None:
    """Fails if an agent can prescribe host changes or overstate the release gate."""
    state = _read(SKILL / "references" / "operational-state.md")
    spec = _read(
        ROOT / "docs" / "superpowers" / "specs" / "2026-08-21-verified-alpha-telegram-ops-design.md"
    )
    plan_path = ROOT / "docs" / "superpowers" / "plans" / "2026-08-21-verified-alpha-telegram-ops.md"
    plan = _read(plan_path)
    for text in (state, spec, plan):
        normalized = " ".join(text.split())
        for required in (
            "93 WHEA hardware errors",
            "Application Error max RecordId 3440795",
            "WHEA-Logger max RecordId 101636",
            "fresh pre-test maximum",
            "FAIL if any matching Python Application Error Event ID 1000 or WHEA-Logger event has RecordId greater than its fresh pre-test maximum",
            "pass only if none do",
            "operator-only recommendation",
            "separate explicit authorization",
            "vendor recovery/BitLocker/virtualization prep",
            "three consecutive",
        ):
            assert required in normalized
        assert "requires greater RecordIds" not in normalized
    for text in (state, plan):
        normalized = " ".join(text.split())
        assert "18 Python Application Error crashes (python.exe 16 + python3.13.exe 2)" in normalized
        assert "17 Python Application Error crashes" not in normalized
    normalized_plan = " ".join(plan.split())
    assert "ed65734" in normalized_plan
    assert "71 verified-delivery" in normalized_plan
    assert "149 related regression" in normalized_plan
    assert "final full pytest rerun is not yet claimed" in normalized_plan
    assert "C:\\Users\\" not in plan
    assert "$env:USERPROFILE" in plan

    task_four = plan.split("### Task 4:", 1)[1]
    for completed_step in (2, 3):
        assert f"- [x] **Step {completed_step}:" in task_four
    for incomplete_step in (1, 4, 5):
        assert f"- [ ] **Step {incomplete_step}:" in task_four


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_installer_creates_same_source_junction_idempotently_and_refuses_unrelated_destination(
    tmp_path: Path,
) -> None:
    """Fails if installer replaces or copies a destination instead of safely linking it."""
    destination_root = tmp_path / "skills-root"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(INSTALLER),
        "-DestinationRoot",
        str(destination_root),
    ]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == "status=created-junction"
    destination = destination_root / "marketflow-openclaw-ops"
    assert destination.is_dir()
    assert destination.resolve() == SKILL.resolve()
    link_type = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-Item -LiteralPath '{destination}').LinkType",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert link_type.returncode == 0, link_type.stderr
    assert link_type.stdout.strip().lower() == "junction"

    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "status=existing-junction"

    destination.rmdir()
    destination.mkdir()
    (destination / "unrelated.txt").write_text("do not replace", encoding="utf-8")
    refused = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert refused.returncode != 0
    assert (destination / "unrelated.txt").read_text(encoding="utf-8") == "do not replace"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_installer_rejects_a_same_target_symbolic_link_when_supported(tmp_path: Path) -> None:
    """Fails if a same-target symbolic link is accepted as the required junction."""
    destination_root = tmp_path / "skills-root"
    destination = destination_root / "marketflow-openclaw-ops"
    destination_root.mkdir()
    symbolic_link = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                f"New-Item -ItemType SymbolicLink -Path '{destination}' "
                f"-Target '{SKILL}' -ErrorAction Stop | Out-Null"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if symbolic_link.returncode != 0:
        pytest.skip("symbolic-link creation is unavailable on this platform")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(INSTALLER),
        "-DestinationRoot",
        str(destination_root),
    ]
    rejected_link = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert rejected_link.returncode != 0
    assert destination.resolve() == SKILL.resolve()
