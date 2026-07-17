"""Unit tests for the bull/bear research debate layer.

Covers the deterministic rule path (the manager math later tasks rely on) and
the round-clamp contract. LLM path falls back per-piece to these rules, so the
rule math is the load-bearing contract.
"""

from app.services.mirofish.tradingagents import research_debate

REPORTS = [
    {'role': 'fundamentals', 'stance': 'bullish', 'score': 30, 'summary': 'PER 저평가', 'evidence': []},
    {'role': 'news', 'stance': 'bullish', 'score': 40, 'summary': '수주 계약', 'evidence': []},
    {'role': 'sentiment', 'stance': 'neutral', 'score': 5, 'summary': '중립', 'evidence': []},
    {'role': 'technical', 'stance': 'bullish', 'score': 50, 'summary': '정배열 신고가', 'evidence': []},
]

BEAR_REPORTS = [
    {'role': 'fundamentals', 'stance': 'bearish', 'score': -30, 'summary': '고평가', 'evidence': []},
    {'role': 'news', 'stance': 'bearish', 'score': -40, 'summary': '소송 리스크', 'evidence': []},
    {'role': 'sentiment', 'stance': 'bearish', 'score': -25, 'summary': '투심 악화', 'evidence': []},
    {'role': 'technical', 'stance': 'bearish', 'score': -50, 'summary': '역배열 붕괴', 'evidence': []},
]


def test_rule_debate_structure_and_bull_win():
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=2, use_llm=False)
    assert len(result['rounds']) == 2
    for rnd in result['rounds']:
        assert isinstance(rnd['round'], int)
        assert rnd['bull']['message'] and rnd['bear']['message']
    assert result['manager']['stance'] == 'bull'          # mean=31.25 > 10
    assert 50 <= result['manager']['confidence'] <= 95    # 50+31.25/2 ≈ 65.6
    assert result['bull_case'] and result['bear_case']
    assert result['method'] == 'rule'


def test_rounds_clamped():
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=99, use_llm=False)
    assert len(result['rounds']) == 4


def test_rounds_clamped_low():
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=0, use_llm=False)
    assert len(result['rounds']) == 1


def test_rule_debate_bear_win():
    result = research_debate.run_research_debate('삼성전자', BEAR_REPORTS, rounds=2, use_llm=False)
    # mean = (-30-40-25-50)/4 = -36.25 < -10 → bear
    assert result['manager']['stance'] == 'bear'
    assert result['manager']['confidence'] == round(min(95, 50 + 36.25 / 2), 2)
    assert result['method'] == 'rule'


def test_manager_neutral_band():
    flat = [dict(r, score=s, stance='neutral')
            for r, s in zip(REPORTS, [5, -5, 8, -3])]
    result = research_debate.run_research_debate('t', flat, rounds=1, use_llm=False)
    # mean = 1.25 → within (-10, 10) → neutral
    assert result['manager']['stance'] == 'neutral'


def test_manager_confidence_math_exact():
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=2, use_llm=False)
    # mean = 31.25, confidence = min(95, 50 + 31.25/2) = 65.62 (rounded)
    assert result['manager']['confidence'] == round(50 + 31.25 / 2, 2)


def _fake_by_system(mapping, default=None):
    """Build a generate_text stub that dispatches on the `system` kwarg."""
    def fake(prompt, **kwargs):
        system = kwargs.get('system') or ''
        for token, response in mapping.items():
            if token in system:
                return response
        return default
    return fake


def test_llm_full_success_method_llm(monkeypatch):
    fake = _fake_by_system({
        '리서치 매니저': '{"stance": "bull", "thesis": "강세 우위", "confidence": 72}',
        'Bull': '{"message": "강세 LLM 근거 발언"}',
        'Bear': '{"message": "약세 LLM 근거 발언"}',
    })
    monkeypatch.setattr(research_debate.llm_client, 'generate_text', fake)
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=1, use_llm=True)
    assert result['method'] == 'llm'
    assert result['manager']['stance'] == 'bull'
    assert result['manager']['confidence'] == 72.0
    assert result['rounds'][0]['bull']['message'] == '강세 LLM 근거 발언'


def test_llm_partial_failure_method_mixed(monkeypatch):
    # Bear call returns None → that piece falls back to rule → method='mixed'.
    fake = _fake_by_system({
        '리서치 매니저': '{"stance": "bull", "thesis": "t", "confidence": 60}',
        'Bull': '{"message": "강세 LLM 발언"}',
        'Bear': None,
    })
    monkeypatch.setattr(research_debate.llm_client, 'generate_text', fake)
    result = research_debate.run_research_debate('삼성전자', REPORTS, rounds=1, use_llm=True)
    assert result['method'] == 'mixed'
    # bull came from LLM, bear fell back to the rule composer
    assert result['rounds'][0]['bull']['message'] == '강세 LLM 발언'
    assert result['rounds'][0]['bear']['message'].startswith('[약세론 R1]')
