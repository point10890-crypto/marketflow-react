"""Pure, deterministic risk checks for AlphaCore shadow/paper intents.

This module has no LLM, network, broker, credential, or filesystem dependency.
It accepts immutable snapshots and returns a hash-bound decision.  Missing,
stale, future-dated, or inconsistent inputs fail closed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from .config import resolve_mode
from .contracts import (
    ContractValidationError,
    PaperOrderIntent,
    RiskDecision,
    canonical_hash,
    normalize_timestamp,
    parse_timestamp,
    validate_hash,
)


def _require_int(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{name} must be an integer")
    if positive and value <= 0:
        raise ContractValidationError(f"{name} must be positive")
    if not positive and value < 0:
        raise ContractValidationError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True)
class RiskPolicy:
    policy_version: str
    cost_schedule_version: str
    max_order_notional_krw: int
    max_single_position_bps: int
    max_gross_exposure_bps: int
    max_sector_exposure_bps: int
    min_cash_buffer_bps: int
    max_adv_participation_bps: int
    max_positions: int
    max_data_age_seconds: int
    max_daily_loss_bps: int
    max_drawdown_bps: int
    max_daily_turnover_bps: int
    reservation_buffer_bps: int
    allowed_strategy_versions: tuple[str, ...]
    allowed_model_versions: tuple[str, ...]
    allowed_hypothesis_ids: tuple[str, ...]
    allowed_order_styles: tuple[str, ...] = ("next_open", "paper_vwap", "paper_limit")
    decision_ttl_seconds: int = 30

    def __post_init__(self) -> None:
        if not str(self.policy_version or "").strip():
            raise ContractValidationError("policy_version is required")
        if not str(self.cost_schedule_version or "").strip():
            raise ContractValidationError("cost_schedule_version is required")
        for field_name in (
            "max_order_notional_krw", "max_single_position_bps",
            "max_gross_exposure_bps", "max_sector_exposure_bps",
            "min_cash_buffer_bps", "max_adv_participation_bps", "max_positions",
            "max_data_age_seconds", "max_daily_loss_bps", "max_drawdown_bps",
            "max_daily_turnover_bps", "decision_ttl_seconds",
        ):
            _require_int(getattr(self, field_name), field_name, positive=True)
        _require_int(self.reservation_buffer_bps, "reservation_buffer_bps")
        for field_name in (
            "max_single_position_bps", "max_gross_exposure_bps",
            "max_sector_exposure_bps", "min_cash_buffer_bps",
            "max_adv_participation_bps", "max_daily_turnover_bps",
        ):
            if getattr(self, field_name) > 10_000:
                raise ContractValidationError(f"{field_name} cannot exceed 10000 bps")
        for field_name in (
            "allowed_strategy_versions", "allowed_model_versions",
            "allowed_hypothesis_ids", "allowed_order_styles",
        ):
            values = tuple(sorted({str(item).strip() for item in getattr(self, field_name) if str(item).strip()}))
            if not values:
                raise ContractValidationError(f"{field_name} must be an explicit non-empty allowlist")
            object.__setattr__(self, field_name, values)

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class PortfolioSnapshot:
    ledger_projection_hash: str
    cash_krw: int | None
    reserved_cash_krw: int
    positions: tuple[Mapping[str, Any], ...]
    gross_exposure_krw: int
    net_exposure_krw: int
    nav_krw: int | None
    as_of: str | None
    daily_loss_bps: int
    drawdown_bps: int
    daily_turnover_krw: int
    sector_exposure_krw: Mapping[str, int]
    ledger_consistent: bool
    kill_state: str = "NORMAL"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ledger_projection_hash",
            validate_hash(self.ledger_projection_hash, field_name="ledger_projection_hash"),
        )
        if self.cash_krw is not None:
            _require_int(self.cash_krw, "cash_krw")
        for field_name in (
            "reserved_cash_krw", "gross_exposure_krw", "daily_turnover_krw",
        ):
            _require_int(getattr(self, field_name), field_name)
        if isinstance(self.net_exposure_krw, bool) or not isinstance(self.net_exposure_krw, int):
            raise ContractValidationError("net_exposure_krw must be an integer")
        if self.nav_krw is not None:
            _require_int(self.nav_krw, "nav_krw", positive=True)
        for field_name in ("daily_loss_bps", "drawdown_bps"):
            if isinstance(getattr(self, field_name), bool) or not isinstance(getattr(self, field_name), int):
                raise ContractValidationError(f"{field_name} must be an integer")
        object.__setattr__(self, "positions", tuple(dict(item) for item in self.positions))
        object.__setattr__(
            self,
            "sector_exposure_krw",
            {str(key): int(value) for key, value in self.sector_exposure_krw.items()},
        )
        if self.as_of is not None:
            object.__setattr__(self, "as_of", normalize_timestamp(self.as_of))
        state = str(self.kill_state or "").upper()
        if state not in {"NORMAL", "BLOCK_NEW", "CANCEL_PENDING", "REDUCE_ONLY", "MANUAL_HALT"}:
            raise ContractValidationError("unknown kill_state")
        object.__setattr__(self, "kill_state", state)

    @classmethod
    def from_projection(
        cls,
        projection: Mapping[str, Any],
        *,
        daily_loss_bps: int = 0,
        drawdown_bps: int = 0,
        daily_turnover_krw: int = 0,
        sector_exposure_krw: Mapping[str, int] | None = None,
        ledger_consistent: bool = True,
        kill_state: str = "NORMAL",
    ) -> "PortfolioSnapshot":
        material = {key: value for key, value in projection.items() if key != "snapshot_hash"}
        expected = canonical_hash(material)
        supplied = str(projection.get("snapshot_hash") or "")
        if supplied != expected:
            raise ContractValidationError("ledger projection snapshot_hash mismatch")
        return cls(
            ledger_projection_hash=supplied,
            cash_krw=projection.get("cash_krw"),
            reserved_cash_krw=int(projection.get("reserved_cash_krw") or 0),
            positions=tuple(projection.get("positions") or ()),
            gross_exposure_krw=int(projection.get("gross_exposure_krw") or 0),
            net_exposure_krw=int(projection.get("net_exposure_krw") or 0),
            nav_krw=projection.get("nav_krw"),
            as_of=projection.get("as_of"),
            daily_loss_bps=daily_loss_bps,
            drawdown_bps=drawdown_bps,
            daily_turnover_krw=daily_turnover_krw,
            sector_exposure_krw=sector_exposure_krw or {},
            ledger_consistent=ledger_consistent,
            kill_state=kill_state,
        )

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(self)

    def position(self, symbol_id: str) -> Mapping[str, Any] | None:
        return next(
            (item for item in self.positions if str(item.get("symbol_id")) == symbol_id),
            None,
        )


@dataclass(frozen=True)
class MarketSnapshot:
    decision_snapshot_hash: str
    market_data_manifest_hash: str
    symbol_id: str
    reference_price_krw: int
    adv_value_krw: int
    available_at: str
    quality_status: str
    sector_id: str
    is_halted: bool = False
    is_market_open: bool | None = None

    def __post_init__(self) -> None:
        for field_name in ("decision_snapshot_hash", "market_data_manifest_hash"):
            object.__setattr__(self, field_name, validate_hash(getattr(self, field_name), field_name=field_name))
        if not str(self.symbol_id or "").strip():
            raise ContractValidationError("symbol_id is required")
        object.__setattr__(self, "symbol_id", str(self.symbol_id).strip())
        _require_int(self.reference_price_krw, "reference_price_krw", positive=True)
        _require_int(self.adv_value_krw, "adv_value_krw", positive=True)
        object.__setattr__(self, "available_at", normalize_timestamp(self.available_at))
        quality = str(self.quality_status or "").strip().upper()
        if quality not in {"PASS", "DEGRADED", "HALT"}:
            raise ContractValidationError("quality_status must be PASS, DEGRADED, or HALT")
        object.__setattr__(self, "quality_status", quality)
        object.__setattr__(self, "sector_id", str(self.sector_id or "UNKNOWN").strip() or "UNKNOWN")

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(self)


class RiskKernel:
    """Deterministic, fail-closed evaluator."""

    def __init__(self, policy: RiskPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        intent: PaperOrderIntent,
        portfolio: PortfolioSnapshot,
        market: MarketSnapshot,
        *,
        evaluated_at: str | datetime,
        nonce: str,
        mode: str | None = None,
    ) -> RiskDecision:
        runtime_mode = resolve_mode(mode)
        now_text = normalize_timestamp(evaluated_at)
        now = parse_timestamp(now_text)
        violations: list[str] = []

        if intent.environment != "paper" or not intent.verify_hash():
            violations.append("INTENT_INTEGRITY_FAILED")
        if now >= parse_timestamp(intent.expires_at):
            violations.append("INTENT_EXPIRED")
        if market.decision_snapshot_hash != intent.decision_snapshot_hash:
            violations.append("DECISION_SNAPSHOT_MISMATCH")
        if market.symbol_id != intent.symbol_id:
            violations.append("MARKET_SYMBOL_MISMATCH")
        if market.quality_status != "PASS":
            violations.append("DATA_QUALITY_NOT_PASS")
        available_at = parse_timestamp(market.available_at)
        if available_at > now:
            violations.append("PIT_FUTURE_DATA")
        elif (now - available_at).total_seconds() > self.policy.max_data_age_seconds:
            violations.append("DATA_STALE")
        if portfolio.as_of is None:
            violations.append("PORTFOLIO_ASOF_MISSING")
        else:
            portfolio_at = parse_timestamp(portfolio.as_of)
            if portfolio_at > now:
                violations.append("PORTFOLIO_FUTURE_DATA")
            elif (now - portfolio_at).total_seconds() > self.policy.max_data_age_seconds:
                violations.append("PORTFOLIO_STALE")
        if not portfolio.ledger_consistent:
            violations.append("LEDGER_INCONSISTENT")
        if market.is_halted:
            violations.append("SYMBOL_HALTED")

        if intent.strategy_version not in self.policy.allowed_strategy_versions:
            violations.append("STRATEGY_VERSION_NOT_ALLOWED")
        if intent.model_version not in self.policy.allowed_model_versions:
            violations.append("MODEL_VERSION_NOT_ALLOWED")
        if intent.risk_policy_version != self.policy.policy_version:
            violations.append("RISK_POLICY_VERSION_MISMATCH")
        if intent.cost_schedule_version != self.policy.cost_schedule_version:
            violations.append("COST_SCHEDULE_VERSION_MISMATCH")
        if intent.hypothesis_id not in self.policy.allowed_hypothesis_ids:
            violations.append("HYPOTHESIS_NOT_ALLOWED")
        if intent.order_style not in self.policy.allowed_order_styles:
            violations.append("ORDER_STYLE_NOT_ALLOWED")

        current_position = portfolio.position(intent.symbol_id)
        current_qty = int((current_position or {}).get("quantity") or 0)
        current_value = int((current_position or {}).get("book_value_krw") or 0)
        is_reduction = intent.side == "sell" and 0 < intent.quantity <= current_qty
        if portfolio.kill_state == "REDUCE_ONLY":
            if not is_reduction:
                violations.append("KILL_STATE_REDUCE_ONLY")
        elif portfolio.kill_state != "NORMAL":
            violations.append(f"KILL_STATE_{portfolio.kill_state}")

        price = market.reference_price_krw
        notional = intent.quantity * price
        if notional > self.policy.max_order_notional_krw:
            violations.append("ORDER_NOTIONAL_LIMIT")
        participation_bps = math.ceil(notional * 10_000 / market.adv_value_krw)
        if participation_bps > self.policy.max_adv_participation_bps:
            violations.append("ADV_PARTICIPATION_LIMIT")

        guard_key = "max_price_krw" if intent.side == "buy" else "min_price_krw"
        guard_raw = intent.price_guard.get(guard_key)
        if isinstance(guard_raw, bool) or not isinstance(guard_raw, int) or guard_raw <= 0:
            violations.append("PRICE_GUARD_MISSING")
        elif intent.side == "buy" and price > guard_raw:
            violations.append("BUY_PRICE_GUARD_BREACH")
        elif intent.side == "sell" and price < guard_raw:
            violations.append("SELL_PRICE_GUARD_BREACH")

        if portfolio.cash_krw is None or portfolio.nav_krw is None or portfolio.nav_krw <= 0:
            violations.append("CAPITAL_NOT_INITIALIZED")
            nav = 0
        else:
            nav = portfolio.nav_krw

        if intent.side == "buy":
            required_reservation = math.ceil(
                notional * (10_000 + self.policy.reservation_buffer_bps) / 10_000
            )
            if intent.notional_reservation_krw < required_reservation:
                violations.append("RESERVATION_UNDERFUNDED")
            if portfolio.cash_krw is not None and nav > 0:
                cash_after = (
                    portfolio.cash_krw
                    - portfolio.reserved_cash_krw
                    - intent.notional_reservation_krw
                )
                minimum_cash = math.ceil(nav * self.policy.min_cash_buffer_bps / 10_000)
                if cash_after < minimum_cash:
                    violations.append("CASH_BUFFER_LIMIT")
                projected_position = current_value + notional
                projected_gross = portfolio.gross_exposure_krw + notional
                if projected_position * 10_000 > nav * self.policy.max_single_position_bps:
                    violations.append("SINGLE_POSITION_LIMIT")
                if projected_gross * 10_000 > nav * self.policy.max_gross_exposure_bps:
                    violations.append("GROSS_EXPOSURE_LIMIT")
                if current_qty <= 0 and len(portfolio.positions) >= self.policy.max_positions:
                    violations.append("POSITION_COUNT_LIMIT")
                sector_value = int(portfolio.sector_exposure_krw.get(market.sector_id, 0)) + notional
                if sector_value * 10_000 > nav * self.policy.max_sector_exposure_bps:
                    violations.append("SECTOR_EXPOSURE_LIMIT")
        elif not is_reduction:
            violations.append("SELL_QUANTITY_EXCEEDS_POSITION")

        if portfolio.daily_loss_bps <= -self.policy.max_daily_loss_bps:
            violations.append("DAILY_LOSS_LIMIT")
        if portfolio.drawdown_bps >= self.policy.max_drawdown_bps:
            violations.append("DRAWDOWN_LIMIT")
        if nav > 0:
            projected_turnover = portfolio.daily_turnover_krw + notional
            if projected_turnover * 10_000 > nav * self.policy.max_daily_turnover_bps:
                violations.append("DAILY_TURNOVER_LIMIT")

        decision_value = "rejected" if violations else "approved"
        reasons = tuple(sorted(set(violations))) if violations else ("ALL_CHECKS_PASSED",)
        expiry_candidate = now + timedelta(seconds=self.policy.decision_ttl_seconds)
        if decision_value == "approved":
            expires = min(expiry_candidate, parse_timestamp(intent.expires_at))
        else:
            expires = expiry_candidate
        seed = {
            "intent_hash": intent.intent_hash,
            "portfolio_snapshot_hash": portfolio.snapshot_hash,
            "market_snapshot_hash": market.snapshot_hash,
            "policy_hash": self.policy.policy_hash,
            "evaluated_at": now_text,
            "nonce": str(nonce),
            "mode": runtime_mode,
            "decision": decision_value,
            "reason_codes": list(reasons),
        }
        seed_hash = canonical_hash(seed).split(":", 1)[1]
        reservation_id = f"pres_{seed_hash[:24]}" if decision_value == "approved" else None
        return RiskDecision(
            risk_decision_id=f"prd_{seed_hash[:24]}",
            intent_id=intent.intent_id,
            intent_hash=intent.intent_hash,
            decision=decision_value,
            reason_codes=reasons,
            portfolio_snapshot_hash=portfolio.snapshot_hash,
            ledger_projection_hash=portfolio.ledger_projection_hash,
            market_snapshot_hash=market.snapshot_hash,
            risk_policy_version=self.policy.policy_version,
            risk_policy_hash=self.policy.policy_hash,
            reservation_id=reservation_id,
            evaluated_at=now_text,
            expires_at=normalize_timestamp(expires),
            nonce=str(nonce),
            evaluation_mode=runtime_mode,
        )
