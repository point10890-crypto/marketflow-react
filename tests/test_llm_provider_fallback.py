import asyncio

from app.services.mirofish import llm_client
from engine.llm_analyzer import LLMAnalyzer, reset_api_status


def test_mirofish_llm_client_falls_back_from_gemini_to_deepseek(monkeypatch):
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
    assert calls == ['gemini', 'deepseek']


def test_mirofish_llm_client_falls_back_to_openai_after_deepseek(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', 'gemini,deepseek,openai')
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
    assert calls == ['gemini', 'deepseek', 'openai']


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


class FakeGrounding:
    def __init__(self, result):
        self.result = result

    async def search_and_analyze(self, *_args, **_kwargs):
        return dict(self.result)


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def analyze_news(self, *_args, **_kwargs):
        self.calls += 1
        return dict(self.result)


class ShouldNotCall:
    async def analyze_news(self, *_args, **_kwargs):
        raise AssertionError('provider should not be called')


class ShouldNotCallGrounding:
    async def search_and_analyze(self, *_args, **_kwargs):
        raise AssertionError('grounding should not be called')


def _bare_analyzer():
    reset_api_status()
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.xai = ShouldNotCall()
    return analyzer


def test_jongga_news_analysis_deepseek_is_primary():
    """2026-09-02 순위 변경 — DeepSeek 이 1순위, 성공 시 다른 provider 는 호출 자체가 없다."""
    analyzer = _bare_analyzer()
    analyzer.grounding = ShouldNotCallGrounding()
    analyzer.deepseek = FakeProvider({'score': 2, 'reason': 'DART 수주와 거래대금 증가', 'themes': ['수주']})
    analyzer.claude = ShouldNotCall()
    analyzer.openai = ShouldNotCall()

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', [{'title': '수주', 'summary': '계약'}]))

    assert result['source'] == 'deepseek'
    assert result['score'] == 2
    assert result['themes'] == ['수주']


def test_jongga_news_analysis_falls_deepseek_then_openai():
    """DeepSeek 실패 → OpenAI(보조)가 2순위로 응답. Grounding/Claude 는 그 뒤라 미호출."""
    analyzer = _bare_analyzer()
    analyzer.grounding = ShouldNotCallGrounding()
    analyzer.deepseek = FakeProvider({'score': 0, 'reason': 'No DeepSeek Client', 'themes': []})
    analyzer.claude = ShouldNotCall()
    analyzer.openai = FakeProvider({'score': 0, 'reason': '확인된 호재가 제한적입니다.', 'themes': []})

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', [{'title': '중립', 'summary': '중립'}]))

    assert result['source'] == 'openai_fallback'
    assert result['score'] == 0
    assert analyzer.deepseek.calls == 1
    assert analyzer.openai.calls == 1


def test_jongga_news_analysis_reaches_claude_after_grounding():
    """DeepSeek·OpenAI·Grounding 모두 실패해도 체인이 Claude 까지 이어진다."""
    analyzer = _bare_analyzer()
    analyzer.grounding = FakeGrounding({
        'score': 0,
        'reason': 'No Gemini API Key',
        'themes': [],
        'source': 'none',
    })
    analyzer.deepseek = FakeProvider({'score': 0, 'reason': 'No DeepSeek Client', 'themes': []})
    analyzer.openai = FakeProvider({'score': 0, 'reason': 'No OpenAI Client', 'themes': []})
    analyzer.claude = FakeProvider({'score': 1, 'reason': '중립적 재료', 'themes': []})

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', [{'title': '중립', 'summary': '중립'}]))

    assert result['source'] == 'claude_fallback'
    assert analyzer.deepseek.calls == 1
    assert analyzer.openai.calls == 1
    assert analyzer.claude.calls == 1
