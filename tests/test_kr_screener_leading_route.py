from datetime import datetime, timedelta
import time

from flask import Flask

from app.routes.kr_market import kr_bp
from app.services import kis_screener


def _client():
    app = Flask(__name__)
    app.register_blueprint(kr_bp, url_prefix="/api/kr")
    return app.test_client()


def _reset_cache(data=None, ts=0):
    with kis_screener._result_lock:
        kis_screener._result_cache["data"] = data
        kis_screener._result_cache["ts"] = ts


def test_leading_endpoint_runs_live_scan_when_latest_file_is_stale(monkeypatch):
    stale = {
        "timestamp": (datetime.now() - timedelta(days=1)).isoformat(),
        "market_status": "closed",
        "results": [{"code": "000001", "name": "Old", "price": 100}],
    }
    fresh = {
        "timestamp": datetime.now().isoformat(),
        "market_status": "open",
        "results": [{"code": "000001", "name": "Fresh", "price": 222}],
        "by_grade": {},
        "total_candidates": 1,
        "time_weight": 1.0,
        "api_calls": 1,
        "elapsed_ms": 1,
    }
    calls = []

    monkeypatch.setattr(kis_screener, "is_market_open", lambda: True)
    monkeypatch.setattr(kis_screener, "load_latest", lambda: stale)
    monkeypatch.setattr(kis_screener, "run_screening", lambda: calls.append(True) or fresh)
    _reset_cache(stale, time.time())

    response = _client().get("/api/kr/screener/leading")

    assert response.status_code == 200
    data = response.get_json()
    assert calls == [True]
    assert data["served_from"] == "live_scan"
    assert data["live_refresh_recommended"] is True
    assert data["results"][0]["price"] == 222


def test_leading_endpoint_serves_fresh_live_file_without_rescan(monkeypatch):
    fresh = {
        "timestamp": datetime.now().isoformat(),
        "market_status": "open",
        "results": [{"code": "000001", "name": "Fresh", "price": 222}],
        "by_grade": {},
        "total_candidates": 1,
        "time_weight": 1.0,
        "api_calls": 1,
        "elapsed_ms": 1,
    }

    monkeypatch.setattr(kis_screener, "is_market_open", lambda: True)
    monkeypatch.setattr(kis_screener, "load_latest", lambda: fresh)
    monkeypatch.setattr(
        kis_screener,
        "run_screening",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected rescan")),
    )
    _reset_cache(None, 0)

    response = _client().get("/api/kr/screener/leading")

    assert response.status_code == 200
    data = response.get_json()
    assert data["served_from"] == "fresh_file"
    assert data["live_refresh_recommended"] is True
    assert data["results"][0]["price"] == 222


def test_leading_endpoint_marks_closed_market_stale_file(monkeypatch):
    stale = {
        "timestamp": (datetime.now() - timedelta(days=30)).isoformat(),
        "market_status": "closed",
        "results": [{"code": "000001", "name": "Old", "price": 100}],
        "by_grade": {},
    }

    monkeypatch.setattr(kis_screener, "is_market_open", lambda: False)
    monkeypatch.setattr(kis_screener, "load_latest", lambda: stale)
    monkeypatch.setattr(
        kis_screener,
        "run_screening",
        lambda **kwargs: {"error": "kis_upstream_empty", "results": []},
    )
    _reset_cache(None, 0)

    response = _client().get("/api/kr/screener/leading")

    assert response.status_code == 200
    data = response.get_json()
    assert data["served_from"] == "stale_file_fallback"
    assert data["freshness"]["is_stale"] is True
    assert data["stale_reason"] == "kis_upstream_empty"
    assert data["live_refresh_recommended"] is False


def test_leading_endpoint_refreshes_stale_closed_market_file(monkeypatch):
    stale = {
        "timestamp": (datetime.now() - timedelta(days=30)).isoformat(),
        "market_status": "closed",
        "results": [{"code": "000001", "name": "Old", "price": 100}],
        "by_grade": {},
    }
    refreshed = {
        "timestamp": datetime.now().isoformat(),
        "market_status": "closed",
        "results": [{"code": "000002", "name": "Refresh", "price": 300}],
        "by_grade": {"A": 1},
        "total_candidates": 1,
        "time_weight": 1.0,
        "api_calls": 3,
        "elapsed_ms": 2,
    }
    calls = []

    monkeypatch.setattr(kis_screener, "is_market_open", lambda: False)
    monkeypatch.setattr(kis_screener, "load_latest", lambda: stale)
    monkeypatch.setattr(kis_screener, "run_screening", lambda **kwargs: calls.append(kwargs) or refreshed)
    _reset_cache(None, 0)

    response = _client().get("/api/kr/screener/leading")

    assert response.status_code == 200
    data = response.get_json()
    assert calls == [{"force": True}]
    assert data["served_from"] == "offhours_refresh"
    assert data["results"][0]["name"] == "Refresh"
    assert data["freshness"]["is_stale"] is False


def test_run_screening_returns_error_without_overwriting_when_kis_sources_empty(monkeypatch):
    saved = []

    monkeypatch.setattr(kis_screener, "get_token", lambda: "token")
    monkeypatch.setattr(kis_screener, "fetch_volume_rank", lambda token, blng_code="3": [])
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [])
    monkeypatch.setattr(kis_screener, "_save_result", lambda result: saved.append(result))
    _reset_cache(None, 0)

    result = kis_screener.run_screening(force=True)

    assert result["error"] == "kis_upstream_empty"
    assert result["source_counts"] == {
        "volume_by_amount": 0,
        "fluctuation": 0,
        "volume_by_surge": 0,
    }
    assert result["results"] == []
    assert saved == []


def test_run_screening_marks_empty_when_candidates_are_below_grade_threshold(monkeypatch):
    saved = []
    raw = {
        "mksc_shrn_iscd": "000001",
        "hts_kor_isnm": "테스트",
        "stck_prpr": "1000",
        "prdy_ctrt": "1.0",
        "acml_tr_pbmn": str(20_0000_0000),
        "acml_vol": "10000",
        "prdy_vol": "10000",
        "bstp_cls_code": "T",
    }

    monkeypatch.setattr(kis_screener, "get_token", lambda: "token")
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [raw] if blng_code == "3" else [raw],
    )
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [])
    monkeypatch.setattr(kis_screener, "fetch_investor", lambda token, code: [])
    monkeypatch.setattr(kis_screener, "fetch_price_detail", lambda token, code: {})
    monkeypatch.setattr(kis_screener, "_time_weight", lambda: 0.8)
    monkeypatch.setattr(kis_screener, "_save_result", lambda result: saved.append(result))
    _reset_cache(None, 0)

    result = kis_screener.run_screening(force=True)

    assert result.get("error") is None
    assert result["empty_reason"] == "below_grade_threshold"
    assert result["filter_summary"] == {
        "scored_candidates": 1,
        "filtered_grade_c": 1,
        "min_grade": "B",
    }
    assert result["source_counts"] == {
        "volume_by_amount": 1,
        "fluctuation": 0,
        "volume_by_surge": 1,
    }
    assert result["results"] == []
    assert saved and saved[0]["empty_reason"] == "below_grade_threshold"
