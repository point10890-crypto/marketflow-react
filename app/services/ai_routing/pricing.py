"""Versioned token price calculation with operator-controlled overrides."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from .contracts import TokenUsage


PRICING_VERSION = "official-2026-09-02"


@dataclass(frozen=True)
class PricingRate:
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None = None
    version: str = PRICING_VERSION


# Official per-million-token rates audited on 2026-09-02. Environment
# overrides take precedence so price changes do not require a deployment.
PROVIDER_MODEL_RATES: Mapping[tuple[str, str], PricingRate] = {
    ("deepseek", "deepseek-v4-flash"): PricingRate(
        Decimal("0.44"), Decimal("1.32"), Decimal("0.014")
    ),
    ("deepseek", "deepseek-v4-pro"): PricingRate(
        Decimal("1.32"), Decimal("3.96"), Decimal("0.044")
    ),
    ("deepseek", "deepseek-v4-flash-vision-exp"): PricingRate(
        Decimal("0.44"), Decimal("1.32"), Decimal("0.014")
    ),
    ("openai", "gpt-5.5"): PricingRate(
        Decimal("5"), Decimal("30"), Decimal("0.50")
    ),
    ("gemini", "gemini-2.5-flash"): PricingRate(
        Decimal("0.30"), Decimal("2.50"), Decimal("0.03")
    ),
}


def _env_key_part(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _decimal_env(*names: str) -> Decimal | None:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and raw.strip():
            try:
                value = Decimal(raw.strip())
            except Exception as exc:
                raise ValueError(f"invalid pricing override: {name}") from exc
            if value < 0:
                raise ValueError(f"pricing override cannot be negative: {name}")
            return value
    return None


def pricing_rate(provider: str, model: str) -> PricingRate | None:
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
    if input_rate is not None and output_rate is not None:
        return PricingRate(input_rate, output_rate, cached_rate)
    return PROVIDER_MODEL_RATES.get((provider.lower(), model.lower()))


def estimate_cost(
    provider: str,
    model: str,
    usage: TokenUsage,
    *,
    rate: PricingRate | None = None,
) -> Decimal | None:
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    selected_rate = rate or pricing_rate(provider, model)
    if selected_rate is None:
        return None
    cached_tokens = usage.cached_input_tokens or 0
    uncached_tokens = usage.uncached_input_tokens or 0
    cached_price = selected_rate.cached_input_per_million
    if cached_tokens and cached_price is None:
        uncached_tokens += cached_tokens
        cached_tokens = 0
    cost = (
        Decimal(uncached_tokens) * selected_rate.input_per_million
        + Decimal(cached_tokens) * (cached_price or Decimal("0"))
        + Decimal(usage.output_tokens) * selected_rate.output_per_million
    ) / Decimal(1_000_000)
    return cost
