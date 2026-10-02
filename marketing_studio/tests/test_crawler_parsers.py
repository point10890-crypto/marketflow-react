import json

from conftest import fixture_html

from studio.crawler.brand_connect import (
    classify_campaign_type,
    discover_campaign_list_urls,
    extract_commission_rate,
    load_selectors,
    parse_campaign_detail,
    parse_campaign_list,
)
from studio.crawler.probe import probe_html
from studio.crawler.product_page import classify_source, clean_product_name, extract_product, find_preloaded_state

BASE = "https://brandconnect.naver.com/creator/campaign"


def test_parse_campaign_list():
    camps = parse_campaign_list(fixture_html("brandconnect_list.html"), BASE)
    assert [c.title for c in camps] == ["프리미엄 무선 청소기 X1 체험단 모집", "비타민C 3000 데일리 리뷰", "초경량 캠핑 의자 원고료 캠페인"]
    first = camps[0]
    assert first.url == "https://brandconnect.naver.com/creator/campaign/10001"
    assert first.brand == "클린테크" and first.campaign_type == "커미션"
    assert first.reward.startswith("수수료 12%") and first.period == "2026-09-01 ~ 2026-09-20"
    assert first.thumbnail.startswith("https://shop-phinf")
    assert camps[1].campaign_type == "체험단" and camps[1].thumbnail.endswith("cmp_10002.jpg")
    assert camps[2].campaign_type == "원고료"


def test_parse_campaign_list_heuristic_without_selectors():
    html = """<html><body><div><a href="/creator/campaign/1"><img alt="상품A"><span>상품A 체험단</span></a></div>
    <div><a href="/creator/campaign/2"><span>상품B 커미션 10%</span></a></div><a href="/mypage">마이페이지</a></body></html>"""
    selectors = load_selectors()
    selectors["list"]["item"] = ["nav li"]  # 매칭 안 되는 셀렉터 → 휴리스틱 경로
    camps = parse_campaign_list(html, BASE, selectors)
    assert len(camps) == 2
    assert camps[1].campaign_type == "커미션"


def test_discover_and_classify():
    urls = discover_campaign_list_urls(fixture_html("brandconnect_list.html"), "https://brandconnect.naver.com/")
    assert urls[0] == "https://brandconnect.naver.com/creator/campaign"
    assert classify_campaign_type("판매 수익 쉐어") == "커미션"
    assert classify_campaign_type("제품 제공 체험단") == "체험단"
    assert classify_campaign_type("") == ""
    assert extract_commission_rate("판매 수수료 12% + 제품 제공") == 12.0
    assert extract_commission_rate("15% 커미션") == 15.0


def test_parse_campaign_detail():
    d = parse_campaign_detail(fixture_html("brandconnect_detail.html"), "https://brandconnect.naver.com/creator/campaign/10001")
    assert d["name"] == "프리미엄 무선 청소기 X1 체험단 모집"
    assert d["brand"] == "클린테크" and d["commission_rate"] == 12.0
    assert d["product_url"] == "https://smartstore.naver.com/cleantech/products/123456"
    assert d["price"] == 299000 and d["original_price"] == 359000
    assert len(d["image_urls"]) == 4 and all("icon" not in u for u in d["image_urls"])
    assert d["campaign"]["period"] == "2026-09-01 ~ 2026-09-20" and d["campaign"]["campaign_type"] == "커미션"
    assert "블로그 포스팅 1건" in d["campaign"]["mission"]
    assert d["features"][0].startswith("최대 흡입력") and not any("수수료" in f for f in d["features"])


def test_selectors_override(tmp_path):
    override = tmp_path / "o.json"
    override.write_text(json.dumps({"list": {"item": ["ul.x > li"]}}), encoding="utf-8")
    sel = load_selectors(override)
    assert sel["list"]["item"] == ["ul.x > li"]
    assert sel["detail"]["title"]  # 나머지는 기본값 유지


def test_extract_smartstore():
    d = extract_product(fixture_html("smartstore_product.html"), "https://smartstore.naver.com/cleantech/products/123456")
    assert d["name"] == "클린테크 무선 청소기 X1" and d["brand"] == "클린테크"
    assert d["price"] == 299000 and d["original_price"] == 359000 and d["discount_rate"] == 16.7
    assert d["category"].endswith("무선청소기") and d["specs"]["흡입력"] == "210W"
    assert d["source"] == "smartstore" and "preloaded_state" in d["raw"]["extractors"]
    assert len(d["image_urls"]) == 5 and not any("icon" in u for u in d["image_urls"])
    assert "클린테크 무선 청소기 X1" not in d["features"]


def test_extract_generic_jsonld():
    d = extract_product(fixture_html("generic_product.html"), "https://healthlab.example/products/vitc3000")
    assert d["name"] == "헬스랩 비타민C 3000 (30포)" and d["brand"] == "헬스랩"
    assert d["price"] == 29900 and d["original_price"] == 39900
    assert d["specs"] == {"용량": "3g x 30포", "원산지": "대한민국"}
    assert d["image_urls"][1].startswith("https://cdn.healthlab.example")
    assert "jsonld" in d["raw"]["extractors"] and d["source"] == "url"
    assert not any("정가" in f for f in d["features"])


def test_preloaded_state_and_helpers():
    state = find_preloaded_state('<script>window.__PRELOADED_STATE__={"a":{"b":"x}y"}};</script>')
    assert state == {"a": {"b": "x}y"}}
    assert find_preloaded_state("<html></html>") is None
    assert classify_source("https://brandconnect.naver.com/x") == "brandconnect"
    assert classify_source("https://www.coupang.com/vp/products/1") == "coupang"
    assert clean_product_name("무선 청소기 : 클린테크 - 네이버 스마트스토어") == "무선 청소기"


def test_probe_html():
    r = probe_html(fixture_html("brandconnect_list.html"), BASE)
    assert r["campaign_link_count"] >= 4
    assert r["repeated_containers"] and r["repeated_containers"][0]["count"] == 3
    assert r["login_marker"] is False
    r2 = probe_html(fixture_html("smartstore_product.html"), "https://smartstore.naver.com/x")
    assert r2["preloaded_state_keys"] == ["product", "channel"]
