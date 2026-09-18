"""Gemini Grounding 모델 지정 테스트.

2026-08-05: gemini-2.0-flash 가 폐기(HTTP 404 "no longer available")됐는데
모델명이 하드코딩돼 있어, 전 종목의 실시간 검색 뉴스 분석이 조용히 DeepSeek
폴백으로 넘어갔다. 폴백에는 웹 검색이 없으므로 분석의 근거 자체가 달라진다.
스크리너는 이미 gemini-2.5-flash 를 쓰고 있어 멀쩡했고, 그래서 더 안 보였다.
"""
import asyncio

import pytest

from app.services.ai_routing.budget import BudgetLimits, BudgetManager, BudgetReservation
from app.services.ai_routing.store import RoutingStore
from engine import llm_analyzer as llm_analyzer_module
from engine.llm_analyzer import GeminiAnalyzer, GeminiGroundingClient, LLMAnalyzer


def test_default_model_is_not_the_retired_one():
    assert GeminiGroundingClient.DEFAULT_MODEL != 'gemini-2.0-flash'


def test_plain_gemini_analyzer_also_avoids_retired_model(monkeypatch):
    monkeypatch.delenv('GEMINI_MODEL', raising=False)
    monkeypatch.setattr(llm_analyzer_module.genai, 'Client', lambda **_kwargs: object())

    analyzer = GeminiAnalyzer(api_key='x')

    assert analyzer.model_name == 'gemini-2.5-flash'


def test_default_model_is_used_when_env_is_absent(monkeypatch):
    monkeypatch.delenv('GEMINI_GROUNDING_MODEL', raising=False)

    client = GeminiGroundingClient(api_key='x')

    assert client.model_name == GeminiGroundingClient.DEFAULT_MODEL


def test_env_overrides_the_model_without_a_code_change(monkeypatch):
    """다음 폐기 때 배포 없이 넘길 수 있어야 한다."""
    monkeypatch.setenv('GEMINI_GROUNDING_MODEL', 'gemini-9-future')

    assert GeminiGroundingClient(api_key='x').model_name == 'gemini-9-future'


def test_base_url_tracks_the_selected_model(monkeypatch):
    """모델만 바꾸고 URL 이 옛 모델을 가리키면 404 가 그대로 난다."""
    monkeypatch.setenv('GEMINI_GROUNDING_MODEL', 'gemini-9-future')

    client = GeminiGroundingClient(api_key='x')

    assert 'models/gemini-9-future:generateContent' in client.base_url


@pytest.mark.parametrize('present, absent', [
    ('GEMINI_API_KEY', 'GOOGLE_API_KEY'),
    ('GOOGLE_API_KEY', 'GEMINI_API_KEY'),
])
def test_either_key_variable_is_accepted(monkeypatch, present, absent):
    """운영에서 GOOGLE 쪽을 비우고 GEMINI 만 채운 상태로 돌고 있다."""
    monkeypatch.setenv(present, 'k')
    monkeypatch.delenv(absent, raising=False)

    assert GeminiGroundingClient().api_key == 'k'


def _payload_of(client, monkeypatch):
    """search_and_analyze 가 실제로 보내는 payload 를 가로챈다."""
    import asyncio, httpx

    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {
            'candidates': [{'content': {'parts': [
                {'text': '{"score":1,"reason":"x","themes":[],"news_summary":"y"}'}
            ]}}],
            'usageMetadata': {
                'promptTokenCount': 12,
                'candidatesTokenCount': 7,
                'thoughtsTokenCount': 0,
                'totalTokenCount': 19,
            },
        }

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            captured['url'] = url
            captured['body'] = json
            return _Resp()

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **k: _Client())
    captured['result'] = asyncio.run(client.search_and_analyze('삼성전자'))
    return captured


def test_thinking_is_disabled_so_the_json_is_not_truncated(monkeypatch):
    """실측: 예산 1024 에 사고만 1,532 토큰 -> MAX_TOKENS -> JSON 81자에서 잘림.

    이 호출은 추론이 아니라 '검색 후 구조화 추출' 이다. 사고를 켜두면 답변이
    잘리고 전 종목이 DeepSeek 폴백으로 넘어간다 — 폴백에는 검색이 없다.
    """
    cfg = _payload_of(GeminiGroundingClient(api_key='k'), monkeypatch)['body']['generationConfig']

    assert cfg['thinkingConfig']['thinkingBudget'] == 0


def test_output_budget_has_headroom_over_the_measured_need(monkeypatch):
    """사고를 끈 상태의 실측 출력이 803 토큰이었다."""
    cfg = _payload_of(GeminiGroundingClient(api_key='k'), monkeypatch)['body']['generationConfig']

    assert cfg['maxOutputTokens'] >= 2048


def test_google_search_tool_is_still_attached(monkeypatch):
    """검색이 빠지면 grounding 이 아니라 그냥 LLM 호출이 된다."""
    body = _payload_of(GeminiGroundingClient(api_key='k'), monkeypatch)['body']

    assert body['tools'] == [{'google_search': {}}]


def test_grounding_normalizes_native_usage(monkeypatch):
    result = _payload_of(GeminiGroundingClient(api_key='k'), monkeypatch)['result']

    assert result['usage'] == {
        'input_tokens': 12,
        'cached_input_tokens': 0,
        'output_tokens': 7,
        'reasoning_tokens': 0,
        'total_tokens': 19,
        'usage_estimated': False,
    }


def _install_grounding_response(monkeypatch, payload=None, *, failure=None):
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))
            if failure is not None:
                raise failure
            return _Resp()

    monkeypatch.setattr(llm_analyzer_module.httpx, 'AsyncClient', lambda **_kwargs: _Client())
    return calls


def _grounding_payload(*, usage=True):
    payload = {
        'candidates': [{
            'content': {'parts': [{
                'text': '{"score":1,"reason":"verified","themes":[]}'
            }]},
            'groundingMetadata': {
                'groundingChunks': [{'web': {'uri': 'https://example.test/news'}}]
            },
        }],
    }
    if usage:
        payload['usageMetadata'] = {
            'promptTokenCount': 12,
            'cachedContentTokenCount': 2,
            'candidatesTokenCount': 7,
            'thoughtsTokenCount': 0,
            'totalTokenCount': 19,
        }
    return payload


def _grounding_client(tmp_path, *, limits=None):
    store = RoutingStore(tmp_path / 'grounding.sqlite3')
    budget = BudgetManager(
        store,
        limits=limits or BudgetLimits(
            max_calls=5,
            max_input_tokens=50_000,
            max_output_tokens=20_000,
            low_priority_cutoff=1.0,
        ),
        pool='specialized_gemini',
        provider='gemini',
    )
    return GeminiGroundingClient(api_key='k', store=store, budget=budget), store


def _attempt_row(store):
    with store.transaction() as connection:
        return connection.execute(
            'SELECT * FROM provider_attempts ORDER BY attempt_number'
        ).fetchone()


def test_grounding_success_is_written_to_central_attempt_ledger(monkeypatch, tmp_path):
    _install_grounding_response(monkeypatch, _grounding_payload())
    client, store = _grounding_client(tmp_path)

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='jongga-run', request_id='jongga-run:005930:grounding'
    ))

    row = _attempt_row(store)
    assert row['run_id'] == 'jongga-run'
    assert row['request_id'] == 'jongga-run:005930:grounding'
    assert row['provider'] == 'gemini'
    assert row['model'] == client.model_name
    assert row['endpoint'] == 'models.generateContent:google_search'
    assert row['operation'] == 'specialized_gemini'
    assert row['status'] == 'success'
    assert row['selected'] == 1
    assert row['input_tokens'] == 12
    assert row['cached_input_tokens'] == 2
    assert row['output_tokens'] == 7
    assert row['total_tokens'] == 19
    assert row['usage_mapping_status'] == 'valid'
    assert row['estimated_cost_usd'] is not None
    assert row['error_class'] is None
    assert row['latency_ms'] >= 0
    assert result['routing']['attempt_count'] == 1
    assert result['routing']['usage_complete'] is True


def test_grounding_failure_records_unknown_usage_without_raw_error(monkeypatch, tmp_path):
    secret = 'credential-canary-must-not-escape-grounding'
    _install_grounding_response(monkeypatch, failure=TimeoutError(secret))
    client, store = _grounding_client(tmp_path)

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='jongga-run', request_id='jongga-run:005930:grounding'
    ))

    row = _attempt_row(store)
    assert row['status'] == 'failed'
    assert row['selected'] == 0
    assert row['error_class'] == 'timeout'
    assert row['input_tokens'] is None
    assert row['output_tokens'] is None
    assert row['estimated_cost_usd'] is None
    assert row['usage_mapping_status'] == 'unverified'
    assert secret not in str(dict(row))
    assert secret not in str(result)
    assert result['routing']['usage_complete'] is False


def test_grounding_budget_rejection_is_audited_without_provider_call(monkeypatch, tmp_path):
    calls = _install_grounding_response(monkeypatch, _grounding_payload())
    client, store = _grounding_client(
        tmp_path,
        limits=BudgetLimits(
            max_calls=0,
            max_input_tokens=0,
            max_output_tokens=0,
            low_priority_cutoff=1.0,
        ),
    )

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='jongga-run', request_id='jongga-run:005930:grounding'
    ))

    assert calls == []
    row = _attempt_row(store)
    assert row['status'] == 'skipped_budget'
    assert row['selected'] == 0
    assert row['input_tokens'] == 0
    assert row['output_tokens'] == 0
    assert row['error_class'] == 'budget_exhausted'
    assert result['source'] == 'none'
    assert result['reason'] == 'Grounding unavailable'
    assert result['routing']['attempt_count'] == 1
    assert result['routing']['usage_complete'] is True


def test_grounding_success_with_missing_usage_is_quarantined_as_unknown(
    monkeypatch, tmp_path
):
    _install_grounding_response(monkeypatch, _grounding_payload(usage=False))
    client, store = _grounding_client(tmp_path)

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='jongga-run', request_id='jongga-run:005930:grounding'
    ))

    row = _attempt_row(store)
    assert row['status'] == 'success'
    assert row['input_tokens'] is None
    assert row['output_tokens'] is None
    assert row['estimated_cost_usd'] is None
    assert result['routing']['usage_complete'] is False


def _attempt_rows(store):
    with store.transaction() as connection:
        return connection.execute(
            'SELECT * FROM provider_attempts ORDER BY attempt_number'
        ).fetchall()


def test_non_provider_skip_does_not_hide_later_billable_same_request(
    monkeypatch, tmp_path
):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    store = RoutingStore(tmp_path / 'grounding.sqlite3')
    budget = BudgetManager(
        store,
        limits=BudgetLimits(max_calls=5, max_input_tokens=50_000,
                            max_output_tokens=20_000, low_priority_cutoff=1.0),
        pool='specialized_gemini', provider='gemini',
    )
    skipped_client = GeminiGroundingClient(api_key='', store=store, budget=budget)
    first = asyncio.run(skipped_client.search_and_analyze(
        '삼성전자', run_id='stable-run', request_id='stable-request'
    ))
    calls = _install_grounding_response(monkeypatch, _grounding_payload())
    live_client = GeminiGroundingClient(api_key='k', store=store, budget=budget)
    second = asyncio.run(live_client.search_and_analyze(
        '삼성전자', run_id='stable-run', request_id='stable-request'
    ))

    rows = _attempt_rows(store)
    assert len(calls) == 1
    assert [(row['attempt_number'], row['status']) for row in rows] == [
        (0, 'skipped_unconfigured'),
        (1, 'success'),
    ]
    assert second['routing']['telemetry_recorded'] is True
    assert second['routing']['usage']['total_tokens'] == 19
    assert first['routing']['attempts'][0]['attempt_number'] == 0


def test_concurrent_same_request_has_one_billable_row_and_one_non_live_skip(
    monkeypatch, tmp_path
):
    client, store = _grounding_client(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return _grounding_payload()

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))
            entered.set()
            await release.wait()
            return _Resp()

    monkeypatch.setattr(llm_analyzer_module.httpx, 'AsyncClient', lambda **_kw: _Client())

    async def scenario():
        owner = asyncio.create_task(client.search_and_analyze(
            '삼성전자', run_id='concurrent-run', request_id='concurrent-request'
        ))
        await entered.wait()
        duplicate = await client.search_and_analyze(
            '삼성전자', run_id='concurrent-run', request_id='concurrent-request'
        )
        release.set()
        return await owner, duplicate

    owner, duplicate = asyncio.run(scenario())

    assert len(calls) == 1
    assert owner['routing']['analysis_status'] == 'SUCCESS_PRIMARY'
    assert duplicate['routing']['analysis_status'] == 'FAILED_TECHNICAL'
    assert [(row['attempt_number'], row['status']) for row in _attempt_rows(store)] == [
        (0, 'skipped_budget'),
        (1, 'success'),
    ]


def test_cross_run_concurrent_same_request_records_every_billable_call(
    monkeypatch, tmp_path
):
    store = RoutingStore(tmp_path / 'grounding.sqlite3')
    limits = BudgetLimits(
        max_calls=5, max_input_tokens=50_000, max_output_tokens=20_000,
        low_priority_cutoff=1.0,
    )
    clients = [
        GeminiGroundingClient(
            api_key='k',
            store=store,
            budget=BudgetManager(
                store, limits=limits, pool='specialized_gemini', provider='gemini'
            ),
        )
        for _ in range(2)
    ]
    both_dispatched = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return _grounding_payload()

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))
            if len(calls) == 2:
                both_dispatched.set()
            await release.wait()
            return _Resp()

    monkeypatch.setattr(llm_analyzer_module.httpx, 'AsyncClient', lambda **_kw: _Client())

    async def scenario():
        tasks = [
            asyncio.create_task(clients[index].search_and_analyze(
                '삼성전자', run_id=f'cross-run-{index}',
                request_id='shared-logical-request',
            ))
            for index in range(2)
        ]
        await both_dispatched.wait()
        release.set()
        return await asyncio.gather(*tasks)

    results = asyncio.run(scenario())

    rows = _attempt_rows(store)
    assert len(calls) == 2
    assert len(rows) == 2
    assert {row['run_id'] for row in rows} == {'cross-run-0', 'cross-run-1'}
    assert [row['attempt_number'] for row in rows] == [1, 2]
    assert all(row['status'] == 'success' for row in rows)
    assert all(result['routing']['telemetry_recorded'] is True for result in results)
    assert {result['routing']['attempts'][0]['attempt_number'] for result in results} == {1, 2}


@pytest.mark.parametrize('mode', ['false', 'exception'])
def test_grounding_rejects_provider_success_when_budget_settlement_fails(
    monkeypatch, tmp_path, mode
):
    canary = 'settlement-secret-must-not-escape'
    _install_grounding_response(monkeypatch, _grounding_payload())
    client, store = _grounding_client(tmp_path)
    if mode == 'false':
        monkeypatch.setattr(client.budget, 'settle', lambda *_a, **_kw: False)
    else:
        monkeypatch.setattr(
            client.budget, 'settle',
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError(canary)),
        )

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='settle-run', request_id=f'settle-{mode}'
    ))

    row = _attempt_row(store)
    with store.transaction() as connection:
        reservation = connection.execute(
            'SELECT status,actual_calls,actual_input_tokens,actual_output_tokens '
            'FROM budget_reservations WHERE request_id=?',
            (f'settle-{mode}',),
        ).fetchone()
    assert result['source'] == 'none'
    assert result['reason'] == 'Grounding unavailable'
    assert result['routing']['analysis_status'] == 'FAILED_TECHNICAL'
    assert result['routing']['fallback_reason'] == 'budget_finalization_failed'
    assert result['routing']['usage']['total_tokens'] == 19
    assert row['status'] == 'failed' and row['selected'] == 0
    assert row['total_tokens'] == 19
    assert reservation['status'] == 'breached'
    assert reservation['actual_calls'] == 1
    assert reservation['actual_input_tokens'] >= 12
    assert reservation['actual_output_tokens'] >= 7
    assert canary not in str(result) and canary not in str(dict(row))


def test_grounding_claim_exception_releases_hold_and_returns_sanitized_artifact(
    monkeypatch, tmp_path
):
    canary = 'claim-secret-must-not-escape'
    calls = _install_grounding_response(monkeypatch, _grounding_payload())
    client, store = _grounding_client(tmp_path)
    monkeypatch.setattr(
        client.budget, 'claim',
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError(canary)),
    )

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='claim-error-run', request_id='claim-error-request'
    ))

    assert calls == []
    assert result['source'] == 'none'
    assert result['reason'] == 'Grounding unavailable'
    assert result['routing']['analysis_status'] == 'FAILED_TECHNICAL'
    assert result['routing']['fallback_reason'] == 'budget_claim_failed'
    assert canary not in str(result)
    with store.transaction() as connection:
        reservation = connection.execute(
            'SELECT status FROM budget_reservations WHERE request_id=?',
            ('claim-error-request',),
        ).fetchone()
    assert reservation['status'] == 'released'
    assert _attempt_row(store)['status'] == 'skipped_budget'


def test_grounding_claim_ownership_loss_terminalizes_claim_without_dispatch(
    monkeypatch, tmp_path
):
    calls = _install_grounding_response(monkeypatch, _grounding_payload())
    client, store = _grounding_client(tmp_path)
    original_claim = client.budget.claim

    def lose_response_ownership(*args, **kwargs):
        claimed = original_claim(*args, **kwargs)
        assert claimed.approved
        return BudgetReservation(
            approved=True,
            reservation_id=claimed.reservation_id,
            acquired_by_caller=False,
            owner_token=None,
        )

    monkeypatch.setattr(client.budget, 'claim', lose_response_ownership)

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='claim-loss-run', request_id='claim-loss-request'
    ))

    assert calls == []
    assert result['routing']['analysis_status'] == 'FAILED_TECHNICAL'
    assert result['routing']['fallback_reason'] == 'budget_claim_unavailable'
    with store.transaction() as connection:
        reservation = connection.execute(
            'SELECT status,actual_calls FROM budget_reservations WHERE request_id=?',
            ('claim-loss-request',),
        ).fetchone()
    assert reservation['status'] == 'released'
    assert reservation['actual_calls'] is None


def test_claim_exception_after_commit_survives_first_cleanup_failure_without_counting_call(
    monkeypatch, tmp_path
):
    canary = 'claim-after-commit-secret'
    calls = _install_grounding_response(monkeypatch, _grounding_payload())
    client, store = _grounding_client(tmp_path)
    original_claim = client.budget.claim
    original_release_before_dispatch = client.budget.release_before_dispatch
    cleanup_calls = []

    def claim_then_raise(*args, **kwargs):
        assert original_claim(*args, **kwargs).approved
        raise OSError(canary)

    def flaky_release_before_dispatch(*args, **kwargs):
        cleanup_calls.append(True)
        if len(cleanup_calls) == 1:
            raise OSError(canary)
        return original_release_before_dispatch(*args, **kwargs)

    monkeypatch.setattr(client.budget, 'claim', claim_then_raise)
    monkeypatch.setattr(
        client.budget, 'release_before_dispatch', flaky_release_before_dispatch,
    )

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='claim-after-commit-run',
        request_id='claim-after-commit-request',
    ))

    assert calls == []
    assert result['routing']['analysis_status'] == 'FAILED_TECHNICAL'
    assert result['routing']['fallback_reason'] == 'budget_claim_failed'
    assert canary not in str(result)
    assert len(cleanup_calls) == 2
    with store.transaction() as connection:
        reservation = connection.execute(
            'SELECT status,actual_calls FROM budget_reservations WHERE request_id=?',
            ('claim-after-commit-request',),
        ).fetchone()
    assert tuple(reservation) == ('released', None)


def test_predispatch_transport_failure_survives_first_cleanup_failure(
    monkeypatch, tmp_path
):
    canary = 'predispatch-cleanup-secret'
    client, store = _grounding_client(tmp_path)
    provider_calls = []

    class _Client:
        async def __aenter__(self):
            raise OSError(canary)

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            provider_calls.append(True)
            raise AssertionError('unreachable')

    monkeypatch.setattr(llm_analyzer_module.httpx, 'AsyncClient', lambda **_kw: _Client())
    monkeypatch.setattr(
        client.budget, 'release',
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError(canary)),
    )

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='predispatch-failure-run',
        request_id='predispatch-failure-request',
    ))

    assert provider_calls == []
    assert result['source'] == 'none'
    assert result['routing']['analysis_status'] == 'FAILED_TECHNICAL'
    assert result['routing']['attempts'][0]['status'] == 'skipped_dispatch'
    assert canary not in str(result)
    with store.transaction() as connection:
        reservation = connection.execute(
            'SELECT status,actual_calls FROM budget_reservations WHERE request_id=?',
            ('predispatch-failure-request',),
        ).fetchone()
    assert tuple(reservation) == ('released', None)


@pytest.mark.parametrize('stage', ['reserve', 'claim'])
def test_grounding_requires_acquired_by_caller_before_dispatch(
    monkeypatch, tmp_path, stage
):
    calls = _install_grounding_response(monkeypatch, _grounding_payload())
    client, store = _grounding_client(tmp_path)
    if stage == 'reserve':
        monkeypatch.setattr(client.budget, 'reserve', lambda **_kw: BudgetReservation(
            approved=True, reservation_id='foreign-reservation',
            acquired_by_caller=False, owner_token='foreign-owner',
        ))
    else:
        monkeypatch.setattr(client.budget, 'claim', lambda *_a, **_kw: BudgetReservation(
            approved=True, reservation_id='foreign-reservation',
            acquired_by_caller=False, owner_token='foreign-owner',
        ))

    result = asyncio.run(client.search_and_analyze(
        '삼성전자', run_id='owner-run', request_id=f'owner-{stage}'
    ))

    assert calls == []
    assert result['source'] == 'none'
    assert result['routing']['analysis_status'] == 'FAILED_TECHNICAL'
    assert result['routing']['attempts'][0]['attempt_number'] == 0
    assert _attempt_row(store)['status'] == 'skipped_budget'


def test_cancellation_after_dispatch_finalizes_budget_and_records_physical_attempt(
    monkeypatch, tmp_path
):
    client, store = _grounding_client(tmp_path)
    entered = asyncio.Event()
    blocked = asyncio.Event()

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url, json=None):
            entered.set()
            await blocked.wait()
            raise AssertionError('unreachable')

    monkeypatch.setattr(llm_analyzer_module.httpx, 'AsyncClient', lambda **_kw: _Client())

    async def scenario():
        task = asyncio.create_task(client.search_and_analyze(
            '삼성전자', run_id='cancel-run', request_id='cancel-request'
        ))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    row = _attempt_row(store)
    assert row['attempt_number'] == 1
    assert row['status'] == 'failed'
    assert row['selected'] == 0
    assert row['input_tokens'] is None
    with store.transaction() as connection:
        reservation = connection.execute(
            "SELECT status, actual_calls FROM budget_reservations WHERE request_id='cancel-request'"
        ).fetchone()
    assert reservation['status'] in {'settled', 'breached'}
    assert reservation['actual_calls'] == 1


def test_freshness_downgrade_synchronizes_nested_domain_status(monkeypatch):
    class Grounding:
        model_name = 'gemini-test'

        async def search_and_analyze(self, *_args, **_kwargs):
            return {
                'score': 2,
                'reason': 'transport succeeded but freshness is unverified',
                'themes': [],
                'source': 'gemini_grounding',
                'citations': ['https://example.test/news'],
                'freshness_verified': False,
                'routing': {
                    'analysis_status': 'SUCCESS_PRIMARY',
                    'actual_provider': 'gemini',
                    'attempt_count': 1,
                },
            }

    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.grounding = Grounding()
    monkeypatch.setitem(llm_analyzer_module.API_STATUS['gemini_grounding'], 'available', True)
    result = asyncio.run(analyzer._ground_when_no_sources(
        '삼성전자', [], '', run_id='freshness-run', request_id='freshness-request'
    ))

    assert result['analysis_status'] == 'DEGRADED'
    assert result['routing']['analysis_status'] == 'DEGRADED'
    assert result['routing']['domain_status'] == 'DEGRADED'
    assert result['routing']['transport_status'] == 'SUCCESS_PRIMARY'
    assert result['buy_evidence_eligible'] is False
