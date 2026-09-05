"""네이버 브랜드커넥트 캠페인 목록/상세 파서 + 라이브 크롤러.

설계 원칙
- DOM 이 바뀌어도 죽지 않게: 후보 셀렉터 리스트(selectors.json) → 첫 매칭 사용, 전부 실패하면 휴리스틱.
- 파서는 순수 함수(HTML 문자열 입력) → 브라우저 없이 픽스처로 테스트 가능.
- 라이브 크롤러는 원본 HTML 을 항상 저장 → `probe` 로 셀렉터 튜닝 가능.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from studio.models import Campaign
from studio.utils import clean_text, parse_percent, parse_period, parse_price, unique

log = logging.getLogger("studio.crawler.brand_connect")

_SELECTORS_PATH = Path(__file__).with_name("selectors.json")

CAMPAIGN_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("커미션", r"커미션|수수료|판매\s*수익|수익\s*쉐어|셰어|커넥트\s*링크|제휴\s*링크|어필리에이트|affiliate"),
    ("공동구매", r"공동\s*구매|공구"),
    ("체험단", r"체험단|체험|제품\s*(?:제공|증정)|무상|무료\s*제공"),
    ("원고료", r"원고료|고료|포스팅\s*비|콘텐츠\s*비"),
    ("클립", r"클립|숏폼|shorts|쇼츠|릴스"),
]
_REWARD_RE = re.compile(
    r"(수수료\s*\d{1,3}(?:\.\d+)?\s*%|\d{1,3}(?:\.\d+)?\s*%\s*(?:수수료|커미션|적립)?|원고료\s*[\d,]+\s*원|"
    r"[\d,]{4,}\s*원\s*(?:지급|상당|원고료|포인트|리워드)?|제품\s*(?:제공|증정)|무료\s*제공|포인트\s*[\d,]+)"
)
_COMMISSION_RE = re.compile(r"(?:수수료|커미션|commission)[^\d%]{0,12}(\d{1,3}(?:\.\d+)?)\s*%|(\d{1,3}(?:\.\d+)?)\s*%\s*(?:수수료|커미션)")
_PRICE_LABEL_RE = re.compile(r"(?:판매가|할인가|가격|정가|소비자가)\s*[:：]?\s*((?:\d{1,3}(?:,\d{3})+|\d{4,})\s*원)")
_NAV_WORDS = ("로그인", "회원가입", "고객센터", "이용약관", "개인정보", "공지사항", "마이페이지", "메뉴", "검색")
_INFO_LINE_RE = re.compile(r"수수료|원고료|판매가|정가|할인가|소비자가|모집\s*기간|신청\s*기간|캠페인\s*기간|리워드|미션|필수|\d{1,3}(?:,\d{3})+\s*원")


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception:  # lxml 미설치
        return BeautifulSoup(html or "", "html.parser")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_selectors(override_path: Path | str | None = None) -> dict[str, Any]:
    with open(_SELECTORS_PATH, "r", encoding="utf-8") as f:
        base = json.load(f)
    if override_path and Path(override_path).is_file():
        try:
            with open(override_path, "r", encoding="utf-8") as f:
                base = _deep_merge(base, json.load(f))
        except ValueError as e:
            log.warning("selectors override 파싱 실패: %s", e)
    return base


def _select(el: Any, selector: str) -> list[Any]:
    try:
        return el.select(selector)
    except Exception:
        return []


def _select_one(el: Any, selector: str) -> Any | None:
    try:
        return el.select_one(selector)
    except Exception:
        return None


def _node_text(node: Any) -> str:
    if node is None:
        return ""
    if node.name == "meta":
        return clean_text(node.get("content"))
    if node.name == "img":
        return clean_text(node.get("alt"))
    return clean_text(node.get_text(" "))


def _first_text(el: Any, selectors: list[str], *, min_len: int = 1, max_len: int = 300) -> str:
    for sel in selectors or []:
        node = _select_one(el, sel)
        text = _node_text(node)
        if len(text) >= min_len:
            return text[:max_len]
    return ""


def _abs(base: str, href: str | None) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith(("javascript:", "#", "mailto:", "tel:")):
        return ""
    return urljoin(base, href)


def _img_src(img: Any, base: str) -> str:
    if img is None:
        return ""
    for attr in ("data-src", "data-original", "data-lazy", "src"):
        val = img.get(attr)
        if val and not str(val).startswith("data:"):
            return _abs(base, str(val))
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        best = ""
        best_w = -1
        for part in str(srcset).split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = 0
            if len(bits) > 1 and bits[1].endswith("w"):
                try:
                    w = int(bits[1][:-1])
                except ValueError:
                    w = 0
            if w > best_w:
                best_w, best = w, bits[0]
        return _abs(base, best)
    return ""


def classify_campaign_type(text: str) -> str:
    t = text or ""
    for label, pattern in CAMPAIGN_TYPE_PATTERNS:
        if re.search(pattern, t, re.I):
            return label
    return ""


def extract_reward(text: str) -> str:
    m = _REWARD_RE.search(text or "")
    return clean_text(m.group(1)) if m else ""


def extract_commission_rate(text: str) -> float | None:
    m = _COMMISSION_RE.search(text or "")
    if m:
        raw = m.group(1) or m.group(2)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _looks_like_nav(text: str) -> bool:
    return any(w in text for w in _NAV_WORDS) and len(text) < 40


# ----------------------------------------------------------------------------- 목록
def parse_campaign_list(html: str, base_url: str, selectors: dict[str, Any] | None = None) -> list[Campaign]:
    sel = (selectors or load_selectors())["list"]
    soup = _soup(html)
    hints = [h.lower() for h in sel.get("path_hints", ["campaign"])]

    def has_campaign_link(el: Any) -> bool:
        anchors = [el] if el.name == "a" else _select(el, "a[href]")
        for a in anchors:
            href = str(a.get("href", "")).lower()
            if any(h in href for h in hints):
                return True
        return False

    items: list[Any] = []
    for item_sel in sel.get("item", []):
        candidates = [el for el in _select(soup, item_sel) if has_campaign_link(el)]
        if len(candidates) >= 2:
            items = candidates
            break
    if not items:
        # 휴리스틱: 캠페인 링크 앵커 → 가장 가까운 블록 컨테이너
        seen_containers: set[int] = set()
        for a in _select(soup, "a[href]"):
            href = str(a.get("href", "")).lower()
            if not any(h in href for h in hints):
                continue
            container = a
            for parent in a.parents:
                if parent.name in ("li", "article", "section"):
                    container = parent
                    break
                if parent.name == "div" and len(clean_text(parent.get_text(" "))) > 12:
                    container = parent
                    break
            if id(container) in seen_containers:
                continue
            seen_containers.add(id(container))
            items.append(container)

    campaigns: list[Campaign] = []
    seen_urls: set[str] = set()
    base_norm = base_url.rstrip("/")
    for el in items:
        anchor = el if el.name == "a" else None
        if anchor is None:
            for a in _select(el, "a[href]"):
                if any(h in str(a.get("href", "")).lower() for h in hints):
                    anchor = a
                    break
            if anchor is None:
                anchor = _select_one(el, "a[href]")
        url = _abs(base_url, anchor.get("href") if anchor else None)
        if not url or url.rstrip("/") == base_norm or url in seen_urls:
            continue
        whole_text = clean_text(el.get_text(" "))
        title = _first_text(el, sel.get("title", []), min_len=2, max_len=120)
        if not title and anchor is not None:
            title = clean_text(anchor.get_text(" "))[:120] or clean_text((_select_one(anchor, "img") or {}).get("alt") if _select_one(anchor, "img") else "")
        if not title or len(title) < 2 or _looks_like_nav(title):
            continue
        brand = _first_text(el, sel.get("brand", []), max_len=60)
        reward = _first_text(el, sel.get("reward", []), max_len=80) or extract_reward(whole_text)
        period_text = _first_text(el, sel.get("period", []), max_len=80)
        period = parse_period(period_text or whole_text)
        type_text = " ".join(_node_text(n) for s in sel.get("type", []) for n in _select(el, s)[:3])
        ctype = classify_campaign_type(type_text) or classify_campaign_type(reward) or classify_campaign_type(whole_text)
        tags = unique(clean_text(t) for t in type_text.split() if 1 < len(clean_text(t)) <= 12)[:6]
        thumb = _img_src(_select_one(el, sel.get("thumbnail", ["img"])[0] if sel.get("thumbnail") else "img"), base_url)
        seen_urls.add(url)
        campaigns.append(
            Campaign(
                title=title,
                url=url,
                brand=brand,
                campaign_type=ctype,
                reward=reward,
                period=period if period and period != whole_text[:80] else "",
                thumbnail=thumb,
                tags=tags,
                raw={"text": whole_text[:300]},
            )
        )
    return campaigns


def discover_campaign_list_urls(html: str, base_url: str, selectors: dict[str, Any] | None = None) -> list[str]:
    """네비게이션에서 캠페인 목록으로 보이는 링크 후보."""
    sel = (selectors or load_selectors())["list"]
    hints = [h.lower() for h in sel.get("path_hints", ["campaign"])]
    soup = _soup(html)
    out: list[str] = []
    for a in _select(soup, "a[href]"):
        href = str(a.get("href", ""))
        text = clean_text(a.get_text(" "))
        if any(h in href.lower() for h in hints) or "캠페인" in text:
            url = _abs(base_url, href)
            if url and urlparse(url).netloc.endswith("naver.com"):
                out.append(url)
    return unique(out)


# ----------------------------------------------------------------------------- 상세
def _meta(soup: BeautifulSoup, prop: str) -> str:
    node = _select_one(soup, f"meta[property='{prop}']") or _select_one(soup, f"meta[name='{prop}']")
    return clean_text(node.get("content")) if node else ""


def extract_features(soup: BeautifulSoup, limit: int = 8) -> list[str]:
    out: list[str] = []
    for node in _select(soup, "li, dd, p, h3, h4, strong"):
        text = clean_text(node.get_text(" "))
        if 8 <= len(text) <= 90 and re.search(r"[가-힣]", text) and not _looks_like_nav(text):
            if any(bad in text for bad in ("쿠키", "javascript", "©", "Copyright", "All rights")):
                continue
            if _INFO_LINE_RE.search(text):
                continue
            out.append(text)
    return unique(out)[:limit]


def _filter_image_urls(urls: list[str]) -> list[str]:
    bad = ("icon", "logo", "sprite", "btn_", "button", "blank", "loading", "emoticon", "badge", "profile", "avatar", ".svg", ".gif", "1x1", "pixel", "spacer")
    out: list[str] = []
    for u in urls:
        low = u.lower()
        if not low.startswith("http"):
            continue
        if any(b in low for b in bad):
            continue
        out.append(u)
    return unique(out)


def parse_campaign_detail(html: str, url: str, selectors: dict[str, Any] | None = None) -> dict[str, Any]:
    sel = (selectors or load_selectors())["detail"]
    soup = _soup(html)
    for tag in soup.select("script, style, noscript"):
        tag.decompose()
    whole_text = clean_text(soup.get_text(" "))

    title = _meta(soup, "og:title") or _first_text(soup, sel.get("title", []), min_len=2, max_len=150)
    if not title and soup.title:
        title = clean_text(soup.title.get_text())
    title = re.sub(r"\s*[|\-:]\s*(네이버\s*)?브랜드\s*커넥트.*$", "", title).strip()

    description = _meta(soup, "og:description") or _meta(soup, "description")
    detail_text = _first_text(soup, sel.get("description", []), min_len=20, max_len=2000)
    if len(detail_text) > len(description):
        description = detail_text

    brand = _first_text(soup, sel.get("brand", []), max_len=60)
    reward = _first_text(soup, sel.get("reward", []), max_len=120) or extract_reward(whole_text)
    commission = extract_commission_rate(reward) or extract_commission_rate(whole_text)
    period = parse_period(_first_text(soup, sel.get("period", []), max_len=120))
    if not period:
        m = re.search(r"(?:모집|신청|캠페인|진행)\s*기간[^0-9]{0,10}([0-9.\-/년월일\s~]{8,40})", whole_text)
        period = parse_period(m.group(1)) if m else ""
    mission = _first_text(soup, sel.get("mission", []), min_len=8, max_len=600)
    type_text = " ".join(_node_text(n) for s in sel.get("type", []) for n in _select(soup, s)[:4])
    ctype = classify_campaign_type(type_text) or classify_campaign_type(reward) or classify_campaign_type(whole_text)

    product_url = ""
    for s in sel.get("product_link", []):
        node = _select_one(soup, s)
        candidate = _abs(url, node.get("href") if node else None)
        if candidate and candidate.rstrip("/") != url.rstrip("/"):
            product_url = candidate
            break

    images: list[str] = []
    og_image = _meta(soup, "og:image")
    if og_image:
        images.append(_abs(url, og_image))
    for s in sel.get("images", []):
        for img in _select(soup, s):
            src = _img_src(img, url)
            if src:
                images.append(src)
        if len(unique(images)) >= 6:
            break
    images = _filter_image_urls(unique(images))[:12]

    price = None
    original_price = None
    m = _PRICE_LABEL_RE.search(whole_text)
    if m:
        price = parse_price(m.group(1))
    og_price = _meta(soup, "product:price:amount")
    if og_price and not price:
        price = parse_price(og_price)
    m2 = re.search(r"(?:정가|소비자가)\s*[:：]?\s*((?:\d{1,3}(?:,\d{3})+|\d{4,})\s*원)", whole_text)
    if m2:
        original_price = parse_price(m2.group(1))
        if price and original_price and original_price <= price:
            original_price = None

    return {
        "name": title,
        "brand": brand,
        "description": description[:2000],
        "features": extract_features(soup),
        "commission_rate": commission,
        "commission_note": reward,
        "product_url": product_url,
        "image_urls": images,
        "price": price,
        "original_price": original_price,
        "campaign": {
            "url": url,
            "campaign_type": ctype,
            "reward": reward,
            "period": period,
            "mission": mission,
        },
    }


# ----------------------------------------------------------------------------- 라이브 크롤러
class BrandConnectCrawler:
    """로그인된 BrowserSession 으로 캠페인 목록/상세를 수집한다."""

    def __init__(
        self,
        session: Any,
        *,
        list_url: str,
        selectors: dict[str, Any] | None = None,
        save_dir: Path | str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.session = session
        self.list_url = list_url
        self.selectors = selectors or load_selectors()
        self.save_dir = Path(save_dir) if save_dir else None
        self.progress = progress or (lambda m: log.info(m))

    def _save_html(self, name: str, html: str) -> None:
        if not self.save_dir:
            return
        try:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            (self.save_dir / name).write_text(html, encoding="utf-8")
        except OSError as e:
            log.debug("HTML 저장 실패: %s", e)

    def _requires_login(self, page: Any, html: str) -> bool:
        if self.session.is_naver_logged_in():
            return False
        if "nid.naver.com" in (page.url or ""):
            return True
        soup = _soup(html)
        for marker in self.selectors.get("login_markers", []):
            if _select_one(soup, marker) is not None:
                return True
        return False

    def _click_load_more(self, page: Any) -> bool:
        for text in self.selectors["list"].get("load_more_text", []):
            try:
                btn = page.get_by_role("button", name=re.compile(re.escape(text)))
                if btn.count() and btn.first.is_visible():
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
        return False

    def _click_next(self, page: Any) -> bool:
        for s in self.selectors["list"].get("next", []):
            try:
                loc = page.locator(s)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
        return False

    def fetch_campaign_list(self, *, max_pages: int = 3, limit: int = 100, max_load_more: int = 5) -> list[Campaign]:
        page = self.session.new_page()
        try:
            self.progress(f"캠페인 목록 접속: {self.list_url}")
            self.session.goto(page, self.list_url)
            html = page.content()
            if self._requires_login(page, html):
                raise LoginRequired("네이버 로그인이 필요합니다. 먼저 '네이버 로그인'을 실행하세요.")
            self.session.scroll_to_bottom(page)
            html = page.content()
            self._save_html("list_page_1.html", html)
            campaigns = parse_campaign_list(html, page.url, self.selectors)
            if not campaigns:
                for candidate in discover_campaign_list_urls(html, page.url, self.selectors)[:4]:
                    if candidate.rstrip("/") == page.url.rstrip("/"):
                        continue
                    self.progress(f"캠페인 목록 후보 탐색: {candidate}")
                    self.session.goto(page, candidate)
                    self.session.scroll_to_bottom(page)
                    html = page.content()
                    self._save_html("list_page_discovered.html", html)
                    campaigns = parse_campaign_list(html, page.url, self.selectors)
                    if campaigns:
                        break
            seen = {c.url for c in campaigns}
            for _ in range(max_load_more):
                if len(campaigns) >= limit or not self._click_load_more(page):
                    break
                self.session.scroll_to_bottom(page, steps=3)
                for c in parse_campaign_list(page.content(), page.url, self.selectors):
                    if c.url not in seen:
                        seen.add(c.url)
                        campaigns.append(c)
            for page_no in range(2, max_pages + 1):
                if len(campaigns) >= limit or not self._click_next(page):
                    break
                self.session.scroll_to_bottom(page, steps=4)
                html = page.content()
                self._save_html(f"list_page_{page_no}.html", html)
                new = [c for c in parse_campaign_list(html, page.url, self.selectors) if c.url not in seen]
                if not new:
                    break
                for c in new:
                    seen.add(c.url)
                    campaigns.append(c)
                self.progress(f"{page_no}페이지 수집 — 누적 {len(campaigns)}건")
            self.progress(f"캠페인 {len(campaigns)}건 수집 완료")
            return campaigns[:limit]
        finally:
            try:
                page.close()
            except Exception:
                pass

    def fetch_campaign_detail(self, url: str) -> tuple[dict[str, Any], Any]:
        """상세 페이지 파싱. (data, page) 반환 — 호출자가 page 로 스크린샷을 찍고 닫는다."""
        page = self.session.new_page()
        self.progress(f"캠페인 상세 접속: {url}")
        self.session.goto(page, url)
        html = page.content()
        if self._requires_login(page, html):
            page.close()
            raise LoginRequired("네이버 로그인이 필요합니다.")
        self.session.scroll_to_bottom(page, steps=5)
        html = page.content()
        slug = re.sub(r"[^0-9a-zA-Z]+", "_", url.split("//", 1)[-1])[:80]
        self._save_html(f"detail_{slug}.html", html)
        data = parse_campaign_detail(html, page.url, self.selectors)
        data["source_url"] = url
        return data, page
