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


def test_scrape_source_run_zero_max_rows_uses_entire_default_source(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=3)

    class FakeDriver:
        def quit(self):
            return None

    visited_urls = []

    def fake_scrape_page_fields(driver, url, xpath, *, timeout_sec):
        visited_urls.append(url)
        return {"result": "BUY", "industry": "LiveIndustry"}

    monkeypatch.setattr(svc, "_create_selenium_driver", lambda: FakeDriver())
    monkeypatch.setattr(svc, "_scrape_page_fields", fake_scrape_page_fields)

    run = svc.scrape_source_run(
        max_rows=0,
        run_id="manual_scrape_all_source",
        persist_progress=True,
        delay_sec=0,
    )

    assert visited_urls == [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
    ]
    assert run["record_count"] == 3
    assert run["source_record_count"] == 3
    assert run["scraper"]["max_rows"] == 3
    assert run["status"] == "completed"
    assert all(record["analyzed_at"] >= run["created_at"] for record in run["records"])


def test_scraper_loop_zero_max_rows_tracks_source_total(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", rows=4)

    def fake_scrape_source_run(**kwargs):
        callback = kwargs.get("progress_callback")
        if callback:
            for index in range(1, 5):
                callback(index, 4, {
                    "rank": index,
                    "stock_name": f"SampleStock{index}",
                    "industry": f"Industry{index}",
                    "result": "BUY",
                })
        return {"run_id": "manual_scrape_loop_all", "record_count": 4}

    monkeypatch.setattr(svc, "scrape_source_run", fake_scrape_source_run)

    svc.start_scraper_loop(max_rows=0, interval_sec=60)
    status = svc.get_scraper_loop_status()
    for _ in range(50):
        if status.get("iterations", 0) >= 1:
            break
        time.sleep(0.02)
        status = svc.get_scraper_loop_status()

    assert status["last_run_id"] == "manual_scrape_loop_all"
    assert status["source_record_count"] == 4
    assert status["total"] == 4
    assert status["processed"] == 4
    assert status["cycle"] >= 1

    stopped = svc.stop_scraper_loop()
    assert stopped["running"] is False
