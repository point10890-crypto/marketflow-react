"""Secret-free provider-attempt recording and usage aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .contracts import Operation, ProviderAttempt, ProviderErrorClass
from .pricing import estimate_cost_details
from .store import RoutingStore, default_store


def _value(value: object | None) -> object | None:
    return value.value if hasattr(value, "value") else value


def record_attempt(attempt: ProviderAttempt, *, store: RoutingStore | None = None) -> bool:
    """Insert one idempotent attempt. Returns whether a row was inserted."""
    ledger = store or default_store()
    usage = attempt.usage
    estimate = estimate_cost_details(
        attempt.provider,
        attempt.model,
        usage,
        event_ts_utc=attempt.event_ts_utc,
    )
    cost = None if usage.mapping_status == "quarantined" else attempt.estimated_cost_usd
    if cost is None and usage.mapping_status != "quarantined":
        cost = estimate.cost
    pricing_version = attempt.pricing_version or estimate.pricing_version
    values = (
        attempt.event_ts_utc,
        attempt.request_id,
        attempt.run_id,
        attempt.provider,
        attempt.model,
        attempt.endpoint,
        str(_value(attempt.operation)),
        attempt.attempt_number,
        int(attempt.selected),
        attempt.status,
        attempt.latency_ms,
        attempt.max_output_tokens,
        usage.input_tokens,
        usage.cached_input_tokens,
        usage.uncached_input_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
        usage.total_tokens,
        usage.raw_total_tokens,
        usage.mapping_version,
        usage.mapping_status,
        str(cost) if cost is not None else None,
        pricing_version,
        int(usage.usage_estimated),
        _value(attempt.error_class),
        attempt.fallback_from,
        attempt.breaker_state,
        int(attempt.cache_hit),
        attempt.symbol,
        attempt.market,
        attempt.caller_endpoint,
    )
    with ledger.transaction(write=True) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO provider_attempts (
                event_ts_utc, request_id, run_id, provider, model, endpoint,
                operation, attempt_number, selected, status, latency_ms,
                max_output_tokens, input_tokens, cached_input_tokens,
                uncached_input_tokens, output_tokens, reasoning_tokens,
                total_tokens, raw_total_tokens, usage_mapping_version,
                usage_mapping_status, estimated_cost_usd, pricing_version,
                usage_estimated, error_class, fallback_from, breaker_state,
                cache_hit, symbol, market, caller_endpoint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        return cursor.rowcount == 1


def _decimal_text(value: object | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).normalize())


def usage_summary(
    days: int,
    limit: int,
    *,
    store: RoutingStore | None = None,
) -> dict[str, Any]:
    if days <= 0 or limit <= 0:
        raise ValueError("days and limit must be positive")
    ledger = store or default_store()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with ledger.transaction() as connection:
        rows = connection.execute(
            """
            SELECT substr(event_ts_utc, 1, 10) AS day, provider, model,
                   COALESCE(caller_endpoint, endpoint) AS endpoint, operation,
                   COUNT(*) AS attempts,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes,
                   SUM(CASE WHEN fallback_from IS NOT NULL THEN 1 ELSE 0 END) AS fallbacks,
                   SUM(input_tokens) AS input_tokens,
                   SUM(cached_input_tokens) AS cached_input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(reasoning_tokens) AS reasoning_tokens,
                   SUM(total_tokens) AS total_tokens,
                   SUM(CAST(estimated_cost_usd AS REAL)) AS estimated_cost_usd,
                   SUM(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL THEN 1 ELSE 0 END)
                       AS unknown_usage_attempts
            FROM provider_attempts
            WHERE event_ts_utc >= ?
            GROUP BY day, provider, model, COALESCE(caller_endpoint, endpoint), operation
            ORDER BY SUM(CAST(estimated_cost_usd AS REAL)) DESC, SUM(total_tokens) DESC
            """,
            (cutoff,),
        ).fetchall()
        endpoint_rows = connection.execute(
            """
            SELECT COALESCE(caller_endpoint, endpoint) AS endpoint,
                   COUNT(*) AS attempts,
                   SUM(total_tokens) AS total_tokens,
                   SUM(CAST(estimated_cost_usd AS REAL)) AS estimated_cost_usd
            FROM provider_attempts
            WHERE event_ts_utc >= ?
            GROUP BY COALESCE(caller_endpoint, endpoint)
            ORDER BY SUM(CAST(estimated_cost_usd AS REAL)) DESC, SUM(total_tokens) DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        total = connection.execute(
            """
            SELECT COUNT(*) AS attempts, SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens, SUM(total_tokens) AS total_tokens,
                   SUM(CAST(estimated_cost_usd AS REAL)) AS estimated_cost_usd,
                   SUM(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL THEN 1 ELSE 0 END)
                       AS unknown_usage_attempts
            FROM provider_attempts WHERE event_ts_utc >= ?
            """,
            (cutoff,),
        ).fetchone()

    def mapped(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["estimated_cost_usd"] = _decimal_text(item.get("estimated_cost_usd"))
        return item

    totals = mapped(total)
    known_attempts = totals["attempts"] - totals["unknown_usage_attempts"]
    totals["usage_completeness"] = (
        known_attempts / totals["attempts"] if totals["attempts"] else None
    )
    return {
        "days": days,
        "groups": [mapped(row) for row in rows[:limit]],
        "top_cost_endpoints": [mapped(row) for row in endpoint_rows],
        "totals": totals,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
