"""Trader plan, risk-team debate, and PM final decision (KR-native).

Ports the TradingAgents "Trader → Risk Team → Portfolio Manager" tail:
    1. Trader drafts an execution plan from the manager thesis + live bundle.
    2. A three-person Risk Team (공격/보수/중립 = risky/safe/neutral) judges the
       plan and votes approve/reject/neutral — always exactly three, in that order.
    3. The Portfolio Manager issues the final verdict.

Each stage tries an LLM first and falls back to a deterministic rule. The PM
LLM output is validated against the allowed verdict set; anything invalid
falls back to the rule verdict. Partial LLM success downgrades `method` to
'mixed'.

Result schema (LOCKED — the engine depends on this):
    {
        'trader_plan': {'action_hint': str, 'entry_note': str, 'risk_note': str},
        'risk_debate': [{'role': 'risky'|'safe'|'neutral', 'message': str,
                         'vote': 'approve'|'reject'|'neutral'}],   # exactly 3, in order
        'pm_decision': {'verdict': 'STRONG_BUY'|'BUY'|'HOLD'|'SELL',
                        'confidence': float, 'strong_buy': bool, 'reasoning': str},
        'method': 'llm'|'rule'|'mixed',
    }

Deterministic PM math (pinned by tests), driven by debate['_analyst_mean']:
    mean >= 35  → STRONG_BUY  (confidence = max(75, manager confidence))
    mean >= 15  → BUY
    mean <= -15 → SELL
    else        → HOLD
    strong_buy = (verdict == 'STRONG_BUY')
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.mirofish import llm_client

logger = logging.getLogger(__name__)

RISK_ROLES: tuple[str, ...] = ('risky', 'safe', 'neutral')
ALLOWED_VERDICTS: tuple[str, ...] = ('STRONG_BUY', 'BUY', 'HOLD', 'SELL')

# Corpus red flags the conservative (safe) persona vetoes on.
NEGATIVE_KEYWORDS: tuple[str, ...] = ('소송', '횡령', '적자', '하한가', '유상증자', '감자')

_STRONG_BUY_CUTOFF = 35.0
_BUY_CUTOFF = 15.0
_SELL_CUTOFF = -15.0
_STRONG_BUY_CONF_FLOOR = 75.0

_TRADER_SYSTEM = (
    '당신은 트레이더입니다. 리서치 매니저의 논지와 현재가/기술적 데이터를 바탕으로 '
    '실행 계획(진입/손절 관점)을 간결하게 제시하세요. 반드시 수치를 인용하세요.'
)
_RISK_SYSTEMS: dict[str, str] = {
    'risky': '당신은 공격적 리스크 애널리스트입니다. 상승 여력과 기회를 강조하되 근거를 제시하세요.',
    'safe': '당신은 보수적 리스크 애널리스트입니다. 하방 위험과 악재를 강조하고 자본 보존을 우선하세요.',
    'neutral': '당신은 중립 리스크 애널리스트입니다. 공격/보수 양측을 중재하고 균형 잡힌 관점을 제시하세요.',
}
_TRADER_JSON = (
    '다음 JSON 형식으로만 응답하세요: '
    '{"action_hint": "매수/관망/매도 등 방향 한 줄", "entry_note": "진입 관점 한 줄", '
    '"risk_note": "손절/리스크 관점 한 줄"}'
)
_RISK_JSON = (
    '다음 JSON 형식으로만 응답하세요: '
    '{"message": "판단 근거 (1~3문장)", "vote": "approve|reject|neutral"}'
)
_PM_SYSTEM = (
    '당신은 포트폴리오 매니저입니다. 트레이더 계획과 리스크팀 3인의 투표를 종합해 '
    '최종 판정을 내리세요. 판정은 STRONG_BUY/BUY/HOLD/SELL 중 하나여야 합니다.'
)
_PM_JSON = (
    '다음 JSON 형식으로만 응답하세요: '
    '{"verdict": "STRONG_BUY|BUY|HOLD|SELL", "confidence": 0~100 정수, '
    '"reasoning": "판단 근거 (2~4문장)"}'
)


# ── Public API ──────────────────────────────────────────────────────

def run_trader_and_risk(
    target: str,
    bundle: dict[str, Any],
    debate: dict[str, Any],
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Run trader plan → 3-role risk debate → PM final decision.

    `debate` carries '_analyst_mean' (injected by the engine) which drives the
    deterministic PM verdict bands. Each stage falls back to its rule on any LLM
    failure; partial success yields method='mixed'.
    """
    bundle = bundle or {}
    debate = debate or {}

    llm_ok = 0
    llm_fail = 0

    trader_plan, used = _trader_plan(target, bundle, debate, use_llm)
    llm_ok, llm_fail = _accumulate(used, use_llm, llm_ok, llm_fail)

    risk_debate: list[dict[str, Any]] = []
    for role in RISK_ROLES:
        entry, used = _risk_entry(role, target, bundle, debate, trader_plan, use_llm)
        llm_ok, llm_fail = _accumulate(used, use_llm, llm_ok, llm_fail)
        risk_debate.append(entry)

    pm_decision, used = _pm_decision(target, debate, trader_plan, risk_debate, use_llm)
    llm_ok, llm_fail = _accumulate(used, use_llm, llm_ok, llm_fail)

    return {
        'trader_plan': trader_plan,
        'risk_debate': risk_debate,
        'pm_decision': pm_decision,
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


# ── Trader plan ─────────────────────────────────────────────────────

def _trader_plan(target: str, bundle: dict[str, Any], debate: dict[str, Any],
                 use_llm: bool) -> tuple[dict[str, Any], bool]:
    if use_llm:
        try:
            plan = _llm_trader(target, bundle, debate)
            if plan:
                return plan, True
        except Exception as exc:  # noqa: BLE001 — isolate per-stage failure
            logger.warning('[trader_risk] trader LLM failed: %s', exc)
    return _trader_plan_rule(bundle, debate), False


def _trader_plan_rule(bundle: dict[str, Any], debate: dict[str, Any]) -> dict[str, Any]:
    price = bundle.get('price') or {}
    tech = bundle.get('technical') or {}
    mean = _analyst_mean(debate)
    trend = str(tech.get('trend') or '').strip().lower()
    px = _safe_float(price.get('price'))
    change = _safe_float(price.get('change_pct'))

    if mean >= _BUY_CUTOFF:
        action = '매수 관점 — 리서치 매니저 우위와 정렬'
    elif mean <= _SELL_CUTOFF:
        action = '매도/관망 관점 — 하방 우위'
    else:
        action = '관망 관점 — 신호 혼재'

    trend_label = {'up': '상승', 'bullish': '상승', 'down': '하락', 'bearish': '하락'}.get(trend, '중립')
    px_text = f'현재가 {px:,.0f}원' if px is not None else '현재가 정보 없음'
    chg_text = f' ({change:+.2f}%)' if change is not None else ''
    entry = f'{px_text}{chg_text}, 추세 {trend_label} 국면에서 분할 진입 검토.'
    risk = '이탈 시 손절 원칙 준수, 과열 구간에서는 포지션 축소.'

    return {'action_hint': action, 'entry_note': entry, 'risk_note': risk}


def _llm_trader(target: str, bundle: dict[str, Any],
                debate: dict[str, Any]) -> dict[str, Any] | None:
    price = bundle.get('price') or {}
    tech = bundle.get('technical') or {}
    manager = debate.get('manager') or {}
    prompt = (
        f'분석 대상: {target}\n'
        f'리서치 매니저 논지: {manager.get("thesis", "")} '
        f'(입장 {manager.get("stance", "?")}, 확신 {manager.get("confidence", "?")})\n'
        f'현재가: {price.get("price")} ({price.get("change_pct")}%)\n'
        f'기술적: {json.dumps(tech, ensure_ascii=False, default=str)[:500]}\n\n{_TRADER_JSON}'
    )
    raw, llm_meta = llm_client.generate_text_with_metadata(
        prompt, system=_TRADER_SYSTEM, temperature=0.4, max_tokens=768, json_mode=True,
    )
    data = _parse_json_obj(raw)
    if not data:
        return None
    plan = {
        'action_hint': str(data.get('action_hint') or '').strip()[:200],
        'entry_note': str(data.get('entry_note') or '').strip()[:300],
        'risk_note': str(data.get('risk_note') or '').strip()[:300],
    }
    if not all(plan.values()):
        return None
    plan['llm'] = llm_meta
    return plan


# ── Risk team ───────────────────────────────────────────────────────

def _risk_entry(role: str, target: str, bundle: dict[str, Any], debate: dict[str, Any],
                trader_plan: dict[str, Any], use_llm: bool) -> tuple[dict[str, Any], bool]:
    if use_llm:
        try:
            entry = _llm_risk(role, target, bundle, debate, trader_plan)
            if entry:
                return entry, True
        except Exception as exc:  # noqa: BLE001
            logger.warning('[trader_risk] risk(%s) LLM failed: %s', role, exc)
    return _risk_entry_rule(role, bundle, debate), False


def _risk_entry_rule(role: str, bundle: dict[str, Any], debate: dict[str, Any]) -> dict[str, Any]:
    mean = _analyst_mean(debate)
    has_negative = _has_negative_keyword(bundle.get('corpus'))

    if role == 'risky':
        vote = 'approve' if mean > 0 else 'neutral'
        message = (
            f'평균 점수 {mean:+.1f} — 상승 여력에 무게. 기회비용을 감안해 적극 대응.'
            if mean > 0 else
            f'평균 점수 {mean:+.1f} — 공격적 매수를 정당화할 모멘텀은 부족, 관망.'
        )
    elif role == 'safe':
        if has_negative or mean < 0:
            vote = 'reject'
            reason = '코퍼스 내 악재 키워드 감지' if has_negative else f'평균 점수 {mean:+.1f} 부진'
            message = f'{reason} — 자본 보존을 위해 진입 반대.'
        else:
            vote = 'neutral'
            message = f'뚜렷한 악재는 없으나(평균 {mean:+.1f}) 손절선 준수 전제 하에 중립.'
    else:  # neutral
        vote = 'neutral'
        message = (
            f'공격/보수 양측을 중재. 평균 점수 {mean:+.1f} 기준 '
            f'포지션 사이징으로 리스크를 관리하는 균형 접근 권고.'
        )

    return {'role': role, 'message': message, 'vote': vote}


def _llm_risk(role: str, target: str, bundle: dict[str, Any], debate: dict[str, Any],
              trader_plan: dict[str, Any]) -> dict[str, Any] | None:
    prompt = (
        f'분석 대상: {target}\n'
        f'트레이더 계획: {trader_plan.get("action_hint", "")} | {trader_plan.get("entry_note", "")} '
        f'| {trader_plan.get("risk_note", "")}\n'
        f'강세 논거: {debate.get("bull_case", "")}\n약세 논거: {debate.get("bear_case", "")}\n'
        f'뉴스 코퍼스(발췌): {str(bundle.get("corpus") or "")[:600]}\n\n{_RISK_JSON}'
    )
    raw, llm_meta = llm_client.generate_text_with_metadata(
        prompt, system=_RISK_SYSTEMS[role], temperature=0.5, max_tokens=512, json_mode=True,
    )
    data = _parse_json_obj(raw)
    if not data:
        return None
    message = str(data.get('message') or '').strip()
    if not message:
        return None
    return {
        'role': role, 'message': message[:600], 'vote': _normalize_vote(data.get('vote')),
        'llm': llm_meta,
    }


# ── Portfolio Manager ───────────────────────────────────────────────

def _pm_decision(target: str, debate: dict[str, Any], trader_plan: dict[str, Any],
                 risk_debate: list[dict[str, Any]], use_llm: bool) -> tuple[dict[str, Any], bool]:
    rule = _pm_decision_rule(debate)
    if use_llm:
        try:
            llm = _llm_pm(target, debate, trader_plan, risk_debate, rule)
            if llm:
                return llm, True
        except Exception as exc:  # noqa: BLE001
            logger.warning('[trader_risk] PM LLM failed: %s', exc)
    return rule, False


def _pm_decision_rule(debate: dict[str, Any]) -> dict[str, Any]:
    mean = _analyst_mean(debate)
    manager_conf = _safe_float((debate.get('manager') or {}).get('confidence')) or 50.0

    if mean >= _STRONG_BUY_CUTOFF:
        verdict = 'STRONG_BUY'
        confidence = max(_STRONG_BUY_CONF_FLOOR, manager_conf)
    elif mean >= _BUY_CUTOFF:
        verdict = 'BUY'
        confidence = manager_conf
    elif mean <= _SELL_CUTOFF:
        verdict = 'SELL'
        confidence = manager_conf
    else:
        verdict = 'HOLD'
        confidence = manager_conf

    confidence = round(_clamp(confidence, 0.0, 100.0), 2)
    reasoning = (
        f'애널리스트 평균 {mean:+.1f}, 리서치 매니저 확신 {manager_conf:.0f} 기준 '
        f'{verdict} 판정.'
    )
    return {
        'verdict': verdict,
        'confidence': confidence,
        'strong_buy': verdict == 'STRONG_BUY',
        'reasoning': reasoning,
    }


def _llm_pm(target: str, debate: dict[str, Any], trader_plan: dict[str, Any],
            risk_debate: list[dict[str, Any]], rule: dict[str, Any]) -> dict[str, Any] | None:
    votes = ', '.join(f'{r["role"]}={r["vote"]}' for r in risk_debate)
    prompt = (
        f'분석 대상: {target}\n'
        f'트레이더 계획: {trader_plan.get("action_hint", "")}\n'
        f'리스크팀 투표: {votes}\n'
        f'강세 논거: {debate.get("bull_case", "")}\n약세 논거: {debate.get("bear_case", "")}\n'
        f'애널리스트 평균 점수: {_analyst_mean(debate):+.1f}\n\n{_PM_JSON}'
    )
    raw, llm_meta = llm_client.generate_text_with_metadata(
        prompt, system=_PM_SYSTEM, temperature=0.3, max_tokens=768, json_mode=True,
    )
    data = _parse_json_obj(raw)
    if not data:
        return None
    verdict = str(data.get('verdict') or '').strip().upper()
    if verdict not in ALLOWED_VERDICTS:
        return None  # invalid → caller keeps the rule verdict
    reasoning = str(data.get('reasoning') or '').strip()
    if not reasoning:
        return None
    confidence = _safe_float(data.get('confidence'))
    if confidence is None:
        confidence = rule['confidence']
    if verdict == 'STRONG_BUY':
        confidence = max(_STRONG_BUY_CONF_FLOOR, confidence)
    confidence = round(_clamp(confidence, 0.0, 100.0), 2)
    return {
        'verdict': verdict,
        'confidence': confidence,
        'strong_buy': verdict == 'STRONG_BUY',
        'reasoning': reasoning[:1500],
        'llm': llm_meta,
    }


# ── Shared helpers ──────────────────────────────────────────────────

def _analyst_mean(debate: dict[str, Any]) -> float:
    return _safe_float(debate.get('_analyst_mean')) or 0.0


def _has_negative_keyword(corpus: Any) -> bool:
    text = str(corpus or '')
    return any(kw in text for kw in NEGATIVE_KEYWORDS)


def _normalize_vote(raw: Any) -> str:
    value = str(raw or '').strip().lower()
    if value in ('approve', 'reject', 'neutral'):
        return value
    if any(token in value for token in ('approve', 'buy', '찬성', '매수', '승인')):
        return 'approve'
    if any(token in value for token in ('reject', 'sell', '반대', '매도', '거절')):
        return 'reject'
    return 'neutral'


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
