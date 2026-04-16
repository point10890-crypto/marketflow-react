"""
2026-04-15 종가베팅 V2 결과 → 커뮤니티 종목분석 게시판 게시
- Nano Banana 히어로 + 테마별 이미지 4장
- 게시판 #27(4/14)과 동일한 HTML 포맷
"""
import json
import os
import sys
import uuid
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

API_URL = os.environ.get('MARKETFLOW_API', 'http://localhost:5001')
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
            contents=prompt + ". No text, no watermark, clean minimal illustration, Korean finance theme.",
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


def img_tag(url, alt):
    if not url:
        return ""
    return f'<p><img src="{url}" alt="{alt}" /></p>'


def main():
    print("[1/5] Gemini client + 이미지 5장 생성")
    client = get_gemini_client()

    hero = generate_image(client,
        "Futuristic Korean stock market dashboard at market close (15:30), "
        "AI neural network analyzing candlestick charts, glowing data streams, "
        "deep navy blue + gold accent, modern flat illustration, 16:9")
    hero_url = save_image(hero) if hero else None
    print(f"  hero: {hero_url}")

    img_power = generate_image(client,
        "Futuristic power grid infrastructure, electric transmission towers, "
        "AI data center with glowing cables, cyan+orange accent, flat vector illustration")
    power_url = save_image(img_power) if img_power else None
    print(f"  power: {power_url}")

    img_ai = generate_image(client,
        "Corporate AI partnership concept, large server building with AI brain, "
        "handshake between tech companies, purple+gold gradient, flat illustration")
    ai_url = save_image(img_ai) if img_ai else None
    print(f"  ai: {ai_url}")

    img_mat = generate_image(client,
        "Advanced battery materials and solar cells, green energy, "
        "microscopic view of nano materials glowing, teal+lime accent, flat illustration")
    mat_url = save_image(img_mat) if img_mat else None
    print(f"  materials: {mat_url}")

    img_beauty = generate_image(client,
        "Premium K-beauty product on display, global market expansion, "
        "pink+rose gold gradient, elegant minimal flat illustration")
    beauty_url = save_image(img_beauty) if img_beauty else None
    print(f"  beauty: {beauty_url}")

    title = "[종가베팅] 4/15 오늘의 S급 6종목 + A급 AI 컨센서스 TOP"

    content = f"""{img_tag(hero_url, 'hero')}

<h1>오늘의 한 줄</h1>
<p><strong>전력망 인프라 + AI 파트너십</strong>이 주도. S등급 6종목 폭발.</p>

<hr />

<h1>⚡ 테마 1 — 전력망/전선 인프라</h1>
{img_tag(power_url, 'power')}

<h2>LS</h2>
<p><strong>341,000원 · +13.10%</strong></p>
<p>오늘 점수 최고점(S급 중) <strong>13/17</strong>. AI 데이터센터 전력 수요 확대 수혜.</p>
<p>외인·기관 동반 매수 유입.</p>

<hr />

<h2>가온전선</h2>
<p><strong>126,900원 · +19.72%</strong></p>
<p>상한가 근접. 해저케이블·초고압전선 수주 모멘텀.</p>
<p>⚠️ 단기 급등 → 눌림목 대기 권장.</p>

<hr />

<h2>LS에코에너지 <em>(A등급)</em></h2>
<p><strong>50,000원 · +12.36%</strong></p>
<p>점수 <strong>14/17</strong>. 1분기 사상 최대 실적 + 증권사 목표가 상향.</p>
<p>전력망+AI 데이터센터 동시 수혜.</p>

<hr />

<h1>🤖 테마 2 — AI 파트너십 / 데이터센터</h1>
{img_tag(ai_url, 'ai')}

<h2>삼성에스디에스</h2>
<p><strong>176,800원 · +16.70%</strong></p>
<p>KKR과 <strong>1.2조원 규모 전략적 협력</strong> + 전환사채 발행으로 AI 투자 확대.</p>
<p>M&amp;A 기대감이 단기 모멘텀 견인.</p>

<hr />

<h2>산일전기 <em>(A등급 · AI Pick #1)</em></h2>
<p><strong>193,500원 · +5.39%</strong></p>
<p>점수 <strong>16/17</strong>(최고점). 데이터센터 신재생 수주 확대 + CAPA 증설.</p>
<p>외국인·기관 동반 강력 매수 → Gemini+GPT-4o 교차검증 통과.</p>

<hr />

<h1>🔋 테마 3 — 전자소재 / 신소재</h1>
{img_tag(mat_url, 'materials')}

<h2>대주전자재료</h2>
<p><strong>134,000원 · +15.22%</strong></p>
<p>스페이스X 태양전지 + 2차전지 실리콘음극재 + MLCC 소재 등 다각화 모멘텀.</p>
<p>중장기 성장 포트폴리오 보유.</p>

<hr />

<h1>💄 테마 4 — K-뷰티 글로벌 확장</h1>
{img_tag(beauty_url, 'beauty')}

<h2>에이피알 <em>(A등급 · AI Pick #2)</em></h2>
<p><strong>409,000원 · +5.96%</strong></p>
<p>점수 <strong>16/17</strong>. 1분기 어닝 서프라이즈 전망 + 미국/유럽 고성장.</p>
<p>증권사 목표가 일제히 상향.</p>

<hr />

<h1>💰 테마 5 — 기타 S급</h1>

<h2>헥토파이낸셜</h2>
<p><strong>33,400원 · +17.81%</strong></p>
<p>핀테크 모멘텀 + 실적 개선 기대. 거래대금 급증.</p>

<hr />

<h2>GS건설</h2>
<p><strong>40,850원 · +9.08%</strong></p>
<p>건설주 반등 + 데이터센터 EPC 수주 기대.</p>

<hr />

<h1>💵 매매 규칙</h1>
<p>손절 : 매수가 <strong>-3%</strong> (엔트리 기준 자동 계산된 stop 참고)</p>
<p>목표 : 매수가 <strong>+5%</strong></p>
<p>테마당 1종목씩만 — 분산 필수.</p>

<hr />

<h1>⚠️ 주의</h1>
<p>상한가 근접(가온전선·헥토파이낸셜)은 <strong>오버나잇 리스크</strong> 높음.</p>
<p>손절선 깨지면 즉시 정리 — 반등 기다리지 말 것.</p>
<p>AI 컨센서스(산일전기·에이피알) 는 Gemini+GPT-4o 교차검증 통과 종목.</p>

<hr />

<p><em>종가베팅 V2 · 17점 체크리스트 · Gemini + GPT-4o 교차검증</em></p>
<p><em>총 12시그널 (S:6 · A:6) · 데이터: 2026-04-15 장마감</em></p>
<p><em>이미지: Gemini 2.5 Flash Image (Nano Banana) 생성</em></p>
"""

    print(f"[2/5] 글 길이: {len(content)}자 · 제목: {title}")

    print("[3/5] 관리자 로그인")
    token = login()

    print("[4/5] 종목분석(analysis) 게시판 게시")
    r = requests.post(
        f"{API_URL}/api/community/boards/analysis/posts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title, "content": content},
    )
    if r.status_code not in (200, 201):
        print(f"[ERROR] post create: {r.status_code} {r.text[:300]}"); sys.exit(1)
    post_id = r.json()['id']
    print(f"  post_id={post_id}")

    print(f"\n[5/5] === 완료 ===")
    print(f"URL: https://bitman-marketflow.pages.dev/dashboard/community/post/{post_id}")


if __name__ == '__main__':
    main()
