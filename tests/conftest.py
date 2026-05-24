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
