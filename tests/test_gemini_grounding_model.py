"""Gemini Grounding 모델 지정 테스트.

2026-08-05: gemini-2.0-flash 가 폐기(HTTP 404 "no longer available")됐는데
모델명이 하드코딩돼 있어, 전 종목의 실시간 검색 뉴스 분석이 조용히 DeepSeek
폴백으로 넘어갔다. 폴백에는 웹 검색이 없으므로 분석의 근거 자체가 달라진다.
스크리너는 이미 gemini-2.5-flash 를 쓰고 있어 멀쩡했고, 그래서 더 안 보였다.
"""
import pytest

from engine.llm_analyzer import GeminiGroundingClient


def test_default_model_is_not_the_retired_one():
    assert GeminiGroundingClient.DEFAULT_MODEL != 'gemini-2.0-flash'


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
        def json(self): return {'candidates': [{'content': {'parts': [
            {'text': '{"score":1,"reason":"x","themes":[],"news_summary":"y"}'}]}}]}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            captured['url'] = url
            captured['body'] = json
            return _Resp()

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **k: _Client())
    asyncio.run(client.search_and_analyze('삼성전자'))
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
