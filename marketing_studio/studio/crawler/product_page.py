"""범용 상품 페이지 추출기 — 스마트스토어/브랜드스토어/쿠팡/일반 쇼핑몰.

우선순위: JSON-LD(Product) → 스마트스토어 __PRELOADED_STATE__ → OpenGraph → 본문 텍스트 정규식.
브라우저 없이 HTML 문자열만으로 동작한다 (테스트 가능).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from studio.utils import clean_text, parse_price, unique

log = logging.getLogger("studio.crawler.product_page")

_PRELOADED_RE = re.compile(r"__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*(?:;\s*)?(?:</script>|\n\s*window\.)", re.S)
_PRICE_LABEL_RE = re.compile(r"(판매가|할인가|최종가|가격|정가|소비자가|정상가)\s*[:：]?\s*((?:\d{1,3}(?:,\d{3})+|\d{4,})\s*원)")
_ANY_PRICE_RE = re.compile(r"((?:\d{1,3}(?:,\d{3})+|\d{4,})\s*원)")
_BAD_IMG = ("icon", "logo", "sprite", "btn_", "button", "blank", "loading", "emoticon", "badge", "profile", "avatar",
            ".svg", ".gif", "1x1", "pixel", "spacer", "banner_", "ad_", "/ad/", "common/", "static/img/ui")
_GOOD_IMG = ("shop-phinf", "shop1.phinf", "pstatic.net", "product", "goods", "item", "detail", "thumb", "coupangcdn", "image")
_NAV_WORDS = ("로그인", "회원가입", "고객센터", "이용약관", "개인정보", "공지사항", "마이페이지", "장바구니", "메뉴", "검색", "찜하기", "톡톡")
_INFO_LINE_RE = re.compile(r"수수료|원고료|판매가|정가|할인가|소비자가|정상가|최종가|모집\s*기간|신청\s*기간|캠페인\s*기간|리워드|미션|\d{1,3}(?:,\d{3})+\s*원")


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception:
        return BeautifulSoup(html or "", "html.parser")


def classify_source(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if "brandconnect.naver" in host:
        return "brandconnect"
    if "smartstore.naver" in host or "brand.naver" in host or "shopping.naver" in host or "naver.me" in host:
        return "smartstore"
    if "coupang" in host:
        return "coupang"
    return "url"


def clean_product_name(name: str) -> str:
    name = clean_text(name)
    name = re.sub(r"\s*[:|\-–]\s*(네이버\s*(쇼핑|스마트스토어|브랜드스토어)|스마트스토어|브랜드스토어|쿠팡!?|Coupang).*$", "", name, flags=re.I)
    name = re.sub(r"\s+:\s+[^:]{1,40}$", "", name)  # '상품명 : 스토어명' (스마트스토어 제목 관례)
    name = re.sub(r"\s*\|\s*.*$", "", name) if name.count("|") == 1 and len(name) > 30 else name
    return name.strip()[:150]


def _meta(soup: BeautifulSoup, key: str) -> str:
    node = soup.select_one(f"meta[property='{key}']") or soup.select_one(f"meta[name='{key}']")
    return clean_text(node.get("content")) if node else ""


# ----------------------------------------------------------------------------- JSON-LD
def _iter_jsonld_objects(node: Any):
    if isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "mainEntity", "item"):
            if key in node:
                yield from _iter_jsonld_objects(node[key])
    elif isinstance(node, list):
        for item in node:
            yield from _iter_jsonld_objects(item)


def parse_jsonld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for obj in _iter_jsonld_objects(data):
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == "product" for t in types if t):
                out.append(obj)
    return out


def _jsonld_to_fields(obj: dict[str, Any]) -> dict[str, Any]:
    brand = obj.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name", "")
    images = obj.get("image") or []
    if isinstance(images, (str, dict)):
        images = [images]
    image_urls = []
    for img in images:
        if isinstance(img, dict):
            img = img.get("url") or img.get("contentUrl")
        if img:
            image_urls.append(str(img))
    offers = obj.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = parse_price(str(offers.get("price", ""))) if isinstance(offers, dict) else None
    if price is None and isinstance(offers, dict) and offers.get("lowPrice"):
        price = parse_price(str(offers.get("lowPrice")))
    return {
        "name": clean_text(obj.get("name", "")),
        "brand": clean_text(brand or ""),
        "description": clean_text(obj.get("description", ""))[:2000],
        "image_urls": image_urls,
        "price": price,
        "category": clean_text(obj.get("category", "")) if isinstance(obj.get("category"), str) else "",
        "sku": clean_text(str(obj.get("sku", ""))),
    }


# ----------------------------------------------------------------------------- 스마트스토어 PRELOADED_STATE
def find_preloaded_state(html: str) -> dict[str, Any] | None:
    if "__PRELOADED_STATE__" not in (html or ""):
        return None
    idx = html.find("__PRELOADED_STATE__")
    start = html.find("{", idx)
    if start < 0:
        return None
    # 중괄호 균형으로 JSON 끝 찾기 (문자열 내부 중괄호 고려)
    depth = 0
    in_str = False
    escape = False
    for i in range(start, min(len(html), start + 5_000_000)):
        ch = html[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : i + 1])
                except ValueError:
                    return None
    return None


def _walk(node: Any, depth: int = 0):
    if depth > 12:
        return
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v, depth + 1)
    elif isinstance(node, list):
        for v in node[:200]:
            yield from _walk(v, depth + 1)


def _deep_get(node: Any, key: str) -> Any:
    for d in _walk(node):
        if key in d and d[key] not in (None, "", [], {}):
            return d[key]
    return None


def preloaded_state_to_fields(state: dict[str, Any]) -> dict[str, Any]:
    product_node: dict[str, Any] | None = None
    for d in _walk(state):
        if "name" in d and ("salePrice" in d or "productImages" in d or "productNo" in d):
            product_node = d
            break
    if product_node is None:
        return {}
    name = clean_text(str(product_node.get("name", "")))
    sale_price = parse_price(str(product_node.get("salePrice", "")))
    discounted = None
    for key in ("discountedSalePrice", "mobileDiscountedSalePrice", "discountedPrice"):
        val = _deep_get(product_node, key)
        if val is not None:
            discounted = parse_price(str(val))
            break
    price = discounted or sale_price
    original = sale_price if (discounted and sale_price and sale_price > discounted) else None
    images: list[str] = []
    for img in product_node.get("productImages") or []:
        if isinstance(img, dict) and img.get("url"):
            images.append(str(img["url"]))
    rep = product_node.get("representativeImage") or product_node.get("representImage")
    if isinstance(rep, dict) and rep.get("url"):
        images.insert(0, str(rep["url"]))
    brand = ""
    for key in ("brandName", "channelName", "manufacturerName"):
        val = _deep_get(product_node, key) or _deep_get(state, key)
        if val:
            brand = clean_text(str(val))
            break
    category = ""
    for key in ("wholeCategoryName", "categoryName"):
        val = _deep_get(product_node, key) or _deep_get(state, key)
        if val:
            category = clean_text(str(val)).replace(">", " > ")
            break
    specs: dict[str, str] = {}
    attrs = _deep_get(product_node, "productAttributes") or _deep_get(product_node, "attributes") or []
    if isinstance(attrs, list):
        for a in attrs[:12]:
            if isinstance(a, dict):
                k = clean_text(str(a.get("attributeName") or a.get("name") or ""))
                v = clean_text(str(a.get("attributeValue") or a.get("value") or a.get("minAttributeValue") or ""))
                if k and v:
                    specs[k] = v
    description = ""
    for key in ("detailContent", "detailContents", "productDescription", "summary"):
        val = _deep_get(product_node, key)
        if isinstance(val, str) and len(val) > 20:
            description = clean_text(BeautifulSoup(val, "html.parser").get_text(" "))[:2000]
            break
    return {
        "name": name,
        "price": price,
        "original_price": original,
        "image_urls": unique(images),
        "brand": brand,
        "category": category,
        "specs": specs,
        "description": description,
    }


# ----------------------------------------------------------------------------- 이미지/특징/스펙
def _img_src(img: Any, base: str) -> str:
    for attr in ("data-src", "data-original", "data-lazy", "src"):
        val = img.get(attr)
        if val and not str(val).startswith("data:"):
            return urljoin(base, str(val))
    return ""


def collect_image_urls(soup: BeautifulSoup, base_url: str, extra: list[str] | None = None, limit: int = 12) -> list[str]:
    urls: list[str] = list(extra or [])
    og = _meta(soup, "og:image")
    if og:
        urls.insert(0, urljoin(base_url, og))
    for img in soup.select("img"):
        src = _img_src(img, base_url)
        if not src:
            continue
        try:
            w = int(str(img.get("width", "0")).replace("px", "") or 0)
            h = int(str(img.get("height", "0")).replace("px", "") or 0)
        except ValueError:
            w = h = 0
        if (w and w < 120) or (h and h < 120):
            continue
        urls.append(src)
    filtered: list[str] = []
    seen_paths: set[str] = set()
    for u in unique(urls):
        low = u.lower()
        if not low.startswith("http") or any(b in low for b in _BAD_IMG):
            continue
        path_key = low.split("?", 1)[0]
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        filtered.append(u)
    filtered.sort(key=lambda u: 0 if any(g in u.lower() for g in _GOOD_IMG) else 1)
    return filtered[:limit]


def _looks_like_nav(text: str) -> bool:
    return any(w in text for w in _NAV_WORDS)


def extract_features(soup: BeautifulSoup, limit: int = 8) -> list[str]:
    out: list[str] = []
    for node in soup.select("li, dd, p, h2, h3, h4, strong, em"):
        text = clean_text(node.get_text(" "))
        if 8 <= len(text) <= 90 and re.search(r"[가-힣]", text) and not _looks_like_nav(text):
            if any(bad in text for bad in ("쿠키", "javascript", "©", "Copyright", "All rights", "배송비", "교환/반품")):
                continue
            if _INFO_LINE_RE.search(text):
                continue
            out.append(text)
    return unique(out)[:limit]


def extract_specs(soup: BeautifulSoup, limit: int = 12) -> dict[str, str]:
    specs: dict[str, str] = {}
    for dl in soup.select("dl"):
        dts = dl.select("dt")
        dds = dl.select("dd")
        for dt, dd in zip(dts, dds):
            k = clean_text(dt.get_text(" "))
            v = clean_text(dd.get_text(" "))
            if 1 <= len(k) <= 20 and 1 <= len(v) <= 80:
                specs[k] = v
            if len(specs) >= limit:
                return specs
    for row in soup.select("table tr"):
        th = row.select_one("th")
        td = row.select_one("td")
        if th and td:
            k = clean_text(th.get_text(" "))
            v = clean_text(td.get_text(" "))
            if 1 <= len(k) <= 20 and 1 <= len(v) <= 80:
                specs[k] = v
        if len(specs) >= limit:
            break
    return specs


def _extract_prices_from_text(text: str) -> tuple[int | None, int | None]:
    price = None
    original = None
    for label, value in _PRICE_LABEL_RE.findall(text):
        val = parse_price(value)
        if val is None:
            continue
        if label in ("정가", "소비자가", "정상가"):
            original = original or val
        elif price is None:
            price = val
    if price is None:
        m = _ANY_PRICE_RE.search(text)
        if m:
            price = parse_price(m.group(1))
    if price and original and original <= price:
        original = None
    return price, original


# ----------------------------------------------------------------------------- 메인
def extract_product(html: str, url: str) -> dict[str, Any]:
    soup = _soup(html)
    data: dict[str, Any] = {
        "name": "",
        "brand": "",
        "category": "",
        "price": None,
        "original_price": None,
        "discount_rate": None,
        "description": "",
        "features": [],
        "specs": {},
        "image_urls": [],
        "product_url": url,
        "source": classify_source(url),
        "raw": {"extractors": []},
    }

    for obj in parse_jsonld_products(soup)[:1]:
        fields = _jsonld_to_fields(obj)
        data["raw"]["extractors"].append("jsonld")
        for k, v in fields.items():
            if v and k != "sku":
                data[k] = v

    state = find_preloaded_state(html)
    if state:
        fields = preloaded_state_to_fields(state)
        if fields.get("name"):
            data["raw"]["extractors"].append("preloaded_state")
            for k, v in fields.items():
                if v and (not data.get(k) or k in ("price", "original_price", "image_urls", "specs")):
                    data[k] = v

    og_title = _meta(soup, "og:title")
    if og_title:
        data["raw"]["extractors"].append("opengraph")
    data["name"] = data["name"] or og_title or (clean_text(soup.title.get_text()) if soup.title else "")
    data["name"] = clean_product_name(data["name"])
    data["description"] = data["description"] or _meta(soup, "og:description") or _meta(soup, "description")
    if not data["brand"]:
        site = _meta(soup, "og:site_name")
        if site and "네이버" not in site and "쿠팡" not in site:
            data["brand"] = site
    og_price = _meta(soup, "product:price:amount")
    if og_price and not data["price"]:
        data["price"] = parse_price(og_price)

    for tag in soup.select("script, style, noscript, header, footer, nav"):
        tag.decompose()
    text = clean_text(soup.get_text(" "))
    t_price, t_original = _extract_prices_from_text(text)
    data["price"] = data["price"] or t_price
    data["original_price"] = data["original_price"] or t_original
    if data["price"] and data["original_price"] and data["original_price"] > data["price"]:
        data["discount_rate"] = round((1 - data["price"] / data["original_price"]) * 100, 1)

    data["image_urls"] = collect_image_urls(soup, url, extra=data.get("image_urls") or [])
    data["features"] = data["features"] or extract_features(soup)
    data["features"] = [f for f in data["features"] if f != data["name"]][:8]
    if not data["specs"]:
        data["specs"] = extract_specs(soup)
    if not data["description"] and text:
        data["description"] = text[:600]
    data["description"] = clean_text(data["description"])[:2000]
    return data
