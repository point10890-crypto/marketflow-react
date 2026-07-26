"""Investing.com serves exactly one page per browser session; the rest are 403.

Measured on the MiniPC (2026-07-26): with a reused session, page 1 returned a
verdict in 3.2s and pages 2-5 came back as a bare "403" body instantly. Clearing
cookies changed nothing, so it is not cookie state. A fresh session per page
scraped every one in ~5s.

The scraper reused one driver across rows, so every row's first attempt was a
guaranteed 403 that then paid a 5s backoff plus a Chrome relaunch before
succeeding. The completed 2026-07-25 cycle shows the cost: 2,330 of 2,341 rows
carry scrape_fallback="retry_fresh_session" at a 17s median, while the 3 rows
that needed no retry took 5s. Recycling up front removes the wasted request.
"""

from pathlib import Path

import pandas as pd

from app.services import manual_stock_analysis as svc


class FakeDriver:
    def __init__(self, index: int):
        self.index = index
        self.closed = False

    def quit(self):
        self.closed = True


def _isolate_manual_service(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(svc, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(svc, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(svc, "DEFAULT_RESULT_PATHS", [])
    monkeypatch.setattr(svc, "DEFAULT_SOURCE_PATHS", [tmp_path / "stock_data.xlsx"])
    svc.ensure_storage()


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


def _install_fake_browser(monkeypatch) -> dict:
    state = {"created": [], "closed": [], "pages": []}

    def create():
        driver = FakeDriver(len(state["created"]) + 1)
        state["created"].append(driver)
        return driver

    def close(driver):
        state["closed"].append(driver)
        driver.closed = True

    def scrape(driver, url, xpath, *, timeout_sec):
        state["pages"].append((driver.index, url))
        return {"result": "BUY", "industry": "LiveIndustry"}

    monkeypatch.setattr(svc, "_create_selenium_driver", create)
    monkeypatch.setattr(svc, "_close_selenium_driver", close)
    monkeypatch.setattr(svc, "_scrape_page_fields", scrape)
    return state


def test_each_row_scrapes_on_a_fresh_session(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=3)
    state = _install_fake_browser(monkeypatch)

    run = svc.scrape_source_run(max_rows=0, run_id="manual_recycle", delay_sec=0)

    assert run["record_count"] == 3
    # One page per session: no session is asked to load a second URL.
    sessions_used = [index for index, _ in state["pages"]]
    assert sessions_used == sorted(set(sessions_used)), "a session loaded more than one page"
    assert len(state["created"]) == 3


def test_recycled_sessions_are_closed_so_chrome_does_not_pile_up(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=4)
    state = _install_fake_browser(monkeypatch)

    svc.scrape_source_run(max_rows=0, run_id="manual_recycle_close", delay_sec=0)

    assert all(driver.closed for driver in state["created"]), "leaked a Chrome session"


def test_pages_per_session_is_tunable(monkeypatch, tmp_path):
    """If the site ever allows reuse again, raise the knob instead of editing code."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=4)
    state = _install_fake_browser(monkeypatch)
    monkeypatch.setattr(svc, "PAGES_PER_SESSION", 2)

    svc.scrape_source_run(max_rows=0, run_id="manual_recycle_tunable", delay_sec=0)

    assert len(state["created"]) == 2
    assert [index for index, _ in state["pages"]] == [1, 1, 2, 2]


def test_zero_disables_recycling(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=3)
    state = _install_fake_browser(monkeypatch)
    monkeypatch.setattr(svc, "PAGES_PER_SESSION", 0)

    svc.scrape_source_run(max_rows=0, run_id="manual_recycle_off", delay_sec=0)

    assert len(state["created"]) == 1
