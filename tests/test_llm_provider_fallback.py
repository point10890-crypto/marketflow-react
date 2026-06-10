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


def _bare_analyzer():
    reset_api_status()
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.xai = ShouldNotCall()
    return analyzer


def test_jongga_news_analysis_routes_gemini_rate_limit_to_deepseek():
    analyzer = _bare_analyzer()
    analyzer.grounding = FakeGrounding({
        'score': 0,
        'reason': 'Rate Limited: 429 RESOURCE_EXHAUSTED',
        'themes': [],
        'source': 'none',
    })
    analyzer.deepseek = FakeProvider({'score': 2, 'reason': 'DART 수주와 거래대금 증가', 'themes': ['수주']})
    analyzer.claude = ShouldNotCall()
    analyzer.openai = ShouldNotCall()

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', [{'title': '수주', 'summary': '계약'}]))

    assert result['source'] == 'deepseek_fallback'
    assert result['score'] == 2
    assert result['themes'] == ['수주']


def test_jongga_news_analysis_does_not_stop_on_missing_clients_before_openai():
    analyzer = _bare_analyzer()
    analyzer.grounding = FakeGrounding({
        'score': 0,
        'reason': 'No Gemini API Key',
        'themes': [],
        'source': 'none',
    })
    analyzer.deepseek = FakeProvider({'score': 0, 'reason': 'No DeepSeek Client', 'themes': []})
    analyzer.claude = FakeProvider({'score': 0, 'reason': 'No Claude Client', 'themes': []})
    analyzer.openai = FakeProvider({'score': 0, 'reason': '확인된 호재가 제한적입니다.', 'themes': []})

    result = asyncio.run(analyzer.analyze_news_sentiment('테스트종목', [{'title': '중립', 'summary': '중립'}]))

    assert result['source'] == 'openai_fallback'
    assert result['score'] == 0
    assert analyzer.deepseek.calls == 1
    assert analyzer.claude.calls == 1
    assert analyzer.openai.calls == 1
