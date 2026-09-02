from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

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


def test_daily_cost_cap_is_atomic_across_run_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_OPENAI_DAILY_BUDGET_USD", "0.05")
    manager = _manager(tmp_path)

    def reserve(index):
        return manager.reserve(
            run_id=f"run-{index}",
            request_id=f"request-{index}",
            operation=Operation.DECISIVE_TEXT,
            input_tokens=100,
            output_tokens=100,
            estimated_cost_usd=Decimal("0.03"),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservations = list(executor.map(reserve, (1, 2)))

    assert sum(item.approved for item in reservations) == 1
    assert {item.reason for item in reservations if not item.approved} == {"daily_hard_cap"}


def test_daily_cost_cap_fails_closed_when_reservation_price_is_unknown(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_OPENAI_DAILY_BUDGET_USD", "1.00")
    manager = _manager(tmp_path)

    reservation = manager.reserve(
        run_id="run-unknown",
        request_id="request-unknown",
        operation=Operation.DECISIVE_TEXT,
        input_tokens=100,
        output_tokens=100,
        estimated_cost_usd=None,
    )

    assert reservation.approved is False
    assert reservation.reason == "daily_cost_unknown"


def test_daily_settlement_releases_unused_reserved_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_OPENAI_DAILY_BUDGET_USD", "0.05")
    manager = _manager(tmp_path)
    first = manager.reserve(
        run_id="run-one",
        request_id="request-one",
        operation=Operation.DECISIVE_TEXT,
        input_tokens=100,
        output_tokens=100,
        estimated_cost_usd=Decimal("0.04"),
    )
    manager.settle(
        first.reservation_id,
        TokenUsage(input_tokens=10, output_tokens=10),
        actual_cost_usd=Decimal("0.01"),
    )

    second = manager.reserve(
        run_id="run-two",
        request_id="request-two",
        operation=Operation.DECISIVE_TEXT,
        input_tokens=100,
        output_tokens=100,
        estimated_cost_usd=Decimal("0.04"),
    )

    assert first.approved is True
    assert second.approved is True


def test_only_router_claim_can_convert_reserved_permit_to_spendable(tmp_path):
    manager = _manager(tmp_path)
    reserved = manager.reserve(
        run_id='run-claim', request_id='request-claim',
        operation=Operation.DECISIVE_TEXT, input_tokens=100, output_tokens=100,
    )
    claimed = manager.claim(
        reserved.reservation_id, run_id='run-claim', request_id='request-claim',
        owner_token=reserved.owner_token, input_tokens=100, output_tokens=100,
    )
    duplicate = manager.claim(
        reserved.reservation_id, run_id='run-claim', request_id='request-claim',
        owner_token=reserved.owner_token, input_tokens=100, output_tokens=100,
    )
    assert claimed.approved and claimed.acquired_by_caller
    assert duplicate.approved is False and duplicate.reason == 'permit_already_claimed'


def test_preflight_owner_cannot_release_peer_or_claimed_permit(tmp_path):
    manager = _manager(tmp_path)
    reserved = manager.reserve(
        run_id='owned-run', request_id='owned-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-a',
    )
    peer = manager.reserve(
        run_id='owned-run', request_id='owned-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-b',
    )
    assert reserved.approved and reserved.acquired_by_caller
    assert peer.approved is False and peer.reason == 'permit_in_use'
    assert manager.release(reserved.reservation_id, owner_token='owner-b') is False
    claimed = manager.claim(
        reserved.reservation_id, run_id='owned-run', request_id='owned-request',
        owner_token='owner-a', input_tokens=100, output_tokens=100,
    )
    assert claimed.approved
    assert manager.release(reserved.reservation_id, owner_token='owner-a') is False
    manager.settle(reserved.reservation_id, TokenUsage(input_tokens=50, output_tokens=50))
    resumed = manager.reserve(
        run_id='owned-run', request_id='owned-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-a',
    )
    assert resumed.approved is False and resumed.reason == 'already_settled'


def test_released_stable_request_can_be_reacquired_by_new_owner(tmp_path):
    manager = _manager(tmp_path)
    first = manager.reserve(
        run_id='resume-run', request_id='resume-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-a',
    )
    assert manager.release(first.reservation_id, owner_token='owner-a') is True
    second = manager.reserve(
        run_id='resume-run', request_id='resume-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=90, output_tokens=90, owner_token='owner-b',
    )
    assert second.approved and second.acquired_by_caller and second.owner_token == 'owner-b'


def test_released_resume_rechecks_current_run_capacity(tmp_path):
    manager = _manager(
        tmp_path, BudgetLimits(max_calls=1, max_input_tokens=100, max_output_tokens=100),
    )
    first = manager.reserve(
        run_id='resume-cap', request_id='stable-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-a',
    )
    assert manager.release(first.reservation_id, owner_token='owner-a') is True
    assert manager.reserve(
        run_id='resume-cap', request_id='other-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-peer',
    ).approved

    resumed = manager.reserve(
        run_id='resume-cap', request_id='stable-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-b',
    )

    assert resumed.approved is False
    assert resumed.reason == 'hard_cap'


def test_claim_and_settlement_fail_closed_above_reserved_bound(tmp_path):
    manager = _manager(tmp_path)
    first = manager.reserve(
        run_id='bound-run', request_id='bound-request', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-a',
    )
    claim = manager.claim(
        first.reservation_id, run_id='bound-run', request_id='bound-request',
        owner_token='owner-a', input_tokens=101, output_tokens=100,
    )
    assert claim.approved is False and claim.reason == 'permit_bound_exceeded'

    second = manager.reserve(
        run_id='bound-run', request_id='bound-request-2', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, owner_token='owner-b',
    )
    assert manager.claim(
        second.reservation_id, run_id='bound-run', request_id='bound-request-2',
        owner_token='owner-b', input_tokens=100, output_tokens=100,
    ).approved
    assert manager.settle(
        second.reservation_id, TokenUsage(input_tokens=101, output_tokens=100),
    ) is False
    with manager.store.transaction() as connection:
        status = connection.execute(
            'SELECT status FROM budget_reservations WHERE reservation_id=?',
            (second.reservation_id,),
        ).fetchone()['status']
    assert status == 'breached'
    snapshot = manager.snapshot('bound-run')
    assert snapshot.used_input_tokens == 201
    assert snapshot.remaining_input_tokens == manager.limits.max_input_tokens - 201

    third = manager.reserve(
        run_id='bound-run', request_id='bound-request-3', operation=Operation.DECISIVE_TEXT,
        input_tokens=100, output_tokens=100, calls=1, owner_token='owner-c',
    )
    assert manager.claim(
        third.reservation_id, run_id='bound-run', request_id='bound-request-3',
        owner_token='owner-c', input_tokens=100, output_tokens=100,
    ).approved
    assert manager.settle(
        third.reservation_id, TokenUsage(input_tokens=100, output_tokens=100), calls=2,
    ) is False
