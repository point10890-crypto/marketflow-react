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
    _reset_cache(None, 0)

    response = _client().get("/api/kr/screener/leading")

    assert response.status_code == 200
    data = response.get_json()
    assert data["served_from"] == "latest_file"
    assert data["freshness"]["is_stale"] is True
    assert data["stale_reason"] == "stale_result"
    assert data["live_refresh_recommended"] is False
