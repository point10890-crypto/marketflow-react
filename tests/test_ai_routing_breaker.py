from app.services.ai_routing.breaker import CircuitBreaker
from app.services.ai_routing.contracts import ProviderErrorClass
from app.services.ai_routing.store import RoutingStore


class Clock:
    def __init__(self):
        self.value = 1_000.0

    def __call__(self):
        return self.value


def _breaker(tmp_path, *, threshold=3, cooldown=60):
    clock = Clock()
    breaker = CircuitBreaker(
        RoutingStore(tmp_path / "usage.sqlite3"),
        failure_threshold=threshold,
        cooldown_seconds=cooldown,
        clock=clock,
    )
    return breaker, clock


def test_auth_and_balance_failures_open_immediately(tmp_path):
    breaker, _clock = _breaker(tmp_path)

    for provider, error in (
        ("deepseek", ProviderErrorClass.AUTHENTICATION),
        ("openai", ProviderErrorClass.INSUFFICIENT_BALANCE),
    ):
        breaker.record_failure(provider, "text", "decisive", error)
        assert breaker.state(provider, "text", "decisive") == "open"
        assert breaker.allow(provider, "text", "decisive") is False


def test_transient_failures_open_only_at_threshold(tmp_path):
    breaker, _clock = _breaker(tmp_path, threshold=3)

    for error in (ProviderErrorClass.RATE_LIMIT, ProviderErrorClass.TIMEOUT):
        breaker.record_failure("deepseek", "text", "fast", error)
        assert breaker.state("deepseek", "text", "fast") == "closed"

    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.SERVER_ERROR)
    assert breaker.state("deepseek", "text", "fast") == "open"


def test_validation_failures_do_not_open_breaker(tmp_path):
    breaker, _clock = _breaker(tmp_path, threshold=1)

    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.INVALID_JSON)
    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.NUMERIC_MISMATCH)

    assert breaker.state("deepseek", "text", "fast") == "closed"


def test_text_and_vision_state_are_independent(tmp_path):
    breaker, _clock = _breaker(tmp_path)

    breaker.record_failure("gemini", "vision", "fast", ProviderErrorClass.AUTHENTICATION)

    assert breaker.state("gemini", "vision", "fast") == "open"
    assert breaker.state("gemini", "text", "fast") == "closed"


def test_only_one_half_open_probe_is_admitted_after_cooldown(tmp_path):
    breaker, clock = _breaker(tmp_path, cooldown=60)
    breaker.record_failure("deepseek", "text", "decisive", ProviderErrorClass.AUTHENTICATION)
    clock.value += 61

    assert breaker.allow("deepseek", "text", "decisive") is True
    assert breaker.state("deepseek", "text", "decisive") == "half_open"
    assert breaker.allow("deepseek", "text", "decisive") is False

    breaker.record_success("deepseek", "text", "decisive")
    assert breaker.state("deepseek", "text", "decisive") == "closed"
