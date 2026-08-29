"""Four-analyst report layer (TradingAgents Analyst Team, KR-native).

Ports the TradingAgents "Analyst Team" concept: four specialists each read
ONLY their own slice of the data bundle and produce an independent report.
Each role tries an LLM first (`llm_client.generate_text`, JSON mode) and falls
back to a deterministic rule scorer per role — a single role's LLM failure
never drags the others down.

Report schema (LOCKED — later tasks depend on this):
    {
        'role': 'fundamentals'|'news'|'sentiment'|'technical',
        'title': str, 'summary': str,   # Korean
        'stance': 'bullish'|'bearish'|'neutral',
        'score': float,                 # -100..100
        'evidence': list[str],
        'method': 'llm'|'rule',
    }

Deterministic rule scoring (verified by tests):
    technical:    trend up/bullish +40, down/bearish -40; MA aligned +20;
                  rs_rating>=80 +30, <=20 -30.
    news:         (positive_kw - negative_kw) * 10, clamp +-40.
    sentiment:    news keyword score + (change_pct*3 clamp +-30).
    fundamentals: PER/ROE valuation; no data -> score 0, evidence '데이터 부족'.
    stance:       score>=15 bullish, <=-15 bearish, else neutral.

Technical normalization note:
    The rule scorer accepts BOTH the real `analyze_target_with_levels` vocab
    (trend='bullish'/'bearish', `indicators` SMA ordering) AND the normalized
    test vocab (trend='up'/'down', explicit `ma_aligned`). `ma_aligned` is read
    directly when present, otherwise derived from sma5>sma20>sma60.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.mirofish import llm_client
from app.services.mirofish.tradingagents import regime as regime_mod

logger = logging.getLogger(__name__)

ROLES: tuple[str, ...] = ('fundamentals', 'news', 'sentiment', 'technical')

ROLE_TITLES: dict[str, str] = {
    'fundamentals': '펀더멘털 분석',
    'news': '뉴스/재료 분석',
    'sentiment': '투자심리 분석',
    'technical': '기술적 분석',
}

POSITIVE_NEWS_KEYWORDS: tuple[str, ...] = ('수주', '계약', '흑자', '신고가', '급등', '무상증자', '자사주')
NEGATIVE_NEWS_KEYWORDS: tuple[str, ...] = ('소송', '횡령', '적자', '하한가', '유상증자', '감자')

_STANCE_BULLISH_CUTOFF = 15.0
_STANCE_BEARISH_CUTOFF = -15.0

_SYSTEM_PROMPTS: dict[str, str] = {
    'fundamentals': (
        '당신은 펀더멘털 애널리스트입니다. 제공된 재무 데이터(PER/ROE/시가총액/DART 스냅샷)'
        '만 근거로 판단하고, 반드시 구체적 수치를 인용하세요. 데이터가 없으면 중립으로 판단합니다.'
    ),
    'news': (
        '당신은 뉴스/재료 애널리스트입니다. 제공된 뉴스 코퍼스만 근거로 호재/악재를 판별하고,'
        '반드시 코퍼스의 구체적 문구를 인용하세요.'
    ),
    'sentiment': (
        '당신은 투자심리 애널리스트입니다. 뉴스 코퍼스 어조와 당일 등락률을 결합해 심리를 평가하고,'
        '반드시 구체적 근거를 인용하세요.'
    ),
    'technical': (
        '당신은 기술적 분석 애널리스트입니다. 추세/이동평균/상대강도(RS) 데이터만 근거로 판단하고,'
        '반드시 구체적 지표 수치를 인용하세요.'
    ),
}

_JSON_INSTRUCTION = (
    '다음 JSON 형식으로만 응답하세요: '
    '{"title": "짧은 제목", "summary": "한국어 분석 (2~4문장)", '
    '"stance": "bullish|bearish|neutral", "score": -100~100 정수, '
    '"evidence": ["근거1", "근거2"]}'
)


# ── Public API ──────────────────────────────────────────────────────

def run_analysts(bundle: dict[str, Any], *, use_llm: bool = True) -> list[dict[str, Any]]:
    """Return exactly four analyst reports in fixed role order.

    Per role: try the LLM (when `use_llm`), fall back to the rule scorer on any
    failure (None response, parse error, exception). Roles are independent.
    """
    reports: list[dict[str, Any]] = []
    for role in ROLES:
        report: dict[str, Any] | None = None
        if use_llm:
            try:
                report = _llm_report(role, bundle)
            except Exception as exc:  # noqa: BLE001 — isolate per-role LLM failure
                logger.warning('[analysts] LLM report failed for %s: %s', role, exc)
                report = None
        if not report:
            report = _rule_report(role, bundle)
        else:
            _attach_number_verification(report, bundle)
        reports.append(report)
    return reports


def _attach_number_verification(report: dict[str, Any], bundle: Any) -> None:
    """L4 기계적 검증 — LLM 리포트의 수치를 수집기 번들과 대조해 결과를 첨부한다.

    shadow 단계: 검증에 실패해도 리포트를 폐기하지 않는다. 관측을 먼저 쌓고,
    정책 전환(폐기)은 표본이 모인 뒤 별도로 판단한다.
    """
    try:
        from app.services.mirofish import number_guard

        text = f"{report.get('summary') or ''} {' '.join(report.get('evidence') or [])}"
        _, verdict = number_guard.guard_output(text, number_guard.flatten_numeric(bundle))
        report['number_verification'] = {
            'verified': verdict['verified'],
            'unverified': verdict['unverified'],
            'contradicted': verdict['contradicted'],
            'policy': 'shadow',
        }
    except Exception as exc:  # noqa: BLE001 — 검증 실패가 분석을 막지 않는다
        logger.warning('[analysts] number verification skipped: %s', exc)


# ── Rule reports ────────────────────────────────────────────────────

def _rule_report(role: str, bundle: dict[str, Any]) -> dict[str, Any]:
    score, evidence = _RULE_SCORERS[role](bundle)
    score = _clamp(score, -100.0, 100.0)
    stance = _stance(score)
    summary = _rule_summary(role, bundle, stance, evidence)
    return {
        'role': role,
        'title': ROLE_TITLES[role],
        'summary': summary,
        'stance': stance,
        'score': float(score),
        'evidence': evidence,
        'method': 'rule',
    }


def _score_technical(bundle: dict[str, Any]) -> tuple[float, list[str]]:
    tech = bundle.get('technical') or {}
    rs = bundle.get('rs') or {}
    score = 0.0
    evidence: list[str] = []

    trend = str(tech.get('trend') or '').strip().lower()
    if trend in ('up', 'bullish'):
        score += 40.0
        evidence.append('추세 상승(+40)')
    elif trend in ('down', 'bearish'):
        score -= 40.0
        evidence.append('추세 하락(-40)')
    else:
        evidence.append('추세 중립')

    if _ma_aligned(tech):
        score += 20.0
        evidence.append('이동평균선 정배열(+20)')

    rating = _safe_int(rs.get('rs_rating'))
    if rating is not None:
        if rating >= 80:
            score += 30.0
            evidence.append(f'RS {rating} 시장 주도주(+30)')
        elif rating <= 20:
            score -= 30.0
            evidence.append(f'RS {rating} 후행 반등 위험(-30)')
        else:
            evidence.append(f'RS {rating}')

    return score, evidence


def _score_news(bundle: dict[str, Any]) -> tuple[float, list[str]]:
    score, pos, neg = _news_keyword_score(bundle.get('corpus'))
    evidence = [f'호재 키워드 {pos}건', f'악재 키워드 {neg}건', f'키워드 심리 {score:+.0f}']
    return score, evidence


def _score_sentiment(bundle: dict[str, Any]) -> tuple[float, list[str]]:
    news_score, _pos, _neg = _news_keyword_score(bundle.get('corpus'))
    change = _safe_float((bundle.get('price') or {}).get('change_pct')) or 0.0
    change_component = _clamp(change * 3.0, -30.0, 30.0)
    score = news_score + change_component
    evidence = [
        f'뉴스 어조 {news_score:+.0f}',
        f'당일 등락률 {change:+.2f}% 반영 {change_component:+.0f}',
    ]
    return score, evidence


def _score_fundamentals(bundle: dict[str, Any]) -> tuple[float, list[str]]:
    fund = bundle.get('fundamentals') or {}
    pe = _safe_float(fund.get('trailingPE'))
    if pe is None:
        pe = _safe_float(fund.get('forwardPE'))
    roe = _safe_float(fund.get('returnOnEquity'))

    if pe is None and roe is None:
        return 0.0, ['데이터 부족 — 재무 지표 없음']

    score = 0.0
    evidence: list[str] = []

    if pe is not None:
        if pe <= 0:
            evidence.append(f'PER {pe:.1f} 적자/비정상')
        elif pe < 10:
            score += 25.0
            evidence.append(f'PER {pe:.1f} 저평가(+25)')
        elif pe < 15:
            score += 15.0
            evidence.append(f'PER {pe:.1f} 양호(+15)')
        elif pe < 25:
            score += 5.0
            evidence.append(f'PER {pe:.1f} 보통(+5)')
        elif pe < 40:
            score -= 5.0
            evidence.append(f'PER {pe:.1f} 다소 높음(-5)')
        else:
            score -= 15.0
            evidence.append(f'PER {pe:.1f} 고평가(-15)')

    if roe is not None:
        roe_pct = roe * 100.0
        if roe >= 0.20:
            score += 25.0
            evidence.append(f'ROE {roe_pct:.0f}% 우수(+25)')
        elif roe >= 0.10:
            score += 15.0
            evidence.append(f'ROE {roe_pct:.0f}% 양호(+15)')
        elif roe >= 0.05:
            score += 5.0
            evidence.append(f'ROE {roe_pct:.0f}% 보통(+5)')
        elif roe < 0:
            score -= 20.0
            evidence.append(f'ROE {roe_pct:.0f}% 손실(-20)')
        else:
            evidence.append(f'ROE {roe_pct:.0f}%')

    return score, evidence


_RULE_SCORERS = {
    'fundamentals': _score_fundamentals,
    'news': _score_news,
    'sentiment': _score_sentiment,
    'technical': _score_technical,
}


def _rule_summary(role: str, bundle: dict[str, Any], stance: str, evidence: list[str]) -> str:
    name = str(bundle.get('display_name') or bundle.get('target') or '대상')
    label = {'bullish': '긍정', 'bearish': '부정', 'neutral': '중립'}[stance]
    detail = ' · '.join(evidence) if evidence else '판단 근거 부족'
    return f'{name} {ROLE_TITLES[role]} 결과 {label}. {detail}.'


# ── LLM reports ─────────────────────────────────────────────────────

def _llm_report(role: str, bundle: dict[str, Any]) -> dict[str, Any] | None:
    prompt = _build_prompt(role, bundle)
    raw, llm_meta = llm_client.generate_text_with_metadata(
        prompt,
        system=_SYSTEM_PROMPTS[role],
        temperature=0.3,
        max_tokens=2048,
        json_mode=True,
    )
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning('[analysts] %s LLM JSON parse failed', role)
        return None
    if not isinstance(data, dict):
        return None

    summary = str(data.get('summary') or '').strip()
    if not summary:
        return None

    score = _clamp(_safe_float(data.get('score')) or 0.0, -100.0, 100.0)
    stance = _normalize_stance(data.get('stance'), score)

    evidence = data.get('evidence')
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = []
    evidence = [str(item)[:200] for item in evidence[:8] if str(item).strip()]

    title = str(data.get('title') or ROLE_TITLES[role]).strip()[:120] or ROLE_TITLES[role]

    return {
        'role': role,
        'title': title,
        'summary': summary[:1500],
        'stance': stance,
        'score': float(score),
        'evidence': evidence,
        'method': 'llm',
        'llm': llm_meta,
    }


def _build_prompt(role: str, bundle: dict[str, Any]) -> str:
    name = str(bundle.get('display_name') or bundle.get('target') or '대상')
    symbol = str(bundle.get('symbol') or '')
    header = f'분석 대상: {name} ({symbol})'
    regime_line = regime_mod.regime_context(bundle.get('brain')).get('line') or ''
    regime_block = f'\n[시장 레짐]\n{regime_line}\n' if regime_line else ''
    slice_text = _role_data_slice(role, bundle)
    return f'{header}{regime_block}\n[데이터]\n{slice_text}\n\n{_JSON_INSTRUCTION}'


def _role_data_slice(role: str, bundle: dict[str, Any]) -> str:
    if role == 'fundamentals':
        payload = {'fundamentals': bundle.get('fundamentals') or {}}
    elif role == 'news':
        payload = {'corpus': _truncate(bundle.get('corpus'), 3000)}
    elif role == 'sentiment':
        price = bundle.get('price') or {}
        payload = {
            'corpus': _truncate(bundle.get('corpus'), 2000),
            'change_pct': price.get('change_pct'),
            'price': price.get('price'),
        }
    else:  # technical
        payload = {'technical': bundle.get('technical') or {}, 'rs': bundle.get('rs') or {}}
    return json.dumps(payload, ensure_ascii=False, default=str)


# ── Shared helpers ──────────────────────────────────────────────────

def _news_keyword_score(corpus: Any) -> tuple[float, int, int]:
    text = str(corpus or '')
    positive = sum(text.count(kw) for kw in POSITIVE_NEWS_KEYWORDS)
    negative = sum(text.count(kw) for kw in NEGATIVE_NEWS_KEYWORDS)
    score = _clamp((positive - negative) * 10.0, -40.0, 40.0)
    return score, positive, negative


def _ma_aligned(tech: dict[str, Any]) -> bool:
    if 'ma_aligned' in tech:
        return bool(tech.get('ma_aligned'))
    indicators = tech.get('indicators') or {}
    sma5 = _safe_float(indicators.get('sma5'))
    sma20 = _safe_float(indicators.get('sma20'))
    sma60 = _safe_float(indicators.get('sma60'))
    if None in (sma5, sma20, sma60):
        return False
    return sma5 > sma20 > sma60


def _stance(score: float) -> str:
    if score >= _STANCE_BULLISH_CUTOFF:
        return 'bullish'
    if score <= _STANCE_BEARISH_CUTOFF:
        return 'bearish'
    return 'neutral'


def _normalize_stance(raw: Any, score: float) -> str:
    value = str(raw or '').strip().lower()
    if value in ('bullish', 'bearish', 'neutral'):
        return value
    if any(token in value for token in ('bull', 'buy', '매수', '강세', '긍정')):
        return 'bullish'
    if any(token in value for token in ('bear', 'sell', '매도', '약세', '부정')):
        return 'bearish'
    return _stance(score)


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


def _safe_int(value: Any) -> int | None:
    number = _safe_float(value)
    return int(number) if number is not None else None


def _truncate(text: Any, max_len: int) -> str:
    text = str(text or '')
    return text if len(text) <= max_len else text[: max_len - 1] + '…'
