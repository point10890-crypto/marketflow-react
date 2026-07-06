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
    assert {record["scrape_state"] for record in run["records"]} == {"completed"}
    assert all(record["analyzed_at"] >= run["created_at"] for record in run["records"])


def test_list_runs_exposes_history_metadata(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    run = {
        "run_id": "manual_history_meta",
        "title": "history meta",
        "source_kind": "selenium_scrape",
        "source_path": str(tmp_path / "stock_data.xlsx"),
        "created_at": "2026-07-06 10:00:00",
        "updated_at": "2026-07-06 10:00:05",
        "status": "running",
        "record_count": 2,
        "source_record_count": 7,
        "summary": {"BUY": 1, "SELL": 1},
        "records": [{"rank": 1}, {"rank": 2}],
    }
    svc._write_run(run)

    rows = svc.list_runs()

    assert rows[0]["run_id"] == "manual_history_meta"
    assert rows[0]["status"] == "stale"
    assert rows[0]["updated_at"] == "2026-07-06 10:00:05"
    assert rows[0]["source_record_count"] == 7
    assert rows[0]["source_path"].endswith("stock_data.xlsx")


def test_list_runs_keeps_active_loop_run_running(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    run = {
        "run_id": "manual_active_loop",
        "title": "active loop",
        "source_kind": "selenium_scrape",
        "source_path": str(tmp_path / "stock_data.xlsx"),
        "created_at": "2026-07-06 10:00:00",
        "updated_at": "2026-07-06 10:00:05",
        "status": "running",
        "record_count": 1,
        "source_record_count": 1,
        "summary": {"BUY": 1},
        "records": [{"rank": 1}],
    }
    svc._write_run(run)
    monkeypatch.setattr(svc, "_active_loop_run_id", lambda: "manual_active_loop")

    rows = svc.list_runs()

    assert rows[0]["run_id"] == "manual_active_loop"
    assert rows[0]["status"] == "running"


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


def test_live_run_detail_filters_pending_rows(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    run = {
        "run_id": "manual_live_filter_test",
        "title": "live filter",
        "source_kind": "selenium_scrape",
        "source_path": "source.xlsx",
        "source_fingerprint": "abc",
        "created_at": "2026-07-06 10:00:00",
        "updated_at": "2026-07-06 10:00:02",
        "status": "running",
        "record_count": 3,
        "summary": {"분석중": 1, "매수": 1, "오류": 1},
        "records": [
            {
                "rank": 1,
                "stock_name": "Pending",
                "ticker": "000001",
                "market": "KOSPI",
                "industry": "Test",
                "source_url": "https://example.com/pending",
                "raw_result": "분석중",
                "result": "분석중",
                "analyzed_at": "",
                "scrape_state": "pending",
            },
            {
                "rank": 2,
                "stock_name": "Running",
                "ticker": "000002",
                "market": "KOSPI",
                "industry": "Test",
                "source_url": "https://example.com/running",
                "raw_result": "분석중",
                "result": "분석중",
                "analyzed_at": "2026-07-06 10:00:01",
                "scrape_state": "scraping",
            },
            {
                "rank": 3,
                "stock_name": "Done",
                "ticker": "000003",
                "market": "KOSPI",
                "industry": "Test",
                "source_url": "https://example.com/done",
                "raw_result": "BUY",
                "result": "매수",
                "analyzed_at": "2026-07-06 10:00:02",
                "scrape_state": "completed",
            },
        ],
    }
    svc._write_run(run)

    detail = svc.get_run("manual_live_filter_test", live_only=True)

    assert [record["rank"] for record in detail["records"]] == [2, 3]
    assert detail["filtered_count"] == 2
