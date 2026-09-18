"""키워드 도출 — 상품 정보 기반 휴리스틱 + (선택) 네이버 검색광고/데이터랩 검색량.

네이버 블로그 SEO 의 핵심은 '검색되는 키워드를 제목/서두/소제목에 배치' 하는 것.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import requests

from studio.models import Product
from studio.utils import clean_text, unique

log = logging.getLogger("studio.content.keywords")

_PROMO_WORDS = {
    "무료배송", "정품", "당일발송", "당일출고", "1+1", "특가", "세일", "할인", "사은품", "증정", "공식", "신상", "new",
    "인기", "베스트", "best", "hot", "추천", "모집", "체험단", "캠페인", "리뷰어", "원고료", "리뷰", "이벤트", "한정",
    "단독", "본품", "택1", "선택", "묶음", "기획", "행사", "프로모션", "쿠폰", "최저가", "핫딜", "데일리",
}
_UNIT_RE = re.compile(r"^\d+(개|팩|포|매|입|ml|g|kg|l|box|set|세트|p|ea|호|종)?$", re.I)


@dataclass
class KeywordSet:
    primary: str = ""
    secondary: list[str] = field(default_factory=list)
    longtail: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    volumes: dict[str, int] = field(default_factory=dict)
    source: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "KeywordSet":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})

    def all_keywords(self) -> list[str]:
        return unique([self.primary, *self.secondary, *self.longtail])


def hashtagify(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z가-힣]", "", text or "")
    return f"#{cleaned}" if cleaned else ""


def core_name(name: str, max_tokens: int = 4) -> str:
    """상품명에서 홍보 문구/괄호/수량을 걷어낸 핵심 명칭."""
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】", " ", name or "")
    s = re.sub(r"[^\w가-힣\s+\-]", " ", s)
    tokens: list[str] = []
    for tok in s.split():
        low = tok.lower()
        if low in _PROMO_WORDS or _UNIT_RE.match(tok):
            continue
        if any(low.startswith(p) for p in ("체험단", "캠페인", "모집")):
            continue
        tokens.append(tok)
    return " ".join(tokens[:max_tokens]).strip() or clean_text(name)[:30]


def category_leaf(category: str) -> str:
    if not category:
        return ""
    parts = [p.strip() for p in re.split(r">|/|>", category) if p.strip()]
    return parts[-1] if parts else ""


def derive_keywords(product: Product, extra: list[str] | None = None, year: int | None = None) -> KeywordSet:
    year = year or date.today().year
    core = core_name(product.name)
    brand = clean_text(product.brand)
    leaf = category_leaf(product.category)
    if brand and core.lower().startswith(brand.lower()):
        core_wo_brand = core[len(brand):].strip() or core
    else:
        core_wo_brand = core
    primary = core
    secondary = [
        f"{brand} {core_wo_brand}".strip() if brand and brand.lower() not in core.lower() else "",
        f"{core} 후기",
        f"{core} 추천",
        f"{core} 가격",
        f"{core} 장단점",
        f"{leaf} 추천" if leaf else "",
        f"{core} 비교",
    ]
    longtail = [
        f"{year} {core} 솔직 후기",
        f"{core} 구매 전 체크리스트",
        f"{core} 할인 정보",
        f"{core} 사용법",
        f"{leaf} 비교 {year}" if leaf else f"{core} 실사용 후기",
    ]
    for kw in extra or []:
        if kw and kw not in secondary:
            secondary.append(clean_text(kw))
    hashtags = [hashtagify(core)]
    if brand:
        hashtags.append(hashtagify(brand))
    if leaf:
        hashtags.append(hashtagify(leaf))
    for tok in core.split()[:3]:
        if len(tok) >= 2:
            hashtags.append(hashtagify(tok))
    hashtags += ["#후기", "#추천", "#리뷰", "#쇼핑추천", "#광고"]
    return KeywordSet(
        primary=primary,
        secondary=unique([clean_text(s) for s in secondary if s]),
        longtail=unique([clean_text(s) for s in longtail if s]),
        hashtags=unique([h for h in hashtags if h])[:15],
    )


# ----------------------------------------------------------------------------- 네이버 검색광고 키워드 도구 (선택)
class NaverKeywordTool:
    BASE = "https://api.searchad.naver.com"

    def __init__(self, api_key: str, secret: str, customer_id: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.secret = secret
        self.customer_id = customer_id
        self.http = session or requests.Session()

    def _headers(self, method: str, uri: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        msg = f"{ts}.{method}.{uri}"
        sig = base64.b64encode(hmac.new(self.secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")
        return {"X-Timestamp": ts, "X-API-KEY": self.api_key, "X-Customer": str(self.customer_id), "X-Signature": sig}

    @staticmethod
    def _to_int(value: Any) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value or "").replace(",", "")
        if "<" in s:
            return 5
        try:
            return int(float(s))
        except ValueError:
            return 0

    def keyword_stats(self, keywords: list[str]) -> dict[str, dict[str, Any]]:
        hints = ",".join(k.replace(" ", "") for k in keywords[:5] if k)
        if not hints:
            return {}
        uri = "/keywordstool"
        resp = self.http.get(self.BASE + uri, params={"hintKeywords": hints, "showDetail": "1"}, headers=self._headers("GET", uri), timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"검색광고 API HTTP {resp.status_code}: {resp.text[:200]}")
        out: dict[str, dict[str, Any]] = {}
        for item in resp.json().get("keywordList", []):
            kw = str(item.get("relKeyword", ""))
            pc = self._to_int(item.get("monthlyPcQcCnt"))
            mobile = self._to_int(item.get("monthlyMobileQcCnt"))
            out[kw] = {"pc": pc, "mobile": mobile, "total": pc + mobile, "competition": item.get("compIdx", "")}
        return out


class NaverDataLab:
    URL = "https://openapi.naver.com/v1/datalab/search"

    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = session or requests.Session()

    def trend(self, keywords: list[str], months: int = 6) -> dict[str, float]:
        end = date.today()
        start = end - timedelta(days=30 * months)
        groups = [{"groupName": k, "keywords": [k]} for k in keywords[:5] if k]
        if not groups:
            return {}
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "month", "keywordGroups": groups}
        resp = self.http.post(
            self.URL,
            json=body,
            headers={"X-Naver-Client-Id": self.client_id, "X-Naver-Client-Secret": self.client_secret, "Content-Type": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"데이터랩 HTTP {resp.status_code}: {resp.text[:200]}")
        out: dict[str, float] = {}
        for result in resp.json().get("results", []):
            data = result.get("data") or []
            out[result.get("title", "")] = float(data[-1].get("ratio", 0)) if data else 0.0
        return out


def enrich_with_volumes(ks: KeywordSet, tool: NaverKeywordTool | None) -> KeywordSet:
    """검색량이 있으면 secondary/longtail 을 검색량 순으로 정렬하고, 검색량이 압도적인 관련 키워드를 primary 후보로 반영."""
    if tool is None:
        return ks
    try:
        stats = tool.keyword_stats([ks.primary, *ks.secondary[:4]])
    except Exception as e:
        log.warning("검색량 조회 실패: %s", e)
        return ks
    if not stats:
        return ks
    volumes: dict[str, int] = {}
    for kw in ks.all_keywords():
        key = kw.replace(" ", "")
        for stat_kw, stat in stats.items():
            if stat_kw.replace(" ", "") == key:
                volumes[kw] = int(stat["total"])
                break
    related = sorted(((v["total"], k) for k, v in stats.items()), reverse=True)
    for total, kw in related[:5]:
        if kw not in volumes and kw.replace(" ", "") != ks.primary.replace(" ", ""):
            ks.secondary.append(kw)
            volumes[kw] = int(total)
    ks.secondary = unique(sorted(ks.secondary, key=lambda k: -volumes.get(k, 0)))
    ks.longtail = unique(sorted(ks.longtail, key=lambda k: -volumes.get(k, 0)))
    ks.volumes = volumes
    ks.source = "naver_searchad"
    return ks
