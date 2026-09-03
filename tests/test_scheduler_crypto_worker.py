"""Regression tests for the isolated Crypto scheduler worker."""

from __future__ import annotations

import json
import os
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import scheduler
from filelock import FileLock
from packaging.requirements import Requirement
from packaging.version import Version
import pytest


STEP_RESULTS = {
    "gate": True,
    "vcp": True,
    "briefing": True,
    "prediction": True,
    "risk": True,
    "lead_lag": True,
}


@pytest.fixture(autouse=True)
def _block_external_side_effects(monkeypatch):
    """RED tests must never fall through to providers, Git, or Telegram."""
    for name in (
        "run_crypto_gate_check",
        "run_crypto_vcp_scan",
        "run_crypto_briefing",
        "run_crypto_prediction",
        "run_crypto_risk",
        "run_crypto_leadlag",
    ):
        monkeypatch.setattr(scheduler, name, lambda: False)
    monkeypatch.setattr(scheduler, "notify_crypto_briefing", lambda: False)
    monkeypatch.setattr(scheduler, "send_telegram", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(scheduler, "send_telegram_long", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(scheduler, "auto_git_push", lambda *_args, **_kwargs: False)


def _configure_crypto_paths(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "marketflow"
    data_dir = base_dir / "data"
    crypto_dir = base_dir / "crypto-analytics"
    market_dir = crypto_dir / "crypto_market"
    output_dir = market_dir / "output"
    output_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (market_dir / "lead_lag").mkdir(parents=True)

    monkeypatch.setattr(scheduler.Config, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(scheduler.Config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(scheduler.Config, "CRYPTO_DIR", str(crypto_dir))
    monkeypatch.setattr(scheduler.Config, "CRYPTO_MARKET_DIR", str(market_dir))
    monkeypatch.setattr(scheduler.Config, "CRYPTO_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(scheduler.Config, "PYTHON_PATH", "python-test")


def _write_fresh_artifacts(timestamp: str) -> None:
    artifacts = (
        (
            Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "market_gate.json",
            {
                "generated_at": timestamp,
                "gate": "YELLOW",
                "score": 50,
                "metrics": {"fear_greed": 45},
                "reasons": [],
            },
        ),
        (
            Path(scheduler.Config.DATA_DIR) / "vcp_crypto_latest.json",
            {
                "metadata": {
                    "generated_at": timestamp,
                    "market": "CRYPTO",
                    "universe_size": 1,
                },
                "signals": [],
                "summary": {},
            },
        ),
        (
            Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "crypto_briefing.json",
            {
                "timestamp": timestamp,
                "market_summary": {"status": "ok"},
                "major_coins": {"BTC": {"price": 1}},
            },
        ),
        (
            Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "btc_prediction.json",
            {"timestamp": timestamp, "predictions": {"BTC": {"bullish_probability": 50}}},
        ),
        (
            Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "crypto_risk.json",
            {
                "timestamp": timestamp,
                "portfolio_summary": {"total_coins": 1, "risk_level": "MEDIUM"},
                "correlation_matrix": {},
            },
        ),
        (
            Path(scheduler.Config.CRYPTO_MARKET_DIR) / "lead_lag" / "results.json",
            {
                "metadata": {"generated_at": timestamp},
                "lead_lag": [{"leader": "BTC", "lagger": "ETH"}],
            },
        ),
    )
    for path, payload in artifacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


def _write_worker_result(command, *, timestamp: str | None = None, **overrides) -> None:
    result_path = Path(command[command.index("--result") + 1])
    run_id = command[command.index("--run-id") + 1]
    current = timestamp or (datetime.now() + timedelta(seconds=1)).isoformat()
    payload = {
        "schema_version": "marketflow.crypto_pipeline_worker.v1",
        "run_id": run_id,
        "status": "succeeded",
        "ok": True,
        "pid": os.getpid() + 1000,
        "started_at": current,
        "completed_at": current,
        "steps": dict(STEP_RESULTS),
    }
    payload.update(overrides)
    _write_fresh_artifacts(current)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload), encoding="utf-8")


def _write_worker_busy_result(command) -> None:
    result_path = Path(command[command.index("--result") + 1])
    run_id = command[command.index("--run-id") + 1]
    current = (datetime.now() + timedelta(seconds=1)).isoformat()
    payload = {
        "schema_version": "marketflow.crypto_pipeline_worker.v1",
        "run_id": run_id,
        "status": "failed",
        "ok": False,
        "pid": os.getpid() + 1001,
        "started_at": current,
        "completed_at": current,
        "steps": {key: False for key in STEP_RESULTS},
        "error_type": "WorkerBusy",
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_worker_process(monkeypatch, writer, *, returncode: int = 0):
    state = {"calls": [], "wait_timeouts": [], "terminated": []}
    child_pid = os.getpid() + 1000

    class FakeProcess:
        pid = child_pid

        def wait(self, timeout):
            state["wait_timeouts"].append(timeout)
            return returncode

    def fake_popen(command, **kwargs):
        state["calls"].append((command, kwargs))
        writer(command)
        return FakeProcess()

    monkeypatch.setattr(scheduler.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        scheduler,
        "_terminate_crypto_process_tree",
        lambda process: state["terminated"].append(process.pid),
    )
    return state


def test_crypto_parent_uses_dedicated_worker_with_bounded_sanitized_process(monkeypatch, tmp_path):
    """A scheduler refactor must not move native Crypto work back into the daemon."""
    _configure_crypto_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "parent-test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "parent-test-chat")
    def fail_if_in_process():
        raise AssertionError("parent executed native Crypto core")

    monkeypatch.setattr(scheduler, "run_crypto_gate_check", fail_if_in_process)
    monkeypatch.setattr(scheduler, "auto_git_push", lambda *_args, **_kwargs: True)

    state = _patch_worker_process(monkeypatch, _write_worker_result)

    assert scheduler.run_crypto_pipeline(no_notify=True) is True
    assert len(state["calls"]) == 1
    command, kwargs = state["calls"][0]
    assert command[0] == "python-test"
    assert command[1].endswith("scripts/run_crypto_pipeline_worker.py") or command[1].endswith(
        "scripts\\run_crypto_pipeline_worker.py"
    )
    assert "--no-notify" in command
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == scheduler.Config.BASE_DIR
    assert kwargs["env"]["PYTHONPATH"] == scheduler.Config.BASE_DIR
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert kwargs["env"]["MARKETFLOW_PRESERVE_ENV"] == "1"
    assert kwargs["env"]["TELEGRAM_BOT_TOKEN"] == ""
    assert kwargs["env"]["TELEGRAM_CHAT_ID"] == ""
    assert state["wait_timeouts"] == [scheduler.Config.CRYPTO_PIPELINE_TIMEOUT]
    assert 0 < state["wait_timeouts"][0] <= 7200
    assert kwargs["stdout"] is scheduler.subprocess.DEVNULL
    assert kwargs["stderr"] is scheduler.subprocess.DEVNULL
    if os.name == "nt":
        assert kwargs["creationflags"] & scheduler.subprocess.CREATE_NO_WINDOW
        assert kwargs["creationflags"] & scheduler.subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert kwargs["start_new_session"] is True
    result_path = Path(command[command.index("--result") + 1])
    assert not result_path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX nested process-group contract")
def test_cloud_bridge_worker_inherits_the_outer_posix_process_group(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("MARKETFLOW_CRYPTO_INHERIT_PROCESS_GROUP", "1")
    state = _patch_worker_process(monkeypatch, _write_worker_result)

    assert scheduler.run_crypto_pipeline(skip_sync=True, no_notify=True) is True

    _, kwargs = state["calls"][0]
    assert "start_new_session" not in kwargs


def test_greenlet_direct_requirement_excludes_broken_windows_wheels():
    requirements = [
        Requirement(line)
        for line in (Path(scheduler.Config.BASE_DIR) / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    greenlet = next(item for item in requirements if item.name.lower() == "greenlet")

    assert not greenlet.specifier.contains(Version("3.5.4"))
    assert greenlet.specifier.contains(Version("3.5.5"))


def test_crypto_core_returns_exact_six_step_results_and_never_syncs_git(monkeypatch):
    calls = []
    functions = (
        ("run_crypto_gate_check", "gate"),
        ("run_crypto_vcp_scan", "vcp"),
        ("run_crypto_briefing", "briefing"),
        ("run_crypto_prediction", "prediction"),
        ("run_crypto_risk", "risk"),
        ("run_crypto_leadlag", "lead_lag"),
    )
    for function_name, step_name in functions:
        monkeypatch.setattr(
            scheduler,
            function_name,
            lambda step_name=step_name: calls.append(step_name) or True,
        )
    monkeypatch.setattr(scheduler, "notify_crypto_briefing", lambda: calls.append("notify") or True)
    monkeypatch.setattr(
        scheduler,
        "auto_git_push",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("child core attempted git sync")),
    )

    assert scheduler._run_crypto_pipeline_core() == STEP_RESULTS
    assert calls == [*STEP_RESULTS, "notify"]


def _load_worker_module():
    path = Path(scheduler.__file__).resolve().parent / "scripts" / "run_crypto_pipeline_worker.py"
    assert path.is_file(), "dedicated worker entrypoint is missing"
    spec = importlib.util.spec_from_file_location("test_crypto_pipeline_worker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_crypto_worker_prioritizes_project_root_for_scheduler_import(monkeypatch):
    project_root = Path(scheduler.__file__).resolve().parent
    scripts_dir = project_root / "scripts"
    remaining = [
        item
        for item in sys.path
        if item not in {str(project_root), str(scripts_dir)}
    ]
    monkeypatch.setattr(sys, "path", [str(scripts_dir), str(project_root), *remaining])

    worker = _load_worker_module()

    assert worker.PROJECT_ROOT == project_root
    assert sys.path[0] == str(project_root)


def test_crypto_worker_writes_exact_atomic_manifest_and_neutralizes_notifications(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    worker = _load_worker_module()
    result_path = tmp_path / "result.json"
    sends = []
    writes = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-only-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-only-chat")

    def fake_core():
        assert not os.environ.get("TELEGRAM_BOT_TOKEN")
        assert not os.environ.get("TELEGRAM_CHAT_ID")
        scheduler.send_telegram("private")
        scheduler.send_telegram_long("long")
        return dict(STEP_RESULTS)

    monkeypatch.setattr(scheduler, "_run_crypto_pipeline_core", fake_core)
    monkeypatch.setattr(scheduler, "send_telegram", lambda *a, **k: sends.append((a, k)) or True)
    monkeypatch.setattr(scheduler, "send_telegram_long", lambda *a, **k: sends.append((a, k)) or True)
    monkeypatch.setattr(
        scheduler,
        "auto_git_push",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("worker attempted git sync")),
    )
    real_atomic_write = scheduler.write_json_atomic

    def track_atomic_write(path, payload, **kwargs):
        writes.append(Path(path))
        return real_atomic_write(path, payload, **kwargs)

    monkeypatch.setattr(scheduler, "write_json_atomic", track_atomic_write)

    assert worker.main(["--run-id", "run-123", "--result", str(result_path), "--no-notify"]) == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "run_id",
        "status",
        "ok",
        "pid",
        "started_at",
        "completed_at",
        "steps",
    }
    assert payload["schema_version"] == "marketflow.crypto_pipeline_worker.v1"
    assert payload["run_id"] == "run-123"
    assert payload["status"] == "succeeded"
    assert payload["ok"] is True
    assert payload["pid"] == os.getpid()
    assert payload["steps"] == STEP_RESULTS
    assert datetime.fromisoformat(payload["completed_at"]) >= datetime.fromisoformat(payload["started_at"])
    assert writes == [result_path]
    assert sends == []
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "test-only-token"
    assert os.environ["TELEGRAM_CHAT_ID"] == "test-only-chat"


def test_crypto_worker_default_keeps_notifications_enabled(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    worker = _load_worker_module()
    result_path = tmp_path / "result.json"
    sends = []

    monkeypatch.setattr(scheduler, "send_telegram", lambda *a, **k: sends.append("short") or True)
    monkeypatch.setattr(scheduler, "send_telegram_long", lambda *a, **k: sends.append("long") or True)

    def fake_core():
        scheduler.send_telegram("private")
        scheduler.send_telegram_long("long")
        return dict(STEP_RESULTS)

    monkeypatch.setattr(scheduler, "_run_crypto_pipeline_core", fake_core)

    assert worker.main(["--run-id", "run-default", "--result", str(result_path)]) == 0
    assert sends == ["short", "long"]


def test_crypto_worker_execution_lock_blocks_an_orphan_overlap(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    worker = _load_worker_module()
    result_path = tmp_path / "busy-result.json"
    core_calls = []
    monkeypatch.setattr(
        scheduler,
        "_run_crypto_pipeline_core",
        lambda: core_calls.append("core") or dict(STEP_RESULTS),
    )
    lock_path = Path(scheduler._crypto_execution_lock_path())
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(str(lock_path), timeout=0):
        assert worker.main(["--run-id", "run-busy", "--result", str(result_path)]) == 1

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["ok"] is False
    assert payload["error_type"] == "WorkerBusy"
    assert payload["steps"] == {key: False for key in STEP_RESULTS}
    assert core_calls == []


def test_crypto_parent_rejects_nonzero_or_untrusted_manifests(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    git_calls = []
    monkeypatch.setattr(scheduler, "auto_git_push", lambda *_a, **_k: git_calls.append("git") or True)

    cases = [
        ("nonzero", lambda command: _write_worker_result(command), 1),
        ("wrong-schema", lambda command: _write_worker_result(command, schema_version="wrong"), 0),
        ("wrong-run", lambda command: _write_worker_result(command, run_id="other"), 0),
        ("same-pid", lambda command: _write_worker_result(command, pid=os.getpid()), 0),
        (
            "missing-step",
            lambda command: _write_worker_result(command, steps={key: True for key in STEP_RESULTS if key != "risk"}),
            0,
        ),
        ("failed-step", lambda command: _write_worker_result(command, steps={**STEP_RESULTS, "risk": False}), 0),
    ]

    for label, writer, returncode in cases:
        _patch_worker_process(monkeypatch, writer, returncode=returncode)
        assert scheduler.run_crypto_pipeline(skip_sync=False) is False, label

    assert git_calls == []


def test_crypto_parent_accepts_worker_pid_different_from_venv_launcher(monkeypatch, tmp_path):
    """Windows venv launchers may wait on a distinct base-interpreter PID."""
    _configure_crypto_paths(monkeypatch, tmp_path)

    def write_result(command):
        _write_worker_result(command, pid=os.getpid() + 1001)

    state = _patch_worker_process(monkeypatch, write_result)

    assert scheduler.run_crypto_pipeline(skip_sync=True, no_notify=True) is True
    assert state["calls"]


def test_crypto_parent_rejects_any_artifact_older_than_parent_launch(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    stale = (datetime.now() - timedelta(minutes=1)).isoformat()

    _patch_worker_process(
        monkeypatch,
        lambda command: _write_worker_result(command, timestamp=stale),
    )
    monkeypatch.setattr(
        scheduler,
        "auto_git_push",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("stale artifacts reached git sync")),
    )

    assert scheduler.run_crypto_pipeline() is False


def test_crypto_parent_restores_the_last_complete_artifacts_after_worker_failure(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    old_timestamp = "2026-09-03T08:00:00"
    _write_fresh_artifacts(old_timestamp)
    paths = [Path(path) for path in scheduler._crypto_artifact_paths()]
    before = {path: json.loads(path.read_text(encoding="utf-8")) for path in paths}
    old_epoch = datetime(2026, 9, 3, 8, 0).timestamp()
    for path in paths:
        os.utime(path, (old_epoch, old_epoch))
    before_mtimes = {path: path.stat().st_mtime_ns for path in paths}

    def write_failed_result(command):
        _write_worker_result(
            command,
            timestamp=(datetime.now() + timedelta(seconds=1)).isoformat(),
            status="failed",
            ok=False,
            steps={**STEP_RESULTS, "risk": False},
        )

    _patch_worker_process(monkeypatch, write_failed_result, returncode=1)

    assert scheduler.run_crypto_pipeline(skip_sync=True) is False
    after = {path: json.loads(path.read_text(encoding="utf-8")) for path in paths}
    assert after == before
    assert {path: path.stat().st_mtime_ns for path in paths} == before_mtimes


def test_crypto_parent_removes_partial_artifacts_that_were_initially_absent(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    paths = [Path(path) for path in scheduler._crypto_artifact_paths()]
    assert all(not path.exists() for path in paths)

    def write_failed_result(command):
        _write_worker_result(
            command,
            timestamp=(datetime.now() + timedelta(seconds=1)).isoformat(),
            status="failed",
            ok=False,
            steps={**STEP_RESULTS, "risk": False},
        )

    _patch_worker_process(monkeypatch, write_failed_result, returncode=1)

    assert scheduler.run_crypto_pipeline(skip_sync=True) is False
    assert all(not path.exists() for path in paths)


def test_crypto_parent_does_not_rollback_or_throttle_a_surviving_orphan_worker(monkeypatch, tmp_path):
    """A busy child means another worker owns and may still mutate artifacts."""
    _configure_crypto_paths(monkeypatch, tmp_path)
    old_timestamp = "2026-09-03T08:00:00"
    orphan_timestamp = (datetime.now() + timedelta(seconds=1)).isoformat()
    _write_fresh_artifacts(old_timestamp)

    def write_busy_while_orphan_advances(command):
        _write_worker_busy_result(command)
        _write_fresh_artifacts(orphan_timestamp)

    state = _patch_worker_process(
        monkeypatch,
        write_busy_while_orphan_advances,
        returncode=1,
    )

    assert scheduler.run_crypto_pipeline(skip_sync=True, no_notify=True) is False
    gate = json.loads(
        (Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "market_gate.json").read_text(encoding="utf-8")
    )
    assert gate["generated_at"] == orphan_timestamp
    assert not Path(scheduler._crypto_attempt_state_path()).exists()
    assert state["terminated"]


def test_crypto_parent_uses_the_contract_timestamp_key_not_an_alternate_fresh_field(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    fresh = (datetime.now() + timedelta(seconds=1)).isoformat()
    stale = (datetime.now() - timedelta(minutes=1)).isoformat()

    def write_result(command):
        _write_worker_result(command, timestamp=fresh)
        briefing_path = Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "crypto_briefing.json"
        briefing_path.write_text(
            json.dumps({"metadata": {"generated_at": fresh}, "timestamp": stale}),
            encoding="utf-8",
        )

    _patch_worker_process(monkeypatch, write_result)

    assert scheduler.run_crypto_pipeline(skip_sync=True) is False


@pytest.mark.parametrize(
    "invalid_step",
    ["gate", "vcp", "briefing", "prediction", "risk", "lead_lag"],
)
def test_crypto_parent_rejects_fresh_but_semantically_empty_artifacts(
    monkeypatch,
    tmp_path,
    invalid_step,
):
    _configure_crypto_paths(monkeypatch, tmp_path)
    fresh = (datetime.now() + timedelta(seconds=1)).isoformat()

    def write_result(command):
        _write_worker_result(command, timestamp=fresh)
        paths = {
            "gate": Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "market_gate.json",
            "vcp": Path(scheduler.Config.DATA_DIR) / "vcp_crypto_latest.json",
            "prediction": Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "btc_prediction.json",
            "risk": Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "crypto_risk.json",
            "briefing": Path(scheduler.Config.CRYPTO_OUTPUT_DIR) / "crypto_briefing.json",
            "lead_lag": Path(scheduler.Config.CRYPTO_MARKET_DIR) / "lead_lag" / "results.json",
        }
        invalid_payloads = {
            "gate": {
                "generated_at": fresh,
                "gate": "UNKNOWN",
                "score": 0,
                "metrics": {},
                "reasons": [],
            },
            "vcp": {
                "metadata": {
                    "generated_at": fresh,
                    "market": "CRYPTO",
                    "universe_size": 0,
                },
                "signals": [],
                "summary": {},
            },
            "prediction": {"timestamp": fresh, "predictions": {}},
            "risk": {
                "timestamp": fresh,
                "portfolio_summary": {"total_coins": 0, "risk_level": "NO_DATA"},
                "correlation_matrix": {},
            },
            "briefing": {"timestamp": fresh, "market_summary": {}, "major_coins": {}},
            "lead_lag": {"metadata": {"generated_at": fresh}, "lead_lag": []},
        }
        paths[invalid_step].write_text(
            json.dumps(invalid_payloads[invalid_step]),
            encoding="utf-8",
        )

    _patch_worker_process(monkeypatch, write_result)

    assert scheduler.run_crypto_pipeline(skip_sync=True, no_notify=True) is False


def test_crypto_parent_treats_post_validation_git_failure_as_analysis_success(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    git_calls = []

    def failed_git_sync(kind):
        git_calls.append(kind)
        raise RuntimeError("repository unavailable")

    _patch_worker_process(monkeypatch, _write_worker_result)
    monkeypatch.setattr(scheduler, "auto_git_push", failed_git_sync)

    assert scheduler.run_crypto_pipeline() is True
    assert git_calls == ["crypto"]


def test_crypto_parent_returns_busy_without_spawning_when_thread_lock_is_held(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler.subprocess,
        "Popen",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("busy call spawned worker")),
    )

    assert scheduler._crypto_worker_thread_lock.acquire(blocking=False)
    try:
        assert scheduler.run_crypto_pipeline() is False
    finally:
        scheduler._crypto_worker_thread_lock.release()
    assert not Path(scheduler._crypto_attempt_state_path()).exists()


def test_crypto_parent_returns_busy_without_spawning_when_process_lock_is_held(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler.subprocess,
        "Popen",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("busy call spawned worker")),
    )
    lock_path = Path(scheduler._crypto_worker_lock_path())
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(str(lock_path), timeout=0):
        assert scheduler.run_crypto_pipeline() is False


def test_latest_crypto_slot_distinguishes_catchup_from_fixed_wrapper(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "CRYPTO_TIMES", ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"])
    now = datetime(2026, 9, 3, 20, 0, 0)

    assert scheduler._latest_crypto_slot(now, include_current=False) == datetime(2026, 9, 3, 16, 0)
    assert scheduler._latest_crypto_slot(now, include_current=True) == datetime(2026, 9, 3, 20, 0)
    assert scheduler._latest_crypto_slot(datetime(2026, 9, 3, 0, 0), include_current=False) == datetime(
        2026, 9, 2, 20, 0
    )


def test_crypto_slot_due_compares_success_against_fixed_slot_not_sliding_hours(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "CRYPTO_TIMES", ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"])
    monkeypatch.setattr(scheduler, "_load_last_run", lambda: {"crypto": "2026-09-03T19:18:00"})

    due_1921, slot_1921 = scheduler._crypto_slot_due(datetime(2026, 9, 3, 19, 21), include_current=False)
    due_2321, slot_2321 = scheduler._crypto_slot_due(datetime(2026, 9, 3, 23, 21), include_current=False)
    due_2000, slot_2000 = scheduler._crypto_slot_due(datetime(2026, 9, 3, 20, 0), include_current=True)

    assert (due_1921, slot_1921) == (False, datetime(2026, 9, 3, 16, 0))
    assert (due_2321, slot_2321) == (True, datetime(2026, 9, 3, 20, 0))
    assert (due_2000, slot_2000) == (True, datetime(2026, 9, 3, 20, 0))


def test_crypto_attempt_backoff_is_durable_and_scoped_to_one_fixed_slot(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(scheduler.Config, "CRYPTO_FAILURE_RETRY_MINUTES", 60, raising=False)
    slot = datetime(2026, 9, 3, 20, 0)
    attempted_at = datetime(2026, 9, 3, 20, 5)

    assert scheduler._crypto_retry_allowed(slot, attempted_at) is True
    scheduler._record_crypto_attempt(slot, attempted_at)

    state = json.loads(Path(scheduler._crypto_attempt_state_path()).read_text(encoding="utf-8"))
    assert state == {
        "schema_version": "marketflow.crypto_pipeline_attempt.v1",
        "slot": slot.isoformat(timespec="minutes"),
        "attempted_at": attempted_at.isoformat(timespec="seconds"),
    }
    assert scheduler._crypto_retry_allowed(slot, attempted_at + timedelta(minutes=59)) is False
    assert scheduler._crypto_retry_allowed(slot, attempted_at + timedelta(minutes=60)) is True
    assert scheduler._crypto_retry_allowed(datetime(2026, 9, 4, 0, 0), attempted_at + timedelta(minutes=1)) is True


def test_crypto_catchup_does_not_repeat_a_failed_slot_every_five_minutes(monkeypatch, tmp_path):
    _configure_crypto_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(scheduler.Config, "CRYPTO_FAILURE_RETRY_MINUTES", 60, raising=False)
    real_datetime = datetime

    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 9, 6, 23, 25)

    calls = []
    records = []
    slot = real_datetime(2026, 9, 6, 20, 0)
    scheduler._record_crypto_attempt(slot, real_datetime(2026, 9, 6, 23, 20))
    monkeypatch.setattr(scheduler, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler, "_load_last_run", lambda: {"crypto": "2026-09-06T19:18:00"})
    monkeypatch.setattr(scheduler, "run_crypto_pipeline", lambda: calls.append("run") or False)
    monkeypatch.setattr(scheduler, "record_task_run", records.append)

    scheduler.check_and_run_missed_tasks()

    assert calls == []
    assert records == []


def test_crypto_worker_timeout_terminates_the_spawned_process_tree(monkeypatch):
    command = ["python-test", "worker.py"]
    process = SimpleNamespace(pid=os.getpid() + 2000)
    wait_calls = []
    terminated = []

    def wait(timeout):
        wait_calls.append(timeout)
        raise scheduler.subprocess.TimeoutExpired(command, timeout)

    process.wait = wait
    monkeypatch.setattr(scheduler.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(
        scheduler,
        "_terminate_crypto_process_tree",
        lambda child: terminated.append(child.pid),
        raising=False,
    )

    with pytest.raises(scheduler.subprocess.TimeoutExpired):
        scheduler._run_crypto_worker_process(command, {}, timeout=5)

    assert wait_calls == [5]
    assert terminated == [process.pid]


def test_crypto_worker_unexpected_wait_failure_terminates_the_spawned_process_tree(monkeypatch):
    command = ["python-test", "worker.py"]
    process = SimpleNamespace(pid=os.getpid() + 2100)
    terminated = []

    def wait(timeout=None):
        raise OSError("wait failed")

    process.wait = wait
    monkeypatch.setattr(scheduler.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(
        scheduler,
        "_terminate_crypto_process_tree",
        lambda child: terminated.append(child.pid),
        raising=False,
    )

    with pytest.raises(OSError, match="wait failed"):
        scheduler._run_crypto_worker_process(command, {}, timeout=5)

    assert terminated == [process.pid]


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill contract")
def test_crypto_tree_termination_uses_taskkill_for_the_live_root(monkeypatch):
    calls = []
    waits = []
    process = SimpleNamespace(pid=os.getpid() + 3000, wait=lambda timeout: waits.append(timeout))

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

    scheduler._terminate_crypto_process_tree(process)

    command, kwargs = calls[0]
    assert command == ["taskkill", "/PID", str(process.pid), "/T", "/F"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 30
    assert kwargs["stdout"] is scheduler.subprocess.DEVNULL
    assert kwargs["stderr"] is scheduler.subprocess.DEVNULL
    assert waits == [30]


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill fallback contract")
def test_crypto_tree_termination_falls_back_when_taskkill_fails(monkeypatch):
    calls = []
    process = SimpleNamespace(
        pid=os.getpid() + 3100,
        kill=lambda: calls.append(("kill",)),
        wait=lambda timeout: calls.append(("wait", timeout)),
    )
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1),
    )

    scheduler._terminate_crypto_process_tree(process)

    assert ("kill",) in calls
    assert ("wait", 30) in calls


def test_crypto_tree_termination_uses_parentage_when_worker_inherits_posix_group(monkeypatch):
    calls = []
    process = SimpleNamespace(
        pid=os.getpid() + 3200,
        kill=lambda: calls.append(("kill",)),
        wait=lambda timeout: calls.append(("wait", timeout)),
    )
    monkeypatch.setattr(scheduler.os, "name", "posix")
    monkeypatch.setattr(scheduler.os, "getpgid", lambda _pid: process.pid - 1, raising=False)
    monkeypatch.setattr(
        scheduler.os,
        "killpg",
        lambda pgid, sig: calls.append(("killpg", pgid, sig)),
        raising=False,
    )
    monkeypatch.setattr(
        scheduler,
        "_terminate_posix_process_tree_by_parentage",
        lambda pid: calls.append(("parentage", pid)) or True,
        raising=False,
    )

    scheduler._terminate_crypto_process_tree(process)

    assert ("parentage", process.pid) in calls
    assert not any(call[0] == "killpg" for call in calls)
