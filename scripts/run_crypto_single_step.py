#!/usr/bin/env python3
"""Run one approved Crypto analysis step under the shared execution lock."""

from __future__ import annotations

import os
import sys
import json
import tempfile
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
while str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

_STEPS = {"gate", "vcp", "briefing", "prediction", "risk", "lead_lag"}
_TELEGRAM_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_CHANNEL_BOT_TOKEN",
    "TELEGRAM_CHANNEL_CHAT_ID",
}
_RUNTIME_ENV = {
    "MARKETFLOW_PRESERVE_ENV": "1",
    "PYTHON_DOTENV_DISABLED": "1",
}
_REPLACE_MAX_ATTEMPTS = 10
_REPLACE_BACKOFF_STEP_SECONDS = 0.05


def _load_root_scheduler():
    import scheduler  # noqa: E402  (project root is forced to sys.path[0])

    return scheduler


@contextmanager
def _runtime_environment_scope() -> Iterator[None]:
    telegram_keys = {
        key for key in os.environ if "TELEGRAM" in key.upper()
    } | _TELEGRAM_KEYS
    managed_keys = telegram_keys | set(_RUNTIME_ENV)
    original_env = {
        key: os.environ[key] for key in managed_keys if key in os.environ
    }
    for key in telegram_keys:
        os.environ[key] = ""
    os.environ.update(_RUNTIME_ENV)
    try:
        yield
    finally:
        for key in managed_keys:
            os.environ.pop(key, None)
        os.environ.update(original_env)


@contextmanager
def _notification_scope(root_scheduler) -> Iterator[None]:
    original_send = root_scheduler.send_telegram
    original_send_long = root_scheduler.send_telegram_long
    root_scheduler.send_telegram = lambda *_args, **_kwargs: False
    root_scheduler.send_telegram_long = lambda *_args, **_kwargs: False
    try:
        yield
    finally:
        root_scheduler.send_telegram = original_send
        root_scheduler.send_telegram_long = original_send_long


def _parse_step(argv: Sequence[str] | None) -> str | None:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) != 1 or values[0] not in _STEPS:
        return None
    return values[0]


def _hydrate_vcp_gate(root_scheduler) -> None:
    """Load the persisted Gate so a fresh VCP process keeps gate-aware limits."""
    gate_path = os.path.join(root_scheduler.Config.CRYPTO_OUTPUT_DIR, "market_gate.json")
    gate_data = root_scheduler._load_json(gate_path)
    if not isinstance(gate_data, dict):
        return
    gate = str(gate_data.get("gate", "")).upper()
    if gate in {"GREEN", "YELLOW", "RED"}:
        root_scheduler._crypto_gate = gate


def _artifact_contract(root_scheduler, step: str) -> tuple[Path, tuple[str, ...]]:
    output_dir = Path(root_scheduler.Config.CRYPTO_OUTPUT_DIR)
    data_dir = Path(root_scheduler.Config.DATA_DIR)
    market_dir = Path(root_scheduler.Config.CRYPTO_MARKET_DIR)
    return {
        "gate": (output_dir / "market_gate.json", ("generated_at",)),
        "vcp": (data_dir / "vcp_crypto_latest.json", ("metadata", "generated_at")),
        "briefing": (output_dir / "crypto_briefing.json", ("timestamp",)),
        "prediction": (output_dir / "btc_prediction.json", ("timestamp",)),
        "risk": (output_dir / "crypto_risk.json", ("timestamp",)),
        "lead_lag": (market_dir / "lead_lag" / "results.json", ("metadata", "generated_at")),
    }[step]


def _snapshot_artifact(path: Path) -> tuple[bool, bytes | None, int | None, int | None]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False, None, None, None
    return True, path.read_bytes(), stat.st_atime_ns, stat.st_mtime_ns


def _retry_contention(operation: Callable[[], None]) -> None:
    """Tolerate brief Windows reader contention during artifact rollback."""
    for attempt in range(_REPLACE_MAX_ATTEMPTS):
        try:
            operation()
            return
        except PermissionError:
            if attempt == _REPLACE_MAX_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_STEP_SECONDS * (attempt + 1))


def _replace_with_retry(source: str, destination: Path) -> None:
    _retry_contention(lambda: os.replace(source, destination))


def _unlink_with_retry(path: Path) -> None:
    try:
        _retry_contention(lambda: path.unlink())
    except FileNotFoundError:
        pass


def _utime_with_retry(path: Path, atime_ns: int, mtime_ns: int) -> None:
    _retry_contention(lambda: os.utime(path, ns=(atime_ns, mtime_ns)))


def _restore_artifact(
    path: Path,
    snapshot: tuple[bool, bytes | None, int | None, int | None],
) -> None:
    existed, content, atime_ns, mtime_ns = snapshot
    if not existed:
        _unlink_with_retry(path)
        return
    if content is None or atime_ns is None or mtime_ns is None:
        raise OSError("invalid artifact snapshot")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".restore",
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_path, path)
        _utime_with_retry(path, atime_ns, mtime_ns)
    finally:
        _unlink_with_retry(Path(temp_path))


def _timestamp_epoch(payload: dict, path: tuple[str, ...]) -> float | None:
    value: object = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _validate_artifact(
    root_scheduler,
    path: Path,
    timestamp_path: tuple[str, ...],
    step: str,
    launch_epoch: float,
) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    artifact_epoch = _timestamp_epoch(payload, timestamp_path)
    if artifact_epoch is None or artifact_epoch < launch_epoch:
        return False
    return root_scheduler._valid_crypto_artifact_shape(step, payload) is True


def main(argv: Sequence[str] | None = None) -> int:
    step = _parse_step(argv)
    if step is None:
        return 2

    succeeded = False
    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with redirect_stdout(sink), redirect_stderr(sink), _runtime_environment_scope():
                root_scheduler = _load_root_scheduler()
                if root_scheduler.FileLock is None:
                    return 1
                worker_lock_path = root_scheduler._crypto_worker_lock_path()
                execution_lock_path = root_scheduler._crypto_execution_lock_path()
                Path(worker_lock_path).parent.mkdir(parents=True, exist_ok=True)
                Path(execution_lock_path).parent.mkdir(parents=True, exist_ok=True)
                runner = {
                    "gate": root_scheduler.run_crypto_gate_check,
                    "vcp": root_scheduler.run_crypto_vcp_scan,
                    "briefing": root_scheduler.run_crypto_briefing,
                    "prediction": root_scheduler.run_crypto_prediction,
                    "risk": root_scheduler.run_crypto_risk,
                    "lead_lag": root_scheduler.run_crypto_leadlag,
                }[step]
                with root_scheduler.FileLock(worker_lock_path, timeout=0):
                    with root_scheduler.FileLock(execution_lock_path, timeout=0):
                        if step == "vcp":
                            _hydrate_vcp_gate(root_scheduler)
                        artifact_path, timestamp_path = _artifact_contract(
                            root_scheduler, step
                        )
                        snapshot = _snapshot_artifact(artifact_path)
                        launch_epoch = time.time()
                        try:
                            with _notification_scope(root_scheduler):
                                runner_succeeded = runner()
                            succeeded = (
                                runner_succeeded is True
                                and _validate_artifact(
                                    root_scheduler,
                                    artifact_path,
                                    timestamp_path,
                                    step,
                                    launch_epoch,
                                )
                            )
                        finally:
                            if not succeeded:
                                _restore_artifact(artifact_path, snapshot)
    except BaseException:
        return 1
    return 0 if succeeded is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
