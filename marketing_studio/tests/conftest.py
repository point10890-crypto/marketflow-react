from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# 샌드박스/CI 에서 playwright 가 설치한 브라우저 대신 사전 설치 크로미움 사용
if not os.environ.get("STUDIO_CHROMIUM_PATH") and Path("/opt/pw-browsers/chromium").exists():
    os.environ["STUDIO_CHROMIUM_PATH"] = "/opt/pw-browsers/chromium"
os.environ.setdefault("STUDIO_ALLOW_FILE_URLS", "1")
os.environ.setdefault("STUDIO_HEADLESS", "1")
for key in ("GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(key, None)


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_uri(name: str) -> str:
    return (FIXTURES / name).resolve().as_uri()


@lru_cache(maxsize=1)
def browser_available() -> bool:
    try:
        from studio.crawler.session import BrowserSession

        with BrowserSession(None, headless=True, chromium_path=os.environ.get("STUDIO_CHROMIUM_PATH") or None, timeout_ms=20000) as s:
            page = s.new_page()
            page.set_content("<h1>ok</h1>")
            return page.inner_text("h1") == "ok"
    except Exception:
        return False


@lru_cache(maxsize=1)
def ffmpeg_available() -> bool:
    from studio.video.ffmpeg import find_ffmpeg

    return bool(find_ffmpeg())


requires_browser = pytest.mark.skipif(not browser_available(), reason="Playwright 브라우저를 실행할 수 없음")
requires_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg 없음")


@pytest.fixture
def settings(tmp_path):
    from studio.config import Settings

    s = Settings(home=tmp_path / "home")
    s.allow_file_urls = True
    s.ensure_dirs()
    return s


@pytest.fixture
def store(settings):
    from studio.db import Store

    st = Store(settings.db_path)
    yield st
    st.close()


@pytest.fixture
def sample_image(tmp_path):
    from PIL import Image, ImageDraw

    path = tmp_path / "sample.jpg"
    img = Image.new("RGB", (800, 600), (220, 80, 60))
    ImageDraw.Draw(img).rectangle((100, 100, 700, 500), fill=(40, 120, 220))
    img.save(path, "JPEG")
    return str(path)


@pytest.fixture
def product_with_media(store, sample_image, tmp_path):
    from studio.models import Product

    media = []
    for name in ("hero.png", "fullpage.png", "mobile.png"):
        p = tmp_path / name
        Path(sample_image).replace(p) if False else None
        from PIL import Image

        Image.open(sample_image).save(p, "PNG")
        media.append(str(p))
    product = Product(
        name="클린테크 무선 청소기 X1", brand="클린테크", category="디지털/가전 > 생활가전 > 청소기 > 무선청소기",
        price=299000, original_price=359000, discount_rate=16.7, commission_rate=12.0,
        description="강력한 210W 흡입력과 5중 헤파 필터로 미세먼지까지 깨끗하게.",
        features=["강력 흡입력 210W 로 카펫 먼지까지", "1회 충전 최대 60분 사용", "본체 무게 1.4kg 초경량"],
        specs={"흡입력": "210W", "무게": "1.4kg"}, screenshots=media, affiliate_url="https://brandconnect.naver.com/l/abc",
        product_url="https://smartstore.naver.com/cleantech/products/123456",
    )
    return store.save_product(product)
