from pathlib import Path
import time

import pandas as pd

from app.services import manual_stock_analysis as svc


def _isolate_storage(monkeypatch, tmp_path: Path) -> None:
    svc.stop_scraper_loop()
    if getattr(svc, "_LOOP_THREAD", None) is not None:
        svc._LOOP_THREAD.join(timeout=1)
    monkeypatch.setattr(svc, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(svc, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(svc, "DEFAULT_RESULT_PATHS", [])
    monkeypatch.setattr(svc, "DEFAULT_SOURCE_PATHS", [tmp_path / "stock_data.xlsx"])


def test_import_result_file_filters_and_exports(monkeypatch, tmp_path):
    _isolate_storage(monkeypatch, tmp_path)
    result_file = tmp_path / "result.xlsx"
    pd.DataFrame([
        {"순번": 1, "종목": "삼성전자 (005930)", "산업": "반도체", "분석 결과": "적극 매수", "오늘 날짜": "2026년07월06일"},
        {"순번": 2, "종목": "현대차 (005380)", "산업": "자동차", "분석 결과": "매도", "오늘 날짜": "2026년07월06일"},
        {"순번": 3, "종목": "SK하이닉스 (000660)", "산업": "반도체", "분석 결과": "중립", "오늘 날짜": "2026년07월06일"},
    ]).to_excel(result_file, index=False)

    run = svc.import_result_file(result_file)

    assert run["record_count"] == 3
    assert run["summary"]["적극 매수"] == 1
    assert run["summary"]["매도"] == 1
    filtered = svc.get_run(run["run_id"], result="적극 매수")
    assert filtered["filtered_count"] == 1
    assert filtered["records"][0]["ticker"] == "005930"

    payload, filename = svc.run_to_excel_bytes(run["run_id"], result="매도")
    assert filename.endswith("_manual_stock_analysis.xlsx")
    assert len(payload) > 1000


def test_pending_source_uses_analysis_in_progress_filter(monkeypatch, tmp_path):
    _isolate_storage(monkeypatch, tmp_path)
    source_file = tmp_path / "stock_data.xlsx"
    pd.DataFrame([
        {"순번": 1, "종목": "삼성전자", "url": "https://example.com/a"},
        {"순번": 2, "종목": "현대차", "url": "https://example.com/b"},
    ]).to_excel(source_file, index=False)

    run = svc.create_pending_run_from_source()

    assert run["record_count"] == 2
    assert run["summary"] == {"분석중": 2}
    assert {record["result"] for record in run["records"]} == {"분석중"}


def test_recommendation_parser_uses_anchored_fallback():
    text = """
    Company Profile
    Technical Summary
    Moving Averages Strong Buy
    Oscillators Neutral
    """

    assert svc._extract_recommendation_from_text(text) == "적극 매수"


def test_recommendation_parser_ignores_unanchored_ad_copy():
    text = "Subscribe now. Buy premium access today. Company profile only."

    assert svc._extract_recommendation_from_text(text) == ""


def test_scraper_loop_status_tracks_progress(monkeypatch, tmp_path):
    _isolate_storage(monkeypatch, tmp_path)

    def fake_scrape_source_run(**kwargs):
        progress_callback = kwargs.get("progress_callback")
        if progress_callback:
            progress_callback(1, 2, {"rank": 1, "stock_name": "삼성전자", "result": "매수"})
            progress_callback(2, 2, {"rank": 2, "stock_name": "현대차", "result": "중립"})
        return {"run_id": "manual_scrape_test", "record_count": 2}

    monkeypatch.setattr(svc, "scrape_source_run", fake_scrape_source_run)

    svc.start_scraper_loop(max_rows=2, interval_sec=60)
    status = svc.get_scraper_loop_status()
    for _ in range(50):
        if status.get("iterations", 0) >= 1:
            break
        time.sleep(0.02)
        status = svc.get_scraper_loop_status()

    assert status["last_run_id"] == "manual_scrape_test"
    assert status["processed"] == 2
    assert status["current_stock"] == "현대차"
    assert status["current_result"] == "중립"

    stopped = svc.stop_scraper_loop()
    assert stopped["running"] is False


def test_scrape_source_run_persists_live_progress_with_industry(monkeypatch, tmp_path):
    _isolate_storage(monkeypatch, tmp_path)
    source_file = tmp_path / "stock_data.xlsx"
    pd.DataFrame([
        {"순번": 1, "종목": "삼성전자 (005930)", "url": "https://example.com/a"},
        {"순번": 2, "종목": "현대차 (005380)", "url": "https://example.com/b"},
    ]).to_excel(source_file, index=False)

    class FakeDriver:
        def quit(self):
            return None

    calls = []

    def fake_scrape_page_fields(driver, url, xpath, *, timeout_sec):
        calls.append(url)
        if url.endswith("/a"):
            return {"result": "적극 매수", "industry": "반도체"}
        return {"result": "중립", "industry": "자동차"}

    monkeypatch.setattr(svc, "_create_selenium_driver", lambda: FakeDriver())
    monkeypatch.setattr(svc, "_scrape_page_fields", fake_scrape_page_fields)

    run = svc.scrape_source_run(
        max_rows=2,
        run_id="manual_scrape_live_test",
        persist_progress=True,
        delay_sec=0,
    )

    assert calls == ["https://example.com/a", "https://example.com/b"]
    assert run["run_id"] == "manual_scrape_live_test"
    assert run["status"] == "completed"
    assert run["summary"] == {"적극 매수": 1, "중립": 1}

    saved = svc.get_run("manual_scrape_live_test")
    assert saved["records"][0]["result"] == "적극 매수"
    assert saved["records"][0]["industry"] == "반도체"
    assert saved["records"][0]["analyzed_at"] >= run["created_at"]
    assert saved["records"][1]["industry"] == "자동차"
