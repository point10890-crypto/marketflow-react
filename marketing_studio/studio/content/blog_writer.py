"""SEO 블로그 작성기 — LLM(JSON) 우선, 실패 시 템플릿 폴백. 결과는 항상 SEO 점검을 거친다."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from studio.config import Settings
from studio.content.keywords import KeywordSet, category_leaf, core_name
from studio.content.llm import LLMClient
from studio.content.markdown import markdown_to_html, markdown_to_plain
from studio.content.prompts import BLOG_REVISE, BLOG_SYSTEM, BLOG_USER
from studio.content.seo import analyze_post
from studio.models import BlogPost, Product
from studio.utils import clean_text, j, korean_char_count, slugify, unique

log = logging.getLogger("studio.content.blog_writer")

IMAGE_HINT_ORDER = ["hero", "image", "detail", "mobile", "price", "image", "hero"]


# ----------------------------------------------------------------------------- 이미지 매칭
def pick_image(images: list[str], hint: str, used: set[str]) -> str:
    """힌트(hero/detail/price/mobile/image)에 맞는 파일을 고르되, 가능하면 미사용 이미지를 우선."""
    hint = (hint or "").lower()
    keys = {
        "hero": ["hero"],
        "detail": ["section", "fullpage", "tile", "image"],
        "price": ["section", "hero", "image"],
        "mobile": ["mobile"],
        "image": ["image", "tile"],
    }.get(hint, ["image", "hero"])
    for key in keys:
        for path in images:
            if key in Path(path).name.lower() and path not in used:
                used.add(path)
                return path
    for path in images:
        if path not in used:
            used.add(path)
            return path
    return images[0] if images else ""


# ----------------------------------------------------------------------------- 템플릿 폴백
def _price_sentence(p: Product) -> str:
    if not p.price:
        return "가격은 판매처 상황에 따라 달라질 수 있으니 아래 링크에서 현재 가격을 확인하는 것이 가장 정확합니다."
    s = f"현재 판매가는 {p.price:,}원"
    if p.original_price and p.original_price > p.price:
        rate = p.discount_rate or round((1 - p.price / p.original_price) * 100, 1)
        s += f"으로, 정가 {p.original_price:,}원 대비 약 {rate:g}% 할인된 가격"
    s += "입니다. 프로모션은 수시로 바뀌므로 구매 전 링크에서 최신 가격과 쿠폰을 한 번 더 확인해 주세요."
    return s


def short_alias(core: str, brand: str) -> str:
    """본문 반복용 짧은 이름: 브랜드 제거 → 마지막 두 토큰. 예) '클린테크 무선 청소기 X1' → '무선 청소기 X1'."""
    name = core
    if brand and name.lower().startswith(brand.lower()):
        name = name[len(brand):].strip()
    tokens = name.split()
    if len(tokens) > 3:
        name = " ".join(tokens[-3:])
    return name or core


def _feature_lines(p: Product, core: str) -> list[str]:
    feats = [clean_text(f) for f in p.features if clean_text(f)]
    if not feats:
        base = [
            f"{core}의 기본 성능이 카테고리 평균 이상으로 안정적입니다",
            "실제 사용 환경에서 세팅이 간단하고 유지 관리 부담이 적습니다",
            "디자인과 마감이 깔끔해 어디에 두어도 잘 어울립니다",
        ]
        feats = base
    return feats[:5]


def template_blog(product: Product, ks: KeywordSet, tone: str = "친근하고 솔직한") -> dict[str, Any]:
    p = product
    core = ks.primary or core_name(p.name)
    alias = short_alias(core, p.brand)
    leaf = category_leaf(p.category) or "제품"
    brand = p.brand or "제조사"
    feats = _feature_lines(p, core)
    desc = clean_text(p.description)[:300]
    spec_line = ", ".join(f"{k} {v}" for k, v in list(p.specs.items())[:5])
    n_feats = min(len(feats), 3)

    sections = [
        {
            "heading": f"{core} 한눈에 보기",
            "body": (
                f"{j(core, '은는')} {brand}에서 선보인 {leaf}입니다. "
                + (f"{desc} " if desc else "")
                + f"이 글에서는 {alias}의 핵심 특징, 실제 사용 상황에서 느낀 장점과 아쉬운 점, 그리고 가격·할인 정보까지 한 번에 정리합니다. "
                f"{j(leaf, '을를')} 살 때 아래 항목만 확인해도 결정에 필요한 정보는 대부분 얻을 수 있습니다.\n\n"
                + "\n".join(f"- {line}" for line in [
                    f"브랜드: {brand}",
                    f"카테고리: {p.category or leaf}",
                    f"가격: {p.price:,}원" if p.price else "가격: 판매처 확인",
                    f"주요 스펙: {spec_line}" if spec_line else f"핵심 포인트: {feats[0]}",
                ])
            ),
            "image_hint": "hero",
        },
        {
            "heading": f"{alias} 핵심 특징 {n_feats}가지",
            "body": "\n\n".join(
                f"**{i}. {feat}**\n{feat}. 이 부분은 실제로 써 보면 체감 차이가 큰 포인트입니다. "
                f"비슷한 가격대의 {j(leaf, '과와')} 나란히 놓고 비교해 보면 {j(alias, '이가')} 어디에서 강한지 바로 드러납니다."
                for i, feat in enumerate(feats[:3], 1)
            ),
            "image_hint": "image",
        },
        {
            "heading": f"{alias} 이런 분께 추천",
            "body": (
                f"{j(alias, '은는')} 특히 다음과 같은 분들에게 잘 맞습니다.\n\n"
                f"- {j(leaf, '을를')} 처음 구매해서 실패 없는 선택을 하고 싶은 분\n"
                f"- 가격 대비 성능을 꼼꼼히 따지는 실속파\n"
                f"- {feats[0]} 같은 실질적인 이점을 중요하게 생각하는 분\n"
                f"- 선물용으로 무난하면서도 만족도 높은 {j(leaf, '을를')} 찾는 분\n\n"
                f"반대로 이미 상위 라인업 {j(leaf, '을를')} 쓰고 있다면 체감 변화가 크지 않을 수 있으니, 지금 쓰는 제품에서 아쉬운 점이 "
                f"이 제품의 특징과 맞닿아 있는지 먼저 살펴보시길 권합니다."
            ),
            "image_hint": "mobile",
        },
        {
            "heading": f"{core} 가격 및 할인 정보",
            "body": (
                _price_sentence(p)
                + f" {brand} 공식 판매처에서 구매하면 정품 보증과 A/S 를 함께 받을 수 있고, 시즌 프로모션 기간에는 추가 혜택이 붙는 경우가 많습니다. "
                f"가격 비교를 할 때는 배송비와 사은품 구성까지 포함해서 보는 것이 실제 체감가를 정확히 계산하는 방법입니다."
            ),
            "image_hint": "price",
        },
    ]
    pros = feats[:3] + [f"{brand} 정품 보증 및 A/S 지원"]
    cons = [
        "인기 옵션은 프로모션 기간에 품절이 잦아 원하는 구성을 미리 확인해야 합니다",
        f"상위 라인업 {j(leaf, '과와')} 비교하면 세부 기능에서 차이가 있을 수 있습니다",
    ]
    faq = [
        {"q": f"{core} 가격은 얼마인가요?", "a": (f"현재 판매가 기준 {p.price:,}원이며" if p.price else "판매처에 따라 가격이 다르며") + " 프로모션에 따라 달라질 수 있어 구매 링크에서 최신 가격을 확인하는 것이 정확합니다."},
        {"q": f"{alias} 장단점을 한 줄로 요약하면?", "a": f"장점은 {feats[0]}, 아쉬운 점은 {cons[0]}입니다."},
        {"q": f"{alias} 어디서 사는 게 좋나요?", "a": f"{brand} 공식 판매처(스마트스토어 등)에서 구매하면 정품 보증과 혜택을 함께 받을 수 있습니다."},
    ]
    return {
        "title": f"{core} 후기 장단점과 가격 총정리"[:40],
        "meta_description": f"{core} 후기: 핵심 특징 {n_feats}가지, 장단점, 가격/할인 정보와 추천 대상까지 한 번에 정리했습니다. {leaf} 구매 전 꼭 확인하세요.",
        "intro": (
            f"{core} 구매를 고민하고 계신가요? 이 글은 {alias}의 특징과 장단점, 가격까지 실제 구매 결정에 필요한 정보만 압축해서 정리한 후기입니다. "
            f"{j(leaf, '을를')} 고를 때 가장 많이 하는 실수는 스펙표만 보고 결정하는 것인데, 아래에서 실제 사용 상황 기준으로 하나씩 짚어 보겠습니다."
        ),
        "sections": sections,
        "pros": pros,
        "cons": cons,
        "faq": faq,
        "conclusion": (
            f"정리하면 {j(core, '은는')} {feats[0]}이라는 확실한 강점을 가진 {leaf}입니다. 위에서 정리한 장단점과 추천 대상을 참고해 본인의 사용 환경과 맞는지 판단해 보세요. "
            f"현재 가격과 프로모션은 아래 링크에서 바로 확인할 수 있습니다."
        ),
        "hashtags": ks.hashtags,
    }


# ----------------------------------------------------------------------------- 조립
def _validate_blog_json(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    if not data.get("title") or not isinstance(data.get("sections"), list) or len(data["sections"]) < 2:
        return None
    for s in data["sections"]:
        if not isinstance(s, dict) or not s.get("heading") or not s.get("body"):
            return None
    return data


def assemble_markdown(
    data: dict[str, Any],
    product: Product,
    ks: KeywordSet,
    *,
    images: list[str],
    affiliate_url: str,
    disclosure: str,
    creator_name: str = "",
) -> tuple[str, list[str]]:
    used: set[str] = set()
    used_images: list[str] = []
    lines: list[str] = [f"# {data['title']}", ""]
    if data.get("intro"):
        lines += [clean_text(data["intro"]), ""]
    if images:
        first = pick_image(images, "hero", used)
        lines += [f"![{product.name}]({first})", ""]
        used_images.append(first)
    for section in data["sections"]:
        lines += [f"## {section['heading']}", "", str(section["body"]).strip(), ""]
        if images:
            img = pick_image(images, section.get("image_hint", "image"), used)
            if img and img not in used_images:
                lines += [f"![{section['heading']}]({img})", ""]
                used_images.append(img)
    pros = [p for p in data.get("pros") or [] if p]
    cons = [c for c in data.get("cons") or [] if c]
    if pros or cons:
        lines += [f"## {ks.primary} 장점과 아쉬운 점", ""]
        if pros:
            lines += ["**장점**"] + [f"- {p}" for p in pros] + [""]
        if cons:
            lines += ["**아쉬운 점**"] + [f"- {c}" for c in cons] + [""]
    faq = [f for f in data.get("faq") or [] if isinstance(f, dict) and f.get("q") and f.get("a")]
    if faq:
        lines += ["## 자주 묻는 질문 (FAQ)", ""]
        for item in faq:
            lines += [f"**Q. {item['q']}**", f"{item['a']}", ""]
    if data.get("conclusion"):
        lines += ["## 마무리", "", clean_text(data["conclusion"]), ""]
    if affiliate_url:
        lines += [f"👉 [{ks.primary} 최저가·프로모션 확인하기]({affiliate_url})", ""]
    if images and len(used_images) < min(3, len(images)):
        for path in images:
            if path not in used_images and len(used_images) < 3:
                lines += [f"![{product.name} 이미지]({path})", ""]
                used_images.append(path)
    if disclosure:
        lines += ["---", "", f"> {disclosure}", ""]
    if creator_name:
        lines += [f"작성: {creator_name}", ""]
    tags = unique([t if str(t).startswith("#") else f"#{t}" for t in (data.get("hashtags") or ks.hashtags) if t])
    if tags:
        lines += [" ".join(tags[:20]), ""]
    return "\n".join(lines).strip() + "\n", used_images


class BlogWriter:
    def __init__(self, settings: Settings, llm: LLMClient | None = None) -> None:
        self.settings = settings
        self.llm = llm

    def _generate_json(self, product: Product, ks: KeywordSet, tone: str, target_length: int) -> tuple[dict[str, Any] | None, str]:
        if not self.llm or not self.llm.available():
            return None, "template"
        prompt = BLOG_USER.format(
            product_summary=product.summary_text(),
            primary=ks.primary,
            secondary=", ".join(ks.secondary[:5]),
            longtail=", ".join(ks.longtail[:4]),
            tone=tone,
            target_length=target_length,
        )
        data, provider = self.llm.generate_json(prompt, system=BLOG_SYSTEM, max_tokens=6000, temperature=0.75)
        return _validate_blog_json(data), provider

    def _revise_json(self, data: dict[str, Any], ks: KeywordSet, suggestions: list[str]) -> dict[str, Any] | None:
        if not self.llm or not suggestions:
            return None
        prompt = BLOG_REVISE.format(
            suggestions="\n".join(f"- {s}" for s in suggestions),
            primary=ks.primary,
            current=json.dumps(data, ensure_ascii=False),
        )
        revised, _ = self.llm.generate_json(prompt, system=BLOG_SYSTEM, max_tokens=6000, temperature=0.5)
        return _validate_blog_json(revised)

    def build(self, product: Product, ks: KeywordSet, data: dict[str, Any], *, images: list[str], affiliate_url: str, provider: str) -> BlogPost:
        markdown, used_images = assemble_markdown(
            data, product, ks, images=images, affiliate_url=affiliate_url,
            disclosure=self.settings.disclosure, creator_name=self.settings.creator_name,
        )
        title = clean_text(data["title"])[:60]
        meta = clean_text(data.get("meta_description", ""))[:160]
        tags = unique([t if str(t).startswith("#") else f"#{t}" for t in (data.get("hashtags") or ks.hashtags) if t])[:20]
        report = analyze_post(
            title=title, markdown=markdown, primary_keyword=ks.primary, meta_description=meta,
            hashtags=tags, image_count=len(used_images), disclosure_present=bool(self.settings.disclosure),
        )
        return BlogPost(
            product_id=product.id,
            title=title,
            slug=slugify(title),
            meta_description=meta,
            primary_keyword=ks.primary,
            keywords=ks.all_keywords(),
            hashtags=tags,
            markdown=markdown,
            html=markdown_to_html(markdown),
            plain_text=markdown_to_plain(markdown),
            images=used_images,
            seo_score=report.score,
            seo_report=report.to_dict(),
            char_count=korean_char_count(re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)),
            provider=provider,
        )

    def write(
        self,
        product: Product,
        ks: KeywordSet,
        *,
        tone: str | None = None,
        target_length: int | None = None,
        affiliate_url: str | None = None,
        images: list[str] | None = None,
        revise: bool = True,
        min_score: int = 75,
    ) -> BlogPost:
        tone = tone or self.settings.blog_tone
        target_length = target_length or self.settings.blog_length
        images = images if images is not None else product.media
        link = affiliate_url if affiliate_url is not None else product.best_link
        data, provider = self._generate_json(product, ks, tone, target_length)
        if data is None:
            data = template_blog(product, ks, tone)
            provider = "template"
        post = self.build(product, ks, data, images=images, affiliate_url=link, provider=provider)
        if revise and provider != "template" and post.seo_score < min_score:
            revised = self._revise_json(data, ks, post.seo_report.get("suggestions", []))
            if revised:
                candidate = self.build(product, ks, revised, images=images, affiliate_url=link, provider=provider)
                if candidate.seo_score >= post.seo_score:
                    post = candidate
        return post

    def rescore(self, post: BlogPost) -> BlogPost:
        """사용자가 마크다운을 수정한 뒤 재채점."""
        report = analyze_post(
            title=post.title, markdown=post.markdown, primary_keyword=post.primary_keyword,
            meta_description=post.meta_description, hashtags=post.hashtags,
            disclosure_present=None,
        )
        post.seo_score = report.score
        post.seo_report = report.to_dict()
        post.html = markdown_to_html(post.markdown)
        post.plain_text = markdown_to_plain(post.markdown)
        post.char_count = korean_char_count(re.sub(r"!\[[^\]]*\]\([^)]*\)", "", post.markdown))
        post.images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", post.markdown)
        return post
