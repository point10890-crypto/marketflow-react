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

from app.services.mirofish import evidence_packet as evidence_packet_mod
from app.services.mirofish import llm_client
from app.services.ai_routing.contracts import ProviderErrorClass

logger = logging.getLogger(__name__)
COMPACT_DEBATE_SYSTEM = '강세/약세 논거를 분리해 같은 EvidencePacket만 인용하세요.'

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
    '{"symbol":"고정값","name":"고정값","market":"고정값","analyst_mean":고정숫자,'
    '"stance": "bull|bear|neutral", "thesis": "최종 판단 근거 (2~4문장)", '
    '"confidence": 0~100 정수}'
)


# ── Public API ──────────────────────────────────────────────────────

def run_research_debate(
    target: str,
    reports: list[dict[str, Any]],
    *,
    rounds: int = 2,
    use_llm: bool = True,
    regime_line: str = '',
    context_line: str = '',
    run_id: str | None = None,
    symbol: str | None = None,
    market: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Run an N-round bull/bear debate and a manager verdict.

    Each piece (per-round bull/bear message, final manager judgment) is produced
    by the LLM when `use_llm`, otherwise by the deterministic rule composer. Any
    per-piece LLM failure falls back to the rule and downgrades `method`.

    `regime_line`, when non-empty, is prepended as a `[시장 레짐]` block into the
    LLM prompts only — the deterministic rule path ignores it.
    """
    reports = reports or []
    rounds = max(_MIN_ROUNDS, min(int(rounds or _MIN_ROUNDS), _MAX_ROUNDS))

    llm_ok = 0
    llm_fail = 0

    debate_rounds: list[dict[str, Any]] = []
    prev_bear = ''
    for round_num in range(1, rounds + 1):
        bull_msg, used_llm, bull_llm = _bull_message(target, reports, prev_bear, round_num, use_llm,
                                                       regime_line=regime_line,
                                                       context_line=context_line)
        llm_ok, llm_fail = _accumulate(used_llm, use_llm, llm_ok, llm_fail)

        bear_msg, used_llm_b, bear_llm = _bear_message(target, reports, bull_msg, round_num, use_llm,
                                                         regime_line=regime_line,
                                                         context_line=context_line)
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

    manager, used_llm_m = _manager_verdict(target, reports, debate_rounds, use_llm,
                                            regime_line=regime_line, context_line=context_line,
                                            run_id=run_id, symbol=symbol, market=market,
                                            name=name or target)
    llm_ok, llm_fail = _accumulate(used_llm_m, use_llm, llm_ok, llm_fail)

    rule_candidate = _manager_rule(reports)
    analysis_status = (
        str((manager.get('llm') or {}).get('analysis_status') or 'SUCCESS_PRIMARY')
        if used_llm_m else ('HOLD_REVIEW' if use_llm else 'SUCCESS_PRIMARY')
    )
    return {
        'rounds': debate_rounds,
        'bull_case': bull_case,
        'bear_case': bear_case,
        'manager': manager,
        'method': _resolve_method(use_llm, llm_ok, llm_fail),
        'analysis_status': analysis_status,
        'rule_candidate_verdict': rule_candidate,
    }


def run_compact_debate(
    target: str, reports: list[dict[str, Any]], *, use_llm: bool = True,
    run_id: str | None = None, request_id: str | None = None,
    reservation_id: str | None = None,
    reservation_owner_token: str | None = None,
    evidence_packet: dict[str, Any] | None = None,
    permit_abort_event: Any = None,
) -> dict[str, Any]:
    """One logical bull/bear call; the research manager remains deterministic."""
    rule_bull = _bull_message_rule(reports, 1)
    rule_bear = _bear_message_rule(reports, 1)
    packet = evidence_packet or {}
    llm_meta: dict[str, Any] | None = None
    citations_valid = not use_llm
    bull_case, bear_case = rule_bull, rule_bear
    bull_ids = list(packet.get('evidence_ids') or [])
    bear_ids = list(packet.get('evidence_ids') or [])
    allowed = set(packet.get('evidence_ids') or [])
    if use_llm:
        prompt = evidence_packet_mod.bound_compact_prompt((
            f"분석 대상: {target}\nEvidencePacket: {json.dumps(packet, ensure_ascii=False, default=str)}\n"
            'JSON: {"bull_case":"...","bear_case":"...","bull_evidence_ids":[],"bear_evidence_ids":[]}'
        ), 'compact_debate')
        raw, llm_meta = llm_client.generate_text_with_metadata(
            prompt, system=COMPACT_DEBATE_SYSTEM,
            temperature=0.2, max_tokens=768, json_mode=True,
            operation='compact_debate', run_id=run_id, request_id=request_id,
            reservation_id=reservation_id,
            reservation_owner_token=reservation_owner_token,
            domain_validator=_compact_debate_domain_validator(allowed),
            symbol=packet.get('symbol'), market=packet.get('market'),
            caller_endpoint='mirofish.tradingagents.compact_debate',
            permit_abort_event=permit_abort_event,
        )
        data = _parse_json_obj(raw)
        if data and str(data.get('bull_case') or '').strip() and str(data.get('bear_case') or '').strip():
            proposed_bull = list(data.get('bull_evidence_ids') or [])
            proposed_bear = list(data.get('bear_evidence_ids') or [])
            if proposed_bull and proposed_bear and set(proposed_bull + proposed_bear) <= allowed:
                bull_case = str(data['bull_case'])[:1500]
                bear_case = str(data['bear_case'])[:1500]
                bull_ids, bear_ids = proposed_bull, proposed_bear
                citations_valid = True
    manager = _manager_rule(reports)
    return {
        'rounds': [{'round': 1, 'bull': {'message': bull_case}, 'bear': {'message': bear_case}}],
        'bull_case': bull_case, 'bear_case': bear_case,
        'bull_evidence_ids': bull_ids, 'bear_evidence_ids': bear_ids,
        'manager': manager, 'method': 'llm' if llm_meta and llm_meta.get('success') else 'rule',
        'analysis_status': (
            (llm_meta or {}).get('analysis_status', 'DEGRADED')
            if citations_valid else ('DEGRADED' if use_llm else 'SUCCESS_PRIMARY')
        ),
        'llm': llm_meta,
        'rule_candidate_verdict': manager,
    }


def _compact_debate_domain_validator(allowed: set[str]):
    def validate(data: Any) -> ProviderErrorClass | None:
        if not isinstance(data, dict):
            return ProviderErrorClass.INVALID_JSON
        if not str(data.get('bull_case') or '').strip() or not str(data.get('bear_case') or '').strip():
            return ProviderErrorClass.INVALID_JSON
        bull_ids = data.get('bull_evidence_ids')
        bear_ids = data.get('bear_evidence_ids')
        if not isinstance(bull_ids, list) or not bull_ids or not isinstance(bear_ids, list) or not bear_ids:
            return ProviderErrorClass.INVALID_JSON
        if any(not isinstance(value, str) for value in bull_ids + bear_ids):
            return ProviderErrorClass.INVALID_JSON
        if not set(bull_ids + bear_ids) <= allowed:
            return ProviderErrorClass.INVALID_JSON
        return None
    return validate


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
                  round_num: int, use_llm: bool,
                  regime_line: str = '',
                  context_line: str = '') -> tuple[str, bool, dict[str, Any] | None]:
    if use_llm:
        try:
            msg, llm_meta = _llm_side(_BULL_SYSTEM, _BULL_JSON, target, reports, prev_bear,
                                      round_num, opponent_label='약세론',
                                      regime_line=regime_line, context_line=context_line)
            if msg:
                return msg, True, llm_meta
        except Exception as exc:  # noqa: BLE001 — isolate per-piece failure
            logger.warning('[research_debate] bull LLM failed R%d: %s', round_num, exc)
    return _bull_message_rule(reports, round_num), False, None


def _bear_message(target: str, reports: list[dict[str, Any]], prev_bull: str,
                  round_num: int, use_llm: bool,
                  regime_line: str = '',
                  context_line: str = '') -> tuple[str, bool, dict[str, Any] | None]:
    if use_llm:
        try:
            msg, llm_meta = _llm_side(_BEAR_SYSTEM, _BEAR_JSON, target, reports, prev_bull,
                                      round_num, opponent_label='강세론',
                                      regime_line=regime_line, context_line=context_line)
            if msg:
                return msg, True, llm_meta
        except Exception as exc:  # noqa: BLE001
            logger.warning('[research_debate] bear LLM failed R%d: %s', round_num, exc)
    return _bear_message_rule(reports, round_num), False, None


def _manager_verdict(target: str, reports: list[dict[str, Any]],
                     debate_rounds: list[dict[str, Any]],
                     use_llm: bool,
                     regime_line: str = '',
                     context_line: str = '', run_id: str | None = None,
                     symbol: str | None = None, market: str | None = None,
                     name: str | None = None) -> tuple[dict[str, Any], bool]:
    if use_llm:
        try:
            verdict = _llm_manager(target, reports, debate_rounds,
                                   regime_line=regime_line, context_line=context_line,
                                   run_id=run_id, symbol=symbol, market=market, name=name)
            if verdict:
                return verdict, True
        except Exception as exc:  # noqa: BLE001
            logger.warning('[research_debate] manager LLM failed: %s', exc)
    rule = _manager_rule(reports)
    return {
        'stance': 'hold_review', 'thesis': '결정 모델 검증이 완료되지 않아 검토가 필요합니다.',
        'confidence': 0.0, 'rule_candidate_verdict': rule,
    } if use_llm else rule, False


def _llm_side(system: str, json_hint: str, target: str, reports: list[dict[str, Any]],
              opponent_prev: str, round_num: int, *, opponent_label: str,
              regime_line: str = '',
              context_line: str = '') -> tuple[str | None, dict[str, Any]]:
    regime_block = f'[시장 레짐]\n{regime_line}\n\n' if regime_line else ''
    # 변형 RAG — 종목 키로 검색한 근거를 사실 자료로만 주입한다(지시문이 아니다)
    context_block = f'[검색된 근거]\n{context_line}\n\n' if context_line else ''
    prompt = (
        f'분석 대상: {target}\n라운드: {round_num}\n\n'
        f'{regime_block}'
        f'{context_block}'
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
                 debate_rounds: list[dict[str, Any]],
                 regime_line: str = '', context_line: str = '',
                 run_id: str | None = None, symbol: str | None = None,
                 market: str | None = None, name: str | None = None) -> dict[str, Any] | None:
    transcript = '\n'.join(
        f"R{r['round']} 강세: {r['bull']['message']}\nR{r['round']} 약세: {r['bear']['message']}"
        for r in debate_rounds
    )
    regime_block = f'[시장 레짐]\n{regime_line}\n\n' if regime_line else ''
    context_block = f'[검색된 근거]\n{context_line}\n\n' if context_line else ''
    prompt = (
        f'분석 대상: {target}\n\n'
        f'[애널리스트 리포트]\n{_reports_digest(reports)}\n\n'
        f'{regime_block}'
        f'{context_block}'
        f'[토론 기록]\n{transcript}\n\n'
        f'고정 식별자: symbol={symbol or ""}, name={name or target}, market={market or ""}, '
        f'analyst_mean={analyst_mean(reports)}\n{_MANAGER_JSON}'
    )
    raw, llm_meta = llm_client.generate_text_with_metadata(
        # 매니저 판정은 기계가 소비한다(decision_brief 근거·TA 가점·SELL 제외 임계 65).
        # 실측 2026-08-29: temp=0.3 에서 confidence 가 ±5(표준편차 2.23) 흔들렸다.
        # 결정론 생성으로 분산을 줄인다. 토론 메시지는 논거 다양성을 위해 확률적 유지.
        prompt, system=_MANAGER_SYSTEM, temperature=0.0, max_tokens=1200, json_mode=True,
        operation='decisive_text', run_id=run_id,
        request_id=f'{run_id}:{symbol or target}:research-manager' if run_id else None,
        symbol=symbol, market=market,
        expected_identity=(
            {'symbol': symbol, 'name': name or target, 'market': market}
            if symbol and market else None
        ),
        expected_numbers={'analyst_mean': analyst_mean(reports)} if symbol and market else None,
        domain_validator=_manager_domain_validator,
        caller_endpoint='mirofish.tradingagents.research_manager',
    )
    data = _parse_json_obj(raw)
    if not data:
        return None
    thesis = str(data.get('thesis') or '').strip()
    if not thesis:
        return None
    stance = str(data.get('stance') or '').strip().lower()
    if stance not in ('bull', 'bear', 'neutral'):
        return None
    # `or 50.0` 은 정당한 confidence 0 을 50 으로 승격시킨다 — None 일 때만 기본값.
    conf_raw = _safe_float(data.get('confidence'))
    if conf_raw is None:
        return None
    confidence = _clamp(conf_raw, 0.0, 100.0)
    return {
        'stance': stance, 'thesis': thesis[:1500], 'confidence': round(confidence, 2),
        'llm': llm_meta,
    }


def _manager_domain_validator(data: Any) -> ProviderErrorClass | None:
    if not isinstance(data, dict):
        return ProviderErrorClass.INVALID_JSON
    if str(data.get('stance') or '').strip().lower() not in {'bull', 'bear', 'neutral'}:
        return ProviderErrorClass.INVALID_JSON
    if not str(data.get('thesis') or '').strip():
        return ProviderErrorClass.INVALID_JSON
    confidence = _safe_float(data.get('confidence'))
    if confidence is None or not 0 <= confidence <= 100:
        return ProviderErrorClass.NUMERIC_MISMATCH
    return None


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
