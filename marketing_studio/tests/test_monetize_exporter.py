from pathlib import Path

from studio.content.blog_writer import BlogWriter
from studio.content.keywords import derive_keywords
from studio.content.script_writer import ScriptWriter
from studio.exporter import build_publish_package, list_packages
from studio.models import EarningsEntry, Product, VideoAsset
from studio.monetize import channel_links, earnings_summary, link_in_bio, parse_settlement_csv, revenue_calculator, with_utm


def test_with_utm_and_channel_links():
    url = with_utm("https://smartstore.naver.com/a/products/1?NaPm=x", source="naver_blog", campaign="무선 청소기 X1")
    assert "NaPm=x" in url and "utm_source=naver_blog" in url and "utm_campaign=" in url
    p = Product(name="x")
    assert channel_links(p, "https://brandconnect.naver.com/l/abc")["youtube"] == "https://brandconnect.naver.com/l/abc"
    assert "utm_source=youtube" in channel_links(p, "https://shop.example/p")["youtube"]
    assert channel_links(p, "") == {}
    text = link_in_bio(Product(name="상품", price=1000, original_price=2000), "https://l")
    assert "🛒 상품" in text and "정가 2,000원" in text and "https://l" in text


def test_parse_settlement_csv_and_summary():
    csv_text = "정산일,캠페인명,채널,클릭수,주문수,판매금액,정산금액\n2026-09-01,클린테크 무선 청소기 X1,블로그,120,3,\"897,000\",\"107,640\"\n2026.09.02,비타민C,클립,40,1,29900,2990\n\n"
    entries = parse_settlement_csv(csv_text, {"클린테크 무선 청소기 x1": "p1"})
    assert len(entries) == 2
    assert entries[0].product_id == "p1" and entries[0].channel == "naver_blog" and entries[0].commission == 107640
    assert entries[1].date == "2026-09-02" and entries[1].channel == "naver_clip"
    tsv = "date\tclicks\tcommission\n2026-08-01\t10\t500\n"
    assert parse_settlement_csv(tsv)[0].commission == 500
    assert parse_settlement_csv("") == []
    summary = earnings_summary(entries, {"p1": "X1"})
    assert summary["totals"]["commission"] == 110630 and summary["conversion_rate"] == 2.5
    assert summary["by_channel"][0]["label"] == "네이버 블로그" and summary["by_product"][0]["name"] == "X1"
    assert summary["by_month"][0]["month"] == "2026-09"
    calc = revenue_calculator(299000, 12, monthly_visits=3000)
    assert calc["expected_commission"] == 161460 and calc["commission_per_order"] == 35880


def test_build_publish_package(settings, store, product_with_media, sample_image):
    p = product_with_media
    ks = derive_keywords(p, year=2026)
    blog = store.save_content(BlogWriter(settings).write(p, ks))
    script = store.save_content(ScriptWriter(settings).write(p, ks))
    video_path = settings.video_dir / "v.mp4"
    video_path.write_bytes(b"0" * 100)
    store.save_video(VideoAsset(product_id=p.id, script_id=script.id, title="영상", path=str(video_path), thumbnail=sample_image, duration=45, metadata={"hashtags": ["#a"], "description": "설명"}))
    manifest = build_publish_package(settings, store, p.id)
    pkg = Path(manifest["dir"])
    for rel in ("blog/post.md", "blog/post.txt", "blog/post.html", "blog/meta.json", "video/script.json", "video/v.mp4", "video/youtube.txt", "video/clip.txt", "links.txt", "CHECKLIST.md", "package.json", "images/hero.png"):
        assert (pkg / rel).exists(), rel
    md = (pkg / "blog/post.md").read_text(encoding="utf-8")
    assert "](../images/hero.png)" in md
    assert "https://brandconnect.naver.com/l/abc" in (pkg / "links.txt").read_text(encoding="utf-8")
    assert "#광고" in (pkg / "video/youtube.txt").read_text(encoding="utf-8")
    assert store.get_product(p.id).status == "packaged"
    assert list_packages(settings)[0]["product_id"] == p.id
