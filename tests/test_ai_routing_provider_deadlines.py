import pytest

from app.services.ai_routing.breaker import CircuitBreaker
from app.services.ai_routing.providers import (
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    build_default_adapters,
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
