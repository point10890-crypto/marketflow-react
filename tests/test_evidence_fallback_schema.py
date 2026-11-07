import json
from types import SimpleNamespace

import pytest

from app.services.ai_routing.contracts import Operation, RoutingRequest
from app.services.ai_routing.providers import OpenAICompatibleAdapter


@pytest.mark.parametrize('provider,model', [('deepseek', 'deepseek-v4-flash'), ('openai', 'gpt-5.5')])
def test_fallback_receives_the_exact_evidence_schema(provider, model):
    sent = []
    def create(**kwargs):
        sent.append(kwargs)
        return {'choices': [{'message': {'content': '{"rows":[]}'}}],
                'usage': {'prompt_tokens': 25, 'completion_tokens': 5, 'total_tokens': 30}}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    adapter = OpenAICompatibleAdapter(lambda: client, provider=provider)
    schema = {'type': 'object', 'properties': {'rows': {'type': 'array', 'items': {'type': 'string'}}},
              'required': ['rows'], 'additionalProperties': False}
    adapter.generate(RoutingRequest(operation=Operation.NEWS_EVENT_EXTRACT, system='Use evidence only.',
        prompt='Public source evidence.', json_mode=True, response_schema=schema), model=model, max_output_tokens=128)
    system = next(message['content'] for message in sent[0]['messages'] if message['role'] == 'system')
    assert 'Use evidence only.' in system
    assert json.dumps(schema, ensure_ascii=False, separators=(',', ':')) in system
    assert sent[0]['response_format'] == {'type': 'json_object'}


def test_legacy_provider_prompt_is_unchanged():
    sent = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs:
        sent.append(kwargs) or {'choices': [{'message': {'content': '{}'}}]})))
    OpenAICompatibleAdapter(lambda: client, provider='deepseek').generate(
        RoutingRequest(operation=Operation.BULK_TEXT, system='Existing system', prompt='JSON',
                       response_schema={'type':'object'}, json_mode=True), model='deepseek-v4-flash', max_output_tokens=128)
    assert sent[0]['messages'][0]['content'] == 'Existing system'
