# -*- coding: utf-8 -*-
"""L4 기계적 검증 — LLM 산출 수치를 수집기 원천과 대조한다.

프로젝트 전반의 원칙 "LLM 은 숫자를 소유하지 않는다"를 규칙 문장이 아니라 **코드로
강제**하는 계층. LLM 이 만든 값은 진실로 취급하지 않으며, 수집기(KIS·DART·
daily_prices·스냅샷)가 가져온 번들 값만 대조 기준이 된다.

정책
    contradicted ≥ 1  → 산출 폐기 (호출부가 결정론 템플릿으로 대체)
    unverified 만     → 산출 유지 + 신뢰 상한 감산 + 공백 기록
    전부 verified     → 통과

대조 불가(번들 부재)는 폐기 사유가 아니다 — 검증하지 못했음을 미검증으로 남긴다.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 'mirofish.number_guard.v1'
POLICY = 'discard_on_contradiction'

# 표기 반올림 차이만 허용한다 (상대 1%).
RELATIVE_TOLERANCE = 0.01
ABSOLUTE_TOLERANCE = 0.005

MAX_CAP_PENALTY = 0.20
UNVERIFIED_PENALTY_STEP = 0.05

# 연도·회차처럼 수치 주장이 아닌 토큰은 추출 대상에서 제외한다.
_YEAR_MIN, _YEAR_MAX = 1900, 2200
_NON_CLAIM_SUFFIX = ('년', '월', '일', '회', '차', '위', '번', '개월', '분기')

_NUMBER_RE = re.compile(
    r'(?P<sign>[+\-−])?'
    r'(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
    r'\s*(?P<suffix>%|퍼센트|억원|억|만원|원|배|포인트|p)?'
)

# 번들 필드 ↔ 단위 힌트 (대조 후보를 좁혀 오탐을 줄인다)
_UNIT_FIELDS = {
    'percent': ('chg_pct', 'change_pct', 'return_pct', 'win_rate_pct', 'expectancy_pct',
                'avg_return_pct', 'rs_rating', 'breadth_pct'),
    'eok': ('trading_value_eok', 'trval_eok', 'trading_value'),
    'won': ('current_price', 'price', 'entry_price', 'stop_price', 'target_price', 'close'),
}

# 모순 판정을 좁히는 문맥 키워드. 단위가 같다는 이유만으로 모순 처리하면
# ROE·부채비율·52주 낙폭처럼 의미가 다른 지표까지 환각으로 몰린다
# (실데이터 육안 검증 2026-08-29). 문맥이 그 필드를 가리킬 때만 모순으로 본다.
_FIELD_CONTEXT = {
    'chg_pct': ('등락', '상승', '하락', '급등', '급락', '전일', '마감', '올라', '떨어'),
    'change_pct': ('등락', '상승', '하락', '급등', '급락', '전일', '마감', '올라', '떨어'),
    'return_pct': ('수익률', '기대값'),
    'rs_rating': ('RS', '상대강도'),
    'current_price': ('주가', '종가', '가격', '거래', '원에'),
    'price': ('주가', '종가', '가격', '거래', '원에'),
    'trading_value_eok': ('거래대금',),
    'trval_eok': ('거래대금',),
    'trading_value': ('거래대금',),
}

# 하락 서술은 음수를 뜻한다 — "3.38% 하락"과 번들의 -3.38 은 같은 사실이다.
_NEGATIVE_WORDS = ('하락', '급락', '떨어', '내리', '하회', '감소', '마이너스')

# 기준 프레임이 다른 서술은 일간 지표와 비교할 수 없다.
# "52주 최고가 대비 31.4% 하락"은 당일 등락률(-3.38%)과 다른 사실이다.
_SCOPE_QUALIFIERS = ('52주', '최고가 대비', '고점 대비', '저점 대비', '연초',
                     '전년', '누적', '평균', '업종', '기간')


def _context_points_to(field: str, context: str) -> bool:
    keywords = _FIELD_CONTEXT.get(field.split('.')[-1])
    if not keywords:
        return False
    if any(q in context for q in _SCOPE_QUALIFIERS):
        return False  # 다른 기준 프레임의 수치 — 모순 판정 대상이 아니다
    return any(k in context for k in keywords)


def _signed_variants(value: float, context: str) -> list[float]:
    """부호 표기 차이를 흡수한다(값은 양수인데 문맥이 하락인 경우)."""
    if value > 0 and any(w in context for w in _NEGATIVE_WORDS):
        return [value, -value]
    return [value]


def _unit_of(suffix: str | None) -> str:
    if not suffix:
        return 'plain'
    if suffix in ('%', '퍼센트'):
        return 'percent'
    if suffix in ('억원', '억'):
        return 'eok'
    if suffix in ('원', '만원'):
        return 'won'
    return 'plain'


def _is_non_claim(text: str, start: int, end: int, value: float) -> bool:
    """연도·회차·순번 등 사실 주장이 아닌 수치를 걸러낸다."""
    tail = text[end:end + 3]
    if tail.startswith(_NON_CLAIM_SUFFIX):
        return True
    if float(value).is_integer() and _YEAR_MIN <= value <= _YEAR_MAX:
        return True
    head = text[max(0, start - 2):start]
    if head.endswith('제'):  # 제1236회
        return True
    return False


def extract_claims(text: Any) -> list[dict[str, Any]]:
    """LLM 산출 텍스트에서 검증 대상 수치를 뽑는다."""
    body = str(text or '')
    claims: list[dict[str, Any]] = []
    for m in _NUMBER_RE.finditer(body):
        raw_num = m.group('num').replace(',', '')
        try:
            value = float(raw_num)
        except ValueError:
            continue
        if _is_non_claim(body, m.start(), m.end('num'), value):
            continue
        sign = m.group('sign')
        if sign in ('-', '−'):
            value = -value
        claims.append({
            'raw': m.group(0).strip(),
            'value': value,
            'unit': _unit_of(m.group('suffix')),
            'context': body[max(0, m.start() - 20):m.end() + 20].strip(),
        })
    return claims


def _close_enough(a: float, b: float) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    if scale == 0:
        return abs(a - b) <= ABSOLUTE_TOLERANCE
    return abs(a - b) / scale <= RELATIVE_TOLERANCE


def _candidate_fields(bundle: dict[str, Any], unit: str) -> list[tuple[str, float]]:
    preferred = _UNIT_FIELDS.get(unit, ())
    out: list[tuple[str, float]] = []
    for key, val in bundle.items():
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        out.append((str(key), float(val)))
    if preferred:
        out.sort(key=lambda kv: 0 if kv[0] in preferred else 1)
    return out


def _lookahead_violation(as_of: Any, watermark: Any) -> bool:
    """인용 기준일이 번들 워터마크보다 미래면 lookahead."""
    if not as_of or not watermark:
        return False
    try:
        a = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
        w = datetime.fromisoformat(str(watermark).replace('Z', '+00:00'))
    except ValueError:
        return False
    if (a.tzinfo is None) != (w.tzinfo is None):
        a, w = a.replace(tzinfo=None), w.replace(tzinfo=None)
    return a > w


def verify_claims(claims: list[dict[str, Any]], bundle: Any,
                  *, as_of: Any = None) -> dict[str, Any]:
    """각 수치를 번들과 대조한다. 대조 불가는 미검증이지 모순이 아니다."""
    verified: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    contradicted: list[dict[str, Any]] = []

    src = bundle if isinstance(bundle, dict) else {}
    watermark = src.get('source_watermark')
    lookahead = _lookahead_violation(as_of, watermark)

    for claim in claims or []:
        item = dict(claim)
        if lookahead:
            item['reason'] = 'lookahead'
            item['as_of'] = as_of
            contradicted.append(item)
            continue

        candidates = _candidate_fields(src, str(claim.get('unit') or 'plain'))
        context = str(claim.get('context') or '')
        variants = _signed_variants(float(claim.get('value')), context)
        match = next((k for k, v in candidates
                      if any(_close_enough(x, v) for x in variants)), None)
        if match is not None:
            item['matched_field'] = match
            item['status'] = 'verified'
            verified.append(item)
            continue

        # 모순은 **문맥이 그 필드를 가리킬 때만** 인정한다. 단위만 같고 의미가 다른
        # 지표(ROE·부채비율·52주 낙폭 등)는 대응 필드가 없는 것이므로 미검증이다.
        expected = _UNIT_FIELDS.get(str(claim.get('unit') or ''), ())
        unit_fields = [(k, v) for k, v in candidates
                       if k.split('.')[-1] in expected and _context_points_to(k, context)]
        if unit_fields:
            item['status'] = 'contradicted'
            item['reason'] = 'value_mismatch'
            item['expected_fields'] = [k for k, _ in unit_fields]
            contradicted.append(item)
        else:
            item['status'] = 'unverified'
            item['reason'] = 'no_matching_source_field'
            unverified.append(item)

    return {'verified': verified, 'unverified': unverified, 'contradicted': contradicted}


def guard_output(text: Any, bundle: Any, *, as_of: Any = None) -> tuple[bool, dict[str, Any]]:
    """산출 채택 여부와 검증 리포트를 반환한다."""
    claims = extract_claims(text)
    detail = verify_claims(claims, bundle, as_of=as_of)
    accepted = not detail['contradicted']
    verdict = {
        'schema_version': SCHEMA_VERSION,
        'policy': POLICY,
        'accepted': accepted,
        'verified': len(detail['verified']),
        'unverified': len(detail['unverified']),
        'contradicted': len(detail['contradicted']),
        'claims': (detail['verified'] + detail['unverified'] + detail['contradicted'])[:20],
    }
    return accepted, verdict


def cap_penalty(counts: dict[str, Any]) -> float:
    """미검증 수치 비율에 비례한 신뢰 상한 감산값 (상한 고정)."""
    try:
        unverified = int(counts.get('unverified') or 0)
        contradicted = int(counts.get('contradicted') or 0)
    except (TypeError, ValueError):
        return 0.0
    if unverified <= 0 and contradicted <= 0:
        return 0.0
    penalty = (unverified + contradicted * 2) * UNVERIFIED_PENALTY_STEP
    return round(min(penalty, MAX_CAP_PENALTY), 4)


def flatten_numeric(bundle: Any, *, prefix: str = '', depth: int = 0) -> dict[str, Any]:
    """중첩 수집기 번들을 대조 가능한 평면 수치 사전으로 편다.

    문자열·불리언·None 은 대조 대상이 아니므로 버린다. 단 `source_watermark` 만은
    lookahead 검사에 필요하므로 원형으로 보존한다.
    """
    out: dict[str, Any] = {}
    if depth > 4 or not isinstance(bundle, dict):
        return out
    for key, value in bundle.items():
        path = f'{prefix}{key}'
        if key == 'source_watermark' and value:
            out['source_watermark'] = value
            continue
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            out[path] = float(value)
        elif isinstance(value, dict):
            out.update(flatten_numeric(value, prefix=f'{path}.', depth=depth + 1))
    return out


def aggregate_verification(reports: Any) -> dict[str, int] | None:
    """리포트들의 검증 결과를 합산한다. 검증된 리포트가 하나도 없으면 None."""
    total = {'verified': 0, 'unverified': 0, 'contradicted': 0}
    found = False
    for report in reports or []:
        detail = (report or {}).get('number_verification') if isinstance(report, dict) else None
        if not isinstance(detail, dict):
            continue
        found = True
        for key in total:
            try:
                total[key] += int(detail.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return total if found else None
