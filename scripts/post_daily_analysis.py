"""
종가베팅 V2 결과 → 커뮤니티 종목분석 게시판 자동 게시 (스케줄용)

스케줄 호출: scheduler.py run_kr_full_update() 말미에서 호출
- data/jongga_v2_latest.json 을 읽어 동적으로 게시글 생성
- 주말·데이터 없음·중복 제목 → skip
- Nano Banana 이미지 4장 생성 (히어로 + 테마 3장)
- 실패해도 예외 전파 안 함 (스케줄러 파이프라인 방어)

Exit codes:
  0  성공
  2  skip (주말/빈 결과/중복)
  1  실패
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

logger = logging.getLogger("post_daily_analysis")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

API_URL = os.environ.get('MARKETFLOW_API', 'http://localhost:5001')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'point10890@gmail.com')
UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'uploads', 'community')
JONGGA_JSON = os.path.join(BASE_DIR, 'data', 'jongga_v2_latest.json')


# ─── Gemini ───────────────────────────────────────────────────
def _get_gemini_client():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.warning("GEMINI_API_KEY missing — image generation skipped")
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.warning(f"Gemini client init failed: {e}")
        return None


def _gen_image(client, prompt: str) -> Optional[bytes]:
    if client is None:
        return None
    try:
        from google.genai import types
        resp = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=prompt + ". No text, no watermark, clean minimal flat illustration, Korean finance theme.",
            config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']),
        )
        for part in resp.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    except Exception as e:
        logger.warning(f"image gen failed: {e}")
    return None


def _save_image(image_data: bytes) -> Optional[str]:
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.png"
        with open(os.path.join(UPLOAD_DIR, filename), 'wb') as f:
            f.write(image_data)
        return f"/api/community/uploads/{filename}"
    except Exception as e:
        logger.warning(f"save image failed: {e}")
        return None


# ─── Theme classification ────────────────────────────────────
THEME_KEYWORDS = [
    ('⚡ 전력망·인프라', ['전선', '전력', '에코에너지', 'LS', '해저케이블', '송전', '변압기', '중전기']),
    ('🤖 AI·데이터센터', ['SDS', '에스디에스', 'SK', 'AI', '데이터센터', '클라우드', '서버', '반도체']),
    ('🔋 2차전지·소재', ['배터리', '전자재료', '실리콘', '음극재', '양극재', '전해질', '머티리얼']),
    ('🏗️ 건설·조선·중공업', ['건설', '건축', '조선', '중공업', '엔지니어링', 'E&C']),
    ('💄 K-뷰티·소비재', ['뷰티', '화장품', 'APR', '에이피알', '코스맥스', '아모레']),
    ('💰 금융·핀테크', ['증권', '금융', '은행', '헥토', '핀테크', '보험', '카드']),
    ('☀️ 신재생·그린', ['태양광', '풍력', '수소', '그린', '신재생', '신성이엔지']),
    ('🚢 수출·운송', ['해운', '항공', '물류', '운송', '조선']),
]


def _classify_theme(stock_name: str, themes: list) -> str:
    text = (stock_name or '') + ' ' + ' '.join(themes or [])
    for label, keywords in THEME_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return label
    return '📊 기타 모멘텀'


IMAGE_PROMPTS = {
    '⚡ 전력망·인프라': "Futuristic power grid, electric transmission towers, glowing high-voltage cables, AI data center, cyan+orange accent",
    '🤖 AI·데이터센터': "Corporate AI partnership, large server building with glowing AI brain, handshake, purple+gold gradient",
    '🔋 2차전지·소재': "Advanced lithium battery and EV chargers, microscopic nano materials glowing, teal+lime accent",
    '🏗️ 건설·조선·중공업': "Modern construction site and shipyard with cranes, steel structures, navy+silver accent",
    '💄 K-뷰티·소비재': "Premium K-beauty product on display, global market, pink+rose gold elegant gradient",
    '💰 금융·핀테크': "Futuristic fintech dashboard with glowing charts, digital money flow, gold+indigo accent",
    '☀️ 신재생·그린': "Solar panels and wind turbines at sunrise, green energy field, yellow+green gradient",
    '🚢 수출·운송': "Large container ship and cargo plane, global trade routes, blue+orange accent",
    '📊 기타 모멘텀': "Abstract Korean stock market momentum chart, dynamic candlesticks, silver+gold accent",
}


# ─── Pipeline ────────────────────────────────────────────────
def _login() -> str:
    for pw in ['admin1234', 'Admin1234!', 'admin']:
        try:
            r = requests.post(f"{API_URL}/api/auth/login",
                              json={"email": ADMIN_EMAIL, "password": pw}, timeout=10)
            if r.status_code == 200:
                return r.json()['token']
        except Exception as e:
            logger.warning(f"login attempt failed: {e}")
    raise RuntimeError("admin login failed — check ADMIN_EMAIL/password")


def _already_posted_today(token: str, date_str: str) -> bool:
    """오늘 날짜 문자열이 포함된 제목의 분석글이 이미 있는지 확인."""
    try:
        r = requests.get(
            f"{API_URL}/api/community/boards/analysis/posts?limit=20",
            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r.status_code != 200:
            return False
        posts = r.json()
        if isinstance(posts, dict):
            posts = posts.get('posts', [])
        mm_dd = date_str[5:10]  # "04-15"
        slash_mm_dd = mm_dd.replace('-', '/').lstrip('0')  # "4/15" (보수적으로 양쪽 다 체크)
        for p in posts[:20]:
            title = p.get('title', '')
            if ('종가베팅' in title) and (mm_dd in title or slash_mm_dd in title or date_str in title):
                return True
        return False
    except Exception as e:
        logger.warning(f"duplicate check failed: {e}")
        return False


def _build_content(data: dict, images: dict) -> tuple[str, str]:
    """jongga_v2 data → (title, content_html)"""
    signals = data.get('signals') or []
    by_grade = data.get('by_grade') or {}
    date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
    mm_dd = date_str[5:10].replace('-', '/').lstrip('0')  # "4/15"

    s_count = by_grade.get('S', 0)
    a_count = by_grade.get('A', 0)

    title = f"[종가베팅] {mm_dd} 오늘의 S급 {s_count}종목 + A급 {a_count}종목"

    # 테마별 그룹핑 (S 우선 정렬)
    by_theme: dict = defaultdict(list)
    for s in signals:
        theme = _classify_theme(s.get('stock_name', ''), s.get('themes', []))
        by_theme[theme].append(s)

    # 테마 정렬: S급 다수 포함 → 상위
    def _theme_score(items):
        return -sum(10 if x.get('grade') == 'S' else 1 for x in items)
    sorted_themes = sorted(by_theme.items(), key=lambda kv: _theme_score(kv[1]))

    # AI Consensus picks lookup (종목코드 → rank)
    ai_picks = (data.get('claude_picks') or {}).get('picks') or []
    ai_rank_map = {}
    for p in ai_picks:
        code = p.get('stock_code')
        if code and p.get('source') == 'consensus':
            ai_rank_map[code] = p.get('rank')

    # HTML 빌드
    hero_url = images.get('_hero')
    hero_html = f'<p><img src="{hero_url}" alt="hero" /></p>' if hero_url else ""

    content = f"""{hero_html}

<h1>오늘의 한 줄</h1>
<p><strong>{date_str}</strong> 종가베팅 V2 결과 — 총 <strong>{s_count + a_count}개 시그널</strong> (S:{s_count} · A:{a_count}).</p>

<hr />
"""

    for theme_label, items in sorted_themes:
        items_sorted = sorted(items, key=lambda x: (x.get('grade') != 'S', -x.get('score', {}).get('total', 0)))
        theme_img = images.get(theme_label)
        img_html = f'<p><img src="{theme_img}" alt="{theme_label}" /></p>' if theme_img else ""

        content += f"\n<h1>{theme_label}</h1>\n{img_html}\n"

        for s in items_sorted:
            name = s.get('stock_name', '?')
            code = s.get('stock_code', '')
            grade = s.get('grade', '?')
            price = s.get('current_price') or s.get('entry_price') or 0
            pct = s.get('change_pct', 0)
            score = s.get('score', {}).get('total', 0)
            ai_rank = ai_rank_map.get(code)

            grade_tag = f"<em>({grade}등급)</em>"
            ai_tag = f" <em>· AI Consensus #{ai_rank}</em>" if ai_rank else ""

            content += f"\n<h2>{name} {grade_tag}{ai_tag}</h2>\n"
            content += f"<p><strong>{price:,.0f}원 · {pct:+.2f}%</strong> (점수 {score}/17)</p>\n"

            # 뉴스/재료 한 줄
            news_items = s.get('news_items') or []
            if news_items:
                first_news = news_items[0]
                news_text = first_news.get('title') if isinstance(first_news, dict) else str(first_news)
                if news_text:
                    content += f"<p>📰 {news_text[:100]}</p>\n"

            # 체크리스트 요약
            cl = s.get('checklist', {}) or {}
            tags = []
            if cl.get('is_new_high'): tags.append('신고가')
            if cl.get('is_breakout'): tags.append('돌파')
            if cl.get('ma_aligned'): tags.append('이평정배열')
            if cl.get('supply_positive'): tags.append('수급양호')
            if cl.get('has_disclosure'): tags.append('호재공시')
            if tags:
                content += f"<p>✔ {' · '.join(tags)}</p>\n"

            content += "\n<hr />\n"

    content += """
<h1>💵 매매 규칙</h1>
<p>손절 : 매수가 <strong>-3%</strong> (시그널의 stop 가격 참고)</p>
<p>목표 : 매수가 <strong>+5%</strong></p>
<p>테마당 1종목씩만 — 분산 필수.</p>

<hr />

<h1>⚠️ 주의</h1>
<p>상한가 근접 종목은 <strong>오버나잇 리스크</strong> 높음.</p>
<p>손절선 깨지면 즉시 정리 — 반등 기다리지 말 것.</p>
<p>AI Consensus 태그는 Gemini+GPT-4o 교차검증 통과.</p>

<hr />

<p><em>종가베팅 V2 · 17점 체크리스트 · Gemini + GPT-4o 교차검증</em></p>
"""
    content += f'<p><em>데이터: {date_str} 장마감 · 자동 생성</em></p>\n'
    content += '<p><em>이미지: Gemini 2.5 Flash Image (Nano Banana) 생성</em></p>\n'

    return title, content


def main() -> int:
    # 1. 주말 skip
    today = datetime.now()
    if today.weekday() >= 5:
        logger.info("주말 — skip")
        return 2

    # 2. jongga_v2 데이터 로드 + 최신성 검증
    if not os.path.exists(JONGGA_JSON):
        logger.warning(f"jongga_v2_latest.json 없음: {JONGGA_JSON}")
        return 1
    with open(JONGGA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    date_str = data.get('date', '')
    today_str = today.strftime('%Y-%m-%d')
    if date_str != today_str:
        logger.info(f"데이터 날짜({date_str}) != 오늘({today_str}) — skip")
        return 2

    signals = data.get('signals') or []
    if len(signals) == 0:
        logger.info("시그널 0개 — skip")
        return 2

    # 3. 로그인 + 중복 확인
    try:
        token = _login()
    except Exception as e:
        logger.error(f"로그인 실패: {e}")
        return 1

    if _already_posted_today(token, date_str):
        logger.info(f"{date_str} 오늘의 분석글 이미 존재 — skip")
        return 2

    # 4. 이미지 생성 (실패해도 계속 진행)
    logger.info(f"signals={len(signals)} — 이미지 생성 시작")
    client = _get_gemini_client()

    images = {}
    # 히어로
    hero = _gen_image(client,
        "Futuristic Korean stock market dashboard at market close, "
        "AI neural network analyzing candlestick charts, glowing data streams, "
        "deep navy blue + gold accent, modern cinematic, 16:9")
    if hero:
        images['_hero'] = _save_image(hero)

    # 테마 이미지 (유니크 테마만, 최대 4장)
    themes_used = set()
    for s in signals:
        t = _classify_theme(s.get('stock_name', ''), s.get('themes', []))
        themes_used.add(t)
    for theme in list(themes_used)[:4]:
        prompt = IMAGE_PROMPTS.get(theme, IMAGE_PROMPTS['📊 기타 모멘텀'])
        img = _gen_image(client, prompt)
        if img:
            images[theme] = _save_image(img)

    logger.info(f"이미지 {sum(1 for v in images.values() if v)}장 저장")

    # 5. HTML 빌드
    title, content = _build_content(data, images)
    logger.info(f"제목: {title} / 본문 {len(content)}자")

    # 6. 게시
    try:
        r = requests.post(
            f"{API_URL}/api/community/boards/analysis/posts",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"title": title, "content": content},
            timeout=30,
        )
        if r.status_code not in (200, 201):
            logger.error(f"게시 실패: {r.status_code} {r.text[:300]}")
            return 1
        post_id = r.json().get('id')
        logger.info(f"게시 완료: post_id={post_id}")
        logger.info(f"URL: https://bitman-marketflow.pages.dev/dashboard/community/post/{post_id}")
        return 0
    except Exception as e:
        logger.error(f"게시 예외: {e}")
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        logger.exception(f"fatal: {e}")
        sys.exit(1)
