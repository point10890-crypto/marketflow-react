"""Root pytest fixtures.

Adds the project root to sys.path so tests can `from engine import ...` etc.
without needing the project to be installed.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# scripts/ 도 import 가능하도록 (lotto_analysis 등)
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def tmp_db(tmp_path):
    """격리된 SQLite DB 생성 — posts/boards 스키마만 포함."""
    db = tmp_path / "users.db"
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE boards (
            id INTEGER PRIMARY KEY,
            slug VARCHAR(50),
            name VARCHAR(100),
            is_active BOOLEAN
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER,
            author_id INTEGER,
            title VARCHAR(200),
            content TEXT,
            is_notice BOOLEAN,
            created_at DATETIME
        );
        INSERT INTO boards (id, slug, name, is_active) VALUES (7, 'lotto-ai', 'AI 로또 분석', 1);
    """)
    con.commit()
    con.close()
    return db


@pytest.fixture
def clean_env(monkeypatch):
    """lotto_analysis 가 영향받는 env 를 모두 unset 후 시작."""
    keys = [
        "MARKETFLOW_API_URL", "COMMUNITY_API_URL",
        "MARKETFLOW_ADMIN_EMAIL", "COMMUNITY_ADMIN_EMAIL",
        "MARKETFLOW_ADMIN_TOKEN", "COMMUNITY_ADMIN_TOKEN",
        "MARKETFLOW_ADMIN_PASSWORD", "COMMUNITY_ADMIN_PASSWORD",
        "MARKETFLOW_ALLOW_LOCAL_ADMIN_TOKEN",
    ]
    for k in keys:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _isolate_decision_cache(tmp_path_factory, monkeypatch):
    """판단 캐시가 테스트 사이에 새지 않게 한다.

    라우트에 일간 캐시가 붙은 뒤, 캐시를 모르는 테스트가 앞선 테스트의 결과를
    적중시켜 계산 함수 호출을 건너뛰는 일이 생겼다(test_kr_decision_route).
    테스트는 운영 캐시 파일(data/decision_cache.db)을 건드리면 안 된다.
    """
    from app.services.mirofish import decision_cache

    path = tmp_path_factory.mktemp('decision_cache') / 'cache.db'
    monkeypatch.setattr(decision_cache, 'DB_PATH', str(path))
