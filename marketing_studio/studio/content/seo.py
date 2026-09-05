"""네이버 블로그 SEO 점검기 — 결정론적 100점 만점 채점 + 개선 제안.

C-Rank/D.I.A. 를 의식한 실무 규칙: 키워드는 제목·서두·소제목에, 본문 1,500자+, 이미지 3장+, 해시태그, 표시(공정위) 문구.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from studio.utils import korean_char_count

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", re.M)


@dataclass
class SEOCheck:
    name: str
    label: str
    passed: bool
    weight: int
    detail: str = ""


@dataclass
class SEOReport:
    score: int = 0
    checks: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def strip_markdown(markdown: str) -> str:
    text = _MD_IMAGE_RE.sub(" ", markdown or "")
    text = _MD_LINK_RE.sub(r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`>]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M)
    return text


def keyword_occurrences(text: str, keyword: str) -> int:
    if not keyword:
        return 0
    return _norm(text).count(_norm(keyword))


def keyword_density(text: str, keyword: str) -> float:
    """공백 제거 글자 기준 밀도(%) = 등장횟수 × 키워드 길이 / 전체 글자수."""
    total = korean_char_count(text)
    if not total or not keyword:
        return 0.0
    return round(keyword_occurrences(text, keyword) * len(_norm(keyword)) / total * 100, 2)


def headings(markdown: str) -> list[str]:
    return [h.strip() for h in _HEADING_RE.findall(markdown or "")]


def analyze_post(
    *,
    title: str,
    markdown: str,
    primary_keyword: str,
    meta_description: str = "",
    hashtags: list[str] | None = None,
    image_count: int | None = None,
    disclosure_present: bool | None = None,
) -> SEOReport:
    hashtags = hashtags or []
    body = strip_markdown(markdown)
    chars = korean_char_count(body)
    kw_norm = _norm(primary_keyword)
    title_norm = _norm(title)
    heads = headings(markdown)
    imgs = image_count if image_count is not None else len(_MD_IMAGE_RE.findall(markdown or ""))
    density = keyword_density(body, primary_keyword)
    occurrences = keyword_occurrences(body, primary_keyword)
    intro = body.strip()[:150]
    if disclosure_present is None:
        disclosure_present = bool(re.search(r"수수료|제휴|광고|협찬|지원받", markdown or ""))
    has_list = bool(re.search(r"^\s*[-•]\s+\S", markdown or "", re.M))
    has_faq = bool(re.search(r"FAQ|자주\s*묻는|Q\.|Q1|질문", markdown or "", re.I))

    checks: list[SEOCheck] = [
        SEOCheck("title_length", "제목 길이 15~40자", 15 <= len(title) <= 40, 8, f"{len(title)}자"),
        SEOCheck("title_keyword", "제목에 핵심 키워드 포함", bool(kw_norm) and kw_norm in title_norm, 15, primary_keyword),
        SEOCheck("title_keyword_front", "핵심 키워드가 제목 앞쪽에 위치", bool(kw_norm) and 0 <= title_norm.find(kw_norm) <= max(0, len(title_norm) // 2), 5, ""),
        SEOCheck("intro_keyword", "서두 150자 안에 핵심 키워드", bool(kw_norm) and kw_norm in _norm(intro), 10, ""),
        SEOCheck("body_length", "본문 1,500자 이상 (공백 제외)", chars >= 1500, 10, f"{chars:,}자"),
        SEOCheck("keyword_density", "핵심 키워드 본문 등장 3~15회", 3 <= occurrences <= 15, 10, f"{occurrences}회 (밀도 {density}%)"),
        SEOCheck("headings", "소제목 3개 이상", len(heads) >= 3, 8, f"{len(heads)}개"),
        SEOCheck("heading_keyword", "소제목에 핵심 키워드 포함", any(kw_norm and kw_norm in _norm(h) for h in heads), 5, ""),
        SEOCheck("images", "이미지 3장 이상", imgs >= 3, 10, f"{imgs}장"),
        SEOCheck("meta_description", "요약문 50~160자 + 키워드", 50 <= len(meta_description) <= 160 and kw_norm in _norm(meta_description), 5, f"{len(meta_description)}자"),
        SEOCheck("hashtags", "해시태그 5~20개", 5 <= len(hashtags) <= 20, 5, f"{len(hashtags)}개"),
        SEOCheck("disclosure", "제휴/광고 표시 문구", bool(disclosure_present), 5, ""),
        SEOCheck("structure", "목록 + FAQ 구조", has_list and has_faq, 4, ""),
    ]
    score = sum(c.weight for c in checks if c.passed)
    suggestions: list[str] = []
    tips = {
        "title_length": "제목을 15~40자로 조정하세요 (모바일 검색결과 잘림 방지).",
        "title_keyword": f"제목에 '{primary_keyword}' 를 그대로 넣으세요.",
        "title_keyword_front": "핵심 키워드를 제목 앞부분으로 옮기세요.",
        "intro_keyword": "첫 문단(150자) 안에 핵심 키워드를 자연스럽게 넣으세요.",
        "body_length": "본문을 1,500자 이상으로 늘리세요 (사용 상황·비교·팁 추가).",
        "keyword_density": "핵심 키워드를 본문에 3~15회 자연스럽게 배치하세요 (많으면 '이 제품'·모델명 등으로 대체).",
        "headings": "소제목(##)을 3개 이상 사용해 구조를 나누세요.",
        "heading_keyword": "소제목 하나에는 핵심 키워드를 포함하세요.",
        "images": "이미지를 3장 이상 배치하세요 (스크린샷/상품 이미지).",
        "meta_description": "요약문을 50~160자로 쓰고 핵심 키워드를 포함하세요.",
        "hashtags": "해시태그를 5~20개로 맞추세요.",
        "disclosure": "공정위 표시 문구(제휴/광고/수수료)를 본문에 넣으세요.",
        "structure": "장단점 목록과 FAQ 섹션을 추가하세요.",
    }
    for c in checks:
        if not c.passed:
            suggestions.append(tips[c.name])
    return SEOReport(
        score=score,
        checks=[asdict(c) for c in checks],
        suggestions=suggestions,
        stats={"chars": chars, "density": density, "occurrences": occurrences, "headings": len(heads), "images": imgs, "hashtags": len(hashtags)},
    )
