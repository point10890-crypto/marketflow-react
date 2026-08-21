from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_auto_runner_e2e.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_auto_runner_e2e", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_send_flag_fails_closed_before_loading_runtime(monkeypatch, capsys):
    module = _load_script()
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "--full", "--send"])

    assert module.main() == 3

    output = capsys.readouterr().out
    assert "run_verified_alpha_telegram.py" in output
    assert "SEND_VERIFIED_ALPHA_TELEGRAM" in output
    assert "personal bot" not in output
    assert "AIbain_bot" not in output


def test_script_source_has_no_direct_telegram_transport():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "_send_telegram_long" not in source
    assert "send_workflow_top3" not in source
    assert "--full --send" not in source
