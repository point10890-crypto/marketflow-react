"""Typed contracts shared by policies, adapters, routing, and telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


class Operation(str, Enum):
    BULK_TEXT = "bulk_text"
    COMPACT_DEBATE = "compact_debate"
    DECISIVE_TEXT = "decisive_text"
    VISION = "vision"
    INTERACTIVE_TEXT = "interactive_text"
    SPECIALIZED_GEMINI = "specialized_gemini"


class AnalysisStatus(str, Enum):
    SUCCESS_PRIMARY = "SUCCESS_PRIMARY"
    SUCCESS_FALLBACK = "SUCCESS_FALLBACK"
    DEGRADED = "DEGRADED"
    HOLD_REVIEW = "HOLD_REVIEW"
    FAILED_TECHNICAL = "FAILED_TECHNICAL"
    IN_PROGRESS = "IN_PROGRESS"


class ProviderErrorClass(str, Enum):
    AUTHENTICATION = "authentication"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    SERVER_ERROR = "server_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_JSON = "invalid_json"
    NUMERIC_MISMATCH = "numeric_mismatch"
    EMPTY = "empty"
    REFUSAL = "refusal"
    CLIENT_UNAVAILABLE = "client_unavailable"
    BREAKER_OPEN = "breaker_open"
    UNKNOWN = "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TokenUsage:
    """Normalized usage; reasoning is a subset of output, not an extra total."""

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    usage_estimated: bool = False
    raw_total_tokens: int | None = None
    mapping_version: str = "normalized-v1"
    mapping_status: str = "unverified"

    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.cached_input_tokens,
            self.output_tokens,
            self.reasoning_tokens,
            self.total_tokens,
            self.raw_total_tokens,
        )
        if any(value is not None and value < 0 for value in values):
            raise ValueError("token counts cannot be negative")
        if (
            self.cached_input_tokens is not None
            and self.input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise ValueError("cached input tokens cannot exceed input tokens")
        if self.input_tokens is None or self.output_tokens is None:
            object.__setattr__(self, "usage_estimated", True)
            object.__setattr__(self, "total_tokens", None)
        elif self.input_tokens is not None and self.output_tokens is not None:
            object.__setattr__(self, "total_tokens", self.input_tokens + self.output_tokens)
        if self.raw_total_tokens is not None:
            status = "valid" if self.total_tokens == self.raw_total_tokens else "quarantined"
            object.__setattr__(self, "mapping_status", status)

    @property
    def uncached_input_tokens(self) -> int | None:
        if self.input_tokens is None:
            return None
        return max(0, self.input_tokens - (self.cached_input_tokens or 0))

    @classmethod
    def unknown(cls) -> "TokenUsage":
        return cls(usage_estimated=True)


@dataclass(frozen=True)
class RoutingRequest:
    operation: Operation
    prompt: str
    system: str | None = None
    run_id: str | None = None
    request_id: str | None = None
    symbol: str | None = None
    market: str | None = None
    json_mode: bool = False
    max_output_tokens: int | None = None
    evidence_fingerprint: str | None = None
    caller_endpoint: str | None = None
    temperature: float = 0.3
    images: tuple[Any, ...] = ()
    expected_numbers: Mapping[str, int | float | Decimal] | None = None


@dataclass(frozen=True)
class ProviderAttempt:
    request_id: str
    provider: str
    model: str
    endpoint: str
    operation: Operation | str
    attempt_number: int
    event_ts_utc: str = field(default_factory=_utc_now)
    run_id: str | None = None
    selected: bool = False
    status: str = "failed"
    latency_ms: float = 0.0
    max_output_tokens: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage.unknown)
    estimated_cost_usd: Decimal | None = None
    pricing_version: str | None = None
    error_class: ProviderErrorClass | str | None = None
    fallback_from: str | None = None
    breaker_state: str = "closed"
    cache_hit: bool = False
    symbol: str | None = None
    market: str | None = None
    caller_endpoint: str | None = None


@dataclass(frozen=True)
class RoutingResult:
    text: str | None
    analysis_status: AnalysisStatus
    primary_provider: str | None
    actual_provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    fallback_reason: ProviderErrorClass | str | None = None
    retry_reason: ProviderErrorClass | str | None = None
    evidence_validated: bool = False
    numeric_validation: str = "not_requested"
    usage: TokenUsage = field(default_factory=TokenUsage.unknown)
    estimated_cost_usd: Decimal | None = None
    attempts: tuple[ProviderAttempt, ...] = ()
    cache_hit: bool = False


@dataclass(frozen=True)
class RoutePolicy:
    operation: Operation
    providers: tuple[str, ...]
    models: Mapping[str, str]
    max_output_tokens: int
    modality: str
    priority: int
    max_attempts_per_provider: int = 1
