"""Cloud scheduler Crypto isolation contract tests."""

from __future__ import annotations

import importlib.util
import builtins
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.utils import scheduler as cloud_scheduler


@pytest.fixture(autouse=True)
def _block_legacy_provider_imports(monkeypatch):
    """Keep the RED path from reaching live Gate/VCP providers."""
    original_import = builtins.__import__
    attempts: list[str] = []

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"market_gate", "run_scan"}:
            attempts.append(name)
            raise ImportError("legacy provider import blocked by test")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    yield attempts


class _CompletedParent:
    def __init__(self, returncode: int = 0) -> None:
        self.pid = 43210
        self.returncode = returncode
        self.wait_timeouts: list[int] = []

    def wait(self, timeout: int) -> int:
        self.wait_timeouts.append(timeout)
        return self.returncode


def _install_parent(monkeypatch: pytest.MonkeyPatch, returncode: int = 0):
    captured: dict[str, object] = {}
    process = _CompletedParent(returncode)

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(cloud_scheduler.subprocess, "Popen", fake_popen)
    return process, captured


def test_cloud_crypto_bridge_isolated_command_does_not_load_legacy_modules(
    monkeypatch,
    _block_legacy_provider_imports,
):
    """Regression: Flask must never import Gate/VCP native modules itself."""
    monkeypatch.delitem(sys.modules, "market_gate", raising=False)
    monkeypatch.delitem(sys.modules, "run_scan", raising=False)
    process, captured = _install_parent(monkeypatch)

    assert cloud_scheduler._run_crypto_pipeline() is True

    assert "market_gate" not in sys.modules
    assert "run_scan" not in sys.modules
    assert _block_legacy_provider_imports == []
    command = captured["command"]
    kwargs = captured["kwargs"]
    assert command == [
        sys.executable,
        str(Path(cloud_scheduler.BASE_DIR) / "scripts" / "run_crypto_pipeline_parent.py"),
    ]
    assert kwargs["cwd"] == cloud_scheduler.BASE_DIR
    assert kwargs["shell"] is False
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["env"]["PYTHONPATH"] == cloud_scheduler.BASE_DIR
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert kwargs["env"]["PYTHONUTF8"] == "1"
    assert kwargs["env"]["PYTHON_DOTENV_DISABLED"] == "1"
    assert kwargs["env"]["MARKETFLOW_PRESERVE_ENV"] == "1"
    assert kwargs["env"]["KR_MARKET_DIR"] == cloud_scheduler.BASE_DIR
    assert kwargs["env"]["MARKETFLOW_SCHEDULER_LOG_FILE"] == os.path.join(
        cloud_scheduler.LOG_DIR, "crypto_pipeline_cloud_parent.log"
    )
    assert process.wait_timeouts == [cloud_scheduler._CRYPTO_PARENT_TIMEOUT_SECONDS]
    if os.name == "nt":
        assert kwargs["creationflags"] == (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        assert "start_new_session" not in kwargs
    else:
        assert kwargs["start_new_session"] is True
        assert "creationflags" not in kwargs


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [(0, True), (1, False), (2, False), (-9, False)],
)
def test_cloud_crypto_bridge_is_all_or_nothing(monkeypatch, returncode, expected):
    """Regression: a partial or crashed parent must never count as success."""
    _install_parent(monkeypatch, returncode)
    monkeypatch.setattr(cloud_scheduler, "_terminate_crypto_parent_tree", lambda _process: None)

    assert cloud_scheduler._run_crypto_pipeline() is expected


def test_cloud_crypto_timeout_kills_process_tree_and_reaps_parent(monkeypatch):
    """Regression: a timed-out bridge must not leave the analysis tree orphaned."""
    calls: list[tuple[object, ...]] = []

    class TimedOutParent:
        pid = 54321

        def __init__(self) -> None:
            self.wait_count = 0

        def wait(self, timeout: int) -> int:
            self.wait_count += 1
            calls.append(("wait", timeout))
            if self.wait_count == 1:
                raise subprocess.TimeoutExpired(["parent"], timeout)
            return -9

        def kill(self) -> None:
            calls.append(("kill",))

    process = TimedOutParent()
    monkeypatch.setattr(cloud_scheduler.subprocess, "Popen", lambda *_a, **_k: process)

    if os.name == "nt":
        def fake_run(command, **kwargs):
            calls.append(("taskkill", tuple(command), kwargs))
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cloud_scheduler.subprocess, "run", fake_run)
    else:
        monkeypatch.setattr(cloud_scheduler.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(
            cloud_scheduler.os,
            "killpg",
            lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        )

    assert cloud_scheduler._run_crypto_pipeline() is False

    if os.name == "nt":
        taskkill = next(call for call in calls if call[0] == "taskkill")
        assert taskkill[1] == ("taskkill", "/PID", str(process.pid), "/T", "/F")
        assert taskkill[2]["shell"] is False
        assert taskkill[2]["stdout"] is subprocess.DEVNULL
        assert taskkill[2]["stderr"] is subprocess.DEVNULL
        assert taskkill[2]["creationflags"] == subprocess.CREATE_NO_WINDOW
    else:
        assert any(call[0] == "killpg" and call[1] == process.pid for call in calls)
    assert calls[-1] == ("wait", cloud_scheduler._CRYPTO_PARENT_REAP_TIMEOUT_SECONDS)


def test_cloud_crypto_unexpected_wait_error_also_kills_and_reaps(monkeypatch):
    """Regression: any wait failure after spawn must close the process tree."""
    calls: list[tuple[object, ...]] = []

    class BrokenWaitParent:
        pid = 65432

        def __init__(self) -> None:
            self.wait_count = 0

        def wait(self, timeout: int) -> int:
            self.wait_count += 1
            calls.append(("wait", timeout))
            if self.wait_count == 1:
                raise OSError("wait handle failed")
            return -9

        def kill(self) -> None:
            calls.append(("kill",))

    process = BrokenWaitParent()
    monkeypatch.setattr(cloud_scheduler.subprocess, "Popen", lambda *_a, **_k: process)
    if os.name == "nt":
        monkeypatch.setattr(
            cloud_scheduler.subprocess,
            "run",
            lambda command, **_kwargs: calls.append(("taskkill", tuple(command)))
            or SimpleNamespace(returncode=0),
        )
    else:
        monkeypatch.setattr(cloud_scheduler.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(
            cloud_scheduler.os,
            "killpg",
            lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        )

    assert cloud_scheduler._run_crypto_pipeline() is False
    assert any(call[0] in {"taskkill", "killpg"} for call in calls)
    assert calls[-1] == ("wait", cloud_scheduler._CRYPTO_PARENT_REAP_TIMEOUT_SECONDS)


def test_cloud_crypto_baseexception_wait_error_also_kills_and_reaps(monkeypatch):
    calls: list[tuple[object, ...]] = []

    class InterruptedParent:
        pid = 66543

        def __init__(self) -> None:
            self.wait_count = 0

        def wait(self, timeout: int) -> int:
            self.wait_count += 1
            calls.append(("wait", timeout))
            if self.wait_count == 1:
                raise KeyboardInterrupt
            return -9

        def kill(self) -> None:
            calls.append(("kill",))

    process = InterruptedParent()
    monkeypatch.setattr(cloud_scheduler.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(
        cloud_scheduler,
        "_terminate_crypto_parent_tree",
        lambda child: calls.append(("terminate", child.pid)),
    )

    assert cloud_scheduler._run_crypto_pipeline() is False
    assert ("terminate", process.pid) in calls


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill fallback contract")
def test_cloud_crypto_tree_cleanup_falls_back_when_taskkill_fails(monkeypatch):
    calls = []
    process = SimpleNamespace(
        pid=67543,
        kill=lambda: calls.append(("kill",)),
        wait=lambda timeout: calls.append(("wait", timeout)),
    )
    monkeypatch.setattr(
        cloud_scheduler.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1),
    )

    cloud_scheduler._terminate_crypto_parent_tree(process)

    assert ("kill",) in calls
    assert ("wait", cloud_scheduler._CRYPTO_PARENT_REAP_TIMEOUT_SECONDS) in calls


def _load_parent_bridge(monkeypatch, fake_scheduler):
    bridge_path = Path(cloud_scheduler.BASE_DIR) / "scripts" / "run_crypto_pipeline_parent.py"
    monkeypatch.setitem(sys.modules, "scheduler", fake_scheduler)
    spec = importlib.util.spec_from_file_location("test_run_crypto_pipeline_parent", bridge_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parent_bridge_prioritizes_project_root_for_scheduler_import(monkeypatch):
    """Regression: a future scripts/scheduler.py must not shadow the root module."""
    project_root = Path(cloud_scheduler.BASE_DIR)
    scripts_dir = project_root / "scripts"
    remaining = [
        item
        for item in sys.path
        if item not in {str(project_root), str(scripts_dir)}
    ]
    monkeypatch.setattr(sys, "path", [str(scripts_dir), str(project_root), *remaining])
    bridge = _load_parent_bridge(
        monkeypatch,
        SimpleNamespace(run_crypto_pipeline=lambda **_kwargs: True),
    )

    assert bridge.PROJECT_ROOT == project_root
    assert sys.path[0] == str(project_root)


def test_parent_bridge_import_does_not_leak_runtime_environment(monkeypatch):
    monkeypatch.delenv("MARKETFLOW_CRYPTO_INHERIT_PROCESS_GROUP", raising=False)
    monkeypatch.delenv("MARKETFLOW_PRESERVE_ENV", raising=False)

    _load_parent_bridge(
        monkeypatch,
        SimpleNamespace(run_crypto_pipeline=lambda **_kwargs: True),
    )

    assert "MARKETFLOW_CRYPTO_INHERIT_PROCESS_GROUP" not in os.environ
    assert "MARKETFLOW_PRESERVE_ENV" not in os.environ


def test_parent_bridge_turns_scheduler_import_failure_into_silent_exit(monkeypatch, capsys):
    """Regression: root import errors must not escape as provider tracebacks."""
    bridge_path = Path(cloud_scheduler.BASE_DIR) / "scripts" / "run_crypto_pipeline_parent.py"
    monkeypatch.delitem(sys.modules, "scheduler", raising=False)
    original_import = builtins.__import__

    def failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scheduler":
            raise RuntimeError("sensitive import failure")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    spec = importlib.util.spec_from_file_location("test_failed_crypto_parent", bridge_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main() == 1
    assert capsys.readouterr() == ("", "")


def test_parent_bridge_forces_no_sync_and_no_notifications(monkeypatch, capsys):
    """Regression: the cloud bridge must not Git-sync or notify Telegram."""
    monkeypatch.delenv("MARKETFLOW_CRYPTO_INHERIT_PROCESS_GROUP", raising=False)
    calls: list[tuple[dict[str, bool], str | None]] = []
    fake_scheduler = SimpleNamespace(
        run_crypto_pipeline=lambda **kwargs: calls.append(
            (kwargs, os.environ.get("MARKETFLOW_CRYPTO_INHERIT_PROCESS_GROUP"))
        ) or True,
    )
    bridge = _load_parent_bridge(monkeypatch, fake_scheduler)

    assert bridge.main() == 0
    assert calls == [
        ({"skip_sync": True, "no_notify": True}, "1"),
    ]
    assert capsys.readouterr() == ("", "")


def test_cloud_nonzero_parent_exit_triggers_residual_tree_cleanup(monkeypatch):
    calls = []

    class FailedParent:
        pid = os.getpid() + 4200

        def wait(self, timeout):
            calls.append(("wait", timeout))
            return 1

    process = FailedParent()
    monkeypatch.setattr(cloud_scheduler.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(
        cloud_scheduler,
        "_terminate_crypto_parent_tree",
        lambda child: calls.append(("terminate", child.pid)),
    )

    assert cloud_scheduler._run_crypto_pipeline() is False
    assert ("terminate", process.pid) in calls


@pytest.mark.parametrize("outcome", [False, None])
def test_parent_bridge_returns_failure_for_non_true_result(monkeypatch, outcome):
    """Regression: only the root scheduler's literal True may exit successfully."""
    fake_scheduler = SimpleNamespace(run_crypto_pipeline=lambda **_kwargs: outcome)
    bridge = _load_parent_bridge(monkeypatch, fake_scheduler)

    assert bridge.main() == 1


def test_parent_bridge_returns_failure_without_leaking_exception(monkeypatch, capsys):
    """Regression: provider exception details must not reach cloud stdout/stderr."""
    def fail(**_kwargs):
        raise RuntimeError("sensitive provider response")

    bridge = _load_parent_bridge(
        monkeypatch,
        SimpleNamespace(run_crypto_pipeline=fail),
    )

    assert bridge.main() == 1
    assert capsys.readouterr() == ("", "")
