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
from threading import Event, Lock, Thread
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


class _PermitHeartbeat:
    """Keep one claimed permit alive while a provider call is in flight."""

    def __init__(
        self,
        budget: BudgetManager,
        reservation_id: str,
        owner_token: str,
        *,
        interval_seconds: float,
        abort_event: object | None = None,
    ) -> None:
        self.budget = budget
        self.reservation_id = reservation_id
        self.owner_token = owner_token
        self.interval_seconds = max(0.001, float(interval_seconds))
        self.abort_event = abort_event
        self.failed = Event()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> bool:
        try:
            thread = Thread(
                target=self._run,
                name="ai-routing-permit-heartbeat",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        except Exception as exc:
            self._thread = None
            logger.warning(
                "[ai_routing] permit heartbeat start failed: %s", type(exc).__name__
            )
            self._mark_failed()
            return False
        return True

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                renewed = self.budget.renew(
                    self.reservation_id,
                    owner_token=self.owner_token,
                )
            except Exception as exc:
                logger.warning(
                    "[ai_routing] permit heartbeat failed: %s", type(exc).__name__
                )
                renewed = False
            if not renewed:
                self._mark_failed()
                return

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=max(0.1, min(5.0, self.interval_seconds * 2.0)))
        if thread.is_alive():
            self._mark_failed()

    def _mark_failed(self) -> None:
        self.failed.set()
        if self.abort_event is None:
            return
        try:
            self.abort_event.set()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning(
                "[ai_routing] permit heartbeat abort signal failed: %s",
                type(exc).__name__,
            )


@dataclass
class _BudgetFinalizer:
    reservation: BudgetReservation
    heartbeat: _PermitHeartbeat | None = None
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


def reserve_openai_fallback(
    request: RoutingRequest, *, budget: BudgetManager | None = None,
    owner_token: str | None = None,
) -> BudgetReservation:
    """Hold one provider fallback allowance before a worker is submitted."""
    policy = policy_for(request.operation)
    if "openai" not in policy.providers:
        return BudgetReservation(True)
    manager = budget or BudgetManager()
    max_output_tokens = policy.max_output_tokens
    if request.max_output_tokens is not None:
        max_output_tokens = min(max_output_tokens, max(1, request.max_output_tokens))
    input_tokens = estimate_reservation_input_tokens(request)
    estimate = _safe_cost_estimate(
        "openai", policy.models["openai"],
        TokenUsage(input_tokens=input_tokens, cached_input_tokens=0,
                   output_tokens=max_output_tokens),
        datetime.now(timezone.utc).isoformat(),
    )
    return manager.reserve(
        run_id=request.run_id or request.request_id or "",
        request_id=request.request_id or "",
        operation=request.operation, input_tokens=input_tokens,
        output_tokens=max_output_tokens, estimated_cost_usd=estimate.cost,
        cost_pricing_version=estimate.pricing_version,
        owner_token=owner_token,
    )


def release_openai_reservations(
    reservations: list[tuple[str, str]], *,
    budget: BudgetManager | None = None,
) -> None:
    """Release any still-unused preflight holds; settled permits are unchanged."""
    manager = budget or BudgetManager()
    for reservation_id, owner_token in dict.fromkeys(
        (str(reservation_id), str(owner_token))
        for reservation_id, owner_token in reservations if reservation_id and owner_token
    ):
        manager.release(reservation_id, owner_token=owner_token)


def renew_openai_reservations(
    reservations: list[tuple[str, str]], *,
    budget: BudgetManager | None = None,
) -> bool:
    """Atomically keep owned queued/claimed fallback permits alive."""
    manager = budget or BudgetManager()
    return manager.renew_many(reservations, terminal_ok=True)


def openai_permit_heartbeat_seconds() -> float:
    """Poll often enough that a healthy coordinator refreshes before expiry."""
    return max(0.05, min(30.0, BudgetManager._lease_seconds() / 3.0))


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
        budget_finalized = True
        budget_failure_reason = "reservation_breached"
        permit_heartbeat_failed = False
        fatal_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        result = self._failed_result(
            policy.operation, policy.providers[0], (), "routing_interrupted"
        )
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
        except BaseException as exc:
            fatal_error = exc
        finally:
            finalizer = _ACTIVE_BUDGET.get()
            if finalizer is not None:
                if finalizer.heartbeat is not None:
                    try:
                        finalizer.heartbeat.stop()
                    except BaseException as exc:
                        if not isinstance(exc, Exception):
                            cleanup_error = exc
                        permit_heartbeat_failed = True
                        logger.warning(
                            "[ai_routing] permit heartbeat cleanup failed: %s",
                            type(exc).__name__,
                        )
                    permit_heartbeat_failed = (
                        permit_heartbeat_failed
                        or finalizer.heartbeat.failed.is_set()
                    )
                budget_finalized = False
                try:
                    budget_finalized = self._finish_budget(
                        finalizer.reservation,
                        finalizer.openai_called,
                        finalizer.openai_usage,
                        finalizer.openai_cost_usd,
                    )
                except BaseException as exc:
                    if cleanup_error is None and not isinstance(exc, Exception):
                        cleanup_error = exc
                    budget_failure_reason = "budget_finalization_failed"
                    logger.warning(
                        "[ai_routing] budget finalization failed: %s", type(exc).__name__
                    )
            try:
                _ACTIVE_BUDGET.reset(finalizer_token)
            except BaseException as exc:
                if cleanup_error is None and not isinstance(exc, Exception):
                    cleanup_error = exc
                budget_finalized = False
                budget_failure_reason = "budget_finalization_failed"
                logger.warning(
                    "[ai_routing] budget context cleanup failed: %s",
                    type(exc).__name__,
                )
        if (
            fatal_error is not None
            or cleanup_error is not None
            or not budget_finalized
            or permit_heartbeat_failed
        ):
            self._signal_permit_abort(request)
        if not budget_finalized:
            logger.error(
                "[ai_routing] provider result rejected after budget finalization: %s",
                budget_failure_reason,
            )
            result = self._failed_result(
                policy.operation, policy.providers[0], tuple(result.attempts),
                budget_failure_reason,
            )
        if permit_heartbeat_failed:
            logger.error(
                "[ai_routing] provider result rejected after permit heartbeat failure"
            )
            result = self._failed_result(
                policy.operation, policy.providers[0], tuple(result.attempts),
                "permit_renewal_failed",
            )
        flight.result = result
        flight.completed.set()
        if fatal_error is not None:
            raise fatal_error
        if cleanup_error is not None:
            raise cleanup_error
        return result

    def _route_owned(self, request: RoutingRequest) -> RoutingResult:
        policy = policy_for(request.operation)
        request_id = request.request_id or ""
        run_id = request.run_id or request_id
        max_output_tokens = policy.max_output_tokens
        if request.max_output_tokens is not None:
            max_output_tokens = min(max_output_tokens, max(1, request.max_output_tokens))
        if self._permit_abort_requested(request):
            return self._failed_result(
                policy.operation,
                policy.providers[0],
                (),
                "permit_lease_renewal_failed",
            )
        reservation = BudgetReservation(True, acquired_by_caller=True)
        if "openai" in policy.providers:
            if request.reservation_id:
                reservation = self.budget.claim(
                    request.reservation_id, run_id=run_id, request_id=request_id,
                    owner_token=request.reservation_owner_token,
                    input_tokens=estimate_reservation_input_tokens(request),
                    output_tokens=max_output_tokens,
                )
            else:
                reservation = reserve_openai_fallback(request, budget=self.budget)
                if reservation.approved and reservation.acquired_by_caller:
                    _ACTIVE_BUDGET.set(_BudgetFinalizer(reservation))
                    reservation = self.budget.claim(
                        reservation.reservation_id,
                        run_id=run_id,
                        request_id=request_id,
                        owner_token=reservation.owner_token,
                        input_tokens=estimate_reservation_input_tokens(request),
                        output_tokens=max_output_tokens,
                    )
            if not reservation.approved:
                self._signal_permit_abort(request)
                return self._failed_result(
                    policy.operation,
                    policy.providers[0],
                    (),
                    reservation.reason,
                )
            if not reservation.acquired_by_caller:
                self._signal_permit_abort(request)
                return self._failed_result(
                    policy.operation,
                    policy.providers[0],
                    (),
                    "duplicate_request",
                )
            finalizer = _BudgetFinalizer(reservation)
            _ACTIVE_BUDGET.set(finalizer)
            try:
                permit_alive = self.budget.renew(
                    reservation.reservation_id,
                    owner_token=reservation.owner_token,
                )
            except Exception as exc:
                logger.warning(
                    "[ai_routing] permit renewal failed: %s", type(exc).__name__
                )
                permit_alive = False
            if not permit_alive:
                self._signal_permit_abort(request)
                return self._failed_result(
                    policy.operation,
                    policy.providers[0],
                    (),
                    "permit_renewal_failed",
                )
            heartbeat = _PermitHeartbeat(
                self.budget,
                str(reservation.reservation_id),
                str(reservation.owner_token),
                interval_seconds=openai_permit_heartbeat_seconds(),
                abort_event=request.permit_abort_event,
            )
            finalizer.heartbeat = heartbeat
            if not heartbeat.start():
                self._signal_permit_abort(request)
                return self._failed_result(
                    policy.operation,
                    policy.providers[0],
                    (),
                    "permit_renewal_failed",
                )

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
                if self._permit_abort_requested(request):
                    return self._failed_result(
                        policy.operation,
                        policy.providers[0],
                        tuple(attempts),
                        "permit_lease_renewal_failed",
                        retry_reason=primary_retry_reason,
                    )
                active_budget = _ACTIVE_BUDGET.get()
                if (
                    active_budget is not None
                    and active_budget.heartbeat is not None
                    and active_budget.heartbeat.failed.is_set()
                ):
                    return self._failed_result(
                        policy.operation,
                        policy.providers[0],
                        tuple(attempts),
                        "permit_renewal_failed",
                        retry_reason=primary_retry_reason,
                    )
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
                if self._permit_abort_requested(request):
                    return self._failed_result(
                        policy.operation,
                        policy.providers[0],
                        tuple(attempts),
                        "permit_lease_renewal_failed",
                        retry_reason=primary_retry_reason,
                    )
                if (
                    active_budget is not None
                    and active_budget.heartbeat is not None
                    and active_budget.heartbeat.failed.is_set()
                ):
                    return self._failed_result(
                        policy.operation,
                        policy.providers[0],
                        tuple(attempts),
                        "permit_renewal_failed",
                        retry_reason=primary_retry_reason,
                    )
                provider_tries += 1
                attempt_number += 1
                event_ts = datetime.now(timezone.utc).isoformat()
                started = time.perf_counter()
                response: AdapterResponse
                error_class: ProviderErrorClass | None = None
                if provider == "openai":
                    finalizer = _ACTIVE_BUDGET.get()
                    if finalizer is not None:
                        try:
                            permit_alive = self.budget.renew(
                                finalizer.reservation.reservation_id,
                                owner_token=finalizer.reservation.owner_token,
                            )
                        except Exception as exc:
                            logger.warning(
                                "[ai_routing] pre-dispatch permit validation failed: %s",
                                type(exc).__name__,
                            )
                            permit_alive = False
                        if not permit_alive:
                            self._signal_permit_abort(request)
                            return self._failed_result(
                                policy.operation,
                                policy.providers[0],
                                tuple(attempts),
                                "permit_renewal_failed",
                                retry_reason=primary_retry_reason,
                            )
                        if self._permit_abort_requested(request):
                            return self._failed_result(
                                policy.operation,
                                policy.providers[0],
                                tuple(attempts),
                                "permit_lease_renewal_failed",
                                retry_reason=primary_retry_reason,
                            )
                        if (
                            finalizer.heartbeat is not None
                            and finalizer.heartbeat.failed.is_set()
                        ):
                            self._signal_permit_abort(request)
                            return self._failed_result(
                                policy.operation,
                                policy.providers[0],
                                tuple(attempts),
                                "permit_renewal_failed",
                                retry_reason=primary_retry_reason,
                            )
                        # Dispatch can raise BaseException after the provider has
                        # accepted work. Account conservatively before crossing
                        # that boundary; a normal response replaces unknown usage.
                        finalizer.openai_called = True
                        finalizer.openai_usage = TokenUsage.unknown()
                        finalizer.openai_cost_usd = None
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

    @staticmethod
    def _permit_abort_requested(request: RoutingRequest) -> bool:
        event = request.permit_abort_event
        if event is None:
            return False
        try:
            return bool(event.is_set())
        except Exception as exc:
            logger.warning(
                "[ai_routing] permit abort fence failed: %s", type(exc).__name__
            )
            return True

    @staticmethod
    def _signal_permit_abort(request: RoutingRequest) -> None:
        event = request.permit_abort_event
        if event is None:
            return
        try:
            event.set()
        except Exception as exc:
            logger.warning(
                "[ai_routing] permit abort signal failed: %s", type(exc).__name__
            )

    def _finish_budget(
        self,
        reservation: BudgetReservation,
        openai_called: bool,
        openai_usage: TokenUsage | None,
        openai_cost_usd: Decimal | None,
    ) -> bool:
        if openai_called:
            return self.budget.settle(
                reservation.reservation_id,
                openai_usage or TokenUsage.unknown(),
                actual_cost_usd=openai_cost_usd,
            )
        return (
            self.budget.release_claimed(reservation.reservation_id)
            or self.budget.release(
                reservation.reservation_id, owner_token=reservation.owner_token,
            )
        )

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
