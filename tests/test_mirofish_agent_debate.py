"""Phase 3B: 5-agent debate tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish import agent_debate as ad  # noqa: E402


@pytest.fixture
def mock_brain():
    return {
        'dimension_scores': {
            'macro_regime': {'score': 45, 'confidence': 0.9, 'evidence': 'phase=Late Cycle, VIX=22'},
            'event_risk': {'score': 60, 'confidence': 0.8, 'evidence': '2 alerts'},
            'sector_momentum': {'score': 80, 'confidence': 0.85, 'evidence': 'Late Cycle phase score=4.0'},
            'earnings_catalyst': {'score': 70, 'confidence': 0.7, 'evidence': '5 upcoming'},
            'ml_prediction': {'score': 75, 'confidence': 0.7, 'evidence': 'SPY bullish 75%'},
            'options_flow': {'score': 65, 'confidence': 0.8, 'evidence': 'bullish 60%'},
            'reversal_signal': {'score': 30, 'confidence': 0.5, 'evidence': '1 rotation'},
            'volatility': {'score': 55, 'confidence': 0.95, 'evidence': 'VIX=22'},
            'correlation_stability': {'score': 70, 'confidence': 0.7, 'evidence': '2 high pairs'},
            'liquidity': {'score': 65, 'confidence': 0.6, 'evidence': 'volume normal'},
            'narrative': {'score': 60, 'confidence': 0.65, 'evidence': 'BUY signal'},
        }
    }


def test_five_agent_profiles_defined():
    assert len(ad.AGENT_PROFILES) == 5
    expected = {'kim_risk', 'park_momentum', 'lee_quant', 'choi_contrarian', 'jung_hedge'}
    actual = {p['id'] for p in ad.AGENT_PROFILES}
    assert actual == expected


def test_each_profile_has_required_fields():
    required = {'id', 'name', 'icon', 'role', 'bias', 'focus', 'persona'}
    for p in ad.AGENT_PROFILES:
        assert set(p.keys()) >= required


def test_run_debate_rule_based_5_agents_per_round(mock_brain):
    out = ad.run_debate('TEST_TARGET', mock_brain, rounds=2, use_llm=False)
    assert out['method'] in ('rule', 'mixed')
    assert len(out['rounds']) == 2
    for r in out['rounds']:
        assert len(r['messages']) == 5  # 5 agents


def test_each_message_cites_at_least_one_dimension(mock_brain):
    out = ad.run_debate('SAMSUNG', mock_brain, rounds=1, use_llm=False)
    for r in out['rounds']:
        for msg in r['messages']:
            assert len(msg['cited_dimensions']) >= 1, \
                f"Agent {msg['agent_id']} did not cite any dimension"


def test_message_contains_cited_score(mock_brain):
    """발언 텍스트에 실제 수치가 포함되는지 (MD 강제 규칙)."""
    out = ad.run_debate('TEST', mock_brain, rounds=1, use_llm=False)
    for r in out['rounds']:
        for msg in r['messages']:
            # 메시지에 cited_dimensions 의 score 가 텍스트로 포함되어야 함
            cited = msg['cited_dimensions']
            if cited:
                # 적어도 하나의 점수가 메시지에 있는지
                dim_name = cited[0]
                dim_data = mock_brain['dimension_scores'].get(dim_name, {})
                score = dim_data.get('score')
                if score is not None:
                    assert str(score) in msg['message'], \
                        f"Score {score} not in message: {msg['message']}"


def test_bearish_agent_tends_to_lower_score_situations(mock_brain):
    """김리스크는 macro_regime=45 (낮음) 상황에서 SELL/HOLD 경향."""
    out = ad.run_debate('TEST', mock_brain, rounds=1, use_llm=False)
    kim = next(m for m in out['rounds'][0]['messages'] if m['agent_id'] == 'kim_risk')
    assert kim['stance'] in ('SELL', 'HOLD')


def test_bullish_agent_with_high_momentum_buys(mock_brain):
    """박모멘텀은 sector_momentum=80 상황에서 BUY 경향."""
    out = ad.run_debate('TEST', mock_brain, rounds=1, use_llm=False)
    park = next(m for m in out['rounds'][0]['messages'] if m['agent_id'] == 'park_momentum')
    assert park['stance'] == 'BUY'


def test_consensus_synthesizes_majority_action(mock_brain):
    out = ad.run_debate('TEST', mock_brain, rounds=2, use_llm=False)
    consensus = out['final_consensus']
    assert consensus['action'] in ('BUY', 'SELL', 'HOLD')
    assert 0.0 <= consensus['confidence'] <= 1.0
    assert isinstance(consensus['split'], dict)


def test_rounds_capped_at_4():
    fake_brain = {'dimension_scores': {'macro_regime': {'score': 50, 'evidence': ''}}}
    out = ad.run_debate('X', fake_brain, rounds=10, use_llm=False)
    assert len(out['rounds']) <= 4


def test_empty_brain_handled_gracefully():
    out = ad.run_debate('X', {}, rounds=1, use_llm=False)
    assert len(out['rounds']) == 1
    # 메시지는 있을 수 있음 (보류 메시지)


def test_validate_debate_drops_no_dimension_messages():
    raw = [{
        'round': 1,
        'messages': [
            {'agent_id': 'a', 'cited_dimensions': ['macro_regime'], 'stance': 'BUY'},
            {'agent_id': 'b', 'cited_dimensions': []},  # drop (no citation)
            {'agent_id': 'c', 'cited_dimensions': ['event_risk'], 'stance': 'HOLD'},
        ]
    }]
    out = ad._validate_debate(raw)
    assert len(out[0]['messages']) == 2  # b dropped


def test_normalize_stance_handles_variants():
    assert ad._normalize_stance('BUY') == 'BUY'
    assert ad._normalize_stance('strongly bullish') == 'BUY'
    assert ad._normalize_stance('bear') == 'SELL'
    assert ad._normalize_stance(None) == 'HOLD'
    assert ad._normalize_stance('weird') == 'HOLD'


def test_clamp_float_bounds():
    assert ad._clamp_float(1.5) == 1.0
    assert ad._clamp_float(-0.3) == 0.0
    assert ad._clamp_float('not_a_number') == 0.5
