"""Central sequential AI router with atomic single-flight execution."""

from __future__ import annotations

import logging
import random
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from threading import Event, Lock
from uuid import uuid4

from .breaker import CircuitBreaker
from .budget import BudgetManager, BudgetReservation
from .contracts import (
    AnalysisStatus,
    Operation,
    ProviderAttempt,
    ProviderErrorClass,
    RoutingRequest,
    RoutingResult,
    TokenUsage,
)
from .policy import policy_for
from .pricing import CostEstimate, estimate_cost_details
from .providers import AdapterResponse, ProviderAdapter, ProviderCallError, build_default_adapters, classify_exception
from .store import RoutingStore, default_store
from .telemetry import record_attempt
from .validation import validate_response


logger = logging.getLogger(__name__)
_TRANSIENT = {
    ProviderErrorClass.RATE_LIMIT,
    ProviderErrorClass.TIMEOUT,
    ProviderErrorClass.CONNECTION,
    ProviderErrorClass.SERVER_ERROR,
}
_MAX_FLIGHTS = 2_048


@dataclass
class _Flight:
    completed: Event
    result: RoutingResult | None = None


@dataclass
class _BudgetFinalizer:
    reservation: BudgetReservation
    openai_called: bool = False
    openai_usage: TokenUsage | None = None
    openai_cost_usd: Decimal | None = None


_FLIGHTS: OrderedDict[tuple[str, str, str], _Flight] = OrderedDict()
_FLIGHTS_LOCK = Lock()
_ACTIVE_BUDGET: ContextVar[_BudgetFinalizer | None] = ContextVar(
    "ai_routing_active_budget", default=None
)


def _safe_cost_estimate(
    provider: str,
    model: str,
    usage: TokenUsage,
    event_ts: str,
) -> CostEstimate:
    try:
        return estimate_cost_details(provider, model, usage, event_ts_utc=event_ts)
    except Exception as exc:
        logger.warning("[ai_routing] pricing failed: %s", type(exc).__name__)
        return CostEstimate(None, "pricing_error")


def estimate_reservation_input_tokens(request: RoutingRequest) -> int:
    """Conservative tokenizer-independent upper bound for fallback admission."""
    text_parts = [request.system or "", request.prompt]
    if request.json_mode:
        text_parts.append("Respond only in valid JSON.")
    # UTF-8 bytes are a safer upper bound than character/4 for Korean and code.
    text_tokens = sum(len(part.encode("utf-8")) for part in text_parts) + 64
    image_tokens = 0
    for image in request.images:
        if isinstance(image, (bytes, bytearray)):
            image_tokens += max(2_048, (len(image) + 2) // 3)
        else:
            image_tokens += 2_048
    return text_tokens + image_tokens


class AIRouter:
    def __init__(
        self,
        adapters: dict[str, ProviderAdapter] | None = None,
        *,
        budget: BudgetManager | None = None,
        breaker: CircuitBreaker | None = None,
        store: RoutingStore | None = None,
        retry_sleeper=time.sleep,
        retry_delay=lambda: random.uniform(0.05, 0.25),
        max_retry_delay: float = 2.0,
        single_flight_wait_seconds: float = 30.0,
    ) -> None:
        self.store = store or default_store()
        self.adapters = build_default_adapters() if adapters is None else adapters
        self.budget = budget or BudgetManager(self.store)
        self.breaker = breaker or CircuitBreaker(self.store)
        adapter_deadlines = [
            float(adapter.request_timeout_seconds)
            for adapter in self.adapters.values()
            if getattr(adapter, "request_timeout_seconds", None) is not None
        ]
        validate_deadlines = getattr(self.breaker, "validate_adapter_deadlines", None)
        if callable(validate_deadlines):
            validate_deadlines(adapter_deadlines)
        elif adapter_deadlines:
            lease = getattr(self.breaker, "probe_lease_seconds", None)
            margin = float(getattr(self.breaker, "probe_margin_seconds", 0.0))
            if lease is not None and float(lease) < max(adapter_deadlines) + margin:
                raise ValueError("probe lease must cover provider deadline plus margin")
        self.retry_sleeper = retry_sleeper
        self.retry_delay = retry_delay
        self.max_retry_delay = max(0.0, max_retry_delay)
        self.single_flight_wait_seconds = max(0.0, single_flight_wait_seconds)

    def route_text(self, request: RoutingRequest) -> RoutingResult:
        if Operation(request.operation) is Operation.VISION:
            raise ValueError("vision requests must use route_vision")
        return self._route(request)

    def route_vision(self, request: RoutingRequest) -> RoutingResult:
        if Operation(request.operation) is not Operation.VISION:
            request = replace(request, operation=Operation.VISION)
        return self._route(request)

    def _claim_flight(self, run_id: str, request_id: str) -> tuple[bool, _Flight]:
        key = (str(self.store.db_path.resolve()), run_id, request_id)
        with _FLIGHTS_LOCK:
            flight = _FLIGHTS.get(key)
            if flight is not None:
                _FLIGHTS.move_to_end(key)
                return False, flight
            completed_keys = [
                existing_key
                for existing_key, existing in _FLIGHTS.items()
                if existing.completed.is_set()
            ]
            while len(_FLIGHTS) >= _MAX_FLIGHTS and completed_keys:
                _FLIGHTS.pop(completed_keys.pop(0), None)
            if len(_FLIGHTS) >= _MAX_FLIGHTS:
                rejected = _Flight(Event())
                rejected.completed.set()
                return False, rejected
            flight = _Flight(Event())
            _FLIGHTS[key] = flight
            return True, flight

    def _route(self, request: RoutingRequest) -> RoutingResult:
        policy = policy_for(request.operation)
        request_id = request.request_id or str(uuid4())
        run_id = request.run_id or request_id
        request = replace(request, request_id=request_id, run_id=run_id)
        owner, flight = self._claim_flight(run_id, request_id)
        if not owner:
            flight.completed.wait(self.single_flight_wait_seconds)
            if flight.result is not None:
                return flight.result
            return RoutingResult(
                text=None,
                analysis_status=AnalysisStatus.IN_PROGRESS,
                primary_provider=policy.providers[0],
            )
        finalizer_token = _ACTIVE_BUDGET.set(None)
        try:
            try:
                result = self._route_owned(request)
            except Exception as exc:
                logger.warning(
                    "[ai_routing] routing infrastructure failed: %s", type(exc).__name__
                )
                result = self._failed_result(
                    policy.operation,
                    policy.providers[0],
                    (),
                    ProviderErrorClass.UNKNOWN,
                )
        finally:
            finalizer = _ACTIVE_BUDGET.get()
            if finalizer is not None:
                try:
                    self._finish_budget(
                        finalizer.reservation,
                        finalizer.openai_called,
                        finalizer.openai_usage,
                        finalizer.openai_cost_usd,
                    )
                except Exception as exc:
                    logger.warning(
                        "[ai_routing] budget finalization failed: %s", type(exc).__name__
                    )
            _ACTIVE_BUDGET.reset(finalizer_token)
        flight.result = result
        flight.completed.set()
        return result

    def _route_owned(self, request: RoutingRequest) -> RoutingResult:
        policy = policy_for(request.operation)
        request_id = request.request_id or ""
        run_id = request.run_id or request_id
        max_output_tokens = policy.max_output_tokens
        if request.max_output_tokens is not None:
            max_output_tokens = min(max_output_tokens, max(1, request.max_output_tokens))
        reservation = BudgetReservation(True, acquired_by_caller=True)
        if "openai" in policy.providers:
            reserved_input_tokens = estimate_reservation_input_tokens(request)
            reserved_cost = _safe_cost_estimate(
                "openai",
                policy.models["openai"],
                TokenUsage(
                    input_tokens=reserved_input_tokens,
                    cached_input_tokens=0,
                    output_tokens=max_output_tokens,
                ),
                datetime.now(timezone.utc).isoformat(),
            )
            reservation = self.budget.reserve(
                run_id=run_id,
                request_id=request_id,
                operation=request.operation,
                input_tokens=reserved_input_tokens,
                output_tokens=max_output_tokens,
                estimated_cost_usd=reserved_cost.cost,
                cost_pricing_version=reserved_cost.pricing_version,
            )
            if not reservation.approved:
                return self._failed_result(policy.operation, policy.providers[0], ())
            if not reservation.acquired_by_caller:
                return self._failed_result(
                    policy.operation,
                    policy.providers[0],
                    (),
                    "duplicate_request",
                )
            _ACTIVE_BUDGET.set(_BudgetFinalizer(reservation))

        attempts: list[ProviderAttempt] = []
        primary_failure_reason: ProviderErrorClass | str | None = None
        primary_retry_reason: ProviderErrorClass | str | None = None
        attempt_number = 0
        for provider_index, provider in enumerate(policy.providers):
            model = policy.models[provider]
            model_tier = "decisive" if policy.operation is Operation.DECISIVE_TEXT else "fast"
            adapter = self.adapters.get(provider)
            if adapter is None:
                if provider_index == 0 and primary_failure_reason is None:
                    primary_failure_reason = ProviderErrorClass.CLIENT_UNAVAILABLE
                continue
            provider_tries = 0
            while provider_tries < 2:
                breaker_persistence_failed = False
                try:
                    allowed = self.breaker.allow(provider, policy.modality, model_tier)
                except Exception as exc:
                    logger.warning(
                        "[ai_routing] breaker read failed: %s", type(exc).__name__
                    )
                    allowed = True
                    breaker_persistence_failed = True
                if not allowed:
                    attempt_number += 1
                    if provider_index == 0:
                        primary_failure_reason = ProviderErrorClass.BREAKER_OPEN
                    skipped = self._skipped_attempt(
                        request,
                        provider,
                        model,
                        attempt_number,
                        max_output_tokens,
                        ProviderErrorClass.BREAKER_OPEN,
                        policy.providers[0] if provider_index > 0 else None,
                    )
                    attempts.append(skipped)
                    try:
                        record_attempt(skipped, store=self.store)
                    except Exception as exc:
                        logger.warning(
                            "[ai_routing] telemetry write failed: %s", type(exc).__name__
                        )
                    break
                provider_tries += 1
                attempt_number += 1
                event_ts = datetime.now(timezone.utc).isoformat()
                started = time.perf_counter()
                response: AdapterResponse
                error_class: ProviderErrorClass | None = None
                try:
                    response = adapter.generate(
                        request,
                        model=model,
                        max_output_tokens=max_output_tokens,
                    )
                    if not isinstance(response, AdapterResponse):
                        response = AdapterResponse(text=response if isinstance(response, str) else None)
                    validation = validate_response(response.text, request)
                    if not validation.valid:
                        error_class = validation.error_class
                except ProviderCallError as exc:
                    error_class = exc.error_class
                    response = AdapterResponse(text=None, usage=exc.usage)
                    validation = validate_response(None, request)
                except Exception as exc:
                    error_class = classify_exception(exc)
                    response = AdapterResponse(text=None)
                    validation = validate_response(None, request)

                latency_ms = round((time.perf_counter() - started) * 1000, 3)
                usage = response.usage
                successful = error_class is None
                estimate = _safe_cost_estimate(provider, model, usage, event_ts)
                if provider == "openai":
                    finalizer = _ACTIVE_BUDGET.get()
                    if finalizer is not None:
                        finalizer.openai_called = True
                        finalizer.openai_usage = usage
                        finalizer.openai_cost_usd = estimate.cost
                try:
                    if successful:
                        self.breaker.record_success(provider, policy.modality, model_tier)
                    else:
                        self.breaker.record_failure(
                            provider, policy.modality, model_tier, error_class
                        )
                except Exception as exc:
                    logger.warning(
                        "[ai_routing] breaker write failed: %s", type(exc).__name__
                    )
                    breaker_persistence_failed = True
                if not successful and provider_index == 0:
                    primary_failure_reason = error_class
                    if error_class in _TRANSIENT and provider_tries < 2:
                        primary_retry_reason = error_class
                if breaker_persistence_failed:
                    breaker_state = "persistence_error"
                else:
                    try:
                        breaker_state = self.breaker.state(
                            provider, policy.modality, model_tier
                        )
                    except Exception as exc:
                        logger.warning(
                            "[ai_routing] breaker state failed: %s", type(exc).__name__
                        )
                        breaker_state = "persistence_error"
                attempt = ProviderAttempt(
                    event_ts_utc=event_ts,
                    request_id=request_id,
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    endpoint=response.endpoint or getattr(adapter, "endpoint", "generate"),
                    operation=request.operation,
                    attempt_number=attempt_number,
                    selected=successful,
                    status="success" if successful else "failed",
                    latency_ms=latency_ms,
                    max_output_tokens=max_output_tokens,
                    usage=usage,
                    estimated_cost_usd=estimate.cost,
                    pricing_version=estimate.pricing_version,
                    error_class=error_class,
                    fallback_from=policy.providers[0] if provider_index > 0 else None,
                    breaker_state=breaker_state,
                    symbol=request.symbol,
                    market=request.market,
                    caller_endpoint=request.caller_endpoint,
                )
                attempts.append(attempt)
                try:
                    record_attempt(attempt, store=self.store)
                except Exception as exc:
                    logger.warning("[ai_routing] telemetry write failed: %s", type(exc).__name__)
                if successful:
                    return RoutingResult(
                        text=response.text,
                        analysis_status=(
                            AnalysisStatus.SUCCESS_PRIMARY
                            if provider_index == 0
                            else AnalysisStatus.SUCCESS_FALLBACK
                        ),
                        primary_provider=policy.providers[0],
                        actual_provider=provider,
                        model=model,
                        fallback_used=provider_index > 0,
                        fallback_reason=(
                            primary_failure_reason if provider_index > 0 else None
                        ),
                        retry_reason=primary_retry_reason,
                        evidence_validated=True,
                        numeric_validation=validation.numeric_validation,
                        usage=usage,
                        estimated_cost_usd=estimate.cost,
                        attempts=tuple(attempts),
                    )
                should_retry = (
                    error_class in _TRANSIENT and provider_tries < 2 and provider_index == 0
                )
                if not should_retry:
                    break
                if error_class is ProviderErrorClass.RATE_LIMIT:
                    delay = min(self.max_retry_delay, max(0.0, float(self.retry_delay())))
                    self.retry_sleeper(delay)

        return self._failed_result(
            policy.operation,
            policy.providers[0],
            tuple(attempts),
            (
                primary_failure_reason
                if any(attempt.fallback_from is not None for attempt in attempts)
                else None
            ),
            retry_reason=primary_retry_reason,
        )

    def _finish_budget(
        self,
        reservation: BudgetReservation,
        openai_called: bool,
        openai_usage: TokenUsage | None,
        openai_cost_usd: Decimal | None,
    ) -> None:
        if openai_called:
            self.budget.settle(
                reservation.reservation_id,
                openai_usage or TokenUsage.unknown(),
                actual_cost_usd=openai_cost_usd,
            )
        else:
            self.budget.release(reservation.reservation_id)

    @staticmethod
    def _skipped_attempt(
        request: RoutingRequest,
        provider: str,
        model: str,
        attempt_number: int,
        max_output_tokens: int,
        error_class: ProviderErrorClass,
        fallback_from: str | None,
    ) -> ProviderAttempt:
        return ProviderAttempt(
            request_id=request.request_id or "",
            run_id=request.run_id,
            provider=provider,
            model=model,
            endpoint="skipped",
            operation=request.operation,
            attempt_number=attempt_number,
            status="skipped_breaker",
            max_output_tokens=max_output_tokens,
            error_class=error_class,
            fallback_from=fallback_from,
            breaker_state="open",
            symbol=request.symbol,
            market=request.market,
            caller_endpoint=request.caller_endpoint,
        )

    @staticmethod
    def _failed_result(
        operation: Operation,
        primary_provider: str,
        attempts: tuple[ProviderAttempt, ...],
        fallback_reason: ProviderErrorClass | str | None = None,
        retry_reason: ProviderErrorClass | str | None = None,
    ) -> RoutingResult:
        if operation is Operation.DECISIVE_TEXT:
            status = AnalysisStatus.HOLD_REVIEW
        elif operation is Operation.VISION:
            status = AnalysisStatus.FAILED_TECHNICAL
        else:
            status = AnalysisStatus.DEGRADED
        return RoutingResult(
            text=None,
            analysis_status=status,
            primary_provider=primary_provider,
            fallback_used=any(attempt.fallback_from is not None for attempt in attempts),
            fallback_reason=fallback_reason,
            retry_reason=retry_reason,
            attempts=attempts,
        )


def route_text(request: RoutingRequest, *, router: AIRouter | None = None) -> RoutingResult:
    return (router or AIRouter()).route_text(request)


def route_vision(request: RoutingRequest, *, router: AIRouter | None = None) -> RoutingResult:
    return (router or AIRouter()).route_vision(request)
