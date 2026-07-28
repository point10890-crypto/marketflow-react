"""Run one guarded Goodrich intraday monitoring and leader-detection cycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOCK_PATH = ROOT / "data" / "admin_mirofish" / "goodrich_intraday.lock"
STATUS_PATH = ROOT / "data" / "admin_mirofish" / "goodrich_intraday_status.json"
LOCK_STALE_SECONDS = 25 * 60


def _write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATUS_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temp_path, STATUS_PATH)


def _acquire_lock(now: datetime) -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        age = now.timestamp() - LOCK_PATH.stat().st_mtime
        if age < LOCK_STALE_SECONDS:
            return False
        LOCK_PATH.unlink(missing_ok=True)
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {now.isoformat()}")
    return True


def run_cycle(*, force: bool = False) -> dict:
    from app.services.kis_screener import is_market_open
    from app.services.mirofish.goodrich_client import (
        monitor_fund_manager,
        run_research,
    )

    started_at = datetime.now(UTC)
    if not force and not is_market_open():
        result = {
            "status": "skipped",
            "reason": "market_closed",
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
        }
        _write_status(result)
        return result

    if not _acquire_lock(started_at):
        return {
            "status": "skipped",
            "reason": "cycle_already_running",
            "started_at": started_at,
        }

    try:
        monitored = monitor_fund_manager()
        research = run_research()
        result = {
            "status": "completed",
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
            "market_status": research.get("integration", {}).get("market_status"),
            "detected_candidates": research.get("integration", {}).get("candidate_count"),
            "qualified_candidates": research.get("integration", {}).get("universe_size"),
            "monitored_active_count": monitored.get("active_count"),
            "top3": [
                {
                    "symbol": pick.get("symbol"),
                    "name": pick.get("name"),
                    "status": pick.get("status"),
                    "current_price": pick.get("current_price"),
                    "target_price": pick.get("target_price"),
                    "stop_price": pick.get("stop_price"),
                }
                for pick in research.get("picks", [])
            ],
        }
        _write_status(result)
        return result
    except Exception as error:
        result = {
            "status": "error",
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
            "error_type": type(error).__name__,
            "error": str(error)[:300],
        }
        _write_status(result)
        raise
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run outside market hours for an operator smoke test.")
    args = parser.parse_args()
    result = run_cycle(force=args.force)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
