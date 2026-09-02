"""Versioned provider pricing with time-aware DeepSeek billing tiers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

from .contracts import TokenUsage


PRICING_VERSION = "official-2026-09-02"
_DEEPSEEK_VERSION = "deepseek-official-2026-09-02"


@dataclass(frozen=True)
class PricingRate:
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None = None
    version: str = PRICING_VERSION


@dataclass(frozen=True)
class CostEstimate:
    cost: Decimal | None
    pricing_version: str | None


PROVIDER_MODEL_RATES: Mapping[tuple[str, str], PricingRate] = {
    ("deepseek", "deepseek-v4-flash"): PricingRate(
        Decimal("0.44"), Decimal("1.32"), Decimal("0.014"), _DEEPSEEK_VERSION
    ),
    ("deepseek", "deepseek-v4-pro"): PricingRate(
        Decimal("1.32"), Decimal("3.96"), Decimal("0.044"), _DEEPSEEK_VERSION
    ),
    ("deepseek", "deepseek-v4-flash-vision-exp"): PricingRate(
        Decimal("0.44"), Decimal("1.32"), Decimal("0.014"), _DEEPSEEK_VERSION
    ),
    ("openai", "gpt-5.5"): PricingRate(
        Decimal("5"), Decimal("30"), Decimal("0.50"), PRICING_VERSION
    ),
    ("gemini", "gemini-2.5-flash"): PricingRate(
        Decimal("0.30"), Decimal("2.50"), Decimal("0.03"), PRICING_VERSION
    ),
}


def _env_key_part(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _decimal_env(*names: str) -> Decimal | None:
    for name in names:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            continue
        try:
            value = Decimal(raw.strip())
        except Exception as exc:
            raise ValueError(f"invalid pricing override: {name}") from exc
        if value < 0:
            raise ValueError(f"pricing override cannot be negative: {name}")
        return value
    return None


def _text_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _parse_utc(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deepseek_tier(at: datetime) -> str:
    peak_window = at.weekday() < 5 and (1 <= at.hour < 4 or 6 <= at.hour < 10)
    return "peak" if peak_window else "off_peak"


def _operator_rate(provider: str, model: str) -> PricingRate | None:
    provider_key = _env_key_part(provider)
    model_key = _env_key_part(model)
    prefix = f"AI_ROUTING_PRICE_{provider_key}_{model_key}"
    provider_prefix = f"AI_ROUTING_PRICE_{provider_key}"
    legacy_prefix = f"AI_{provider_key}"
    input_rate = _decimal_env(
        f"{prefix}_INPUT_PER_MILLION",
        f"{provider_prefix}_INPUT_PER_MILLION",
        f"{legacy_prefix}_INPUT_USD_PER_MILLION",
    )
    output_rate = _decimal_env(
        f"{prefix}_OUTPUT_PER_MILLION",
        f"{provider_prefix}_OUTPUT_PER_MILLION",
        f"{legacy_prefix}_OUTPUT_USD_PER_MILLION",
    )
    cached_rate = _decimal_env(
        f"{prefix}_CACHED_INPUT_PER_MILLION",
        f"{provider_prefix}_CACHED_INPUT_PER_MILLION",
        f"{legacy_prefix}_CACHED_INPUT_USD_PER_MILLION",
    )
    if input_rate is None or output_rate is None:
        return None
    version = _text_env(
        f"{prefix}_VERSION",
        f"{provider_prefix}_VERSION",
        "AI_ROUTING_PRICE_VERSION",
    ) or "operator-env-unversioned"
    return PricingRate(input_rate, output_rate, cached_rate, version)


def pricing_rate(
    provider: str,
    model: str,
    *,
    event_ts_utc: str | datetime | None = None,
) -> PricingRate | None:
    override = _operator_rate(provider, model)
    if override is not None:
        return override
    rate = PROVIDER_MODEL_RATES.get((provider.lower(), model.lower()))
    if rate is None or provider.lower() != "deepseek":
        return rate
    tier = _deepseek_tier(_parse_utc(event_ts_utc))
    if tier == "peak":
        return replace(rate, version=f"{rate.version}:peak")
    half = Decimal("0.5")
    return PricingRate(
        input_per_million=rate.input_per_million * half,
        output_per_million=rate.output_per_million * half,
        cached_input_per_million=(
            rate.cached_input_per_million * half
            if rate.cached_input_per_million is not None
            else None
        ),
        version=f"{rate.version}:off_peak",
    )


def estimate_cost_details(
    provider: str,
    model: str,
    usage: TokenUsage,
    *,
    rate: PricingRate | None = None,
    event_ts_utc: str | datetime | None = None,
) -> CostEstimate:
    if usage.mapping_status == "quarantined":
        selected = rate or pricing_rate(provider, model, event_ts_utc=event_ts_utc)
        return CostEstimate(None, selected.version if selected else None)
    if usage.input_tokens is None or usage.output_tokens is None:
        return CostEstimate(None, None)
    selected = rate or pricing_rate(provider, model, event_ts_utc=event_ts_utc)
    if selected is None:
        return CostEstimate(None, None)
    cached_tokens = usage.cached_input_tokens or 0
    uncached_tokens = usage.uncached_input_tokens or 0
    cached_price = selected.cached_input_per_million
    if cached_tokens and cached_price is None:
        uncached_tokens += cached_tokens
        cached_tokens = 0
    cost = (
        Decimal(uncached_tokens) * selected.input_per_million
        + Decimal(cached_tokens) * (cached_price or Decimal("0"))
        + Decimal(usage.output_tokens) * selected.output_per_million
    ) / Decimal(1_000_000)
    return CostEstimate(cost, selected.version)


def estimate_cost(
    provider: str,
    model: str,
    usage: TokenUsage,
    *,
    rate: PricingRate | None = None,
    event_ts_utc: str | datetime | None = None,
) -> Decimal | None:
    return estimate_cost_details(
        provider,
        model,
        usage,
        rate=rate,
        event_ts_utc=event_ts_utc,
    ).cost
