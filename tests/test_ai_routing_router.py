from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from threading import Event

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
from app.services.ai_routing.router import AIRouter, estimate_reservation_input_tokens, reserve_openai_fallback
from app.services.ai_routing.store import RoutingStore
from app.services.ai_routing.telemetry import usage_summary
from app.services.ai_routing import router as router_module


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


def test_domain_schema_rejection_is_a_provider_failure_then_one_fallback(tmp_path):
    deepseek = FakeAdapter(_response('{"verdict":"NOT_ALLOWED"}'))
    openai = FakeAdapter(_response('{"verdict":"BUY"}'))
    router, _store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture', run_id='domain-run',
        request_id='domain-request', json_mode=True,
        domain_validator=lambda value: (
            None if value.get('verdict') in {'BUY', 'HOLD', 'SELL'}
            else ProviderErrorClass.INVALID_JSON
        ),
    )
    result = router.route_text(request)
    assert result.analysis_status is AnalysisStatus.SUCCESS_FALLBACK
    assert deepseek.calls == 1 and openai.calls == 1
    assert result.attempts[0].error_class is ProviderErrorClass.INVALID_JSON


def test_router_claims_pre_reserved_permit_and_settles_without_second_debit(tmp_path):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture', run_id='permit-run',
        request_id='permit-request', json_mode=True,
    )
    permit = reserve_openai_fallback(request, budget=budget)
    assert permit.approved and permit.reservation_id
    routed = RoutingRequest(**{**request.__dict__, 'reservation_id': permit.reservation_id})
    router = AIRouter(
        {'deepseek': FakeAdapter(ProviderCallError(ProviderErrorClass.AUTHENTICATION)),
         'openai': FakeAdapter(_response('{"verdict":"BUY"}'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )
    result = router.route_text(routed)
    assert result.analysis_status is AnalysisStatus.SUCCESS_FALLBACK
    with store.transaction() as connection:
        rows = connection.execute(
            "SELECT status, actual_calls FROM budget_reservations WHERE run_id='permit-run'"
        ).fetchall()
    assert [(row['status'], row['actual_calls']) for row in rows] == [('settled', 1)]


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


def test_half_open_invalid_json_is_rejected_then_fallback_proceeds(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    clock = type("Clock", (), {"value": 1_000.0, "__call__": lambda self: self.value})()
    breaker = CircuitBreaker(store, cooldown_seconds=10, clock=clock)
    breaker.record_failure(
        "deepseek", "text", "decisive", ProviderErrorClass.AUTHENTICATION
    )
    clock.value += 11
    deepseek = FakeAdapter(_response("not-json"))
    openai = FakeAdapter(_response('{"ok":true}'))
    router = AIRouter(
        {"deepseek": deepseek, "openai": openai},
        budget=BudgetManager(store),
        breaker=breaker,
        store=store,
    )

    result = router.route_text(_request(json_mode=True))

    assert result.actual_provider == "openai"
    assert result.attempts[0].error_class is ProviderErrorClass.INVALID_JSON
    assert breaker.state("deepseek", "text", "decisive") == "closed"


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
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.retry_reason is ProviderErrorClass.RATE_LIMIT


def test_primary_retry_reason_is_separate_from_true_fallback_reason(tmp_path):
    deepseek = FakeAdapter(
        ProviderCallError(ProviderErrorClass.RATE_LIMIT),
        ProviderCallError(ProviderErrorClass.AUTHENTICATION),
    )
    openai = FakeAdapter(_response("fallback"))
    router, _store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})

    result = router.route_text(_request())

    assert result.actual_provider == "openai"
    assert result.retry_reason is ProviderErrorClass.RATE_LIMIT
    assert result.fallback_reason is ProviderErrorClass.AUTHENTICATION


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


def test_both_open_breakers_record_decisions_not_live_calls(tmp_path):
    router, store = _router(
        tmp_path,
        {
            "deepseek": FakeAdapter(_response("unused")),
            "openai": FakeAdapter(_response("unused")),
        },
    )
    for provider in ("deepseek", "openai"):
        router.breaker.record_failure(
            provider, "text", "decisive", ProviderErrorClass.AUTHENTICATION
        )

    router.route_text(_request())
    summary = usage_summary(1, 20, store=store)

    assert summary["totals"]["attempts"] == 2
    assert summary["totals"]["live_attempts"] == 0
    assert summary["totals"]["breaker_skipped_attempts"] == 2
    assert summary["totals"]["fallbacks"] == 0


def test_pricing_error_after_billable_fallback_still_audits_and_settles(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_ROUTING_PRICE_OPENAI_INPUT_PER_MILLION", "invalid")
    deepseek = FakeAdapter(ProviderCallError(ProviderErrorClass.AUTHENTICATION))
    openai = FakeAdapter(_response("fallback", input_tokens=50, output_tokens=10))
    router, store = _router(tmp_path, {"deepseek": deepseek, "openai": openai})

    result = router.route_text(_request())

    assert result.text == "fallback"
    assert result.actual_provider == "openai"
    with store.transaction() as connection:
        reservation = connection.execute(
            "SELECT status, actual_input_tokens, actual_output_tokens "
            "FROM budget_reservations WHERE request_id = 'request-1'"
        ).fetchone()
        attempt = connection.execute(
            "SELECT input_tokens, output_tokens, estimated_cost_usd "
            "FROM provider_attempts WHERE request_id = 'request-1' AND provider = 'openai'"
        ).fetchone()
    assert tuple(reservation) == ("settled", 50, 10)
    assert tuple(attempt) == (50, 10, None)


def test_single_flight_registry_stays_bounded_behind_hung_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(router_module, "_MAX_FLIGHTS", 3)
    with router_module._FLIGHTS_LOCK:
        router_module._FLIGHTS.clear()
    router, _store = _router(tmp_path, {"deepseek": FakeAdapter(_response("ok"))})

    _owner, hung = router._claim_flight("run", "hung")
    for request_id in ("done-1", "done-2"):
        _owner, flight = router._claim_flight("run", request_id)
        flight.result = router._failed_result(Operation.BULK_TEXT, "deepseek", ())
        flight.completed.set()

    for request_id in ("new-1", "new-2", "new-3"):
        router._claim_flight("run", request_id)

    with router_module._FLIGHTS_LOCK:
        assert len(router_module._FLIGHTS) <= 3
    assert hung.completed.is_set() is False


def test_duplicate_wait_timeout_returns_explicit_in_progress_status(tmp_path):
    entered = Event()
    release = Event()

    class BlockingAdapter:
        endpoint = "fake.generate"

        def generate(self, request, *, model, max_output_tokens):
            entered.set()
            release.wait(5)
            return _response("owner-result")

    store = RoutingStore(tmp_path / "usage.sqlite3")
    router = AIRouter(
        {"deepseek": BlockingAdapter(), "openai": FakeAdapter(_response("unused"))},
        budget=BudgetManager(store),
        breaker=CircuitBreaker(store),
        store=store,
        single_flight_wait_seconds=0,
    )
    request = _request(request_id="in-progress-request")
    with ThreadPoolExecutor(max_workers=1) as executor:
        owner = executor.submit(router.route_text, request)
        assert entered.wait(2)
        duplicate = router.route_text(request)
        release.set()
        owner_result = owner.result(timeout=5)

    assert duplicate.analysis_status is AnalysisStatus.IN_PROGRESS
    assert duplicate.fallback_reason is None
    assert owner_result.text == "owner-result"


class BrokenPersistenceBreaker:
    probe_lease_seconds = 120
    probe_margin_seconds = 30

    def allow(self, provider, modality, model_tier):
        return True

    def record_success(self, provider, modality, model_tier):
        raise OSError("breaker unavailable")

    def record_failure(self, provider, modality, model_tier, error_class):
        raise OSError("breaker unavailable")

    def state(self, provider, modality, model_tier):
        raise OSError("breaker unavailable")


def test_breaker_persistence_failure_does_not_discard_valid_response(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    router = AIRouter(
        {"deepseek": FakeAdapter(_response("valid"))},
        budget=BudgetManager(store),
        breaker=BrokenPersistenceBreaker(),
        store=store,
    )

    result = router.route_text(_request(Operation.BULK_TEXT))

    assert result.text == "valid"
    assert len(result.attempts) == 1
    assert result.attempts[0].breaker_state == "persistence_error"
    assert usage_summary(1, 20, store=store)["totals"]["live_attempts"] == 1


def test_breaker_persistence_failure_does_not_hide_billable_failure(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    deepseek = FakeAdapter(ProviderCallError(ProviderErrorClass.AUTHENTICATION))
    openai = FakeAdapter(_response("fallback", input_tokens=20, output_tokens=5))
    router = AIRouter(
        {"deepseek": deepseek, "openai": openai},
        budget=BudgetManager(store),
        breaker=BrokenPersistenceBreaker(),
        store=store,
    )

    result = router.route_text(_request())

    assert result.text == "fallback"
    assert len(result.attempts) == 2
    assert all(attempt.breaker_state == "persistence_error" for attempt in result.attempts)
    assert usage_summary(1, 20, store=store)["totals"]["live_attempts"] == 2
