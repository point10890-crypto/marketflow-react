"""스크린샷/이미지 수집 전략 — 상품당 최소 3장 보장.

1. hero.png      : 첫 화면 (1280 폭)
2. fullpage.png  : 전체 페이지 (최대 8000px 까지)
3. mobile.png    : 모바일 뷰포트 (390x844) — 세로 영상용
4. section_N.png : 가격/상세/옵션 영역 요소 스크린샷 (있을 때)
5. image_N.jpg   : 상품 이미지 다운로드 (원본 URL)
6. tile_N.png    : 위가 부족하면 fullpage 를 잘라 채움
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Callable

from studio.utils import ensure_dir

log = logging.getLogger("studio.crawler.screenshots")

SECTION_SELECTORS = [
    "[class*='price']",
    "[class*='Price']",
    "[class*='option']",
    "[class*='detail']",
    "[class*='Detail']",
    "[class*='info']",
    "table",
]
MAX_FULLPAGE_HEIGHT = 8000


def _pil():
    from PIL import Image  # 지연 import

    return Image


def download_images(
    fetch: Callable[[str], bytes | None],
    urls: list[str],
    out_dir: Path,
    *,
    max_images: int = 6,
    min_side: int = 200,
) -> list[str]:
    Image = _pil()
    out: list[str] = []
    for url in urls:
        if len(out) >= max_images:
            break
        data = fetch(url)
        if not data or len(data) < 1024:
            continue
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            continue
        if min(img.size) < min_side:
            continue
        target = out_dir / f"image_{len(out) + 1}.jpg"
        try:
            img.convert("RGB").save(target, "JPEG", quality=90)
        except Exception:
            continue
        out.append(str(target))
    return out


def tile_image(src: Path | str, out_dir: Path, *, tile_height: int = 1280, max_tiles: int = 3, prefix: str = "tile") -> list[str]:
    Image = _pil()
    try:
        img = Image.open(src)
        img.load()
    except Exception:
        return []
    w, h = img.size
    tiles: list[str] = []
    y = 0
    while y < h and len(tiles) < max_tiles:
        box = (0, y, w, min(h, y + tile_height))
        if box[3] - box[1] < 200:
            break
        target = out_dir / f"{prefix}_{len(tiles) + 1}.png"
        img.crop(box).save(target, "PNG")
        tiles.append(str(target))
        y += tile_height
    return tiles


def capture_page_media(
    session: Any,
    page: Any,
    out_dir: Path | str,
    *,
    image_urls: list[str] | None = None,
    min_images: int = 3,
    max_downloads: int = 6,
    mobile: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, list[str]]:
    """열려 있는 page 에서 스크린샷 + 이미지 다운로드. {'screenshots': [...], 'images': [...]}"""
    say = progress or (lambda m: log.info(m))
    out_dir = ensure_dir(out_dir)
    shots: list[str] = []
    url = page.url

    hero = out_dir / "hero.png"
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(hero))
        shots.append(str(hero))
    except Exception as e:
        log.warning("hero 스크린샷 실패: %s", e)

    full = out_dir / "fullpage.png"
    try:
        height = int(page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)") or 0)
        vw = page.viewport_size["width"] if page.viewport_size else 1280
        if height > MAX_FULLPAGE_HEIGHT:
            page.screenshot(path=str(full), full_page=True, clip={"x": 0, "y": 0, "width": vw, "height": MAX_FULLPAGE_HEIGHT})
        else:
            page.screenshot(path=str(full), full_page=True)
        shots.append(str(full))
    except Exception as e:
        log.warning("fullpage 스크린샷 실패: %s", e)

    section_count = 0
    for sel in SECTION_SELECTORS:
        if section_count >= 2:
            break
        try:
            loc = page.locator(sel).first
            if loc.count() == 0 or not loc.is_visible():
                continue
            box = loc.bounding_box()
            if not box or box["height"] < 60 or box["height"] > 3000 or box["width"] < 200:
                continue
            target = out_dir / f"section_{section_count + 1}.png"
            loc.screenshot(path=str(target))
            shots.append(str(target))
            section_count += 1
        except Exception:
            continue

    if mobile:
        try:
            mp = session.new_page(viewport=(390, 844))
            if session.goto(mp, url, settle_ms=800):
                mp.screenshot(path=str(out_dir / "mobile.png"))
                shots.append(str(out_dir / "mobile.png"))
            mp.close()
        except Exception as e:
            log.debug("mobile 스크린샷 실패: %s", e)

    say(f"스크린샷 {len(shots)}장 저장")
    images = download_images(lambda u: session.fetch_bytes(u, referer=url), image_urls or [], out_dir, max_images=max_downloads)
    say(f"상품 이미지 {len(images)}장 다운로드")

    if len(shots) + len(images) < min_images:
        src = full if full.exists() else (hero if hero.exists() else None)
        if src:
            shots.extend(tile_image(src, out_dir, max_tiles=min_images - len(shots) - len(images)))
    return {"screenshots": shots, "images": images}
