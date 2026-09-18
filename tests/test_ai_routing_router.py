from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from threading import Event

import pytest

from app.services.ai_routing import budget as budget_module
from app.services.ai_routing.breaker import CircuitBreaker
from app.services.ai_routing.budget import BudgetManager, BudgetReservation
from app.services.ai_routing.contracts import (
    AnalysisStatus,
    Operation,
    ProviderErrorClass,
    RoutingRequest,
    TokenUsage,
    VisionImage,
)
from app.services.ai_routing.providers import AdapterResponse, ProviderCallError
from app.services.ai_routing.router import (
    AIRouter,
    COMPACT_BUDGET_POOL,
    compact_budget_limits,
    estimate_reservation_input_tokens,
    reserve_openai_fallback,
)
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


def _router(tmp_path, adapters, **router_kwargs):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    return (
        AIRouter(
            adapters,
            budget=BudgetManager(store),
            breaker=CircuitBreaker(store),
            store=store,
            **router_kwargs,
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
    router, store = _router(
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
    routed = RoutingRequest(**{
        **request.__dict__, 'reservation_id': permit.reservation_id,
        'reservation_owner_token': permit.owner_token,
    })
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


def test_compact_budget_pool_claims_preflight_permit_from_the_same_pool(tmp_path):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    automatic_budget = BudgetManager(store)
    compact_budget = BudgetManager(
        store,
        limits=compact_budget_limits(),
        pool=COMPACT_BUDGET_POOL,
    )
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT,
        prompt='fixture',
        run_id='compact-permit-run',
        request_id='compact-permit-request',
        json_mode=True,
        budget_pool=COMPACT_BUDGET_POOL,
    )
    permit = reserve_openai_fallback(
        request,
        budget=compact_budget,
        owner_token='compact-owner',
    )
    routed = RoutingRequest(**{
        **request.__dict__,
        'reservation_id': permit.reservation_id,
        'reservation_owner_token': permit.owner_token,
    })
    router = AIRouter(
        {
            'deepseek': FakeAdapter(
                ProviderCallError(ProviderErrorClass.AUTHENTICATION)
            ),
            'openai': FakeAdapter(_response('{"verdict":"BUY"}')),
        },
        budget=automatic_budget,
        compact_budget=compact_budget,
        breaker=CircuitBreaker(store),
        store=store,
    )

    result = router.route_text(routed)

    assert result.analysis_status is AnalysisStatus.SUCCESS_FALLBACK
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT pool, status FROM budget_reservations "
            "WHERE run_id='compact-permit-run'"
        ).fetchone()
    assert (row['pool'], row['status']) == (COMPACT_BUDGET_POOL, 'settled')


def test_compact_budget_allows_exactly_three_complete_three_stage_candidates(tmp_path):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    limits = compact_budget_limits()
    manager = BudgetManager(store, limits=limits, pool=COMPACT_BUDGET_POOL)
    operations = (
        Operation.DECISIVE_TEXT,
        Operation.BULK_TEXT,
        Operation.COMPACT_DEBATE,
    )

    permits = []
    for candidate_index in range(3):
        for operation in operations:
            permits.append(manager.reserve(
                run_id='compact-three',
                request_id=f'{candidate_index}:{operation.value}',
                operation=operation,
                input_tokens=100,
                output_tokens=768,
                owner_token=f'owner-{candidate_index}-{operation.value}',
            ))
    overflow = manager.reserve(
        run_id='compact-three',
        request_id='fourth:decisive_text',
        operation=Operation.DECISIVE_TEXT,
        input_tokens=100,
        output_tokens=768,
        owner_token='owner-fourth',
    )

    assert len(permits) == 9
    assert all(permit.approved for permit in permits)
    assert overflow.approved is False
    assert overflow.reason == 'hard_cap'
    assert limits.max_calls == 9
    assert limits.max_output_tokens >= (3 * (1200 + 768 + 768))
    assert BudgetManager(store).limits.max_calls == 5


def test_router_fails_closed_when_provider_usage_exceeds_reservation(tmp_path):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    abort = Event()
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture', run_id='breach-run',
        request_id='breach-request', json_mode=True, max_output_tokens=1,
        permit_abort_event=abort,
    )
    permit = reserve_openai_fallback(request, budget=budget, owner_token='owner-a')
    routed = RoutingRequest(**{
        **request.__dict__, 'reservation_id': permit.reservation_id,
        'reservation_owner_token': permit.owner_token,
    })
    response = AdapterResponse(
        text='{"verdict":"BUY"}', usage=TokenUsage(input_tokens=1, output_tokens=2),
    )
    router = AIRouter(
        {'deepseek': FakeAdapter(ProviderCallError(ProviderErrorClass.AUTHENTICATION)),
         'openai': FakeAdapter(response)},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )
    result = router.route_text(routed)
    assert result.analysis_status is AnalysisStatus.HOLD_REVIEW
    assert result.fallback_reason == 'reservation_breached'
    assert abort.is_set()
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM budget_reservations WHERE run_id='breach-run'"
        ).fetchone()
    assert row['status'] == 'breached'


def test_router_fails_closed_when_settlement_persistence_raises(tmp_path, monkeypatch):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture', run_id='settle-error-run',
        request_id='settle-error-request',
    )
    permit = reserve_openai_fallback(request, budget=budget, owner_token='settle-owner')
    routed = RoutingRequest(**{
        **request.__dict__, 'reservation_id': permit.reservation_id,
        'reservation_owner_token': permit.owner_token,
    })
    monkeypatch.setattr(budget, 'settle', lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('disk')))
    router = AIRouter(
        {'deepseek': FakeAdapter(ProviderCallError(ProviderErrorClass.AUTHENTICATION)),
         'openai': FakeAdapter(_response('fallback'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )

    result = router.route_text(routed)

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.HOLD_REVIEW
    assert result.fallback_reason == 'budget_finalization_failed'


def test_router_fails_closed_when_unused_permit_release_raises(tmp_path, monkeypatch):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture', run_id='release-error-run',
        request_id='release-error-request',
    )
    permit = reserve_openai_fallback(request, budget=budget, owner_token='release-owner')
    routed = RoutingRequest(**{
        **request.__dict__, 'reservation_id': permit.reservation_id,
        'reservation_owner_token': permit.owner_token,
    })
    monkeypatch.setattr(
        budget, 'release_claimed',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('locked')),
    )
    router = AIRouter(
        {'deepseek': FakeAdapter(_response('primary')),
         'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )

    result = router.route_text(routed)

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.HOLD_REVIEW
    assert result.fallback_reason == 'budget_finalization_failed'


def test_budget_finalization_base_exception_completes_single_flight_before_reraise(
    tmp_path, monkeypatch,
):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    deepseek = FakeAdapter(_response('primary result'))
    router = AIRouter(
        {'deepseek': deepseek, 'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
        single_flight_wait_seconds=0.01,
    )
    request = RoutingRequest(
        operation=Operation.BULK_TEXT,
        prompt='bounded fixture prompt',
        run_id='finalizer-fatal-run', request_id='finalizer-fatal-request',
    )
    monkeypatch.setattr(
        budget,
        'release_claimed',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            KeyboardInterrupt('finalizer interrupted')
        ),
    )

    with pytest.raises(KeyboardInterrupt, match='finalizer interrupted'):
        router.route_text(request)
    replay = router.route_text(request)

    assert replay.analysis_status is not AnalysisStatus.IN_PROGRESS
    assert replay.text is None
    assert replay.fallback_reason == 'budget_finalization_failed'
    assert deepseek.calls == 1


def test_router_fails_closed_before_provider_when_permit_renewal_persistence_fails(
    tmp_path, monkeypatch,
):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    abort = Event()
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture', run_id='renew-error-run',
        request_id='renew-error-request', permit_abort_event=abort,
    )
    permit = reserve_openai_fallback(request, budget=budget, owner_token='renew-owner')
    routed = RoutingRequest(**{
        **request.__dict__, 'reservation_id': permit.reservation_id,
        'reservation_owner_token': permit.owner_token,
    })
    deepseek = FakeAdapter(_response('primary must not run'))
    openai = FakeAdapter(_response('fallback must not run'))
    monkeypatch.setattr(
        budget, 'renew',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('locked')),
    )
    router = AIRouter(
        {'deepseek': deepseek, 'openai': openai},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )

    result = router.route_text(routed)

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.HOLD_REVIEW
    assert result.fallback_reason == 'permit_renewal_failed'
    assert deepseek.calls == 0 and openai.calls == 0
    assert abort.is_set()


def test_preflight_claim_rejection_aborts_batch_with_specific_reason(
    tmp_path, monkeypatch,
):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    abort = Event()
    monkeypatch.setattr(
        budget,
        'claim',
        lambda *_args, **_kwargs: BudgetReservation(
            False, reservation_id='expired-permit',
            reason='permit_billing_day_expired',
        ),
    )
    deepseek = FakeAdapter(_response('must not run'))
    router = AIRouter(
        {'deepseek': deepseek, 'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture',
        run_id='claim-failed-run', request_id='claim-failed-request',
        reservation_id='expired-permit', reservation_owner_token='owner',
        permit_abort_event=abort,
    )

    result = router.route_text(request)

    assert result.text is None
    assert result.fallback_reason == 'permit_billing_day_expired'
    assert abort.is_set()
    assert deepseek.calls == 0


def test_router_does_not_use_terminalized_preflight_permit(tmp_path, monkeypatch):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT, prompt='fixture', run_id='terminal-run',
        request_id='terminal-request',
    )
    permit = reserve_openai_fallback(request, budget=budget, owner_token='terminal-owner')
    routed = RoutingRequest(**{
        **request.__dict__, 'reservation_id': permit.reservation_id,
        'reservation_owner_token': permit.owner_token,
    })
    original_claim = budget.claim

    def terminalizing_claim(*args, **kwargs):
        claimed = original_claim(*args, **kwargs)
        assert claimed.approved
        assert budget.release_claimed(claimed.reservation_id)
        return claimed

    monkeypatch.setattr(budget, 'claim', terminalizing_claim)
    deepseek = FakeAdapter(_response('must not run'))
    router = AIRouter(
        {'deepseek': deepseek, 'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )

    result = router.route_text(routed)

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.HOLD_REVIEW
    assert result.fallback_reason == 'permit_renewal_failed'
    assert deepseek.calls == 0


def test_router_claims_and_heartbeats_internal_permit_while_provider_is_active(
    tmp_path, monkeypatch,
):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    heartbeat_seen = Event()
    renewals = []
    original_renew = budget.renew

    def renew(reservation_id, *, owner_token=None):
        renewals.append((reservation_id, owner_token))
        result = original_renew(reservation_id, owner_token=owner_token)
        if len(renewals) >= 2:
            heartbeat_seen.set()
        return result

    monkeypatch.setattr(budget, 'renew', renew)
    monkeypatch.setattr(router_module, 'openai_permit_heartbeat_seconds', lambda: 0.01)
    observed_statuses = []

    class BlockingAdapter:
        endpoint = 'fake.generate'

        def generate(self, request, *, model, max_output_tokens):
            with store.transaction() as connection:
                row = connection.execute(
                    "SELECT status FROM budget_reservations WHERE run_id=? AND request_id=?",
                    (request.run_id, request.request_id),
                ).fetchone()
            observed_statuses.append(row['status'])
            assert heartbeat_seen.wait(timeout=0.5)
            return _response('primary')

    router = AIRouter(
        {'deepseek': BlockingAdapter(), 'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )

    result = router.route_text(_request(Operation.BULK_TEXT))

    assert result.text == 'primary'
    assert observed_statuses == ['claimed']
    assert len(renewals) >= 2
    assert all(reservation_id and owner for reservation_id, owner in renewals)
    with store.transaction() as connection:
        status = connection.execute(
            "SELECT status FROM budget_reservations WHERE run_id='run-1' "
            "AND request_id='request-1'",
        ).fetchone()['status']
    assert status == 'released'


def test_internal_permit_heartbeat_failure_discards_provider_success(
    tmp_path, monkeypatch,
):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    heartbeat_failed = Event()
    renew_calls = 0
    original_renew = budget.renew

    def renew(reservation_id, *, owner_token=None):
        nonlocal renew_calls
        renew_calls += 1
        if renew_calls == 1:
            return original_renew(reservation_id, owner_token=owner_token)
        heartbeat_failed.set()
        raise OSError('renew store unavailable')

    monkeypatch.setattr(budget, 'renew', renew)
    monkeypatch.setattr(router_module, 'openai_permit_heartbeat_seconds', lambda: 0.01)
    abort = Event()
    abort_seen_while_active = []

    class BlockingAdapter:
        endpoint = 'fake.generate'

        def generate(self, request, *, model, max_output_tokens):
            assert heartbeat_failed.wait(timeout=0.5)
            abort_seen_while_active.append(abort.wait(timeout=0.5))
            return _response('must be discarded')

    router = AIRouter(
        {'deepseek': BlockingAdapter(), 'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )

    request = RoutingRequest(**{
        **_request(Operation.BULK_TEXT).__dict__, 'permit_abort_event': abort,
    })
    result = router.route_text(request)

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.DEGRADED
    assert result.fallback_reason == 'permit_renewal_failed'
    assert renew_calls >= 2
    assert abort.is_set()
    assert abort_seen_while_active == [True]


def test_heartbeat_failure_during_breaker_check_blocks_provider_call(
    tmp_path, monkeypatch,
):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    heartbeat_failed = Event()
    renew_calls = 0
    original_renew = budget.renew

    def renew(reservation_id, *, owner_token=None):
        nonlocal renew_calls
        renew_calls += 1
        if renew_calls == 1:
            return original_renew(reservation_id, owner_token=owner_token)
        heartbeat_failed.set()
        raise OSError('renew store unavailable')

    monkeypatch.setattr(budget, 'renew', renew)
    monkeypatch.setattr(router_module, 'openai_permit_heartbeat_seconds', lambda: 0.01)
    breaker = CircuitBreaker(store)

    def allow(*_args, **_kwargs):
        assert heartbeat_failed.wait(timeout=0.5)
        finalizer = router_module._ACTIVE_BUDGET.get()
        assert finalizer is not None and finalizer.heartbeat is not None
        assert finalizer.heartbeat.failed.wait(timeout=0.5)
        return True

    monkeypatch.setattr(breaker, 'allow', allow)
    deepseek = FakeAdapter(_response('must not be called'))
    router = AIRouter(
        {'deepseek': deepseek, 'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=breaker, store=store,
    )

    result = router.route_text(_request(Operation.BULK_TEXT))

    assert result.text is None
    assert result.fallback_reason == 'permit_renewal_failed'
    assert deepseek.calls == 0


def test_internal_permit_heartbeat_start_failure_releases_claim(tmp_path, monkeypatch):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)

    class StartFailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError('thread unavailable')

        def join(self, timeout=None):
            raise AssertionError('an unstarted thread must not be joined')

        def is_alive(self):
            return False

    monkeypatch.setattr(router_module, 'Thread', StartFailingThread)
    deepseek = FakeAdapter(_response('must not run'))
    router = AIRouter(
        {'deepseek': deepseek, 'openai': FakeAdapter(_response('unused'))},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )

    result = router.route_text(_request(Operation.BULK_TEXT))

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.DEGRADED
    assert result.fallback_reason == 'permit_renewal_failed'
    assert deepseek.calls == 0
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM budget_reservations WHERE run_id='run-1' "
            "AND request_id='request-1'",
        ).fetchone()
    assert row['status'] == 'released'


def test_batch_abort_during_primary_blocks_openai_fallback(tmp_path):
    abort = Event()

    class AbortingPrimary:
        endpoint = 'fake.generate'

        def generate(self, request, *, model, max_output_tokens):
            abort.set()
            raise ProviderCallError(ProviderErrorClass.AUTHENTICATION)

    openai = FakeAdapter(_response('must not be called'))
    router, store = _router(tmp_path, {
        'deepseek': AbortingPrimary(), 'openai': openai,
    })
    request = RoutingRequest(
        operation=Operation.BULK_TEXT,
        prompt='bounded fixture prompt',
        run_id='abort-run', request_id='abort-request',
        permit_abort_event=abort,
    )

    result = router.route_text(request)

    assert result.text is None
    assert result.analysis_status is AnalysisStatus.DEGRADED
    assert result.fallback_reason == 'permit_lease_renewal_failed'
    assert openai.calls == 0
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM budget_reservations WHERE run_id='abort-run'",
        ).fetchone()
    assert row['status'] == 'released'


def test_openai_fallback_revalidates_permit_after_utc_billing_day_rollover(
    tmp_path, monkeypatch,
):
    now = {'value': datetime(2026, 9, 3, 23, 59, 50, tzinfo=timezone.utc)}
    monkeypatch.setenv('AI_OPENAI_PERMIT_LEASE_SECONDS', '60')
    monkeypatch.setattr(budget_module, '_utc_now_datetime', lambda: now['value'])
    monkeypatch.setattr(router_module, 'openai_permit_heartbeat_seconds', lambda: 30.0)
    abort = Event()

    class CrossDayPrimary:
        endpoint = 'fake.generate'

        def generate(self, request, *, model, max_output_tokens):
            now['value'] = datetime(2026, 9, 4, 0, 0, 5, tzinfo=timezone.utc)
            raise ProviderCallError(ProviderErrorClass.AUTHENTICATION)

    openai = FakeAdapter(_response('must not be called'))
    router, store = _router(tmp_path, {
        'deepseek': CrossDayPrimary(), 'openai': openai,
    })
    request = RoutingRequest(
        operation=Operation.BULK_TEXT,
        prompt='bounded fixture prompt',
        run_id='cross-day-run', request_id='cross-day-request',
        permit_abort_event=abort,
    )

    result = router.route_text(request)

    assert result.text is None
    assert result.fallback_reason == 'permit_renewal_failed'
    assert openai.calls == 0
    assert abort.is_set()
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM budget_reservations WHERE run_id='cross-day-run'",
        ).fetchone()
    assert row['status'] == 'released'


def test_openai_dispatch_rechecks_abort_after_synchronous_permit_renewal(
    tmp_path, monkeypatch,
):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    abort = Event()
    renew_calls = 0
    original_renew = budget.renew

    def aborting_renew(reservation_id, *, owner_token=None):
        nonlocal renew_calls
        renew_calls += 1
        renewed = original_renew(reservation_id, owner_token=owner_token)
        if renew_calls == 2:
            abort.set()
        return renewed

    monkeypatch.setattr(budget, 'renew', aborting_renew)
    monkeypatch.setattr(router_module, 'openai_permit_heartbeat_seconds', lambda: 30.0)
    deepseek = FakeAdapter(
        ProviderCallError(ProviderErrorClass.AUTHENTICATION),
    )
    openai = FakeAdapter(_response('must not be called'))
    router = AIRouter(
        {'deepseek': deepseek, 'openai': openai},
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )
    request = RoutingRequest(
        operation=Operation.BULK_TEXT,
        prompt='bounded fixture prompt',
        run_id='renew-abort-run', request_id='renew-abort-request',
        permit_abort_event=abort,
    )

    result = router.route_text(request)

    assert result.text is None
    assert result.fallback_reason == 'permit_lease_renewal_failed'
    assert openai.calls == 0
    assert abort.is_set()


def test_batch_abort_before_claim_never_reserves_or_calls_provider(tmp_path):
    abort = Event()
    abort.set()
    deepseek = FakeAdapter(_response('must not be called'))
    openai = FakeAdapter(_response('must not be called'))
    router, store = _router(tmp_path, {'deepseek': deepseek, 'openai': openai})
    request = RoutingRequest(
        operation=Operation.BULK_TEXT,
        prompt='bounded fixture prompt',
        run_id='pre-abort-run', request_id='pre-abort-request',
        permit_abort_event=abort,
    )

    result = router.route_text(request)

    assert result.text is None
    assert result.fallback_reason == 'permit_lease_renewal_failed'
    assert deepseek.calls == 0 and openai.calls == 0
    with store.transaction() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM budget_reservations WHERE run_id='pre-abort-run'",
        ).fetchone()[0]
    assert count == 0


def test_openai_dispatch_base_exception_is_accounted_and_re_raised(tmp_path):
    class FatalOpenAI:
        endpoint = 'fake.generate'
        calls = 0

        def generate(self, request, *, model, max_output_tokens):
            self.calls += 1
            raise KeyboardInterrupt('cancelled after dispatch')

    store = RoutingStore(tmp_path / 'usage.sqlite3')
    budget = BudgetManager(store)
    openai = FatalOpenAI()
    router = AIRouter(
        {
            'deepseek': FakeAdapter(
                ProviderCallError(ProviderErrorClass.AUTHENTICATION),
            ),
            'openai': openai,
        },
        budget=budget, breaker=CircuitBreaker(store), store=store,
    )
    request = RoutingRequest(
        operation=Operation.DECISIVE_TEXT,
        prompt='bounded fixture prompt',
        run_id='fatal-run', request_id='fatal-request',
    )

    with pytest.raises(KeyboardInterrupt, match='cancelled after dispatch'):
        router.route_text(request)

    assert openai.calls == 1
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT status,actual_calls FROM budget_reservations "
            "WHERE run_id='fatal-run'",
        ).fetchone()
    assert tuple(row) == ('settled', 1)
    replay = router.route_text(request)
    assert replay.analysis_status is not AnalysisStatus.IN_PROGRESS
    assert openai.calls == 1


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


def test_three_hop_vision_records_immediate_predecessor_and_reason(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-verified")
    policy_now = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)
    vision_attestation = {
        "provider": "deepseek",
        "endpoint": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-vision-verified",
        "modality": "vision",
        "checked_at": "2026-09-03T02:59:30+00:00",
        "ttl_seconds": 300,
        "capable": True,
        "healthy": True,
    }
    auth = ProviderCallError(ProviderErrorClass.AUTHENTICATION)
    router, store = _router(
        tmp_path,
        {
            "gemini": FakeAdapter(auth),
            "deepseek": FakeAdapter(auth),
            "openai": FakeAdapter(_response('{"signal":"HOLD"}')),
        },
        vision_attestation=vision_attestation,
        policy_clock=lambda: policy_now,
    )
    request = RoutingRequest(
        operation=Operation.VISION,
        prompt="chart",
        run_id="three-hop",
        request_id="three-hop:1",
        images=(VisionImage(data=b"png"),),
        json_mode=True,
    )

    result = router.route_vision(request)

    assert result.fallback_reason is ProviderErrorClass.AUTHENTICATION
    assert [attempt.provider for attempt in result.attempts] == [
        "gemini",
        "deepseek",
        "openai",
    ]
    assert [attempt.fallback_from for attempt in result.attempts] == [
        None,
        "gemini",
        "deepseek",
    ]
    assert [attempt.fallback_reason for attempt in result.attempts] == [
        None,
        ProviderErrorClass.AUTHENTICATION,
        ProviderErrorClass.AUTHENTICATION,
    ]
    with store.transaction() as connection:
        persisted = connection.execute(
            "SELECT provider, fallback_from, fallback_reason "
            "FROM provider_attempts WHERE request_id=? ORDER BY attempt_number",
            ("three-hop:1",),
        ).fetchall()
    assert [tuple(row) for row in persisted] == [
        ("gemini", None, None),
        ("deepseek", "gemini", "authentication"),
        ("openai", "deepseek", "authentication"),
    ]


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


def test_request_can_disable_primary_retry_for_cost_bounded_vision(tmp_path):
    gemini = FakeAdapter(ProviderCallError(ProviderErrorClass.RATE_LIMIT))
    openai = FakeAdapter(_response('{"signal":"HOLD"}'))
    router, _store = _router(tmp_path, {"gemini": gemini, "openai": openai})
    request = RoutingRequest(
        operation=Operation.VISION,
        prompt="bounded chart",
        run_id="vision-no-retry",
        request_id="vision-no-retry:1",
        json_mode=True,
        images=(VisionImage(data=b"x", width_px=1, height_px=1),),
        max_primary_attempts=1,
    )

    result = router.route_vision(request)

    assert result.actual_provider == "openai"
    assert gemini.calls == 1
    assert openai.calls == 1


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
