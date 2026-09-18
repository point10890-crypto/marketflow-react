import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Barrier

import pytest

from app.services.ai_routing.contracts import Operation, ProviderAttempt, TokenUsage
from app.services.ai_routing.pricing import PricingRate, estimate_cost, estimate_cost_details
from app.services.ai_routing.store import RoutingStore
from app.services.ai_routing.telemetry import (
    allocate_and_record_attempt,
    record_attempt,
    usage_summary,
)


def _attempt(
    request_id: str,
    attempt_number: int,
    *,
    provider: str = "openai",
    endpoint: str = "/api/analyze",
    cost: str | None = "0.025",
    usage: TokenUsage | None = None,
) -> ProviderAttempt:
    return ProviderAttempt(
        request_id=request_id,
        run_id="run-1",
        provider=provider,
        model="gpt-5.5" if provider == "openai" else "deepseek-v4-pro",
        endpoint="chat.completions",
        operation=Operation.DECISIVE_TEXT,
        attempt_number=attempt_number,
        selected=True,
        status="success",
        latency_ms=25.0,
        max_output_tokens=1200,
        usage=usage or TokenUsage(input_tokens=100, cached_input_tokens=20, output_tokens=25),
        estimated_cost_usd=Decimal(cost) if cost is not None else None,
        pricing_version="test-v1" if cost is not None else None,
        caller_endpoint=endpoint,
    )


def test_duplicate_request_attempt_is_counted_once(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    attempt = _attempt("request-1", 1)

    assert record_attempt(attempt, store=ledger) is True
    assert record_attempt(attempt, store=ledger) is False

    summary = usage_summary(days=7, limit=20, store=ledger)
    assert summary["totals"]["attempts"] == 1


def test_atomic_attempt_allocation_is_global_across_runs_and_concurrent_writers(tmp_path):
    db_path = tmp_path / "usage.sqlite3"
    request_id = "shared-request"
    skipped = allocate_and_record_attempt(
        replace(
            _attempt(request_id, 0),
            run_id="run-skip",
            status="skipped_unconfigured",
            selected=False,
        ),
        store=RoutingStore(db_path),
    )

    start = Barrier(2)

    def record_live(run_id: str) -> ProviderAttempt:
        start.wait()
        return allocate_and_record_attempt(
            replace(_attempt(request_id, 1), run_id=run_id),
            store=RoutingStore(db_path),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        recorded = list(executor.map(record_live, ("run-a", "run-b")))

    with RoutingStore(db_path).transaction() as connection:
        rows = connection.execute(
            "SELECT attempt_number, run_id, status FROM provider_attempts "
            "WHERE request_id=? ORDER BY attempt_number",
            (request_id,),
        ).fetchall()

    assert skipped.attempt_number == 0
    assert sorted(item.attempt_number for item in recorded) == [1, 2]
    assert [(row[0], row[2]) for row in rows] == [
        (0, "skipped_unconfigured"),
        (1, "success"),
        (2, "success"),
    ]
    assert rows[0][1] == "run-skip"
    assert {rows[1][1], rows[2][1]} == {"run-a", "run-b"}


def test_cached_input_cannot_exceed_total_input():
    with pytest.raises(ValueError, match="cached input"):
        TokenUsage(input_tokens=10, cached_input_tokens=11, output_tokens=1)


def test_reasoning_tokens_are_not_double_counted():
    usage = TokenUsage(
        input_tokens=100,
        cached_input_tokens=0,
        output_tokens=20,
        reasoning_tokens=7,
        total_tokens=127,
    )

    assert usage.total_tokens == 120


def test_price_calculation_charges_cached_input_separately():
    usage = TokenUsage(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=10,
        reasoning_tokens=4,
    )

    cost = estimate_cost(
        "test-provider",
        "test-model",
        usage,
        rate=PricingRate(
            input_per_million=Decimal("5"),
            cached_input_per_million=Decimal("0.5"),
            output_per_million=Decimal("30"),
            version="test-v1",
        ),
    )

    assert cost == Decimal("0.00071")


def test_missing_native_usage_is_unknown_not_zero(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    record_attempt(_attempt("unknown-1", 1, cost=None, usage=TokenUsage.unknown()), store=ledger)

    summary = usage_summary(days=7, limit=20, store=ledger)

    assert summary["totals"]["unknown_usage_attempts"] == 1
    assert summary["totals"]["input_tokens"] is None
    assert summary["totals"]["estimated_cost_usd"] is None


def test_all_skipped_statuses_are_excluded_from_live_usage_and_fallbacks(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    statuses = (
        "skipped_unconfigured",
        "skipped_breaker",
        "skipped_budget",
        "skipped_future_guard",
    )

    for attempt_number, status in enumerate(statuses, start=1):
        attempt = _attempt(
            f"skipped-{attempt_number}",
            attempt_number,
            cost="0.50" if status == "skipped_breaker" else None,
            usage=(
                TokenUsage(input_tokens=400, cached_input_tokens=100, output_tokens=50)
                if status == "skipped_breaker"
                else TokenUsage.unknown()
            ),
        )
        record_attempt(
            replace(attempt, status=status, fallback_from="deepseek"),
            store=ledger,
        )

    totals = usage_summary(days=7, limit=20, store=ledger)["totals"]

    assert totals["attempts"] == 4
    assert totals["breaker_skipped_attempts"] == 1
    assert totals["live_attempts"] == 0
    assert totals["fallbacks"] == 0
    assert totals["input_tokens"] is None
    assert totals["cached_input_tokens"] is None
    assert totals["output_tokens"] is None
    assert totals["reasoning_tokens"] is None
    assert totals["total_tokens"] is None
    assert totals["known_estimated_cost_usd"] is None
    assert totals["estimated_cost_usd"] is None
    assert totals["unknown_usage_attempts"] == 0
    assert totals["quarantined_usage_attempts"] == 0
    assert totals["unknown_cost_attempts"] == 0
    assert totals["usage_completeness"] is None
    assert totals["cost_completeness"] is None


def test_partial_native_usage_is_marked_estimated():
    usage = TokenUsage(input_tokens=100, output_tokens=None)

    assert usage.usage_estimated is True
    assert usage.total_tokens is None


def test_attempt_schema_contains_no_secret_or_raw_content_fields(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    ledger.initialize()

    with sqlite3.connect(ledger.db_path) as connection:
        columns = {
            row[1].lower()
            for row in connection.execute("PRAGMA table_info(provider_attempts)").fetchall()
        }

    assert {"prompt", "response", "key", "api_key", "authorization"}.isdisjoint(columns)
    assert {"raw_total_tokens", "usage_mapping_version", "usage_mapping_status"} <= columns


def test_usage_mapping_evidence_and_quarantine_are_persisted(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    usage = TokenUsage(
        input_tokens=100,
        output_tokens=20,
        raw_total_tokens=999,
        mapping_version="provider-v1",
    )
    record_attempt(_attempt("quarantine", 1, usage=usage, cost=None), store=ledger)

    with sqlite3.connect(ledger.db_path) as connection:
        row = connection.execute(
            "SELECT raw_total_tokens, usage_mapping_version, usage_mapping_status, estimated_cost_usd "
            "FROM provider_attempts WHERE request_id = 'quarantine'"
        ).fetchone()

    assert row == (999, "provider-v1", "quarantined", None)


def test_deepseek_pricing_is_time_tiered_and_versioned():
    usage = TokenUsage(input_tokens=1_000_000, cached_input_tokens=0, output_tokens=0)

    peak = estimate_cost_details(
        "deepseek", "deepseek-v4-flash", usage, event_ts_utc="2026-09-02T02:00:00+00:00"
    )
    off_peak = estimate_cost_details(
        "deepseek", "deepseek-v4-flash", usage, event_ts_utc="2026-09-02T05:00:00+00:00"
    )

    assert peak.cost == Decimal("0.44")
    assert off_peak.cost == Decimal("0.220")
    assert peak.pricing_version.endswith(":peak")
    assert off_peak.pricing_version.endswith(":off_peak")


def test_operator_price_override_is_not_labeled_official(monkeypatch):
    monkeypatch.setenv("AI_ROUTING_PRICE_DEEPSEEK_INPUT_PER_MILLION", "1")
    monkeypatch.setenv("AI_ROUTING_PRICE_DEEPSEEK_OUTPUT_PER_MILLION", "2")
    monkeypatch.setenv("AI_ROUTING_PRICE_DEEPSEEK_VERSION", "operator-contract-7")

    estimate = estimate_cost_details(
        "deepseek",
        "deepseek-v4-flash",
        TokenUsage(input_tokens=10, output_tokens=10),
        event_ts_utc="2026-09-02T02:00:00+00:00",
    )

    assert estimate.pricing_version == "operator-contract-7"


def test_mixed_quarantined_usage_marks_token_and_cost_totals_partial(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    record_attempt(_attempt("known", 1, cost="0.10"), store=ledger)
    record_attempt(
        _attempt(
            "quarantined",
            1,
            cost=None,
            usage=TokenUsage(input_tokens=100, output_tokens=20, raw_total_tokens=999),
        ),
        store=ledger,
    )

    totals = usage_summary(1, 20, store=ledger)["totals"]

    assert totals["quarantined_usage_attempts"] == 1
    assert totals["unknown_usage_attempts"] == 1
    assert totals["unknown_cost_attempts"] == 1
    assert totals["usage_completeness"] == 0.5
    assert totals["cost_completeness"] == 0.5
    assert totals["estimated_cost_usd"] is None
    assert totals["known_estimated_cost_usd"] == "0.1"


def test_summary_groups_dimensions_and_ranks_cost_by_endpoint(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    record_attempt(_attempt("request-1", 1, endpoint="/api/cheap", cost="0.01"), store=ledger)
    record_attempt(
        _attempt(
            "request-2",
            1,
            endpoint="/api/expensive",
            cost="0.20",
            usage=TokenUsage(input_tokens=500, cached_input_tokens=100, output_tokens=50),
        ),
        store=ledger,
    )

    summary = usage_summary(days=7, limit=20, store=ledger)

    assert summary["groups"][0].keys() >= {
        "day", "provider", "model", "endpoint", "operation", "attempts", "estimated_cost_usd"
    }
    assert summary["top_cost_endpoints"][0]["endpoint"] == "/api/expensive"
    assert summary["top_cost_endpoints"][0]["estimated_cost_usd"] == "0.2"


def test_summary_ranking_ignores_skipped_cost_and_tokens_before_limit(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    record_attempt(
        replace(
            _attempt(
                "skipped-request",
                0,
                endpoint="/api/skipped-only",
                cost="9.00",
                usage=TokenUsage(
                    input_tokens=90_000,
                    cached_input_tokens=0,
                    output_tokens=9_000,
                ),
            ),
            operation=Operation.BULK_TEXT,
            selected=False,
            status="skipped_budget",
        ),
        store=ledger,
    )
    record_attempt(
        _attempt("live-request", 1, endpoint="/api/live", cost="0.01"),
        store=ledger,
    )

    summary = usage_summary(days=7, limit=1, store=ledger)

    assert summary["groups"][0]["endpoint"] == "/api/live"
    assert summary["groups"][0]["operation"] == "decisive_text"
    assert summary["top_cost_endpoints"][0]["endpoint"] == "/api/live"
    assert summary["totals"]["attempts"] == 2
    assert summary["totals"]["live_attempts"] == 1
    assert summary["totals"]["known_estimated_cost_usd"] == "0.01"


def test_summary_ranking_places_unknown_live_before_skipped_only_rows(tmp_path):
    ledger = RoutingStore(tmp_path / "usage.sqlite3")
    record_attempt(
        replace(
            _attempt(
                "skipped-request",
                0,
                endpoint="/api/a-skipped-only",
                cost="9.00",
                usage=TokenUsage(input_tokens=90_000, output_tokens=9_000),
            ),
            selected=False,
            status="skipped_budget",
        ),
        store=ledger,
    )
    record_attempt(
        replace(
            _attempt(
                "live-unknown-request",
                1,
                endpoint="/api/z-live-unknown",
                cost=None,
                usage=TokenUsage.unknown(),
            ),
            selected=False,
            status="failed",
        ),
        store=ledger,
    )

    summary = usage_summary(days=7, limit=1, store=ledger)

    assert summary["groups"][0]["endpoint"] == "/api/z-live-unknown"
    assert summary["groups"][0]["live_attempts"] == 1
    assert summary["top_cost_endpoints"][0]["endpoint"] == "/api/z-live-unknown"
    assert summary["top_cost_endpoints"][0]["live_attempts"] == 1
