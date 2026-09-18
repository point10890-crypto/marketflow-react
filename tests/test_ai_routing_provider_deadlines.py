import pytest
import httpx
import openai

from app.services.ai_routing.breaker import CircuitBreaker
from app.services.ai_routing.contracts import Operation, ProviderErrorClass, RoutingRequest
from app.services.ai_routing.providers import (
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    build_default_adapters,
    classify_exception,
    ProviderCallError,
)
from app.services.ai_routing.router import AIRouter
from app.services.ai_routing.store import RoutingStore


def test_gemini_adapter_has_finite_deadline_below_default_probe_lease():
    adapters = build_default_adapters()

    assert adapters["gemini"].request_timeout_seconds == GEMINI_REQUEST_TIMEOUT_SECONDS
    assert 0 < GEMINI_REQUEST_TIMEOUT_SECONDS < CircuitBreaker.DEFAULT_PROBE_LEASE_SECONDS
    assert MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS == 90


def test_router_rejects_adapter_deadline_not_covered_by_breaker_lease(tmp_path):
    class TooSlowAdapter:
        endpoint = "fake.generate"
        request_timeout_seconds = 121

        def generate(self, request, *, model, max_output_tokens):
            raise AssertionError("must not run")

    store = RoutingStore(tmp_path / "usage.sqlite3")

    with pytest.raises(ValueError, match="probe lease"):
        AIRouter({"deepseek": TooSlowAdapter()}, store=store)


def test_openai_compatible_factories_disable_sdk_internal_retries(monkeypatch):
    constructor_kwargs = []

    class ConstructorOnlyClient:
        def __init__(self, **kwargs):
            constructor_kwargs.append(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr(openai, "OpenAI", ConstructorOnlyClient)

    adapters = build_default_adapters()
    adapters["openai"].client_factory()
    adapters["deepseek"].client_factory()

    assert [kwargs["max_retries"] for kwargs in constructor_kwargs] == [0, 0]


def test_one_adapter_invocation_sends_once_on_retryable_transport_response(monkeypatch):
    sends = 0

    def retryable_response(request):
        nonlocal sends
        sends += 1
        return httpx.Response(
            500,
            request=request,
            json={"error": {"message": "retryable", "type": "server_error"}},
        )

    transport = httpx.MockTransport(retryable_response)
    real_openai = openai.OpenAI

    def safe_openai(**kwargs):
        return real_openai(
            **kwargs,
            base_url="https://unit.test/v1",
            http_client=httpx.Client(transport=transport),
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(openai, "OpenAI", safe_openai)
    adapter = build_default_adapters()["openai"]

    with pytest.raises(ProviderCallError):
        adapter.generate(
            RoutingRequest(operation=Operation.DECISIVE_TEXT, prompt="fixture"),
            model="gpt-5.5",
            max_output_tokens=10,
        )

    assert sends == 1


def test_http_402_classifies_as_secret_free_insufficient_balance():
    class BillingFailure(RuntimeError):
        status_code = 402

    failure = BillingFailure("Authorization: Bearer must-not-leak")

    assert classify_exception(failure) is ProviderErrorClass.INSUFFICIENT_BALANCE
