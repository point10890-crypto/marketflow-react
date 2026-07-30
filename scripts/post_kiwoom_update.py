"""
2026-04-15 키움 AI전략 테마 라이브 연동 업데이트 공지글 게시
- HTML 직접 작성 (Gemini 대신 정확한 내용 컨트롤)
- Nano Banana 히어로 이미지 1장 생성
- 공지사항 게시판에 게시 + 핀
"""
import json
import os
import sys
import uuid
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.utils.local_api import local_api_base

API_URL = local_api_base()
ADMIN_EMAIL = "point10890@gmail.com"
UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'uploads', 'community')


def get_gemini_client():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("[ERROR] GEMINI_API_KEY missing"); sys.exit(1)
    from google import genai
    return genai.Client(api_key=api_key)


def generate_image(client, prompt: str) -> bytes | None:
    from google.genai import types
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=prompt + ". No text, no watermark, clean illustration.",
            config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    except Exception as e:
        print(f"[WARN] image gen failed: {e}")
    return None


def save_image(image_data: bytes) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    with open(os.path.join(UPLOAD_DIR, filename), 'wb') as f:
        f.write(image_data)
    return f"/api/community/uploads/{filename}"


def login() -> str:
    for pw in ['admin1234', 'Admin1234!', 'admin']:
        r = requests.post(f"{API_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": pw})
        if r.status_code == 200:
            return r.json()['token']
    print("[ERROR] login failed"); sys.exit(1)


def main():
    print("[1/4] Gemini client + 히어로 이미지 생성")
    client = get_gemini_client()
    img_data = generate_image(
        client,
        "Minimal flat illustration, futuristic AI brain analyzing Korean stock market candlestick chart, "
        "deep navy blue + gold accent, glowing neural network nodes, financial data flowing, "
        "clean modern style, 16:9 aspect"
    )
    if img_data:
        hero_url = save_image(img_data)
        print(f"  히어로: {hero_url}")
    else:
        hero_url = None
        print("  이미지 실패 → 텍스트만")

    title = "🤖 키움 AI전략 7종 라이브 연동 — 주도주LIVE 업데이트"

    hero_html = (
        f'<img src="{hero_url}" alt="AI 조건검색 라이브 연동" '
        f'style="width:100%;max-width:680px;border-radius:12px;margin:16px auto;display:block;" />'
        if hero_url else ""
    )

    content = f"""{hero_html}

<h1>오늘의 한 줄</h1>
<p>키움 HTS 영웅문의 <strong>AI전략 조건검색식 7종</strong>이 주도주LIVE에 실시간으로 흐릅니다.</p>

<hr />

<h1>🤖 무엇이 새로워졌나</h1>
<p>주도주LIVE 페이지 상단에 <strong>"AI전략 테마 TOP"</strong> 카드가 추가됐습니다.</p>
<p>키움 영웅문 HTS의 7개 AI 조건식을 장중 동시에 돌려, <strong>여러 조건에 중복 매칭된 종목</strong>을 매칭 강도(hit_count) 순으로 랭킹합니다.</p>

<ul>
  <li>AI전략(종가매매)</li>
  <li>AI전략(종가매매2)</li>
  <li>AI전략(BNF 강력매수)</li>
  <li>AI가만든(노스트라다무스)</li>
  <li>AI전략 스윙매매</li>
  <li>AI전략(올라운드 단기)</li>
  <li>AI전략(Super Agent)</li>
</ul>

<hr />

<h1>⚙️ 동작 방식</h1>
<p>장중(09:10~15:25) <strong>15분 간격</strong>으로 7개 조건식을 순차 실행합니다. 키움 OpenAPI rate limit을 고려해 조건식당 10초 간격을 둡니다.</p>
<p>예: 오늘 09:19 첫 실행 결과 — <strong>30개 unique 종목</strong> 수집 (드림시큐리티 +30.00%, 아이씨티케이 +29.95% 등 상한가 종목 다수).</p>

<hr />

<h1>📲 텔레그램 알림</h1>
<p>주도주LIVE 시간별 요약 메시지에도 <strong>AI전략 테마 TOP 5</strong>가 자동 포함됩니다.</p>
<p>매칭 강도가 높은 종목일수록 여러 AI 모델이 동시에 추천한 종목이라는 뜻입니다.</p>

<hr />

<h1>⚠️ 주의사항</h1>
<p>AI 조건식 매칭은 <strong>참고 지표</strong>일 뿐, 매수 신호가 아닙니다. 본인의 매매 원칙·손절선과 함께 활용하세요.</p>
<p>장 시작 직후 5분간은 종가 기반 조건식(종가매매 등)에서 결과가 비어있을 수 있습니다.</p>

<hr />

<p><em>업데이트: 2026-04-15 / 데이터 소스: 키움 OpenAPI WebSocket(CNSRREQ) / 이미지: Nano Banana</em></p>
"""

    print(f"[2/4] 글 길이: {len(content)}자, 제목: {title}")

    print("[3/4] 관리자 로그인")
    token = login()

    print("[4/4] 공지사항 게시판 게시 + 핀")
    r = requests.post(
        f"{API_URL}/api/community/boards/notice/posts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title, "content": content},
    )
    if r.status_code not in (200, 201):
        print(f"[ERROR] post create: {r.status_code} {r.text[:300]}"); sys.exit(1)
    post_id = r.json()['id']
    print(f"  post_id={post_id}")

    pr = requests.put(
        f"{API_URL}/api/community/posts/{post_id}/notice",
        headers={"Authorization": f"Bearer {token}"},
    )
    print(f"  pin: {pr.status_code}")

    print(f"\n=== 완료 ===")
    print(f"URL: https://bitman-marketflow.pages.dev/dashboard/community/post/{post_id}")


if __name__ == '__main__':
    main()
