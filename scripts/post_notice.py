"""
커뮤니티 공지글 자동 생성 + 게시 스크립트
Gemini가 HTML 공지글 작성 + Nano Banana가 이미지 생성 → Flask API로 게시

사용법:
  python scripts/post_notice.py --topic "4월 업데이트 — 수식 마켓 리뉴얼"
  python scripts/post_notice.py --topic "주식 재미난 에피소드" --board free-talk --no-pin
  python scripts/post_notice.py --topic "서버 점검" --no-image
  python scripts/post_notice.py --topic "테스트" --dry-run
"""

import argparse
import json
import os
import sys
import uuid
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

API_URL = os.getenv("MARKETFLOW_API_URL") or os.getenv("COMMUNITY_API_URL") or "http://localhost:5001"
ADMIN_EMAIL = os.getenv("MARKETFLOW_ADMIN_EMAIL") or os.getenv("COMMUNITY_ADMIN_EMAIL") or "point10890@gmail.com"
ADMIN_TOKEN = os.getenv("MARKETFLOW_ADMIN_TOKEN") or os.getenv("COMMUNITY_ADMIN_TOKEN")
ADMIN_PASSWORD = os.getenv("MARKETFLOW_ADMIN_PASSWORD") or os.getenv("COMMUNITY_ADMIN_PASSWORD")
UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'uploads', 'community')


def get_gemini_client():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("[ERROR] GEMINI_API_KEY not found in .env")
        sys.exit(1)
    from google import genai
    return genai.Client(api_key=api_key)


def generate_notice(client, topic: str, board: str) -> dict:
    """Gemini 2.5 Flash로 공지글 제목 + HTML 본문 생성"""
    board_names = {
        'notice': '공지사항',
        'free-talk': '자유게시판',
        'analysis': '종목분석',
        'trade-journal': '매매일지',
        'pro-lounge': 'Pro 라운지',
        'formula-market': '수식/조건검색식 마켓',
        'lotto-ai': 'AI 로또 분석',
    }
    board_name = board_names.get(board, board)

    prompt = f"""당신은 MarketFlow 트레이딩 플랫폼의 운영진입니다.
아래 주제로 커뮤니티 '{board_name}' 게시판에 올릴 글을 작성하세요.

주제: {topic}

요구사항:
1. JSON 형식으로 반환: {{"title": "제목", "content": "HTML 본문", "image_prompt": "본문 내용에 어울리는 일러스트 이미지를 생성하기 위한 영어 프롬프트 (1~2문장)"}}
2. 제목은 간결하고 명확하게 (50자 이내)
3. 본문은 HTML 태그 사용: <h2>, <h3>, <ul><li>, <p>, <hr>, <strong>
4. 톤: 공식적이면서 친근하게, 존댓말 사용
5. 시작: "안녕하세요, MarketFlow 운영진입니다."
6. 마무리: 감사 인사
7. 본문 중간에 이미지가 들어갈 자리에 {{{{IMAGE}}}} 플레이스홀더를 1~2개 넣으세요
8. image_prompt: 본문 주제에 어울리는 일러스트/만화 스타일 이미지 프롬프트 (영어, 텍스트 없이)
9. 반드시 유효한 JSON만 반환하세요. 다른 텍스트 없이 JSON만 출력하세요.
"""

    from google.genai import types
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.7),
    )

    text = response.text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
    if text.endswith('```'):
        text = text[:-3]
    if text.startswith('json'):
        text = text[4:]
    text = text.strip()

    return json.loads(text)


def generate_image(client, prompt: str) -> bytes | None:
    """Nano Banana (gemini-2.5-flash-image)로 이미지 생성"""
    from google.genai import types
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=prompt + ". No text, no watermark, clean illustration style.",
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
            ),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    except Exception as e:
        print(f"[WARN] Image generation failed: {e}")
    return None


def save_image(image_data: bytes) -> str:
    """이미지를 uploads 디렉토리에 저장하고 URL 반환"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, 'wb') as f:
        f.write(image_data)
    return f"/api/community/uploads/{filename}"


def login() -> str:
    """관리자 로그인하여 토큰 반환"""
    if ADMIN_TOKEN:
        return ADMIN_TOKEN
    if not ADMIN_PASSWORD:
        print("[ERROR] MARKETFLOW_ADMIN_TOKEN or MARKETFLOW_ADMIN_PASSWORD is required")
        sys.exit(1)
    resp = requests.post(f"{API_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    })
    if resp.status_code == 200:
        return resp.json()['token']

    print(f"[ERROR] Admin login failed for {ADMIN_EMAIL}")
    sys.exit(1)


def create_post(token: str, board: str, title: str, content: str) -> int:
    """게시글 생성, post_id 반환"""
    resp = requests.post(
        f"{API_URL}/api/community/boards/{board}/posts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title, "content": content},
    )
    if resp.status_code not in (200, 201):
        print(f"[ERROR] Post creation failed: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)
    post_id = resp.json()['id']
    print(f"[OK] Post created: id={post_id}")
    return post_id


def pin_notice(token: str, post_id: int):
    """공지 고정"""
    resp = requests.put(
        f"{API_URL}/api/community/posts/{post_id}/notice",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_notice": True},
    )
    if resp.status_code == 200:
        print(f"[OK] Notice pinned: id={post_id}")
    else:
        print(f"[WARN] Pin failed: {resp.status_code}")


def main():
    parser = argparse.ArgumentParser(description="커뮤니티 글 자동 생성 (Gemini AI + Nano Banana 이미지)")
    parser.add_argument('--topic', help='글 주제/키워드 (인라인)')
    parser.add_argument('--topic-file', help='글 주제 UTF-8 파일 경로 (PowerShell 한글 인코딩 회피)')
    parser.add_argument('--board', default='notice', help='게시판 slug (default: notice)')
    parser.add_argument('--no-pin', action='store_true', help='공지 고정 안 함')
    parser.add_argument('--no-image', action='store_true', help='이미지 생성 안 함')
    parser.add_argument('--dry-run', action='store_true', help='생성만 하고 게시하지 않음')
    args = parser.parse_args()

    # --topic-file 우선 (인코딩 안전 경로)
    if args.topic_file:
        from pathlib import Path as _P
        args.topic = _P(args.topic_file).read_text(encoding='utf-8').strip()
    if not args.topic:
        parser.error('--topic 또는 --topic-file 필수')

    client = get_gemini_client()

    # Step 1: 글 생성
    print(f"[1/5] Gemini로 글 작성 중... (주제: {args.topic})")
    result = generate_notice(client, args.topic, args.board)
    title = result['title']
    content = result['content']
    image_prompt = result.get('image_prompt', '')

    print(f"[2/5] 제목: {title}")
    print(f"[2/5] 본문 길이: {len(content)}자")
    if image_prompt:
        print(f"[2/5] 이미지 프롬프트: {image_prompt[:80]}...")

    # Step 2: 이미지 생성
    if not args.no_image and image_prompt and '{{IMAGE}}' in content:
        print("[3/5] Nano Banana로 이미지 생성 중...")
        image_data = generate_image(client, image_prompt)
        if image_data:
            image_url = save_image(image_data)
            img_tag = f'<img src="{image_url}" alt="AI generated illustration" style="width:100%;max-width:680px;border-radius:12px;margin:16px auto;display:block;" />'
            # 첫 번째 {{IMAGE}}를 이미지로 교체, 나머지는 제거
            content = content.replace('{{IMAGE}}', img_tag, 1)
            content = content.replace('{{IMAGE}}', '')
            print(f"[3/5] 이미지 생성 완료: {image_url}")
        else:
            content = content.replace('{{IMAGE}}', '')
            print("[3/5] 이미지 생성 실패 — 텍스트만 게시")
    else:
        content = content.replace('{{IMAGE}}', '')
        if args.no_image:
            print("[3/5] 이미지 생성 스킵 (--no-image)")
        else:
            print("[3/5] 이미지 플레이스홀더 없음 — 스킵")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        print(f"Title: {title}")
        print(f"Content:\n{content[:600]}...")
        return

    # Step 3: 로그인 + 게시
    print("[4/5] 관리자 로그인...")
    token = login()

    print(f"[5/5] '{args.board}' 게시판에 게시 중...")
    post_id = create_post(token, args.board, title, content)

    if not args.no_pin and args.board == 'notice':
        pin_notice(token, post_id)

    print(f"\n=== 완료 ===")
    print(f"URL: /dashboard/community/post/{post_id}")


if __name__ == '__main__':
    main()
