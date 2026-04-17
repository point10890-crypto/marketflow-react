"""Migration: add users.requested_tier column (2026-04-17)

가입 시 유저가 선택한 구독 플랜을 저장하기 위한 컬럼 추가.
기존 123명 데이터는 NULL 유지 (역할: 신규 가입자부터 활용).

Idempotent: 이미 컬럼이 존재하면 no-op.

Usage:
    PYTHONIOENCODING=utf-8 "$PYTHON" scripts/migrations/2026_04_17_requested_tier.py
"""
import os
import sqlite3
import sys

# 워크트리 루트 기준 DB 경로
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'users.db')
DB_PATH = os.path.normpath(DB_PATH)


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def main():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        if column_exists(conn, 'users', 'requested_tier'):
            print(f"[OK] users.requested_tier already exists — no-op")
            return

        conn.execute("ALTER TABLE users ADD COLUMN requested_tier VARCHAR(20)")
        conn.commit()
        print(f"[OK] Added users.requested_tier (NULL default)")

        # 검증
        cur = conn.execute("PRAGMA table_info(users)")
        cols = [row[1] for row in cur.fetchall()]
        assert 'requested_tier' in cols, "column not added!"
        print(f"[OK] Verified — total columns: {len(cols)}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
