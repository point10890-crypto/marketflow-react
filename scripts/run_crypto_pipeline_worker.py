#!/usr/bin/env python3
"""Run the Crypto analysis pipeline in an isolated child process."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
while str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

import scheduler  # noqa: E402  (project root must be on sys.path first)


SCHEMA_VERSION = "marketflow.crypto_pipeline_worker.v1"
STEP_NAMES = ("gate", "vcp", "briefing", "prediction", "risk", "lead_lag")


class WorkerBusy(RuntimeError):
    """Another surviving worker still owns the native execution lock."""


class LockUnavailable(RuntimeError):
    """The required process lock dependency is unavailable."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _notification_scope(*, disabled: bool) -> Iterator[None]:
    """Temporarily suppress the scheduler's two Telegram entry points."""
    if not disabled:
        yield
        return

    original_send = scheduler.send_telegram
    original_send_long = scheduler.send_telegram_long
    telegram_keys = {
        key for key in os.environ if "TELEGRAM" in key.upper()
    } | {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_CHANNEL_BOT_TOKEN",
        "TELEGRAM_CHANNEL_CHAT_ID",
    }
    original_env = {
        key: os.environ[key] for key in telegram_keys if key in os.environ
    }
    scheduler.send_telegram = lambda *_args, **_kwargs: False
    scheduler.send_telegram_long = lambda *_args, **_kwargs: False
    for key in telegram_keys:
        # Keep the key present but empty so a grandchild's load_dotenv() with
        # override=False cannot silently repopulate credentials.
        os.environ[key] = ""
    try:
        yield
    finally:
        scheduler.send_telegram = original_send
        scheduler.send_telegram_long = original_send_long
        for key in telegram_keys:
            os.environ.pop(key, None)
        os.environ.update(original_env)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--no-notify", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    started_at = _timestamp()
    steps = {name: False for name in STEP_NAMES}
    error_type: str | None = None

    try:
        if scheduler.FileLock is None or scheduler.FileLockTimeout is None:
            raise LockUnavailable
        lock_path = scheduler._crypto_execution_lock_path()
        Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            with scheduler.FileLock(lock_path, timeout=0):
                with _notification_scope(disabled=args.no_notify):
                    raw_steps = scheduler._run_crypto_pipeline_core()
        except scheduler.FileLockTimeout:
            raise WorkerBusy from None
        if not isinstance(raw_steps, dict) or set(raw_steps) != set(STEP_NAMES):
            raise ValueError("invalid step result shape")
        if any(type(raw_steps[name]) is not bool for name in STEP_NAMES):
            raise TypeError("step results must be booleans")
        steps = {name: raw_steps[name] for name in STEP_NAMES}
    except Exception as exc:  # The manifest intentionally excludes exception text.
        error_type = type(exc).__name__

    ok = all(steps.values())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": args.run_id,
        "status": "succeeded" if ok else "failed",
        "ok": ok,
        "pid": os.getpid(),
        "started_at": started_at,
        "completed_at": _timestamp(),
        "steps": steps,
    }
    if error_type is not None:
        payload["error_type"] = error_type

    try:
        scheduler.write_json_atomic(args.result, payload, sort_keys=True)
    except Exception:
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
