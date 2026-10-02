"""발행 패키지 — 채널별로 바로 올릴 수 있는 폴더 묶음 (자동 발행은 하지 않음)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from studio.config import Settings
from studio.content.markdown import markdown_to_html
from studio.db import Store
from studio.models import BlogPost, Product, VideoAsset, VideoScript
from studio.monetize import CHANNELS, channel_links, link_in_bio
from studio.utils import atomic_write_json, atomic_write_text, ensure_dir, slugify, today_str


def checklist_markdown(product: Product, blog: BlogPost | None, script: VideoScript | None, video: VideoAsset | None, links: dict[str, str]) -> str:
    lines = [f"# 발행 체크리스트 — {product.name}", ""]
    lines += ["> 이 앱은 자동 발행을 하지 않습니다. 아래 순서대로 직접 올리면 됩니다 (약 10분).", ""]
    lines += ["## 0. 링크 준비", f"- 제휴/구매 링크: {product.best_link or '(미설정 — 상품 편집에서 affiliate_url 입력)'}"]
    if links:
        lines += [f"- {CHANNELS.get(ch, ch)}: {url}" for ch, url in links.items()]
    lines += ["", "## 1. 네이버 블로그"]
    if blog:
        lines += [
            f"- 제목: {blog.title}",
            f"- SEO 점수: {blog.seo_score}/100 (blog/meta.json 참고)",
            "- blog/post.txt 를 에디터에 붙여넣고, [이미지 삽입: ...] 자리마다 images/ 의 해당 파일을 업로드",
            "- 본문 맨 아래 제휴 표시 문구가 남아 있는지 확인 (공정위 표시광고법)",
            f"- 태그: {' '.join(blog.hashtags[:10])}",
        ]
    else:
        lines.append("- (블로그 글 없음 — 콘텐츠 스튜디오에서 생성)")
    lines += ["", "## 2. 네이버 클립 / 유튜브 쇼츠 / 인스타 릴스"]
    if video:
        lines += [
            f"- 영상: video/{Path(video.path).name} ({video.duration:.0f}초, 세로 {video.width}x{video.height})",
            "- 썸네일: video/ 의 *_thumb.png",
            "- 제목/설명/해시태그: video/youtube.txt, video/clip.txt 복사",
            "- 자막 파일(SRT)은 유튜브 자막 업로드에 사용 가능",
            "- 설명란 첫 줄 또는 고정 댓글에 링크 + '#광고' 표기",
        ]
    elif script:
        lines.append("- (영상 미제작 — 대본은 video/script.json 참고, '영상 제작' 실행)")
    else:
        lines.append("- (대본/영상 없음)")
    lines += ["", "## 3. 발행 후", "- 수익 관리 탭에 채널별 클릭/주문/수수료 입력 (또는 정산 CSV 가져오기)", "- 7일 뒤 조회수·클릭 확인 → 제목/썸네일 A/B 수정", ""]
    return "\n".join(lines)


def build_publish_package(settings: Settings, store: Store, product_id: str) -> dict[str, Any]:
    product = store.get_product(product_id)
    if not product:
        raise ValueError("상품을 찾을 수 없습니다")
    blog = store.latest_content(product.id, "blog")
    script = store.latest_content(product.id, "script")
    videos = store.list_videos(product.id, limit=1)
    video = videos[0] if videos else None
    blog = blog if isinstance(blog, BlogPost) else None
    script = script if isinstance(script, VideoScript) else None

    pkg_name = f"{today_str()}_{slugify(product.name, max_len=40)}_{product.id}"
    pkg_dir = settings.package_dir / pkg_name
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir, ignore_errors=True)
    ensure_dir(pkg_dir)
    files: list[str] = []

    # images
    img_dir = ensure_dir(pkg_dir / "images")
    copied: dict[str, str] = {}
    for src in product.media:
        p = Path(src)
        if p.is_file():
            dst = img_dir / p.name
            if not dst.exists():
                shutil.copyfile(p, dst)
            copied[src] = f"images/{p.name}"
            files.append(f"images/{p.name}")

    # blog
    if blog:
        blog_dir = ensure_dir(pkg_dir / "blog")
        md = blog.markdown
        for src, rel in copied.items():
            md = md.replace(f"]({src})", f"](../{rel})")
        atomic_write_text(blog_dir / "post.md", md)
        atomic_write_text(blog_dir / "post.html", "<meta charset='utf-8'>\n" + markdown_to_html(md))
        atomic_write_text(blog_dir / "post.txt", blog.plain_text)
        atomic_write_json(blog_dir / "meta.json", {
            "title": blog.title, "meta_description": blog.meta_description, "primary_keyword": blog.primary_keyword,
            "keywords": blog.keywords, "hashtags": blog.hashtags, "seo_score": blog.seo_score, "seo_report": blog.seo_report,
            "char_count": blog.char_count, "provider": blog.provider,
        })
        files += ["blog/post.md", "blog/post.html", "blog/post.txt", "blog/meta.json"]

    # video
    if script or video:
        vid_dir = ensure_dir(pkg_dir / "video")
        if script:
            atomic_write_json(vid_dir / "script.json", script.to_dict())
            files.append("video/script.json")
        if video:
            for src in (video.path, video.thumbnail, video.srt):
                if src and Path(src).is_file():
                    dst = vid_dir / Path(src).name
                    shutil.copyfile(src, dst)
                    files.append(f"video/{dst.name}")
            meta = video.metadata or {}
            title = meta.get("title") or video.title or (script.title if script else product.name)
            desc = meta.get("description") or (script.description if script else "")
            tags = meta.get("hashtags") or (script.hashtags if script else [])
            link = product.best_link
            yt = [f"[제목]\n{title}", f"\n[설명]\n{desc}", f"\n🛒 구매 링크: {link}" if link else "", "\n#광고 " + " ".join(tags)]
            atomic_write_text(vid_dir / "youtube.txt", "\n".join(x for x in yt if x))
            clip = [f"[클립 제목]\n{title}", f"\n[설명]\n{desc}", f"\n링크: {link}" if link else "", "\n" + " ".join(tags[:10])]
            atomic_write_text(vid_dir / "clip.txt", "\n".join(x for x in clip if x))
            files += ["video/youtube.txt", "video/clip.txt"]

    # links
    links = channel_links(product, product.best_link)
    link_lines = [f"상품: {product.name}", f"구매/제휴 링크: {product.best_link or '(미설정)'}", ""]
    if links:
        link_lines += ["[채널별 링크]"] + [f"{CHANNELS.get(ch, ch)}: {url}" for ch, url in links.items()] + [""]
    if product.best_link:
        link_lines += ["[링크인바이오 / 고정댓글 문구]", link_in_bio(product, product.best_link), ""]
    link_lines += ["[표시 문구]", settings.disclosure]
    atomic_write_text(pkg_dir / "links.txt", "\n".join(link_lines))
    files.append("links.txt")

    atomic_write_text(pkg_dir / "CHECKLIST.md", checklist_markdown(product, blog, script, video, links))
    files.append("CHECKLIST.md")
    manifest = {
        "package": pkg_name,
        "dir": str(pkg_dir),
        "product_id": product.id,
        "product_name": product.name,
        "blog_id": blog.id if blog else "",
        "script_id": script.id if script else "",
        "video_id": video.id if video else "",
        "files": files,
        "created_at": today_str(),
    }
    atomic_write_json(pkg_dir / "package.json", manifest)
    product.status = "packaged"
    store.save_product(product)
    return manifest


def list_packages(settings: Settings) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not settings.package_dir.exists():
        return out
    for d in sorted(settings.package_dir.iterdir(), reverse=True):
        manifest = d / "package.json"
        if manifest.is_file():
            try:
                out.append(json.loads(manifest.read_text(encoding="utf-8")))
            except ValueError:
                continue
    return out
