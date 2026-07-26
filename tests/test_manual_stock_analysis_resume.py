"""A blocked cycle must resume where it stopped, not restart from row 1.

Investing.com cuts the scraper off after roughly 1,400 successful page loads.
Production evidence (2026-07-26): cycles reached 1,445 (61.7%) and 1,409 (60.2%)
rows, tripped the consecutive-block circuit, cooled off for 20 minutes -- and then
started a brand new run from rank 1. At ~9s/row the loop can never get past the
same ~1,400 ceiling, so the first 1,400 stocks are re-scraped forever while the
last ~900 never refresh at all.

Resuming the same run after the cool-off means one run eventually walks the whole
2,341-stock universe across several block windows.
"""

from pathlib import Path
import time

import pandas as pd

from app.services import manual_stock_analysis as svc


class FakeDriver:
    def quit(self):
        return None


def _isolate_manual_service(monkeypatch, tmp_path: Path) -> None:
    svc.stop_scraper_loop()
    if getattr(svc, "_LOOP_THREAD", None) is not None:
        svc._LOOP_THREAD.join(timeout=2)
    monkeypatch.setattr(svc, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(svc, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(svc, "DEFAULT_RESULT_PATHS", [])
    monkeypatch.setattr(svc, "DEFAULT_SOURCE_PATHS", [tmp_path / "stock_data.xlsx"])
    svc.ensure_storage()


def _write_source(path: Path, rows: int = 5) -> None:
    pd.DataFrame([
        {
            "rank": index + 1,
            "stock": f"SampleStock{index + 1} ({index + 1:06d})",
            "industry": f"Industry{index + 1}",
            "url": f"https://example.com/{index + 1}",
        }
        for index in range(rows)
    ]).to_excel(path, index=False)


def _install_fake_browser(monkeypatch) -> list[str]:
    visited: list[str] = []

    def scrape(driver, url, xpath, *, timeout_sec):
        visited.append(url)
        return {"result": "BUY", "industry": "LiveIndustry"}

    monkeypatch.setattr(svc, "_create_selenium_driver", lambda: FakeDriver())
    monkeypatch.setattr(svc, "_close_selenium_driver", lambda driver: None)
    monkeypatch.setattr(svc, "_scrape_page_fields", scrape)
    return visited


def _record(rank: int, state: str, result: str) -> dict:
    return {
        "rank": rank,
        "stock_name": f"SampleStock{rank}",
        "ticker": f"{rank:06d}",
        "market": "KOSPI",
        "industry": f"Industry{rank}",
        "source_url": f"https://example.com/{rank}",
        "raw_result": result,
        "result": result,
        "analyzed_at": "2026-07-26 09:00:00" if state != "pending" else "",
        "scrape_state": state,
    }


def _write_partial_run(run_id: str, *, source: Path) -> dict:
    """A run that got 3 of 5 rows done before the Cloudflare circuit opened."""
    run = {
        "run_id": run_id,
        "title": "2026-07-26 - 4회차",
        "cycle_date": "2026-07-26",
        "cycle_number": 4,
        "cycle_label": "2026-07-26 - 4회차",
        "source_kind": "selenium_scrape",
        "source_path": str(source),
        "source_fingerprint": "abc123",
        "created_at": "2026-07-26 08:00:00",
        "updated_at": "2026-07-26 09:00:00",
        "status": "running",
        "record_count": 5,
        "source_record_count": 5,
        "summary": {"매수": 2, "오류": 1, "분석중": 2},
        "records": [
            _record(1, "completed", "매수"),
            _record(2, "completed", "매수"),
            _record(3, "error", "오류"),
            _record(4, "pending", "분석중"),
            _record(5, "pending", "분석중"),
        ],
        "scraper": {
            "xpath": svc.DEFAULT_INVESTING_XPATH,
            "max_rows": 5,
            "source_record_count": 5,
            "timeout_sec": 10,
        },
    }
    svc._write_run(run)
    return run


def test_resume_skips_terminal_rows_and_scrapes_the_remainder(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    source = tmp_path / "stock_data.xlsx"
    _write_source(source, rows=5)
    _write_partial_run("manual_resume_basic", source=source)
    visited = _install_fake_browser(monkeypatch)

    run = svc.scrape_source_run(
        max_rows=0,
        run_id="manual_resume_basic",
        resume=True,
        delay_sec=0,
    )

    # completed + error rows are terminal: re-scraping them is the wasted work
    # that kept the loop pinned to the first ~1,400 stocks.
    assert visited == ["https://example.com/4", "https://example.com/5"]
    assert run["status"] == "completed"
    states = {record["rank"]: record["scrape_state"] for record in run["records"]}
    assert states == {1: "completed", 2: "completed", 3: "error", 4: "completed", 5: "completed"}


def test_resume_keeps_the_whole_universe_in_the_run(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    source = tmp_path / "stock_data.xlsx"
    _write_source(source, rows=5)
    _write_partial_run("manual_resume_universe", source=source)
    _install_fake_browser(monkeypatch)

    run = svc.scrape_source_run(
        max_rows=0,
        run_id="manual_resume_universe",
        resume=True,
        delay_sec=0,
    )

    assert run["record_count"] == 5
    assert run["source_record_count"] == 5
    # Summary is over all rows, not just the resumed slice.
    assert sum(run["summary"].values()) == 5
    assert run["summary"]["매수"] == 4
    assert run["summary"]["오류"] == 1
    # Cycle identity is preserved so the dashboard keeps one card, not two.
    assert run["run_id"] == "manual_resume_universe"
    assert run["cycle_label"] == "2026-07-26 - 4회차"
    assert run["cycle_number"] == 4
    assert run["created_at"] == "2026-07-26 08:00:00"
    # Already-scraped verdicts are untouched.
    assert run["records"][0]["analyzed_at"] == "2026-07-26 09:00:00"


def test_resume_progress_reports_position_over_full_list(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    source = tmp_path / "stock_data.xlsx"
    _write_source(source, rows=5)
    _write_partial_run("manual_resume_progress", source=source)
    _install_fake_browser(monkeypatch)

    seen: list[tuple[int, int]] = []

    def on_progress(processed, total, record):
        seen.append((processed, total))

    svc.scrape_source_run(
        max_rows=0,
        run_id="manual_resume_progress",
        resume=True,
        delay_sec=0,
        progress_callback=on_progress,
    )

    # The dashboard must read 4/5 and 5/5, never 1/2 and 2/2.
    assert {total for _, total in seen} == {5}
    assert min(processed for processed, _ in seen) == 4
    assert max(processed for processed, _ in seen) == 5


def test_non_resume_call_still_rebuilds_every_row_as_pending(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    source = tmp_path / "stock_data.xlsx"
    _write_source(source, rows=5)
    _write_partial_run("manual_resume_regression", source=source)
    visited = _install_fake_browser(monkeypatch)

    run = svc.scrape_source_run(
        max_rows=0,
        run_id="manual_resume_regression",
        delay_sec=0,
    )

    assert len(visited) == 5
    assert run["record_count"] == 5
    assert {record["scrape_state"] for record in run["records"]} == {"completed"}


def test_resume_kill_switch_restores_start_from_scratch(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    monkeypatch.setattr(svc, "RESUME_AFTER_BLOCK", False)
    source = tmp_path / "stock_data.xlsx"
    _write_source(source, rows=5)
    _write_partial_run("manual_resume_killswitch", source=source)
    visited = _install_fake_browser(monkeypatch)

    run = svc.scrape_source_run(
        max_rows=0,
        run_id="manual_resume_killswitch",
        resume=True,
        delay_sec=0,
    )

    assert len(visited) == 5
    assert {record["scrape_state"] for record in run["records"]} == {"completed"}


def test_resume_without_a_persisted_run_starts_fresh(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=3)
    visited = _install_fake_browser(monkeypatch)

    run = svc.scrape_source_run(
        max_rows=0,
        run_id="manual_resume_missing",
        resume=True,
        delay_sec=0,
    )

    assert len(visited) == 3
    assert run["record_count"] == 3
    assert run["status"] == "completed"


def test_loop_resumes_the_same_run_after_a_block_cooloff(monkeypatch, tmp_path):
    """One circuit-open then success must leave ONE run id, not two."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=2)
    # Shrink the 20-minute cool-off so the test does not sleep for real.
    monkeypatch.setattr(svc, "BLOCK_BACKOFF_SEC", 0.05)

    calls: list[dict] = []

    def fake_scrape_source_run(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise svc.ScraperCircuitOpen("5 consecutive blocks; aborting cycle at rank 1445")
        return {"run_id": kwargs.get("run_id"), "record_count": 2}

    monkeypatch.setattr(svc, "scrape_source_run", fake_scrape_source_run)

    try:
        svc.start_scraper_loop(max_rows=0, interval_sec=60)
        deadline = time.time() + 10
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
    finally:
        svc.stop_scraper_loop()
        if getattr(svc, "_LOOP_THREAD", None) is not None:
            svc._LOOP_THREAD.join(timeout=5)

    assert len(calls) >= 2
    first, second = calls[0], calls[1]
    assert not first.get("resume")
    assert second.get("resume") is True
    # Same run, same cycle -- the dashboard keeps a single 회차 card.
    assert second["run_id"] == first["run_id"]
    assert second["cycle_label"] == first["cycle_label"]
    assert second["cycle_number"] == first["cycle_number"]
    assert second["cycle_date"] == first["cycle_date"]


def test_loop_starts_a_new_cycle_after_a_run_completes(monkeypatch, tmp_path):
    """Resume is only for blocked runs; a finished run must roll to a new 회차."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=2)

    calls: list[dict] = []

    def fake_scrape_source_run(**kwargs):
        calls.append(dict(kwargs))
        return {"run_id": kwargs.get("run_id"), "record_count": 2}

    monkeypatch.setattr(svc, "scrape_source_run", fake_scrape_source_run)

    try:
        svc.start_scraper_loop(max_rows=0, interval_sec=0)
        deadline = time.time() + 10
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
    finally:
        svc.stop_scraper_loop()
        if getattr(svc, "_LOOP_THREAD", None) is not None:
            svc._LOOP_THREAD.join(timeout=5)

    assert len(calls) >= 2
    assert not calls[1].get("resume")
    assert calls[1]["run_id"] != calls[0]["run_id"]
