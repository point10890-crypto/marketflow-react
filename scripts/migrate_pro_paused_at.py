"""
Stage 9 Migration — Add `pro_paused_at` column to users table.

AI Bain 활성 중 Pro 만료 카운터 일시정지용. Pro tier 회원이 AI Bain 추가 시
pro_paused_at = now() 세팅 → expiry checker skip → AI Bain 만료 시 흐른
paused 기간만큼 pro_expires_at 연장 후 NULL 처리.

실행 (miniPC):
    cd C:\\bitman_marketfloww && .venv\\Scripts\\python.exe scripts\\migrate_pro_paused_at.py

Idempotent.
"""
from __future__ import annotations

import os
import sqlite3
import sys


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, 'data', 'users.db')

    if not os.path.exists(db_path):
        print(f'[ERROR] DB not found: {db_path}')
        sys.exit(1)

    print(f'[INFO] Target DB: {db_path}')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cur.fetchall()}

    if 'pro_paused_at' in existing_cols:
        print('[SKIP] Column already exists: pro_paused_at')
        conn.close()
        print('[DONE]')
        return

    try:
        cur.execute("ALTER TABLE users ADD COLUMN pro_paused_at DATETIME")
        conn.commit()
        print('[OK] Added column: pro_paused_at')
    except sqlite3.OperationalError as e:
        print(f'[FAIL] {e}')
        sys.exit(2)

    cur.execute("PRAGMA table_info(users)")
    final_cols = {row[1] for row in cur.fetchall()}
    print(f'[INFO] Total columns: {len(final_cols)} (added pro_paused_at)')
    conn.close()
    print('[DONE]')


if __name__ == '__main__':
    main()
