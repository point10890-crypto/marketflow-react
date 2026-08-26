from app import (
    _screener_poll_interval_seconds,
    _screener_result_is_safe,
    _screener_stock_is_immediate_s,
)


def test_screener_poll_interval_defaults_to_quota_safe_cadence(monkeypatch):
    monkeypatch.delenv("KIS_SCREENER_POLL_INTERVAL_SECONDS", raising=False)
    assert _screener_poll_interval_seconds() == 30.0


def test_screener_poll_interval_is_bounded(monkeypatch):
    monkeypatch.setenv("KIS_SCREENER_POLL_INTERVAL_SECONDS", "1")
    assert _screener_poll_interval_seconds() == 15.0
    monkeypatch.setenv("KIS_SCREENER_POLL_INTERVAL_SECONDS", "900")
    assert _screener_poll_interval_seconds() == 300.0
    monkeypatch.setenv("KIS_SCREENER_POLL_INTERVAL_SECONDS", "invalid")
    assert _screener_poll_interval_seconds() == 30.0


def test_screener_worker_accepts_only_explicitly_safe_results():
    assert _screener_result_is_safe({
        "results": [],
        "data_quality": {"safe_to_replace_latest": True},
    }) is True
    assert _screener_result_is_safe({
        "results": [{"code": "000001"}],
        "data_quality": {"safe_to_replace_latest": False},
    }) is False
    assert _screener_result_is_safe({
        "poller_busy": True,
        "data_quality": {"safe_to_replace_latest": True},
    }) is False
    assert _screener_result_is_safe({
        "error": "kis_upstream_empty",
        "data_quality": {"safe_to_replace_latest": True},
    }) is False


def test_immediate_s_alert_ignores_async_enrichment_promotion():
    promoted = {
        "grade": "S",
        "score": {"total": 77, "total_enriched": 85},
    }
    base_s = {
        "grade": "S",
        "score": {"total": 80, "total_enriched": 88},
    }

    assert _screener_stock_is_immediate_s(promoted) is False
    assert _screener_stock_is_immediate_s(base_s) is True
    assert _screener_stock_is_immediate_s({"grade": "S"}) is True
