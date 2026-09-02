from concurrent.futures import ThreadPoolExecutor

from app.services.ai_routing.budget import BudgetLimits, BudgetManager
from app.services.ai_routing.contracts import Operation, TokenUsage
from app.services.ai_routing.store import RoutingStore


def _manager(tmp_path, limits=None):
    return BudgetManager(RoutingStore(tmp_path / "usage.sqlite3"), limits=limits)


def test_default_openai_automatic_run_caps(tmp_path):
    manager = _manager(tmp_path)

    assert manager.limits.max_calls == 5
    assert manager.limits.max_input_tokens == 30_000
    assert manager.limits.max_output_tokens == 6_000


def test_two_concurrent_reservations_cannot_spend_same_remaining_capacity(tmp_path):
    manager = _manager(
        tmp_path,
        BudgetLimits(max_calls=1, max_input_tokens=100, max_output_tokens=100),
    )

    def reserve(index):
        return manager.reserve(
            run_id="run-1",
            request_id=f"request-{index}",
            operation=Operation.DECISIVE_TEXT,
            input_tokens=100,
            output_tokens=100,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservations = list(executor.map(reserve, (1, 2)))

    assert sum(item.approved for item in reservations) == 1
    assert manager.snapshot("run-1").used_calls == 1


def test_low_priority_is_rejected_at_eighty_percent(tmp_path):
    manager = _manager(
        tmp_path,
        BudgetLimits(max_calls=5, max_input_tokens=1_000, max_output_tokens=1_000),
    )
    for index in range(4):
        assert manager.reserve(
            run_id="run-1",
            request_id=f"decisive-{index}",
            operation=Operation.DECISIVE_TEXT,
            input_tokens=100,
            output_tokens=100,
        ).approved

    denied = manager.reserve(
        run_id="run-1",
        request_id="bulk-1",
        operation=Operation.BULK_TEXT,
        input_tokens=10,
        output_tokens=10,
    )

    assert denied.approved is False
    assert denied.reason == "priority_reserve"


def test_decisive_can_use_capacity_reserved_from_vision_and_bulk(tmp_path):
    manager = _manager(
        tmp_path,
        BudgetLimits(max_calls=5, max_input_tokens=1_000, max_output_tokens=1_000),
    )
    for index in range(4):
        manager.reserve(
            run_id="run-1",
            request_id=f"seed-{index}",
            operation=Operation.DECISIVE_TEXT,
            input_tokens=100,
            output_tokens=100,
        )

    decisive = manager.reserve(
        run_id="run-1",
        request_id="last-decisive",
        operation=Operation.DECISIVE_TEXT,
        input_tokens=100,
        output_tokens=100,
    )

    assert decisive.approved is True


def test_settlement_releases_unused_reserved_tokens(tmp_path):
    manager = _manager(
        tmp_path,
        BudgetLimits(max_calls=5, max_input_tokens=1_000, max_output_tokens=1_000),
    )
    reservation = manager.reserve(
        run_id="run-1",
        request_id="request-1",
        operation=Operation.DECISIVE_TEXT,
        input_tokens=600,
        output_tokens=500,
    )

    manager.settle(
        reservation.reservation_id,
        TokenUsage(input_tokens=250, cached_input_tokens=0, output_tokens=100),
    )

    snapshot = manager.snapshot("run-1")
    assert snapshot.used_input_tokens == 250
    assert snapshot.used_output_tokens == 100
    assert snapshot.remaining_input_tokens == 750
    assert snapshot.remaining_output_tokens == 900

