"""
Stage 6 Migration — Add AI Bain 알파 스캐너 컬럼 (User table).

신규 컬럼:
- aibain_enabled       (BOOLEAN, NOT NULL, default 0)
- aibain_expires_at    (DATETIME, NULLABLE)
- aibain_alert_stage   (VARCHAR(10), NULLABLE)

실행 (miniPC):
    cd C:\\bitman_marketfloww && .venv\\Scripts\\python.exe scripts\\migrate_aibain_columns.py

Idempotent — 이미 컬럼이 있으면 SKIP.
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

    # 현재 컬럼 목록 조회
    cur.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cur.fetchall()}
    print(f'[INFO] Existing columns ({len(existing_cols)}): {sorted(existing_cols)}')

    migrations = [
        ('aibain_enabled', "ALTER TABLE users ADD COLUMN aibain_enabled BOOLEAN NOT NULL DEFAULT 0"),
        ('aibain_expires_at', "ALTER TABLE users ADD COLUMN aibain_expires_at DATETIME"),
        ('aibain_alert_stage', "ALTER TABLE users ADD COLUMN aibain_alert_stage VARCHAR(10)"),
    ]

    applied = 0
    skipped = 0
    for col_name, sql in migrations:
        if col_name in existing_cols:
            print(f'[SKIP] Column already exists: {col_name}')
            skipped += 1
            continue
        try:
            cur.execute(sql)
            print(f'[OK]   Added column: {col_name}')
            applied += 1
        except sqlite3.OperationalError as e:
            print(f'[FAIL] {col_name}: {e}')
            sys.exit(2)

    conn.commit()

    # 결과 확인
    cur.execute("PRAGMA table_info(users)")
    final_cols = {row[1] for row in cur.fetchall()}
    print(f'[INFO] Final columns ({len(final_cols)}): {sorted(final_cols)}')

    # AI Bain 컬럼 확인
    aibain_cols = [c for c in final_cols if c.startswith('aibain_')]
    print(f'[INFO] AI Bain columns: {aibain_cols}')

    conn.close()
    print(f'[DONE] Applied={applied}, Skipped={skipped}')


if __name__ == '__main__':
    main()
