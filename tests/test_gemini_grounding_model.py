"""Gemini Grounding 모델 지정 테스트.

2026-08-05: gemini-2.0-flash 가 폐기(HTTP 404 "no longer available")됐는데
모델명이 하드코딩돼 있어, 전 종목의 실시간 검색 뉴스 분석이 조용히 DeepSeek
폴백으로 넘어갔다. 폴백에는 웹 검색이 없으므로 분석의 근거 자체가 달라진다.
스크리너는 이미 gemini-2.5-flash 를 쓰고 있어 멀쩡했고, 그래서 더 안 보였다.
"""
import asyncio

import pytest

from app.services.ai_routing.budget import BudgetLimits, BudgetManager
from app.services.ai_routing.store import RoutingStore
from engine import llm_analyzer as llm_analyzer_module
from engine.llm_analyzer import GeminiAnalyzer, GeminiGroundingClient


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
