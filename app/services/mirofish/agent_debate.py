"""Multi-agent 5인 토론 — 김리스크/박모멘텀/이퀀트/최역발상/정헤지.

각 발언에는 Brain 13D dimension 수치 1개 이상 인용 강제.
LLM 실패 시 결정론적 fallback (Brain dimension 직접 reading).
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from typing import Any

# ─── 5인 페르소나 정의 (MD 명세) ─────────────────────────────
AGENT_PROFILES = [
    {
        'id': 'kim_risk',
        'name': '김리스크',
        'icon': '🐻',
        'role': '글로벌 매크로 전략가',
        'bias': 'Bearish',
        'focus': ['macro_regime', 'event_risk', 'volatility'],
        'persona': '거시 위험을 중시하며 보수적이고 신중한 입장. 시장의 균열을 먼저 발견.',
    },
    {
        'id': 'park_momentum',
        'name': '박모멘텀',
        'icon': '🐂',
        'role': '시장 모멘텀 트레이더',
        'bias': 'Bullish',
        'focus': ['sector_momentum', 'earnings_catalyst', 'narrative'],
        'persona': '추세를 따라가는 공격형. 거래량과 실적 모멘텀을 핵심으로 봄.',
    },
    {
        'id': 'lee_quant',
        'name': '이퀀트',
        'icon': '🤖',
        'role': '시스템 트레이딩 퀀트',
        'bias': 'Quant',
        'focus': ['ml_prediction', 'options_flow', 'correlation_stability'],
        'persona': '데이터에만 의존. 모델 예측과 옵션 시장 신호 우선.',
    },
    {
        'id': 'choi_contrarian',
        'name': '최역발상',
        'icon': '🔄',
        'role': '역발상 전략가',
        'bias': 'Contrarian',
        'focus': ['reversal_signal', 'crypto_sentiment', 'narrative'],
        'persona': '컨센서스를 의심. 과매수/과매도 극단에서 반대 포지션 선호.',
    },
    {
        'id': 'jung_hedge',
        'name': '정헤지',
        'icon': '🛡️',
        'role': '리스크 관리자',
        'bias': 'Neutral',
        'focus': ['correlation_stability', 'event_risk', 'liquidity'],
        'persona': '포트폴리오 안정성 우선. 균형 잡힌 헤지 전략 제시.',
    },
]


# ─── Public API ───────────────────────────────────────────

def run_debate(
    target: str,
    brain_snapshot: dict[str, Any],
    rounds: int = 2,
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    """5인 라운드별 토론.

    Returns:
        {
            'target': str,
            'rounds': [{'round': 1, 'messages': [{'agent_id', 'agent_name',
                'icon', 'stance', 'confidence', 'message', 'cited_dimensions'}]}],
            'final_consensus': {'action', 'confidence', 'split'},
            'method': 'llm' | 'rule',
        }
    """
    rounds = max(1, min(rounds, 4))  # cap 4 rounds
    method = 'rule'
    debate_rounds: list[dict[str, Any]] = []

    if use_llm:
        try:
            llm_rounds = _run_with_gemini(target, brain_snapshot, rounds)
            if llm_rounds:
                debate_rounds = llm_rounds
                method = 'llm'
        except Exception:
            method = 'rule'

    if not debate_rounds:
        debate_rounds = _run_with_rules(target, brain_snapshot, rounds)
        method = 'rule' if method != 'llm' else 'mixed'

    consensus = _synthesize_consensus(debate_rounds)

    return {
        'target': target,
        'rounds': debate_rounds,
        'final_consensus': consensus,
        'method': method,
        'completed_at': datetime.now(timezone.utc).isoformat(),
    }


# ─── Rule-based debate (Brain dimension 직접 읽기) ─────────

def _run_with_rules(target: str, brain: dict, rounds: int) -> list[dict]:
    dim_scores = brain.get('dimension_scores', {}) if isinstance(brain.get('dimension_scores'), dict) else {}
    debate: list[dict] = []
    for r in range(1, rounds + 1):
        messages: list[dict] = []
        for profile in AGENT_PROFILES:
            msg = _build_rule_message(profile, dim_scores, target, round_num=r)
            messages.append(msg)
        debate.append({'round': r, 'messages': messages})
    return debate


def _build_rule_message(profile: dict, dim_scores: dict, target: str, round_num: int) -> dict:
    """페르소나 + 자기 focus dimension 점수에 기반한 발언 생성."""
    cited: list[str] = []
    cited_values: list[tuple[str, int, str]] = []  # (name, score, evidence)

    for dim_name in profile['focus']:
        dim = dim_scores.get(dim_name)
        if isinstance(dim, dict) and dim.get('score') is not None:
            score = dim['score']
            cited.append(dim_name)
            cited_values.append((dim_name, score, dim.get('evidence', '')))

    if not cited_values:
        # focus dimension 결측 — 사용 가능한 dim 1개 fallback
        for dim_name, dim in dim_scores.items():
            if isinstance(dim, dict) and dim.get('score') is not None:
                cited.append(dim_name)
                cited_values.append((dim_name, dim['score'], dim.get('evidence', '')))
                break

    # Stance 결정: bias + cited score 평균
    avg_score = sum(s for _, s, _ in cited_values) / len(cited_values) if cited_values else 50
    stance = _stance_from_bias(profile['bias'], avg_score)
    confidence = _confidence_from_bias(profile['bias'], avg_score)

    # 발언 생성 (페르소나 + 수치 인용)
    message = _persona_message(profile, target, cited_values, stance, round_num)

    return {
        'agent_id': profile['id'],
        'agent_name': profile['name'],
        'icon': profile['icon'],
        'role': profile['role'],
        'stance': stance,
        'confidence': round(confidence, 2),
        'message': message,
        'cited_dimensions': cited,
        'round': round_num,
    }


def _stance_from_bias(bias: str, score: float) -> str:
    """편향 + 점수 → 최종 stance."""
    if bias == 'Bearish':
        if score > 75:
            return 'HOLD'
        return 'SELL' if score < 40 else 'HOLD'
    if bias == 'Bullish':
        if score < 30:
            return 'HOLD'
        return 'BUY' if score > 50 else 'HOLD'
    if bias == 'Quant':
        if score > 60:
            return 'BUY'
        if score < 40:
            return 'SELL'
        return 'HOLD'
    if bias == 'Contrarian':
        # 점수가 극단일수록 반대로
        if score > 75:
            return 'SELL'
        if score < 25:
            return 'BUY'
        return 'HOLD'
    # Neutral
    if score > 60:
        return 'BUY'
    if score < 40:
        return 'SELL'
    return 'HOLD'


def _confidence_from_bias(bias: str, score: float) -> float:
    """확신도 — 점수가 자기 편향과 일치하면 높음."""
    base = 0.55
    if bias == 'Bearish' and score < 40:
        return min(0.9, base + (40 - score) * 0.01)
    if bias == 'Bullish' and score > 60:
        return min(0.9, base + (score - 60) * 0.01)
    if bias == 'Quant':
        return 0.5 + abs(score - 50) * 0.008
    if bias == 'Contrarian':
        deviation = abs(score - 50)
        return min(0.85, base + deviation * 0.007)
    # Neutral
    return base


def _persona_message(profile: dict, target: str, cited: list[tuple[str, int, str]],
                     stance: str, round_num: int) -> str:
    """페르소나 화법으로 메시지 생성."""
    if not cited:
        return f"[{profile['name']}] {target} 에 대한 데이터가 부족하여 판단 보류합니다."

    name, score, evidence = cited[0]
    # 라운드별 다른 화법
    intros = {
        'Bearish': ['걱정스러운 신호가 보입니다.', '신중하게 봐야 합니다.', '리스크에 주목합시다.'],
        'Bullish': ['긍정적 시그널입니다.', '추세가 살아있습니다.', '모멘텀이 형성됐습니다.'],
        'Quant': ['데이터가 명확합니다.', '모델 신호 확인.', '통계적 유의성 있음.'],
        'Contrarian': ['컨센서스를 의심해야 합니다.', '극단에 다가가고 있습니다.', '반대 포지션 검토.'],
        'Neutral': ['균형 잡힌 시각이 필요합니다.', '포지션 사이징이 핵심.', '헤지를 고려합시다.'],
    }
    intro_pool = intros.get(profile['bias'], ['관점을 공유합니다.'])
    intro = intro_pool[(round_num - 1) % len(intro_pool)]

    cited_text = f"{name} 점수가 {score}/100"
    if evidence:
        cited_text += f" ({evidence[:60]})"

    return f"{intro} {cited_text}이며, 이를 근거로 {target} 에 대해 {stance} 입장입니다."


# ─── Gemini multi-agent (compact prompting) ────────────────

def _run_with_gemini(target: str, brain: dict, rounds: int) -> list[dict] | None:
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=api_key)

        # 한 번의 호출로 모든 라운드 + 모든 에이전트 생성 (비용 절감)
        prompt = _build_gemini_prompt(target, brain, rounds)
        response = client.models.generate_content(
            model=os.getenv('MIROFISH_DEBATE_MODEL', 'gemini-2.5-flash'),
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type='application/json',
                temperature=0.7,
                max_output_tokens=10000,  # 6k → 10k (5명×4라운드 토론 안전 capacity)
            ),
        )
        raw = (response.text or '').strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # truncated JSON 부분 복구 — rounds 배열에서 가능한 만큼 살린다
            data = _try_recover_debate_json(raw)
            if not data:
                return None
        if not isinstance(data, dict):
            return None
        rounds_data = data.get('rounds', [])
        return _validate_debate(rounds_data)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'[Debate] Gemini call failed: {type(e).__name__}: {e}')
        return None


def _try_recover_debate_json(raw: str) -> dict | None:
    """truncated debate JSON 에서 완성된 round 만 살린다."""
    import re as _re
    rounds_out: list[dict] = []
    # 'round': N 패턴 + 그 다음 messages 배열 시도
    # 단순 휴리스틱: { ... } 단위로 객체 추출
    depth = 0
    buf = ''
    in_string = False
    escape = False
    for ch in raw:
        if escape:
            escape = False
            buf += ch
            continue
        if ch == '\\' and in_string:
            escape = True
            buf += ch
            continue
        if ch == '"':
            in_string = not in_string
            buf += ch
            continue
        if in_string:
            buf += ch
            continue
        if ch == '{':
            if depth == 0:
                buf = '{'
            else:
                buf += ch
            depth += 1
        elif ch == '}':
            depth -= 1
            buf += ch
            if depth == 0:
                try:
                    obj = json.loads(buf)
                    # round 객체만 (messages 키 가짐)
                    if isinstance(obj, dict) and 'messages' in obj:
                        rounds_out.append(obj)
                except (json.JSONDecodeError, ValueError):
                    pass
                buf = ''
        elif depth > 0:
            buf += ch
    if rounds_out:
        return {'rounds': rounds_out}
    return None


def _build_gemini_prompt(target: str, brain: dict, rounds: int) -> str:
    dim_scores = brain.get('dimension_scores', {}) if isinstance(brain.get('dimension_scores'), dict) else {}
    dims_text = '\n'.join(
        f"- {k}: {v.get('score', '?')}/100 ({v.get('evidence', '')})"
        for k, v in dim_scores.items() if isinstance(v, dict) and v.get('score') is not None
    )
    profiles_text = '\n'.join(
        f"- {p['id']} ({p['name']}, {p['bias']}): {p['persona']} | focus={p['focus']}"
        for p in AGENT_PROFILES
    )
    return f"""5인의 금융 분석가가 종목 {target} 에 대해 라운드 토론을 진행합니다.

페르소나:
{profiles_text}

Brain 13D 데이터:
{dims_text}

총 {rounds} 라운드, 각 라운드마다 모든 5인이 발언. 각 발언에 반드시 Brain dimension 수치 1개 이상 인용.

JSON 출력 형식:
{{
  "rounds": [
    {{"round": 1, "messages": [
      {{"agent_id": "kim_risk", "agent_name": "김리스크", "icon": "🐻",
        "role": "글로벌 매크로 전략가", "stance": "BUY|HOLD|SELL",
        "confidence": 0.0~1.0, "message": "발언 내용 (수치 인용 필수)",
        "cited_dimensions": ["dim_name1", ...], "round": 1}},
      ...5인...
    ]}},
    ...{rounds} 라운드...
  ]
}}
"""


def _validate_debate(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for r_item in raw[:4]:
        if not isinstance(r_item, dict):
            continue
        msgs = r_item.get('messages', [])
        if not isinstance(msgs, list):
            continue
        valid_msgs = []
        for m in msgs[:5]:
            if not isinstance(m, dict):
                continue
            cited = m.get('cited_dimensions', [])
            if not isinstance(cited, list) or not cited:
                continue  # MD 강제 규칙: dimension 인용 없으면 drop
            valid_msgs.append({
                'agent_id': str(m.get('agent_id', '')),
                'agent_name': str(m.get('agent_name', '')),
                'icon': str(m.get('icon', '')),
                'role': str(m.get('role', '')),
                'stance': _normalize_stance(m.get('stance')),
                'confidence': _clamp_float(m.get('confidence', 0.5)),
                'message': str(m.get('message', ''))[:500],
                'cited_dimensions': [str(c) for c in cited[:5]],
                'round': int(r_item.get('round', 1)),
            })
        if valid_msgs:
            out.append({'round': r_item.get('round', 1), 'messages': valid_msgs})
    return out


def _synthesize_consensus(debate_rounds: list[dict]) -> dict[str, Any]:
    """마지막 라운드 stance 카운트 + 평균 confidence."""
    if not debate_rounds:
        return {'action': 'HOLD', 'confidence': 0.5, 'split': {}}

    last_round = debate_rounds[-1]
    stance_count: dict[str, int] = {}
    confidences: list[float] = []
    for msg in last_round.get('messages', []):
        s = msg.get('stance', 'HOLD')
        stance_count[s] = stance_count.get(s, 0) + 1
        confidences.append(msg.get('confidence', 0.5))

    if not stance_count:
        return {'action': 'HOLD', 'confidence': 0.5, 'split': {}}

    action = max(stance_count.items(), key=lambda x: x[1])[0]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.5
    return {
        'action': action,
        'confidence': round(avg_conf, 2),
        'split': stance_count,
    }


def _normalize_stance(s: Any) -> str:
    if not s:
        return 'HOLD'
    s = str(s).upper().strip()
    if s in ('BUY', 'SELL', 'HOLD'):
        return s
    if 'BUY' in s or 'BULL' in s:
        return 'BUY'
    if 'SELL' in s or 'BEAR' in s:
        return 'SELL'
    return 'HOLD'


def _clamp_float(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5
