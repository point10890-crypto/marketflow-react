# -*- coding: utf-8 -*-
"""적합성 깔때기 (0~2단) — 전부 결정론. LLM 을 호출하지 않는다.

하루 수만 건의 기사를 종목·테마와 무관한 것부터 즉시 버려, 사건 후보 수십 건만 남긴다.
원문 본문은 어느 단계에서도 보관하지 않는다.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

SUMMARY_MAX = 500

# 소스 등급 가중 — S: 거래소·공시 / A: 공식 통계·기관 / B: 언론 / C: 미검증
GRADE_WEIGHT = {'S': 3.0, 'A': 2.0, 'B': 1.0, 'C': 0.4}

SYMBOL_HIT_WEIGHT = 1.0
THEME_HIT_WEIGHT = 0.5
CORROBORATION_WEIGHT = 0.8
MIN_NAME_LEN = 2

_TICKER_RE = re.compile(r'(?<!\d)(\d{6})(?!\d)')
_HANGUL_OR_WORD = re.compile(r'[가-힣A-Za-z0-9]')

# 회사명이 일반명사·지명과 겹치는 종목들. 실데이터 육안 검증(2026-08-29)에서
# '반도체 대상 관세', '진도군 업무협약', '미래산업 유치' 같은 오탐이 나왔다.
# 이 이름들은 금융 문맥이 함께 있을 때만 종목 지목으로 인정한다.
AMBIGUOUS_NAMES = frozenset({
    '대상', '진도', '미래산업', '이수', '한일', '대한', '동원', '세방', '동양',
    '광주', '대구', '전방', '한섬', '삼양', '태경', '보령', '신도', '오리온',
    '경남', '무학',
})

# 종목 문맥을 가리키는 결정론 키워드 (LLM 없음)
FINANCIAL_CONTEXT = (
    '주가', '주식', '증자', '공시', '상장', '실적', '매출', '영업이익', '순이익',
    '특징주', '장중', '거래량', '거래대금', '지분', '인수', '배당', '자사주',
    '목표주가', '코스피', '코스닥', '증권', '주주', '시총', '시가총액', '급등',
    '급락', '체결', '호가', '수주', '계약 체결', '흑자', '적자',
)


def has_financial_context(text: str) -> bool:
    return any(k in text for k in FINANCIAL_CONTEXT)


def content_hash(title: Any, link: Any) -> str:
    """제목+링크로 만드는 안정 식별자 — 같은 기사의 재수집·정정판 중복을 막는다."""
    payload = f'{str(title or "").strip()}|{str(link or "").strip()}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _is_standalone(text: str, start: int, end: int) -> bool:
    """앞뒤가 다른 단어에 붙어 있지 않은지 — 부분 일치 오탐을 줄인다."""
    before = text[start - 1] if start > 0 else ''
    after = text[end] if end < len(text) else ''
    touching_before = bool(before) and bool(_HANGUL_OR_WORD.match(before))
    touching_after = bool(after) and bool(_HANGUL_OR_WORD.match(after))
    return not touching_before and not touching_after


def match_symbols(text: Any, universe: dict[str, str]) -> list[str]:
    """종목명 또는 6자리 코드로 결정론 매칭. 긴 이름을 먼저 시도해 부분 일치를 피한다."""
    body = str(text or '')
    if not body:
        return []
    hits: list[str] = []

    for code in _TICKER_RE.findall(body):
        if code in universe and code not in hits:
            hits.append(code)

    for code, name in sorted(universe.items(), key=lambda kv: -len(str(kv[1] or ''))):
        label = str(name or '').strip()
        if len(label) < MIN_NAME_LEN or code in hits:
            continue
        ambiguous = label in AMBIGUOUS_NAMES or len(label) <= 2
        if ambiguous and not has_financial_context(body):
            continue  # 일반명사와 겹치는 이름은 금융 문맥이 있어야 인정한다
        idx = body.find(label)
        while idx != -1:
            if _is_standalone(body, idx, idx + len(label)):
                hits.append(code)
                break
            idx = body.find(label, idx + 1)
    return hits


def match_themes(text: Any, theme_map: dict[str, str]) -> list[str]:
    """키워드 → 테마 결정론 매핑."""
    body = str(text or '')
    out: list[str] = []
    for keyword, theme in (theme_map or {}).items():
        if keyword and keyword in body and theme not in out:
            out.append(theme)
    return out


def importance_score(*, symbols: Iterable[str], themes: Iterable[str],
                     grade: str, corroboration: int = 1) -> float:
    """2단 중요도. 매칭이 하나도 없으면 0 — 곧 폐기 대상이다."""
    sym = list(symbols or [])
    thm = list(themes or [])
    if not sym and not thm:
        return 0.0
    base = GRADE_WEIGHT.get(str(grade or 'C').upper(), GRADE_WEIGHT['C'])
    hits = len(sym) * SYMBOL_HIT_WEIGHT + len(thm) * THEME_HIT_WEIGHT
    corr = max(0, int(corroboration or 1) - 1) * CORROBORATION_WEIGHT
    return round(base + hits + corr, 3)


def run_funnel(items: list[dict[str, Any]], universe: dict[str, str],
               theme_map: dict[str, str], *, min_score: float = 0.0) -> list[dict[str, Any]]:
    """0~2단 통과분만 반환. 본문 필드는 절대 실어 나르지 않는다."""
    staged: dict[str, dict[str, Any]] = {}

    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get('title') or '').strip()
        if not title:
            continue
        link = str(raw.get('link') or '').strip()
        digest = content_hash(title, link)

        if digest in staged:
            staged[digest]['corroboration'] += 1
            sources = staged[digest]['sources']
            src = str(raw.get('source') or '')
            if src and src not in sources:
                sources.append(src)
            continue

        summary = str(raw.get('summary') or '').strip()[:SUMMARY_MAX]
        haystack = f'{title} {summary}'
        symbols = match_symbols(haystack, universe)
        themes = match_themes(haystack, theme_map)
        if not symbols and not themes:
            continue  # 1단에서 즉시 폐기

        staged[digest] = {
            'content_hash': digest,
            'title': title,
            'summary': summary,
            'link': link,
            'source': str(raw.get('source') or ''),
            'sources': [str(raw.get('source') or '')],
            'grade': str(raw.get('grade') or 'C').upper(),
            'published_ts': raw.get('published_ts'),
            'symbols': symbols,
            'themes': themes,
            'corroboration': 1,
        }

    kept: list[dict[str, Any]] = []
    for event in staged.values():
        event['score'] = importance_score(
            symbols=event['symbols'], themes=event['themes'],
            grade=event['grade'], corroboration=event['corroboration'])
        if event['score'] > min_score:
            kept.append(event)
    kept.sort(key=lambda e: (-e['score'], str(e.get('published_ts') or '')))
    return kept
