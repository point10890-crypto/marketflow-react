"""영상 대본 작성기 — 쇼츠(45초) / 리뷰(2~3분). LLM(JSON) 우선, 템플릿 폴백.

각 장면에 내레이션·자막·비주얼(로컬 이미지)·길이를 배정해 영상 렌더러가 바로 사용할 수 있게 한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from studio.config import Settings
from studio.content.keywords import KeywordSet, category_leaf, core_name
from studio.content.llm import LLMClient
from studio.content.prompts import SCRIPT_SYSTEM, SCRIPT_USER
from studio.models import BlogPost, Product, Scene, VideoScript
from studio.utils import clean_text, j, unique

log = logging.getLogger("studio.content.script_writer")

FORMATS = {
    "shorts": {"label": "쇼츠/클립(세로 숏폼)", "duration": 45, "scenes": 7, "max_chars": 45},
    "review": {"label": "리뷰 영상(2~3분)", "duration": 150, "scenes": 12, "max_chars": 80},
}
CHARS_PER_SECOND = 4.3  # 한국어 TTS 보통 속도


def estimate_speech_seconds(text: str) -> float:
    n = len(clean_text(text).replace(" ", ""))
    return round(max(2.0, n / CHARS_PER_SECOND + 0.6), 2)


def _visual_for_hint(images: list[str], hint: str, used: set[str]) -> str:
    hint = (hint or "").lower()
    keys = {
        "hero": ["hero"], "mobile": ["mobile"], "price": ["section", "hero"],
        "detail": ["section", "tile", "fullpage", "image"], "image": ["image", "tile"],
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


def template_script(product: Product, ks: KeywordSet, fmt: str = "shorts") -> dict[str, Any]:
    p = product
    core = ks.primary or core_name(p.name)
    leaf = category_leaf(p.category) or "제품"
    feats = [clean_text(f) for f in p.features if clean_text(f)][:3]
    while len(feats) < 3:
        feats.append(["기본기가 탄탄해서 처음 사도 실패가 적어요", "관리가 간단해서 오래 써도 부담이 없어요", "디자인이 깔끔해서 어디에 둬도 잘 어울려요"][len(feats)])
    price_line = f"{p.price:,}원" + (f", 정가 대비 {p.discount_rate:g}% 할인" if p.discount_rate else "") if p.price else "가격은 링크에서 확인"
    price_caption = (f"{p.discount_rate:g}% 할인 {p.price:,}원" if p.discount_rate else f"{p.price:,}원") if p.price else "가격은 링크 확인"
    scenes = [
        {"narration": f"{leaf} 고르다가 실패한 적 있으세요? 오늘은 {core} 솔직하게 보여드릴게요.", "caption": f"{leaf} 고민 끝", "visual_hint": "hero", "kind": "hook"},
        {"narration": f"{j(leaf, '은는')} 스펙만 보고 사면 후회하기 쉬워요. 실제로 쓸 때 뭐가 다른지가 중요하거든요.", "caption": "스펙만 보면 후회", "visual_hint": "mobile", "kind": "body"},
        {"narration": f"첫 번째, {feats[0]}.", "caption": feats[0][:12], "visual_hint": "image", "kind": "feature"},
        {"narration": f"두 번째, {feats[1]}.", "caption": feats[1][:12], "visual_hint": "image", "kind": "feature"},
        {"narration": f"세 번째, {feats[2]}.", "caption": feats[2][:12], "visual_hint": "detail", "kind": "feature"},
        {"narration": f"가격은 {price_line}이에요. 프로모션은 자주 바뀌니까 링크에서 꼭 확인하세요.", "caption": price_caption[:16], "visual_hint": "price", "kind": "offer"},
        {"narration": f"{core} 자세한 후기와 구매 링크는 프로필과 댓글에 있어요. 도움이 됐다면 저장해 두세요!", "caption": "링크는 댓글·프로필", "visual_hint": "hero", "kind": "cta"},
    ]
    if fmt == "review":
        desc = clean_text(p.description)[:120]
        extra = [
            {"narration": f"{j(core, '은는')} {p.brand or '브랜드'}에서 나온 {leaf}인데요, {desc or '기본기가 탄탄한 제품이에요'}.", "caption": f"{core} 소개"[:16], "visual_hint": "hero", "kind": "body"},
            {"narration": "먼저 구성품부터 볼게요. 박스를 열면 본체와 기본 액세서리가 들어 있고, 설명서도 한글로 잘 되어 있어요.", "caption": "구성품 확인", "visual_hint": "image", "kind": "body"},
            {"narration": "실제 사용 환경에서 일주일 정도 써 봤는데, 세팅은 5분이면 끝나고 유지 관리도 간단했어요.", "caption": "일주일 사용", "visual_hint": "detail", "kind": "body"},
            {"narration": "아쉬운 점도 있어요. 인기 옵션은 프로모션 때 금방 품절되니까 원하는 구성은 미리 확인하세요.", "caption": "아쉬운 점", "visual_hint": "mobile", "kind": "body"},
            {"narration": f"이런 분께 추천해요. {leaf} 처음 사는 분, 가성비 따지는 분, 그리고 {feats[0]} 같은 실질적인 장점을 원하는 분.", "caption": "이런 분께 추천", "visual_hint": "image", "kind": "body"},
        ]
        scenes = scenes[:2] + extra[:3] + scenes[2:5] + extra[3:] + scenes[5:]
    return {
        "title": f"{core} 솔직 리뷰 {len(feats)}가지 포인트"[:30],
        "hook": scenes[0]["narration"],
        "scenes": scenes,
        "cta": scenes[-1]["narration"],
        "description": f"{core} 후기 영상입니다. {feats[0]}, {feats[1]} 등 핵심 포인트와 가격 정보를 정리했어요. 구매 링크는 프로필/댓글을 확인해 주세요. #광고",
        "hashtags": ks.hashtags,
    }


def _validate_script_json(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list) or len(data["scenes"]) < 3:
        return None
    for s in data["scenes"]:
        if not isinstance(s, dict) or not s.get("narration"):
            return None
    if not data.get("title"):
        data["title"] = clean_text(data["scenes"][0]["narration"])[:30]
    return data


class ScriptWriter:
    def __init__(self, settings: Settings, llm: LLMClient | None = None) -> None:
        self.settings = settings
        self.llm = llm

    def _generate_json(self, product: Product, ks: KeywordSet, fmt: str, target_duration: int, blog: BlogPost | None) -> tuple[dict[str, Any] | None, str]:
        if not self.llm or not self.llm.available():
            return None, "template"
        spec = FORMATS.get(fmt, FORMATS["shorts"])
        blog_summary = clean_text(blog.meta_description) if blog and blog.meta_description else "(없음)"
        prompt = SCRIPT_USER.format(
            format_label=spec["label"],
            product_summary=product.summary_text(),
            primary=ks.primary,
            blog_summary=blog_summary,
            target_duration=target_duration,
            scene_count=spec["scenes"],
            max_chars=spec["max_chars"],
        )
        data, provider = self.llm.generate_json(prompt, system=SCRIPT_SYSTEM, max_tokens=4000, temperature=0.8)
        return _validate_script_json(data), provider

    def build(self, product: Product, ks: KeywordSet, data: dict[str, Any], *, fmt: str, target_duration: int, visuals: list[str], provider: str) -> VideoScript:
        used: set[str] = set()
        scenes: list[Scene] = []
        for i, raw in enumerate(data["scenes"]):
            narration = clean_text(raw.get("narration", ""))
            caption = clean_text(raw.get("caption", "")) or narration[:14]
            hint = str(raw.get("visual_hint", "image")).lower()
            scenes.append(Scene(
                index=i,
                narration=narration,
                caption=caption[:24],
                visual=_visual_for_hint(visuals, hint, used),
                visual_hint=hint,
                duration=estimate_speech_seconds(narration),
                kind=str(raw.get("kind", "body")).lower(),
            ))
        # 목표 길이에 맞춰 스케일 (±25% 범위, 장면 최소 2초)
        total = sum(s.duration for s in scenes) or 1.0
        factor = target_duration / total
        factor = max(0.75, min(1.25, factor))
        for s in scenes:
            s.duration = round(max(2.0, s.duration * factor), 2)
        tags = unique([t if str(t).startswith("#") else f"#{t}" for t in (data.get("hashtags") or ks.hashtags) if t])[:15]
        return VideoScript(
            product_id=product.id,
            format=fmt,
            title=clean_text(data.get("title", ""))[:40],
            hook=clean_text(data.get("hook", "")) or (scenes[0].narration if scenes else ""),
            scenes=[s.to_dict() for s in scenes],
            cta=clean_text(data.get("cta", "")) or (scenes[-1].narration if scenes else ""),
            description=clean_text(data.get("description", "")),
            hashtags=tags,
            duration=round(sum(s.duration for s in scenes), 2),
            provider=provider,
        )

    def write(
        self,
        product: Product,
        ks: KeywordSet,
        *,
        fmt: str = "shorts",
        target_duration: int | None = None,
        blog: BlogPost | None = None,
        visuals: list[str] | None = None,
    ) -> VideoScript:
        fmt = fmt if fmt in FORMATS else "shorts"
        target_duration = target_duration or FORMATS[fmt]["duration"]
        visuals = visuals if visuals is not None else product.media
        data, provider = self._generate_json(product, ks, fmt, target_duration, blog)
        if data is None:
            data = template_script(product, ks, fmt)
            provider = "template"
        return self.build(product, ks, data, fmt=fmt, target_duration=target_duration, visuals=visuals, provider=provider)
