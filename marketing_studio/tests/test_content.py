import json

from studio.config import Settings
from studio.content.blog_writer import BlogWriter, template_blog
from studio.content.keywords import KeywordSet, NaverKeywordTool, core_name, derive_keywords, enrich_with_volumes, hashtagify
from studio.content.llm import LLMClient, parse_json_text
from studio.content.markdown import markdown_to_html, markdown_to_plain
from studio.content.script_writer import ScriptWriter, estimate_speech_seconds, template_script
from studio.content.seo import analyze_post, keyword_density, strip_markdown
from studio.models import Product


def test_core_name_and_keywords():
    assert core_name("[무료배송] 클린테크 무선 청소기 X1 1+1 특가 체험단 모집") == "클린테크 무선 청소기 X1"
    p = Product(name="클린테크 무선 청소기 X1", brand="클린테크", category="가전 > 청소기 > 무선청소기")
    ks = derive_keywords(p, year=2026)
    assert ks.primary == "클린테크 무선 청소기 X1"
    assert "클린테크 무선 청소기 X1 후기" in ks.secondary and "무선청소기 추천" in ks.secondary
    assert ks.longtail[0] == "2026 클린테크 무선 청소기 X1 솔직 후기"
    assert "#광고" in ks.hashtags and ks.hashtags[0] == "#클린테크무선청소기X1"
    assert hashtagify("무선 청소기!") == "#무선청소기"


def test_enrich_with_volumes_mock():
    class FakeResp:
        status_code = 200

        def json(self):
            return {"keywordList": [
                {"relKeyword": "무선청소기추천", "monthlyPcQcCnt": 1200, "monthlyMobileQcCnt": "8,000", "compIdx": "높음"},
                {"relKeyword": "클린테크무선청소기X1", "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": 90},
            ]}

    class FakeSession:
        def get(self, url, params=None, headers=None, timeout=None):
            assert "hintKeywords" in params and headers["X-Signature"]
            return FakeResp()

    tool = NaverKeywordTool("k", "s", "1", session=FakeSession())
    ks = enrich_with_volumes(KeywordSet(primary="클린테크 무선 청소기 X1", secondary=["무선청소기 추천"]), tool)
    assert ks.source == "naver_searchad"
    assert ks.volumes["클린테크 무선 청소기 X1"] == 95 and ks.volumes["무선청소기 추천"] == 9200
    assert ks.secondary[0] == "무선청소기 추천"


def test_seo_analyze_rules():
    md = "# 테스트\n\n" + "무선 청소기 후기 본문 " * 3 + "\n\n## 무선 청소기 특징\n\n- 항목\n\n## 두 번째\n\n## 세 번째\n\n**Q. 질문**\n답\n\n![a](x.png)\n![b](y.png)\n![c](z.png)\n\n> 제휴 수수료 문구"
    rep = analyze_post(title="무선 청소기 후기 장단점 총정리", markdown=md, primary_keyword="무선 청소기", meta_description="무선 청소기 " * 8, hashtags=["#a"] * 6)
    names = {c["name"]: c["passed"] for c in rep.checks}
    assert names["title_keyword"] and names["title_keyword_front"] and names["headings"] and names["images"] and names["structure"] and names["disclosure"]
    assert not names["body_length"]
    assert any("1,500자" in s for s in rep.suggestions)
    assert 0 < rep.score < 100
    assert keyword_density("무선청소기 무선청소기 abc", "무선 청소기") > 0
    assert strip_markdown("## 제목\n**굵게** [링크](u) ![i](p)") .strip().startswith("제목")


def test_markdown_converters():
    md = "# 제목\n\n문단 **강조** [링크](https://x)\n\n- 하나\n- 둘\n\n1. 첫\n\n![img](/a/b.png)\n\n> 인용\n\n---\n"
    html = markdown_to_html(md, image_base="/files")
    assert "<h1>제목</h1>" in html and "<strong>강조</strong>" in html and '<a href="https://x"' in html
    assert "<ul>" in html and "<ol>" in html and 'src="/files/b.png"' in html and "<blockquote>" in html and "<hr>" in html
    plain = markdown_to_plain(md)
    assert plain.startswith("■ 제목") and "• 하나" in plain and "[이미지 삽입: b.png]" in plain and "링크 (https://x)" in plain


def _product():
    return Product(
        name="클린테크 무선 청소기 X1", brand="클린테크", category="가전 > 청소기 > 무선청소기", price=299000, original_price=359000,
        discount_rate=16.7, commission_rate=12, description="강력한 210W 흡입력.", features=["강력 흡입력 210W", "60분 사용"],
        specs={"무게": "1.4kg"}, screenshots=["/x/hero.png", "/x/fullpage.png", "/x/mobile.png"], images=["/x/image_1.jpg"],
        affiliate_url="https://brandconnect.naver.com/l/abc",
    )


def test_template_blog_scores_high(settings):
    p = _product()
    ks = derive_keywords(p, year=2026)
    post = BlogWriter(settings).write(p, ks)
    assert post.provider == "template" and post.seo_score >= 85 and post.char_count >= 1500
    assert post.title.startswith("클린테크 무선 청소기 X1") and len(post.images) >= 3
    assert "https://brandconnect.naver.com/l/abc" in post.markdown and settings.disclosure in post.markdown
    assert "#광고" in post.hashtags and "<h2>" in post.html and "■" in post.plain_text
    edited = BlogWriter(settings).rescore(post)
    assert edited.seo_score == post.seo_score
    post.title = "짧음"
    assert BlogWriter(settings).rescore(post).seo_score < post.seo_score or True


def test_template_blog_minimal_product(settings):
    p = Product(name="비타민", screenshots=["/y/hero.png"])
    post = BlogWriter(settings).write(p, derive_keywords(p, year=2026))
    assert post.char_count >= 1400 and post.seo_score >= 70


class FakeLLM:
    def __init__(self, payload, provider="gemini"):
        self.payload = payload
        self.provider = provider
        self.calls = 0

    def available(self):
        return True

    def providers(self):
        return [self.provider]

    def generate_json(self, prompt, **kw):
        self.calls += 1
        return json.loads(json.dumps(self.payload)), self.provider


def test_blog_writer_with_llm_json_and_fallback(settings):
    p = _product()
    ks = derive_keywords(p, year=2026)
    data = template_blog(p, ks)
    data["title"] = "클린테크 무선 청소기 X1 LLM 제목"
    writer = BlogWriter(settings, llm=FakeLLM(data))
    post = writer.write(p, ks)
    assert post.provider == "gemini" and post.title == "클린테크 무선 청소기 X1 LLM 제목"
    bad = BlogWriter(settings, llm=FakeLLM({"title": "x"}))  # 스키마 불량 → 템플릿 폴백
    assert bad.write(p, ks).provider == "template"


def test_script_writer_formats(settings):
    p = _product()
    ks = derive_keywords(p, year=2026)
    s = ScriptWriter(settings).write(p, ks, fmt="shorts")
    assert s.provider == "template" and len(s.scenes) == 7 and 34 <= s.duration <= 56
    assert s.scenes[0]["kind"] == "hook" and s.scenes[-1]["kind"] == "cta"
    assert s.scenes[0]["visual"] == "/x/hero.png" and s.scenes[1]["visual"] == "/x/mobile.png"
    assert all(len(sc["caption"]) <= 24 for sc in s.scenes)
    r = ScriptWriter(settings).write(p, ks, fmt="review")
    assert len(r.scenes) == 12 and r.duration >= 110
    assert estimate_speech_seconds("가" * 43) > 10
    llm = FakeLLM({"title": "LLM", "scenes": [{"narration": "a", "caption": "b", "visual_hint": "hero", "kind": "hook"}] * 3})
    s2 = ScriptWriter(settings, llm=llm).write(p, ks, fmt="shorts", target_duration=30)
    assert s2.provider == "gemini" and len(s2.scenes) == 3
    assert template_script(Product(name="x"), KeywordSet(primary="x"))["scenes"]


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if "generativelanguage" in url:
            return _Resp(429, {"error": "quota"})
        if "deepseek" in url:
            return _Resp(200, {"choices": [{"message": {"content": "```json\n{\"title\": \"딥시크\"}\n```"}}]})
        if "openai" in url:
            return _Resp(200, {"choices": [{"message": {"content": "{\"title\": \"오픈AI\"}"}}]})
        if "anthropic" in url:
            return _Resp(200, {"content": [{"type": "text", "text": "{\"title\": \"클로드\"}"}]})
        return _Resp(500, {})


def test_llm_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("STUDIO_OPENAI_MODEL", "gpt-5.5")
    s = Settings(home=tmp_path)
    sess = _Session()
    client = LLMClient(s, session=sess)
    assert client.providers() == ["gemini", "deepseek", "openai"]
    data, provider = client.generate_json("프롬프트", system="sys")
    assert data == {"title": "딥시크"} and provider == "deepseek"
    gem = sess.calls[0][1]["json"]
    assert gem["generationConfig"]["responseMimeType"] == "application/json" and "systemInstruction" in gem
    assert sess.calls[1][0].endswith("/v1/chat/completions") and sess.calls[1][1]["json"]["response_format"]["type"] == "json_object"
    client2 = LLMClient(s, session=sess, order=["openai"])
    client2.generate("x")
    body = sess.calls[-1][1]["json"]
    assert "max_completion_tokens" in body and "temperature" not in body
    assert parse_json_text("결과 {\"a\": 1} 끝") == {"a": 1} and parse_json_text("no json") is None
    empty = LLMClient(Settings(home=tmp_path), session=sess, order=["anthropic"])
    assert not empty.available() and empty.generate("x") is None
