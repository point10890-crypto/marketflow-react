"""A block cool-off must survive a restart, because restarting IS the deploy path.

Resuming after a Cloudflare block keeps one run open for 7h+ (≈3.5h of scraping,
a 45-56min cool-off, then the remaining rows). The resume intent used to live only
in a local of `_scraper_loop_worker`, so a reboot mid-cool-off would:
  1. drop the intent -- the next cycle restarts at rank 1 and the ~1,400 rows
     already collected are abandoned;
  2. leave the partial run persisted as status="running" with no active loop id,
     which `_public_run_status` reports as "stale" -- and the dashboard filters
     stale runs out of every selection path, so the run with the freshest data
     disappears from the page entirely.

The intent is therefore written into the run file itself.
"""

import time
from pathlib import Path

import pandas as pd

from app.services import manual_stock_analysis as svc


def _isolate_manual_service(monkeypatch, tmp_path: Path) -> None:
    svc.stop_scraper_loop()
    monkeypatch.setattr(svc, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(svc, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(svc, "DEFAULT_RESULT_PATHS", [])
    monkeypatch.setattr(svc, "DEFAULT_SOURCE_PATHS", [tmp_path / "stock_data.xlsx"])
    svc._LOOP_STOP.clear()
    svc.ensure_storage()


def _recent_stamp(*, minutes_ago: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _write_source(path: Path, rows: int = 3) -> None:
    pd.DataFrame([
        {
            "rank": index + 1,
            "stock": f"SampleStock{index + 1} ({index + 1:06d})",
            "industry": f"Industry{index + 1}",
            "url": f"https://example.com/{index + 1}",
        }
        for index in range(rows)
    ]).to_excel(path, index=False)


def _write_run(run_id: str, *, status: str = "running", resume_pending: bool = False,
               mtime: float | None = None) -> dict:
    run = {
        "run_id": run_id,
        "title": run_id,
        "source_kind": "selenium_scrape",
        "created_at": "2026-07-26 20:00:00",
        "updated_at": "2026-07-26 20:30:00",
        "status": status,
        "record_count": 1,
        "summary": {"매수": 1},
        "cycle_date": "2026-07-26",
        "cycle_number": 7,
        "cycle_label": "2026-07-26 - 7회차",
        "records": [{"rank": 1, "stock_name": "Probe", "result": "매수", "scrape_state": "completed"}],
    }
    if resume_pending:
        run["resume_pending"] = True
        run["blocked_at"] = "2026-07-26 20:30:00"
    svc._write_run(run)
    if mtime is not None:
        import os
        path = svc.RUNS_DIR / f"{run_id}.json"
        os.utime(path, (mtime, mtime))
    return run


def test_circuit_open_marks_the_run_file_for_resume(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_run("manual_scrape_blocked", resume_pending=False)

    svc.mark_run_resume_pending("manual_scrape_blocked")

    stored = svc._read_run(svc.RUNS_DIR / "manual_scrape_blocked.json")
    assert stored["resume_pending"] is True
    assert stored["blocked_at"]


def test_marking_a_missing_run_is_harmless(monkeypatch, tmp_path):
    """A scraper bookkeeping failure must never take the loop down."""
    _isolate_manual_service(monkeypatch, tmp_path)

    assert svc.mark_run_resume_pending("manual_scrape_does_not_exist") is False


def test_finds_the_newest_pending_run_after_a_restart(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_run("manual_scrape_old_pending", resume_pending=True, mtime=time.time() - 7200)
    _write_run("manual_scrape_new_pending", resume_pending=True, mtime=time.time())
    _write_run("manual_scrape_finished", status="completed", mtime=time.time() - 60)

    found = svc.find_resume_pending_run()

    assert found is not None
    assert found["run_id"] == "manual_scrape_new_pending"
    assert found["cycle_label"] == "2026-07-26 - 7회차"
    assert found["cycle_number"] == 7


def test_adopts_a_run_interrupted_mid_scrape_not_just_mid_cooloff(monkeypatch, tmp_path):
    """Rebooting is the deploy path and a cycle now runs ~6.6h, so most restarts
    land while scraping, not during the 45min cool-off. Those partial runs must be
    picked up too, otherwise every deploy throws away hours of collection."""
    _isolate_manual_service(monkeypatch, tmp_path)
    svc._write_run({
        "run_id": "manual_scrape_interrupted",
        "title": "interrupted",
        "source_kind": "selenium_scrape",
        "created_at": "2026-07-26 20:00:00",
        "updated_at": _recent_stamp(minutes_ago=30),
        "status": "running",
        "record_count": 2,
        "cycle_date": "2026-07-26",
        "cycle_number": 8,
        "cycle_label": "2026-07-26 - 8회차",
        "summary": {},
        "records": [
            {"rank": 1, "stock_name": "Done", "result": "매수", "scrape_state": "completed"},
            {"rank": 2, "stock_name": "Todo", "result": "분석중", "scrape_state": "pending"},
        ],
    })

    found = svc.find_resume_pending_run()

    assert found is not None
    assert found["run_id"] == "manual_scrape_interrupted"
    assert found["cycle_label"] == "2026-07-26 - 8회차"


def test_does_not_adopt_a_long_abandoned_run(monkeypatch, tmp_path):
    """A run left over from days ago is history, not work in progress."""
    _isolate_manual_service(monkeypatch, tmp_path)
    svc._write_run({
        "run_id": "manual_scrape_ancient",
        "title": "ancient",
        "source_kind": "selenium_scrape",
        "created_at": "2026-07-20 08:00:00",
        "updated_at": _recent_stamp(minutes_ago=60 * 48),
        "status": "running",
        "record_count": 2,
        "summary": {},
        "records": [
            {"rank": 1, "stock_name": "Done", "result": "매수", "scrape_state": "completed"},
            {"rank": 2, "stock_name": "Todo", "result": "분석중", "scrape_state": "pending"},
        ],
    })

    assert svc.find_resume_pending_run() is None


def test_does_not_adopt_a_run_with_nothing_left_to_do(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    svc._write_run({
        "run_id": "manual_scrape_all_done",
        "title": "all done",
        "source_kind": "selenium_scrape",
        "created_at": "2026-07-26 20:00:00",
        "updated_at": _recent_stamp(minutes_ago=5),
        "status": "running",
        "record_count": 1,
        "summary": {},
        "records": [{"rank": 1, "stock_name": "Done", "result": "매수", "scrape_state": "completed"}],
    })

    assert svc.find_resume_pending_run() is None


def test_completed_runs_are_never_resumed(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_run("manual_scrape_finished", status="completed")

    assert svc.find_resume_pending_run() is None


def test_completing_a_run_clears_the_resume_flag(monkeypatch, tmp_path):
    """Otherwise the loop would keep re-adopting a finished cycle forever."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=2)
    _write_run("manual_scrape_resumed", resume_pending=True)

    monkeypatch.setattr(svc, "_create_selenium_driver", lambda: object())
    monkeypatch.setattr(svc, "_close_selenium_driver", lambda driver: None)
    monkeypatch.setattr(
        svc,
        "_scrape_page_fields",
        lambda driver, url, xpath, *, timeout_sec: {"result": "BUY", "industry": "Live"},
    )

    svc.scrape_source_run(max_rows=0, run_id="manual_scrape_resumed", persist_progress=True, delay_sec=0)

    stored = svc._read_run(svc.RUNS_DIR / "manual_scrape_resumed.json")
    assert stored["status"] == "completed"
    assert not stored.get("resume_pending")
    assert svc.find_resume_pending_run() is None


def test_a_blocked_run_stays_selectable_instead_of_reading_as_stale(monkeypatch, tmp_path):
    """"stale" is filtered out of every selection path in the dashboard."""
    _isolate_manual_service(monkeypatch, tmp_path)
    run = _write_run("manual_scrape_blocked", resume_pending=True)

    status = svc._public_run_status(run, "")

    assert status == "blocked"
    assert status != "stale"


def test_an_abandoned_running_run_still_reads_as_stale(monkeypatch, tmp_path):
    """No resume flag means nothing plans to finish it -- the old behaviour stands."""
    _isolate_manual_service(monkeypatch, tmp_path)
    run = _write_run("manual_scrape_orphan", resume_pending=False)

    assert svc._public_run_status(run, "") == "stale"


def test_the_active_run_still_reads_as_running(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    run = _write_run("manual_scrape_live", resume_pending=True)

    assert svc._public_run_status(run, "manual_scrape_live") == "running"
