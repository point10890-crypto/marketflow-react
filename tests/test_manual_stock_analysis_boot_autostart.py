"""Regression guard for the 2026-07-15 manual-scraper freeze.

The scraper loop used to be started only as a side effect of a status GET
(`get_scraper_loop_status(auto_start=True)`).  Production disabled that implicit
start (`MANUAL_STOCK_ANALYSIS_AUTO_LOOP=0`) so a poll could not launch thousands
of Selenium scrapes -- but nothing else ever started the loop, so the dashboard
froze at the last completed run for 10 days.

These tests pin both halves: status polling still must not start the loop, and a
deliberate per-process boot start must, even with request auto-start disabled.
"""

from pathlib import Path
import time

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
    svc._LOOP_STOP.clear()


def _write_source(path: Path, rows: int = 2) -> None:
    pd.DataFrame([
        {
            "rank": index + 1,
            "stock": f"SampleStock{index + 1} ({index + 1:06d})",
            "industry": f"Industry{index + 1}",
            "url": f"https://example.com/{index + 1}",
        }
        for index in range(rows)
    ]).to_excel(path, index=False)


def _capture_start(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_start_scraper_loop(**kwargs):
        calls.append(kwargs)
        return {"running": True, "state": "starting"}

    monkeypatch.setattr(svc, "start_scraper_loop", fake_start_scraper_loop)
    return calls


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_status_poll_does_not_start_loop_when_request_autostart_disabled(monkeypatch, tmp_path):
    """The 2026-07-15 hardening: a GET must never launch a scrape cycle."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=2)
    monkeypatch.setattr(svc, "AUTO_LOOP_ENABLED", False)
    calls = _capture_start(monkeypatch)

    status = svc.get_scraper_loop_status(auto_start=True)

    assert calls == []
    assert not status.get("running")


def test_boot_autostart_is_off_by_default(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, "LOOP_BOOT_AUTOSTART", False)
    calls = _capture_start(monkeypatch)

    assert svc.start_scraper_loop_on_boot() is False
    time.sleep(0.1)
    assert calls == []


def test_boot_autostart_starts_loop_even_with_request_autostart_disabled(monkeypatch, tmp_path):
    """Production config: AUTO_LOOP=0 (poll cannot start) + boot autostart on."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=2)
    monkeypatch.setattr(svc, "AUTO_LOOP_ENABLED", False)
    monkeypatch.setattr(svc, "LOOP_BOOT_AUTOSTART", True)
    monkeypatch.setattr(svc, "LOOP_BOOT_DELAY_SEC", 0)
    monkeypatch.setattr(svc, "AUTO_LOOP_MAX_ROWS", 0)
    monkeypatch.setattr(svc, "AUTO_LOOP_INTERVAL_SEC", 600)
    monkeypatch.setattr(svc, "AUTO_LOOP_TIMEOUT_SEC", 10)
    calls = _capture_start(monkeypatch)

    assert svc.start_scraper_loop_on_boot() is True
    assert _wait_for(lambda: len(calls) == 1), "boot autostart never started the loop"
    assert calls[0]["max_rows"] == 0
    assert calls[0]["interval_sec"] == 600
    assert calls[0]["timeout_sec"] == 10


def test_boot_autostart_returns_without_blocking_the_caller(monkeypatch, tmp_path):
    """Flask startup must never wait on Selenium/Excel work before binding a port."""
    _isolate_manual_service(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, "LOOP_BOOT_AUTOSTART", True)
    monkeypatch.setattr(svc, "LOOP_BOOT_DELAY_SEC", 0)

    def slow_start(**_kwargs):
        time.sleep(1.5)
        return {"running": True}

    monkeypatch.setattr(svc, "start_scraper_loop", slow_start)

    started = time.time()
    assert svc.start_scraper_loop_on_boot() is True
    assert time.time() - started < 0.5


def test_boot_autostart_swallows_start_failures(monkeypatch, tmp_path):
    """A scraper failure must not be able to take the API process down."""
    _isolate_manual_service(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, "LOOP_BOOT_AUTOSTART", True)
    monkeypatch.setattr(svc, "LOOP_BOOT_DELAY_SEC", 0)

    def boom(**_kwargs):
        raise RuntimeError("chrome not installed")

    monkeypatch.setattr(svc, "start_scraper_loop", boom)

    assert svc.start_scraper_loop_on_boot() is True
    assert _wait_for(lambda: "chrome not installed" in svc._loop_snapshot().get("last_error", ""))


def test_boot_autostart_cancelled_by_stop_during_delay(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, "LOOP_BOOT_AUTOSTART", True)
    monkeypatch.setattr(svc, "LOOP_BOOT_DELAY_SEC", 5)
    calls = _capture_start(monkeypatch)

    assert svc.start_scraper_loop_on_boot() is True
    svc.stop_scraper_loop()
    time.sleep(0.3)

    assert calls == []
