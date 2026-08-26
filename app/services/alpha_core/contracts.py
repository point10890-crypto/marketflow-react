"""Typed AlphaCore contracts and deterministic canonical hashing.

Financial amounts are represented as integer KRW and rates as integer basis
points.  This avoids binary floating point ambiguity in permission hashes.
Timestamps must be timezone-aware and are normalized to UTC before hashing.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


HASH_PREFIX = "sha256:"
INTENT_SIDES = frozenset({"buy", "sell"})
ORDER_STYLES = frozenset({"next_open", "paper_vwap", "paper_limit"})
FILL_QUALITY = frozenset({"complete", "partial", "not_comparable"})


class ContractValidationError(ValueError):
    """Raised when an object cannot cross an AlphaCore trust boundary."""


def normalize_timestamp(value: str | datetime) -> str:
    """Normalize a timezone-aware timestamp to an ISO-8601 UTC string."""

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ContractValidationError("timestamp is required")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ContractValidationError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError("timestamp must include a timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse via :func:`normalize_timestamp` and return an aware datetime."""

    return datetime.fromisoformat(normalize_timestamp(value).replace("Z", "+00:00"))


def canonical_json(value: Any) -> str:
    """Serialize supported values deterministically for audit hashes.

    ``Decimal`` values are encoded as normalized decimal strings.  Core
    contracts use integer KRW/bps, but this rule makes external manifest hashes
    deterministic without ever converting a decimal through binary float.
    """

    normalized = _canonical_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return f"{HASH_PREFIX}{hashlib.sha256(payload).hexdigest()}"


def validate_hash(value: str, *, field_name: str = "hash") -> str:
    text = str(value or "").strip().lower()
    digest = text[len(HASH_PREFIX):] if text.startswith(HASH_PREFIX) else ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ContractValidationError(f"{field_name} must be a sha256: hash")
    return text


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError("canonical object keys must be strings")
            result[key] = _canonical_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item) for item in value]
        return sorted(items, key=canonical_json)
    if isinstance(value, datetime):
        return normalize_timestamp(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ContractValidationError("non-finite Decimal is not canonical")
        normalized = value.normalize()
        if normalized == 0:
            return "0"
        return format(normalized, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("non-finite float is not canonical")
        if value == 0:
            return 0
        # Use the shortest round-trippable representation chosen by Python's
        # JSON encoder.  Permission-bearing core values themselves are ints.
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ContractValidationError(f"unsupported canonical type: {type(value).__name__}")


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(f"{name} is required")
    return text


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ContractValidationError(f"{name} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{name} must be a positive integer") from exc
    if number <= 0 or number != value:
        raise ContractValidationError(f"{name} must be a positive integer")
    return number


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ContractValidationError(f"{name} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{name} must be a non-negative integer") from exc
    if number < 0 or number != value:
        raise ContractValidationError(f"{name} must be a non-negative integer")
    return number


@dataclass(frozen=True)
class PaperOrderIntent:
    intent_id: str
    strategy_id: str
    strategy_version: str
    hypothesis_id: str
    signal_instance_id: str
    decision_snapshot_hash: str
    symbol_id: str
    side: str
    quantity: int
    order_style: str
    price_guard: Mapping[str, Any]
    time_in_force: str
    notional_reservation_krw: int
    created_at: str
    expires_at: str
    nonce: str
    model_version: str = "deterministic-v1"
    risk_policy_version: str = "risk-v1"
    cost_schedule_version: str = "cost-v1"
    fill_model_version: str = "fill-v1"
    environment: str = "paper"
    status: str = "PROPOSED"
    intent_hash: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "intent_id", "strategy_id", "strategy_version", "hypothesis_id",
            "signal_instance_id", "symbol_id", "time_in_force", "nonce",
            "model_version", "risk_policy_version", "cost_schedule_version",
            "fill_model_version",
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        if self.environment != "paper":
            raise ContractValidationError("PaperOrderIntent environment must be paper")
        side = str(self.side or "").strip().lower()
        if side not in INTENT_SIDES:
            raise ContractValidationError(f"unsupported side: {self.side!r}")
        object.__setattr__(self, "side", side)
        style = str(self.order_style or "").strip().lower()
        if style not in ORDER_STYLES:
            raise ContractValidationError(f"unsupported order_style: {self.order_style!r}")
        object.__setattr__(self, "order_style", style)
        object.__setattr__(self, "quantity", _positive_int(self.quantity, "quantity"))
        object.__setattr__(
            self,
            "notional_reservation_krw",
            _nonnegative_int(self.notional_reservation_krw, "notional_reservation_krw"),
        )
        if not isinstance(self.price_guard, Mapping):
            raise ContractValidationError("price_guard must be an object")
        object.__setattr__(self, "price_guard", dict(self.price_guard))
        object.__setattr__(
            self,
            "decision_snapshot_hash",
            validate_hash(self.decision_snapshot_hash, field_name="decision_snapshot_hash"),
        )
        created = normalize_timestamp(self.created_at)
        expires = normalize_timestamp(self.expires_at)
        if parse_timestamp(expires) <= parse_timestamp(created):
            raise ContractValidationError("expires_at must be after created_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        if str(self.status).upper() != "PROPOSED":
            raise ContractValidationError("new intent status must be PROPOSED")
        object.__setattr__(self, "status", "PROPOSED")
        computed = canonical_hash(self.hash_material())
        if self.intent_hash and validate_hash(self.intent_hash, field_name="intent_hash") != computed:
            raise ContractValidationError("intent_hash does not match intent material")
        object.__setattr__(self, "intent_hash", computed)

    def hash_material(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "environment": self.environment,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "hypothesis_id": self.hypothesis_id,
            "signal_instance_id": self.signal_instance_id,
            "decision_snapshot_hash": self.decision_snapshot_hash,
            "symbol_id": self.symbol_id,
            "side": self.side,
            "quantity": self.quantity,
            "order_style": self.order_style,
            "price_guard": dict(self.price_guard),
            "time_in_force": self.time_in_force,
            "notional_reservation_krw": self.notional_reservation_krw,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "model_version": self.model_version,
            "risk_policy_version": self.risk_policy_version,
            "cost_schedule_version": self.cost_schedule_version,
            "fill_model_version": self.fill_model_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.hash_material(), "status": self.status, "intent_hash": self.intent_hash}

    def verify_hash(self) -> bool:
        return self.intent_hash == canonical_hash(self.hash_material())


@dataclass(frozen=True)
class RiskDecision:
    risk_decision_id: str
    intent_id: str
    intent_hash: str
    decision: str
    reason_codes: tuple[str, ...]
    portfolio_snapshot_hash: str
    ledger_projection_hash: str
    market_snapshot_hash: str
    risk_policy_version: str
    risk_policy_hash: str
    reservation_id: str | None
    evaluated_at: str
    expires_at: str
    nonce: str
    evaluation_mode: str = "shadow"
    decision_hash: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "risk_decision_id", "intent_id", "risk_policy_version", "nonce",
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        decision = str(self.decision or "").strip().lower()
        if decision not in {"approved", "rejected"}:
            raise ContractValidationError("decision must be approved or rejected")
        object.__setattr__(self, "decision", decision)
        reasons = tuple(sorted({_required_text(item, "reason_code") for item in self.reason_codes}))
        if not reasons:
            raise ContractValidationError("reason_codes must not be empty")
        object.__setattr__(self, "reason_codes", reasons)
        for field_name in (
            "intent_hash", "portfolio_snapshot_hash", "ledger_projection_hash",
            "market_snapshot_hash", "risk_policy_hash",
        ):
            object.__setattr__(self, field_name, validate_hash(getattr(self, field_name), field_name=field_name))
        if decision == "approved" and not str(self.reservation_id or "").strip():
            raise ContractValidationError("approved decision requires reservation_id")
        if decision == "rejected" and self.reservation_id is not None:
            raise ContractValidationError("rejected decision cannot reserve capital")
        evaluated = normalize_timestamp(self.evaluated_at)
        expires = normalize_timestamp(self.expires_at)
        if parse_timestamp(expires) <= parse_timestamp(evaluated):
            raise ContractValidationError("risk decision expires_at must be after evaluated_at")
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "expires_at", expires)
        mode = str(self.evaluation_mode or "").strip().lower()
        if mode not in {"shadow", "paper"}:
            raise ContractValidationError("evaluation_mode must be shadow or paper")
        object.__setattr__(self, "evaluation_mode", mode)
        computed = canonical_hash(self.hash_material())
        if self.decision_hash and validate_hash(self.decision_hash, field_name="decision_hash") != computed:
            raise ContractValidationError("decision_hash does not match decision material")
        object.__setattr__(self, "decision_hash", computed)

    def hash_material(self) -> dict[str, Any]:
        return {
            "risk_decision_id": self.risk_decision_id,
            "intent_id": self.intent_id,
            "intent_hash": self.intent_hash,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "portfolio_snapshot_hash": self.portfolio_snapshot_hash,
            "ledger_projection_hash": self.ledger_projection_hash,
            "market_snapshot_hash": self.market_snapshot_hash,
            "risk_policy_version": self.risk_policy_version,
            "risk_policy_hash": self.risk_policy_hash,
            "reservation_id": self.reservation_id,
            "evaluated_at": self.evaluated_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "evaluation_mode": self.evaluation_mode,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.hash_material(), "decision_hash": self.decision_hash}


@dataclass(frozen=True)
class PaperFill:
    fill_id: str
    intent_id: str
    intent_hash: str
    side: str
    fill_model_version: str
    cost_schedule_version: str
    market_data_manifest_hash: str
    filled_at: str
    quantity: int
    gross_price_krw: int
    slippage_krw: int
    fee_krw: int
    tax_krw: int
    net_cash_delta_krw: int
    quality_status: str
    fill_hash: str = ""

    def __post_init__(self) -> None:
        for field_name in ("fill_id", "intent_id", "fill_model_version", "cost_schedule_version"):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        side = str(self.side or "").strip().lower()
        if side not in INTENT_SIDES:
            raise ContractValidationError("fill side must be buy or sell")
        object.__setattr__(self, "side", side)
        for field_name in ("intent_hash", "market_data_manifest_hash"):
            object.__setattr__(self, field_name, validate_hash(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "filled_at", normalize_timestamp(self.filled_at))
        object.__setattr__(self, "quantity", _positive_int(self.quantity, "quantity"))
        object.__setattr__(self, "gross_price_krw", _positive_int(self.gross_price_krw, "gross_price_krw"))
        for field_name in ("slippage_krw", "fee_krw", "tax_krw"):
            object.__setattr__(self, field_name, _nonnegative_int(getattr(self, field_name), field_name))
        if isinstance(self.net_cash_delta_krw, bool) or not isinstance(self.net_cash_delta_krw, int):
            raise ContractValidationError("net_cash_delta_krw must be an integer")
        gross_value = self.gross_price_krw * self.quantity
        expected_cash_delta = (
            -(gross_value + self.fee_krw + self.tax_krw)
            if side == "buy"
            else gross_value - self.fee_krw - self.tax_krw
        )
        if self.net_cash_delta_krw != expected_cash_delta:
            raise ContractValidationError(
                "net_cash_delta_krw does not reconcile with side, gross value, fees, and tax"
            )
        quality = str(self.quality_status or "").strip().lower()
        if quality not in FILL_QUALITY:
            raise ContractValidationError(f"unsupported quality_status: {self.quality_status!r}")
        object.__setattr__(self, "quality_status", quality)
        computed = canonical_hash(self.hash_material())
        if self.fill_hash and validate_hash(self.fill_hash, field_name="fill_hash") != computed:
            raise ContractValidationError("fill_hash does not match fill material")
        object.__setattr__(self, "fill_hash", computed)

    def hash_material(self) -> dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "intent_id": self.intent_id,
            "intent_hash": self.intent_hash,
            "side": self.side,
            "fill_model_version": self.fill_model_version,
            "cost_schedule_version": self.cost_schedule_version,
            "market_data_manifest_hash": self.market_data_manifest_hash,
            "filled_at": self.filled_at,
            "quantity": self.quantity,
            "gross_price_krw": self.gross_price_krw,
            "slippage_krw": self.slippage_krw,
            "fee_krw": self.fee_krw,
            "tax_krw": self.tax_krw,
            "net_cash_delta_krw": self.net_cash_delta_krw,
            "quality_status": self.quality_status,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.hash_material(), "fill_hash": self.fill_hash}


@dataclass(frozen=True)
class ReconciliationResult:
    reconciliation_id: str
    status: str
    replay_projection_hash: str
    expected_projection_hash: str
    discrepancies: tuple[str, ...]
    reconciled_at: str
    intent_id: str | None = None
    reconciliation_hash: str = field(default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "reconciliation_id", _required_text(self.reconciliation_id, "reconciliation_id"))
        status = str(self.status or "").strip().upper()
        if status not in {"MATCHED", "MISMATCH", "HALTED"}:
            raise ContractValidationError("invalid reconciliation status")
        object.__setattr__(self, "status", status)
        for field_name in ("replay_projection_hash", "expected_projection_hash"):
            object.__setattr__(self, field_name, validate_hash(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "discrepancies", tuple(str(item) for item in self.discrepancies))
        object.__setattr__(self, "reconciled_at", normalize_timestamp(self.reconciled_at))
        computed = canonical_hash(self.hash_material())
        if self.reconciliation_hash and validate_hash(
            self.reconciliation_hash, field_name="reconciliation_hash"
        ) != computed:
            raise ContractValidationError("reconciliation_hash mismatch")
        object.__setattr__(self, "reconciliation_hash", computed)

    def hash_material(self) -> dict[str, Any]:
        return {
            "reconciliation_id": self.reconciliation_id,
            "status": self.status,
            "replay_projection_hash": self.replay_projection_hash,
            "expected_projection_hash": self.expected_projection_hash,
            "discrepancies": list(self.discrepancies),
            "reconciled_at": self.reconciled_at,
            "intent_id": self.intent_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.hash_material(), "reconciliation_hash": self.reconciliation_hash}
