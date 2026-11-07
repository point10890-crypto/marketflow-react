import json

import pytest

from app.services.ai_routing.contracts import RoutingRequest, Operation
from app.services.ai_routing.validation import validate_response
from app.services.mirofish.tradingagents import trader_risk


@pytest.mark.parametrize('mean', [31.25, -11.125, 100 / 3])
@pytest.mark.parametrize('compact', [False, True])
def test_pm_exact_numeric_contract_survives_prompt_compaction(monkeypatch, mean, compact):
    def fake(prompt, **kwargs):
        marker = '[고정 출력 값]\n'
        assert marker in prompt
        fixed = json.loads(prompt.split(marker)[1].splitlines()[0])
        assert fixed['analyst_mean'] == kwargs['expected_numbers']['analyst_mean'] == mean
        data = {**fixed, 'verdict': 'HOLD', 'confidence': 50, 'reasoning': '검증된 숫자 보존'}
        raw = json.dumps(data)
        result = validate_response(raw, RoutingRequest(operation=Operation.DECISIVE_TEXT,
            prompt=prompt, json_mode=True, expected_numbers=kwargs['expected_numbers']))
        assert result.valid
        return raw, {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}

    monkeypatch.setattr(trader_risk.llm_client, 'generate_text_with_metadata', fake)
    decision, _ = trader_risk._llm_pm('삼성전자', {'_analyst_mean': mean, 'bull_case': '근거' * 10000},
        {}, [], {}, symbol='005930', market='KOSPI', name='삼성전자',
        evidence_packet={'large': '검증자료' * 10000}, compact=compact)
    assert decision['verdict'] == 'HOLD'
