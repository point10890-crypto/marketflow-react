from collections import deque

from app.services.ai_routing.breaker import CircuitBreaker
from app.services.ai_routing.budget import BudgetManager
from app.services.ai_routing.contracts import (
    AnalysisStatus,
    Operation,
    ProviderErrorClass,
    RoutingRequest,
    TokenUsage,
)
from app.services.ai_routing.providers import AdapterResponse, ProviderCallError
from app.services.ai_routing.router import AIRouter
from app.services.ai_routing.store import RoutingStore
from app.services.ai_routing.telemetry import usage_summary


class FakeAdapter:
    endpoint = "fake.generate"

    def __init__(self, *results):
        self.results = deque(results)
        self.calls = 0

    def generate(self, request, *, model, max_output_tokens):
        self.calls += 1
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result


def _response(text, *, input_tokens=10, output_tokens=4):
    return AdapterResponse(
        text=text,
        usage=TokenUsage(input_tokens=input_tokens, cached_input_tokens=0, output_tokens=output_tokens),
    )


def _router(tmp_path, adapters):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    return (
        AIRouter(
            adapters,
            budget=BudgetManager(store),
            breaker=CircuitBreaker(store),
            store=store,
        ),
        store,
    )


def _request(operation=Operation.DECISIVE_TEXT, *, request_id="request-1", json_mode=False):
    return RoutingRequest(
        operation=operation,
        prompt="bounded fixture prompt",
        run_id="run-1",
        request_id=request_id,
        json_mode=json_mode,
        caller_endpoint="/api/test",
    )


def test_decisive_deepseek_then_one_openai_fallback(tmp_path):
    deepseek = FakeAdapter(ProviderCallError(ProviderErrorClass.TIMEOUT))
    openai = FakeAdapter(_response('{"decision":"WATCH"}'))
    router, _store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})

    result = router.route_text(_request(json_mode=True))

    assert result.analysis_status is AnalysisStatus.SUCCESS_FALLBACK
    assert result.actual_provider == "openai"
    assert result.fallback_used is True
    assert deepseek.calls == 2  # one bounded transient retry
    assert openai.calls == 1


def test_both_decisive_providers_fail_returns_hold_review(tmp_path):
    error = ProviderCallError(ProviderErrorClass.AUTHENTICATION)
    router, _store = _router(
        tmp_path,
        {"deepseek": FakeAdapter(error), "openai": FakeAdapter(error)},
    )

    result = router.route_text(_request())

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.HOLD_REVIEW


def test_auth_failure_opens_breaker_and_next_request_skips_dead_provider(tmp_path):
    deepseek = FakeAdapter(
        ProviderCallError(ProviderErrorClass.AUTHENTICATION),
        _response("must-not-be-used"),
    )
    openai = FakeAdapter(_response("fallback-1"), _response("fallback-2"))
    router, _store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})

    first = router.route_text(_request())
    second = router.route_text(_request(request_id="request-2"))

    assert first.actual_provider == "openai"
    assert second.actual_provider == "openai"
    assert deepseek.calls == 1
    assert any(attempt.breaker_state == "open" for attempt in second.attempts if attempt.provider == "deepseek")


def test_budget_exhaustion_does_not_call_provider(tmp_path):
    deepseek = FakeAdapter(_response("must-not-call"))
    openai = FakeAdapter(_response("must-not-call"))
    router, _store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})
    for index in range(5):
        router.budget.reserve(
            run_id="run-1",
            request_id=f"seed-{index}",
            operation=Operation.DECISIVE_TEXT,
            input_tokens=1,
            output_tokens=1,
        )

    result = router.route_text(_request())

    assert result.analysis_status is AnalysisStatus.HOLD_REVIEW
    assert deepseek.calls == 0
    assert openai.calls == 0


def test_invalid_json_falls_back_without_global_breaker(tmp_path):
    deepseek = FakeAdapter(_response("not-json"))
    openai = FakeAdapter(_response('{"ok":true}'))
    router, _store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})

    result = router.route_text(_request(json_mode=True))

    assert result.actual_provider == "openai"
    assert router.breaker.state("deepseek", "text", "decisive") == "closed"
    assert result.attempts[0].error_class is ProviderErrorClass.INVALID_JSON


def test_usage_is_recorded_for_every_billable_attempt(tmp_path):
    deepseek = FakeAdapter(_response(""))
    openai = FakeAdapter(_response("ok", input_tokens=30, output_tokens=5))
    router, store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})

    router.route_text(_request())

    summary = usage_summary(days=1, limit=20, store=store)
    assert summary["totals"]["attempts"] == 2
    assert summary["totals"]["total_tokens"] == 49


def test_vision_starts_with_gemini_and_skips_unverified_deepseek_vision(tmp_path):
    gemini = FakeAdapter(_response("chart-result"))
    deepseek = FakeAdapter(_response("must-not-call"))
    openai = FakeAdapter(_response("must-not-call"))
    router, _store = _router(
        tmp_path,
        {"gemini": gemini, "deepseek": deepseek, "openai": openai},
    )

    result = router.route_vision(_request(Operation.VISION))

    assert result.actual_provider == "gemini"
    assert gemini.calls == 1
    assert deepseek.calls == 0
    assert openai.calls == 0
