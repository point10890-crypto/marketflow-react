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


def test_scrape_page_fields_uses_partial_dom_after_load_timeout(monkeypatch):
    class FakeElement:
        text = ""

    class FakeWait:
        def __init__(self, driver, timeout):
            self.driver = driver
            self.timeout = timeout

        def until(self, condition):
            return FakeElement()

    class FakeDriver:
        def set_page_load_timeout(self, timeout):
            self.timeout = timeout

        def get(self, url):
            raise TimeoutError("slow investing page")

        def execute_script(self, script):
            if "window.stop" in script:
                self.stopped = True
                return None
            return "Technical Summary Strong Buy\nIndustry: Semiconductors"

    monkeypatch.setattr("selenium.webdriver.support.ui.WebDriverWait", FakeWait)

    fields = svc._scrape_page_fields(FakeDriver(), "https://example.com", "//missing", timeout_sec=5)

    assert fields["result"] == "적극 매수"
    assert fields["industry"] == "Semiconductors"


def test_investing_snapshot_prefers_analyst_sentiment_over_technical():
    fields = svc._extract_investing_snapshot_fields("""
    005935 점수
    기술적 분석
    중립
    애널리스트 센티멘트
    적극 매수
    목표 주가
    348,450
    상승 여력 있음
    +63.98%
    산업
    컴퓨터, 전화 및 가전제품
    부문
    기술
    직원
    128735
    시장
    한국
    """)

    assert fields["result"] == "적극 매수"
    assert fields["technical_result"] == "중립"
    assert fields["analyst_sentiment"] == "적극 매수"
    assert fields["target_price"] == "348,450"
    assert fields["upside_potential"] == "+63.98%"
    assert fields["industry"] == "컴퓨터, 전화 및 가전제품"
    assert fields["sector"] == "기술"


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


def test_scrape_source_run_persists_investing_snapshot_fields(monkeypatch, tmp_path):
    _isolate_storage(monkeypatch, tmp_path)
    source_file = tmp_path / "stock_data.xlsx"
    pd.DataFrame([
        {"순번": 1, "종목": "삼성전자우 (005935)", "산업": "컴퓨터", "url": "https://example.com/pref"},
    ]).to_excel(source_file, index=False)

    class FakeDriver:
        def quit(self):
            return None

    def fake_scrape_page_fields(driver, url, xpath, *, timeout_sec):
        return {
            "result": "적극 매수",
            "technical_result": "중립",
            "analyst_sentiment": "적극 매수",
            "industry": "컴퓨터, 전화 및 가전제품",
            "sector": "기술",
            "target_price": "348,450",
            "upside_potential": "+63.98%",
        }

    monkeypatch.setattr(svc, "_create_selenium_driver", lambda: FakeDriver())
    monkeypatch.setattr(svc, "_scrape_page_fields", fake_scrape_page_fields)

    run = svc.scrape_source_run(
        max_rows=1,
        run_id="manual_scrape_snapshot_fields",
        persist_progress=True,
        delay_sec=0,
    )

    saved = svc.get_run(run["run_id"])
    record = saved["records"][0]
    assert record["result"] == "적극 매수"
    assert record["technical_result"] == "중립"
    assert record["analyst_sentiment"] == "적극 매수"
    assert record["industry"] == "컴퓨터, 전화 및 가전제품"
    assert record["sector"] == "기술"
    assert record["target_price"] == "348,450"
    assert record["upside_potential"] == "+63.98%"


def test_scrape_source_run_marks_collection_gap_as_analysis_pending(monkeypatch, tmp_path):
    _isolate_storage(monkeypatch, tmp_path)
    source_file = tmp_path / "stock_data.xlsx"
    pd.DataFrame([
        {"순번": 1, "종목": "삼성전자 (005930)", "산업": "반도체", "url": "https://example.com/a"},
    ]).to_excel(source_file, index=False)

    class FakeDriver:
        def quit(self):
            return None

    def fake_scrape_page_fields(driver, url, xpath, *, timeout_sec):
        raise TimeoutError("slow investing page")

    monkeypatch.setattr(svc, "_create_selenium_driver", lambda: FakeDriver())
    monkeypatch.setattr(svc, "_scrape_page_fields", fake_scrape_page_fields)

    run = svc.scrape_source_run(
        max_rows=1,
        run_id="manual_scrape_collection_gap",
        persist_progress=True,
        delay_sec=0,
    )

    assert run["status"] == "completed"
    assert run["summary"] == {"분석중": 1}
    saved = svc.get_run("manual_scrape_collection_gap")
    record = saved["records"][0]
    assert record["result"] == "분석중"
    assert record["raw_result"] == "분석중"
    assert record["scrape_state"] == "completed"
    assert record["scrape_fallback"] == "collection_gap"
    assert "TimeoutError" in record["error"]
