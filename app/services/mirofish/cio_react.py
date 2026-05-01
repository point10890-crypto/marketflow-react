"""ReACT CIO 추론 엔진 — 7개 Action Tool + Thought→Action→Observation 루프.

MD 명세 7가지 Action Tools:
1. query_brain: 차원별 스코어/신뢰도 조회
2. search_graph: EKG 인과 체인 BFS 탐색
3. check_history: 과거 예측 적중률 검증
4. interview_agent: 특정 에이전트에게 추가 논거 요구
5. insight_forge: 복합 질문 분할 및 통합 검색
6. panorama_search: 특정 시간 필터 및 깊은 BFS (Depth 4) 탐색
7. final_answer: 확신도 및 자산 배분 비율을 포함한 최종 결론
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

# ─── Public API ────────────────────────────────────────────

MAX_LOOPS = int(os.getenv('MIROFISH_REACT_MAX_LOOPS', '5'))
MIN_LOOPS = 3  # MD 명세: 최소 3회


def run_cio(
    target: str,
    brain_snapshot: dict[str, Any],
    debate_result: dict[str, Any],
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    """ReACT CIO 루프 실행.

    Returns:
        {
            'target': str,
            'trace': [{'loop': N, 'thought': str, 'action': {tool, args},
                      'observation': dict}, ...],
            'final_answer': {'action': BUY|HOLD|SELL, 'confidence': float,
                             'allocation_pct': float, 'reasoning': str,
                             'opposing_scenario': str},
            'method': 'llm' | 'rule',
            'loops_used': int,
        }
    """
    # 도구 함수 binding (closure 로 brain/debate 컨텍스트 유지)
    tools = _build_tools(brain_snapshot, debate_result)

    method = 'rule'
    trace: list[dict] = []
    final_answer: dict | None = None

    if use_llm:
        try:
            llm_trace, llm_final = _run_with_gemini(target, brain_snapshot, debate_result, tools)
            if llm_final:
                trace = llm_trace
                final_answer = llm_final
                method = 'llm'
        except Exception:
            method = 'rule'

    if final_answer is None:
        trace, final_answer = _run_with_rules(target, brain_snapshot, debate_result, tools)
        method = 'rule' if method != 'llm' else 'mixed'

    return {
        'target': target,
        'trace': trace,
        'final_answer': final_answer,
        'method': method,
        'loops_used': len(trace),
        'completed_at': datetime.now(timezone.utc).isoformat(),
    }


# ─── Tool implementations ──────────────────────────────────

def _build_tools(brain: dict, debate: dict) -> dict[str, Callable]:
    """7개 tool 함수 — 각각 dict args 받고 dict observation 반환."""

    def query_brain(args: dict) -> dict:
        dim_name = (args or {}).get('dimension', '')
        dim_scores = brain.get('dimension_scores', {}) or {}
        dim = dim_scores.get(dim_name)
        if not dim:
            return {'error': f'dimension {dim_name!r} not found',
                    'available': list(dim_scores.keys())}
        return {
            'dimension': dim_name,
            'score': dim.get('score'),
            'confidence': dim.get('confidence'),
            'evidence': dim.get('evidence'),
        }

    def search_graph(args: dict) -> dict:
        from app.services.mirofish import graphrag_extractor as gr
        start = (args or {}).get('start_entity_id', '')
        depth = int((args or {}).get('max_depth', 3))
        if not start:
            return {'error': 'start_entity_id required'}
        chains = gr.search_causal_chain(start, max_depth=depth)
        return {
            'start': start,
            'chains_found': len(chains),
            'sample_chains': chains[:3],
        }

    def check_history(args: dict) -> dict:
        """과거 jongga_v2 예측 적중률 (간소화 — 결과 파일 카운트 + 평균 grade)."""
        history_dir = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')),
            'data',
        )
        files = [f for f in os.listdir(history_dir)
                 if f.startswith('jongga_v2_results_') and f.endswith('.json')] \
            if os.path.isdir(history_dir) else []
        return {
            'total_runs': len(files),
            'recent_runs': sorted(files)[-5:],
            'note': 'simplified — actual hit rate requires backtest pipeline',
        }

    def interview_agent(args: dict) -> dict:
        agent_id = (args or {}).get('agent_id', '')
        rounds = debate.get('rounds', []) or []
        # 마지막 라운드의 해당 agent 발언
        for r in reversed(rounds):
            for msg in r.get('messages', []):
                if msg.get('agent_id') == agent_id:
                    return {
                        'agent_id': agent_id,
                        'agent_name': msg.get('agent_name'),
                        'stance': msg.get('stance'),
                        'confidence': msg.get('confidence'),
                        'message': msg.get('message'),
                        'cited_dimensions': msg.get('cited_dimensions', []),
                    }
        return {'error': f'agent {agent_id!r} not found in debate'}

    def insight_forge(args: dict) -> dict:
        """복합 질문 분할 — 단순화: brain + debate 핵심 키워드 통합."""
        consensus = debate.get('final_consensus', {}) or {}
        regime = brain.get('regime', 'unknown')
        alignment = brain.get('alignment_score', 0)
        return {
            'regime': regime,
            'alignment_score': alignment,
            'debate_consensus': consensus,
            'key_dimensions_above_70': [
                k for k, v in (brain.get('dimension_scores', {}) or {}).items()
                if isinstance(v, dict) and (v.get('score') or 0) >= 70
            ],
            'key_dimensions_below_30': [
                k for k, v in (brain.get('dimension_scores', {}) or {}).items()
                if isinstance(v, dict) and (v.get('score') is not None) and v['score'] < 30
            ],
        }

    def panorama_search(args: dict) -> dict:
        """깊은 BFS (depth 4) — 시간 필터는 EKG에 timestamp 없으므로 스킵."""
        from app.services.mirofish import graphrag_extractor as gr
        start = (args or {}).get('start_entity_id', '')
        if not start:
            stats = gr.get_ekg_stats()
            return {
                'overview': True,
                'total_entities': stats.get('total_entities', 0),
                'entity_types': stats.get('entity_types', []),
            }
        chains = gr.search_causal_chain(start, max_depth=4)
        return {
            'start': start,
            'depth': 4,
            'chains_found': len(chains),
            'sample_chains': chains[:5],
        }

    def final_answer(args: dict) -> dict:
        """최종 결정 — args 검증 + return."""
        action = str((args or {}).get('action', 'HOLD')).upper()
        if action not in {'BUY', 'SELL', 'HOLD'}:
            action = 'HOLD'
        try:
            confidence = float((args or {}).get('confidence', 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5
        try:
            alloc = float((args or {}).get('allocation_pct', 0))
            alloc = max(0.0, min(100.0, alloc))
        except (TypeError, ValueError):
            alloc = 0.0
        return {
            'action': action,
            'confidence': round(confidence, 3),
            'allocation_pct': round(alloc, 1),
            'reasoning': str((args or {}).get('reasoning', ''))[:1000],
            'opposing_scenario': str((args or {}).get('opposing_scenario', ''))[:500],
        }

    return {
        'query_brain': query_brain,
        'search_graph': search_graph,
        'check_history': check_history,
        'interview_agent': interview_agent,
        'insight_forge': insight_forge,
        'panorama_search': panorama_search,
        'final_answer': final_answer,
    }


# ─── Rule-based ReACT loop ─────────────────────────────────

def _run_with_rules(target: str, brain: dict, debate: dict,
                    tools: dict[str, Callable]) -> tuple[list[dict], dict]:
    """결정론적 ReACT — 미리 정의된 6단계 루프 + 합성."""
    trace: list[dict] = []

    # Loop 1: insight_forge — overview
    obs1 = tools['insight_forge']({})
    trace.append({
        'loop': 1,
        'thought': f'{target} 의 거시 정렬 상태와 토론 합의를 먼저 파악한다.',
        'action': {'tool': 'insight_forge', 'args': {}},
        'observation': obs1,
    })

    # Loop 2: query_brain — 가장 영향 큰 dimension
    high_dims = obs1.get('key_dimensions_above_70', [])
    low_dims = obs1.get('key_dimensions_below_30', [])
    target_dim = (high_dims + low_dims + ['macro_regime'])[0]
    obs2 = tools['query_brain']({'dimension': target_dim})
    trace.append({
        'loop': 2,
        'thought': f'{target_dim} 의 정확한 점수와 근거를 확인한다.',
        'action': {'tool': 'query_brain', 'args': {'dimension': target_dim}},
        'observation': obs2,
    })

    # Loop 3: interview_agent — 가장 확신도 높은 에이전트 인터뷰
    agent_id = _pick_top_confidence_agent(debate)
    if agent_id:
        obs3 = tools['interview_agent']({'agent_id': agent_id})
        trace.append({
            'loop': 3,
            'thought': f'가장 확신도 높은 에이전트({agent_id})에게 추가 근거를 요청한다.',
            'action': {'tool': 'interview_agent', 'args': {'agent_id': agent_id}},
            'observation': obs3,
        })

    # Loop 4: check_history — 과거 적중률
    obs4 = tools['check_history']({})
    trace.append({
        'loop': 4,
        'thought': '과거 예측 시스템의 신뢰도를 검증한다.',
        'action': {'tool': 'check_history', 'args': {}},
        'observation': obs4,
    })

    # Loop 5: final_answer — debate consensus + brain alignment 종합
    consensus = debate.get('final_consensus', {}) or {}
    cons_action = consensus.get('action', 'HOLD')
    cons_conf = consensus.get('confidence', 0.5)
    alignment = brain.get('alignment_score', 0.5)
    # CIO 자체 확신도 = 토론 합의 + brain alignment 평균
    final_conf = round((cons_conf + alignment) / 2, 3)
    # Allocation = action 따라
    if cons_action == 'BUY':
        alloc = min(40, final_conf * 50)
    elif cons_action == 'SELL':
        alloc = 0
    else:
        alloc = min(15, final_conf * 20)

    final_args = {
        'action': cons_action,
        'confidence': final_conf,
        'allocation_pct': alloc,
        'reasoning': (
            f"Brain alignment={alignment:.2f}, debate consensus={cons_action}({cons_conf:.2f}). "
            f"High-strength dims: {', '.join(high_dims[:3])}. Low: {', '.join(low_dims[:3])}."
        ),
        'opposing_scenario': (
            f"If {', '.join(low_dims[:2]) or 'risk metrics'} deteriorate further, "
            f"recommend reducing allocation by half."
        ),
    }
    obs5 = tools['final_answer'](final_args)
    trace.append({
        'loop': 5,
        'thought': 'Brain + 토론 + 과거 적중률을 종합하여 최종 결론을 제시한다.',
        'action': {'tool': 'final_answer', 'args': final_args},
        'observation': obs5,
    })

    return trace, obs5


def _pick_top_confidence_agent(debate: dict) -> str | None:
    rounds = debate.get('rounds', []) or []
    if not rounds:
        return None
    last = rounds[-1]
    msgs = last.get('messages', []) or []
    if not msgs:
        return None
    sorted_msgs = sorted(msgs, key=lambda m: m.get('confidence', 0), reverse=True)
    return sorted_msgs[0].get('agent_id') if sorted_msgs else None


# ─── Gemini LLM ReACT (function-calling style — simulated) ─

def _run_with_gemini(target: str, brain: dict, debate: dict,
                     tools: dict[str, Callable]) -> tuple[list[dict], dict | None]:
    """Gemini structured output — Thought/Action/Observation 시퀀스 생성.

    실제 function calling 대신 single-shot JSON 으로 trace 생성 후 tool 실행.
    """
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return [], None
    try:
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=api_key)
        prompt = _build_react_prompt(target, brain, debate)
        response = client.models.generate_content(
            model=os.getenv('MIROFISH_REACT_MODEL', 'gemini-2.5-flash'),
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type='application/json',
                temperature=0.4,
                max_output_tokens=4000,
            ),
        )
        plan = json.loads(response.text or '{}')
        steps = plan.get('steps', [])
        if not isinstance(steps, list) or len(steps) < MIN_LOOPS:
            return [], None

        # 각 step 의 action 을 실제 tool 로 실행
        trace: list[dict] = []
        final: dict | None = None
        for i, step in enumerate(steps[:MAX_LOOPS], start=1):
            if not isinstance(step, dict):
                continue
            action_obj = step.get('action', {})
            tool_name = action_obj.get('tool', '')
            args = action_obj.get('args', {}) if isinstance(action_obj.get('args'), dict) else {}
            if tool_name not in tools:
                continue
            obs = tools[tool_name](args)
            trace.append({
                'loop': i,
                'thought': str(step.get('thought', ''))[:500],
                'action': {'tool': tool_name, 'args': args},
                'observation': obs,
            })
            if tool_name == 'final_answer':
                final = obs
                break

        if final is None and trace:
            # 마지막에 final_answer 강제 호출
            consensus = debate.get('final_consensus', {}) or {}
            final = tools['final_answer']({
                'action': consensus.get('action', 'HOLD'),
                'confidence': consensus.get('confidence', 0.5),
                'allocation_pct': 10,
                'reasoning': 'LLM trace did not include final_answer; synthesized from debate.',
            })
            trace.append({
                'loop': len(trace) + 1,
                'thought': 'Synthesizing final answer from debate consensus.',
                'action': {'tool': 'final_answer', 'args': {}},
                'observation': final,
            })

        return trace, final
    except Exception:
        return [], None


def _build_react_prompt(target: str, brain: dict, debate: dict) -> str:
    consensus = debate.get('final_consensus', {}) or {}
    return f"""당신은 CIO (최고투자책임자) 역할. ReACT 루프로 {target} 에 대한 최종 투자 판단을 내리세요.

가용 도구 (7개):
1. query_brain(dimension: str) — 13D 차원 점수 조회
2. search_graph(start_entity_id, max_depth=3) — EKG BFS
3. check_history() — 과거 예측 적중률
4. interview_agent(agent_id) — 5인 에이전트 추가 인터뷰
5. insight_forge() — overview 통합
6. panorama_search(start_entity_id, max_depth=4) — 깊은 그래프 탐색
7. final_answer(action, confidence, allocation_pct, reasoning, opposing_scenario)

Brain alignment: {brain.get('alignment_score', '?')}, regime: {brain.get('regime', '?')}
Debate consensus: {consensus}

JSON 출력:
{{
  "steps": [
    {{"thought": "...", "action": {{"tool": "insight_forge", "args": {{}}}}}},
    {{"thought": "...", "action": {{"tool": "query_brain", "args": {{"dimension": "macro_regime"}}}}}},
    {{"thought": "...", "action": {{"tool": "interview_agent", "args": {{"agent_id": "kim_risk"}}}}}},
    {{"thought": "...", "action": {{"tool": "final_answer", "args": {{
      "action": "BUY|HOLD|SELL", "confidence": 0.0~1.0, "allocation_pct": 0~50,
      "reasoning": "...", "opposing_scenario": "..."}}}}}}
  ]
}}

규칙:
- 최소 3 step, 최대 5 step
- 마지막 step 은 반드시 final_answer
"""
