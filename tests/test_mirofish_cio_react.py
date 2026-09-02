"""Phase 4B: ReACT CIO tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish import cio_react as cr  # noqa: E402


@pytest.fixture
def mock_brain():
    return {
        'alignment_score': 0.62,
        'regime': 'constructive_accumulation',
        'dimension_scores': {
            'macro_regime': {'score': 60, 'confidence': 0.9, 'evidence': 'phase=Mid Cycle'},
            'sector_momentum': {'score': 78, 'confidence': 0.85, 'evidence': 'XLK strong'},
            'event_risk': {'score': 35, 'confidence': 0.8, 'evidence': '3 alerts'},
            'ml_prediction': {'score': 75, 'confidence': 0.7, 'evidence': 'SPY bullish'},
            'options_flow': {'score': 65, 'confidence': 0.8, 'evidence': 'bullish 60%'},
        }
    }


@pytest.fixture
def mock_debate():
    return {
        'rounds': [
            {'round': 1, 'messages': [
                {'agent_id': 'kim_risk', 'agent_name': '김리스크', 'stance': 'HOLD',
                 'confidence': 0.6, 'message': 'event_risk=35 우려.', 'cited_dimensions': ['event_risk']},
                {'agent_id': 'park_momentum', 'agent_name': '박모멘텀', 'stance': 'BUY',
                 'confidence': 0.78, 'message': 'sector_momentum=78 강함.', 'cited_dimensions': ['sector_momentum']},
                {'agent_id': 'lee_quant', 'agent_name': '이퀀트', 'stance': 'BUY',
                 'confidence': 0.7, 'message': 'ml_prediction=75.', 'cited_dimensions': ['ml_prediction']},
            ]},
        ],
        'final_consensus': {'action': 'BUY', 'confidence': 0.69, 'split': {'BUY': 2, 'HOLD': 1}},
    }


def test_run_cio_returns_required_fields(mock_brain, mock_debate):
    out = cr.run_cio('TEST', mock_brain, mock_debate, use_llm=False)
    assert 'trace' in out
    assert 'final_answer' in out
    assert out['method'] in ('rule', 'mixed')
    assert out['loops_used'] >= cr.MIN_LOOPS


def test_final_answer_has_required_fields(mock_brain, mock_debate):
    out = cr.run_cio('TEST', mock_brain, mock_debate, use_llm=False)
    fa = out['final_answer']
    assert fa['action'] in ('BUY', 'HOLD', 'SELL')
    assert 0.0 <= fa['confidence'] <= 1.0
    assert 0.0 <= fa['allocation_pct'] <= 100.0
    assert isinstance(fa['reasoning'], str)
    assert isinstance(fa['opposing_scenario'], str)


def test_trace_loops_have_thought_action_observation(mock_brain, mock_debate):
    out = cr.run_cio('TEST', mock_brain, mock_debate, use_llm=False)
    for step in out['trace']:
        assert 'thought' in step
        assert 'action' in step
        assert 'observation' in step
        assert 'tool' in step['action']


def test_query_brain_tool(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['query_brain']({'dimension': 'macro_regime'})
    assert obs['score'] == 60
    assert obs['confidence'] == 0.9


def test_query_brain_missing_dimension(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['query_brain']({'dimension': 'nonexistent'})
    assert 'error' in obs
    assert 'available' in obs


def test_interview_agent_tool(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['interview_agent']({'agent_id': 'park_momentum'})
    assert obs['agent_name'] == '박모멘텀'
    assert obs['stance'] == 'BUY'


def test_interview_missing_agent(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['interview_agent']({'agent_id': 'unknown'})
    assert 'error' in obs


def test_insight_forge_returns_high_low_dims(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['insight_forge']({})
    assert 'sector_momentum' in obs['key_dimensions_above_70']
    assert 'event_risk' not in obs['key_dimensions_above_70']
    # event_risk=35 not below 30, ml=75 not below
    # 5개 모두 30 이상 — below_30 빈 list 가능


def test_final_answer_clamps_confidence(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['final_answer']({'action': 'BUY', 'confidence': 1.5, 'allocation_pct': 200})
    assert obs['confidence'] == 1.0
    assert obs['allocation_pct'] == 100.0


def test_final_answer_normalizes_invalid_action(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['final_answer']({'action': 'WEIRD', 'confidence': 0.5, 'allocation_pct': 10})
    assert obs['action'] == 'HOLD'


def test_check_history_runs(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    obs = tools['check_history']({})
    assert 'total_runs' in obs


def test_seven_tools_registered(mock_brain, mock_debate):
    tools = cr._build_tools(mock_brain, mock_debate)
    expected = {'query_brain', 'search_graph', 'check_history', 'interview_agent',
                'insight_forge', 'panorama_search', 'final_answer'}
    assert set(tools.keys()) == expected


def test_max_loops_capped(mock_brain, mock_debate):
    out = cr.run_cio('TEST', mock_brain, mock_debate, use_llm=False)
    assert out['loops_used'] <= cr.MAX_LOOPS


def test_pick_top_confidence_agent(mock_debate):
    agent_id = cr._pick_top_confidence_agent(mock_debate)
    # park_momentum has highest confidence (0.78)
    assert agent_id == 'park_momentum'


def test_consensus_buy_results_in_buy_action(mock_brain, mock_debate):
    """토론 BUY → CIO 도 BUY."""
    out = cr.run_cio('TEST', mock_brain, mock_debate, use_llm=False)
    assert out['final_answer']['action'] == 'BUY'


def test_llm_exhaustion_keeps_rule_buy_diagnostic_only(monkeypatch, mock_brain, mock_debate):
    monkeypatch.setattr(
        'app.services.mirofish.llm_client.generate_text_with_metadata',
        lambda *args, **kwargs: (None, {
            'success': False, 'analysis_status': 'HOLD_REVIEW',
            'attempts': [{'provider': 'deepseek'}, {'provider': 'openai'}],
        }),
    )
    out = cr.run_cio(
        '삼성전자', mock_brain, mock_debate, use_llm=True,
        run_id='mf_1', symbol='005930', market='KOSPI',
    )
    assert out['analysis_status'] == 'HOLD_REVIEW'
    assert out['final_answer']['action'] == 'HOLD_REVIEW'
    assert out['rule_candidate_verdict']['action'] == 'BUY'
    assert out['llm']['attempts'] == [{'provider': 'deepseek'}, {'provider': 'openai'}]
