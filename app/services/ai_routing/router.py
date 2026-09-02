"""Central sequential AI router with budget, breaker, validation, and usage."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from threading import Lock
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
from .pricing import PRICING_VERSION, estimate_cost
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


class AIRouter:
    def __init__(
        self,
        adapters: dict[str, ProviderAdapter] | None = None,
        *,
        budget: BudgetManager | None = None,
        breaker: CircuitBreaker | None = None,
        store: RoutingStore | None = None,
        result_cache: dict[str, RoutingResult] | None = None,
    ) -> None:
        self.store = store or default_store()
        self.adapters = build_default_adapters() if adapters is None else adapters
        self.budget = budget or BudgetManager(self.store)
        self.breaker = breaker or CircuitBreaker(self.store)
        self.result_cache = result_cache if result_cache is not None else {}
        self._cache_lock = Lock()

    def route_text(self, request: RoutingRequest) -> RoutingResult:
        if Operation(request.operation) is Operation.VISION:
            raise ValueError("vision requests must use route_vision")
        return self._route(request)

    def route_vision(self, request: RoutingRequest) -> RoutingResult:
        if Operation(request.operation) is not Operation.VISION:
            request = replace(request, operation=Operation.VISION)
        return self._route(request)

    def _route(self, request: RoutingRequest) -> RoutingResult:
        policy = policy_for(request.operation)
        request_id = request.request_id or str(uuid4())
        run_id = request.run_id or request_id
        request = replace(request, request_id=request_id, run_id=run_id)
        cache_key = (
            f"{request.operation.value}:{request.evidence_fingerprint}"
            if request.evidence_fingerprint
            else None
        )
        if cache_key:
            with self._cache_lock:
                cached = self.result_cache.get(cache_key)
            if cached is not None:
                return replace(cached, cache_hit=True)

        max_output_tokens = policy.max_output_tokens
        if request.max_output_tokens is not None:
            max_output_tokens = min(max_output_tokens, max(1, request.max_output_tokens))
        estimated_input_tokens = max(1, len(request.prompt) // 4)
        reservation = BudgetReservation(True)
        if "openai" in policy.providers:
            reservation = self.budget.reserve(
                run_id=run_id,
                request_id=request_id,
                operation=request.operation,
                input_tokens=estimated_input_tokens,
                output_tokens=max_output_tokens,
            )
            if not reservation.approved:
                return self._failed_result(policy.operation, policy.providers[0], ())

        attempts: list[ProviderAttempt] = []
        fallback_reason: ProviderErrorClass | None = None
        openai_usage: TokenUsage | None = None
        openai_called = False
        attempt_number = 0
        for provider_index, provider in enumerate(policy.providers):
            model = policy.models[provider]
            model_tier = "decisive" if policy.operation is Operation.DECISIVE_TEXT else "fast"
            if not self.breaker.allow(provider, policy.modality, model_tier):
                attempt_number += 1
                attempts.append(
                    self._skipped_attempt(
                        request,
                        provider,
                        model,
                        attempt_number,
                        max_output_tokens,
                        "open",
                        fallback_reason,
                    )
                )
                continue
            adapter = self.adapters.get(provider)
            if adapter is None:
                error_class = ProviderErrorClass.CLIENT_UNAVAILABLE
                if fallback_reason is None:
                    fallback_reason = error_class
                continue

            provider_tries = 0
            while True:
                provider_tries += 1
                attempt_number += 1
                started = time.perf_counter()
                response: AdapterResponse | None = None
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
                except Exception as exc:
                    error_class = classify_exception(exc)
                    response = AdapterResponse(text=None)

                latency_ms = round((time.perf_counter() - started) * 1000, 3)
                usage = response.usage
                if provider == "openai":
                    openai_called = True
                    openai_usage = usage
                successful = error_class is None
                if successful:
                    self.breaker.record_success(provider, policy.modality, model_tier)
                else:
                    self.breaker.record_failure(provider, policy.modality, model_tier, error_class)
                    if fallback_reason is None:
                        fallback_reason = error_class
                cost = estimate_cost(provider, model, usage)
                attempt = ProviderAttempt(
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
                    estimated_cost_usd=cost,
                    pricing_version=PRICING_VERSION if cost is not None else None,
                    error_class=error_class,
                    fallback_from=policy.providers[0] if provider_index > 0 else None,
                    breaker_state=self.breaker.state(provider, policy.modality, model_tier),
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
                    if openai_called:
                        self.budget.settle(reservation.reservation_id, openai_usage or TokenUsage.unknown())
                    else:
                        self.budget.release(reservation.reservation_id)
                    result = RoutingResult(
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
                        fallback_reason=fallback_reason,
                        evidence_validated=True,
                        numeric_validation=validation.numeric_validation,
                        usage=usage,
                        estimated_cost_usd=cost,
                        attempts=tuple(attempts),
                    )
                    if cache_key:
                        with self._cache_lock:
                            self.result_cache[cache_key] = result
                    return result
                if error_class not in _TRANSIENT or provider_tries >= 2 or provider_index > 0:
                    break

        if openai_called:
            self.budget.settle(reservation.reservation_id, openai_usage or TokenUsage.unknown())
        else:
            self.budget.release(reservation.reservation_id)
        return self._failed_result(policy.operation, policy.providers[0], tuple(attempts), fallback_reason)

    @staticmethod
    def _skipped_attempt(
        request: RoutingRequest,
        provider: str,
        model: str,
        attempt_number: int,
        max_output_tokens: int,
        breaker_state: str,
        fallback_reason: ProviderErrorClass | None,
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
            error_class=fallback_reason,
            breaker_state=breaker_state,
            symbol=request.symbol,
            market=request.market,
            caller_endpoint=request.caller_endpoint,
        )

    @staticmethod
    def _failed_result(
        operation: Operation,
        primary_provider: str,
        attempts: tuple[ProviderAttempt, ...],
        fallback_reason: ProviderErrorClass | None = None,
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
            fallback_used=len({item.provider for item in attempts if item.endpoint != "skipped"}) > 1,
            fallback_reason=fallback_reason,
            attempts=attempts,
        )


def route_text(request: RoutingRequest, *, router: AIRouter | None = None) -> RoutingResult:
    return (router or AIRouter()).route_text(request)


def route_vision(request: RoutingRequest, *, router: AIRouter | None = None) -> RoutingResult:
    return (router or AIRouter()).route_vision(request)
