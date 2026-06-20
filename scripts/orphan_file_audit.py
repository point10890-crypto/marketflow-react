#!/usr/bin/env python3
"""Run the community upload orphan-file audit in an isolated process.

The long-lived scheduler process can import many analytics modules over time.
Some PyO3-backed dependencies are not safe to re-initialize repeatedly inside
that same interpreter. This script keeps the Flask app/database import isolated
so the scheduler can call it through subprocess and only consume JSON output.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_audit(*, max_orphans: int = 50) -> dict[str, Any]:
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    upload_dir = REPO_ROOT / 'data' / 'uploads' / 'community'
    if not upload_dir.is_dir():
        return {
            'ok': True,
            'service': 'orphan_file_audit',
            'upload_dir': str(upload_dir),
            'upload_dir_exists': False,
            'scanned': 0,
            'total': 0,
            'orphans': [],
            'generated_at': _now_iso(),
        }

    db_file = REPO_ROOT / 'data' / 'users.db'
    if not db_file.is_file():
        raise FileNotFoundError(f'community DB not found: {db_file}')

    existing = {path.name for path in upload_dir.iterdir() if path.is_file()}
    posts = _load_posts_with_files(db_file)
    orphans: list[dict[str, Any]] = []
    for post in posts:
        stored = str(post.get('file_url') or '').rsplit('/', 1)[-1]
        if stored and stored not in existing:
            orphans.append({
                'post_id': post.get('id'),
                'title': post.get('title'),
                'file_name': post.get('file_name'),
                'stored_filename': stored,
                'created_at': _format_db_datetime(post.get('created_at')),
                'updated_at': _format_db_datetime(post.get('updated_at')),
            })

    max_count = max(1, int(max_orphans))
    return {
        'ok': True,
        'service': 'orphan_file_audit',
        'upload_dir': str(upload_dir),
        'upload_dir_exists': True,
        'scanned': len(posts),
        'total': len(orphans),
        'orphans': orphans[:max_count],
        'truncated': len(orphans) > max_count,
        'generated_at': _now_iso(),
    }


def _load_posts_with_files(db_file: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(str(db_file), timeout=10) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("PRAGMA table_info(posts)")
        columns = {row['name'] for row in cur.fetchall()}
        required = {'id', 'title', 'file_url'}
        missing = required - columns
        if missing:
            raise RuntimeError(f'posts table missing required columns: {sorted(missing)}')

        select_columns = ['id', 'title', 'file_url']
        for optional in ('file_name', 'created_at', 'updated_at'):
            if optional in columns:
                select_columns.append(optional)

        cur.execute(
            f"""
            SELECT {', '.join(select_columns)}
            FROM posts
            WHERE file_url IS NOT NULL
            ORDER BY id DESC
            """
        )
        rows = []
        for row in cur.fetchall():
            item = {key: row[key] for key in row.keys()}
            for optional in ('file_name', 'created_at', 'updated_at'):
                item.setdefault(optional, None)
            rows.append(item)
        return rows


def _format_db_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='print compact JSON')
    parser.add_argument('--max-orphans', type=int, default=50)
    args = parser.parse_args(argv)

    try:
        payload = run_audit(max_orphans=args.max_orphans)
        print(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
        return 0
    except Exception as exc:
        payload = {
            'ok': False,
            'service': 'orphan_file_audit',
            'error_type': type(exc).__name__,
            'error': str(exc),
            'generated_at': _now_iso(),
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
        return 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == '__main__':
    raise SystemExit(main())
