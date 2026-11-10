import json
from dataclasses import replace
from types import SimpleNamespace
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from decimal import Decimal

import httpx2 as httpx
import pytest

from app.services.ai_routing.contracts import (
    AnalysisStatus, Operation, ProviderErrorClass, RoutingRequest, TokenUsage,
)
from app.services.ai_routing.policy import policy_for
from app.services.ai_routing.pricing import estimate_cost
from app.services.ai_routing.providers import (
    AdapterResponse, ProviderCallError, build_default_adapters,
)
from app.services.ai_routing.router import AIRouter
from app.services.ai_routing.store import RoutingStore


class FixedAdapter:
    endpoint = 'fixture.generate'

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def generate(self, request, *, model, max_output_tokens):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def good_response(text='{"evidence":[]}'):
    return AdapterResponse(text, TokenUsage(input_tokens=100, output_tokens=20))


def request(operation='news_event_extract', request_id='new-feature'):
    return RoutingRequest(operation=operation, prompt='Saved evidence only.',
                          json_mode=True, run_id=request_id, request_id=request_id)


def ledger(store):
    with store.transaction() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM budget_reservations WHERE pool='evidence_review'"
        )]


@pytest.mark.parametrize('operation,model', [
    ('news_event_extract', 'claude-haiku-5-5'),
    ('candidate_review', 'claude-sonnet-5-5'),
])
def test_new_operations_dispatch_anthropic_and_persist_native_cost(tmp_path, operation, model):
    primary = FixedAdapter(good_response())
    fallback = FixedAdapter(good_response())
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    result = AIRouter({'anthropic': primary, 'deepseek': fallback}, store=store).route_text(request(operation))
    assert result.analysis_status == AnalysisStatus.SUCCESS_PRIMARY
    assert result.actual_provider == 'anthropic' and result.model == model
    assert primary.calls == 1 and fallback.calls == 0
    assert result.usage.total_tokens == 120
    assert len(ledger(store)) == 1
    assert Decimal(ledger(store)[0]['actual_cost_usd']) == result.estimated_cost_usd


def test_old_operations_keep_their_existing_primary_and_fallback_order():
    for operation in ('bulk_text', 'compact_debate', 'decisive_text', 'interactive_text'):
        assert policy_for(operation).providers == ('deepseek', 'openai')
    assert policy_for('vision').providers == ('gemini', 'openai')
    assert policy_for('specialized_gemini').providers == ('gemini', 'deepseek', 'openai')


def wire_adapter(monkeypatch, handler):
    import anthropic
    real_client = anthropic.Anthropic
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fixture-secret')
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://untrusted.invalid')
    def intercepted_client(**kwargs):
        configured = kwargs.pop('http_client', None)
        follows = configured.follow_redirects if configured is not None else True
        if configured is not None:
            configured.close()
        return real_client(**kwargs, http_client=httpx.Client(
            follow_redirects=follows, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(anthropic, 'Anthropic', intercepted_client)
    return build_default_adapters()['anthropic']


def test_official_messages_schema_disabled_thinking_and_cache_usage(monkeypatch):
    sent = []
    def handler(req):
        sent.append(req)
        return httpx.Response(200, json={
            'id': 'msg_fixture', 'type': 'message', 'role': 'assistant',
            'model': 'claude-haiku-5-5', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': '{"value":"saved"}'}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 30, 'cache_creation_input_tokens': 0},
        })
    adapter = wire_adapter(monkeypatch, handler)
    schema = {'type': 'object', 'properties': {'value': {'type': 'string'}},
              'required': ['value'], 'additionalProperties': False}
    response = adapter.generate(RoutingRequest(operation='news_event_extract', prompt='Evidence.',
                               system='Use supplied evidence.', json_mode=True, response_schema=schema),
                               model='claude-haiku-5-5', max_output_tokens=200)
    assert str(sent[0].url) == 'https://api.anthropic.com/v1/messages'
    body = json.loads(sent[0].content)
    assert body['output_config']['format'] == {'type': 'json_schema', 'schema': schema}
    assert body['thinking'] == {'type': 'disabled'}
    assert 'cache_control' not in json.dumps(body) and 'citations' not in json.dumps(body)
    assert body['max_tokens'] == 200 and body['system'] == 'Use supplied evidence.'
    assert response.usage.input_tokens == 130
    assert response.usage.cached_input_tokens == 30 and response.usage.total_tokens == 150
    assert estimate_cost('anthropic', 'claude-haiku-5-5', response.usage) == Decimal('0.0000203')
    assert 0 < adapter.request_timeout_seconds <= 90


@pytest.mark.parametrize('status,message,error', [
    (400, 'Your credit balance is too low to access the Anthropic API. fixture-secret', ProviderErrorClass.INSUFFICIENT_BALANCE),
    (401, 'bad key fixture-secret', ProviderErrorClass.AUTHENTICATION),
    (404, 'model not found fixture-secret', ProviderErrorClass.MODEL_UNAVAILABLE),
])
def test_anthropic_rejections_fallback_and_breaker_survives_restart(tmp_path, monkeypatch, status, message, error):
    sends = []
    def handler(req):
        sends.append(req)
        return httpx.Response(status, json={'type': 'error', 'error': {'type': 'invalid_request_error', 'message': message}})
    primary = wire_adapter(monkeypatch, handler)
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    result = AIRouter({'anthropic': primary, 'deepseek': FixedAdapter(good_response())}, store=store).route_text(request())
    assert result.analysis_status == AnalysisStatus.SUCCESS_FALLBACK
    assert result.fallback_reason == error and result.actual_provider == 'deepseek'
    assert result.attempts[0].error_class == error
    assert 'fixture-secret' not in repr(result)
    restart = AIRouter({'anthropic': primary, 'deepseek': FixedAdapter(good_response())},
                       store=RoutingStore(store.db_path))
    second = restart.route_text(request(request_id='after-restart'))
    assert second.actual_provider == 'deepseek'
    assert second.attempts[0].error_class == ProviderErrorClass.BREAKER_OPEN
    assert len(sends) == 1


def test_native_sdk_never_retries_a_transient_error(monkeypatch):
    sends = []
    def handler(req):
        sends.append(req)
        return httpx.Response(500, json={'type': 'error', 'error': {'type': 'api_error', 'message': 'temporary'}})
    adapter = wire_adapter(monkeypatch, handler)
    with pytest.raises(ProviderCallError, match='server_error'):
        adapter.generate(request(), model='claude-haiku-5-5', max_output_tokens=20)
    assert len(sends) == 1


def test_sonnet_55_uses_supported_text_only_thinking_mode_with_schema(monkeypatch):
    sent = []
    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={
            'id': 'msg_sonnet', 'type': 'message', 'role': 'assistant',
            'model': 'claude-sonnet-5-5', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': '{"value":"saved"}'}],
            'usage': {'input_tokens': 100, 'output_tokens': 20},
        })
    schema = {'type': 'object', 'properties': {'value': {'type': 'string'}},
              'required': ['value'], 'additionalProperties': False}
    response = wire_adapter(monkeypatch, handler).generate(
        RoutingRequest(operation='candidate_review', prompt='Supplied evidence.',
                       json_mode=True, response_schema=schema),
        model='claude-sonnet-5-5', max_output_tokens=200)
    assert sent[0]['thinking'] == {'type': 'between_tools'}
    assert sent[0]['output_config'] == {
        'effort': 'low', 'format': {'type': 'json_schema', 'schema': schema},
    }
    assert 'tools' not in sent[0]
    assert response.text == '{"value":"saved"}'


def test_daily_call_cap_includes_fallback_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '2')
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    primary = FixedAdapter(ProviderCallError(ProviderErrorClass.TIMEOUT))
    fallback = FixedAdapter(good_response())
    result = AIRouter({'anthropic': primary, 'deepseek': fallback}, store=store).route_text(request())
    assert result.actual_provider == 'deepseek'
    assert primary.calls == 1 and fallback.calls == 1
    rows = ledger(store)
    assert len(rows) == 2
    unknown = next(row for row in rows if row['provider'] == 'anthropic')
    assert Decimal(unknown['reserved_cost_usd']) > 0
    assert unknown['actual_cost_usd'] in (None, unknown['reserved_cost_usd'])
    blocked = AIRouter({'anthropic': fallback}, store=RoutingStore(store.db_path)).route_text(request(request_id='next'))
    assert blocked.analysis_status == AnalysisStatus.DEGRADED
    assert blocked.fallback_reason == ProviderErrorClass.BUDGET_EXHAUSTED
    assert fallback.calls == 1


def test_openai_final_fallback_is_debited_to_both_scoped_and_openai_ledgers(tmp_path):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    failure = ProviderCallError(ProviderErrorClass.MODEL_UNAVAILABLE)
    result = AIRouter({'anthropic': FixedAdapter(failure), 'deepseek': FixedAdapter(failure),
                       'openai': FixedAdapter(good_response())}, store=store).route_text(request())
    assert result.actual_provider == 'openai' and result.fallback_used
    assert len(ledger(store)) == 3
    with store.transaction() as connection:
        row = connection.execute("SELECT * FROM budget_reservations WHERE pool='automatic'").fetchone()
    assert row['provider'] == 'openai' and row['status'] == 'settled'


def _competing_reservation(arguments):
    from app.services.ai_routing.budget import EvidenceReviewBudget
    path, index = arguments
    manager = EvidenceReviewBudget(RoutingStore(path))
    return manager.reserve_attempt(request=request(request_id=f'process-{index}'), provider='anthropic',
                                   input_tokens=1000, output_tokens=1000,
                                   estimated_cost_usd=Decimal('0.4'), pricing_version='fixture').approved


def test_daily_usd_cap_is_atomic_across_processes(tmp_path):
    path = str(tmp_path / 'usage.sqlite3')
    # Initialize once; all actual admission/aggregation is in independent processes.
    RoutingStore(path).initialize()
    with ProcessPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(_competing_reservation, [(path, i) for i in range(8)]))
    assert sum(results) == 2
    assert len(ledger(RoutingStore(path))) == 2


def test_unknown_usage_is_conservatively_reserved_and_cannot_be_replayed(tmp_path):
    from app.services.ai_routing.budget import EvidenceReviewBudget
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    manager = EvidenceReviewBudget(store)
    kwargs = dict(request=request(), provider='anthropic', input_tokens=1000, output_tokens=1000,
                  estimated_cost_usd=Decimal('0.8'), pricing_version='fixture')
    permit = manager.reserve_attempt(**kwargs)
    assert permit.approved
    manager.settle(permit.reservation_id, TokenUsage.unknown())
    restart = EvidenceReviewBudget(RoutingStore(store.db_path))
    assert not restart.reserve_attempt(**kwargs).approved
    assert not restart.reserve_attempt(**{**kwargs, 'request': request(request_id='another'),
                                          'estimated_cost_usd': Decimal('0.3')}).approved


def _review_permit(manager, identifier, *, caller='scheduled_evidence_review', operation='news_event_extract', provider='anthropic', cost=Decimal('0.001')):
    return manager.reserve_attempt(request=replace(request(operation, identifier), caller_endpoint=caller),
        provider=provider, input_tokens=100, output_tokens=20, estimated_cost_usd=cost, pricing_version='fixture')


def test_optional_articles_leave_nine_calls_for_all_top3_role_fallbacks(tmp_path, monkeypatch):
    from app.services.ai_routing.budget import EvidenceReviewBudget
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_BUDGET_USD', '1')
    store = RoutingStore(tmp_path/'usage.sqlite3')
    manager = EvidenceReviewBudget(store)
    assert all(_review_permit(manager, f'article-{index}').approved for index in range(91))
    denied = _review_permit(manager, 'article-overflow')
    assert not denied.approved and denied.reason == 'top3_capacity_reserved'
    assert len(ledger(store)) == 91

    primary = FixedAdapter(good_response('invalid-json'))
    fallback = FixedAdapter(good_response('invalid-json'))
    final = FixedAdapter(good_response())
    router = AIRouter({'anthropic': primary, 'deepseek': fallback, 'openai': final}, store=store)
    article_blocked = router.route_text(replace(request(request_id='blocked-article'),
        caller_endpoint='scheduled_evidence_review'))
    assert article_blocked.fallback_reason == ProviderErrorClass.BUDGET_EXHAUSTED
    assert (primary.calls, fallback.calls, final.calls) == (0, 0, 0)
    for role, operation in [('analyst','news_event_extract'), ('critic','news_event_extract'), ('chair','candidate_review')]:
        result = router.route_text(replace(request(operation, role), run_id='top3-debate',
            caller_endpoint='scheduled_top3_advisor', max_output_tokens=100))
        assert result.analysis_status == AnalysisStatus.SUCCESS_FALLBACK and result.actual_provider == 'openai'
    assert (primary.calls, fallback.calls, final.calls) == (3, 3, 3)
    assert len(ledger(store)) == 100
    blocked = router.route_text(replace(request(request_id='another-top3'), caller_endpoint='scheduled_top3_advisor'))
    assert blocked.fallback_reason == ProviderErrorClass.BUDGET_EXHAUSTED
    assert (primary.calls, fallback.calls, final.calls) == (3, 3, 3)


@pytest.mark.parametrize('cap,article_allowance', [(0,0), (1,0), (9,0), (10,1)])
def test_top3_reserve_respects_small_configured_caps(tmp_path, monkeypatch, cap, article_allowance):
    from app.services.ai_routing.budget import EvidenceReviewBudget
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', str(cap))
    manager = EvidenceReviewBudget(RoutingStore(tmp_path/'usage.sqlite3'))
    assert sum(_review_permit(manager, f'article-{index}').approved for index in range(12)) == article_allowance
    assert sum(_review_permit(manager, f'top3-{index}', caller='scheduled_top3_advisor').approved
               for index in range(12)) == cap-article_allowance


@pytest.mark.parametrize('caller,operation', [
    ('scheduled_evidence_review','candidate_review'),
    ('scheduled_top3_advisor','news_event_extract'),
    ('manual_review','news_event_extract'),
    (None,'news_event_extract'),
])
def test_top3_reserve_does_not_change_other_review_callers_or_operations(tmp_path, monkeypatch, caller, operation):
    from app.services.ai_routing.budget import EvidenceReviewBudget
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    manager = EvidenceReviewBudget(RoutingStore(tmp_path/'usage.sqlite3'))
    assert _review_permit(manager, 'allowed', caller=caller, operation=operation).approved
    assert not _review_permit(manager, 'capped', caller=caller, operation=operation).approved


def test_article_priority_admission_remains_atomic_and_preserves_charge_fences(tmp_path, monkeypatch):
    from app.services.ai_routing.budget import EvidenceReviewBudget
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '11')
    store = RoutingStore(tmp_path/'usage.sqlite3')
    store.initialize()
    manager = EvidenceReviewBudget(store)
    with ThreadPoolExecutor(max_workers=8) as executor:
        permits = list(executor.map(lambda index: _review_permit(manager, f'article-{index}'), range(8)))
    assert sum(permit.approved for permit in permits) == 2
    rows = ledger(store)
    # A claimed/unknown paid attempt cannot use the reserve as a replay escape.
    existing = rows[0]['request_id']
    duplicate = _review_permit(manager, existing, caller='scheduled_top3_advisor')
    assert not duplicate.approved and duplicate.reason == 'duplicate_request'
    assert _review_permit(manager, 'unknown-cost', caller='scheduled_top3_advisor', cost=None).reason == 'daily_cost_unknown'
    assert len(ledger(store)) == 2


def test_invalid_json_still_accounts_for_billable_native_usage(tmp_path):
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    result = AIRouter({'anthropic': FixedAdapter(good_response('not-json')),
                       'deepseek': FixedAdapter(good_response())}, store=store).route_text(request())
    assert result.actual_provider == 'deepseek'
    assert result.attempts[0].usage.total_tokens == 120
    assert result.attempts[0].estimated_cost_usd > 0
    assert all(row['actual_cost_usd'] is not None for row in ledger(store))


def test_native_client_rejects_redirects_outside_the_official_host(monkeypatch):
    import anthropic
    real_client = anthropic.Anthropic
    sent = []
    def redirect(req):
        sent.append(str(req.url))
        if req.url.host == 'api.anthropic.com':
            return httpx.Response(307, headers={'location': 'https://other.invalid/v1/messages'})
        return httpx.Response(401, json={'error': {'type': 'authentication_error', 'message': 'unexpected host'}})
    def intercepted_client(**kwargs):
        configured = kwargs.pop('http_client', None)
        # Reproduce the SDK's documented redirect default until the factory
        # explicitly supplies a restricted transport.
        follows = configured.follow_redirects if configured is not None else True
        if configured is not None:
            configured.close()
        return real_client(**kwargs, http_client=httpx.Client(
            follow_redirects=follows, transport=httpx.MockTransport(redirect)))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fixture')
    monkeypatch.setattr(anthropic, 'Anthropic', intercepted_client)
    with pytest.raises(ProviderCallError):
        build_default_adapters()['anthropic'].generate(request(), model='claude-haiku-5-5', max_output_tokens=10)
    assert sent == ['https://api.anthropic.com/v1/messages']


def test_factory_constructs_the_pinned_sdk_client_without_network(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fixture-only')
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://other.invalid')
    client = build_default_adapters()['anthropic'].client_factory()
    try:
        assert client.base_url.host == 'api.anthropic.com'
        assert client.max_retries == 0
        assert client._client.follow_redirects is False
    finally:
        client.close()


def test_haiku_does_not_report_low_tier_price_for_long_context():
    assert estimate_cost('anthropic', 'claude-haiku-5-5',
                         TokenUsage(input_tokens=100001, output_tokens=20)) is None


def test_schema_input_size_rejects_before_any_paid_dispatch(tmp_path):
    adapter = FixedAdapter(good_response())
    oversized = RoutingRequest(operation='news_event_extract', prompt='small',
        response_schema={'description': 'X' * 100001}, json_mode=True)
    result = AIRouter({'anthropic': adapter}, store=RoutingStore(tmp_path / 'usage.sqlite3')).route_text(oversized)
    assert result.fallback_reason == ProviderErrorClass.PAYLOAD_TOO_LARGE
    assert adapter.calls == 0


def test_exhausted_legacy_openai_budget_does_not_block_anthropic_primary(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_OPENAI_DAILY_BUDGET_USD', '0.000001')
    primary = FixedAdapter(good_response())
    result = AIRouter({'anthropic': primary}, store=RoutingStore(tmp_path / 'usage.sqlite3')).route_text(request())
    assert result.actual_provider == 'anthropic'


def test_unexpected_cache_writes_keep_unknown_price_instead_of_underbilling():
    from app.services.ai_routing.providers import normalize_anthropic_usage
    usage = normalize_anthropic_usage({'input_tokens': 10, 'output_tokens': 20,
                                      'cache_creation_input_tokens': 100, 'cache_read_input_tokens': 5})
    assert usage.input_tokens == 115 and usage.total_tokens == 135
    assert usage.mapping_status == 'quarantined'
    assert estimate_cost('anthropic', 'claude-haiku-5-5', usage) is None


def test_openai_global_daily_cap_counts_one_fallback_once(tmp_path, monkeypatch):
    from app.services.ai_routing.budget import BudgetManager, _utc_billing_day
    monkeypatch.setenv('AI_OPENAI_DAILY_BUDGET_USD', '0.008')
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    failure = ProviderCallError(ProviderErrorClass.AUTHENTICATION)
    result = AIRouter({'anthropic': FixedAdapter(failure), 'deepseek': FixedAdapter(failure),
        'openai': FixedAdapter(good_response())}, store=store).route_text(
            replace(request(), max_output_tokens=20))
    assert result.actual_provider == 'openai'
    with store.transaction() as connection:
        daily_cost = BudgetManager(store)._used_daily_cost(connection, _utc_billing_day())
    assert daily_cost == Decimal('0.0011')
    assert next(row for row in ledger(store) if row['provider'] == 'openai')['actual_cost_usd'] == '0.0011'


@pytest.mark.parametrize('provider', ['anthropic', 'deepseek', 'openai'])
@pytest.mark.parametrize('operation', ['news_event_extract', 'candidate_review', 'decisive_text'])
def test_missing_client_is_known_zero_only_for_new_review_operations(provider, operation):
    from app.services.ai_routing.providers import AnthropicAdapter, OpenAICompatibleAdapter
    adapter = AnthropicAdapter(lambda: None) if provider == 'anthropic' else OpenAICompatibleAdapter(
        lambda: None, provider=provider)
    with pytest.raises(ProviderCallError) as captured:
        adapter.generate(request(operation), model='fixture', max_output_tokens=20)
    assert captured.value.error_class == ProviderErrorClass.CLIENT_UNAVAILABLE
    if operation == 'decisive_text':
        assert captured.value.usage.usage_estimated
    else:
        assert captured.value.usage.input_tokens == 0
        assert captured.value.usage.output_tokens == 0
        assert not captured.value.usage.usage_estimated


@pytest.mark.parametrize('provider', ['deepseek', 'openai'])
@pytest.mark.parametrize('status,message', [
    (401, 'Unauthorized'), (403, 'Forbidden'), (402, 'Payment required'),
    (400, 'Your credit balance is too low to access the API.'),
    (404, 'Model not found'), (410, 'Model no longer available'),
])
def test_fallback_preinference_rejections_have_zero_usage_for_reviews(provider, status, message):
    from app.services.ai_routing.providers import OpenAICompatibleAdapter
    class HTTPFailure(RuntimeError):
        status_code = status
        body = {'error': {'message': message}}
    def fail(**kwargs):
        raise HTTPFailure('private response must not be exposed')
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
    adapter = OpenAICompatibleAdapter(lambda: client, provider=provider)
    with pytest.raises(ProviderCallError) as review:
        adapter.generate(request(), model='fixture', max_output_tokens=20)
    assert review.value.usage.total_tokens == 0
    with pytest.raises(ProviderCallError) as legacy:
        adapter.generate(request('decisive_text'), model='fixture', max_output_tokens=20)
    assert legacy.value.usage.total_tokens is None


def test_breaker_and_missing_adapter_skips_are_known_no_charge(tmp_path):
    from app.services.ai_routing.breaker import CircuitBreaker
    store = RoutingStore(tmp_path / 'usage.sqlite3')
    CircuitBreaker(store).record_failure('anthropic', 'text', 'evidence:claude-haiku-5-5',
                                         ProviderErrorClass.AUTHENTICATION)
    result = AIRouter({'anthropic': FixedAdapter(good_response())}, store=store).route_text(request())
    assert result.text is None
    assert result.attempts[0].error_class == ProviderErrorClass.BREAKER_OPEN
    assert all(attempt.usage.total_tokens == 0 and attempt.estimated_cost_usd == 0
               for attempt in result.attempts)
    assert ledger(store) == []


def test_anthropic_review_uses_a_thirty_second_native_http_timeout(monkeypatch):
    sent = []
    def handler(req):
        sent.append(req)
        return httpx.Response(200, json={
            'id': 'msg_timeout_bound', 'type': 'message', 'role': 'assistant',
            'model': 'claude-haiku-5-5', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': '{}'}],
            'usage': {'input_tokens': 10, 'output_tokens': 2},
        })
    wire_adapter(monkeypatch, handler).generate(request(), model='claude-haiku-5-5', max_output_tokens=20)
    assert all(value == 30 for value in sent[0].extensions['timeout'].values())


@pytest.mark.parametrize('provider', ['deepseek', 'openai'])
def test_fallback_review_timeout_is_scoped_and_legacy_default_is_preserved(provider):
    from app.services.ai_routing.providers import OpenAICompatibleAdapter
    sent = []
    def create(**kwargs):
        sent.append(kwargs)
        return {'choices': [{'message': {'content': '{}'}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    adapter = OpenAICompatibleAdapter(lambda: client, provider=provider)
    adapter.generate(request(), model='fixture', max_output_tokens=20)
    adapter.generate(request('decisive_text'), model='fixture', max_output_tokens=20)
    assert sent[0]['timeout'] == 30
    assert 'timeout' not in sent[1]


@pytest.mark.parametrize('error', [TimeoutError(), ConnectionError()])
def test_fallback_uncertain_transport_never_becomes_zero_usage(error):
    from app.services.ai_routing.providers import OpenAICompatibleAdapter
    def fail(**kwargs):
        raise error
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
    with pytest.raises(ProviderCallError) as captured:
        OpenAICompatibleAdapter(lambda: client, provider='deepseek').generate(
            request(), model='fixture', max_output_tokens=20)
    assert captured.value.usage.usage_estimated
    assert captured.value.usage.total_tokens is None
