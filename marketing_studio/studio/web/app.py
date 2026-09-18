"""Flask API — 스튜디오 UI 백엔드. 오래 걸리는 작업은 JobRunner 로 큐잉하고 /api/jobs 로 폴링."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file, send_from_directory

from studio import __version__
from studio.config import Settings, get_settings
from studio.content.keywords import derive_keywords
from studio.db import Store
from studio.exporter import list_packages
from studio.jobs import JobRunner
from studio.models import AffiliateLink, BlogPost, EarningsEntry, Product, VideoAsset, VideoScript
from studio.monetize import CHANNELS, channel_links, earnings_summary, link_in_bio, parse_settlement_csv, revenue_calculator
from studio.pipeline import RUNTIME_SETTING_KEYS, Pipeline
from studio.utils import atomic_write_json, resolve_under, safe_relpath

log = logging.getLogger("studio.web")
STATIC_DIR = Path(__file__).with_name("static")


class APIError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def create_app(settings: Settings | None = None, store: Store | None = None, runner: JobRunner | None = None, pipeline: Pipeline | None = None) -> Flask:
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = store or Store(settings.db_path)
    store.mark_stale_jobs_failed()
    pipeline = pipeline or Pipeline(settings, store)
    runner = runner or JobRunner(store)
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.json.ensure_ascii = False  # type: ignore[attr-defined]
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
    app.extensions["studio"] = {"settings": settings, "store": store, "runner": runner, "pipeline": pipeline}
    login_cache: dict[str, Any] = {"value": store.get_setting("naver_logged_in", False), "at": 0.0}

    # ------------------------------------------------------------------ helpers
    def file_url(path: str | None) -> str:
        if not path:
            return ""
        rel = safe_relpath(path, settings.home)
        if rel.startswith("/") or rel[1:3] == ":/" or rel.startswith(".."):
            return ""
        return "/files/" + rel

    def ser_product(p: Product) -> dict[str, Any]:
        d = p.to_dict()
        d["media_urls"] = [u for u in (file_url(x) for x in p.media) if u]
        d["thumbnail_url"] = d["media_urls"][0] if d["media_urls"] else ""
        d["best_link"] = p.best_link
        return d

    def ser_content(c: BlogPost | VideoScript) -> dict[str, Any]:
        d = c.to_dict()
        if isinstance(c, BlogPost):
            html = c.html
            for img in c.images:
                url = file_url(img)
                if url:
                    html = html.replace(f'src="{img}"', f'src="{url}"')
            d["html_preview"] = html
        else:
            for s in d.get("scenes", []):
                s["visual_url"] = file_url(s.get("visual", ""))
        return d

    def ser_video(v: VideoAsset) -> dict[str, Any]:
        d = v.to_dict()
        d["url"] = file_url(v.path)
        d["thumbnail_url"] = file_url(v.thumbnail)
        d["srt_url"] = file_url(v.srt)
        return d

    def body() -> dict[str, Any]:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def submit(job_type: str, payload: dict[str, Any], fn):
        job = runner.submit(job_type, payload, fn)
        return jsonify({"job": job.to_dict()}), 202

    def require_product(pid: str) -> Product:
        p = store.get_product(pid)
        if not p:
            raise APIError("상품을 찾을 수 없습니다", 404)
        return p

    # ------------------------------------------------------------------ errors
    @app.errorhandler(APIError)
    def _api_error(e: APIError):
        return jsonify({"error": str(e)}), e.status

    @app.errorhandler(404)
    def _not_found(_e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return send_from_directory(STATIC_DIR, "index.html")

    @app.errorhandler(Exception)
    def _any_error(e: Exception):
        log.exception("API 오류: %s", e)
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    # ------------------------------------------------------------------ static
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/files/<path:rel>")
    def files(rel: str):
        target = resolve_under(settings.home, rel)
        if not target or not target.is_file():
            raise APIError("파일 없음", 404)
        return send_file(target, conditional=True)

    # ------------------------------------------------------------------ status / settings
    @app.get("/api/status")
    def status():
        report = pipeline.doctor(check_login=False)
        report["version"] = __version__
        report["naver_logged_in"] = bool(login_cache["value"])
        report["active_jobs"] = [j.to_dict() for j in store.list_jobs(limit=5, active_only=True)]
        return jsonify(report)

    @app.get("/api/settings")
    def get_settings_api():
        return jsonify({"settings": settings.public_dict(), "runtime": store.get_setting("runtime", {}) or {}, "runtime_keys": list(RUNTIME_SETTING_KEYS), "channels": CHANNELS})

    @app.put("/api/settings")
    def put_settings():
        data = body()
        runtime = store.get_setting("runtime", {}) or {}
        for key in RUNTIME_SETTING_KEYS:
            if key in data:
                runtime[key] = data[key]
        store.set_setting("runtime", runtime)
        pipeline.apply_runtime_settings()
        return jsonify({"runtime": runtime, "settings": settings.public_dict()})

    @app.get("/api/settings/selectors")
    def get_selectors():
        override = settings.data_dir / "selectors.override.json"
        override_text = override.read_text(encoding="utf-8") if override.is_file() else ""
        return jsonify({"effective": pipeline.selectors(), "override": override_text})

    @app.put("/api/settings/selectors")
    def put_selectors():
        text = (body().get("override") or "").strip()
        override = settings.data_dir / "selectors.override.json"
        if not text:
            if override.exists():
                override.unlink()
            return jsonify({"ok": True, "override": ""})
        try:
            parsed = json.loads(text)
        except ValueError as e:
            raise APIError(f"JSON 파싱 실패: {e}")
        atomic_write_json(override, parsed)
        return jsonify({"ok": True, "effective": pipeline.selectors()})

    # ------------------------------------------------------------------ naver login
    @app.get("/api/naver/status")
    def naver_status():
        if request.args.get("refresh") == "1" and time.time() - login_cache["at"] > 5:
            login_cache["value"] = pipeline.login_status()
            login_cache["at"] = time.time()
        return jsonify({"logged_in": bool(login_cache["value"]), "checked_at": login_cache["at"]})

    @app.post("/api/naver/login")
    def naver_login():
        def fn(job, progress):
            ok = pipeline.bind(progress).login(wait_seconds=int(body_payload.get("wait", 600)))
            login_cache["value"] = ok
            login_cache["at"] = time.time()
            return {"logged_in": ok}

        body_payload = body()
        return submit("naver_login", body_payload, fn)

    # ------------------------------------------------------------------ brand connect
    @app.post("/api/brandconnect/crawl")
    def crawl():
        data = body()
        max_pages = int(data.get("max_pages", 3))
        limit = int(data.get("limit", 50))
        details = int(data.get("detail_limit", 0))
        return submit("crawl", data, lambda job, progress: pipeline.bind(progress).crawl_brand_connect(max_pages=max_pages, limit=limit, detail_limit=details))

    @app.get("/api/campaigns")
    def campaigns():
        return jsonify({"campaigns": [c.to_dict() for c in store.list_campaigns()]})

    @app.delete("/api/campaigns")
    def clear_campaigns():
        store.clear_campaigns()
        return jsonify({"ok": True})

    @app.post("/api/campaigns/<cid>/import")
    def import_campaign(cid: str):
        if not store.get_campaign(cid):
            raise APIError("캠페인을 찾을 수 없습니다", 404)
        return submit("import_campaign", {"campaign_id": cid}, lambda job, progress: {"product": ser_product(pipeline.bind(progress).import_campaign(cid))})

    @app.post("/api/probe")
    def probe():
        url = (body().get("url") or "").strip()
        if not pipeline.valid_url(url):
            raise APIError("http(s) URL 을 입력하세요")
        return submit("probe", {"url": url}, lambda job, progress: pipeline.bind(progress).probe(url))

    # ------------------------------------------------------------------ products
    @app.get("/api/products")
    def products():
        return jsonify({"products": [ser_product(p) for p in store.list_products(status=request.args.get("status") or None)]})

    @app.post("/api/products/import")
    def import_product():
        data = body()
        url = (data.get("url") or "").strip()
        if not pipeline.valid_url(url):
            raise APIError("http(s) URL 을 입력하세요")
        capture = bool(data.get("capture", True))
        return submit("import_url", {"url": url}, lambda job, progress: {"product": ser_product(pipeline.bind(progress).import_url(url, capture=capture))})

    @app.post("/api/products/manual")
    def manual_product():
        data = body()
        if isinstance(data.get("features"), str):
            data["features"] = [f.strip() for f in data["features"].splitlines() if f.strip()]
        for key in ("price", "original_price"):
            if data.get(key) in ("", None):
                data[key] = None
            elif key in data:
                data[key] = int(str(data[key]).replace(",", ""))
        return jsonify({"product": ser_product(pipeline.add_manual_product(data))}), 201

    @app.get("/api/products/<pid>")
    def product(pid: str):
        p = require_product(pid)
        contents = [ser_content(c) for c in store.list_contents(product_id=pid)]
        videos = [ser_video(v) for v in store.list_videos(product_id=pid)]
        links = [l.to_dict() for l in store.list_links(pid)]
        return jsonify({"product": ser_product(p), "contents": contents, "videos": videos, "links": links, "channel_links": channel_links(p, p.best_link), "link_in_bio": link_in_bio(p, p.best_link) if p.best_link else ""})

    @app.put("/api/products/<pid>")
    def update_product(pid: str):
        p = require_product(pid)
        data = body()
        editable = ("name", "brand", "category", "price", "original_price", "commission_rate", "commission_note", "description", "features", "specs", "affiliate_url", "product_url", "status", "notes")
        for key in editable:
            if key not in data:
                continue
            val = data[key]
            if key in ("price", "original_price"):
                val = int(str(val).replace(",", "")) if val not in ("", None) else None
            elif key == "commission_rate":
                val = float(val) if val not in ("", None) else None
            elif key == "features" and isinstance(val, str):
                val = [f.strip() for f in val.splitlines() if f.strip()]
            setattr(p, key, val)
        if p.price and p.original_price and p.original_price > p.price:
            p.discount_rate = round((1 - p.price / p.original_price) * 100, 1)
        store.save_product(p)
        return jsonify({"product": ser_product(p)})

    @app.delete("/api/products/<pid>")
    def delete_product(pid: str):
        require_product(pid)
        pipeline.delete_product(pid)
        return jsonify({"ok": True})

    @app.post("/api/products/<pid>/keywords")
    def refresh_keywords(pid: str):
        p = require_product(pid)
        ks = pipeline.keywords_for(p, refresh=True)
        return jsonify({"keywords": ks.to_dict()})

    @app.post("/api/products/<pid>/blog")
    def gen_blog(pid: str):
        require_product(pid)
        data = body()
        tone = data.get("tone") or None
        length = int(data["length"]) if data.get("length") else None
        return submit("blog", {"product_id": pid}, lambda job, progress: {"content": ser_content(pipeline.bind(progress).generate_blog(pid, tone=tone, length=length))})

    @app.post("/api/products/<pid>/script")
    def gen_script(pid: str):
        require_product(pid)
        data = body()
        fmt = data.get("format") or "shorts"
        duration = int(data["duration"]) if data.get("duration") else None
        return submit("script", {"product_id": pid, "format": fmt}, lambda job, progress: {"content": ser_content(pipeline.bind(progress).generate_script(pid, fmt=fmt, duration=duration))})

    @app.post("/api/products/<pid>/video")
    def gen_video(pid: str):
        require_product(pid)
        data = body()
        script_id = data.get("script_id") or None
        bgm = data.get("bgm") or None
        voice = data.get("voice") or None
        kenburns = bool(data.get("kenburns", True))
        fmt = data.get("format") or "shorts"
        return submit("video", {"product_id": pid, "script_id": script_id}, lambda job, progress: {"video": ser_video(pipeline.bind(progress).render_video(pid, script_id=script_id, bgm=bgm, voice=voice, kenburns=kenburns, fmt=fmt))})

    @app.post("/api/products/<pid>/package")
    def gen_package(pid: str):
        require_product(pid)
        return submit("package", {"product_id": pid}, lambda job, progress: pipeline.bind(progress).export_package(pid))

    @app.post("/api/pipeline/run")
    def run_pipeline():
        data = body()
        url = (data.get("url") or "").strip() or None
        pid = data.get("product_id") or None
        cid = data.get("campaign_id") or None
        if not (url or pid or cid):
            raise APIError("url / product_id / campaign_id 중 하나가 필요합니다")
        if url and not pipeline.valid_url(url):
            raise APIError("http(s) URL 을 입력하세요")
        kwargs = {
            "fmt": data.get("format") or "shorts",
            "with_blog": bool(data.get("with_blog", True)),
            "with_video": bool(data.get("with_video", True)),
            "with_package": bool(data.get("with_package", True)),
        }
        return submit("pipeline", data, lambda job, progress: pipeline.bind(progress).run_full(url=url, product_id=pid, campaign_id=cid, **kwargs))

    # ------------------------------------------------------------------ contents
    @app.get("/api/contents")
    def contents():
        items = store.list_contents(product_id=request.args.get("product_id") or None, kind=request.args.get("kind") or None)
        return jsonify({"contents": [ser_content(c) for c in items]})

    @app.get("/api/contents/<cid>")
    def content(cid: str):
        c = store.get_content(cid)
        if not c:
            raise APIError("콘텐츠를 찾을 수 없습니다", 404)
        return jsonify({"content": ser_content(c)})

    @app.put("/api/contents/<cid>")
    def update_content(cid: str):
        c = store.get_content(cid)
        if not c:
            raise APIError("콘텐츠를 찾을 수 없습니다", 404)
        data = body()
        if isinstance(c, BlogPost):
            for key in ("title", "markdown", "meta_description", "status"):
                if key in data:
                    setattr(c, key, data[key])
            if "hashtags" in data:
                c.hashtags = [t.strip() for t in (data["hashtags"] if isinstance(data["hashtags"], list) else str(data["hashtags"]).split()) if t.strip()]
            c = pipeline.blog_writer.rescore(c)
        else:
            for key in ("title", "hook", "cta", "description", "status"):
                if key in data:
                    setattr(c, key, data[key])
            if isinstance(data.get("scenes"), list):
                c.scenes = data["scenes"]
                c.duration = round(sum(float(s.get("duration", 0) or 0) for s in c.scenes), 2)
            if "hashtags" in data:
                c.hashtags = [t.strip() for t in (data["hashtags"] if isinstance(data["hashtags"], list) else str(data["hashtags"]).split()) if t.strip()]
        store.save_content(c)
        return jsonify({"content": ser_content(c)})

    @app.delete("/api/contents/<cid>")
    def delete_content(cid: str):
        store.delete_content(cid)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ videos
    @app.get("/api/videos")
    def videos():
        return jsonify({"videos": [ser_video(v) for v in store.list_videos(product_id=request.args.get("product_id") or None)]})

    @app.get("/api/videos/<vid>")
    def video(vid: str):
        v = store.get_video(vid)
        if not v:
            raise APIError("영상을 찾을 수 없습니다", 404)
        return jsonify({"video": ser_video(v)})

    @app.delete("/api/videos/<vid>")
    def delete_video(vid: str):
        store.delete_video(vid)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ jobs
    @app.get("/api/jobs")
    def jobs():
        return jsonify({"jobs": [j.to_dict() for j in store.list_jobs(limit=int(request.args.get("limit", 30)))]})

    @app.get("/api/jobs/<jid>")
    def job(jid: str):
        j = store.get_job(jid)
        if not j:
            raise APIError("작업을 찾을 수 없습니다", 404)
        return jsonify({"job": j.to_dict()})

    @app.post("/api/jobs/<jid>/cancel")
    def cancel_job(jid: str):
        return jsonify({"ok": runner.cancel(jid)})

    # ------------------------------------------------------------------ earnings / links
    @app.get("/api/earnings")
    def earnings():
        return jsonify({"earnings": [e.to_dict() for e in store.list_earnings(product_id=request.args.get("product_id") or None)]})

    @app.post("/api/earnings")
    def add_earning():
        data = body()
        entry = EarningsEntry(
            date=str(data.get("date") or "")[:10],
            product_id=data.get("product_id") or "",
            content_id=data.get("content_id") or "",
            channel=data.get("channel") or "other",
            clicks=int(data.get("clicks") or 0),
            orders=int(data.get("orders") or 0),
            revenue=int(str(data.get("revenue") or 0).replace(",", "")),
            commission=int(str(data.get("commission") or 0).replace(",", "")),
            note=str(data.get("note") or "")[:200],
        )
        if not entry.date:
            raise APIError("날짜가 필요합니다")
        store.add_earning(entry)
        return jsonify({"entry": entry.to_dict()}), 201

    @app.delete("/api/earnings/<eid>")
    def delete_earning(eid: str):
        store.delete_earning(eid)
        return jsonify({"ok": True})

    @app.post("/api/earnings/import")
    def import_earnings():
        text = body().get("csv") or ""
        lookup = {p.name.lower(): p.id for p in store.list_products()}
        entries = parse_settlement_csv(text, lookup)
        for e in entries:
            store.add_earning(e)
        return jsonify({"imported": len(entries), "entries": [e.to_dict() for e in entries]})

    @app.get("/api/earnings/summary")
    def earnings_summary_api():
        names = {p.id: p.name for p in store.list_products()}
        summary = earnings_summary(store.list_earnings(), names)
        summary["counts"] = store.counts()
        return jsonify(summary)

    @app.post("/api/calculator")
    def calculator():
        data = body()
        return jsonify(revenue_calculator(
            int(str(data.get("price") or 0).replace(",", "")), float(data.get("commission_rate") or 0),
            monthly_visits=int(data.get("visits") or 3000), ctr=float(data.get("ctr") or 0.06), cvr=float(data.get("cvr") or 0.025),
        ))

    @app.get("/api/links")
    def links():
        return jsonify({"links": [l.to_dict() for l in store.list_links(request.args.get("product_id") or None)]})

    @app.post("/api/links")
    def add_link():
        data = body()
        if not data.get("url"):
            raise APIError("url 이 필요합니다")
        link = AffiliateLink(product_id=data.get("product_id") or "", network=data.get("network") or "brandconnect", url=data["url"], label=data.get("label") or "", channel=data.get("channel") or "")
        store.add_link(link)
        if link.product_id:
            p = store.get_product(link.product_id)
            if p and not p.affiliate_url:
                p.affiliate_url = link.url
                store.save_product(p)
        return jsonify({"link": link.to_dict()}), 201

    @app.delete("/api/links/<lid>")
    def delete_link(lid: str):
        store.delete_link(lid)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ packages / keywords
    @app.get("/api/packages")
    def packages():
        return jsonify({"packages": list_packages(settings)})

    @app.post("/api/keywords/research")
    def keyword_research():
        data = body()
        name = (data.get("query") or "").strip()
        if not name:
            raise APIError("query 가 필요합니다")
        pseudo = Product(name=name, brand=data.get("brand") or "", category=data.get("category") or "")
        ks = derive_keywords(pseudo)
        s = settings
        if s.naver_searchad_api_key and s.naver_searchad_secret and s.naver_searchad_customer_id:
            from studio.content.keywords import NaverKeywordTool, enrich_with_volumes

            ks = enrich_with_volumes(ks, NaverKeywordTool(s.naver_searchad_api_key, s.naver_searchad_secret, s.naver_searchad_customer_id))
        return jsonify({"keywords": ks.to_dict()})

    return app
