import sqlite3
from decimal import Decimal

import pytest

from app.services.ai_routing.contracts import Operation, ProviderAttempt, TokenUsage
from app.services.ai_routing.pricing import PricingRate, estimate_cost
from app.services.ai_routing.store import RoutingStore
from app.services.ai_routing.telemetry import record_attempt, usage_summary


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
