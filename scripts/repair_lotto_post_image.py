"""커뮤니티 게시글의 깨진 이미지 복구 — 렌더 안 되는 <img> 를 실제 PNG 로 교체.

제1231~1236회 AI 로또 분석 글은 `<img>` 태그는 있었지만 `.svg` 를 가리켰고,
`serve_upload()` 화이트리스트(jpg/jpeg/png/gif/webp)에 svg 가 없어 항상 404 →
독자에게는 깨진 이미지로 보였다. 이 스크립트는 그런 글의 이미지를 다시 만들어
본문을 갱신한다.

사용법:
  python scripts/repair_lotto_post_image.py --post-id 185
  python scripts/repair_lotto_post_image.py --latest --dry-run
  python scripts/repair_lotto_post_image.py --board lotto-ai --all-broken
"""

import argparse
import logging
import os
import re
import sqlite3
import sys

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))

import lotto_analysis as L  # noqa: E402  (경로 세팅 후 import)

logger = logging.getLogger('repair_lotto_post_image')
if not logger.handlers and not logging.getLogger().handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# app/routes/community.py::ALLOWED_EXTENSIONS 와 동일해야 한다.
SERVABLE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
IMG_SRC_RE = re.compile(r'<img[^>]*?src="([^"]+)"[^>]*?>', re.IGNORECASE)


def fetch_post(post_id: int) -> dict | None:
    with sqlite3.connect(L.DB_FILE, timeout=5) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT p.id, p.title, p.content, b.slug FROM posts p "
            "JOIN boards b ON p.board_id = b.id WHERE p.id = ?",
            (post_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {'id': row[0], 'title': row[1], 'content': row[2] or '', 'board': row[3]}


def list_board_posts(board: str, limit: int = 20) -> list[dict]:
    with sqlite3.connect(L.DB_FILE, timeout=5) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT p.id, p.title, p.content, b.slug FROM posts p "
            "JOIN boards b ON p.board_id = b.id WHERE b.slug = ? "
            "ORDER BY p.id DESC LIMIT ?",
            (board, limit),
        )
        rows = cur.fetchall()
    return [{'id': r[0], 'title': r[1], 'content': r[2] or '', 'board': r[3]} for r in rows]


def broken_image_srcs(content: str) -> list[str]:
    """렌더되지 않는 <img src> 목록 — 서빙 불가 확장자 또는 파일 없음."""
    broken = []
    for src in IMG_SRC_RE.findall(content or ''):
        if not src.startswith('/api/community/uploads/'):
            continue  # 외부 URL 은 판단하지 않는다
        filename = src.rsplit('/', 1)[-1]
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in SERVABLE_EXTENSIONS:
            broken.append(src)
            continue
        if not os.path.exists(os.path.join(L.UPLOAD_DIR, filename)):
            broken.append(src)
    return broken


def draw_no_from_title(title: str) -> int | None:
    m = re.search(r'제?\s*(\d{3,5})\s*회', title or '')
    return int(m.group(1)) if m else None


def numbers_from_content(content: str) -> list[int]:
    """본문의 첫 추천 세트 (<strong>3, 11, 19, 28, 34, 42</strong>) 추출 — 카드 폴백용."""
    for raw in re.findall(r'<strong>([^<]+)</strong>', content or ''):
        nums = [int(x) for x in re.findall(r'\b(\d{1,2})\b', raw)]
        nums = [n for n in nums if 1 <= n <= 45]
        if len(nums) == 6 and len(set(nums)) == 6:
            return sorted(nums)
    return []


def build_replacement_image(post: dict) -> tuple[str, str] | None:
    """새 이미지를 만들어 저장하고 (url, source) 반환."""
    drw = draw_no_from_title(post['title'])
    prompt = (
        'Bright cheerful illustration of Korean Lotto 6/45 lottery balls floating with soft '
        'sparkles over a deep navy background, clean modern digital art, '
        'no text, no numbers, no logo, no watermark'
    )

    logger.info('Nano Banana 이미지 생성 중...')
    data = L.generate_image(None, prompt)
    source = 'nano_banana'
    if not data:
        logger.info('OpenAI Images 폴백 시도...')
        data = L.generate_openai_image(prompt)
        source = 'openai_image'
    if not data:
        logger.warning('외부 이미지 API 실패 — 로컬 렌더 카드로 대체')
        numbers = numbers_from_content(post['content'])
        stats = {'last_draw': {'drwNo': (drw - 1) if drw else 0}}
        candidates = (
            {'AI 추천': {'desc': '', 'sets': [{'numbers': numbers, 'score': 0}]}}
            if numbers else {}
        )
        data = L.render_fallback_card_png(stats, candidates)
        source = 'local_card'
    if not data:
        return None
    return L.save_image(data), source


def repair_post(post: dict, dry_run: bool = False) -> bool:
    broken = broken_image_srcs(post['content'])
    if not broken:
        logger.info('id=%s "%s" — 깨진 이미지 없음, 건너뜀', post['id'], post['title'])
        return False

    logger.info('id=%s "%s" — 깨진 이미지 %d개: %s',
                post['id'], post['title'], len(broken), ', '.join(broken))
    if dry_run:
        logger.info('[DRY RUN] 이미지 생성/게시 안 함')
        return False

    built = build_replacement_image(post)
    if not built:
        logger.error('id=%s — 이미지 생성 실패, 원본 유지', post['id'])
        return False
    image_url, source = built

    content = post['content']
    # 첫 깨진 이미지는 새 이미지로 교체, 나머지 깨진 이미지는 제거
    content = content.replace(broken[0], image_url, 1)
    for src in broken[1:]:
        content = IMG_SRC_RE.sub(
            lambda m: '' if m.group(1) == src else m.group(0), content
        )

    token = L.login()
    resp = requests.put(
        f'{L.API_URL}/api/community/posts/{post["id"]}',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={'content': content},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error('id=%s 수정 실패: %s %s', post['id'], resp.status_code, resp.text[:200])
        return False

    logger.info('id=%s 복구 완료 — %s (source=%s)', post['id'], image_url, source)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description='커뮤니티 게시글 깨진 이미지 복구')
    parser.add_argument('--post-id', type=int, help='복구할 게시글 id')
    parser.add_argument('--board', default=L.LOTTO_BOARD_SLUG, help='게시판 slug')
    parser.add_argument('--latest', action='store_true', help='해당 게시판 최신 글 1건')
    parser.add_argument('--all-broken', action='store_true', help='최근 20건 중 깨진 글 전부')
    parser.add_argument('--dry-run', action='store_true', help='진단만, 수정 안 함')
    args = parser.parse_args()

    if args.post_id:
        post = fetch_post(args.post_id)
        if not post:
            logger.error('post id=%s 를 찾을 수 없습니다', args.post_id)
            return 1
        targets = [post]
    elif args.latest:
        targets = list_board_posts(args.board, limit=1)
    elif args.all_broken:
        targets = list_board_posts(args.board, limit=20)
    else:
        parser.error('--post-id / --latest / --all-broken 중 하나가 필요합니다')
        return 1

    repaired = sum(1 for post in targets if repair_post(post, dry_run=args.dry_run))
    logger.info('=== 대상 %d건 / 복구 %d건 ===', len(targets), repaired)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
