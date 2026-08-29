# -*- coding: utf-8 -*-
"""딥검증 판정의 재현성 계약.

실측(2026-08-29, 종목 2 x 반복 5): stance 는 10/10 안정적이었으나 confidence 가
temp=0.3 에서 +-5 (표준편차 2.23) 흔들렸다. 매니저 판정은 기계가 소비하는 값
(decision_brief 근거, TA 가점, SELL 제외 임계 65)이므로 결정론적으로 생성한다.
토론 메시지는 논거 다양성이 유용하므로 확률적 생성을 유지한다.
"""
from app.services.mirofish.tradingagents import research_debate as rd


def _capture(monkeypatch):
    calls = []

    def fake(prompt, **kwargs):
        calls.append(kwargs)
        role = kwargs.get('system') or ''
        if 'MANAGER' in str(role) or rd._MANAGER_SYSTEM == role:
            return '{"stance": "bull", "thesis": "t", "confidence": 70}', {}
        return '{"message": "m"}', {}

    monkeypatch.setattr(rd.llm_client, 'generate_text_with_metadata', fake)
    return calls


def test_manager_verdict_is_deterministic(monkeypatch):
    calls = _capture(monkeypatch)
    rd.run_research_debate('005930', [{'role': 'technical', 'stance': 'bullish',
                                       'score': 20.0, 'summary': 's'}],
                           rounds=1, use_llm=True)
    manager = [c for c in calls if c.get('system') == rd._MANAGER_SYSTEM]
    assert manager, '매니저 판정 호출이 있어야 한다'
    assert manager[0]['temperature'] == 0.0


def test_debate_messages_keep_exploratory_temperature(monkeypatch):
    calls = _capture(monkeypatch)
    rd.run_research_debate('005930', [{'role': 'technical', 'stance': 'bullish',
                                       'score': 20.0, 'summary': 's'}],
                           rounds=1, use_llm=True)
    debate = [c for c in calls if c.get('system') != rd._MANAGER_SYSTEM]
    assert debate, '토론 메시지 호출이 있어야 한다'
    assert all(c['temperature'] > 0 for c in debate)
