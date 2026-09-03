import pytest

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


@pytest.mark.parametrize(
    "error_class",
    (
        ProviderErrorClass.INVALID_JSON,
        ProviderErrorClass.NUMERIC_MISMATCH,
        ProviderErrorClass.EMPTY,
        ProviderErrorClass.REFUSAL,
    ),
)
def test_non_breaking_validation_failure_completes_half_open_probe(
    tmp_path, error_class
):
    breaker, _clock = _breaker(tmp_path, threshold=1)
    breaker.record_failure(
        "deepseek", "text", "fast", ProviderErrorClass.AUTHENTICATION
    )
    _clock.value += 61
    assert breaker.allow("deepseek", "text", "fast") is True
    assert breaker.state("deepseek", "text", "fast") == "half_open"

    breaker.record_failure("deepseek", "text", "fast", error_class)

    assert breaker.state("deepseek", "text", "fast") == "closed"
    assert breaker.allow("deepseek", "text", "fast") is True


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


def test_stale_half_open_probe_lease_can_be_reclaimed_once(tmp_path):
    clock = Clock()
    breaker = CircuitBreaker(
        RoutingStore(tmp_path / "usage.sqlite3"),
        cooldown_seconds=10,
        probe_lease_seconds=5,
        max_provider_deadline_seconds=1,
        probe_margin_seconds=1,
        clock=clock,
    )
    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.AUTHENTICATION)
    clock.value += 11
    assert breaker.allow("deepseek", "text", "fast") is True
    assert breaker.allow("deepseek", "text", "fast") is False

    clock.value += 6
    assert breaker.allow("deepseek", "text", "fast") is True
    assert breaker.allow("deepseek", "text", "fast") is False


def test_default_probe_lease_exceeds_ninety_second_provider_deadline(tmp_path):
    clock = Clock()
    breaker = CircuitBreaker(
        RoutingStore(tmp_path / "usage.sqlite3"), cooldown_seconds=10, clock=clock
    )
    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.AUTHENTICATION)
    clock.value += 11
    assert breaker.allow("deepseek", "text", "fast") is True

    clock.value += 91
    assert breaker.allow("deepseek", "text", "fast") is False
    clock.value += 30
    assert breaker.allow("deepseek", "text", "fast") is True


def test_probe_lease_must_cover_every_adapter_deadline_plus_margin(tmp_path):
    with pytest.raises(ValueError, match="probe lease"):
        CircuitBreaker(
            RoutingStore(tmp_path / "usage.sqlite3"),
            probe_lease_seconds=119,
            max_provider_deadline_seconds=90,
            probe_margin_seconds=30,
        )


def test_transient_failure_count_resets_outside_failure_window(tmp_path):
    clock = Clock()
    breaker = CircuitBreaker(
        RoutingStore(tmp_path / "usage.sqlite3"),
        failure_threshold=2,
        failure_window_seconds=10,
        clock=clock,
    )

    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.TIMEOUT)
    clock.value += 11
    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.CONNECTION)
    assert breaker.state("deepseek", "text", "fast") == "closed"

    clock.value += 9
    breaker.record_failure("deepseek", "text", "fast", ProviderErrorClass.SERVER_ERROR)
    assert breaker.state("deepseek", "text", "fast") == "open"
