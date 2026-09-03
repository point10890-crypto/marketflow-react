"""Regression tests for isolated manual Crypto administration paths."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.routes import common as common_routes
from app.routes import crypto as crypto_routes


class _SuccessfulProcess:
    def __init__(self) -> None:
        self.pid = 43210
        self.returncode = 0
        self.stdout = io.BytesIO(b"")

    def communicate(self, timeout: int):
        return "", ""

    def wait(self, timeout: int | None = None) -> int:
        self.returncode = 0
        return 0


def _install_process_capture(monkeypatch, module):
    calls: list[tuple[str, list[str], dict[str, object]]] = []

    def fake_popen(command, **kwargs):
        calls.append(("popen", list(command), kwargs))
        return _SuccessfulProcess()

    def fake_run(command, **kwargs):
        calls.append(("run", list(command), kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return calls


class _InlineThread:
    def __init__(self, *, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


@pytest.mark.parametrize(
    ("data_type", "bridge_name", "bridge_args"),
    [
        ("crypto_all", "run_crypto_pipeline_parent.py", []),
        ("crypto_gate", "run_crypto_single_step.py", ["gate"]),
        ("crypto_scan", "run_crypto_single_step.py", ["vcp"]),
        ("crypto_briefing", "run_crypto_single_step.py", ["briefing"]),
        ("crypto_prediction", "run_crypto_single_step.py", ["prediction"]),
        ("crypto_risk", "run_crypto_single_step.py", ["risk"]),
        ("crypto_leadlag", "run_crypto_single_step.py", ["lead_lag"]),
    ],
)
def test_common_crypto_updates_use_lock_aware_bridges(
    monkeypatch,
    data_type,
    bridge_name,
    bridge_args,
):
    """Regression: manual SSE Crypto runs must not bypass the worker locks."""
    calls = _install_process_capture(monkeypatch, common_routes)
    monkeypatch.setattr(common_routes.os.path, "exists", lambda _path: True)
    app = Flask(__name__)

    with app.test_request_context(f"/api/system/update-single?type={data_type}"):
        response = common_routes.update_single_data.__wrapped__()
        body = response.get_data(as_text=True)

    assert "completed successfully" in body
    assert len(calls) == 1
    kind, command, kwargs = calls[0]
    assert kind == "popen"
    assert command == [
        sys.executable,
        str(Path(common_routes.BASE_DIR) / "scripts" / bridge_name),
        *bridge_args,
    ]
    assert kwargs["env"]["PYTHONPATH"] == common_routes.BASE_DIR
    assert kwargs["env"]["KR_MARKET_DIR"] == common_routes.BASE_DIR
    assert kwargs["env"]["PYTHON_DOTENV_DISABLED"] == "1"
    assert kwargs["env"]["MARKETFLOW_PRESERVE_ENV"] == "1"
    assert kwargs["env"]["TELEGRAM_BOT_TOKEN"] == ""
    assert kwargs["env"]["TELEGRAM_CHAT_ID"] == ""
    assert kwargs["cwd"] == common_routes.BASE_DIR
    if os.name == "nt":
        assert kwargs["creationflags"] == (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        assert kwargs["start_new_session"] is True


def test_common_crypto_bridge_timeout_kills_tree_and_reports_failure(monkeypatch):
    """Regression: a silent bridge must be bounded and reaped by the SSE API."""
    calls: list[tuple[object, ...]] = []

    class TimedOutBridge:
        pid = 45678
        returncode = None

        def communicate(self, timeout):
            calls.append(("communicate", timeout))
            raise subprocess.TimeoutExpired(["bridge"], timeout)

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if timeout == 30:
                return -9
            raise subprocess.TimeoutExpired(["bridge"], timeout)

        def kill(self):
            calls.append(("kill",))

    monkeypatch.setattr(
        common_routes.subprocess,
        "Popen",
        lambda *_args, **_kwargs: TimedOutBridge(),
    )
    if os.name == "nt":
        monkeypatch.setattr(
            common_routes.subprocess,
            "run",
            lambda command, **kwargs: calls.append(("taskkill", tuple(command), kwargs))
            or SimpleNamespace(returncode=0),
        )
    else:
        monkeypatch.setattr(
            common_routes.os,
            "killpg",
            lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        )
    monkeypatch.setattr(common_routes.os.path, "exists", lambda _path: True)
    monkeypatch.setenv("CRYPTO_ADMIN_SINGLE_STEP_TIMEOUT_SECONDS", "60")
    app = Flask(__name__)

    with app.test_request_context("/api/system/update-single?type=crypto_scan"):
        response = common_routes.update_single_data.__wrapped__()
        body = response.get_data(as_text=True)

    assert "timed out" in body
    assert "completed successfully" not in body
    assert ": keepalive" in body
    assert any(call[0] in {"taskkill", "killpg"} for call in calls)
    assert calls[-1] == ("wait", 30)


def test_common_single_step_timeout_cannot_undercut_inner_runner(monkeypatch):
    """Regression: Flask must leave enough time for bridge rollback."""
    observed = []

    def fake_stream(_script, _args, _name, timeout):
        observed.append(timeout)
        yield "data: done\n\n"

    monkeypatch.setattr(common_routes, "_stream_crypto_bridge", fake_stream)
    monkeypatch.setattr(common_routes.os.path, "exists", lambda _path: True)
    monkeypatch.setenv("CRYPTO_ADMIN_SINGLE_STEP_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("CRYPTO_MARKET_TASK_TIMEOUT", "1200")
    app = Flask(__name__)

    with app.test_request_context("/api/system/update-single?type=crypto_prediction"):
        response = common_routes.update_single_data.__wrapped__()
        response.get_data(as_text=True)

    assert observed == [1290]


def test_common_crypto_bridge_disconnect_kills_and_reaps_tree(monkeypatch):
    """Regression: closing an SSE stream must not orphan its analysis process."""
    calls: list[tuple[object, ...]] = []

    class RunningBridge:
        pid = 56789
        returncode = None

        def communicate(self, timeout):
            raise subprocess.TimeoutExpired(["bridge"], timeout)

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if timeout == 30:
                return -9
            raise subprocess.TimeoutExpired(["bridge"], timeout)

        def kill(self):
            calls.append(("kill",))

    monkeypatch.setattr(
        common_routes.subprocess,
        "Popen",
        lambda *_args, **_kwargs: RunningBridge(),
    )
    if os.name == "nt":
        monkeypatch.setattr(
            common_routes.subprocess,
            "run",
            lambda command, **kwargs: calls.append(("taskkill", tuple(command), kwargs))
            or SimpleNamespace(returncode=0),
        )
    else:
        monkeypatch.setattr(
            common_routes.os,
            "killpg",
            lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        )
    monkeypatch.setattr(common_routes.os.path, "exists", lambda _path: True)
    app = Flask(__name__)

    with app.test_request_context("/api/system/update-single?type=crypto_gate"):
        response = common_routes.update_single_data.__wrapped__()
        iterator = iter(response.response)
        assert "Starting Crypto Market Gate" in next(iterator)
        assert ": keepalive" in next(iterator)
        response.close()

    assert any(call[0] in {"taskkill", "killpg"} for call in calls)
    assert calls[-1] == ("wait", 30)


def test_common_crypto_bridge_close_after_completion_does_not_kill_reused_pid(
    monkeypatch,
):
    """Regression: closing after wait() reaps the child must not target its old PID."""
    calls: list[tuple[object, ...]] = []

    class CompletedBridge:
        pid = 67890
        returncode = 0

        def wait(self, timeout):
            calls.append(("wait", timeout))
            return 0

        def kill(self):
            calls.append(("kill",))

    monkeypatch.setattr(
        common_routes.subprocess,
        "Popen",
        lambda *_args, **_kwargs: CompletedBridge(),
    )
    monkeypatch.setattr(
        common_routes.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(("taskkill", tuple(command)))
        or SimpleNamespace(returncode=0),
    )
    if os.name != "nt":
        monkeypatch.setattr(
            common_routes.os,
            "killpg",
            lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        )
    monkeypatch.setattr(common_routes.os.path, "exists", lambda _path: True)
    app = Flask(__name__)

    with app.test_request_context("/api/system/update-single?type=crypto_all"):
        response = common_routes.update_single_data.__wrapped__()
        iterator = iter(response.response)
        assert "Starting Crypto (Full)" in next(iterator)
        assert "completed successfully" in next(iterator)
        response.close()

    assert not any(call[0] in {"taskkill", "killpg", "kill"} for call in calls)


def test_common_full_update_does_not_report_scheduler_lock_conflict_as_success(
    monkeypatch,
):
    """Regression: scheduler.py's legacy exit-0 lock refusal is still failure."""
    class LockedSchedulerProcess:
        pid = 34567
        returncode = 0
        stdout = io.BytesIO("스케줄러 이미 실행 중\n".encode("utf-8"))

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(
        common_routes.subprocess,
        "Popen",
        lambda *_args, **_kwargs: LockedSchedulerProcess(),
    )
    monkeypatch.setattr(common_routes.os.path, "exists", lambda _path: True)
    app = Flask(__name__)

    with app.test_request_context("/api/system/update-data-stream"):
        response = common_routes.stream_update_data.__wrapped__()
        body = response.get_data(as_text=True)

    assert "Process finished with exit code 0" in body
    assert "Update failed. Check logs." in body
    assert "Update completed successfully." not in body


def test_crypto_run_scan_uses_single_step_bridge(monkeypatch):
    """Regression: the async VCP endpoint must publish the scheduler artifact."""
    calls = _install_process_capture(monkeypatch, crypto_routes)
    monkeypatch.setattr(crypto_routes.threading, "Thread", _InlineThread)
    monkeypatch.setattr(crypto_routes, "load_json_file", lambda _path: {"gate": "GREEN"})
    crypto_routes._running_tasks.clear()
    app = Flask(__name__)

    with app.test_request_context("/api/crypto/run-scan", method="POST", json={}):
        response = crypto_routes.run_scan.__wrapped__()
        payload = response.get_json()

    assert payload["status"] == "started"
    assert crypto_routes._running_tasks[payload["task_id"]]["status"] == "completed"
    assert len(calls) == 1
    kind, command, kwargs = calls[0]
    assert kind == "popen"
    assert command == [
        sys.executable,
        str(Path(crypto_routes.BASE_DIR) / "scripts" / "run_crypto_single_step.py"),
        "vcp",
    ]
    assert kwargs["cwd"] == crypto_routes.BASE_DIR
    assert kwargs["env"]["TELEGRAM_BOT_TOKEN"] == ""
    assert kwargs["env"]["MARKETFLOW_PRESERVE_ENV"] == "1"
    assert kwargs["env"]["MARKETFLOW_SCHEDULER_LOG_FILE"] == str(
        Path(crypto_routes.BASE_DIR) / "logs" / "crypto_manual_bridge.log"
    )
    if os.name == "nt":
        assert kwargs["creationflags"] == (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        assert "start_new_session" not in kwargs
    else:
        assert kwargs["start_new_session"] is True
        assert "creationflags" not in kwargs


def test_crypto_gate_scan_uses_single_step_bridge(monkeypatch):
    """Regression: the Gate endpoint must contend on the shared execution lock."""
    calls = _install_process_capture(monkeypatch, crypto_routes)
    monkeypatch.setattr(
        crypto_routes,
        "load_json_file",
        lambda _path: {"gate": "YELLOW", "score": 50},
    )
    app = Flask(__name__)

    with app.test_request_context("/api/crypto/gate-scan", method="POST"):
        response = crypto_routes.gate_scan.__wrapped__()
        payload = response.get_json()

    assert payload["status"] == "completed"
    assert len(calls) == 1
    kind, command, kwargs = calls[0]
    assert kind == "popen"
    assert command == [
        sys.executable,
        str(Path(crypto_routes.BASE_DIR) / "scripts" / "run_crypto_single_step.py"),
        "gate",
    ]
    assert kwargs["cwd"] == crypto_routes.BASE_DIR
    assert kwargs["env"]["TELEGRAM_CHAT_ID"] == ""


@pytest.mark.parametrize(
    ("route_name", "step"),
    [
        ("run_prediction", "prediction"),
        ("run_risk", "risk"),
        ("run_leadlag", "lead_lag"),
    ],
)
def test_crypto_async_analysis_routes_use_single_step_bridge(
    monkeypatch,
    route_name,
    step,
):
    """Regression: manual analysis steps must not race the full worker."""
    calls = _install_process_capture(monkeypatch, crypto_routes)
    monkeypatch.setattr(crypto_routes.threading, "Thread", _InlineThread)
    monkeypatch.setattr(crypto_routes.os.path, "exists", lambda _path: True)
    crypto_routes._running_tasks.clear()
    app = Flask(__name__)

    with app.test_request_context(f"/api/crypto/{route_name}", method="POST"):
        response = getattr(crypto_routes, route_name).__wrapped__()
        payload = response.get_json()

    assert payload["status"] == "started"
    assert crypto_routes._running_tasks[payload["task_id"]]["status"] == "completed"
    assert len(calls) == 1
    kind, command, kwargs = calls[0]
    assert kind == "popen"
    assert command == [
        sys.executable,
        str(Path(crypto_routes.BASE_DIR) / "scripts" / "run_crypto_single_step.py"),
        step,
    ]
    assert kwargs["cwd"] == crypto_routes.BASE_DIR
    assert kwargs["env"]["TELEGRAM_BOT_TOKEN"] == ""


def test_crypto_briefing_route_uses_bridge_and_preserves_last_good_artifact(monkeypatch):
    """Regression: briefing refresh must lock and must not delete good data first."""
    calls = _install_process_capture(monkeypatch, crypto_routes)
    removed: list[str] = []
    monkeypatch.setattr(crypto_routes.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(crypto_routes.os, "remove", lambda path: removed.append(path))
    monkeypatch.setattr(
        crypto_routes,
        "_generate_live_briefing",
        lambda: (_ for _ in ()).throw(AssertionError("in-process briefing called")),
    )
    monkeypatch.setattr(
        crypto_routes,
        "load_json_file",
        lambda _path: {"timestamp": "2026-09-03T14:00:00", "summary": "fresh"},
    )
    app = Flask(__name__)

    with app.test_request_context("/api/crypto/run-briefing", method="POST"):
        result = crypto_routes.run_briefing.__wrapped__()
        response = result[0] if isinstance(result, tuple) else result
        payload = response.get_json()

    assert payload["status"] == "completed"
    assert payload["briefing"]["summary"] == "fresh"
    assert removed == []
    assert len(calls) == 1
    assert calls[0][0] == "popen"
    assert calls[0][1] == [
        sys.executable,
        str(Path(crypto_routes.BASE_DIR) / "scripts" / "run_crypto_single_step.py"),
        "briefing",
    ]


def test_crypto_single_step_timeout_includes_inner_timeout_and_rollback_grace(
    monkeypatch,
):
    """Regression: an outer timeout must not kill bridge finally first."""
    monkeypatch.setenv("CRYPTO_MARKET_TASK_TIMEOUT", "1200")
    monkeypatch.setenv("CRYPTO_MARKET_BRIEFING_TIMEOUT", "700")

    assert crypto_routes._single_step_bridge_timeout("prediction") == 1290
    assert crypto_routes._single_step_bridge_timeout("risk") == 1290
    assert crypto_routes._single_step_bridge_timeout("lead_lag") == 1290
    assert crypto_routes._single_step_bridge_timeout("briefing") == 790
    assert crypto_routes._single_step_bridge_timeout("vcp") == 900


def test_crypto_route_runner_kills_tree_and_reaps_after_timeout(monkeypatch):
    """Regression: a timed-out admin child must not outlive the Flask request."""
    calls: list[tuple[object, ...]] = []

    class TimedOutProcess:
        pid = 54321

        def communicate(self, timeout: int):
            calls.append(("communicate", timeout))
            raise subprocess.TimeoutExpired(["bridge"], timeout)

        def wait(self, timeout: int):
            calls.append(("wait", timeout))
            return -9

        def kill(self):
            calls.append(("kill",))

    monkeypatch.setattr(
        crypto_routes.subprocess,
        "Popen",
        lambda *_args, **_kwargs: TimedOutProcess(),
    )
    if os.name == "nt":
        monkeypatch.setattr(
            crypto_routes.subprocess,
            "run",
            lambda command, **kwargs: calls.append(("taskkill", tuple(command), kwargs))
            or SimpleNamespace(returncode=0),
        )
    else:
        monkeypatch.setattr(
            crypto_routes.os,
            "killpg",
            lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        )

    with pytest.raises(subprocess.TimeoutExpired):
        crypto_routes._run_python_process(
            "bridge.py",
            args=["vcp"],
            cwd=crypto_routes.BASE_DIR,
            timeout=17,
            suppress_telegram=True,
        )

    if os.name == "nt":
        taskkill = next(call for call in calls if call[0] == "taskkill")
        assert taskkill[1] == ("taskkill", "/PID", "54321", "/T", "/F")
        assert taskkill[2]["shell"] is False
        assert taskkill[2]["stdout"] is subprocess.DEVNULL
        assert taskkill[2]["stderr"] is subprocess.DEVNULL
    else:
        assert any(call[0] == "killpg" and call[1] == 54321 for call in calls)
    assert calls[-1] == ("wait", 30)


def test_crypto_route_runner_kills_tree_after_unexpected_wait_error(monkeypatch):
    """Regression: non-timeout wait failures must also close the process tree."""
    calls: list[tuple[object, ...]] = []

    class BrokenProcess:
        pid = 65432

        def communicate(self, timeout: int):
            calls.append(("communicate", timeout))
            raise OSError("wait handle failed")

        def wait(self, timeout: int):
            calls.append(("wait", timeout))
            return -9

        def kill(self):
            calls.append(("kill",))

    monkeypatch.setattr(
        crypto_routes.subprocess,
        "Popen",
        lambda *_args, **_kwargs: BrokenProcess(),
    )
    if os.name == "nt":
        monkeypatch.setattr(
            crypto_routes.subprocess,
            "run",
            lambda command, **kwargs: calls.append(("taskkill", tuple(command), kwargs))
            or SimpleNamespace(returncode=0),
        )
    else:
        monkeypatch.setattr(
            crypto_routes.os,
            "killpg",
            lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        )

    with pytest.raises(OSError, match="wait handle failed"):
        crypto_routes._run_python_process(
            "bridge.py",
            args=["gate"],
            cwd=crypto_routes.BASE_DIR,
            timeout=23,
            suppress_telegram=True,
        )

    assert any(call[0] in {"taskkill", "killpg"} for call in calls)
    assert calls[-1] == ("wait", 30)


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill fallback contract")
def test_crypto_route_tree_cleanup_falls_back_when_taskkill_fails(monkeypatch):
    """Regression: a taskkill failure must still terminate and reap the parent."""
    calls: list[tuple[object, ...]] = []

    class Process:
        pid = 76543

        def kill(self):
            calls.append(("kill",))

        def wait(self, timeout):
            calls.append(("wait", timeout))
            return -9

    monkeypatch.setattr(
        crypto_routes.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    crypto_routes._terminate_subprocess_tree(Process())

    assert calls == [("kill",), ("wait", 30)]


def _load_single_step_bridge(monkeypatch, fake_scheduler):
    bridge_path = Path(crypto_routes.BASE_DIR) / "scripts" / "run_crypto_single_step.py"
    monkeypatch.setitem(sys.modules, "scheduler", fake_scheduler)
    spec = importlib.util.spec_from_file_location("test_run_crypto_single_step", bridge_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_single_step_bridge_prioritizes_project_root(monkeypatch):
    """Regression: a future scripts/scheduler.py must not shadow root scheduler."""
    project_root = Path(crypto_routes.BASE_DIR)
    scripts_dir = project_root / "scripts"
    remaining = [
        entry
        for entry in sys.path
        if entry not in {str(project_root), str(scripts_dir)}
    ]
    monkeypatch.setattr(sys, "path", [str(scripts_dir), str(project_root), *remaining])

    bridge = _load_single_step_bridge(monkeypatch, _fake_scheduler([]))

    assert bridge.PROJECT_ROOT == project_root
    assert sys.path[0] == str(project_root)


class _RecordingLock:
    def __init__(self, calls, path, timeout):
        self.calls = calls
        calls.append(("lock", path, timeout))

    def __enter__(self):
        self.calls.append(("enter",))
        return self

    def __exit__(self, *_args):
        self.calls.append(("exit",))


def _fake_scheduler(calls, outcome=True, artifact_root=None):
    fake_scheduler = SimpleNamespace()

    if artifact_root is None:
        output_dir = Path("crypto-output")
        data_dir = Path("data")
        market_dir = Path("crypto-market")
    else:
        output_dir = Path(artifact_root) / "crypto" / "output"
        data_dir = Path(artifact_root) / "data"
        market_dir = Path(artifact_root) / "crypto"
        output_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)
        (market_dir / "lead_lag").mkdir(parents=True)

    fake_scheduler.Config = SimpleNamespace(
        CRYPTO_OUTPUT_DIR=str(output_dir),
        DATA_DIR=str(data_dir),
        CRYPTO_MARKET_DIR=str(market_dir),
    )

    def write_valid_artifact(step):
        if artifact_root is None:
            return
        generated_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        artifact, payload = {
            "gate": (
                output_dir / "market_gate.json",
                {
                    "_test_valid_step": "gate",
                    "generated_at": generated_at,
                    "gate": "GREEN",
                    "score": 80,
                    "metrics": {"btc_trend": 1},
                    "reasons": [],
                },
            ),
            "vcp": (
                data_dir / "vcp_crypto_latest.json",
                {
                    "_test_valid_step": "vcp",
                    "metadata": {
                        "generated_at": generated_at,
                        "market": "CRYPTO",
                        "universe_size": 1,
                    },
                    "signals": [],
                    "summary": {},
                },
            ),
            "briefing": (
                output_dir / "crypto_briefing.json",
                {
                    "_test_valid_step": "briefing",
                    "timestamp": generated_at,
                    "market_summary": {"trend": "UP"},
                    "major_coins": {"BTC": {}},
                },
            ),
            "prediction": (
                output_dir / "btc_prediction.json",
                {
                    "_test_valid_step": "prediction",
                    "timestamp": generated_at,
                    "predictions": {"BTC": {"signal": "HOLD"}},
                },
            ),
            "risk": (
                output_dir / "crypto_risk.json",
                {
                    "_test_valid_step": "risk",
                    "timestamp": generated_at,
                    "portfolio_summary": {
                        "total_coins": 1,
                        "risk_level": "LOW",
                    },
                    "correlation_matrix": {},
                },
            ),
            "lead_lag": (
                market_dir / "lead_lag" / "results.json",
                {
                    "_test_valid_step": "lead_lag",
                    "metadata": {"generated_at": generated_at},
                    "lead_lag": [{"leader": "BTC"}],
                },
            ),
        }[step]
        artifact.write_text(json.dumps(payload), encoding="utf-8")

    def run_gate():
        calls.append(("gate",))
        write_valid_artifact("gate")
        return outcome

    def run_vcp():
        calls.append(
            (
                "vcp",
                os.environ.get("TELEGRAM_BOT_TOKEN"),
                os.environ.get("CUSTOM_TELEGRAM_SECRET"),
                os.environ.get("MARKETFLOW_PRESERVE_ENV"),
                os.environ.get("PYTHON_DOTENV_DISABLED"),
                fake_scheduler._crypto_gate,
            )
        )
        fake_scheduler.send_telegram("must-be-suppressed")
        fake_scheduler.send_telegram_long("must-also-be-suppressed")
        write_valid_artifact("vcp")
        return outcome

    def run_step(step):
        calls.append((step,))
        write_valid_artifact(step)
        return outcome

    fake_scheduler.FileLock = lambda path, timeout: _RecordingLock(calls, path, timeout)
    fake_scheduler.FileLockTimeout = TimeoutError
    fake_scheduler._crypto_worker_lock_path = lambda: "worker.lock"
    fake_scheduler._crypto_execution_lock_path = lambda: "execution.lock"
    fake_scheduler._crypto_gate = "YELLOW"
    fake_scheduler._load_json = lambda _path: {"gate": "RED"}
    fake_scheduler._valid_crypto_artifact_shape = (
        lambda step, payload: payload.get("_test_valid_step") == step
    )
    fake_scheduler.run_crypto_gate_check = run_gate
    fake_scheduler.run_crypto_vcp_scan = run_vcp
    fake_scheduler.run_crypto_briefing = lambda: run_step("briefing")
    fake_scheduler.run_crypto_prediction = lambda: run_step("prediction")
    fake_scheduler.run_crypto_risk = lambda: run_step("risk")
    fake_scheduler.run_crypto_leadlag = lambda: run_step("lead_lag")
    fake_scheduler.send_telegram = (
        lambda *_args, **_kwargs: calls.append(("telegram",)) or True
    )
    fake_scheduler.send_telegram_long = (
        lambda *_args, **_kwargs: calls.append(("telegram-long",)) or True
    )
    return fake_scheduler


def _set_fake_artifact_paths(fake_scheduler, tmp_path):
    output_dir = tmp_path / "crypto" / "output"
    data_dir = tmp_path / "data"
    market_dir = tmp_path / "crypto"
    output_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (market_dir / "lead_lag").mkdir(parents=True)
    fake_scheduler.Config = SimpleNamespace(
        CRYPTO_OUTPUT_DIR=str(output_dir),
        DATA_DIR=str(data_dir),
        CRYPTO_MARKET_DIR=str(market_dir),
    )
    return output_dir, data_dir, market_dir


def test_single_step_bridge_delegates_shape_validation_to_root_scheduler(
    monkeypatch,
    tmp_path,
):
    """Regression: manual and scheduled runs must share one shape contract."""
    calls: list[tuple[object, ...]] = []
    fake_scheduler = _fake_scheduler(calls, artifact_root=tmp_path)
    fake_scheduler._valid_crypto_artifact_shape = (
        lambda step, _payload: calls.append(("shape", step)) or False
    )
    bridge = _load_single_step_bridge(monkeypatch, fake_scheduler)

    assert bridge.main(["prediction"]) == 1
    assert ("shape", "prediction") in calls


def test_single_step_bridge_retries_windows_style_restore_contention(
    monkeypatch,
    tmp_path,
):
    """Regression: a dashboard reader must not defeat last-good rollback."""
    bridge = _load_single_step_bridge(monkeypatch, _fake_scheduler([]))
    artifact = tmp_path / "btc_prediction.json"
    artifact.write_bytes(b'{"old":true}')
    snapshot = bridge._snapshot_artifact(artifact)
    artifact.write_bytes(b'{"new":true}')
    real_replace = bridge.os.replace
    replace_attempts = []

    def flaky_replace(source, destination):
        replace_attempts.append((source, destination))
        if len(replace_attempts) < 3:
            raise PermissionError(5, "destination is temporarily locked")
        return real_replace(source, destination)

    monkeypatch.setattr(bridge.os, "replace", flaky_replace)
    monkeypatch.setattr(bridge.time, "sleep", lambda _seconds: None)

    bridge._restore_artifact(artifact, snapshot)

    assert len(replace_attempts) == 3
    assert artifact.read_bytes() == b'{"old":true}'


def test_single_step_bridge_retries_absent_cleanup_and_mtime_restore(
    monkeypatch,
    tmp_path,
):
    """Regression: Windows readers may contend on unlink and timestamp restore."""
    bridge = _load_single_step_bridge(monkeypatch, _fake_scheduler([]))
    new_artifact = tmp_path / "new-risk.json"
    new_artifact.write_bytes(b'{"partial":true}')
    real_unlink = bridge.os.unlink
    unlink_attempts = []

    def flaky_unlink(path, *args, **kwargs):
        if Path(path) == new_artifact:
            unlink_attempts.append(path)
            if len(unlink_attempts) < 3:
                raise PermissionError(5, "destination is temporarily locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(bridge.os, "unlink", flaky_unlink)
    monkeypatch.setattr(bridge.time, "sleep", lambda _seconds: None)
    bridge._restore_artifact(new_artifact, (False, None, None, None))

    assert len(unlink_attempts) == 3
    assert not new_artifact.exists()

    artifact = tmp_path / "btc_prediction.json"
    artifact.write_bytes(b'{"old":true}')
    old_ns = 1_700_000_200_000_000_000
    bridge.os.utime(artifact, ns=(old_ns, old_ns))
    snapshot = bridge._snapshot_artifact(artifact)
    artifact.write_bytes(b'{"new":true}')
    real_utime = bridge.os.utime
    utime_attempts = []

    def flaky_utime(path, *args, **kwargs):
        utime_attempts.append(path)
        if len(utime_attempts) < 3:
            raise PermissionError(5, "destination is temporarily locked")
        return real_utime(path, *args, **kwargs)

    monkeypatch.setattr(bridge.os, "utime", flaky_utime)
    bridge._restore_artifact(artifact, snapshot)

    assert len(utime_attempts) == 3
    assert artifact.stat().st_mtime_ns == old_ns


def test_single_step_bridge_rejects_stale_artifact_and_preserves_mtime(
    monkeypatch,
    tmp_path,
):
    """Regression: runner True without a fresh artifact is failure, not success."""
    fake_scheduler = _fake_scheduler([])
    output_dir, _data_dir, _market_dir = _set_fake_artifact_paths(
        fake_scheduler, tmp_path
    )
    artifact = output_dir / "btc_prediction.json"
    artifact.write_text(
        '{"timestamp":"2025-01-01T00:00:00","predictions":{"BTC":{}}}',
        encoding="utf-8",
    )
    old_ns = 1_700_000_000_000_000_000
    os.utime(artifact, ns=(old_ns, old_ns))
    before = artifact.read_bytes()
    fake_scheduler.run_crypto_prediction = lambda: True
    bridge = _load_single_step_bridge(monkeypatch, fake_scheduler)

    assert bridge.main(["prediction"]) == 1
    assert artifact.read_bytes() == before
    assert artifact.stat().st_mtime_ns == old_ns


def test_single_step_bridge_rejects_empty_prediction_and_restores_last_good(
    monkeypatch,
    tmp_path,
):
    """Regression: Prediction's empty-success fallback must fail closed."""
    fake_scheduler = _fake_scheduler([])
    output_dir, _data_dir, _market_dir = _set_fake_artifact_paths(
        fake_scheduler, tmp_path
    )
    artifact = output_dir / "btc_prediction.json"
    old_payload = b'{"timestamp":"2025-01-01T00:00:00","predictions":{"BTC":{"bullish_probability":50}}}'
    artifact.write_bytes(old_payload)
    old_ns = 1_700_000_100_000_000_000
    os.utime(artifact, ns=(old_ns, old_ns))

    def write_empty_prediction():
        from datetime import datetime

        artifact.write_text(
            '{"timestamp":"' + datetime.now().isoformat() + '","predictions":{}}',
            encoding="utf-8",
        )
        return True

    fake_scheduler.run_crypto_prediction = write_empty_prediction
    bridge = _load_single_step_bridge(monkeypatch, fake_scheduler)

    assert bridge.main(["prediction"]) == 1
    assert artifact.read_bytes() == old_payload
    assert artifact.stat().st_mtime_ns == old_ns


def test_single_step_bridge_removes_new_truncated_artifact_after_failure(
    monkeypatch,
    tmp_path,
):
    """Regression: a failed first run must not leave corrupt JSON visible."""
    fake_scheduler = _fake_scheduler([])
    output_dir, _data_dir, _market_dir = _set_fake_artifact_paths(
        fake_scheduler, tmp_path
    )
    artifact = output_dir / "crypto_risk.json"

    def write_truncated_risk():
        artifact.write_text("{", encoding="utf-8")
        return True

    fake_scheduler.run_crypto_risk = write_truncated_risk
    bridge = _load_single_step_bridge(monkeypatch, fake_scheduler)

    assert bridge.main(["risk"]) == 1
    assert not artifact.exists()


def test_single_step_bridge_uses_root_vcp_contract_lock_and_no_notifications(
    monkeypatch,
    capsys,
    tmp_path,
):
    """Regression: manual VCP must write the UI artifact without Telegram."""
    calls: list[tuple[object, ...]] = []
    fake_scheduler = _fake_scheduler(calls, artifact_root=tmp_path)
    original_send = fake_scheduler.send_telegram
    original_send_long = fake_scheduler.send_telegram_long
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "sensitive-token")
    monkeypatch.setenv("CUSTOM_TELEGRAM_SECRET", "another-secret")
    monkeypatch.delenv("MARKETFLOW_PRESERVE_ENV", raising=False)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    bridge = _load_single_step_bridge(monkeypatch, fake_scheduler)
    assert "MARKETFLOW_PRESERVE_ENV" not in os.environ
    assert "PYTHON_DOTENV_DISABLED" not in os.environ

    assert bridge.main(["vcp"]) == 0

    assert calls == [
        ("lock", "worker.lock", 0),
        ("enter",),
        ("lock", "execution.lock", 0),
        ("enter",),
        ("vcp", "", "", "1", "1", "RED"),
        ("exit",),
        ("exit",),
    ]
    assert fake_scheduler.send_telegram is original_send
    assert fake_scheduler.send_telegram_long is original_send_long
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "sensitive-token"
    assert os.environ["CUSTOM_TELEGRAM_SECRET"] == "another-secret"
    assert "MARKETFLOW_PRESERVE_ENV" not in os.environ
    assert "PYTHON_DOTENV_DISABLED" not in os.environ
    assert capsys.readouterr() == ("", "")


def test_single_step_bridge_calls_gate_and_requires_literal_true(monkeypatch):
    """Regression: truthy partial outcomes must not be reported as success."""
    calls: list[tuple[object, ...]] = []
    bridge = _load_single_step_bridge(monkeypatch, _fake_scheduler(calls, outcome=1))

    assert bridge.main(["gate"]) == 1
    assert ("gate",) in calls


@pytest.mark.parametrize(
    "step",
    ["briefing", "prediction", "risk", "lead_lag"],
)
def test_single_step_bridge_dispatches_remaining_scheduler_steps(
    monkeypatch,
    tmp_path,
    step,
):
    """Regression: every artifact-producing admin action uses root scheduler."""
    calls: list[tuple[object, ...]] = []
    bridge = _load_single_step_bridge(
        monkeypatch,
        _fake_scheduler(calls, artifact_root=tmp_path),
    )

    assert bridge.main([step]) == 0
    assert (step,) in calls


@pytest.mark.parametrize(
    "step",
    ["gate", "vcp", "briefing", "prediction", "risk", "lead_lag"],
)
def test_single_step_bridge_requires_literal_true_for_every_step(monkeypatch, step):
    """Regression: truthy non-boolean results may never become API success."""
    bridge = _load_single_step_bridge(monkeypatch, _fake_scheduler([], outcome=1))

    assert bridge.main([step]) == 1


def test_single_step_bridge_returns_silent_failure_when_lock_is_busy(monkeypatch, capsys):
    """Regression: contention must fail closed without leaking exception text."""
    class BusyLock:
        def __enter__(self):
            raise TimeoutError("sensitive lock path")

        def __exit__(self, *_args):
            return None

    fake_scheduler = _fake_scheduler([])
    fake_scheduler.FileLock = lambda *_args, **_kwargs: BusyLock()
    bridge = _load_single_step_bridge(monkeypatch, fake_scheduler)

    assert bridge.main(["vcp"]) == 1
    assert capsys.readouterr() == ("", "")


def test_single_step_bridge_rejects_unknown_step_silently(monkeypatch, capsys):
    """Regression: only the two approved single-step operations are callable."""
    bridge = _load_single_step_bridge(monkeypatch, _fake_scheduler([]))

    assert bridge.main(["unknown-step"]) == 2
    assert capsys.readouterr() == ("", "")
