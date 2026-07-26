"""Filter for stocks newly upgraded to 적극 매수, measured day over day.

Comparing against the previous *cycle* would always report zero: the scraper runs
6-7 cycles a day and Investing.com verdicts do not move within a day. Measured on
production data (2026-07-26 6회차, 1,409 overlapping stocks): 0 changes against
the same day's earlier cycle, 1 against the previous day, ~43 against 07-14. So
the comparison unit is the newest run from an *earlier date*.
"""

import os
import time
from pathlib import Path

from app.services import manual_stock_analysis as svc


def _isolate_manual_service(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(svc, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(svc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(svc, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(svc, "DEFAULT_RESULT_PATHS", [])
    monkeypatch.setattr(svc, "AUTO_IMPORT_KNOWN_RESULTS", False)
    svc._prior_verdict_cache.clear()
    svc.ensure_storage()


def _record(name: str, ticker: str, result: str, state: str = "completed") -> dict:
    return {
        "rank": int(ticker),
        "stock_name": name,
        "ticker": ticker,
        "market": "KOSPI",
        "industry": "테스트",
        "source_url": f"https://example.com/{ticker}",
        "result": result,
        "raw_result": result,
        "analyzed_at": "10:00:00",
        "scrape_state": state,
    }


def _write_run(run_id: str, cycle_date: str, records: list[dict], mtime: float) -> None:
    svc._write_run({
        "run_id": run_id,
        "title": run_id,
        "source_kind": "selenium_scrape",
        "created_at": f"{cycle_date} 10:00:00",
        "updated_at": f"{cycle_date} 10:00:00",
        "cycle_date": cycle_date,
        "status": "completed",
        "record_count": len(records),
        "summary": svc._summary(records),
        "records": records,
    })
    path = svc.RUNS_DIR / f"{run_id}.json"
    os.utime(path, (mtime, mtime))


def test_flags_a_stock_that_moved_up_since_the_previous_day(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260725_090000_aaa", "2026-07-25", [
        _record("삼성전자", "005930", "매수"),
        _record("SK하이닉스", "000660", "적극 매수"),
        _record("현대차", "005380", "중립"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_bbb", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),   # 매수 -> 적극 매수 = upgrade
        _record("SK하이닉스", "000660", "적극 매수"),  # unchanged
        _record("현대차", "005380", "매수"),          # up, but not to 적극 매수
    ], mtime=base)

    detail = svc.get_run("manual_scrape_20260726_090000_bbb", result=svc.UPGRADE_FILTER)

    assert detail["upgraded_count"] == 1
    assert [r["ticker"] for r in detail["records"]] == ["005930"]


def test_earlier_cycles_from_the_same_day_are_not_the_comparison(monkeypatch, tmp_path):
    """Verdicts never move within a day, so same-day runs must be skipped."""
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260725_090000_aaa", "2026-07-25", [
        _record("삼성전자", "005930", "매수"),
    ], mtime=base - 86_400)
    # Same-day earlier cycle already shows 적극 매수; if it were used as the
    # baseline the upgrade would be invisible.
    _write_run("manual_scrape_20260726_010000_bbb", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base - 3600)
    _write_run("manual_scrape_20260726_090000_ccc", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base)

    detail = svc.get_run("manual_scrape_20260726_090000_ccc", result=svc.UPGRADE_FILTER)

    assert detail["upgraded_count"] == 1
    assert detail["records"][0]["ticker"] == "005930"


def test_falls_further_back_when_the_previous_day_has_no_verdict(monkeypatch, tmp_path):
    """분석중/오류 rows are not opinions -- keep looking for the last real one."""
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260724_090000_aaa", "2026-07-24", [
        _record("삼성전자", "005930", "중립"),
    ], mtime=base - 172_800)
    _write_run("manual_scrape_20260725_090000_bbb", "2026-07-25", [
        _record("삼성전자", "005930", "분석중", state="pending"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_ccc", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base)

    assert svc.get_run("manual_scrape_20260726_090000_ccc",
                       result=svc.UPGRADE_FILTER)["upgraded_count"] == 1


def test_first_appearance_is_not_an_upgrade(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260725_090000_aaa", "2026-07-25", [
        _record("삼성전자", "005930", "매수"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_bbb", "2026-07-26", [
        _record("삼성전자", "005930", "매수"),
        _record("신규상장", "999999", "적극 매수"),
    ], mtime=base)

    detail = svc.get_run("manual_scrape_20260726_090000_bbb", result=svc.UPGRADE_FILTER)

    assert detail["upgraded_count"] == 0
    assert detail["records"] == []


def test_already_strong_buy_yesterday_is_not_a_transition(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260725_090000_aaa", "2026-07-25", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_bbb", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base)

    assert svc.get_run("manual_scrape_20260726_090000_bbb",
                       result=svc.UPGRADE_FILTER)["upgraded_count"] == 0


def test_selecting_an_older_cycle_compares_against_its_own_past(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260724_090000_aaa", "2026-07-24", [
        _record("삼성전자", "005930", "매수"),
    ], mtime=base - 172_800)
    _write_run("manual_scrape_20260725_090000_bbb", "2026-07-25", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_ccc", "2026-07-26", [
        _record("삼성전자", "005930", "매수"),
    ], mtime=base)

    assert svc.get_run("manual_scrape_20260725_090000_bbb",
                       result=svc.UPGRADE_FILTER)["upgraded_count"] == 1
    svc._prior_verdict_cache.clear()
    assert svc.get_run("manual_scrape_20260724_090000_aaa",
                       result=svc.UPGRADE_FILTER)["upgraded_count"] == 0


def test_count_covers_the_run_while_the_query_narrows_the_rows(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260725_090000_aaa", "2026-07-25", [
        _record("삼성전자", "005930", "매수"),
        _record("현대차", "005380", "중립"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_bbb", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),
        _record("현대차", "005380", "적극 매수"),
    ], mtime=base)

    detail = svc.get_run("manual_scrape_20260726_090000_bbb",
                         result=svc.UPGRADE_FILTER, q="현대")

    assert detail["upgraded_count"] == 2
    assert [r["ticker"] for r in detail["records"]] == ["005380"]


def test_unfiltered_payload_still_reports_the_count(monkeypatch, tmp_path):
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260725_090000_aaa", "2026-07-25", [
        _record("삼성전자", "005930", "중립"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_bbb", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base)

    assert svc.get_run("manual_scrape_20260726_090000_bbb")["upgraded_count"] == 1
    assert svc.get_run("manual_scrape_20260726_090000_bbb",
                       result="적극 매수")["upgraded_count"] == 1


def test_prior_verdicts_are_cached_across_polls(monkeypatch, tmp_path):
    """/runs/<id> is polled every second while a cycle streams."""
    _isolate_manual_service(monkeypatch, tmp_path)
    base = time.time()
    _write_run("manual_scrape_20260725_090000_aaa", "2026-07-25", [
        _record("삼성전자", "005930", "매수"),
    ], mtime=base - 86_400)
    _write_run("manual_scrape_20260726_090000_bbb", "2026-07-26", [
        _record("삼성전자", "005930", "적극 매수"),
    ], mtime=base)
    svc.get_run("manual_scrape_20260726_090000_bbb")

    reads: list[Path] = []
    original = svc._read_run
    monkeypatch.setattr(svc, "_read_run", lambda p, *a, **k: (reads.append(p), original(p, *a, **k))[1])

    svc.get_run("manual_scrape_20260726_090000_bbb")

    assert [p.stem for p in reads] == ["manual_scrape_20260726_090000_bbb"], "prior runs re-parsed"
