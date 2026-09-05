"""수익화 — 제휴 링크(UTM), 링크인바이오 문구, 정산 CSV 파싱, 수익 요약/예측."""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from studio.models import EarningsEntry, Product
from studio.utils import clean_text, slugify

CHANNELS: dict[str, str] = {
    "naver_blog": "네이버 블로그",
    "naver_clip": "네이버 클립",
    "youtube": "유튜브 쇼츠",
    "instagram": "인스타그램 릴스",
    "other": "기타",
}

_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("날짜", "일자", "date", "정산일", "주문일", "기준일", "day"),
    "channel": ("채널", "channel", "매체", "플랫폼", "platform"),
    "product": ("상품", "product", "캠페인", "campaign", "품명", "상품명"),
    "clicks": ("클릭", "click", "유입", "방문"),
    "orders": ("주문", "order", "구매", "건수", "판매수"),
    "revenue": ("매출", "판매금액", "revenue", "sales", "거래액", "결제금액", "주문금액"),
    "commission": ("수수료", "정산", "commission", "수익", "리워드", "적립", "정산금액", "예상수익"),
    "note": ("비고", "메모", "note", "memo"),
}


def with_utm(url: str, *, source: str, medium: str = "affiliate", campaign: str = "", content: str = "") -> str:
    """기존 쿼리 보존 + UTM 추가 (이미 있으면 덮어씀). 네이버 커넥트링크 등 단축링크는 그대로 두는 편이 안전하므로 호출부에서 선택."""
    if not url:
        return ""
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["utm_source"] = source
    query["utm_medium"] = medium
    if campaign:
        query["utm_campaign"] = slugify(campaign, max_len=40)
    if content:
        query["utm_content"] = slugify(content, max_len=40)
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


def link_in_bio(product: Product, url: str, disclosure_short: str = "#광고 · 제휴 링크로 구매 시 수수료를 받을 수 있어요") -> str:
    lines = [f"🛒 {product.name}"]
    if product.price:
        lines.append(f"가격: {product.price:,}원" + (f" (정가 {product.original_price:,}원)" if product.original_price and product.original_price > product.price else ""))
    lines.append(f"👉 {url}")
    lines.append(disclosure_short)
    return "\n".join(lines)


def channel_links(product: Product, base_url: str) -> dict[str, str]:
    """채널별 UTM 링크 (단축링크/브랜드커넥트 링크는 UTM 을 붙이지 않고 원본 유지)."""
    if not base_url:
        return {}
    host = urlparse(base_url).netloc.lower()
    if "brandconnect" in host or "naver.me" in host or "link." in host or "coupa.ng" in host:
        return {ch: base_url for ch in CHANNELS}
    return {ch: with_utm(base_url, source=ch, campaign=product.name) for ch in CHANNELS}


# ----------------------------------------------------------------------------- 정산 파일
def _to_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d\-]", "", str(value))
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _norm_date(value: str) -> str:
    s = clean_text(value)
    m = re.search(r"(20\d{2})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(20\d{2})[.\-/년\s]*(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-01"
    return s[:10] or date.today().isoformat()


def _map_headers(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for h in headers:
        key = clean_text(h).lower()
        for field, aliases in _HEADER_ALIASES.items():
            if field in mapping:
                continue
            if any(a.lower() in key for a in aliases):
                mapping[field] = h
                break
    return mapping


def _guess_channel(text: str) -> str:
    t = (text or "").lower()
    if "클립" in t or "clip" in t:
        return "naver_clip"
    if "블로그" in t or "blog" in t:
        return "naver_blog"
    if "유튜브" in t or "youtube" in t or "쇼츠" in t:
        return "youtube"
    if "인스타" in t or "insta" in t or "릴스" in t:
        return "instagram"
    return "other"


def parse_settlement_csv(text: str, product_lookup: dict[str, str] | None = None) -> list[EarningsEntry]:
    """브랜드커넥트/쿠팡 등 정산 CSV(헤더 자유형) → EarningsEntry 목록. product_lookup: {상품명 소문자: product_id}."""
    text = (text or "").lstrip("﻿")
    if not text.strip():
        return []
    sample = text[:2000]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return []
    mapping = _map_headers(list(reader.fieldnames))
    entries: list[EarningsEntry] = []
    lookup = {k.lower(): v for k, v in (product_lookup or {}).items()}
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        get = lambda f: row.get(mapping[f], "") if f in mapping else ""  # noqa: E731
        product_name = clean_text(get("product"))
        product_id = ""
        if product_name:
            for name, pid in lookup.items():
                if name and (name in product_name.lower() or product_name.lower() in name):
                    product_id = pid
                    break
        entries.append(EarningsEntry(
            date=_norm_date(get("date")),
            product_id=product_id,
            channel=_guess_channel(get("channel") or get("note")),
            clicks=_to_int(get("clicks")),
            orders=_to_int(get("orders")),
            revenue=_to_int(get("revenue")),
            commission=_to_int(get("commission")),
            note=clean_text(get("note") or product_name)[:200],
        ))
    return entries


# ----------------------------------------------------------------------------- 요약
def earnings_summary(entries: list[EarningsEntry], product_names: dict[str, str] | None = None) -> dict[str, Any]:
    names = product_names or {}
    totals = {"clicks": 0, "orders": 0, "revenue": 0, "commission": 0, "entries": len(entries)}
    by_channel: dict[str, dict[str, int]] = defaultdict(lambda: {"clicks": 0, "orders": 0, "revenue": 0, "commission": 0})
    by_product: dict[str, dict[str, Any]] = defaultdict(lambda: {"clicks": 0, "orders": 0, "revenue": 0, "commission": 0, "name": ""})
    by_month: dict[str, dict[str, int]] = defaultdict(lambda: {"clicks": 0, "orders": 0, "revenue": 0, "commission": 0})
    cutoff_30 = (date.today() - timedelta(days=30)).isoformat()
    last_30 = {"clicks": 0, "orders": 0, "revenue": 0, "commission": 0}
    for e in entries:
        for k in ("clicks", "orders", "revenue", "commission"):
            v = int(getattr(e, k) or 0)
            totals[k] += v
            by_channel[e.channel or "other"][k] += v
            by_product[e.product_id or "unassigned"][k] += v
            by_month[(e.date or "")[:7] or "unknown"][k] += v
            if (e.date or "") >= cutoff_30:
                last_30[k] += v
        by_product[e.product_id or "unassigned"]["name"] = names.get(e.product_id, "미지정" if not e.product_id else e.product_id)
    clicks = totals["clicks"]
    orders = totals["orders"]
    top_products = sorted(
        ({"product_id": pid, **vals} for pid, vals in by_product.items()),
        key=lambda x: -x["commission"],
    )[:10]
    return {
        "totals": totals,
        "conversion_rate": round(orders / clicks * 100, 2) if clicks else 0.0,
        "epc": round(totals["commission"] / clicks, 1) if clicks else 0.0,
        "avg_commission_per_order": round(totals["commission"] / orders) if orders else 0,
        "by_channel": [{"channel": ch, "label": CHANNELS.get(ch, ch), **vals} for ch, vals in sorted(by_channel.items(), key=lambda kv: -kv[1]["commission"])],
        "by_product": top_products,
        "by_month": [{"month": m, **vals} for m, vals in sorted(by_month.items())],
        "last_30_days": last_30,
    }


def revenue_calculator(price: int | None, commission_rate: float | None, *, monthly_visits: int = 3000, ctr: float = 0.06, cvr: float = 0.025) -> dict[str, Any]:
    """월 예상 수익 = 방문 × 링크 클릭률 × 구매전환율 × 판매가 × 수수료율."""
    price = int(price or 0)
    rate = float(commission_rate or 0) / 100.0
    clicks = monthly_visits * ctr
    orders = clicks * cvr
    revenue = orders * price
    commission = revenue * rate
    return {
        "monthly_visits": monthly_visits,
        "ctr": ctr,
        "cvr": cvr,
        "expected_clicks": round(clicks, 1),
        "expected_orders": round(orders, 2),
        "expected_revenue": round(revenue),
        "expected_commission": round(commission),
        "commission_per_order": round(price * rate),
    }
