"""최소 Markdown → HTML / 플레인텍스트 변환기 (외부 의존성 없음).

블로그 작성기가 생성하는 문법만 지원: #/##/###, 문단, - 목록, 1. 목록, **굵게**, [링크](url), ![이미지](경로), > 인용, ---
"""

from __future__ import annotations

import html
import re
from pathlib import Path

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str, image_base: str = "") -> str:
    out = html.escape(text, quote=False)
    out = _IMG_RE.sub(lambda m: f'<img src="{_img_src(m.group(2), image_base)}" alt="{html.escape(m.group(1))}" style="max-width:100%">', out)
    out = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>', out)
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    return out


def _img_src(src: str, image_base: str) -> str:
    src = src.strip()
    if src.startswith(("http://", "https://", "data:")):
        return src
    if image_base:
        return image_base.rstrip("/") + "/" + Path(src).name
    return src


def markdown_to_html(markdown: str, image_base: str = "") -> str:
    lines = (markdown or "").splitlines()
    out: list[str] = []
    para: list[str] = []
    list_type: str | None = None

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(p, image_base) for p in para) + "</p>")
            para.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            close_list()
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_para()
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2), image_base)}</h{level}>")
            continue
        if line.strip() == "---":
            flush_para()
            close_list()
            out.append("<hr>")
            continue
        if line.startswith("> "):
            flush_para()
            close_list()
            out.append(f"<blockquote>{_inline(line[2:], image_base)}</blockquote>")
            continue
        m = re.match(r"^\s*[-•]\s+(.*)$", line)
        if m:
            flush_para()
            if list_type != "ul":
                close_list()
                out.append("<ul>")
                list_type = "ul"
            out.append(f"<li>{_inline(m.group(1), image_base)}</li>")
            continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            flush_para()
            if list_type != "ol":
                close_list()
                out.append("<ol>")
                list_type = "ol"
            out.append(f"<li>{_inline(m.group(1), image_base)}</li>")
            continue
        if _IMG_RE.fullmatch(line.strip()):
            flush_para()
            close_list()
            out.append(f'<figure>{_inline(line.strip(), image_base)}</figure>')
            continue
        close_list()
        para.append(line)
    flush_para()
    close_list()
    return "\n".join(out)


def markdown_to_plain(markdown: str) -> str:
    """네이버 블로그 에디터에 붙여넣기 좋은 플레인텍스트 (소제목 ■, 목록 •, 이미지 자리표시)."""
    out: list[str] = []
    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            marker = "■" if len(m.group(1)) <= 2 else "▶"
            out.append("")
            out.append(f"{marker} {m.group(2)}")
            continue
        if line.strip() == "---":
            out.append("")
            continue
        img = _IMG_RE.fullmatch(line.strip())
        if img:
            out.append(f"[이미지 삽입: {Path(img.group(2)).name}]")
            continue
        line = _IMG_RE.sub(lambda m: f"[이미지: {Path(m.group(2)).name}]", line)
        line = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", line)
        line = _BOLD_RE.sub(r"\1", line)
        line = re.sub(r"^\s*[-•]\s+", "• ", line)
        line = re.sub(r"^>\s*", "", line)
        out.append(line)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
