"""슬라이드 합성 (Pillow) — 1080x1920 세로 프레임: 블러 배경 + 상품 이미지 + 큰 자막 + 진행바."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from studio.video.fonts import load_font

DEFAULT_THEME = {
    "bg": (18, 18, 24),
    "bg2": (36, 30, 52),
    "accent": (3, 199, 90),      # 네이버 그린
    "accent2": (255, 107, 53),
    "text": (255, 255, 255),
    "muted": (200, 200, 210),
    "caption_box": (0, 0, 0, 150),
}


def _pil():
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    return Image, ImageDraw, ImageEnhance, ImageFilter


def text_width(draw: Any, text: str, font: Any) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        box = draw.textbbox((0, 0), text, font=font)
        return box[2] - box[0]


def wrap_text(draw: Any, text: str, font: Any, max_width: int, max_lines: int = 3) -> list[str]:
    """단어 단위 줄바꿈, 단어가 너무 길면 글자 단위. 최대 줄 수 초과 시 말줄임."""
    words = (text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if text_width(draw, trial, font) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
            current = ""
        if text_width(draw, word, font) <= max_width:
            current = word
            continue
        chunk = ""
        for ch in word:
            if text_width(draw, chunk + ch, font) <= max_width:
                chunk += ch
            else:
                lines.append(chunk)
                chunk = ch
        current = chunk
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and text_width(draw, last + "…", font) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines or [""]


def _gradient(size: tuple[int, int], c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Any:
    Image, _, _, _ = _pil()
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
    return base.resize((w, h))


def _cover(img: Any, size: tuple[int, int]) -> Any:
    Image, _, _, _ = _pil()
    w, h = size
    ratio = max(w / img.width, h / img.height)
    resized = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))), Image.LANCZOS)
    left = (resized.width - w) // 2
    top = (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _fit(img: Any, box: tuple[int, int]) -> Any:
    Image, _, _, _ = _pil()
    ratio = min(box[0] / img.width, box[1] / img.height, 1.0 if img.width >= box[0] * 0.6 else 2.0)
    return img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))), Image.LANCZOS)


def _rounded_mask(size: tuple[int, int], radius: int) -> Any:
    Image, ImageDraw, _, _ = _pil()
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _draw_text_block(draw: Any, lines: list[str], font: Any, *, center_x: int, top: int, fill: tuple, stroke: tuple | None = None, stroke_width: int = 0, line_gap: int = 12) -> int:
    y = top
    for line in lines:
        w = text_width(draw, line, font)
        box = draw.textbbox((0, 0), line, font=font)
        line_h = box[3] - box[1]
        draw.text((center_x - w // 2, y), line, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke)
        y += line_h + line_gap
    return y


def compose_slide(
    *,
    out_path: str | Path,
    image_path: str | None = None,
    caption: str = "",
    subtitle: str = "",
    title: str = "",
    label: str = "",
    size: tuple[int, int] = (1080, 1920),
    font_path: str | None = None,
    theme: dict[str, Any] | None = None,
    progress: float | None = None,
) -> str:
    Image, ImageDraw, ImageEnhance, ImageFilter = _pil()
    th = {**DEFAULT_THEME, **(theme or {})}
    w, h = size
    canvas = _gradient(size, th["bg"], th["bg2"])

    img = None
    if image_path and Path(image_path).is_file():
        try:
            img = Image.open(image_path).convert("RGB")
        except Exception:
            img = None
    if img is not None:
        bg = _cover(img, size).filter(ImageFilter.GaussianBlur(28))
        bg = ImageEnhance.Brightness(bg).enhance(0.42)
        canvas.paste(bg, (0, 0))
        fg = _fit(img, (w - 140, int(h * 0.50)))
        fx = (w - fg.width) // 2
        fy = int(h * 0.15)
        shadow = Image.new("RGBA", (fg.width + 40, fg.height + 40), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((20, 20, fg.width + 20, fg.height + 20), radius=36, fill=(0, 0, 0, 140))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        canvas.paste(shadow, (fx - 20, fy - 8), shadow)
        canvas.paste(fg, (fx, fy), _rounded_mask(fg.size, 36))

    draw = ImageDraw.Draw(canvas, "RGBA")
    if title:
        f_title = load_font(font_path, 40)
        lines = wrap_text(draw, title, f_title, w - 160, max_lines=1)
        _draw_text_block(draw, lines, f_title, center_x=w // 2, top=70, fill=th["muted"])
    if label:
        f_label = load_font(font_path, 42)
        lw = text_width(draw, label, f_label) + 56
        lx = (w - lw) // 2
        ly = 130
        draw.rounded_rectangle((lx, ly, lx + lw, ly + 70), radius=35, fill=th["accent"] + (255,))
        draw.text((lx + 28, ly + 10), label, font=f_label, fill=(255, 255, 255))

    if caption:
        f_cap = load_font(font_path, 78)
        lines = wrap_text(draw, caption, f_cap, w - 140, max_lines=3)
        line_h = (draw.textbbox((0, 0), "가", font=f_cap)[3]) + 16
        block_h = line_h * len(lines) + 60
        top = int(h * 0.70) - block_h // 2
        draw.rounded_rectangle((60, top - 20, w - 60, top + block_h), radius=32, fill=th["caption_box"])
        _draw_text_block(draw, lines, f_cap, center_x=w // 2, top=top + 10, fill=th["text"], stroke=(0, 0, 0), stroke_width=4, line_gap=16)
        sub_top = top + block_h + 30
    else:
        sub_top = int(h * 0.72)

    if subtitle:
        f_sub = load_font(font_path, 40)
        lines = wrap_text(draw, subtitle, f_sub, w - 180, max_lines=3)
        _draw_text_block(draw, lines, f_sub, center_x=w // 2, top=sub_top, fill=th["muted"], stroke=(0, 0, 0), stroke_width=2, line_gap=10)

    if progress is not None:
        bar_y = h - 40
        draw.rounded_rectangle((60, bar_y, w - 60, bar_y + 12), radius=6, fill=(255, 255, 255, 60))
        end = 60 + int((w - 120) * max(0.0, min(1.0, progress)))
        draw.rounded_rectangle((60, bar_y, max(72, end), bar_y + 12), radius=6, fill=th["accent"] + (255,))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG")
    return str(out)


def compose_thumbnail(*, out_path: str | Path, image_path: str | None, title: str, badge: str = "솔직 후기", size: tuple[int, int] = (1080, 1920), font_path: str | None = None, theme: dict[str, Any] | None = None) -> str:
    return compose_slide(out_path=out_path, image_path=image_path, caption=title, label=badge, size=size, font_path=font_path, theme=theme)
