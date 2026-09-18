from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.services.ai_routing.contracts import Operation, ProviderAttempt, TokenUsage
from app.services.ai_routing.reporting import (
    get_llm_routing_status,
    get_llm_usage_report,
)
from app.services.ai_routing.store import RoutingStore
from app.services.ai_routing.telemetry import record_attempt


UTC = timezone.utc


@pytest.fixture()
def authorized_clients():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "MARKETFLOW_BACKGROUND_WORKERS": "false",
        "SECRET_KEY": "test-llm-routing-report-secret",
    })
    clients = {}
    with app.app_context():
        admin = User(
            email="llm-routing-admin@test.local",
            name="Routing Admin",
            role="admin",
            status="approved",
            tier="premium",
        )
        admin.set_password("test-password-1234")
        subscriber = User(
            email="llm-routing-aibain@test.local",
            name="Routing Subscriber",
            role="user",
            status="approved",
            tier="pro",
            aibain_enabled=True,
            aibain_expires_at=datetime.now(UTC) + timedelta(days=2),
        )
        subscriber.set_password("test-password-1234")
        db.session.add_all([admin, subscriber])
        db.session.commit()
        tokens = {"admin": generate_token(admin.id), "aibain": generate_token(subscriber.id)}
    for role, token in tokens.items():
        client = app.test_client()
        client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        clients[role] = client
    clients["anonymous"] = app.test_client()
    return clients


def _attempt(
    *,
    request_id: str,
    provider: str,
    endpoint: str,
    operation: Operation,
    event_ts: datetime,
    latency_ms: float,
    usage: TokenUsage,
    cost: str | None,
    status: str = "success",
    fallback_from: str | None = None,
) -> ProviderAttempt:
    return ProviderAttempt(
        request_id=request_id,
        run_id="run-report",
        provider=provider,
        model=f"{provider}-test-model",
        endpoint=f"https://{provider}.invalid/v1",
        caller_endpoint=endpoint,
        operation=operation,
        attempt_number=1,
        event_ts_utc=event_ts.isoformat(),
        selected=status == "success",
        status=status,
        latency_ms=latency_ms,
        max_output_tokens=100,
        usage=usage,
        estimated_cost_usd=Decimal(cost) if cost is not None else None,
        fallback_from=fallback_from,
    )


def test_routes_require_auth_and_allow_admin_or_aibain(authorized_clients, monkeypatch):
    import app.routes.admin_mirofish as routes

    monkeypatch.setattr(routes, "get_llm_routing_status", lambda: {"service": "ai-routing"})
    monkeypatch.setattr(routes, "get_llm_usage_report", lambda **kwargs: {"days": kwargs["days"]})

    assert authorized_clients["anonymous"].get(
        "/api/admin/mirofish/llm-routing/status"
    ).status_code == 401
    for role in ("admin", "aibain"):
        status = authorized_clients[role].get("/api/admin/mirofish/llm-routing/status")
        usage = authorized_clients[role].get("/api/admin/mirofish/llm-usage")
        assert status.status_code == usage.status_code == 200
        assert "no-store" in status.headers["Cache-Control"]
        assert "max-age=0" in status.headers["Cache-Control"]
        assert "no-store" in usage.headers["Cache-Control"]
        assert "max-age=0" in usage.headers["Cache-Control"]


@pytest.mark.parametrize(
    "query",
    [
        "days=0",
        "days=181",
        "days=+7",
        "days=%EF%BC%97",
        "days=7.0",
        "limit=0",
        "limit=51",
        "limit=",
    ],
)
def test_usage_route_rejects_non_strict_or_out_of_range_query(
    authorized_clients, monkeypatch, query
):
    import app.routes.admin_mirofish as routes

    monkeypatch.setattr(routes, "get_llm_usage_report", pytest.fail)
    response = authorized_clients["admin"].get(f"/api/admin/mirofish/llm-usage?{query}")

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_query"
    assert "no-store" in response.headers["Cache-Control"]
    assert "max-age=0" in response.headers["Cache-Control"]


@pytest.mark.parametrize("endpoint,function_name", [
    ("/api/admin/mirofish/llm-routing/status", "get_llm_routing_status"),
    ("/api/admin/mirofish/llm-usage", "get_llm_usage_report"),
])
def test_reporting_failure_is_fixed_sanitized_and_no_store(
    authorized_clients, monkeypatch, endpoint, function_name
):
    import app.routes.admin_mirofish as routes

    def fail(**_kwargs):
        raise RuntimeError("Authorization: Bearer should-never-escape")

    monkeypatch.setattr(routes, function_name, fail)
    response = authorized_clients["admin"].get(endpoint)

    assert response.status_code == 500
    assert "no-store" in response.headers["Cache-Control"]
    assert "max-age=0" in response.headers["Cache-Control"]
    assert response.get_json() == {
        "error": "llm_routing_report_unavailable",
        "message": "LLM routing report is temporarily unavailable",
    }
    assert "Bearer" not in response.get_data(as_text=True)


def test_usage_report_aggregates_attempts_without_turning_unknown_into_zero(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    rows = [
        _attempt(
            request_id="r1", provider="deepseek", endpoint="/api/z-low",
            operation=Operation.BULK_TEXT, event_ts=now - timedelta(hours=1),
            latency_ms=10, usage=TokenUsage(input_tokens=100, output_tokens=20), cost="0.10",
        ),
        _attempt(
            request_id="r2", provider="openai", endpoint="/api/a-high",
            operation=Operation.DECISIVE_TEXT, event_ts=now - timedelta(minutes=50),
            latency_ms=20, usage=TokenUsage(input_tokens=50, output_tokens=10), cost="0.30",
            fallback_from="deepseek",
        ),
        _attempt(
            request_id="r3", provider="deepseek", endpoint="/api/m-mid",
            operation=Operation.BULK_TEXT, event_ts=now - timedelta(minutes=40),
            latency_ms=30, usage=TokenUsage(input_tokens=30, output_tokens=10), cost="0.20",
        ),
        _attempt(
            request_id="r4", provider="deepseek", endpoint="/api/unknown",
            operation=Operation.BULK_TEXT, event_ts=now - timedelta(minutes=30),
            latency_ms=100, usage=TokenUsage.unknown(), cost=None, status="failed",
        ),
        _attempt(
            request_id="r5", provider="openai", endpoint="/api/skipped",
            operation=Operation.VISION, event_ts=now - timedelta(minutes=20),
            latency_ms=0, usage=TokenUsage.unknown(), cost=None, status="skipped_budget",
            fallback_from="gemini",
        ),
    ]
    for row in rows:
        assert record_attempt(row, store=store)

    report = get_llm_usage_report(days=7, limit=20, store=store, now=now)

    assert report["window"]["timezone"] == "UTC"
    assert report["window"]["start_utc"] == "2026-08-28T00:00:00+00:00"
    assert report["totals"]["attempts"] == 5
    assert report["totals"]["live_attempts"] == 4
    assert report["totals"]["fallbacks"] == 1
    assert report["fallback_attempt_share"] == 0.25
    assert report["totals"]["total_tokens"] is None
    assert report["totals"]["known_total_tokens"] == 220
    assert report["totals"]["estimated_cost_usd"] is None
    assert report["totals"]["known_estimated_cost_usd"] == "0.6"
    assert report["totals"]["unknown_usage_attempts"] == 1
    assert report["totals"]["latency_ms"] == {"p50": 25.0, "p95": 100.0}
    assert [row["endpoint"] for row in report["top_cost_endpoints"]][-1] == "/api/unknown"
    assert report["hold_review"] == {
        "available": False,
        "count": None,
        "rate": None,
        "reason": "final_outcome_not_recorded",
    }


def test_openai_shares_use_full_window_before_limit(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    for request_id, provider, endpoint, cost in (
        ("r1", "deepseek", "/api/one", "0.30"),
        ("r2", "deepseek", "/api/two", "0.20"),
        ("r3", "openai", "/api/three", "0.10"),
    ):
        record_attempt(_attempt(
            request_id=request_id, provider=provider, endpoint=endpoint,
            operation=Operation.BULK_TEXT, event_ts=now, latency_ms=10,
            usage=TokenUsage(input_tokens=8, output_tokens=2), cost=cost,
            fallback_from="deepseek" if provider == "openai" else None,
        ), store=store)

    report = get_llm_usage_report(days=1, limit=1, store=store, now=now)

    assert len(report["groups"]) == len(report["top_cost_endpoints"]) == 1
    assert report["openai_shares"] == {
        "attempts": pytest.approx(1 / 3),
        "tokens": pytest.approx(1 / 3),
        "cost": pytest.approx(1 / 6),
    }


def test_status_reads_only_allowlisted_fresh_health_breakers_and_utc_budget(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-for-test")
    store = RoutingStore(tmp_path / "usage.sqlite3")
    now = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:29:30+00:00",
        "ttl_seconds": 60,
        "providers": [{
            "provider": "deepseek",
            "operation": "decisive_text",
            "configured": True,
            "available": True,
            "model": "deepseek-v4-pro",
            "status": "healthy",
            "checked_at": "2026-09-03T00:29:30+00:00",
            "ttl_seconds": 60,
            "raw_error": "Authorization: Bearer leaked-secret",
            "api_key": "leaked-secret",
        }],
        "raw_response": "leaked-secret",
    }), encoding="utf-8")
    monkeypatch.setenv("AI_OPENAI_DAILY_BUDGET_USD", "1.25")
    with store.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO circuit_breakers
            (provider, modality, model_tier, state, failure_count, opened_at,
             last_error_class, probe_in_flight, updated_at)
            VALUES ('deepseek','text','decisive','open',2,1.0,'authentication',0,1.0)"""
        )
        connection.execute(
            """INSERT INTO budget_reservations
            (reservation_id,run_id,request_id,pool,provider,operation,reserved_calls,
             reserved_input_tokens,reserved_output_tokens,billing_day_utc,
             reserved_cost_usd,actual_cost_usd,status,created_at_utc)
            VALUES ('b1','run','req','automatic','openai','decisive_text',1,10,10,
                    '2026-09-03','0.5','0.4','settled','2026-09-03T00:10:00+00:00')"""
        )

    report = get_llm_routing_status(store=store, health_path=health_path, now=now)
    serialized = json.dumps(report)

    assert report["freshness"]["status"] == "fresh"
    deepseek = next(row for row in report["providers"] if row["provider"] == "deepseek" and row["operation"] == "decisive_text")
    assert deepseek["available"] is True and deepseek["status"] == "healthy"
    breaker = next(row for row in report["breakers"] if row["provider"] == "deepseek" and row["model_tier"] == "decisive")
    assert breaker["state"] == "open" and breaker["failure_count"] == 2
    assert report["budget"] == {
        "scope": "utc_calendar_day",
        "day_utc": "2026-09-03",
        "pool": "automatic",
        "provider": "openai",
        "daily_cap_usd_configured": True,
        "daily_cap_usd": "1.25",
        "used_usd": "0.4",
        "remaining_usd": "0.85",
        "usage_percent": 32.0,
        "status": "configured",
    }
    assert "leaked-secret" not in serialized and "raw_error" not in serialized
    with store.transaction() as connection:
        state = connection.execute(
            "SELECT state, probe_in_flight FROM circuit_breakers WHERE provider='deepseek'"
        ).fetchone()
    assert dict(state) == {"state": "open", "probe_in_flight": 0}


def test_stale_health_snapshot_is_unknown_not_configured_health(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:00:00+00:00",
        "ttl_seconds": 30,
        "providers": [{
            "provider": "deepseek", "operation": "decisive_text",
            "configured": True, "available": True, "model": "deepseek-v4-pro",
            "status": "healthy", "checked_at": "2026-09-03T00:00:00+00:00",
            "ttl_seconds": 30,
        }],
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store, health_path=health_path,
        now=datetime(2026, 9, 3, 0, 1, tzinfo=UTC),
    )

    assert report["freshness"]["status"] == "stale"
    deepseek = next(row for row in report["providers"] if row["provider"] == "deepseek" and row["operation"] == "decisive_text")
    assert deepseek["available"] is None
    assert deepseek["status"] == "unknown"


def test_fresh_snapshot_never_revives_a_stale_provider_record(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-for-test")
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:09:50+00:00",
        "ttl_seconds": 300,
        "providers": [{
            "provider": "deepseek", "operation": "decisive_text",
            "configured": True, "available": True, "model": "deepseek-v4-pro",
            "status": "healthy", "checked_at": "2026-09-03T00:00:00+00:00",
            "ttl_seconds": 60,
        }],
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store,
        health_path=health_path,
        now=datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )

    assert report["freshness"]["status"] == "fresh"
    deepseek = next(
        row for row in report["providers"]
        if row["provider"] == "deepseek" and row["operation"] == "decisive_text"
    )
    assert deepseek["available"] is None
    assert deepseek["status"] == "unknown"


def test_health_record_configuration_must_match_current_provider_state(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:09:50+00:00",
        "ttl_seconds": 300,
        "providers": [{
            "provider": "deepseek", "operation": "decisive_text",
            "configured": True, "available": True, "model": "deepseek-v4-pro",
            "status": "healthy", "checked_at": "2026-09-03T00:09:50+00:00",
            "ttl_seconds": 300,
        }],
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store,
        health_path=health_path,
        now=datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )

    deepseek = next(
        row for row in report["providers"]
        if row["provider"] == "deepseek" and row["operation"] == "decisive_text"
    )
    assert deepseek["configured"] is False
    assert deepseek["available"] is None
    assert deepseek["status"] == "unknown"


def test_whitespace_credential_is_not_currently_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "   ")
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:09:50+00:00",
        "ttl_seconds": 300,
        "providers": [{
            "provider": "deepseek", "operation": "decisive_text",
            "configured": True, "available": True, "model": "deepseek-v4-pro",
            "status": "healthy", "checked_at": "2026-09-03T00:09:50+00:00",
            "ttl_seconds": 300,
        }],
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store,
        health_path=health_path,
        now=datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )

    deepseek = next(
        row for row in report["providers"]
        if row["provider"] == "deepseek" and row["operation"] == "decisive_text"
    )
    assert deepseek["configured"] is False
    assert deepseek["available"] is None
    assert deepseek["status"] == "unknown"


def test_google_key_is_a_current_gemini_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "configured-for-test")
    monkeypatch.setenv("AI_GEMINI_VISION_MODEL", "gemini-2.5-pro")
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:09:50+00:00",
        "ttl_seconds": 300,
        "providers": [{
            "provider": "gemini", "operation": "vision",
            "configured": True, "available": True, "model": "gemini-2.5-pro",
            "status": "healthy", "checked_at": "2026-09-03T00:09:50+00:00",
            "ttl_seconds": 300,
        }],
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store,
        health_path=health_path,
        now=datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )

    gemini = next(
        row for row in report["providers"]
        if row["provider"] == "gemini" and row["operation"] == "vision"
    )
    assert gemini["configured"] is True
    assert gemini["available"] is True
    assert gemini["status"] == "healthy"


def test_unaccounted_health_snapshot_cannot_activate_deepseek_vision(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-for-test")
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:09:50+00:00",
        "ttl_seconds": 300,
        "telemetry": {"complete": False, "status": "unavailable"},
        "cost_saving_activation": {
            "ready": False,
            "status": "blocked",
            "reason": "health_accounting_unavailable",
        },
        "providers": [],
        "vision_attestation": {
            "provider": "deepseek",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-vision-tested",
            "modality": "vision",
            "checked_at": "2026-09-03T00:09:50+00:00",
            "ttl_seconds": 300,
            "capable": True,
            "healthy": True,
        },
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store,
        health_path=health_path,
        now=datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )

    assert report["provider_order"]["vision"] == ["gemini", "openai"]


@pytest.mark.parametrize("current_key", [None, "   "])
def test_saved_attestation_cannot_activate_unconfigured_deepseek_vision(
    tmp_path, monkeypatch, current_key
):
    if current_key is None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    else:
        monkeypatch.setenv("DEEPSEEK_API_KEY", current_key)
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:09:50+00:00",
        "ttl_seconds": 300,
        "telemetry": {"complete": True, "status": "complete"},
        "cost_saving_activation": {
            "ready": True,
            "status": "ready",
            "reason": "deepseek_decisive_healthy",
        },
        "providers": [],
        "vision_attestation": {
            "provider": "deepseek",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-vision-tested",
            "modality": "vision",
            "checked_at": "2026-09-03T00:09:50+00:00",
            "ttl_seconds": 300,
            "capable": True,
            "healthy": True,
        },
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store,
        health_path=health_path,
        now=datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )

    assert report["provider_order"]["vision"] == ["gemini", "openai"]


def test_fresh_snapshot_rejects_a_future_dated_provider_record(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-for-test")
    store = RoutingStore(tmp_path / "usage.sqlite3")
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps({
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-03T00:09:50+00:00",
        "ttl_seconds": 300,
        "providers": [{
            "provider": "deepseek", "operation": "decisive_text",
            "configured": True, "available": True, "model": "deepseek-v4-pro",
            "status": "healthy", "checked_at": "2026-09-03T00:10:01+00:00",
            "ttl_seconds": 300,
        }],
    }), encoding="utf-8")

    report = get_llm_routing_status(
        store=store,
        health_path=health_path,
        now=datetime(2026, 9, 3, 0, 10, tzinfo=UTC),
    )

    deepseek = next(
        row for row in report["providers"]
        if row["provider"] == "deepseek" and row["operation"] == "decisive_text"
    )
    assert deepseek["available"] is None
    assert deepseek["status"] == "unknown"
