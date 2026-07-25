"""The dashboard needs a cheap, restart-proof "when did data last arrive?" signal.

`/runs` parses every run JSON (~85MB on the MiniPC), so it is fetched once on
mount and cannot back a live badge. `/scraper-loop` is polled every 1-2.5s, so
the freshness stamp rides along there -- read from file mtime (stat only) rather
than in-memory loop flags, which reset on restart and so kept the 2026-07-15
freeze invisible for 10 days.
"""

import os
import time
from pathlib import Path

import pandas as pd

from app.services import manual_stock_analysis as svc


def _isolate_manual_service(monkeypatch, tmp_path: Path) -> None:
    svc.stop_scraper_loop()
    if getattr(svc, "_LOOP_THREAD", None) is not None:
        svc._LOOP_THREAD.join(timeout=1)
    monkeypatch.setattr(svc, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(svc, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(svc, "DEFAULT_RESULT_PATHS", [])
    monkeypatch.setattr(svc, "DEFAULT_SOURCE_PATHS", [tmp_path / "stock_data.xlsx"])
    monkeypatch.setattr(svc, "AUTO_LOOP_ENABLED", False)
    monkeypatch.setattr(svc, "LOOP_BOOT_AUTOSTART", False)
    svc._LOOP_STOP.clear()
    svc.ensure_storage()


def _write_run(run_id: str, mtime: float | None = None) -> Path:
    svc._write_run({
        "run_id": run_id,
        "title": run_id,
        "source_kind": "selenium_scrape",
        "created_at": "2026-07-25 10:00:00",
        "updated_at": "2026-07-25 10:00:00",
        "status": "completed",
        "record_count": 1,
        "summary": {"매수": 1},
        "records": [{"rank": 1, "stock_name": "Probe", "result": "매수"}],
    })
    path = svc.RUNS_DIR / f"{run_id}.json"
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_returns_empty_when_no_runs_exist(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)

    assert svc.latest_run_data_at() == ""


def test_reports_the_newest_run_file_write_time(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    old = time.time() - 86_400
    recent = time.time() - 60
    _write_run("manual_scrape_old", mtime=old)
    _write_run("manual_scrape_recent", mtime=recent)

    stamp = svc.latest_run_data_at()

    assert stamp == time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(recent))


def test_survives_an_unreadable_runs_directory(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "does_not_exist")

    assert svc.latest_run_data_at() == ""


def test_loop_status_carries_the_freshness_stamp(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    recent = time.time() - 30
    _write_run("manual_scrape_recent", mtime=recent)
    pd.DataFrame([
        {"rank": 1, "stock": "Sample (000001)", "industry": "Test", "url": "https://example.com/1"},
    ]).to_excel(tmp_path / "stock_data.xlsx", index=False)

    status = svc.get_scraper_loop_status()

    assert status["last_data_at"] == time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(recent))


def test_freshness_stamp_present_even_when_autostart_path_taken(monkeypatch, tmp_path):
    """Every return path of get_scraper_loop_status must carry the stamp."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_run("manual_scrape_recent", mtime=time.time() - 5)
    monkeypatch.setattr(svc, "AUTO_LOOP_ENABLED", True)
    monkeypatch.setattr(svc, "start_scraper_loop", lambda **_kw: {"running": True, "state": "starting"})

    status = svc.get_scraper_loop_status(auto_start=True)

    assert status["running"] is True
    assert status["last_data_at"] != ""
