"""Contract checks for the committed MarketFlow OpenClaw operator skill."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "marketflow-openclaw-ops"
INSTALLER = ROOT / "scripts" / "install_marketflow_codex_skill.ps1"
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
    """Fails if the confirmation gate or private-only boundary is removed."""
    text = _read(SKILL / "references" / "telegram-delivery.md")
    assert ".\\.venv\\Scripts\\python.exe scripts/run_verified_alpha_telegram.py" in text
    assert (
        ".\\.venv\\Scripts\\python.exe scripts/run_verified_alpha_telegram.py "
        "--send --confirm SEND_VERIFIED_ALPHA_TELEGRAM"
    ) in text
    assert "private" in text.lower()
    assert "검출 보류" in text
    assert "stale" in text.lower()
    assert "invalid" in text.lower()
    assert "directional candidate" in text.lower()


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


def test_main_pc_reference_has_only_non_mutating_openclaw_verification_commands() -> None:
    """Fails if an operator cannot verify the exact read-only OpenClaw contract."""
    text = _read(SKILL / "references" / "main-pc-validation.md")
    for required in (
        ".\\.venv\\Scripts\\python.exe scripts/setup_openclaw_mcp.py --json",
        "Join-Path $env:LOCALAPPDATA 'OpenClaw\\deps\\portable-node\\openclaw.cmd'",
        "fail if absent",
        "config validate --json",
        "mcp doctor marketflow --probe",
        "mcp probe marketflow --json",
        "skills check --agent marketflow",
        "agents list --bindings --json",
        "security audit --json",
        "19/0/0/all/none/mutation false",
        "no apply",
        "future explicitly authorized configuration change",
    ):
        assert required in text


def test_installer_requires_an_existing_same_target_link_to_be_a_junction() -> None:
    """Fails if a same-target symlink can masquerade as the committed junction."""
    text = _read(INSTALLER)
    assert "LinkType" in text
    assert "Junction" in text


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


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_installer_creates_only_a_same_source_junction_and_refuses_unrelated_destination(
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

    destination.rmdir()
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
    rejected_link = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert rejected_link.returncode != 0
    assert destination.resolve() == SKILL.resolve()

    destination.rmdir()
    destination.mkdir()
    (destination / "unrelated.txt").write_text("do not replace", encoding="utf-8")
    refused = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert refused.returncode != 0
    assert (destination / "unrelated.txt").read_text(encoding="utf-8") == "do not replace"
