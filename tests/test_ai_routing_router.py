from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

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
from app.services.ai_routing.router import AIRouter, estimate_reservation_input_tokens
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


class RepeatingAdapter:
    endpoint = "fake.generate"

    def __init__(self, result):
        self.result = result
        self.calls = 0
        self._lock = Lock()

    def generate(self, request, *, model, max_output_tokens):
        with self._lock:
            self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


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


def test_duplicate_request_id_single_flight_bills_and_records_fallback_once(tmp_path):
    deepseek = RepeatingAdapter(ProviderCallError(ProviderErrorClass.AUTHENTICATION))
    openai = RepeatingAdapter(_response("fallback"))
    router, store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})
    request = _request(request_id="same-request")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: router.route_text(request), range(8)))
    router.route_text(request)

    assert all(result.text == "fallback" for result in results)
    assert deepseek.calls == 1
    assert openai.calls == 1
    summary = usage_summary(days=1, limit=20, store=store)
    openai_attempts = sum(
        group["attempts"] for group in summary["groups"] if group["provider"] == "openai"
    )
    assert openai_attempts == 1
    assert router.budget.snapshot("run-1").used_calls == 1


def test_reservation_estimate_includes_system_json_and_images():
    base = RoutingRequest(operation=Operation.VISION, prompt="가", run_id="run", request_id="base")
    rich = RoutingRequest(
        operation=Operation.VISION,
        prompt="가",
        system="system instructions",
        json_mode=True,
        images=(b"image-bytes",),
        run_id="run",
        request_id="rich",
    )

    assert estimate_reservation_input_tokens(rich) > estimate_reservation_input_tokens(base) + 2_000


def test_same_evidence_fingerprint_does_not_use_incomplete_result_cache(tmp_path):
    deepseek = FakeAdapter(_response("first"), _response("second"))
    router, _store = _router(tmp_path, {"deepseek": deepseek, "openai": FakeAdapter(_response("unused"))})
    first = _request(request_id="one")
    second = _request(request_id="two")
    first = RoutingRequest(**{**first.__dict__, "evidence_fingerprint": "same"})
    second = RoutingRequest(**{**second.__dict__, "evidence_fingerprint": "same", "prompt": "different"})

    assert router.route_text(first).text == "first"
    assert router.route_text(second).text == "second"
    assert deepseek.calls == 2


def test_breaker_skipped_primary_still_reports_failed_fallback(tmp_path):
    router, _store = _router(
        tmp_path,
        {
            "deepseek": FakeAdapter(_response("unused")),
            "openai": FakeAdapter(ProviderCallError(ProviderErrorClass.AUTHENTICATION)),
        },
    )
    router.breaker.record_failure(
        "deepseek", "text", "decisive", ProviderErrorClass.AUTHENTICATION
    )

    result = router.route_text(_request())

    assert result.fallback_used is True
    assert result.fallback_reason is ProviderErrorClass.BREAKER_OPEN
    assert result.attempts[0].error_class is ProviderErrorClass.BREAKER_OPEN
    assert result.attempts[1].fallback_from == "deepseek"


def test_429_retry_uses_bounded_injected_delay(tmp_path):
    delays = []
    deepseek = FakeAdapter(
        ProviderCallError(ProviderErrorClass.RATE_LIMIT),
        _response("retried"),
    )
    store = RoutingStore(tmp_path / "usage.sqlite3")
    router = AIRouter(
        {"deepseek": deepseek, "openai": FakeAdapter(_response("unused"))},
        budget=BudgetManager(store),
        breaker=CircuitBreaker(store),
        store=store,
        retry_sleeper=delays.append,
        retry_delay=lambda: 99.0,
        max_retry_delay=2.0,
    )

    result = router.route_text(_request())

    assert result.text == "retried"
    assert delays == [2.0]


def test_retry_rechecks_breaker_after_first_transient_failure(tmp_path):
    deepseek = FakeAdapter(
        ProviderCallError(ProviderErrorClass.RATE_LIMIT),
        _response("must-not-retry"),
    )
    store = RoutingStore(tmp_path / "usage.sqlite3")
    router = AIRouter(
        {"deepseek": deepseek, "openai": FakeAdapter(_response("fallback"))},
        budget=BudgetManager(store),
        breaker=CircuitBreaker(store, failure_threshold=1),
        store=store,
        retry_sleeper=lambda _seconds: None,
        retry_delay=lambda: 0.0,
    )

    result = router.route_text(_request())

    assert result.actual_provider == "openai"
    assert deepseek.calls == 1
