from studio.db import Store
from studio.models import BlogPost, Campaign, EarningsEntry, Job, Product, VideoAsset, VideoScript
from studio.utils import j, josa, parse_percent, parse_period, parse_price, resolve_under, slugify


def test_slugify_korean():
    assert slugify("클린테크 무선 청소기 X1 (특가!)") == "클린테크-무선-청소기-x1-특가"
    assert slugify("!!!") == "item"


def test_parse_price_and_percent():
    assert parse_price("판매가 299,000원") == 299000
    assert parse_price("₩12,900") == 12900
    assert parse_price("가격 미정") is None
    assert parse_percent("수수료 12.5%") == 12.5
    assert parse_percent("없음") is None


def test_parse_period():
    assert parse_period("모집기간 2026.09.01 ~ 2026.09.20") == "2026-09-01 ~ 2026-09-20"
    assert parse_period("2026년 9월 3일") == "2026-09-03"
    assert parse_period("9.05 ~ 9.25").endswith("-09-05 ~ 2026-09-25") or "~" in parse_period("9.05 ~ 9.25")


def test_josa():
    assert j("청소기", "은는") == "청소기는"
    assert j("X1", "은는") == "X1은"
    assert j("비타민C", "이가") == "비타민C가"
    assert josa("서울", "으로", "로") == "로"
    assert josa("부산", "으로", "로") == "으로"


def test_resolve_under(tmp_path):
    assert resolve_under(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()
    assert resolve_under(tmp_path, "../etc/passwd") is None


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "s.db")
    p = store.save_product(Product(name="상품", price=1000, features=["a"]))
    assert store.get_product(p.id).features == ["a"]
    assert store.find_product_by_url("x") is None
    p.source_url = "https://x/1"
    store.save_product(p)
    assert store.find_product_by_url("https://x/1").id == p.id
    b = store.save_content(BlogPost(product_id=p.id, title="b", seo_score=80))
    s = store.save_content(VideoScript(product_id=p.id, title="s", scenes=[{"index": 0}]))
    assert isinstance(store.get_content(b.id), BlogPost)
    assert isinstance(store.get_content(s.id), VideoScript)
    assert store.latest_content(p.id, "script").id == s.id
    store.save_video(VideoAsset(product_id=p.id, path="/x.mp4"))
    assert len(store.list_videos(p.id)) == 1
    assert store.save_campaigns([Campaign(title="c", url="https://c/1"), Campaign(title="c2", url="https://c/1")]) == 2
    assert len(store.list_campaigns()) == 1
    store.add_earning(EarningsEntry(date="2026-09-01", product_id=p.id, channel="naver_blog", clicks=5, commission=100))
    assert store.list_earnings(p.id)[0].commission == 100
    job = store.save_job(Job(type="x", status="running"))
    assert store.mark_stale_jobs_failed() == 1
    assert store.get_job(job.id).status == "failed"
    store.set_setting("runtime", {"blog_tone": "t"})
    assert store.get_setting("runtime")["blog_tone"] == "t"
    counts = store.counts()
    assert counts["products"] == 1 and counts["blogs"] == 1 and counts["scripts"] == 1
    store.delete_product(p.id)
    assert store.get_product(p.id) is None and store.list_contents(p.id) == []
    store.close()
