"""Read-only, secret-free reporting over the central AI routing ledger."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.utils.paths import DATA_DIR

from .contracts import Operation, ProviderErrorClass
from .policy import policy_for
from .store import RoutingStore, default_store


HEALTH_SNAPSHOT_PATH = Path(DATA_DIR) / "ai_routing" / "health.json"
HEALTH_SCHEMA_VERSION = "ai-routing-health-v1"
USAGE_SCHEMA_VERSION = "ai-routing-usage-v1"
STATUS_SCHEMA_VERSION = "ai-routing-status-v1"
_MAX_HEALTH_BYTES = 64 * 1024
_MAX_HEALTH_TTL_SECONDS = 86_400
_USAGE_FRESHNESS_TTL_SECONDS = 300
_PROVIDERS = {"deepseek", "openai", "gemini"}
_HEALTH_STATUSES = {
    "healthy",
    "authentication",
    "billing",
    "insufficient_balance",
    "rate_limit",
    "timeout",
    "connection",
    "server_error",
    "model_unavailable",
    "unavailable",
    "unknown",
}
_ERROR_CLASSES = {item.value for item in ProviderErrorClass}


def _utc_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_ttl(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0 or value > _MAX_HEALTH_TTL_SECONDS:
        return None
    return value


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(value for value in values if math.isfinite(value) and value >= 0)
    if not ordered:
        return None
    if percentile == 0.5:
        middle = len(ordered) // 2
        value = (
            (ordered[middle - 1] + ordered[middle]) / 2
            if len(ordered) % 2 == 0
            else ordered[middle]
        )
    else:
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        value = ordered[index]
    return round(float(value), 3)


def _is_physical_attempt(status: object) -> bool:
    return not str(status or "").startswith("skipped_")


def _new_metrics() -> dict[str, Any]:
    return {
        "attempts": 0,
        "live_attempts": 0,
        "breaker_skipped_attempts": 0,
        "successes": 0,
        "fallbacks": 0,
        "input_tokens_known": 0,
        "cached_input_tokens_known": 0,
        "output_tokens_known": 0,
        "reasoning_tokens_known": 0,
        "total_tokens_known": 0,
        "known_cost": Decimal("0"),
        "unknown_usage_attempts": 0,
        "quarantined_usage_attempts": 0,
        "unknown_cost_attempts": 0,
        "latencies": [],
    }


def _add_row(metrics: dict[str, Any], row: Mapping[str, Any]) -> None:
    metrics["attempts"] += 1
    status = str(row.get("status") or "")
    if status == "skipped_breaker":
        metrics["breaker_skipped_attempts"] += 1
    if not _is_physical_attempt(status):
        return
    metrics["live_attempts"] += 1
    if status == "success":
        metrics["successes"] += 1
    if row.get("fallback_from") is not None:
        metrics["fallbacks"] += 1

    try:
        latency = float(row.get("latency_ms"))
    except (TypeError, ValueError):
        latency = -1
    if math.isfinite(latency) and latency >= 0:
        metrics["latencies"].append(latency)

    quarantined = row.get("usage_mapping_status") == "quarantined"
    usage_known = (
        not quarantined
        and row.get("input_tokens") is not None
        and row.get("output_tokens") is not None
    )
    if quarantined:
        metrics["quarantined_usage_attempts"] += 1
    if not usage_known:
        metrics["unknown_usage_attempts"] += 1
    else:
        input_tokens = int(row.get("input_tokens") or 0)
        output_tokens = int(row.get("output_tokens") or 0)
        metrics["input_tokens_known"] += input_tokens
        metrics["cached_input_tokens_known"] += int(row.get("cached_input_tokens") or 0)
        metrics["output_tokens_known"] += output_tokens
        metrics["reasoning_tokens_known"] += int(row.get("reasoning_tokens") or 0)
        metrics["total_tokens_known"] += input_tokens + output_tokens

    cost = None if quarantined else _decimal(row.get("estimated_cost_usd"))
    if cost is None:
        metrics["unknown_cost_attempts"] += 1
    else:
        metrics["known_cost"] += cost


def _finalize_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    live = int(metrics["live_attempts"])
    unknown_usage = int(metrics["unknown_usage_attempts"])
    unknown_cost = int(metrics["unknown_cost_attempts"])
    usage_known = unknown_usage == 0
    cost_known = unknown_cost == 0
    result = {
        "attempts": int(metrics["attempts"]),
        "live_attempts": live,
        "breaker_skipped_attempts": int(metrics["breaker_skipped_attempts"]),
        "successes": int(metrics["successes"]),
        "fallbacks": int(metrics["fallbacks"]),
        "input_tokens": int(metrics["input_tokens_known"]) if usage_known else None,
        "cached_input_tokens": int(metrics["cached_input_tokens_known"]) if usage_known else None,
        "output_tokens": int(metrics["output_tokens_known"]) if usage_known else None,
        "reasoning_tokens": int(metrics["reasoning_tokens_known"]) if usage_known else None,
        "total_tokens": int(metrics["total_tokens_known"]) if usage_known else None,
        "known_input_tokens": int(metrics["input_tokens_known"]),
        "known_output_tokens": int(metrics["output_tokens_known"]),
        "known_total_tokens": int(metrics["total_tokens_known"]),
        "known_estimated_cost_usd": _decimal_text(metrics["known_cost"]),
        "estimated_cost_usd": _decimal_text(metrics["known_cost"]) if cost_known else None,
        "unknown_usage_attempts": unknown_usage,
        "quarantined_usage_attempts": int(metrics["quarantined_usage_attempts"]),
        "unknown_cost_attempts": unknown_cost,
        "usage_completeness": ((live - unknown_usage) / live) if live else None,
        "cost_completeness": ((live - unknown_cost) / live) if live else None,
        "latency_ms": {
            "p50": _percentile(metrics["latencies"], 0.5),
            "p95": _percentile(metrics["latencies"], 0.95),
        },
    }
    return result


def _report_sort_key(item: Mapping[str, Any], label: str) -> tuple[Any, ...]:
    # Fully known zero is a real value; incomplete/unknown totals are always last.
    unknown_cost = item.get("estimated_cost_usd") is None
    unknown_usage = item.get("total_tokens") is None
    cost = _decimal(item.get("known_estimated_cost_usd")) or Decimal("0")
    tokens = int(item.get("known_total_tokens") or 0)
    return (unknown_cost, -cost, unknown_usage, -tokens, str(item.get(label) or ""))


def _usage_freshness(rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    parsed = [_parse_utc(row.get("event_ts_utc")) for row in rows]
    timestamps = [item for item in parsed if item is not None]
    if not timestamps:
        return {
            "status": "unknown",
            "last_event_at": None,
            "age_seconds": None,
            "ttl_seconds": _USAGE_FRESHNESS_TTL_SECONDS,
        }
    latest = max(timestamps)
    age = (now - latest).total_seconds()
    status = "unknown" if age < 0 else "fresh" if age < _USAGE_FRESHNESS_TTL_SECONDS else "stale"
    return {
        "status": status,
        "last_event_at": latest.isoformat(),
        "age_seconds": round(age, 3) if age >= 0 else None,
        "ttl_seconds": _USAGE_FRESHNESS_TTL_SECONDS,
    }


def get_llm_usage_report(
    *,
    days: int = 7,
    limit: int = 20,
    store: RoutingStore | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate provider attempts for the last UTC calendar-day window."""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 180:
        raise ValueError("days must be an integer between 1 and 180")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50")
    current = _utc_now(now)
    start = datetime.combine(
        current.date() - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc
    )
    ledger = store or default_store()
    with ledger.transaction() as connection:
        raw_rows = connection.execute(
            """SELECT event_ts_utc, provider, model, endpoint, caller_endpoint,
                      operation, status, latency_ms, input_tokens,
                      cached_input_tokens, output_tokens, reasoning_tokens,
                      total_tokens, usage_mapping_status, estimated_cost_usd,
                      fallback_from
               FROM provider_attempts
               WHERE event_ts_utc >= ? AND event_ts_utc <= ?""",
            (start.isoformat(), current.isoformat()),
        ).fetchall()
    rows = [dict(row) for row in raw_rows]

    total_metrics = _new_metrics()
    openai_metrics = _new_metrics()
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = defaultdict(_new_metrics)
    endpoints: dict[str, dict[str, Any]] = defaultdict(_new_metrics)
    operations: dict[str, dict[str, Any]] = defaultdict(_new_metrics)
    for row in rows:
        endpoint = str(row.get("caller_endpoint") or row.get("endpoint") or "unknown")
        operation = str(row.get("operation") or "unknown")
        day = str(row.get("event_ts_utc") or "")[:10]
        key = (
            day,
            str(row.get("provider") or "unknown"),
            str(row.get("model") or "unknown"),
            endpoint,
            operation,
        )
        _add_row(total_metrics, row)
        if str(row.get("provider") or "").lower() == "openai":
            _add_row(openai_metrics, row)
        _add_row(grouped[key], row)
        _add_row(endpoints[endpoint], row)
        _add_row(operations[operation], row)

    totals = _finalize_metrics(total_metrics)
    openai = _finalize_metrics(openai_metrics)
    groups = [
        {
            "day": key[0], "provider": key[1], "model": key[2],
            "endpoint": key[3], "operation": key[4],
            **_finalize_metrics(metrics),
        }
        for key, metrics in grouped.items()
    ]
    endpoint_rows = [
        {"endpoint": endpoint, **_finalize_metrics(metrics)}
        for endpoint, metrics in endpoints.items()
    ]
    operation_rows = [
        {"operation": operation, **_finalize_metrics(metrics)}
        for operation, metrics in operations.items()
    ]
    groups.sort(key=lambda item: _report_sort_key(item, "endpoint"))
    endpoint_rows.sort(key=lambda item: _report_sort_key(item, "endpoint"))
    operation_rows.sort(key=lambda item: _report_sort_key(item, "operation"))

    attempts_share = openai["live_attempts"] / totals["live_attempts"] if totals["live_attempts"] else None
    if totals["unknown_usage_attempts"]:
        token_share = None
    elif totals["known_total_tokens"]:
        token_share = openai["known_total_tokens"] / totals["known_total_tokens"]
    else:
        token_share = 0.0
    total_cost = _decimal(totals["known_estimated_cost_usd"]) or Decimal("0")
    openai_cost = _decimal(openai["known_estimated_cost_usd"]) or Decimal("0")
    if totals["unknown_cost_attempts"]:
        cost_share = None
    elif total_cost:
        cost_share = float(openai_cost / total_cost)
    else:
        cost_share = 0.0
    fallback_share = totals["fallbacks"] / totals["live_attempts"] if totals["live_attempts"] else None

    return {
        "schema_version": USAGE_SCHEMA_VERSION,
        "days": days,
        "limit": limit,
        "window": {
            "start_utc": start.isoformat(),
            "end_utc": current.isoformat(),
            "timezone": "UTC",
        },
        "groups": groups[:limit],
        "top_cost_endpoints": endpoint_rows[:limit],
        "top_operations": operation_rows[:limit],
        "totals": totals,
        "openai_shares": {
            "attempts": attempts_share,
            "tokens": token_share,
            "cost": cost_share,
        },
        "fallback_count": totals["fallbacks"],
        "fallback_attempt_share": fallback_share,
        "hold_review": {
            "available": False,
            "count": None,
            "rate": None,
            "reason": "final_outcome_not_recorded",
        },
        "freshness": _usage_freshness(rows, current),
        "generated_at": current.isoformat(),
    }


def _load_health_snapshot(path: Path, now: datetime) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    unknown = {
        "status": "unknown", "checked_at": None,
        "age_seconds": None, "ttl_seconds": None,
    }
    if path.name != "health.json":
        return None, unknown
    try:
        if not path.is_file() or path.stat().st_size > _MAX_HEALTH_BYTES:
            return None, unknown
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, unknown
    if not isinstance(value, dict) or value.get("schema_version") != HEALTH_SCHEMA_VERSION:
        return None, unknown
    checked_at = _parse_utc(value.get("checked_at"))
    ttl = _safe_ttl(value.get("ttl_seconds"))
    providers = value.get("providers")
    if checked_at is None or ttl is None or not isinstance(providers, list):
        return None, unknown
    age = (now - checked_at).total_seconds()
    status = "unknown" if age < 0 else "fresh" if age < ttl else "stale"
    freshness = {
        "status": status,
        "checked_at": checked_at.isoformat(),
        "age_seconds": round(age, 3) if age >= 0 else None,
        "ttl_seconds": ttl,
    }
    return value, freshness


def _provider_is_configured(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def _provider_slots() -> list[dict[str, Any]]:
    decisive = policy_for(Operation.DECISIVE_TEXT)
    vision = policy_for(Operation.VISION)
    slots = [
        {
            "provider": "deepseek", "operation": Operation.DECISIVE_TEXT.value,
            "configured": _provider_is_configured("DEEPSEEK_API_KEY"),
            "model": decisive.models["deepseek"],
        },
        {
            "provider": "openai", "operation": Operation.DECISIVE_TEXT.value,
            "configured": _provider_is_configured("OPENAI_API_KEY"),
            "model": decisive.models["openai"],
        },
        {
            "provider": "gemini", "operation": Operation.VISION.value,
            "configured": _provider_is_configured("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "model": vision.models["gemini"],
        },
    ]
    deepseek_vision = str(vision.models.get("deepseek_vision") or "")
    if deepseek_vision:
        slots.append({
            "provider": "deepseek", "operation": Operation.VISION.value,
            "configured": _provider_is_configured("DEEPSEEK_API_KEY"),
            "model": deepseek_vision,
        })
    return slots


def _providers_from_health(
    snapshot: dict[str, Any] | None,
    freshness: Mapping[str, Any],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    slots = _provider_slots()
    fresh = freshness.get("status") == "fresh"
    records: dict[tuple[str, str], Mapping[str, Any]] = {}
    if fresh and snapshot is not None:
        for candidate in snapshot.get("providers", []):
            if not isinstance(candidate, Mapping):
                continue
            provider = candidate.get("provider")
            operation = candidate.get("operation")
            if provider not in _PROVIDERS or not isinstance(operation, str):
                continue
            records[(str(provider), operation)] = candidate

    result = []
    for slot in slots:
        record = records.get((slot["provider"], slot["operation"]))
        status = record.get("status") if record is not None else None
        available = record.get("available") if record is not None else None
        record_model = record.get("model") if record is not None else None
        record_configured = record.get("configured") if record is not None else None
        checked_at = _parse_utc(record.get("checked_at")) if record is not None else None
        ttl = _safe_ttl(record.get("ttl_seconds")) if record is not None else None
        age_seconds = (now - checked_at).total_seconds() if checked_at is not None else None
        record_valid = (
            record is not None
            and status in _HEALTH_STATUSES
            and (available is None or isinstance(available, bool))
            and record_model == slot["model"]
            and isinstance(record_configured, bool)
            and record_configured is slot["configured"]
            and checked_at is not None
            and ttl is not None
            and age_seconds is not None
            and 0 <= age_seconds < ttl
        )
        result.append({
            **slot,
            "available": available if record_valid else None,
            "status": status if record_valid else "unknown",
            "checked_at": checked_at.isoformat() if checked_at is not None else freshness.get("checked_at"),
            "ttl_seconds": ttl if ttl is not None else freshness.get("ttl_seconds"),
        })
    return sorted(result, key=lambda item: (item["provider"], item["operation"]))


def _breaker_rows(store: RoutingStore, policies: Mapping[str, list[str]]) -> list[dict[str, Any]]:
    keys: set[tuple[str, str, str]] = set()
    for operation in Operation:
        policy = policy_for(operation)
        tier = "decisive" if operation is Operation.DECISIVE_TEXT else "fast"
        for provider in policies[operation.value]:
            keys.add((provider, policy.modality, tier))
    with store.transaction() as connection:
        saved = {
            (str(row["provider"]), str(row["modality"]), str(row["model_tier"])): dict(row)
            for row in connection.execute(
                """SELECT provider, modality, model_tier, state, failure_count,
                          last_error_class, updated_at
                   FROM circuit_breakers"""
            ).fetchall()
        }
    result = []
    for key in sorted(keys):
        row = saved.get(key)
        state = str(row.get("state")) if row else "closed"
        if state not in {"closed", "open", "half_open"}:
            state = "unknown"
        error = row.get("last_error_class") if row else None
        result.append({
            "provider": key[0], "modality": key[1], "model_tier": key[2],
            "state": state,
            "failure_count": int(row.get("failure_count") or 0) if row else 0,
            "last_error_class": error if error in _ERROR_CLASSES else None,
        })
    return result


def _daily_budget(store: RoutingStore, now: datetime) -> dict[str, Any]:
    raw_cap = os.getenv("AI_OPENAI_DAILY_BUDGET_USD")
    base = {
        "scope": "utc_calendar_day",
        "day_utc": now.date().isoformat(),
        "pool": "automatic",
        "provider": "openai",
    }
    if raw_cap is None or not raw_cap.strip():
        return {
            **base, "daily_cap_usd_configured": False, "daily_cap_usd": None,
            "used_usd": None, "remaining_usd": None, "usage_percent": None,
            "status": "unavailable",
        }
    cap = _decimal(raw_cap.strip())
    if cap is None or cap <= 0:
        return {
            **base, "daily_cap_usd_configured": True, "daily_cap_usd": None,
            "used_usd": None, "remaining_usd": None, "usage_percent": None,
            "status": "invalid_configuration",
        }
    with store.transaction() as connection:
        rows = connection.execute(
            """SELECT reserved_cost_usd, actual_cost_usd, status
               FROM budget_reservations
               WHERE provider='openai' AND billing_day_utc=? AND status <> 'released'""",
            (now.date().isoformat(),),
        ).fetchall()
    used = Decimal("0")
    complete = True
    for row in rows:
        raw = (
            row["actual_cost_usd"]
            if row["status"] in {"settled", "breached"} and row["actual_cost_usd"] is not None
            else row["reserved_cost_usd"]
        )
        cost = _decimal(raw)
        if cost is None:
            complete = False
        else:
            used += cost
    if not complete:
        return {
            **base, "daily_cap_usd_configured": True, "daily_cap_usd": _decimal_text(cap),
            "used_usd": None, "remaining_usd": None, "usage_percent": None,
            "status": "incomplete",
        }
    remaining = max(Decimal("0"), cap - used)
    return {
        **base,
        "daily_cap_usd_configured": True,
        "daily_cap_usd": _decimal_text(cap),
        "used_usd": _decimal_text(used),
        "remaining_usd": _decimal_text(remaining),
        "usage_percent": round(float((used / cap) * 100), 3),
        "status": "configured",
    }


def get_llm_routing_status(
    *,
    store: RoutingStore | None = None,
    health_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return configuration plus persisted health/breaker/budget state, without probes."""
    current = _utc_now(now)
    ledger = store or default_store()
    snapshot, freshness = _load_health_snapshot(
        Path(health_path) if health_path is not None else HEALTH_SNAPSHOT_PATH,
        current,
    )
    telemetry = snapshot.get("telemetry") if snapshot is not None else None
    activation = (
        snapshot.get("cost_saving_activation") if snapshot is not None else None
    )
    attestation_accounted = (
        _provider_is_configured("DEEPSEEK_API_KEY")
        and isinstance(telemetry, Mapping)
        and telemetry.get("complete") is True
        and telemetry.get("status") == "complete"
        and isinstance(activation, Mapping)
        and activation.get("ready") is True
        and activation.get("status") == "ready"
    )
    attestation = (
        snapshot.get("vision_attestation")
        if snapshot is not None
        and freshness["status"] == "fresh"
        and attestation_accounted
        else None
    )
    policies = {
        operation.value: list(
            policy_for(operation, vision_attestation=attestation, now=current).providers
        )
        for operation in Operation
    }
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "service": "ai-routing",
        "checked_at": current.isoformat(),
        "freshness": freshness,
        "provider_order": policies,
        "providers": _providers_from_health(snapshot, freshness, now=current),
        "breakers": _breaker_rows(ledger, policies),
        "budget": _daily_budget(ledger, current),
        "hold_review": {
            "available": False,
            "count": None,
            "rate": None,
            "reason": "final_outcome_not_recorded",
        },
    }


__all__ = [
    "HEALTH_SCHEMA_VERSION",
    "HEALTH_SNAPSHOT_PATH",
    "get_llm_routing_status",
    "get_llm_usage_report",
]
