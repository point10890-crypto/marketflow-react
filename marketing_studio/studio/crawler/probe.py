"""DOM 프로브 — 셀렉터 튜닝용 페이지 구조 리포트.

`python -m studio probe <url>` → data/probe/<slug>/ 에 page.html, screenshot.png, probe.json 저장.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from studio.crawler.product_page import find_preloaded_state, parse_jsonld_products
from studio.utils import clean_text, ensure_dir, slugify


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception:
        return BeautifulSoup(html or "", "html.parser")


def css_path(el: Any, max_depth: int = 4) -> str:
    parts: list[str] = []
    node = el
    while node is not None and node.name and node.name != "[document]" and len(parts) < max_depth:
        cls = node.get("class") or []
        seg = node.name + ("." + ".".join(c for c in cls[:2]) if cls else "")
        parts.append(seg)
        node = node.parent
    return " > ".join(reversed(parts))


def probe_html(html: str, url: str = "") -> dict[str, Any]:
    soup = _soup(html)
    meta = {}
    for m in soup.select("meta[property], meta[name]"):
        key = m.get("property") or m.get("name")
        if key and (str(key).startswith(("og:", "product:", "twitter:")) or key in ("description", "keywords")):
            meta[str(key)] = clean_text(m.get("content"))[:200]
    jsonld_types = []
    for s in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(s.string or s.get_text() or "")
        except ValueError:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if isinstance(o, dict):
                jsonld_types.append(str(o.get("@type")))
    state = find_preloaded_state(html)
    class_counter: Counter[str] = Counter()
    for el in soup.find_all(True):
        for c in el.get("class") or []:
            class_counter[c] += 1
    repeated: list[dict[str, Any]] = []
    for el in soup.find_all(True):
        children = [c for c in el.children if getattr(c, "name", None)]
        if len(children) < 3:
            continue
        sig = Counter((c.name, tuple(c.get("class") or [])) for c in children)
        (name, cls), count = sig.most_common(1)[0]
        if count >= 3 and any(ch.select_one("a[href]") for ch in children[:count]):
            sample = clean_text(children[0].get_text(" "))[:120]
            repeated.append({
                "container": css_path(el),
                "child": name + ("." + ".".join(cls[:2]) if cls else ""),
                "count": count,
                "sample_text": sample,
            })
    repeated.sort(key=lambda r: -r["count"])
    campaign_links = [a.get("href") for a in soup.select("a[href]") if re.search(r"campaign|캠페인", str(a.get("href", "")) + a.get_text(), re.I)]
    text = clean_text(soup.get_text(" "))
    return {
        "url": url,
        "title": clean_text(soup.title.get_text()) if soup.title else "",
        "meta": meta,
        "jsonld_types": jsonld_types,
        "preloaded_state_keys": list(state.keys())[:30] if isinstance(state, dict) else [],
        "campaign_link_samples": [str(h) for h in campaign_links[:15]],
        "campaign_link_count": len(campaign_links),
        "repeated_containers": repeated[:12],
        "top_classes": class_counter.most_common(40),
        "image_count": len(soup.select("img")),
        "image_samples": [str(i.get("src") or i.get("data-src")) for i in soup.select("img")[:10]],
        "price_samples": re.findall(r"(?:\d{1,3}(?:,\d{3})+|\d{4,})\s*원", text)[:10],
        "percent_samples": re.findall(r"\d{1,3}(?:\.\d+)?\s*%", text)[:10],
        "date_samples": re.findall(r"20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2}일?", text)[:10],
        "login_marker": bool(soup.select_one("a[href*='nidlogin'], a[href*='nid.naver.com']")),
    }


def probe_live(session: Any, url: str, out_dir: Path | str) -> dict[str, Any]:
    out = ensure_dir(Path(out_dir) / slugify(url.split("//", 1)[-1], max_len=50))
    page = session.new_page()
    try:
        session.goto(page, url)
        session.scroll_to_bottom(page, steps=6)
        html = page.content()
        (out / "page.html").write_text(html, encoding="utf-8")
        try:
            page.screenshot(path=str(out / "screenshot.png"), full_page=True)
        except Exception:
            pass
        report = probe_html(html, page.url)
        report["logged_in"] = session.is_naver_logged_in()
        report["saved_to"] = str(out)
        (out / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        page.close()
