"""Bull/Bear research debate with a research-manager verdict (KR-native).

Ports the TradingAgents "Research Team" stage: a Bull Researcher and a Bear
Researcher argue across N structured rounds — each reading the four analyst
reports and rebutting the opponent's previous message — after which a Research
Manager judges the full transcript and issues a stance/thesis/confidence.

Each debate piece (per-round bull, per-round bear, final manager) tries an LLM
first and falls back to a deterministic rule composition on any failure. A
single failed piece never aborts the debate; it just downgrades `method` to
'mixed'.

Result schema (LOCKED — the engine and later tasks depend on this):
    {
        'rounds': [{'round': int, 'bull': {'message': str}, 'bear': {'message': str}}],
        'bull_case': str, 'bear_case': str,
        'manager': {'stance': 'bull'|'bear'|'neutral', 'thesis': str, 'confidence': float},
        'method': 'llm'|'rule'|'mixed',
    }

Deterministic manager math (pinned by tests):
    mean       = mean(analyst scores)
    confidence = min(95, 50 + |mean|/2)
    stance     = 'bull' if mean > 10, 'bear' if mean < -10, else 'neutral'
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.mirofish import llm_client

logger = logging.getLogger(__name__)

_MANAGER_BULL_CUTOFF = 10.0
_MANAGER_BEAR_CUTOFF = -10.0
_MIN_ROUNDS = 1
_MAX_ROUNDS = 4

_BULL_SYSTEM = (
    '당신은 강세론(Bull) 리서처입니다. 제공된 4개 애널리스트 리포트에서 매수 논거를 '
    '적극 발굴하고, 반드시 리포트의 역할·점수를 인용하세요. 상대(약세론)의 직전 주장이 '
    '있으면 구체적으로 반박하세요.'
)
_BEAR_SYSTEM = (
    '당신은 약세론(Bear) 리서처입니다. 제공된 4개 애널리스트 리포트에서 위험 요인과 '
    '매도/관망 논거를 발굴하고, 반드시 리포트의 역할·점수를 인용하세요. 상대(강세론)의 '
    '직전 주장이 있으면 구체적으로 반박하세요.'
)
_MANAGER_SYSTEM = (
    '당신은 리서치 매니저입니다. 강세론과 약세론의 전체 토론 기록을 심판하고, '
    '어느 쪽 논거가 더 강한지 판단해 최종 입장을 정하세요. 반드시 근거를 제시하세요.'
)

_BULL_JSON = '다음 JSON 형식으로만 응답하세요: {"message": "강세 주장 (2~4문장, 점수 인용)"}'
_BEAR_JSON = '다음 JSON 형식으로만 응답하세요: {"message": "약세 주장 (2~4문장, 점수 인용)"}'
_MANAGER_JSON = (
    '다음 JSON 형식으로만 응답하세요: '
    '{"stance": "bull|bear|neutral", "thesis": "최종 판단 근거 (2~4문장)", '
    '"confidence": 0~100 정수}'
)


# ── Public API ──────────────────────────────────────────────────────

def run_research_debate(
    target: str,
    reports: list[dict[str, Any]],
    *,
    rounds: int = 2,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Run an N-round bull/bear debate and a manager verdict.

    Each piece (per-round bull/bear message, final manager judgment) is produced
    by the LLM when `use_llm`, otherwise by the deterministic rule composer. Any
    per-piece LLM failure falls back to the rule and downgrades `method`.
    """
    reports = reports or []
    rounds = max(_MIN_ROUNDS, min(int(rounds or _MIN_ROUNDS), _MAX_ROUNDS))

    llm_ok = 0
    llm_fail = 0

    debate_rounds: list[dict[str, Any]] = []
    prev_bear = ''
    for round_num in range(1, rounds + 1):
        bull_msg, used_llm, bull_llm = _bull_message(target, reports, prev_bear, round_num, use_llm)
        llm_ok, llm_fail = _accumulate(used_llm, use_llm, llm_ok, llm_fail)

        bear_msg, used_llm_b, bear_llm = _bear_message(target, reports, bull_msg, round_num, use_llm)
        llm_ok, llm_fail = _accumulate(used_llm_b, use_llm, llm_ok, llm_fail)

        bull_output = {'message': bull_msg}
        bear_output = {'message': bear_msg}
        if bull_llm:
            bull_output['llm'] = bull_llm
        if bear_llm:
            bear_output['llm'] = bear_llm
        debate_rounds.append({
            'round': round_num,
            'bull': bull_output,
            'bear': bear_output,
        })
        prev_bear = bear_msg

    bull_case = debate_rounds[-1]['bull']['message'] if debate_rounds else ''
    bear_case = debate_rounds[-1]['bear']['message'] if debate_rounds else ''

    manager, used_llm_m = _manager_verdict(target, reports, debate_rounds, use_llm)
    llm_ok, llm_fail = _accumulate(used_llm_m, use_llm, llm_ok, llm_fail)

    return {
        'rounds': debate_rounds,
        'bull_case': bull_case,
        'bear_case': bear_case,
        'manager': manager,
        'method': _resolve_method(use_llm, llm_ok, llm_fail),
    }


# ── Method bookkeeping ──────────────────────────────────────────────

def _accumulate(used_llm: bool, use_llm: bool, ok: int, fail: int) -> tuple[int, int]:
    if not use_llm:
        return ok, fail
    return (ok + 1, fail) if used_llm else (ok, fail + 1)


def _resolve_method(use_llm: bool, ok: int, fail: int) -> str:
    if not use_llm or ok == 0:
        return 'rule'
    return 'llm' if fail == 0 else 'mixed'


# ── Rule composition ────────────────────────────────────────────────

def _bull_message_rule(reports: list[dict[str, Any]], round_num: int) -> str:
    bullish = [r for r in reports if str(r.get('stance')) == 'bullish']
    picked = bullish or _top_reports(reports, positive=True)
    cites = _cite(picked)
    body = ' '.join(cites) if cites else '뚜렷한 매수 근거는 제한적이나 하방 리스크도 낮다.'
    return f'[강세론 R{round_num}] {body} 종합적으로 매수 우위로 판단한다.'


def _bear_message_rule(reports: list[dict[str, Any]], round_num: int) -> str:
    risky = [r for r in reports if str(r.get('stance')) in ('bearish', 'neutral')]
    picked = risky or _top_reports(reports, positive=False)
    cites = _cite(picked)
    body = ' '.join(cites) if cites else '눈에 띄는 악재는 없으나 추세 과열 부담이 있다.'
    return f'[약세론 R{round_num}] {body} 리스크 대비 신중한 접근을 권고한다.'


def _manager_rule(reports: list[dict[str, Any]]) -> dict[str, Any]:
    mean = analyst_mean(reports)
    if mean > _MANAGER_BULL_CUTOFF:
        stance = 'bull'
    elif mean < _MANAGER_BEAR_CUTOFF:
        stance = 'bear'
    else:
        stance = 'neutral'
    confidence = round(min(95.0, 50.0 + abs(mean) / 2.0), 2)
    label = {'bull': '강세', 'bear': '약세', 'neutral': '중립'}[stance]
    thesis = (
        f'애널리스트 평균 점수 {mean:+.1f} 기준 {label} 우위. '
        f'강세/약세 논거를 종합해 {label} 입장으로 결론.'
    )
    return {'stance': stance, 'thesis': thesis, 'confidence': confidence}


def _top_reports(reports: list[dict[str, Any]], *, positive: bool) -> list[dict[str, Any]]:
    if not reports:
        return []
    ordered = sorted(reports, key=lambda r: _safe_float(r.get('score')) or 0.0,
                     reverse=positive)
    return ordered[:2]


def _cite(reports: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in reports[:4]:
        role = str(r.get('role') or '?')
        score = _safe_float(r.get('score')) or 0.0
        summary = str(r.get('summary') or '').strip()
        snippet = f' — {summary[:60]}' if summary else ''
        out.append(f'{role}({score:+.0f}){snippet}.')
    return out


# ── LLM pieces (each returns (message_or_verdict, used_llm)) ─────────

def _bull_message(target: str, reports: list[dict[str, Any]], prev_bear: str,
                  round_num: int, use_llm: bool) -> tuple[str, bool, dict[str, Any] | None]:
    if use_llm:
        try:
            msg, llm_meta = _llm_side(_BULL_SYSTEM, _BULL_JSON, target, reports, prev_bear,
                                      round_num, opponent_label='약세론')
            if msg:
                return msg, True, llm_meta
        except Exception as exc:  # noqa: BLE001 — isolate per-piece failure
            logger.warning('[research_debate] bull LLM failed R%d: %s', round_num, exc)
    return _bull_message_rule(reports, round_num), False, None


def _bear_message(target: str, reports: list[dict[str, Any]], prev_bull: str,
                  round_num: int, use_llm: bool) -> tuple[str, bool, dict[str, Any] | None]:
    if use_llm:
        try:
            msg, llm_meta = _llm_side(_BEAR_SYSTEM, _BEAR_JSON, target, reports, prev_bull,
                                      round_num, opponent_label='강세론')
            if msg:
                return msg, True, llm_meta
        except Exception as exc:  # noqa: BLE001
            logger.warning('[research_debate] bear LLM failed R%d: %s', round_num, exc)
    return _bear_message_rule(reports, round_num), False, None


def _manager_verdict(target: str, reports: list[dict[str, Any]],
                     debate_rounds: list[dict[str, Any]],
                     use_llm: bool) -> tuple[dict[str, Any], bool]:
    if use_llm:
        try:
            verdict = _llm_manager(target, reports, debate_rounds)
            if verdict:
                return verdict, True
        except Exception as exc:  # noqa: BLE001
            logger.warning('[research_debate] manager LLM failed: %s', exc)
    return _manager_rule(reports), False


def _llm_side(system: str, json_hint: str, target: str, reports: list[dict[str, Any]],
              opponent_prev: str, round_num: int, *, opponent_label: str,
              ) -> tuple[str | None, dict[str, Any]]:
    prompt = (
        f'분석 대상: {target}\n라운드: {round_num}\n\n'
        f'[애널리스트 리포트]\n{_reports_digest(reports)}\n\n'
        f'[{opponent_label}의 직전 주장]\n{opponent_prev or "(없음)"}\n\n{json_hint}'
    )
    raw, llm_meta = llm_client.generate_text_with_metadata(
        prompt, system=system, temperature=0.5, max_tokens=1024, json_mode=True,
    )
    data = _parse_json_obj(raw)
    if not data:
        return None, llm_meta
    message = str(data.get('message') or '').strip()
    return (message[:1200] if message else None), llm_meta


def _llm_manager(target: str, reports: list[dict[str, Any]],
                 debate_rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    transcript = '\n'.join(
        f"R{r['round']} 강세: {r['bull']['message']}\nR{r['round']} 약세: {r['bear']['message']}"
        for r in debate_rounds
    )
    prompt = (
        f'분석 대상: {target}\n\n'
        f'[애널리스트 리포트]\n{_reports_digest(reports)}\n\n'
        f'[토론 기록]\n{transcript}\n\n{_MANAGER_JSON}'
    )
    raw, llm_meta = llm_client.generate_text_with_metadata(
        prompt, system=_MANAGER_SYSTEM, temperature=0.3, max_tokens=1024, json_mode=True,
    )
    data = _parse_json_obj(raw)
    if not data:
        return None
    thesis = str(data.get('thesis') or '').strip()
    if not thesis:
        return None
    stance = _normalize_stance(data.get('stance'), reports)
    confidence = _clamp(_safe_float(data.get('confidence')) or 50.0, 0.0, 100.0)
    return {
        'stance': stance, 'thesis': thesis[:1500], 'confidence': round(confidence, 2),
        'llm': llm_meta,
    }


def _reports_digest(reports: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in reports:
        role = str(r.get('role') or '?')
        stance = str(r.get('stance') or '?')
        score = _safe_float(r.get('score')) or 0.0
        summary = str(r.get('summary') or '').strip()[:120]
        lines.append(f'- {role} [{stance} {score:+.0f}]: {summary}')
    return '\n'.join(lines) if lines else '(리포트 없음)'


# ── Shared helpers ──────────────────────────────────────────────────

def analyst_mean(reports: list[dict[str, Any]]) -> float:
    scores = [_safe_float(r.get('score')) for r in (reports or [])]
    scores = [s for s in scores if s is not None]
    return sum(scores) / len(scores) if scores else 0.0


def _normalize_stance(raw: Any, reports: list[dict[str, Any]]) -> str:
    value = str(raw or '').strip().lower()
    if value in ('bull', 'bear', 'neutral'):
        return value
    if any(token in value for token in ('bull', 'buy', '매수', '강세')):
        return 'bull'
    if any(token in value for token in ('bear', 'sell', '매도', '약세')):
        return 'bear'
    # Fall back to rule stance derived from the analyst mean.
    return _manager_rule(reports)['stance']


def _parse_json_obj(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        if isinstance(value, str):
            value = value.replace(',', '')
        return float(value)
    except (TypeError, ValueError):
        return None
