"""파이프라인 — 수집 → 키워드 → 블로그 → 대본 → 영상 → 발행 패키지.

모든 단계는 개별 호출 가능하며 `run_full()` 이 순서대로 묶는다.
progress(message, percent) 콜백으로 작업 상태를 보고한다 (JobRunner 연동).
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from studio.config import Settings
from studio.content.blog_writer import BlogWriter
from studio.content.keywords import KeywordSet, NaverKeywordTool, derive_keywords, enrich_with_volumes
from studio.content.llm import LLMClient
from studio.content.script_writer import FORMATS, ScriptWriter
from studio.crawler.brand_connect import BrandConnectCrawler, load_selectors, parse_campaign_detail
from studio.crawler.probe import probe_live
from studio.crawler.product_page import classify_source, extract_product
from studio.crawler.screenshots import capture_page_media
from studio.crawler.session import BrowserSession, check_login_status, login_interactive, playwright_available
from studio.db import Store
from studio.exporter import build_publish_package
from studio.models import BlogPost, Campaign, Product, VideoAsset, VideoScript
from studio.utils import atomic_write_json, atomic_write_text, ensure_dir, slugify
from studio.video.ffmpeg import ffmpeg_version, find_ffmpeg
from studio.video.fonts import find_font, font_supports_hangul
from studio.video.renderer import RenderScene, VideoRenderer
from studio.video.slides import compose_slide, compose_thumbnail
from studio.video.tts import TTS, edge_tts_available

log = logging.getLogger("studio.pipeline")

ProgressFn = Callable[[str, int | None], None]
RUNTIME_SETTING_KEYS = ("blog_tone", "blog_length", "tts_voice", "tts_rate", "disclosure", "creator_name", "headless", "brandconnect_url", "min_screenshots")
SCENE_LABELS = {"hook": "", "body": "", "feature": "POINT {n}", "offer": "가격 정보", "cta": "링크는 댓글·프로필"}


def _default_progress(message: str, pct: int | None = None) -> None:
    log.info("%s%s", f"[{pct}%] " if pct is not None else "", message)


class Pipeline:
    def __init__(self, settings: Settings, store: Store, *, llm: LLMClient | None = None, progress: ProgressFn | None = None) -> None:
        self.settings = settings
        self.store = store
        self.settings.ensure_dirs()
        self.apply_runtime_settings()
        self.llm = llm if llm is not None else LLMClient(settings)
        self.blog_writer = BlogWriter(settings, self.llm)
        self.script_writer = ScriptWriter(settings, self.llm)
        self.progress: ProgressFn = progress or _default_progress

    # ------------------------------------------------------------------ 공통
    def bind(self, progress: ProgressFn | None) -> "Pipeline":
        """진행 콜백만 바꾼 얕은 복사본 (작업 실행기용)."""
        clone = copy.copy(self)
        clone.progress = progress or _default_progress
        return clone

    def say(self, message: str, pct: int | None = None) -> None:
        self.progress(message, pct)

    def apply_runtime_settings(self) -> None:
        """DB 에 저장된 런타임 설정(UI 에서 변경)을 Settings 에 덮어쓴다."""
        runtime = self.store.get_setting("runtime", {}) or {}
        for key in RUNTIME_SETTING_KEYS:
            if key in runtime and runtime[key] not in (None, ""):
                value = runtime[key]
                if key in ("blog_length", "min_screenshots"):
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        continue
                if key == "headless":
                    value = bool(value)
                setattr(self.settings, key, value)

    def selectors(self) -> dict[str, Any]:
        return load_selectors(self.settings.data_dir / "selectors.override.json")

    def product_dir(self, product: Product) -> Path:
        return ensure_dir(self.settings.products_dir / product.id)

    def _session(self, *, headless: bool | None = None, persistent: bool = True) -> BrowserSession:
        if not playwright_available():
            raise RuntimeError("playwright 가 설치되지 않았습니다. setup.bat 을 실행하세요.")
        return BrowserSession(
            self.settings.profile_dir if persistent else None,
            headless=self.settings.headless if headless is None else headless,
            chromium_path=self.settings.chromium_path,
            timeout_ms=self.settings.crawl_timeout_ms,
        )

    # ------------------------------------------------------------------ 진단
    def doctor(self, *, check_login: bool = False) -> dict[str, Any]:
        ffmpeg = find_ffmpeg(self.settings.ffmpeg_path)
        font = find_font(self.settings.font_path, self.settings.assets_dir)
        report: dict[str, Any] = {
            "home": str(self.settings.home),
            "playwright": playwright_available(),
            "chromium_path": self.settings.chromium_path or "(playwright 기본)",
            "ffmpeg": ffmpeg or "",
            "ffmpeg_version": ffmpeg_version(ffmpeg) if ffmpeg else "",
            "font": font or "",
            "font_hangul": font_supports_hangul(font),
            "edge_tts": edge_tts_available(),
            "llm_providers": self.llm.providers(),
            "llm_mode": "llm" if self.llm.available() else "template",
            "naver_searchad": bool(self.settings.naver_searchad_api_key and self.settings.naver_searchad_secret and self.settings.naver_searchad_customer_id),
            "profile_exists": self.settings.profile_dir.exists() and any(self.settings.profile_dir.iterdir()),
            "counts": self.store.counts(),
        }
        if check_login and report["profile_exists"] and report["playwright"]:
            report["naver_logged_in"] = check_login_status(self.settings.profile_dir, chromium_path=self.settings.chromium_path)
        problems: list[str] = []
        if not report["playwright"]:
            problems.append("playwright 미설치 → setup.bat 실행")
        if not ffmpeg:
            problems.append("ffmpeg 를 찾을 수 없음 → pip install imageio-ffmpeg 또는 STUDIO_FFMPEG 설정")
        if not font or not report["font_hangul"]:
            problems.append("한글 폰트 없음 → STUDIO_FONT_PATH 설정 또는 assets/fonts 에 .ttf 추가")
        if not report["edge_tts"]:
            problems.append("edge-tts 미설치 → 무음 영상으로 제작됨")
        if not self.llm.available():
            problems.append("LLM API 키 없음 → 템플릿 모드로 작성됨 (.env 에 GEMINI/DEEPSEEK/OPENAI 키 입력 권장)")
        report["problems"] = problems
        report["ok"] = not problems
        return report

    # ------------------------------------------------------------------ 로그인
    def login(self, wait_seconds: int = 600) -> bool:
        self.say("네이버 로그인 창을 엽니다 — 브라우저에서 직접 로그인하세요", 5)
        ok = login_interactive(self.settings.profile_dir, chromium_path=self.settings.chromium_path, wait_seconds=wait_seconds, on_status=lambda m: self.say(m))
        self.store.set_setting("naver_logged_in", ok)
        self.say("로그인 완료" if ok else "로그인 확인 실패", 100 if ok else 90)
        return ok

    def login_status(self) -> bool:
        if not self.settings.profile_dir.exists():
            return False
        ok = check_login_status(self.settings.profile_dir, chromium_path=self.settings.chromium_path)
        self.store.set_setting("naver_logged_in", ok)
        return ok

    # ------------------------------------------------------------------ 브랜드커넥트
    def crawl_brand_connect(self, *, max_pages: int = 3, limit: int = 50, detail_limit: int = 0) -> dict[str, Any]:
        self.say("브라우저 시작", 3)
        imported: list[str] = []
        with self._session() as session:
            crawler = BrandConnectCrawler(session, list_url=self.settings.brandconnect_url, selectors=self.selectors(), save_dir=self.settings.campaigns_dir, progress=lambda m: self.say(m))
            campaigns = crawler.fetch_campaign_list(max_pages=max_pages, limit=limit)
            saved = self.store.save_campaigns(campaigns)
            self.say(f"캠페인 {saved}건 저장", 40)
            if detail_limit > 0:
                targets = [c for c in self.store.list_campaigns() if not c.product_id][:detail_limit]
                for i, c in enumerate(targets):
                    self.say(f"상세 수집 {i + 1}/{len(targets)}: {c.title}", 40 + int(50 * (i + 1) / max(1, len(targets))))
                    try:
                        product = self._import_campaign_with(session, crawler, c)
                        imported.append(product.id)
                    except Exception as e:  # noqa: BLE001
                        log.warning("상세 수집 실패 %s: %s", c.url, e)
        self.say(f"완료 — 캠페인 {len(campaigns)}건, 상품 {len(imported)}건", 100)
        return {"campaigns": len(campaigns), "imported_products": imported}

    def import_campaign(self, campaign_id: str) -> Product:
        campaign = self.store.get_campaign(campaign_id)
        if not campaign:
            raise ValueError("캠페인을 찾을 수 없습니다")
        with self._session() as session:
            crawler = BrandConnectCrawler(session, list_url=self.settings.brandconnect_url, selectors=self.selectors(), save_dir=self.settings.campaigns_dir, progress=lambda m: self.say(m))
            return self._import_campaign_with(session, crawler, campaign)

    def _import_campaign_with(self, session: BrowserSession, crawler: BrandConnectCrawler, campaign: Campaign) -> Product:
        data, page = crawler.fetch_campaign_detail(campaign.url)
        product = self._product_from_detail(data, campaign.url, campaign)
        existing = self.store.find_product_by_url(campaign.url)
        if existing:
            product.id = existing.id
            product.created_at = existing.created_at
            product.affiliate_url = existing.affiliate_url or product.affiliate_url
            product.keywords = existing.keywords
        pdir = self.product_dir(product)
        try:
            atomic_write_text(pdir / "page.html", page.content())
            media = capture_page_media(session, page, pdir, image_urls=product.image_urls, min_images=self.settings.min_screenshots, progress=lambda m: self.say(m))
            product.screenshots = media["screenshots"]
            product.images = media["images"]
        finally:
            page.close()
        if product.product_url:
            self._enrich_from_store(session, product)
        self.store.save_product(product)
        campaign.product_id = product.id
        self.store.save_campaigns([campaign])
        atomic_write_json(pdir / "product.json", product.to_dict())
        return product

    def _product_from_detail(self, data: dict[str, Any], source_url: str, campaign: Campaign | None) -> Product:
        camp = dict(data.get("campaign") or {})
        if campaign:
            camp.setdefault("title", campaign.title)
            for key, val in (("campaign_type", campaign.campaign_type), ("reward", campaign.reward), ("period", campaign.period)):
                if not camp.get(key) and val:
                    camp[key] = val
        name = data.get("name") or (campaign.title if campaign else "") or "이름 없는 상품"
        return Product(
            name=name,
            source="brandconnect",
            source_url=source_url,
            product_url=data.get("product_url", ""),
            brand=data.get("brand") or (campaign.brand if campaign else ""),
            description=data.get("description", ""),
            features=list(data.get("features") or []),
            commission_rate=data.get("commission_rate"),
            commission_note=data.get("commission_note", ""),
            price=data.get("price"),
            original_price=data.get("original_price"),
            image_urls=list(data.get("image_urls") or []),
            campaign=camp,
            raw={"extractor": "brandconnect"},
        )

    def _enrich_from_store(self, session: BrowserSession, product: Product) -> None:
        """브랜드커넥트 상세에 연결된 스마트스토어 상품 페이지에서 가격/이미지/스펙 보강 + 추가 스크린샷."""
        self.say(f"연결 상품 페이지 보강: {product.product_url}")
        page = session.new_page()
        try:
            if not session.goto(page, product.product_url):
                return
            session.scroll_to_bottom(page, steps=4)
            html = page.content()
            data = extract_product(html, page.url)
            if not product.price and data.get("price"):
                product.price = data["price"]
            if not product.original_price and data.get("original_price"):
                product.original_price = data["original_price"]
            if data.get("discount_rate"):
                product.discount_rate = data["discount_rate"]
            for key in ("brand", "category", "description"):
                if not getattr(product, key) and data.get(key):
                    setattr(product, key, data[key])
            if not product.specs and data.get("specs"):
                product.specs = data["specs"]
            if len(product.features) < 3 and data.get("features"):
                product.features = list(dict.fromkeys(product.features + data["features"]))[:8]
            new_urls = [u for u in data.get("image_urls") or [] if u not in product.image_urls]
            product.image_urls.extend(new_urls[:8])
            store_dir = ensure_dir(self.product_dir(product) / "store")
            atomic_write_text(store_dir / "page.html", html)
            media = capture_page_media(session, page, store_dir, image_urls=new_urls, min_images=0, mobile=False, progress=lambda m: self.say(m))
            product.screenshots += media["screenshots"]
            product.images += media["images"]
        except Exception as e:  # noqa: BLE001
            log.warning("상품 페이지 보강 실패: %s", e)
        finally:
            page.close()
        if product.price and product.original_price and product.original_price > product.price and not product.discount_rate:
            product.discount_rate = round((1 - product.price / product.original_price) * 100, 1)

    # ------------------------------------------------------------------ URL 가져오기
    def valid_url(self, url: str) -> bool:
        url = (url or "").strip().lower()
        if url.startswith(("http://", "https://")):
            return True
        return self.settings.allow_file_urls and url.startswith("file://")

    def import_url(self, url: str, *, capture: bool = True) -> Product:
        url = url.strip()
        if not self.valid_url(url):
            raise ValueError("http(s) URL 을 입력하세요")
        self.say(f"페이지 접속: {url}", 5)
        with self._session() as session:
            page = session.new_page()
            try:
                if not session.goto(page, url):
                    raise RuntimeError("페이지 접속 실패 (URL/네트워크 확인)")
                session.scroll_to_bottom(page, steps=4)
                html = page.content()
                final_url = page.url
                if classify_source(final_url) == "brandconnect" or classify_source(url) == "brandconnect":
                    data = parse_campaign_detail(html, final_url, self.selectors())
                    product = self._product_from_detail(data, url, None)
                else:
                    data = extract_product(html, final_url)
                    product = Product(
                        name=data.get("name") or "이름 없는 상품",
                        source=data.get("source", "url"),
                        source_url=url,
                        product_url=final_url,
                        brand=data.get("brand", ""),
                        category=data.get("category", ""),
                        price=data.get("price"),
                        original_price=data.get("original_price"),
                        discount_rate=data.get("discount_rate"),
                        description=data.get("description", ""),
                        features=list(data.get("features") or []),
                        specs=dict(data.get("specs") or {}),
                        image_urls=list(data.get("image_urls") or []),
                        raw=data.get("raw") or {},
                    )
                existing = self.store.find_product_by_url(url)
                if existing:
                    product.id = existing.id
                    product.created_at = existing.created_at
                    product.affiliate_url = existing.affiliate_url
                    product.keywords = existing.keywords
                    product.notes = existing.notes
                pdir = self.product_dir(product)
                atomic_write_text(pdir / "page.html", html)
                self.say(f"상품 정보 추출: {product.name}", 30)
                if capture:
                    media = capture_page_media(session, page, pdir, image_urls=product.image_urls, min_images=self.settings.min_screenshots, progress=lambda m: self.say(m, 50))
                    product.screenshots = media["screenshots"]
                    product.images = media["images"]
            finally:
                page.close()
            if product.source == "brandconnect" and product.product_url:
                self._enrich_from_store(session, product)
        self.store.save_product(product)
        atomic_write_json(pdir / "product.json", product.to_dict())
        self.say(f"상품 저장 완료: {product.name} (이미지 {len(product.media)}장)", 100)
        return product

    def add_manual_product(self, fields: dict[str, Any]) -> Product:
        product = Product.from_dict({k: v for k, v in fields.items() if k in Product.__dataclass_fields__})
        product.source = "manual"
        if not product.name:
            raise ValueError("상품명은 필수입니다")
        self.product_dir(product)
        self.store.save_product(product)
        return product

    # ------------------------------------------------------------------ 키워드
    def keywords_for(self, product: Product, *, refresh: bool = False) -> KeywordSet:
        if product.keywords and not refresh:
            return KeywordSet.from_dict(product.keywords)
        ks = derive_keywords(product)
        s = self.settings
        if s.naver_searchad_api_key and s.naver_searchad_secret and s.naver_searchad_customer_id:
            ks = enrich_with_volumes(ks, NaverKeywordTool(s.naver_searchad_api_key, s.naver_searchad_secret, s.naver_searchad_customer_id))
        product.keywords = ks.to_dict()
        self.store.save_product(product)
        return ks

    # ------------------------------------------------------------------ 블로그
    def generate_blog(self, product_id: str, *, tone: str | None = None, length: int | None = None) -> BlogPost:
        product = self._require_product(product_id)
        self.say(f"키워드 분석: {product.name}", 10)
        ks = self.keywords_for(product)
        self.say(f"블로그 작성 ({'LLM: ' + '/'.join(self.llm.providers()) if self.llm.available() else '템플릿 모드'})", 30)
        post = self.blog_writer.write(product, ks, tone=tone, target_length=length)
        self.store.save_content(post)
        out_dir = ensure_dir(self.settings.blog_dir / f"{post.slug}_{post.id}")
        atomic_write_text(out_dir / "post.md", post.markdown)
        atomic_write_text(out_dir / "post.html", "<meta charset='utf-8'>\n" + post.html)
        atomic_write_text(out_dir / "post.txt", post.plain_text)
        atomic_write_json(out_dir / "meta.json", {"title": post.title, "meta_description": post.meta_description, "keywords": post.keywords, "hashtags": post.hashtags, "seo": post.seo_report})
        if product.status == "new":
            product.status = "content_ready"
            self.store.save_product(product)
        self.say(f"블로그 완료 — SEO {post.seo_score}점, {post.char_count:,}자", 100)
        return post

    # ------------------------------------------------------------------ 대본
    def generate_script(self, product_id: str, *, fmt: str = "shorts", duration: int | None = None) -> VideoScript:
        product = self._require_product(product_id)
        ks = self.keywords_for(product)
        blog = self.store.latest_content(product.id, "blog")
        self.say(f"영상 대본 작성 ({FORMATS.get(fmt, FORMATS['shorts'])['label']})", 30)
        script = self.script_writer.write(product, ks, fmt=fmt, target_duration=duration, blog=blog if isinstance(blog, BlogPost) else None)
        self.store.save_content(script)
        if product.status == "new":
            product.status = "content_ready"
            self.store.save_product(product)
        self.say(f"대본 완료 — {len(script.scenes)}장면, 약 {script.duration:.0f}초", 100)
        return script

    # ------------------------------------------------------------------ 영상
    def render_video(self, product_id: str, *, script_id: str | None = None, bgm: str | None = None, voice: str | None = None, kenburns: bool = True, fmt: str = "shorts") -> VideoAsset:
        product = self._require_product(product_id)
        script = self.store.get_content(script_id) if script_id else self.store.latest_content(product.id, "script")
        if not isinstance(script, VideoScript):
            script = self.generate_script(product.id, fmt=fmt)
        ffmpeg = find_ffmpeg(self.settings.ffmpeg_path)
        if not ffmpeg:
            raise RuntimeError("ffmpeg 를 찾을 수 없습니다 (pip install imageio-ffmpeg 또는 STUDIO_FFMPEG 설정)")
        font = find_font(self.settings.font_path, self.settings.assets_dir)
        out_dir = ensure_dir(self.settings.video_dir / f"{slugify(product.name, max_len=40)}_{script.id}")
        tts = TTS(voice or self.settings.tts_voice, self.settings.tts_rate, ffmpeg=ffmpeg)
        scenes = script.scene_objects()
        render_scenes: list[RenderScene] = []
        engines: set[str] = set()
        feature_no = 0
        media = product.media
        for i, sc in enumerate(scenes):
            self.say(f"음성 합성 {i + 1}/{len(scenes)}", 10 + int(40 * (i + 1) / max(1, len(scenes))))
            audio = tts.synthesize(sc.narration, out_dir / f"scene_{i:02d}")
            engines.add(audio.engine)
            duration = round(audio.duration + 0.45, 2) if audio.engine != "silent" else round(max(2.0, sc.duration), 2)
            if sc.kind == "feature":
                feature_no += 1
            label = SCENE_LABELS.get(sc.kind, "").format(n=feature_no)
            visual = sc.visual if sc.visual and Path(sc.visual).is_file() else (media[i % len(media)] if media else None)
            slide = compose_slide(
                out_path=out_dir / f"slide_{i:02d}.png",
                image_path=visual,
                caption=sc.caption,
                subtitle=sc.narration if sc.narration != sc.caption else "",
                title=product.name,
                label=label,
                size=self.settings.video_size,
                font_path=font,
                progress=(i + 1) / max(1, len(scenes)),
            )
            render_scenes.append(RenderScene(image=slide, audio=audio.path, duration=duration, caption=sc.caption, narration=sc.narration))
        thumb = compose_thumbnail(out_path=out_dir / "thumbnail.png", image_path=media[0] if media else None, title=script.title or product.name, font_path=font, size=self.settings.video_size)
        bgm_path = bgm or self._default_bgm()
        self.say("영상 렌더링 시작", 55)
        renderer = VideoRenderer(ffmpeg, size=self.settings.video_size, fps=self.settings.video_fps)
        result = renderer.render(render_scenes, out_dir / f"{slugify(product.name, max_len=40)}.mp4", bgm_path=bgm_path, kenburns=kenburns, thumbnail_src=thumb, progress=lambda m: self.say(m))
        video = VideoAsset(
            product_id=product.id,
            script_id=script.id,
            title=script.title or product.name,
            path=result.path,
            thumbnail=result.thumbnail,
            srt=result.srt,
            duration=result.duration,
            width=self.settings.video_size[0],
            height=self.settings.video_size[1],
            tts_engine="+".join(sorted(engines)),
            metadata={
                "title": script.title,
                "description": script.description,
                "hashtags": script.hashtags,
                "format": script.format,
                "scenes": len(render_scenes),
                "bgm": bgm_path or "",
                "warnings": result.warnings,
                "tts_error": tts.last_error,
            },
        )
        self.store.save_video(video)
        atomic_write_json(out_dir / "metadata.json", video.to_dict())
        product.status = "video_ready"
        self.store.save_product(product)
        self.say(f"영상 완료 — {result.duration:.0f}초, TTS: {video.tts_engine}", 100)
        return video

    def _default_bgm(self) -> str | None:
        bgm_dir = self.settings.assets_dir / "bgm"
        if bgm_dir.is_dir():
            for f in sorted(bgm_dir.iterdir()):
                if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".ogg"):
                    return str(f)
        return None

    # ------------------------------------------------------------------ 패키지 / 전체
    def export_package(self, product_id: str) -> dict[str, Any]:
        self.say("발행 패키지 생성", 20)
        manifest = build_publish_package(self.settings, self.store, product_id)
        self.say(f"패키지 완료: {manifest['dir']}", 100)
        return manifest

    def run_full(
        self,
        *,
        url: str | None = None,
        product_id: str | None = None,
        campaign_id: str | None = None,
        fmt: str = "shorts",
        with_blog: bool = True,
        with_video: bool = True,
        with_package: bool = True,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if url:
            product = self.import_url(url)
        elif campaign_id:
            product = self.import_campaign(campaign_id)
        elif product_id:
            product = self._require_product(product_id)
        else:
            raise ValueError("url / product_id / campaign_id 중 하나가 필요합니다")
        result["product_id"] = product.id
        result["product_name"] = product.name
        if with_blog:
            blog = self.generate_blog(product.id)
            result["blog_id"] = blog.id
            result["seo_score"] = blog.seo_score
        script = self.generate_script(product.id, fmt=fmt)
        result["script_id"] = script.id
        if with_video:
            video = self.render_video(product.id, script_id=script.id)
            result["video_id"] = video.id
            result["video_path"] = video.path
        if with_package:
            manifest = self.export_package(product.id)
            result["package_dir"] = manifest["dir"]
        self.say("전체 파이프라인 완료", 100)
        return result

    # ------------------------------------------------------------------ 프로브 / 삭제
    def probe(self, url: str) -> dict[str, Any]:
        with self._session() as session:
            return probe_live(session, url, self.settings.probe_dir)

    def delete_product(self, product_id: str, *, remove_files: bool = True) -> None:
        product = self.store.get_product(product_id)
        self.store.delete_product(product_id)
        if product and remove_files:
            shutil.rmtree(self.settings.products_dir / product.id, ignore_errors=True)

    def _require_product(self, product_id: str) -> Product:
        product = self.store.get_product(product_id)
        if not product:
            raise ValueError(f"상품을 찾을 수 없습니다: {product_id}")
        return product
