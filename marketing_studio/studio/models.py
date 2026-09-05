"""데이터 모델 — 상품/캠페인/블로그/대본/영상/작업/수익.

모든 모델은 `to_dict()` (플랫 JSON) 과 `from_dict()` 를 제공한다.
프론트엔드(static/app.js) 는 이 딕셔너리 구조를 그대로 사용한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from studio.utils import now_iso, short_id


def _filter_kwargs(cls, data: dict[str, Any]) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in (data or {}).items() if k in names}


class _Base:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        return cls(**_filter_kwargs(cls, data))  # type: ignore[misc]


@dataclass
class Campaign(_Base):
    """브랜드커넥트 캠페인 목록 항목."""

    id: str = field(default_factory=lambda: short_id("c"))
    title: str = ""
    url: str = ""
    brand: str = ""
    campaign_type: str = ""  # 체험단 / 커미션 / 원고료 / 공동구매 …
    reward: str = ""
    period: str = ""
    thumbnail: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "brandconnect"
    product_id: str = ""  # 상품으로 가져온 경우
    raw: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=now_iso)


@dataclass
class Product(_Base):
    """수집된 상품 (콘텐츠 생성의 기준 단위)."""

    id: str = field(default_factory=lambda: short_id("p"))
    name: str = ""
    source: str = "url"  # brandconnect | smartstore | url | manual
    source_url: str = ""
    product_url: str = ""
    affiliate_url: str = ""
    brand: str = ""
    category: str = ""
    price: int | None = None
    original_price: int | None = None
    discount_rate: float | None = None
    commission_rate: float | None = None
    commission_note: str = ""
    description: str = ""
    features: list[str] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)  # 로컬 파일 (다운로드한 상품 이미지)
    screenshots: list[str] = field(default_factory=list)  # 로컬 파일 (스크린샷)
    image_urls: list[str] = field(default_factory=list)  # 원본 이미지 URL
    campaign: dict[str, Any] = field(default_factory=dict)
    keywords: dict[str, Any] = field(default_factory=dict)
    status: str = "new"  # new | content_ready | video_ready | packaged | published
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @property
    def media(self) -> list[str]:
        """스크린샷 + 상품 이미지 (콘텐츠에 쓰는 순서)."""
        out: list[str] = []
        for p in self.screenshots + self.images:
            if p and p not in out:
                out.append(p)
        return out

    @property
    def best_link(self) -> str:
        return self.affiliate_url or self.product_url or self.source_url

    def summary_text(self, max_features: int = 6) -> str:
        parts = [f"상품명: {self.name}"]
        if self.brand:
            parts.append(f"브랜드: {self.brand}")
        if self.category:
            parts.append(f"카테고리: {self.category}")
        if self.price:
            price = f"{self.price:,}원"
            if self.original_price and self.original_price > self.price:
                price += f" (정가 {self.original_price:,}원)"
            parts.append(f"가격: {price}")
        if self.commission_rate:
            parts.append(f"제휴 수수료: {self.commission_rate:g}%")
        if self.description:
            parts.append(f"설명: {self.description[:600]}")
        if self.features:
            parts.append("특징: " + " / ".join(self.features[:max_features]))
        if self.specs:
            spec = ", ".join(f"{k}: {v}" for k, v in list(self.specs.items())[:8])
            parts.append(f"스펙: {spec}")
        if self.campaign:
            c = self.campaign
            bits = [f"{k}: {v}" for k, v in c.items() if v and k in ("campaign_type", "reward", "period", "mission")]
            if bits:
                parts.append("캠페인: " + " / ".join(bits))
        return "\n".join(parts)


@dataclass
class BlogPost(_Base):
    id: str = field(default_factory=lambda: short_id("b"))
    product_id: str = ""
    kind: str = "blog"
    title: str = ""
    slug: str = ""
    meta_description: str = ""
    primary_keyword: str = ""
    keywords: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    markdown: str = ""
    html: str = ""
    plain_text: str = ""
    images: list[str] = field(default_factory=list)
    seo_score: int = 0
    seo_report: dict[str, Any] = field(default_factory=dict)
    char_count: int = 0
    provider: str = "template"
    status: str = "draft"  # draft | ready | published
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class Scene(_Base):
    index: int = 0
    narration: str = ""
    caption: str = ""
    visual: str = ""  # 로컬 이미지 경로
    visual_hint: str = ""  # hero | detail | price | mobile | image | any
    duration: float = 5.0
    kind: str = "body"  # hook | body | feature | offer | cta


@dataclass
class VideoScript(_Base):
    id: str = field(default_factory=lambda: short_id("s"))
    product_id: str = ""
    kind: str = "script"
    format: str = "shorts"  # shorts | review
    title: str = ""
    hook: str = ""
    scenes: list[dict[str, Any]] = field(default_factory=list)
    cta: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    duration: float = 0.0
    provider: str = "template"
    status: str = "draft"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def scene_objects(self) -> list[Scene]:
        return [Scene.from_dict(s) if isinstance(s, dict) else s for s in self.scenes]


@dataclass
class VideoAsset(_Base):
    id: str = field(default_factory=lambda: short_id("v"))
    product_id: str = ""
    script_id: str = ""
    title: str = ""
    path: str = ""
    thumbnail: str = ""
    srt: str = ""
    duration: float = 0.0
    width: int = 1080
    height: int = 1920
    tts_engine: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "ready"
    created_at: str = field(default_factory=now_iso)


@dataclass
class Job(_Base):
    id: str = field(default_factory=lambda: short_id("j"))
    type: str = ""
    status: str = "queued"  # queued | running | done | failed | cancelled
    progress: int = 0
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class EarningsEntry(_Base):
    id: str = field(default_factory=lambda: short_id("e"))
    date: str = ""
    product_id: str = ""
    content_id: str = ""
    channel: str = ""  # naver_blog | naver_clip | youtube | instagram | other
    clicks: int = 0
    orders: int = 0
    revenue: int = 0
    commission: int = 0
    note: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass
class AffiliateLink(_Base):
    id: str = field(default_factory=lambda: short_id("l"))
    product_id: str = ""
    network: str = "brandconnect"  # brandconnect | coupang | other
    url: str = ""
    label: str = ""
    channel: str = ""
    created_at: str = field(default_factory=now_iso)
