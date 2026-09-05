"""LLM 프롬프트 — 블로그(JSON) / 영상 대본(JSON)."""

from __future__ import annotations

BLOG_SYSTEM = (
    "당신은 네이버 블로그 상위노출 경험이 많은 한국어 제휴 마케팅 콘텐츠 작가입니다. "
    "과장·허위 없이, 실제 사용 상황이 떠오르는 구체적인 문장으로 씁니다. "
    "숫자·스펙은 제공된 정보만 사용하고, 없는 정보는 지어내지 않습니다. "
    "반드시 요청한 JSON 스키마로만 응답합니다."
)

BLOG_USER = """다음 상품으로 네이버 블로그 SEO 최적화 포스팅을 작성하세요.

[상품 정보]
{product_summary}

[키워드]
- 핵심 키워드(제목 앞부분·첫 문단·소제목 1개 이상에 그대로 포함): {primary}
- 보조 키워드(본문에 자연스럽게 2~3개 사용): {secondary}
- 롱테일: {longtail}

[작성 규칙]
- 톤: {tone}
- 본문 총 {target_length}자 이상 (공백 제외). 섹션 5~6개, 각 섹션 250~400자.
- 제목은 15~40자, 핵심 키워드로 시작하고 클릭을 부르는 구체적 이점 포함.
- 소제목(heading)은 검색 의도형으로: "OO 장단점", "OO 이런 분께 추천", "OO 가격/할인 정보" 등.
- 첫 문단(intro)은 150자 안에 핵심 키워드를 포함하고 독자의 고민을 짚습니다.
- 장점 3~5개, 아쉬운 점 1~2개(솔직함이 신뢰를 만듭니다).
- FAQ 3개 (검색창에 실제 칠 법한 질문).
- 이모지는 섹션당 최대 1개. 과장 광고 표현(최고, 1위, 무조건) 금지.
- image_hint 는 hero / detail / price / mobile / image 중 하나로, 그 섹션에 어울리는 이미지 종류.

[출력 JSON 스키마]
{{
  "title": "제목",
  "meta_description": "80~140자 요약 (핵심 키워드 포함)",
  "intro": "첫 문단",
  "sections": [{{"heading": "소제목", "body": "본문 (마크다운, 줄바꿈 가능, 목록은 '- ')", "image_hint": "hero"}}],
  "pros": ["장점"],
  "cons": ["아쉬운 점"],
  "faq": [{{"q": "질문", "a": "답변"}}],
  "conclusion": "마무리 문단 (구매 링크 유도 문장 포함, 링크 자체는 쓰지 말 것)",
  "hashtags": ["#태그"]
}}"""

BLOG_REVISE = """아래 블로그 포스팅 JSON 을 SEO 점검 결과에 맞게 수정하세요. 구조(JSON 스키마)는 그대로 유지하고 내용만 보강합니다.

[SEO 점검 제안]
{suggestions}

[핵심 키워드] {primary}

[현재 JSON]
{current}

수정된 전체 JSON 만 출력하세요."""

SCRIPT_SYSTEM = (
    "당신은 조회수가 잘 나오는 한국어 숏폼(쇼츠/클립/릴스) 대본 작가입니다. "
    "첫 3초 훅으로 시선을 잡고, 한 장면에 한 메시지만 담으며, 구어체로 짧게 씁니다. "
    "숫자·스펙은 제공된 정보만 사용합니다. 반드시 요청한 JSON 으로만 응답합니다."
)

SCRIPT_USER = """다음 상품의 {format_label} 영상 대본을 작성하세요.

[상품 정보]
{product_summary}

[핵심 키워드] {primary}
[참고 블로그 요약] {blog_summary}

[규칙]
- 총 길이 약 {target_duration}초, 장면 {scene_count}개.
- 각 장면: narration(내레이션, 구어체 1~2문장, 장면당 {max_chars}자 이내), caption(화면 자막 12자 이내, 핵심만), visual_hint(hero/detail/price/mobile/image 중 하나), kind(hook/body/feature/offer/cta).
- 첫 장면은 hook: 궁금증/공감 유발 한 문장. 마지막 장면은 cta: "링크는 프로필/댓글 확인" 유도.
- 가격/할인 정보가 있으면 offer 장면에 포함. 과장(최고, 1위, 무조건) 금지.
- description 은 유튜브/클립 설명란용 2~3문장 + 핵심 키워드 포함.

[출력 JSON 스키마]
{{
  "title": "영상 제목 (30자 이내, 핵심 키워드 포함)",
  "hook": "훅 문장",
  "scenes": [{{"narration": "...", "caption": "...", "visual_hint": "hero", "kind": "hook"}}],
  "cta": "마지막 유도 문장",
  "description": "설명란 텍스트",
  "hashtags": ["#태그"]
}}"""
