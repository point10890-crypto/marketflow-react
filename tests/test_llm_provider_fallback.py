import asyncio
import openai
from datetime import datetime, timezone
from decimal import Decimal

from app.services.ai_routing import store as routing_store
from app.services.ai_routing.contracts import AnalysisStatus, RoutingResult, TokenUsage
from app.services.mirofish import llm_client
from engine import llm_analyzer as llm_analyzer_module
from engine.llm_analyzer import LLMAnalyzer, reset_api_status


def test_mirofish_llm_client_ordinary_call_is_deepseek_first(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER', 'gemini')
    monkeypatch.delenv('MIROFISH_LLM_PROVIDER_ORDER', raising=False)
    monkeypatch.delenv('MIROFISH_LLM_DISABLED', raising=False)

    calls = []

    def fake_gemini(*_args, **_kwargs):
        calls.append('gemini')
        return None

    def fake_deepseek(*_args, **_kwargs):
        calls.append('deepseek')
        return '{"ok": true}'

    def fake_openai(*_args, **_kwargs):
        calls.append('openai')
        return '{"should_not_call": true}'

    monkeypatch.setattr(llm_client, '_generate_gemini', fake_gemini)
    monkeypatch.setattr(llm_client, '_generate_deepseek', fake_deepseek)
    monkeypatch.setattr(llm_client, '_generate_openai', fake_openai)

    text, provider = llm_client.generate_text_with_provider('return json', json_mode=True)

    assert text == '{"ok": true}'
    assert provider == 'deepseek'
    assert calls == ['deepseek']


def test_mirofish_llm_client_falls_back_to_openai_after_deepseek(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', 'openai,deepseek')
    monkeypatch.delenv('MIROFISH_LLM_DISABLED', raising=False)

    calls = []

    def fake_gemini(*_args, **_kwargs):
        calls.append('gemini')
        return None

    def fake_deepseek(*_args, **_kwargs):
        calls.append('deepseek')
        return None

    def fake_openai(*_args, **_kwargs):
        calls.append('openai')
        return 'openai-result'

    monkeypatch.setattr(llm_client, '_generate_gemini', fake_gemini)
    monkeypatch.setattr(llm_client, '_generate_deepseek', fake_deepseek)
    monkeypatch.setattr(llm_client, '_generate_openai', fake_openai)

    text, provider = llm_client.generate_text_with_provider('summarize')

    assert text == 'openai-result'
    assert provider == 'openai'
    assert calls == ['deepseek', 'openai']


def test_mirofish_llm_client_can_disable_exhausted_gemini(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER', 'gemini')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    monkeypatch.delenv('MIROFISH_LLM_PROVIDER_ORDER', raising=False)

    calls = []

    def fake_gemini(*_args, **_kwargs):
        calls.append('gemini')
        return None

    def fake_deepseek(*_args, **_kwargs):
        calls.append('deepseek')
        return 'deepseek-result'

    monkeypatch.setattr(llm_client, '_generate_gemini', fake_gemini)
    monkeypatch.setattr(llm_client, '_generate_deepseek', fake_deepseek)
    monkeypatch.setattr(llm_client, '_generate_openai', lambda *_args, **_kwargs: None)

    text, provider = llm_client.generate_text_with_provider('analyze')

    assert text == 'deepseek-result'
    assert provider == 'deepseek'
    assert calls == ['deepseek']


def test_legacy_openai_compatible_factories_disable_sdk_internal_retries(monkeypatch):
    constructor_kwargs = []

    class ConstructorOnlyClient:
        def __init__(self, **kwargs):
            constructor_kwargs.append(kwargs)

    monkeypatch.setenv('OPENAI_API_KEY', 'test-only')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only')
    monkeypatch.setattr(openai, 'OpenAI', ConstructorOnlyClient)

    llm_client.get_openai_client()
    llm_client.get_deepseek_client()

    assert [kwargs['max_retries'] for kwargs in constructor_kwargs] == [0, 0]


def test_mirofish_llm_client_all_disabled_does_not_rebuild_default_adapters(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'deepseek,openai,gemini')

    text, metadata = llm_client.generate_text_with_metadata('analyze')

    assert text is None
    assert metadata['provider'] == 'none'
    assert metadata['attempts'] == []
    assert metadata['failure_reason'] == 'all_providers_disabled'


def test_mirofish_llm_metadata_records_secret_free_fallback(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', 'deepseek,openai')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'must-not-appear')
    monkeypatch.setenv('OPENAI_API_KEY', 'also-must-not-appear')

    monkeypatch.setattr(llm_client, '_generate_deepseek', lambda *_a, **_k: None)
    monkeypatch.setattr(llm_client, '_generate_openai', lambda *_a, **_k: '{"verdict":"BUY"}')

    text, metadata = llm_client.generate_text_with_metadata('json please', json_mode=True)

    assert text == '{"verdict":"BUY"}'
    assert metadata['provider'] == 'openai'
    assert metadata['model']
    assert metadata['success'] is True
    assert metadata['fallback_used'] is True
    assert metadata['json_mode'] is True
    assert metadata['latency_ms'] >= 0
    assert [attempt['provider'] for attempt in metadata['attempts']] == ['deepseek', 'openai']
    assert metadata['attempts'][0]['failure_reason'] == 'empty_response'
    assert metadata['attempts'][1]['success'] is True
    assert 'must-not-appear' not in repr(metadata)
    assert llm_client.get_last_generation_metadata() == metadata


def test_json_mode_rejects_invalid_provider_payload_and_falls_back(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', 'deepseek,openai')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    calls = []

    def fake_deepseek(*_args, **_kwargs):
        calls.append('deepseek')
        return 'not valid json'

    def fake_openai(*_args, **_kwargs):
        calls.append('openai')
        return '{"ok":true}'

    monkeypatch.setattr(llm_client, '_generate_deepseek', fake_deepseek)
    monkeypatch.setattr(llm_client, '_generate_openai', fake_openai)

    text, metadata = llm_client.generate_text_with_metadata('return json', json_mode=True)

    assert text == '{"ok":true}'
    assert calls == ['deepseek', 'openai']
    assert metadata['provider'] == 'openai'
    assert metadata['attempts'][0]['failure_reason'] == 'invalid_json'


def test_deepseek_and_openai_json_mode_use_compatible_response_format(monkeypatch):
    class Message:
        content = '{"ok":true}'

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return Response()

    class Client:
        def __init__(self):
            self.chat = type('Chat', (), {})()
            self.chat.completions = Completions()

    deepseek = Client()
    openai = Client()
    monkeypatch.setattr(llm_client, 'get_deepseek_client', lambda: deepseek)
    monkeypatch.setattr(llm_client, 'get_openai_client', lambda: openai)

    assert llm_client._generate_deepseek(
        'produce data', system=None, model_env=None, temperature=0.1,
        max_tokens=100, json_mode=True,
    ) == '{"ok":true}'
    assert llm_client._generate_openai(
        'produce data', system=None, model_env=None, temperature=0.1,
        max_tokens=100, json_mode=True,
    ) == '{"ok":true}'

    for kwargs in (deepseek.chat.completions.kwargs, openai.chat.completions.kwargs):
        assert kwargs['response_format'] == {'type': 'json_object'}
        assert 'json' in kwargs['messages'][-1]['content'].lower()


def test_legacy_helper_forwards_native_usage_to_central_metadata(monkeypatch):
    class Usage:
        prompt_tokens = 100
        completion_tokens = 20
        total_tokens = 120
        prompt_tokens_details = {'cached_tokens': 25}
        completion_tokens_details = {'reasoning_tokens': 7}

    class Message:
        content = 'ok'

    class Response:
        choices = [type('Choice', (), {'message': Message()})()]
        usage = Usage()

    class Completions:
        @staticmethod
        def create(**_kwargs):
            return Response()

    client = type('Client', (), {'chat': type('Chat', (), {'completions': Completions()})()})()
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'openai,gemini')
    monkeypatch.setattr(llm_client, 'get_deepseek_client', lambda: client)

    _text, metadata = llm_client.generate_text_with_metadata('ordinary')

    assert metadata['usage']['input_tokens'] == 100
    assert metadata['usage']['cached_input_tokens'] == 25
    assert metadata['usage']['output_tokens'] == 20
    assert metadata['usage']['reasoning_tokens'] == 7
    assert metadata['usage']['total_tokens'] == 120
    assert metadata['estimated_cost_usd'] is not None


def test_gemini_thinking_tokens_are_billable_output():
    usage = llm_client.normalize_gemini_usage({
        'prompt_token_count': 100,
        'cached_content_token_count': 10,
        'candidates_token_count': 20,
        'thoughts_token_count': 7,
        'total_token_count': 127,
    })

    assert usage.output_tokens == 27
    assert usage.reasoning_tokens == 7
    assert usage.total_tokens == 127
    assert usage.mapping_status == 'valid'


def test_generation_metadata_collector_captures_run_calls(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', 'deepseek')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'openai,gemini')
    monkeypatch.setattr(llm_client, '_generate_deepseek', lambda *_a, **_k: 'ok')

    with llm_client.collect_generation_metadata() as calls:
        llm_client.generate_text('first')
        llm_client.generate_text('second')

    assert len(calls) == 2
    assert all(call['provider'] == 'deepseek' for call in calls)
    assert all(call['success'] is True for call in calls)


def test_generation_metadata_collector_propagates_one_run_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(routing_store, 'DEFAULT_DB_PATH', tmp_path / 'usage.sqlite3')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    openai_calls = []
    monkeypatch.setattr(llm_client, '_generate_deepseek', lambda *_a, **_k: None)

    def fake_openai(*_args, **_kwargs):
        openai_calls.append('openai')
        return 'fallback'

    monkeypatch.setattr(llm_client, '_generate_openai', fake_openai)

    with llm_client.collect_generation_metadata() as calls:
        results = [
            llm_client.generate_text(f'call-{index}', operation='decisive_text')
            for index in range(6)
        ]

    assert results[:5] == ['fallback'] * 5
    assert results[5] is None
    assert openai_calls == ['openai'] * 5
    assert len({call['run_id'] for call in calls}) == 1


def test_legacy_wrapper_preserves_authentication_error_class(tmp_path, monkeypatch):
    class AuthenticationError(Exception):
        status_code = 401

    class Completions:
        @staticmethod
        def create(**_kwargs):
            raise AuthenticationError()

    deepseek_client = type(
        'Client', (), {'chat': type('Chat', (), {'completions': Completions()})()}
    )()
    monkeypatch.setattr(routing_store, 'DEFAULT_DB_PATH', tmp_path / 'usage.sqlite3')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    monkeypatch.setattr(llm_client, 'get_deepseek_client', lambda: deepseek_client)
    monkeypatch.setattr(llm_client, '_generate_openai', lambda *_a, **_k: 'fallback')

    _text, metadata = llm_client.generate_text_with_metadata(
        'one', run_id='run', request_id='one'
    )
    _text, second = llm_client.generate_text_with_metadata(
        'two', run_id='run', request_id='two'
    )

    assert metadata['attempts'][0]['failure_reason'] == 'authentication'
    assert metadata['attempts'][0]['breaker_state'] == 'open'
    assert second['attempts'][0]['status'] == 'skipped_breaker'


def test_retry_then_empty_200_keeps_usage_and_clears_stale_error(tmp_path, monkeypatch):
    class RateLimitError(Exception):
        status_code = 429

    class Usage:
        prompt_tokens = 80
        completion_tokens = 5
        total_tokens = 85
        prompt_tokens_details = {'cached_tokens': 0}
        completion_tokens_details = {'reasoning_tokens': 0}

    class EmptyMessage:
        content = ''
        refusal = None

    class Completions:
        calls = 0

        @classmethod
        def create(cls, **_kwargs):
            cls.calls += 1
            if cls.calls == 1:
                raise RateLimitError()
            return type(
                'Response', (),
                {'choices': [type('Choice', (), {'message': EmptyMessage()})()], 'usage': Usage()},
            )()

    client = type('Client', (), {
        'chat': type('Chat', (), {'completions': Completions()})(),
    })()
    monkeypatch.setattr(routing_store, 'DEFAULT_DB_PATH', tmp_path / 'usage.sqlite3')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    monkeypatch.setattr(llm_client, 'get_deepseek_client', lambda: client)
    monkeypatch.setattr(llm_client, '_generate_openai', lambda *_a, **_k: 'fallback')

    _text, metadata = llm_client.generate_text_with_metadata(
        'retry', run_id='run', request_id='retry-empty'
    )

    assert metadata['attempts'][0]['failure_reason'] == 'rate_limit'
    assert metadata['attempts'][1]['failure_reason'] == 'empty_response'
    assert metadata['attempts'][1]['usage']['input_tokens'] == 80
    assert metadata['attempts'][1]['estimated_cost_usd'] is not None
    assert metadata['retry_reason'] == 'rate_limit'
    assert metadata['fallback_reason'] == 'empty_response'


def test_explicit_decisive_operation_uses_central_policy_and_cap(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', 'openai,deepseek')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    calls = []

    def fake_deepseek(*_args, **kwargs):
        calls.append(('deepseek', kwargs['max_tokens']))
        return None

    def fake_openai(*_args, **kwargs):
        calls.append(('openai', kwargs['max_tokens']))
        return 'reviewed'

    monkeypatch.setattr(llm_client, '_generate_deepseek', fake_deepseek)
    monkeypatch.setattr(llm_client, '_generate_openai', fake_openai)

    text, metadata = llm_client.generate_text_with_metadata(
        'decide',
        operation='decisive_text',
        max_tokens=4096,
    )

    assert text == 'reviewed'
    assert calls == [('deepseek', 1200), ('openai', 1200)]
    assert metadata['analysis_status'] == 'SUCCESS_FALLBACK'


def test_legacy_metadata_additively_exposes_usage_cost_and_breaker(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    monkeypatch.setattr(llm_client, '_generate_deepseek', lambda *_a, **_k: 'ok')

    _text, metadata = llm_client.generate_text_with_metadata('ordinary')

    assert metadata.keys() >= {
        'analysis_status', 'usage', 'estimated_cost_usd', 'breaker_state', 'attempts'
    }
    assert metadata['usage']['usage_estimated'] is True
    assert metadata['usage']['input_tokens'] is None
    assert metadata['estimated_cost_usd'] is None
    assert metadata['breaker_state'] == 'closed'


def test_generation_metadata_nested_usage_is_defensively_copied(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'gemini')
    monkeypatch.setattr(llm_client, '_generate_deepseek', lambda *_a, **_k: 'ok')

    _text, metadata = llm_client.generate_text_with_metadata('ordinary')
    metadata['attempts'][0]['usage']['input_tokens'] = 999

    stored = llm_client.get_last_generation_metadata()
    assert stored['attempts'][0]['usage']['input_tokens'] is None


def _bare_analyzer():
    reset_api_status()
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.grounding = None
    return analyzer


def _routed_news(*, provider='deepseek', fallback=False, text=None):
    return RoutingResult(
        text=text or '{"score":2,"reason":"확인된 수주","themes":["수주"]}',
        analysis_status=(
            AnalysisStatus.SUCCESS_FALLBACK if fallback else AnalysisStatus.SUCCESS_PRIMARY
        ),
        primary_provider='deepseek',
        actual_provider=provider,
        model='deepseek-v4-flash' if provider == 'deepseek' else 'gpt-5.5',
        fallback_used=fallback,
        fallback_reason='timeout' if fallback else None,
        evidence_validated=True,
        usage=TokenUsage(input_tokens=40, output_tokens=20),
        estimated_cost_usd=Decimal('0.001'),
    )


def _attributed_news():
    return [{
        'title': '수주',
        'summary': '계약',
        'source': '연합뉴스',
        'url': 'https://example.test/news/1',
        'published_at': datetime.now(timezone.utc).isoformat(),
    }]


def test_jongga_news_analysis_routes_deepseek_first_with_source_attribution(monkeypatch):
    """The central ordinary slot owns DS -> OA and keeps deterministic sources."""
    analyzer = _bare_analyzer()
    seen = []
    monkeypatch.setattr(
        llm_analyzer_module,
        'route_text',
        lambda request: seen.append(request) or _routed_news(),
    )

    result = asyncio.run(
        analyzer.analyze_news_sentiment(
            '테스트종목',
            _attributed_news(),
            run_id='jongga-run',
            request_id='jongga-run:005930:news',
        )
    )

    assert result['source'] == 'deepseek'
    assert result['score'] == 2
    assert result['themes'] == ['수주']
    assert result['buy_evidence_eligible'] is True
    assert result['non_grounded_summary'] is False
    assert result['citations'] == ['https://example.test/news/1']
    assert result['routing']['actual_provider'] == 'deepseek'
    request = seen[0]
    assert request.operation.value == 'bulk_text'
    assert request.run_id == 'jongga-run'
    assert request.request_id == 'jongga-run:005930:news'


def test_jongga_news_analysis_exposes_openai_only_as_failed_slot_replacement(monkeypatch):
    analyzer = _bare_analyzer()
    monkeypatch.setattr(
        llm_analyzer_module,
        'route_text',
        lambda request: _routed_news(
            provider='openai',
            fallback=True,
            text='{"score":1,"reason":"제한적","themes":[]}',
        ),
    )

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', _attributed_news()))

    assert result['source'] == 'openai_fallback'
    assert result['routing']['fallback_used'] is True
    assert result['routing']['fallback_reason'] == 'timeout'


def test_jongga_unattributed_text_uses_rule_before_any_non_grounded_llm(monkeypatch):
    """Source-less prose must never become standalone BUY evidence."""
    analyzer = _bare_analyzer()
    monkeypatch.setattr(
        llm_analyzer_module,
        'route_text',
        lambda request: (_ for _ in ()).throw(AssertionError('LLM must not run')),
    )

    result = asyncio.run(
        analyzer.analyze_news_sentiment(
            '테스트종목',
            [{'title': '대규모 수주', 'summary': '계약 성공'}],
        )
    )

    assert result['source'] == 'keyword_fallback'
    assert result['score'] <= 1
    assert result['buy_evidence_eligible'] is False
    assert result['non_grounded_summary'] is True


def test_jongga_dart_text_without_freshness_cannot_become_buy_evidence(monkeypatch):
    """A source name alone is not a substitute for dated/citable evidence."""
    analyzer = _bare_analyzer()
    monkeypatch.setattr(
        llm_analyzer_module,
        'route_text',
        lambda request: (_ for _ in ()).throw(AssertionError('LLM must not run')),
    )

    result = asyncio.run(
        analyzer.analyze_news_sentiment(
            '테스트종목',
            [],
            dart_text='대규모 공급계약 체결',
        )
    )

    assert result['score'] <= 1
    assert result['buy_evidence_eligible'] is False
    assert result['non_grounded_summary'] is True
    assert result['source_evidence'][0]['source'] == 'DART'


def test_jongga_attribution_and_freshness_must_exist_on_same_record(monkeypatch):
    analyzer = _bare_analyzer()
    monkeypatch.setattr(
        llm_analyzer_module,
        'route_text',
        lambda request: (_ for _ in ()).throw(AssertionError('LLM must not run')),
    )
    split_evidence = [
        {
            'title': 'URL만 있음',
            'summary': '계약',
            'source': '연합뉴스',
            'url': 'https://example.test/news/1',
            'published_at': '',
        },
        {
            'title': '날짜만 있음',
            'summary': '계약',
            'source': '연합뉴스',
            'url': '',
            'published_at': datetime.now(timezone.utc).isoformat(),
        },
    ]

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', split_evidence))

    assert result['buy_evidence_eligible'] is False
    assert result['analysis_status'] == 'DEGRADED'


def test_jongga_stale_news_cannot_enter_llm_buy_evidence(monkeypatch):
    analyzer = _bare_analyzer()
    monkeypatch.setattr(
        llm_analyzer_module,
        'route_text',
        lambda request: (_ for _ in ()).throw(AssertionError('LLM must not run')),
    )
    stale = [{
        'title': '오래된 계약',
        'summary': '과거 자료',
        'source': '연합뉴스',
        'url': 'https://example.test/old',
        'published_at': '2020-01-01T00:00:00+00:00',
    }]

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', stale))

    assert result['buy_evidence_eligible'] is False
    assert result['analysis_status'] == 'DEGRADED'


def test_jongga_unknown_source_sentinel_is_not_verified_evidence(monkeypatch):
    analyzer = _bare_analyzer()
    monkeypatch.setattr(
        llm_analyzer_module,
        'route_text',
        lambda request: (_ for _ in ()).throw(AssertionError('LLM must not run')),
    )
    sentinel = [{
        'title': '출처 미상',
        'summary': '계약',
        'source': 'Unknown',
        'url': 'https://example.test/news',
        'published_at': datetime.now(timezone.utc).isoformat(),
    }]

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', sentinel))

    assert result['buy_evidence_eligible'] is False
    assert result['analysis_status'] == 'DEGRADED'


def test_naive_korean_news_timestamp_is_interpreted_as_kst():
    record = {
        'source': '연합뉴스',
        'url': 'https://example.test/news',
        'published_at': '2026-09-03T09:00:00',
    }

    assert llm_analyzer_module._fresh_attributed_news_record(
        record,
        now=datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc),
    ) is True


def test_grounding_without_verified_freshness_cannot_alone_create_buy_evidence():
    class Grounding:
        model_name = 'gemini-2.5-flash'

        async def search_and_analyze(self, *_args, **_kwargs):
            return {
                'score': 3,
                'reason': '검색 결과',
                'themes': ['테마'],
                'source': 'gemini_grounding',
                'citations': ['https://example.test/result'],
            }

    reset_api_status()
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.grounding = Grounding()

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', []))

    assert result['source'] == 'gemini_grounding'
    assert result['score'] <= 1
    assert result['buy_evidence_eligible'] is False
    assert result['analysis_status'] == 'DEGRADED'


def test_specialized_grounding_keeps_parent_run_identity_and_usage():
    class Grounding:
        model_name = 'gemini-2.5-flash'

        async def search_and_analyze(self, *_args, **_kwargs):
            return {
                'score': 2,
                'reason': '검증된 검색 결과',
                'themes': ['테마'],
                'source': 'gemini_grounding',
                'citations': ['https://example.test/result'],
                'freshness_verified': True,
                'usage': {
                    'input_tokens': 30,
                    'cached_input_tokens': 0,
                    'output_tokens': 10,
                    'reasoning_tokens': 0,
                    'total_tokens': 40,
                    'usage_estimated': False,
                },
            }

    reset_api_status()
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.grounding = Grounding()

    result = asyncio.run(
        analyzer.analyze_news_sentiment(
            '테스트종목',
            [],
            run_id='jongga-run',
            request_id='jongga-run:005930:news',
        )
    )

    assert result['routing']['run_id'] == 'jongga-run'
    assert result['routing']['request_id'] == 'jongga-run:005930:news'
    assert result['routing']['usage']['total_tokens'] == 40
