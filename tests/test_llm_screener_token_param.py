"""OpenAI 호환 스크리너의 토큰 한도 파라미터 협상 테스트.

2026-08-05: 계정에 gpt-4o 가 없어(보유: gpt-5.5) 모델을 바꿨더니 이번에는
"Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens'" 로
OpenAI 스크리너가 통째로 실패했다. 모델명으로 분기하면 모델이 바뀔 때마다
같은 자리에서 다시 깨진다.
"""
import pytest

from engine.llm_analyzer import BaseScreener


class _Recorder:
    """chat.completions.create 호출을 기록하는 최소 더블."""

    def __init__(self, reject_max_tokens: bool):
        self.reject = reject_max_tokens
        self.calls = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject and 'max_tokens' in kwargs:
            raise RuntimeError(
                "Error code: 400 - Unsupported parameter: 'max_tokens' is not "
                "supported with this model. Use 'max_completion_tokens' instead."
            )
        return 'response'


@pytest.mark.asyncio
async def test_legacy_model_keeps_max_tokens():
    client = _Recorder(reject_max_tokens=False)

    got = await BaseScreener()._chat_with_token_limit(
        client, model='gpt-4o', messages=[], max_output_tokens=4096)

    assert got == 'response'
    assert len(client.calls) == 1
    assert client.calls[0]['max_tokens'] == 4096


@pytest.mark.asyncio
async def test_new_model_retries_with_max_completion_tokens():
    client = _Recorder(reject_max_tokens=True)

    got = await BaseScreener()._chat_with_token_limit(
        client, model='gpt-5.5', messages=[], max_output_tokens=4096)

    assert got == 'response'
    assert len(client.calls) == 2
    assert 'max_tokens' not in client.calls[1]
    assert client.calls[1]['max_completion_tokens'] == 4096


@pytest.mark.asyncio
async def test_unrelated_errors_are_not_swallowed():
    """인증 실패·모델 없음까지 재시도로 삼키면 진짜 장애가 조용해진다."""
    class _Broken(_Recorder):
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError('Error code: 401 - invalid api key')

    client = _Broken(reject_max_tokens=False)

    with pytest.raises(RuntimeError, match='401'):
        await BaseScreener()._chat_with_token_limit(
            client, model='gpt-5.5', messages=[], max_output_tokens=4096)

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_extra_kwargs_survive_the_retry():
    """response_format 을 잃으면 JSON 파싱이 깨진다."""
    client = _Recorder(reject_max_tokens=True)

    await BaseScreener()._chat_with_token_limit(
        client, model='gpt-5.5', messages=[], max_output_tokens=4096,
        response_format={'type': 'json_object'})

    assert client.calls[1]['response_format'] == {'type': 'json_object'}
