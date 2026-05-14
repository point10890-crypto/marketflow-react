"""한국어 종목명 처리 — 초성 추출, 약어 별칭, 정규화.

청사진 ``mirofish_graphrag_analysis_endpoint_implementation_blueprint_2026_05_14.md``
§5.1 입력 유형 + §13 P0 #2 entity resolver 고도화 (초성, 복수 후보) 지원.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable


# 한글 초성 19개 (ㄱ ㄲ ㄴ ㄷ ㄸ ㄹ ㅁ ㅂ ㅃ ㅅ ㅆ ㅇ ㅈ ㅉ ㅊ ㅋ ㅌ ㅍ ㅎ)
_CHOSUNG = (
    'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ',
    'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ',
)

# 음절(가-힣) 코드 시작점 0xAC00
_SYLLABLE_BASE = 0xAC00
_SYLLABLE_LAST = 0xD7A3
_CHOSUNG_DIVISOR = 21 * 28  # 중성×종성 조합 수


def extract_chosung(text: str) -> str:
    """한글 문자열에서 초성만 추출. 비한글 문자는 그대로 유지.

    >>> extract_chosung('삼성전자')
    'ㅅㅅㅈㅈ'
    >>> extract_chosung('SK하이닉스')
    'SKㅎㅇㄴㅅ'
    >>> extract_chosung('한미반도체')
    'ㅎㅁㅂㄷㅊ'
    """
    if not text:
        return ''
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if _SYLLABLE_BASE <= code <= _SYLLABLE_LAST:
            chosung_idx = (code - _SYLLABLE_BASE) // _CHOSUNG_DIVISOR
            out.append(_CHOSUNG[chosung_idx])
        elif ch in _CHOSUNG:
            # 이미 초성 자체 (예: 'ㅅㅅㅈㅈ')
            out.append(ch)
        elif ch.isspace():
            continue
        else:
            out.append(ch)
    return ''.join(out)


def is_chosung_only(text: str) -> bool:
    """문자열이 한글 초성만으로 구성되어 있는지.

    >>> is_chosung_only('ㅅㅅㅈㅈ')
    True
    >>> is_chosung_only('삼성')
    False
    >>> is_chosung_only('ㅅSK')
    False
    """
    if not text:
        return False
    return all(ch in _CHOSUNG for ch in text if not ch.isspace())


def normalize_query(text: str) -> str:
    """resolver 입력 정규화.

    - 양끝 공백 제거
    - NFC 정규화 (한글 자모 결합 보장)
    - 영문은 upper 화 (ticker 대조)

    한글-영문 혼합은 알파벳 부분만 upper.
    """
    if text is None:
        return ''
    t = unicodedata.normalize('NFC', str(text).strip())
    if not t:
        return ''
    out: list[str] = []
    for ch in t:
        if ch.isascii() and ch.isalpha():
            out.append(ch.upper())
        else:
            out.append(ch)
    return ''.join(out)


# ── 약어 / 별칭 사전 (수동 큐레이션, 점진 확장) ───────────────────────

# 운영 중 발견되는 별칭은 여기에 등록 후 init 스크립트 재실행.
# entity_id 는 `kr:{ticker}` 형식 강제.
KOREAN_ALIASES: dict[str, str] = {
    # 삼성 그룹
    '삼전': 'kr:005930',
    '삼성전': 'kr:005930',
    'samsung': 'kr:005930',

    # SK 그룹
    '하닉': 'kr:000660',
    'SK하닉': 'kr:000660',
    '하이닉스': 'kr:000660',

    # LG 그룹
    'LG엔솔': 'kr:373220',
    'LG에너지': 'kr:373220',

    # 현대 그룹
    '현차': 'kr:005380',
    '현대차': 'kr:005380',

    # 네카오
    '네이버': 'kr:035420',
    'NAVER': 'kr:035420',
    '카톡': 'kr:035720',
    '카카오톡': 'kr:035720',

    # 반도체 장비
    '한미': 'kr:042700',
    '한미반도': 'kr:042700',
}


def iter_alias_records() -> Iterable[tuple[str, str, str]]:
    """``(alias, entity_id, source='manual')`` 튜플 yield.

    init 스크립트에서 SQLite entity_aliases 테이블에 적재할 때 사용.
    """
    for alias, entity_id in KOREAN_ALIASES.items():
        yield (alias, entity_id, 'manual')
