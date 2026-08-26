"""Deterministic and deliberately conservative internal paper fills."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from .config import resolve_mode
from .contracts import (
    ContractValidationError,
    PaperFill,
    PaperOrderIntent,
    canonical_hash,
    normalize_timestamp,
    parse_timestamp,
    validate_hash,
)


@dataclass(frozen=True)
class CostSchedule:
    version: str
    effective_from: str
    market: str
    buy_fee_bps: int
    sell_fee_bps: int
    buy_tax_bps: int
    sell_tax_bps: int
    source: str

    def __post_init__(self) -> None:
        if not all(str(getattr(self, name) or "").strip() for name in ("version", "market", "source")):
            raise ContractValidationError("cost schedule version, market, and source are required")
        try:
            date.fromisoformat(self.effective_from)
        except ValueError as exc:
            raise ContractValidationError("effective_from must be YYYY-MM-DD") from exc
        for name in ("buy_fee_bps", "sell_fee_bps", "buy_tax_bps", "sell_tax_bps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class FillModel:
    version: str
    adverse_slippage_bps: int
    max_bar_participation_bps: int

    def __post_init__(self) -> None:
        if not str(self.version or "").strip():
            raise ContractValidationError("fill model version is required")
        if (
            isinstance(self.adverse_slippage_bps, bool)
            or not isinstance(self.adverse_slippage_bps, int)
            or self.adverse_slippage_bps < 0
        ):
            raise ContractValidationError("adverse_slippage_bps must be non-negative")
        if (
            isinstance(self.max_bar_participation_bps, bool)
            or not isinstance(self.max_bar_participation_bps, int)
            or not 0 < self.max_bar_participation_bps <= 10_000
        ):
            raise ContractValidationError("max_bar_participation_bps must be in 1..10000")


@dataclass(frozen=True)
class MarketBar:
    symbol_id: str
    session_date: str
    available_at: str
    open_krw: int
    high_krw: int
    low_krw: int
    close_krw: int
    volume: int
    market_data_manifest_hash: str
    quality_status: str = "PASS"
    vwap_krw: int | None = None

    def __post_init__(self) -> None:
        if not str(self.symbol_id or "").strip():
            raise ContractValidationError("bar symbol_id is required")
        try:
            date.fromisoformat(self.session_date)
        except ValueError as exc:
            raise ContractValidationError("session_date must be YYYY-MM-DD") from exc
        object.__setattr__(self, "available_at", normalize_timestamp(self.available_at))
        object.__setattr__(
            self,
            "market_data_manifest_hash",
            validate_hash(self.market_data_manifest_hash, field_name="market_data_manifest_hash"),
        )
        for name in ("open_krw", "high_krw", "low_krw", "close_krw"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ContractValidationError(f"{name} must be a positive integer")
        if not self.low_krw <= min(self.open_krw, self.close_krw) <= max(self.open_krw, self.close_krw) <= self.high_krw:
            raise ContractValidationError("OHLC values are inconsistent")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0:
            raise ContractValidationError("volume must be a non-negative integer")
        if self.vwap_krw is not None and (
            isinstance(self.vwap_krw, bool) or not isinstance(self.vwap_krw, int) or self.vwap_krw <= 0
        ):
            raise ContractValidationError("vwap_krw must be a positive integer")
        quality = str(self.quality_status or "").upper()
        if quality not in {"PASS", "DEGRADED", "HALT"}:
            raise ContractValidationError("invalid bar quality_status")
        object.__setattr__(self, "quality_status", quality)

    @property
    def bar_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class SimulationResult:
    status: str
    reason_codes: tuple[str, ...]
    fill: PaperFill | None
    result_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "fill": self.fill.to_dict() if self.fill else None,
            "result_hash": self.result_hash,
        }


def simulate_fill(
    intent: PaperOrderIntent,
    bar: MarketBar,
    *,
    cost_schedule: CostSchedule,
    fill_model: FillModel,
    filled_at: str,
    mode: str | None = None,
) -> SimulationResult:
    """Create at most one deterministic fill and never call an external system."""

    runtime_mode = resolve_mode(mode)
    at = normalize_timestamp(filled_at)
    if runtime_mode != "paper":
        return _no_fill("BLOCKED", ("SHADOW_MODE_NO_FILL",), intent, bar, at, fill_model)
    if intent.environment != "paper" or not intent.verify_hash():
        return _no_fill("BLOCKED", ("INTENT_INTEGRITY_FAILED",), intent, bar, at, fill_model)
    if intent.symbol_id != bar.symbol_id:
        return _no_fill("NOT_COMPARABLE", ("SYMBOL_MISMATCH",), intent, bar, at, fill_model)
    if bar.quality_status != "PASS":
        return _no_fill("NOT_COMPARABLE", ("BAR_QUALITY_NOT_PASS",), intent, bar, at, fill_model)
    if parse_timestamp(bar.available_at) > parse_timestamp(at):
        return _no_fill("NOT_COMPARABLE", ("PIT_FUTURE_BAR",), intent, bar, at, fill_model)
    if parse_timestamp(at) >= parse_timestamp(intent.expires_at):
        return _no_fill("NO_FILL", ("INTENT_EXPIRED",), intent, bar, at, fill_model)
    if bar.session_date < cost_schedule.effective_from:
        return _no_fill("NOT_COMPARABLE", ("COST_SCHEDULE_NOT_EFFECTIVE",), intent, bar, at, fill_model)
    if cost_schedule.version != intent.cost_schedule_version:
        return _no_fill("BLOCKED", ("COST_SCHEDULE_VERSION_MISMATCH",), intent, bar, at, fill_model)
    if fill_model.version != intent.fill_model_version:
        return _no_fill("BLOCKED", ("FILL_MODEL_VERSION_MISMATCH",), intent, bar, at, fill_model)

    capacity = math.floor(bar.volume * fill_model.max_bar_participation_bps / 10_000)
    fill_quantity = min(intent.quantity, capacity)
    if fill_quantity <= 0:
        return _no_fill("NO_FILL", ("ZERO_LIQUIDITY_CAPACITY",), intent, bar, at, fill_model)

    base_price: int | None
    if intent.order_style == "next_open":
        base_price = bar.open_krw
    elif intent.order_style == "paper_vwap":
        if bar.vwap_krw is None:
            return _no_fill("NOT_COMPARABLE", ("VWAP_MISSING",), intent, bar, at, fill_model)
        base_price = bar.vwap_krw
    else:
        limit_value = intent.price_guard.get("limit_price_krw")
        if isinstance(limit_value, bool) or not isinstance(limit_value, int) or limit_value <= 0:
            return _no_fill("NOT_COMPARABLE", ("LIMIT_PRICE_MISSING",), intent, bar, at, fill_model)
        touched = bar.low_krw <= limit_value if intent.side == "buy" else bar.high_krw >= limit_value
        if not touched:
            return _no_fill("NO_FILL", ("LIMIT_NOT_TOUCHED",), intent, bar, at, fill_model)
        # When only OHLC is known, claiming improvement inside the bar would be
        # optimistic.  Use the limit itself as the conservative reference.
        base_price = limit_value

    if intent.side == "buy":
        fill_price = math.ceil(base_price * (10_000 + fill_model.adverse_slippage_bps) / 10_000)
        if intent.order_style == "paper_limit":
            fill_price = min(fill_price, int(intent.price_guard["limit_price_krw"]))
        max_price = intent.price_guard.get("max_price_krw")
        if not isinstance(max_price, int) or isinstance(max_price, bool) or fill_price > max_price:
            return _no_fill("NO_FILL", ("BUY_PRICE_GUARD_BREACH",), intent, bar, at, fill_model)
        fee_bps = cost_schedule.buy_fee_bps
        tax_bps = cost_schedule.buy_tax_bps
    else:
        fill_price = math.floor(base_price * (10_000 - fill_model.adverse_slippage_bps) / 10_000)
        if intent.order_style == "paper_limit":
            fill_price = max(fill_price, int(intent.price_guard["limit_price_krw"]))
        min_price = intent.price_guard.get("min_price_krw")
        if not isinstance(min_price, int) or isinstance(min_price, bool) or fill_price < min_price:
            return _no_fill("NO_FILL", ("SELL_PRICE_GUARD_BREACH",), intent, bar, at, fill_model)
        fee_bps = cost_schedule.sell_fee_bps
        tax_bps = cost_schedule.sell_tax_bps

    gross_value = fill_price * fill_quantity
    fee = math.ceil(gross_value * fee_bps / 10_000)
    tax = math.ceil(gross_value * tax_bps / 10_000)
    slippage = abs(fill_price - base_price) * fill_quantity
    net_cash_delta = -(gross_value + fee + tax) if intent.side == "buy" else gross_value - fee - tax
    seed = {
        "intent_hash": intent.intent_hash,
        "bar_hash": bar.bar_hash,
        "fill_model_version": fill_model.version,
        "cost_schedule_version": cost_schedule.version,
        "filled_at": at,
        "quantity": fill_quantity,
        "gross_price_krw": fill_price,
    }
    seed_hash = canonical_hash(seed).split(":", 1)[1]
    quality = "complete" if fill_quantity == intent.quantity else "partial"
    fill = PaperFill(
        fill_id=f"pfill_{seed_hash[:24]}",
        intent_id=intent.intent_id,
        intent_hash=intent.intent_hash,
        side=intent.side,
        fill_model_version=fill_model.version,
        cost_schedule_version=cost_schedule.version,
        market_data_manifest_hash=bar.market_data_manifest_hash,
        filled_at=at,
        quantity=fill_quantity,
        gross_price_krw=fill_price,
        slippage_krw=slippage,
        fee_krw=fee,
        tax_krw=tax,
        net_cash_delta_krw=net_cash_delta,
        quality_status=quality,
    )
    status = "FILLED" if quality == "complete" else "PARTIAL"
    result_material = {"status": status, "reason_codes": [], "fill": fill.to_dict()}
    return SimulationResult(status, (), fill, canonical_hash(result_material))


def _no_fill(
    status: str,
    reasons: tuple[str, ...],
    intent: PaperOrderIntent,
    bar: MarketBar,
    at: str,
    model: FillModel,
) -> SimulationResult:
    material = {
        "status": status,
        "reason_codes": list(reasons),
        "intent_hash": intent.intent_hash,
        "bar_hash": bar.bar_hash,
        "filled_at": at,
        "fill_model_version": model.version,
    }
    return SimulationResult(status, reasons, None, canonical_hash(material))
