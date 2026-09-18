"""한글 폰트 탐색 — 명시 경로 → assets/fonts → OS 기본 후보."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("studio.video.fonts")

_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\NanumGothicBold.ttf",
    r"C:\Windows\Fonts\NotoSansKR-Bold.otf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def find_font(explicit: str | None = None, assets_dir: Path | str | None = None) -> str | None:
    if explicit and Path(explicit).is_file():
        return str(explicit)
    if assets_dir:
        fonts_dir = Path(assets_dir) / "fonts"
        if fonts_dir.is_dir():
            for pattern in ("*Bold*.ttf", "*Bold*.otf", "*.ttf", "*.otf", "*.ttc"):
                found = sorted(fonts_dir.glob(pattern))
                if found:
                    return str(found[0])
    for c in _CANDIDATES_BOLD:
        if Path(c).is_file():
            return c
    return None


def load_font(path: str | None, size: int) -> Any:
    from PIL import ImageFont

    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception as e:
            log.warning("폰트 로드 실패 %s: %s", path, e)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 구버전 Pillow
        return ImageFont.load_default()


def font_supports_hangul(path: str | None) -> bool:
    if not path:
        return False
    try:
        from PIL import ImageFont

        font = ImageFont.truetype(path, 40)
        box_ko = font.getbbox("한")
        box_blank = font.getbbox(" ")
        return bool(box_ko) and (box_ko[2] - box_ko[0]) > 5 and box_ko != box_blank
    except Exception:
        return False
