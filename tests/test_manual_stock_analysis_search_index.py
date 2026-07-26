"""Autocomplete needs a stock/industry universe the search box can filter locally.

Built from the scraping source workbook rather than run files: a live cycle hides
rows it has not scraped yet, so a run-backed index would offer only the handful of
stocks already processed. The workbook is the full universe from the first second.
"""

import os
import time
from pathlib import Path

import pandas as pd

from app.services import manual_stock_analysis as svc


def _isolate_manual_service(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(svc, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(svc, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(svc, "DEFAULT_RESULT_PATHS", [])
    monkeypatch.setattr(svc, "DEFAULT_SOURCE_PATHS", [tmp_path / "stock_data.xlsx"])
    svc._search_index_cache.clear()
    svc._industry_cache.clear()


def _write_source(path: Path, rows: list[tuple[str, str, str]]) -> None:
    pd.DataFrame([
        {
            "rank": index + 1,
            "stock": name,
            "industry": industry,
            "url": url,
        }
        for index, (name, industry, url) in enumerate(rows)
    ]).to_excel(path, index=False)


def test_index_lists_every_source_stock_with_ticker_and_industry(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [
        ("삼성전자 (005930)", "반도체", "https://example.com/1"),
        ("SK하이닉스 (000660)", "반도체", "https://example.com/2"),
        ("현대차 (005380)", "자동차", "https://example.com/3"),
    ])

    index = svc.build_search_index()

    assert index["count"] == 3
    first = index["stocks"][0]
    assert first["name"] == "삼성전자"
    assert first["ticker"] == "005930"
    assert first["industry"] == "반도체"


def _write_run(run_id: str, records: list[dict], mtime: float | None = None) -> None:
    svc.ensure_storage()
    svc._write_run({
        "run_id": run_id,
        "title": run_id,
        "source_kind": "selenium_scrape",
        "created_at": "2026-07-25 10:00:00",
        "updated_at": "2026-07-25 10:00:00",
        "status": "completed",
        "record_count": len(records),
        "summary": {},
        "records": records,
    })
    if mtime is not None:
        path = svc.RUNS_DIR / f"{run_id}.json"
        os.utime(path, (mtime, mtime))


def test_industries_come_from_scraped_records_not_the_workbook(monkeypatch, tmp_path):
    """The workbook stores English industries; scraped rows carry the Korean ones
    the table actually filters on, so suggestions must use the scraped vocabulary."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [
        ("삼성전자 (005930)", "Semiconductors", "https://example.com/1"),
        ("SK하이닉스 (000660)", "Semiconductors", "https://example.com/2"),
        ("현대차 (005380)", "Auto Manufacturers", "https://example.com/3"),
    ])
    _write_run("manual_scrape_recent", [
        {"rank": 1, "stock_name": "삼성전자", "ticker": "005930",
         "industry": "반도체 및 반도체 장비", "scrape_state": "completed"},
        {"rank": 2, "stock_name": "SK하이닉스", "ticker": "000660",
         "industry": "반도체 및 반도체 장비", "scrape_state": "completed"},
        {"rank": 3, "stock_name": "현대차", "ticker": "005380",
         "industry": "자동차 및 자동차 부품", "scrape_state": "completed"},
    ])

    industries = {item["name"]: item["count"] for item in svc.build_search_index()["industries"]}

    assert industries == {"반도체 및 반도체 장비": 2, "자동차 및 자동차 부품": 1}


def test_pending_rows_do_not_contribute_industries(monkeypatch, tmp_path):
    """Unscraped rows still hold the workbook's English value -- ignore them."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [
        ("삼성전자 (005930)", "Semiconductors", "https://example.com/1"),
    ])
    _write_run("manual_scrape_live", [
        {"rank": 1, "stock_name": "삼성전자", "ticker": "005930",
         "industry": "반도체 및 반도체 장비", "scrape_state": "completed"},
        {"rank": 2, "stock_name": "SK하이닉스", "ticker": "000660",
         "industry": "Semiconductors", "scrape_state": "pending"},
    ])

    names = [item["name"] for item in svc.build_search_index()["industries"]]

    assert names == ["반도체 및 반도체 장비"]


def test_industries_fall_back_to_an_older_run_when_the_live_one_is_empty(monkeypatch, tmp_path):
    """A cycle that just started has no scraped rows yet; keep offering industries."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [("삼성전자 (005930)", "Semiconductors", "https://e.com/1")])
    _write_run("manual_scrape_old", [
        {"rank": 1, "stock_name": "삼성전자", "ticker": "005930",
         "industry": "반도체 및 반도체 장비", "scrape_state": "completed"},
    ], mtime=time.time() - 7200)
    _write_run("manual_scrape_fresh_empty", [
        {"rank": 1, "stock_name": "삼성전자", "ticker": "005930",
         "industry": "Semiconductors", "scrape_state": "pending"},
    ], mtime=time.time())

    names = [item["name"] for item in svc.build_search_index()["industries"]]

    assert names == ["반도체 및 반도체 장비"]


def test_new_industries_appear_without_the_workbook_changing(monkeypatch, tmp_path):
    """Industries come from runs, so the workbook-keyed cache must not freeze them."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [("삼성전자 (005930)", "Semiconductors", "https://e.com/1")])
    _write_run("manual_scrape_a", [
        {"rank": 1, "stock_name": "삼성전자", "ticker": "005930",
         "industry": "반도체 및 반도체 장비", "scrape_state": "completed"},
    ])
    assert [i["name"] for i in svc.build_search_index()["industries"]] == ["반도체 및 반도체 장비"]

    svc._industry_cache.clear()  # simulate the TTL lapsing
    _write_run("manual_scrape_b", [
        {"rank": 1, "stock_name": "현대차", "ticker": "005380",
         "industry": "자동차 및 자동차 부품", "scrape_state": "completed"},
    ], mtime=time.time() + 10)

    assert [i["name"] for i in svc.build_search_index()["industries"]] == ["자동차 및 자동차 부품"]


def test_industry_scan_is_cached_between_calls(monkeypatch, tmp_path):
    """Scanning parses ~1MB run files, so it must not run on every request."""
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [("삼성전자 (005930)", "Semiconductors", "https://e.com/1")])
    _write_run("manual_scrape_a", [
        {"rank": 1, "stock_name": "삼성전자", "ticker": "005930",
         "industry": "반도체 및 반도체 장비", "scrape_state": "completed"},
    ])
    svc.build_search_index()

    reads: list[int] = []
    original = svc._read_run
    monkeypatch.setattr(svc, "_read_run", lambda *a, **k: (reads.append(1), original(*a, **k))[1])

    svc.build_search_index()

    assert reads == []


def test_index_works_with_no_runs_at_all(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [("삼성전자 (005930)", "Semiconductors", "https://e.com/1")])

    index = svc.build_search_index()

    assert index["count"] == 1
    assert index["industries"] == []


def test_duplicate_rows_appear_once(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    _write_source(tmp_path / "stock_data.xlsx", [
        ("삼성전자 (005930)", "반도체", "https://example.com/1"),
        ("삼성전자 (005930)", "반도체", "https://example.com/1"),
    ])

    assert svc.build_search_index()["count"] == 1


def test_index_is_cached_until_the_workbook_changes(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    source = tmp_path / "stock_data.xlsx"
    _write_source(source, [("삼성전자 (005930)", "반도체", "https://example.com/1")])

    calls: list[int] = []
    original = svc._read_excel_records

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(svc, "_read_excel_records", counting)

    svc.build_search_index()
    svc.build_search_index()
    assert len(calls) == 1, "second call should be served from cache"

    _write_source(source, [
        ("삼성전자 (005930)", "반도체", "https://example.com/1"),
        ("현대차 (005380)", "자동차", "https://example.com/2"),
    ])
    assert svc.build_search_index()["count"] == 2
