"""CLI — python -m studio <command>."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from studio import __version__
from studio.config import get_settings
from studio.db import Store


def _pipeline():
    from studio.pipeline import Pipeline

    settings = get_settings()
    settings.ensure_dirs()
    store = Store(settings.db_path)
    return settings, store, Pipeline(settings, store)


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_serve(args: argparse.Namespace) -> int:
    from studio.web.app import create_app

    settings = get_settings()
    app = create_app()
    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://{host}:{port}"
    print(f"Marketing Studio v{__version__} → {url}")
    if args.open:
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    report = pipeline.doctor(check_login=args.login)
    _print(report)
    return 0 if report["ok"] else 1


def cmd_login(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    ok = pipeline.login(wait_seconds=args.wait)
    print("로그인 성공 — 세션이 data/browser_profile 에 저장되었습니다." if ok else "로그인 확인 실패")
    return 0 if ok else 1


def cmd_crawl(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    _print(pipeline.crawl_brand_connect(max_pages=args.pages, limit=args.limit, detail_limit=args.details))
    return 0


def cmd_campaigns(args: argparse.Namespace) -> int:
    _, store, _ = _pipeline()
    for c in store.list_campaigns():
        print(f"{c.id}  [{c.campaign_type or '-'}] {c.title}  | {c.brand} | {c.reward} | {c.period} | product={c.product_id or '-'}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    product = pipeline.import_url(args.url, capture=not args.no_capture)
    _print({k: v for k, v in product.to_dict().items() if k not in ("raw", "description")})
    return 0


def cmd_products(args: argparse.Namespace) -> int:
    _, store, _ = _pipeline()
    for p in store.list_products():
        price = f"{p.price:,}원" if p.price else "-"
        print(f"{p.id}  {p.name}  | {p.brand} | {price} | {p.status} | media={len(p.media)}")
    return 0


def cmd_blog(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    post = pipeline.generate_blog(args.product_id, tone=args.tone, length=args.length)
    print(f"{post.id}  SEO {post.seo_score}/100  {post.char_count:,}자  provider={post.provider}\n제목: {post.title}")
    return 0


def cmd_script(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    script = pipeline.generate_script(args.product_id, fmt=args.format, duration=args.duration)
    print(f"{script.id}  {script.format}  {script.duration:.0f}s  {len(script.scenes)}장면\n제목: {script.title}")
    for s in script.scene_objects():
        print(f"  #{s.index + 1} [{s.kind}] {s.duration:.1f}s  {s.caption}  — {s.narration}")
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    video = pipeline.render_video(args.product_id, script_id=args.script, bgm=args.bgm, voice=args.voice, kenburns=not args.no_kenburns)
    print(f"{video.id}  {video.path}  {video.duration:.1f}s  tts={video.tts_engine}")
    return 0


def cmd_package(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    _print(pipeline.export_package(args.product_id))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    _, store, pipeline = _pipeline()
    target = args.target
    kwargs = {"fmt": args.format, "with_video": not args.no_video, "with_package": not args.no_package}
    if target.startswith("http"):
        result = pipeline.run_full(url=target, **kwargs)
    elif store.get_product(target):
        result = pipeline.run_full(product_id=target, **kwargs)
    elif store.get_campaign(target):
        result = pipeline.run_full(campaign_id=target, **kwargs)
    else:
        print("URL / 상품 ID / 캠페인 ID 를 입력하세요")
        return 2
    _print(result)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    _, _, pipeline = _pipeline()
    _print(pipeline.probe(args.url))
    return 0


def cmd_earnings(args: argparse.Namespace) -> int:
    from studio.monetize import earnings_summary, parse_settlement_csv

    _, store, _ = _pipeline()
    if args.import_csv:
        text = Path(args.import_csv).read_text(encoding="utf-8-sig")
        lookup = {p.name.lower(): p.id for p in store.list_products()}
        entries = parse_settlement_csv(text, lookup)
        for e in entries:
            store.add_earning(e)
        print(f"{len(entries)}건 가져옴")
    names = {p.id: p.name for p in store.list_products()}
    _print(earnings_summary(store.list_earnings(), names))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio", description="Marketing Studio — 브랜드커넥트 수집 → SEO 블로그 → 영상 → 발행 패키지")
    parser.add_argument("--version", action="version", version=f"studio {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="웹 스튜디오 실행")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--open", action="store_true", help="브라우저 자동 열기")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("doctor", help="환경 진단 (ffmpeg/폰트/LLM/브라우저)")
    p.add_argument("--login", action="store_true", help="네이버 로그인 상태까지 확인")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("login", help="네이버 로그인 창 열기 (세션 저장)")
    p.add_argument("--wait", type=int, default=600)
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("crawl", help="브랜드커넥트 캠페인 목록 수집")
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--details", type=int, default=0, help="상세까지 가져올 캠페인 수")
    p.set_defaults(func=cmd_crawl)

    sub.add_parser("campaigns", help="수집된 캠페인 목록").set_defaults(func=cmd_campaigns)

    p = sub.add_parser("import", help="URL 에서 상품 가져오기 (스마트스토어/브랜드커넥트/일반)")
    p.add_argument("url")
    p.add_argument("--no-capture", action="store_true")
    p.set_defaults(func=cmd_import)

    sub.add_parser("products", help="상품 목록").set_defaults(func=cmd_products)

    p = sub.add_parser("blog", help="SEO 블로그 생성")
    p.add_argument("product_id")
    p.add_argument("--tone")
    p.add_argument("--length", type=int)
    p.set_defaults(func=cmd_blog)

    p = sub.add_parser("script", help="영상 대본 생성")
    p.add_argument("product_id")
    p.add_argument("--format", choices=["shorts", "review"], default="shorts")
    p.add_argument("--duration", type=int)
    p.set_defaults(func=cmd_script)

    p = sub.add_parser("video", help="영상 제작")
    p.add_argument("product_id")
    p.add_argument("--script")
    p.add_argument("--bgm")
    p.add_argument("--voice")
    p.add_argument("--no-kenburns", action="store_true")
    p.set_defaults(func=cmd_video)

    p = sub.add_parser("package", help="발행 패키지 생성")
    p.add_argument("product_id")
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("run", help="전체 파이프라인 (URL | 상품ID | 캠페인ID)")
    p.add_argument("target")
    p.add_argument("--format", choices=["shorts", "review"], default="shorts")
    p.add_argument("--no-video", action="store_true")
    p.add_argument("--no-package", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("probe", help="페이지 DOM 구조 리포트 (셀렉터 튜닝)")
    p.add_argument("url")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("earnings", help="수익 요약 / 정산 CSV 가져오기")
    p.add_argument("--import-csv", dest="import_csv")
    p.set_defaults(func=cmd_earnings)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"오류: {e}", file=sys.stderr)
        if args.verbose:
            raise
        return 1
