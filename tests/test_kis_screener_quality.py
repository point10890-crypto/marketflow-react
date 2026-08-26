import json
import threading
from datetime import datetime, timedelta

import pytest
from filelock import FileLock

from app.services import kis_screener


class _Response:
    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _isolate_token_state(monkeypatch, tmp_path):
    monkeypatch.setattr(
        kis_screener, "_TOKEN_CACHE_FILE", str(tmp_path / "kis_token_cache.json")
    )
    monkeypatch.setattr(
        kis_screener, "SCREENER_POLLER_LOCK", str(tmp_path / "kis_poller.lock")
    )
    kis_screener._token_cache.update(
        {"token": None, "expires_at": 0, "namespace": None}
    )
    with kis_screener._result_lock:
        kis_screener._result_cache["data"] = None
        kis_screener._result_cache["ts"] = 0
    monkeypatch.setattr(kis_screener, "_pace_api_request", lambda: None)
    yield
    kis_screener._token_cache.update(
        {"token": None, "expires_at": 0, "namespace": None}
    )


def test_run_screening_has_one_cross_process_poller(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []
    first_result = []
    latest = {"timestamp": "2026-08-24T10:00:00", "results": [{"code": "001"}]}

    def slow_scan(force=False):
        calls.append(force)
        started.set()
        assert release.wait(timeout=2)
        return {"timestamp": datetime.now().isoformat(), "results": [], "by_grade": {}}

    monkeypatch.setattr(kis_screener, "_run_screening_unlocked", slow_scan)
    monkeypatch.setattr(
        kis_screener,
        "load_latest",
        lambda: latest,
    )

    worker = threading.Thread(
        target=lambda: first_result.append(kis_screener.run_screening(force=True)),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=1)

    busy = kis_screener.run_screening(force=True)
    assert busy["poller_busy"] is True
    assert busy["served_from"] == "poller_busy_cache"
    assert busy["poller_fallback_source"] == "latest_file"
    assert busy["timestamp"] == latest["timestamp"]
    assert "poller_busy" not in latest and "served_from" not in latest
    assert calls == [True]

    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert first_result and first_result[0].get("poller_busy") is None


def test_run_screening_enforces_shared_completion_gap_even_for_force(monkeypatch):
    calls = []
    latest = {
        "timestamp": datetime.now().isoformat(),
        "results": [{"code": "SAFE"}],
        "data_quality": {"safe_to_replace_latest": True},
    }

    def scan(force=False):
        calls.append(force)
        return dict(latest)

    monkeypatch.setattr(kis_screener, "_run_screening_unlocked", scan)
    monkeypatch.setattr(kis_screener, "load_latest", lambda: latest)

    first = kis_screener.run_screening(force=True)
    deferred = kis_screener.run_screening(force=True)

    assert first.get("poller_busy") is None
    assert calls == [True]
    assert deferred["poller_busy"] is True
    assert deferred["poller_backoff"] is True
    assert deferred["poller_backoff_reason"] == "completed"
    assert deferred["served_from"] == "poller_backoff_cache"
    assert 0 < deferred["retry_after_seconds"] <= 5.0


def test_unsafe_scan_uses_longer_shared_failure_cooldown(monkeypatch):
    calls = []
    unsafe = {
        "error": "kis_upstream_empty",
        "timestamp": datetime.now().isoformat(),
        "results": [],
        "data_quality": {"safe_to_replace_latest": False},
    }
    monkeypatch.setenv("KIS_SCREENER_MIN_SCAN_GAP_SECONDS", "0")
    monkeypatch.setenv("KIS_SCREENER_FAILURE_COOLDOWN_SECONDS", "30")
    monkeypatch.setattr(
        kis_screener,
        "_run_screening_unlocked",
        lambda force=False: calls.append(force) or unsafe,
    )
    monkeypatch.setattr(kis_screener, "load_latest", lambda: None)

    first = kis_screener.run_screening(force=True)
    deferred = kis_screener.run_screening(force=True)

    assert first is unsafe
    assert calls == [True]
    assert deferred["poller_backoff_reason"] == "unsafe_result"
    assert deferred["served_from"] == "poller_backoff_no_cache"
    assert deferred["retry_after_seconds"] > 29


@pytest.mark.parametrize(
    ("cache_age", "file_age", "expected_code", "expected_source"),
    [(10, 40, "CACHE", "memory_cache"), (40, 10, "FILE", "latest_file")],
)
def test_busy_fallback_selects_newest_normal_payload(
    monkeypatch, cache_age, file_age, expected_code, expected_source
):
    now = datetime.now()
    cached = {
        "timestamp": (now - timedelta(seconds=cache_age)).isoformat(),
        "results": [{"code": "CACHE"}],
        "data_quality": {"critical_complete": True},
    }
    latest = {
        "timestamp": (now - timedelta(seconds=file_age)).isoformat(),
        "results": [{"code": "FILE"}],
        "data_quality": {"critical_complete": True},
    }
    with kis_screener._result_lock:
        kis_screener._result_cache["data"] = cached
        kis_screener._result_cache["ts"] = 0
    monkeypatch.setattr(kis_screener, "load_latest", lambda: latest)

    result = kis_screener._poller_busy_result()

    assert result["results"][0]["code"] == expected_code
    assert result["poller_fallback_source"] == expected_source
    assert result["timestamp"] == (
        cached["timestamp"] if expected_code == "CACHE" else latest["timestamp"]
    )
    assert "poller_busy" not in cached and "poller_busy" not in latest


def test_busy_fallback_ignores_newer_unsafe_memory_scan(monkeypatch):
    now = datetime.now()
    unsafe = {
        "timestamp": (now - timedelta(seconds=5)).isoformat(),
        "results": [{"code": "UNSAFE"}],
        "data_quality": {
            "critical_complete": True,
            "score_reliable": False,
            "safe_to_replace_latest": False,
        },
    }
    latest = {
        "timestamp": (now - timedelta(seconds=30)).isoformat(),
        "results": [{"code": "SAFE"}],
        "data_quality": {
            "critical_complete": True,
            "score_reliable": True,
            "safe_to_replace_latest": True,
        },
    }
    with kis_screener._result_lock:
        kis_screener._result_cache["data"] = unsafe
        kis_screener._result_cache["ts"] = 0
    monkeypatch.setattr(kis_screener, "load_latest", lambda: latest)

    result = kis_screener._poller_busy_result()

    assert result["results"] == [{"code": "SAFE"}]
    assert result["poller_fallback_source"] == "latest_file"


def test_materially_future_result_is_never_fresh():
    now = datetime.now()
    future = {
        "timestamp": (now + timedelta(minutes=1)).isoformat(),
        "market_status": "open",
    }
    slight_clock_skew = {
        "timestamp": (now + timedelta(seconds=3)).isoformat(),
        "market_status": "open",
    }

    assert kis_screener.result_age_seconds(future, now=now) is None
    assert not kis_screener.is_live_result_fresh(future, now=now, max_age_seconds=90)
    assert kis_screener.result_age_seconds(slight_clock_skew, now=now) == 0.0
    assert kis_screener.is_live_result_fresh(
        slight_clock_skew, now=now, max_age_seconds=90
    )


def test_get_token_preserves_cached_absolute_expiry(monkeypatch, tmp_path):
    now = 1_800_000_000.0
    expires_at = now + 3600
    monkeypatch.setenv("KIS_APP_KEY", "cache-test-key")
    monkeypatch.setenv("KIS_APP_SECRET", "cache-test-secret")
    namespace = kis_screener._token_namespace()
    mode, fingerprint = namespace.split(":", 1)
    cache_path = tmp_path / "kis_token_cache.json"
    cache_path.write_text(
        json.dumps({
            "version": kis_screener._TOKEN_CACHE_VERSION,
            "tokens": {
                namespace: {
                    "token": "cached-token",
                    "expires_at": expires_at,
                    "mode": mode,
                    "app_key_fingerprint": fingerprint,
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(kis_screener.time, "time", lambda: now)
    monkeypatch.setattr(
        kis_screener.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a usable disk token must not be reissued")
        ),
    )

    assert kis_screener.get_token() == "cached-token"
    assert kis_screener._token_cache["expires_at"] == expires_at


def test_refresh_once_updates_following_calls_and_price_detail(monkeypatch):
    now = 1_800_000_000.0
    old_token = "expired-token"
    new_token = "refreshed-token"
    post_calls = []
    request_tokens = []
    monkeypatch.setenv("KIS_APP_KEY", "test-key")
    monkeypatch.setenv("KIS_APP_SECRET", "test-secret")
    kis_screener._token_cache.update({
        "token": old_token,
        "expires_at": now + 3600,
        "namespace": kis_screener._token_namespace(),
    })
    monkeypatch.setattr(kis_screener.time, "time", lambda: now)

    def fake_post(*args, **kwargs):
        post_calls.append(True)
        return _Response(
            200,
            {"access_token": new_token, "expires_in": 7200},
        )

    def fake_get(url, headers, params, timeout):
        request_token = headers["authorization"].removeprefix("Bearer ")
        request_tokens.append(request_token)
        if request_token == old_token:
            return _Response(401, {"msg_cd": "EGW00123"})
        if url.endswith("/inquire-price"):
            return _Response(200, {"rt_cd": "0", "output": {"stck_prpr": "1234"}})
        return _Response(200, {"rt_cd": "0", "output": [{"ok": "1"}]})

    monkeypatch.setattr(kis_screener.requests, "post", fake_post)
    monkeypatch.setattr(kis_screener.requests, "get", fake_get)

    assert kis_screener.fetch_volume_rank(old_token) == [{"ok": "1"}]
    assert kis_screener.fetch_fluctuation_rank(old_token) == [{"ok": "1"}]
    assert kis_screener.fetch_investor(old_token, "000001") == [{"ok": "1"}]
    assert kis_screener.fetch_price_detail(old_token, "000001") == {
        "stck_prpr": "1234"
    }

    assert len(post_calls) == 1
    assert request_tokens[0] == old_token
    assert request_tokens[1:] == [new_token, new_token, new_token, new_token]
    assert kis_screener._token_cache == {
        "token": new_token,
        "expires_at": now + 7200,
        "namespace": kis_screener._token_namespace(),
    }
    cache_text = open(
        kis_screener._TOKEN_CACHE_FILE, "r", encoding="utf-8"
    ).read()
    cache_doc = json.loads(cache_text)
    assert cache_doc["version"] == kis_screener._TOKEN_CACHE_VERSION
    assert list(cache_doc["tokens"]) == [kis_screener._token_namespace()]
    assert "test-key" not in cache_text
    assert "test-secret" not in cache_text


def test_token_cache_is_namespaced_by_mode_and_app_key(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "key-a")
    paper_namespace = kis_screener._token_namespace()
    monkeypatch.setenv("KIS_APP_KEY", "key-b")
    other_key_namespace = kis_screener._token_namespace()
    monkeypatch.setattr(kis_screener, "_paper", not kis_screener._paper)
    other_mode_namespace = kis_screener._token_namespace()

    assert paper_namespace != other_key_namespace
    assert other_key_namespace != other_mode_namespace
    assert "key-a" not in paper_namespace
    assert "key-b" not in other_key_namespace


def test_token_issuance_honors_process_shared_file_lock(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "locked-key")
    monkeypatch.setenv("KIS_APP_SECRET", "locked-secret")
    monkeypatch.setattr(kis_screener, "_TOKEN_LOCK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(
        kis_screener.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("token POST must not run without the process lock")
        ),
    )

    with FileLock(kis_screener._token_cache_lock_path()):
        assert kis_screener.get_token() is None


def test_rate_interval_uses_safe_paper_default_and_uncapped_override(monkeypatch):
    monkeypatch.delenv("KIS_API_MIN_REQUEST_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(kis_screener, "_paper", True)
    assert kis_screener._api_request_interval_seconds() == 0.5

    monkeypatch.setattr(kis_screener, "_paper", False)
    assert kis_screener._api_request_interval_seconds() == 0.2

    monkeypatch.setenv("KIS_API_MIN_REQUEST_INTERVAL_SECONDS", "5")
    assert kis_screener._api_request_interval_seconds() == 5.0


def test_investor_score_uses_latest_completed_row_after_live_blank_placeholder():
    rows = [
        {
            "stck_bsop_date": "20260824",
            "frgn_ntby_qty": "",
            "orgn_ntby_qty": "",
        },
        {
            "stck_bsop_date": "20260821",
            "frgn_ntby_qty": "2000",
            "orgn_ntby_qty": "3000",
        },
    ]

    assert kis_screener._has_investor_inputs(rows) is True
    assert kis_screener._select_investor_row(rows)["stck_bsop_date"] == "20260821"
    assert kis_screener._score_investor(rows) == (25, 2000, 3000)
    assert kis_screener._has_investor_inputs(rows[:1]) is False


def test_small_unknown_tail_can_publish_but_broad_gap_stays_fail_closed(monkeypatch):
    monkeypatch.delenv("KIS_SCREENER_MIN_RESOLVED_COVERAGE", raising=False)
    assert kis_screener._minimum_resolved_candidate_coverage() == 0.90
    assert kis_screener._resolved_candidate_coverage(31, 2) > 0.90
    assert kis_screener._resolved_candidate_coverage(9, 1) < 0.90
    assert kis_screener._resolved_candidate_coverage(0, 0) == 1.0


def test_shared_api_slots_serialize_same_account_but_not_other_key(monkeypatch):
    monkeypatch.setattr(kis_screener, "_paper", False)
    monkeypatch.setenv("KIS_APP_KEY", "account-a")

    first = kis_screener._reserve_shared_api_slot(0.2, now=100.0)
    second = kis_screener._reserve_shared_api_slot(0.2, now=100.0)

    monkeypatch.setenv("KIS_APP_KEY", "account-b")
    other_account = kis_screener._reserve_shared_api_slot(0.2, now=100.0)

    assert first == 0.0
    assert second == pytest.approx(0.2)
    assert other_account == 0.0


def test_shared_rate_limit_backoff_delays_peer_reservation(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "shared-rate-limit-account")

    wait = kis_screener._publish_shared_rate_limit_backoff(2.0, now=100.0)
    peer_delay = kis_screener._reserve_shared_api_slot(0.2, now=100.5)

    assert wait == 2.0
    assert peer_delay == pytest.approx(1.5)


def test_http_get_uses_pooled_session_when_transport_is_not_monkeypatched(monkeypatch):
    calls = []

    class _Session:
        def get(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "pooled-response"

    monkeypatch.setattr(kis_screener, "_http_session", lambda: _Session())

    result = kis_screener._http_get("https://example.test/quote", timeout=10)

    assert result == "pooled-response"
    assert calls == [(('https://example.test/quote',), {"timeout": 10})]


def test_api_get_retries_rate_limit_once_in_next_quota_window(monkeypatch):
    responses = iter([
        _Response(500, {"msg_cd": "EGW00201", "msg1": "rate limited"}),
        _Response(200, {"rt_cd": "0", "output": [{"ok": "1"}]}),
    ])
    http_calls = []
    sleeps = []

    def fake_get(*args, **kwargs):
        http_calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(kis_screener, "_active_request_token", lambda token=None: token)
    monkeypatch.setattr(kis_screener, "_http_get", fake_get)
    monkeypatch.setattr(
        kis_screener, "_publish_shared_rate_limit_backoff", lambda delay: 1.0
    )
    monkeypatch.setattr(kis_screener.time, "sleep", sleeps.append)

    with kis_screener._track_api_attempts() as tracker:
        result = kis_screener._api_get("token", "/quote", "TR", {})
        metrics = kis_screener._attempt_metrics(tracker, logical_calls=1)

    assert result == [{"ok": "1"}]
    assert len(http_calls) == 2
    assert sleeps == [1.0]
    assert metrics == {
        "logical_calls": 1,
        "get_attempts": 2,
        "token_issue_attempts": 0,
        "physical_attempts_total": 2,
        "rate_limit_responses": 1,
    }


def _ranking_row(*, prdy_vol="100000", trading_value=500_0000_0000, sector="T"):
    row = {
        "mksc_shrn_iscd": "000001",
        "stck_shrn_iscd": "000001",
        "hts_kor_isnm": "품질테스트",
        "stck_prpr": "1000",
        "prdy_ctrt": "10.0",
        "acml_tr_pbmn": str(trading_value),
        "acml_vol": "100000",
        "bstp_cls_code": sector,
    }
    if prdy_vol is not None:
        row["prdy_vol"] = prdy_vol
    return row


def _patch_complete_enrichment(monkeypatch):
    monkeypatch.setattr(kis_screener, "get_token", lambda: "token")
    monkeypatch.setattr(
        kis_screener,
        "fetch_investor",
        lambda token, code: [{"frgn_ntby_qty": "0", "orgn_ntby_qty": "0"}],
    )
    monkeypatch.setattr(
        kis_screener,
        "fetch_price_detail",
        lambda token, code: {
            "stck_prpr": "1000",
            "w52_hgpr": "2000",
            "w52_lwpr": "500",
            "w52_hgpr_date": "20200101",
        },
    )
    monkeypatch.setattr(kis_screener, "_time_weight", lambda: 1.0)
    monkeypatch.setattr(kis_screener.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(kis_screener, "_save_result", lambda result: None)


@pytest.mark.parametrize("prdy_vol", [None, "", "invalid", "0", 0, -1])
def test_invalid_previous_volume_never_manufactures_a_surge(prdy_vol):
    score, ratio = kis_screener._score_volume_surge(
        {"acml_vol": "999999999", "prdy_vol": prdy_vol}
    )

    assert score == 0
    assert ratio == 0.0


@pytest.mark.parametrize("ratio", [None, "", "invalid", "0", 0, -1])
def test_invalid_official_volume_ratio_never_manufactures_a_surge(ratio):
    score, parsed_ratio = kis_screener._score_volume_surge(
        {
            "acml_vol": "999999999",
            "prdy_vol": None,
            "prdy_vrss_vol_rate": ratio,
        }
    )

    assert score == 0
    assert parsed_ratio == 0.0


def test_annual_high_is_never_used_as_52_week_proxy():
    today = datetime.now().strftime("%Y%m%d")
    score, info = kis_screener._score_new_high(
        {
            "stck_dryy_hgpr": "100",
            "dryy_hgpr_date": today,
            "w52_hgpr": "200",
            "w52_hgpr_date": today,
        },
        100,
    )
    assert score == 0
    assert info["high_52w"] == 200
    assert info["distance_pct"] == 50.0

    unavailable_score, unavailable_info = kis_screener._score_new_high(
        {"stck_dryy_hgpr": "100", "dryy_hgpr_date": today}, 100
    )
    assert unavailable_score == 0
    assert unavailable_info == {}


def test_amount_rank_baseline_survives_blank_surge_row(monkeypatch):
    amount = _ranking_row(prdy_vol="50000")
    surge = dict(amount)
    surge.pop("prdy_vol")
    _patch_complete_enrichment(monkeypatch)
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [amount] if blng_code == "3" else [surge],
    )
    monkeypatch.setattr(
        kis_screener, "fetch_fluctuation_rank", lambda token: [amount]
    )

    result = kis_screener.run_screening(force=True)

    row = result["candidate_pool"][0]
    assert row["volume_ratio"] == 200.0
    assert row["score"]["volume_surge"] == 6
    assert row["volume_ratio_source"] == "volume_amount_rank.prdy_vol"
    assert row["score_complete"] is True
    assert result["data_quality"]["volume_baseline"]["sources"] == {
        "volume_amount_rank.prdy_vol": 1
    }


def test_surge_only_row_is_included_in_candidate_union(monkeypatch):
    amount = _ranking_row()
    surge = dict(_ranking_row(prdy_vol="25000"))
    surge.update({"mksc_shrn_iscd": "000002", "stck_shrn_iscd": "000002",
                  "hts_kor_isnm": "급증단독"})
    _patch_complete_enrichment(monkeypatch)
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [amount] if blng_code == "3" else [surge],
    )
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [amount])

    result = kis_screener.run_screening(force=True)
    rows = {row["code"]: row for row in result["candidate_pool"]}

    assert set(rows) == {"000001", "000002"}
    assert rows["000002"]["volume_ratio_source"] == "volume_surge_rank.prdy_vol"
    assert result["api_call_metrics"] == {
        "logical_calls": 7,
        "get_attempts": 0,
        "token_issue_attempts": 0,
        "physical_attempts_total": 0,
    }


def test_potential_grade_b_outside_top15_is_enriched_not_dropped(monkeypatch):
    rows = []
    for number in range(1, 16):
        row = _ranking_row()
        code = f"{number:06d}"
        row.update({
            "mksc_shrn_iscd": code,
            "stck_shrn_iscd": code,
            "hts_kor_isnm": f"상위{number}",
        })
        rows.append(row)

    possible = _ranking_row(trading_value=20_0000_0000, sector="")
    possible.update({
        "mksc_shrn_iscd": "000016",
        "stck_shrn_iscd": "000016",
        "hts_kor_isnm": "잠재주도주",
        "prdy_ctrt": "1.0",
    })
    rows.append(possible)

    investor_calls = []
    detail_calls = []
    monkeypatch.setattr(kis_screener, "get_token", lambda: "token")
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": rows,
    )
    monkeypatch.setattr(
        kis_screener, "fetch_fluctuation_rank", lambda token: rows[:1]
    )

    def fetch_investor(token, code):
        investor_calls.append(code)
        return [{"frgn_ntby_qty": "1", "orgn_ntby_qty": "1"}]

    def fetch_detail(token, code):
        detail_calls.append(code)
        return {
            "stck_prpr": "1000",
            "w52_hgpr": "2000",
            "w52_lwpr": "500",
            "w52_hgpr_date": "20200101",
        }

    monkeypatch.setattr(kis_screener, "fetch_investor", fetch_investor)
    monkeypatch.setattr(kis_screener, "fetch_price_detail", fetch_detail)
    monkeypatch.setattr(kis_screener, "_time_weight", lambda: 1.0)
    monkeypatch.setattr(kis_screener, "_save_result", lambda result: None)

    result = kis_screener.run_screening(force=True)
    result_by_code = {row["code"]: row for row in result["results"]}

    assert "000016" in investor_calls
    assert "000016" in detail_calls
    assert result_by_code["000016"]["grade"] == "B"
    assert result_by_code["000016"]["score_complete"] is True
    assert result["filter_summary"]["filtered_incomplete_score"] == 0
    assert result["api_call_breakdown"] == {
        "ranking": 3,
        "fluctuation_liquidity_detail": 0,
        "investor": 16,
        "candidate_detail": 16,
    }


def test_partial_detail_uses_missing_signal_upper_bounds_without_duplicate_detail(
    monkeypatch,
):
    amount_rows = []
    for number in range(1, 16):
        row = _ranking_row()
        code = f"{number:06d}"
        row.update({
            "mksc_shrn_iscd": code,
            "stck_shrn_iscd": code,
            "hts_kor_isnm": f"상위{number}",
        })
        amount_rows.append(row)

    fluctuation = {
        "stck_shrn_iscd": "000016",
        "hts_kor_isnm": "부분상세잠재주",
        "stck_prpr": "1000",
        "stck_hgpr": "1000",
        "prdy_ctrt": "1.0",
        "acml_vol": "3000000",
        "bstp_cls_code": "",
    }
    investor_calls = []
    detail_calls = []
    monkeypatch.setattr(kis_screener, "get_token", lambda: "token")
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": amount_rows,
    )
    monkeypatch.setattr(
        kis_screener, "fetch_fluctuation_rank", lambda token: [fluctuation]
    )

    def fetch_investor(token, code):
        investor_calls.append(code)
        return [{"frgn_ntby_qty": "1", "orgn_ntby_qty": "1"}]

    def fetch_detail(token, code):
        detail_calls.append(code)
        if code == "000016":
            # A truthy but incomplete fluctuation-liquidity response must not
            # make the missing high/volume upside disappear from the bound.
            return {
                "stck_prpr": "1000",
                "acml_tr_pbmn": str(20_0000_0000),
            }
        return {
            "stck_prpr": "1000",
            "w52_hgpr": "2000",
            "w52_hgpr_date": "20200101",
        }

    monkeypatch.setattr(kis_screener, "fetch_investor", fetch_investor)
    monkeypatch.setattr(kis_screener, "fetch_price_detail", fetch_detail)
    monkeypatch.setattr(kis_screener, "_time_weight", lambda: 0.8)
    monkeypatch.setattr(kis_screener, "_save_result", lambda result: None)

    result = kis_screener.run_screening(force=True)

    assert "000016" in investor_calls
    assert detail_calls.count("000016") == 1
    assert result["scan_profile"]["secondary_enrichment_candidates"] == 1
    assert result["data_quality"]["unresolved_potential_codes"] == ["000016"]
    # One guarded unknown among sixteen candidates remains a small tail. The
    # incomplete row is excluded from detection while complete rows stay live.
    assert result["data_quality"]["safe_to_replace_latest"] is True
    assert all(row["score_complete"] is True for row in result["results"])


def test_provably_c_incomplete_target_does_not_block_safe_empty_scan(monkeypatch):
    raw = _ranking_row(prdy_vol=None, trading_value=20_0000_0000, sector="")
    raw["prdy_ctrt"] = "0.0"
    monkeypatch.setattr(kis_screener, "get_token", lambda: "token")
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [raw],
    )
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [raw])
    monkeypatch.setattr(
        kis_screener,
        "fetch_investor",
        lambda token, code: [{"frgn_ntby_qty": "0", "orgn_ntby_qty": "0"}],
    )
    monkeypatch.setattr(
        kis_screener,
        "fetch_price_detail",
        lambda token, code: {
            "stck_prpr": "1000",
            "w52_hgpr": "2000",
            "w52_hgpr_date": "20200101",
        },
    )
    monkeypatch.setattr(kis_screener, "_time_weight", lambda: 1.0)
    monkeypatch.setattr(kis_screener, "_save_result", lambda result: None)

    result = kis_screener.run_screening(force=True)

    row = result["candidate_pool"][0]
    assert row["score"]["total"] == 10
    assert row["data_quality"]["score_upper_bound"] == 20
    assert row["rejection_reason"] == "below_grade_threshold"
    assert result["filter_summary"]["filtered_grade_c"] == 1
    assert result["filter_summary"]["filtered_incomplete_score"] == 0
    assert result["data_quality"]["unresolved_potential_codes"] == []
    assert result["data_quality"]["score_reliable"] is True
    assert result["data_quality"]["safe_to_replace_latest"] is True
    assert result["empty_reason"] == "below_grade_threshold"


def test_price_detail_official_ratio_recovers_missing_previous_volume(monkeypatch):
    raw = _ranking_row(prdy_vol=None)
    _patch_complete_enrichment(monkeypatch)
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [raw],
    )
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [raw])
    monkeypatch.setattr(
        kis_screener,
        "fetch_price_detail",
        lambda token, code: {
            "stck_prpr": "1000",
            "acml_vol": "100000",
            "acml_tr_pbmn": str(500_0000_0000),
            "prdy_vrss_vol_rate": "500.0",
            "w52_hgpr": "2000",
            "w52_lwpr": "500",
            "w52_hgpr_date": "20200101",
        },
    )

    result = kis_screener.run_screening(force=True)

    row = result["candidate_pool"][0]
    assert row["volume_ratio"] == 500.0
    assert row["score"]["volume_surge"] == 10
    assert row["volume_ratio_source"] == "price_detail.prdy_vrss_vol_rate"
    assert row["data_quality"]["inputs"]["prdy_vol"] == "available"
    assert row["score_complete"] is True
    assert result["data_quality"]["volume_baseline"]["missing_codes"] == []
    assert result["api_calls"] == 5
    assert result["api_call_breakdown"] == {
        "ranking": 3,
        "fluctuation_liquidity_detail": 0,
        "investor": 1,
        "candidate_detail": 1,
    }


def test_fluctuation_upper_bound_skips_impossible_liquidity_without_detail(monkeypatch):
    fluctuation = _ranking_row(prdy_vol=None, trading_value=0)
    fluctuation.pop("acml_tr_pbmn")
    fluctuation["stck_hgpr"] = "1000"
    fluctuation["acml_vol"] = "100000"
    _patch_complete_enrichment(monkeypatch)
    monkeypatch.setattr(kis_screener, "fetch_volume_rank", lambda *args: [])
    monkeypatch.setattr(
        kis_screener, "fetch_fluctuation_rank", lambda token: [fluctuation]
    )
    monkeypatch.setattr(
        kis_screener,
        "fetch_price_detail",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("impossible-liquidity row must not request detail")
        ),
    )

    result = kis_screener.run_screening(force=True)

    assert result["total_candidates"] == 0
    assert result["api_calls"] == 3
    assert result["scan_profile"]["liquidity_upper_bound_skips"] == 1


def test_missing_prdy_volume_is_unknown_and_cannot_raise_grade(monkeypatch):
    # Known inputs total 35 (C); the historical denominator=1 fallback added
    # 10 and incorrectly promoted this exact boundary case to B.
    raw = _ranking_row(prdy_vol=None, trading_value=20_0000_0000)
    _patch_complete_enrichment(monkeypatch)
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [raw],
    )
    # Keep every critical ranking source available while reusing the candidate.
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [raw])

    result = kis_screener.run_screening(force=True)

    assert result["results"] == []
    row = result["candidate_pool"][0]
    assert row["grade"] == "C"
    assert row["score"]["total"] == 35
    assert row["score"]["volume_surge"] == 0
    assert row["volume_ratio"] == 0.0
    assert row["score_complete"] is False
    assert row["incomplete_reasons"] == ["prdy_vol"]
    assert row["data_quality"]["score_interpretation"] == "lower_bound"
    assert result["data_quality"]["critical_complete"] is True
    assert result["data_quality"]["status"] == "partial"
    assert result["data_quality"]["volume_baseline"]["missing_codes"] == [
        "000001"
    ]
    assert result["data_quality"]["score_reliable"] is False
    assert result["data_quality"]["safe_to_replace_latest"] is False
    assert result["data_quality"]["unresolved_potential_codes"] == ["000001"]
    assert result["empty_reason"] == "score_inputs_incomplete"


def test_blank_sector_is_optional_and_does_not_make_score_incomplete(monkeypatch):
    # KIS ranking responses in production do not currently populate a usable
    # sector code. Sector momentum remains a zero-point optional signal; it
    # must not suppress otherwise valid NEW/UP/DROP monitoring events.
    raw = _ranking_row(sector="")
    _patch_complete_enrichment(monkeypatch)
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [raw],
    )
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [raw])

    result = kis_screener.run_screening(force=True)

    row = result["candidate_pool"][0]
    assert row["score"]["sector"] == 0
    assert row["score_complete"] is True
    assert row["incomplete_reasons"] == []
    assert row["data_quality"]["score_interpretation"] == "complete"
    assert result["data_quality"]["score_reliable"] is True


def test_partial_ranking_source_is_explicitly_critical(monkeypatch):
    raw = _ranking_row()
    _patch_complete_enrichment(monkeypatch)
    monkeypatch.setattr(
        kis_screener,
        "fetch_volume_rank",
        lambda token, blng_code="3": [raw],
    )
    monkeypatch.setattr(kis_screener, "fetch_fluctuation_rank", lambda token: [])

    result = kis_screener.run_screening(force=True)

    assert result["results"]
    quality = result["data_quality"]
    assert quality["status"] == "partial"
    assert quality["critical_complete"] is False
    assert quality["safe_to_replace_latest"] is False
    assert quality["missing_sources"] == ["fluctuation"]
    assert quality["source_status"]["fluctuation"] == {
        "status": "missing_or_empty",
        "rows": 0,
    }


def test_partial_critical_scan_does_not_replace_good_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(kis_screener, "DATA_DIR", str(tmp_path))
    latest = tmp_path / "screener_leading_latest.json"
    archive = tmp_path / f"screener_leading_{datetime.now():%Y%m%d}.json"
    good = {"timestamp": "good", "results": [{"code": "GOOD"}]}
    latest.write_text(json.dumps(good), encoding="utf-8")
    archive.write_text(json.dumps(good), encoding="utf-8")
    partial = {
        "timestamp": "partial",
        "results": [{"code": "PARTIAL"}],
        "data_quality": {
            "status": "partial",
            "critical_complete": False,
            "missing_sources": ["fluctuation"],
            "safe_to_replace_latest": False,
        },
    }

    kis_screener._save_result(partial)

    assert json.loads(latest.read_text(encoding="utf-8")) == good
    assert json.loads(archive.read_text(encoding="utf-8")) == good


def test_safe_empty_scan_replaces_stale_nonempty_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(kis_screener, "DATA_DIR", str(tmp_path))
    latest = tmp_path / "screener_leading_latest.json"
    archive = tmp_path / f"screener_leading_{datetime.now():%Y%m%d}.json"
    old = {"timestamp": "old", "results": [{"code": "OLD"}]}
    latest.write_text(json.dumps(old), encoding="utf-8")
    archive.write_text(json.dumps(old), encoding="utf-8")
    complete_empty = {
        "timestamp": "new",
        "results": [],
        "empty_reason": "below_grade_threshold",
        "data_quality": {
            "status": "complete",
            "critical_complete": True,
            "safe_to_replace_latest": True,
        },
    }

    kis_screener._save_result(complete_empty)

    assert json.loads(latest.read_text(encoding="utf-8")) == complete_empty
    assert json.loads(archive.read_text(encoding="utf-8")) == complete_empty
