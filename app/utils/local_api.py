"""로컬 Flask API base URL 단일 해석기 — 포트 드리프트 방지.

2026-07-30 Flask 가 5001 → 5003 으로 이전(commit 8b0a3a4, JUST BUY 포트 충돌 회피)
되었을 때, 커뮤니티 자동 게시 스크립트들이 `http://localhost:5001` 을 하드코딩/기본값
으로 갖고 있어 조용히 전부 실패했다. 포트는 한 곳에서만 결정되어야 한다.

해석 우선순위:
    1. MARKETFLOW_API_URL   (명시 오버라이드)
    2. COMMUNITY_API_URL    (레거시 별칭)
    3. MARKETFLOW_API       (레거시 별칭 — scheduler env_extra 등)
    4. http://127.0.0.1:{FLASK_PORT}   (기동 스크립트가 세팅하는 포트를 따라감)
    5. http://127.0.0.1:5003           (현재 운영 기본값)

stdlib 전용 — Flask/SQLAlchemy 를 import 하지 않으므로 standalone 스크립트에서도
안전하게 쓸 수 있다.
"""

import os

DEFAULT_FLASK_PORT = '5003'


def local_api_base() -> str:
    """로컬 Flask API 의 base URL (trailing slash 없음)."""
    for name in ('MARKETFLOW_API_URL', 'COMMUNITY_API_URL', 'MARKETFLOW_API'):
        value = (os.getenv(name) or '').strip().rstrip('/')
        if value:
            return value
    port = (os.getenv('FLASK_PORT') or '').strip() or DEFAULT_FLASK_PORT
    return f'http://127.0.0.1:{port}'
