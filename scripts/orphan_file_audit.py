#!/usr/bin/env python3
"""Run the community upload orphan-file audit in an isolated process.

The long-lived scheduler process can import many analytics modules over time.
Some PyO3-backed dependencies are not safe to re-initialize repeatedly inside
that same interpreter. This script keeps the Flask app/database import isolated
so the scheduler can call it through subprocess and only consume JSON output.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_audit(*, max_orphans: int = 50) -> dict[str, Any]:
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / '.env', override=True)
    except Exception:
        pass

    from app import create_app
    from app.models.community import Post

    app = create_app()
    upload_dir = REPO_ROOT / 'data' / 'uploads' / 'community'
    with app.app_context():
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

        existing = {path.name for path in upload_dir.iterdir() if path.is_file()}
        posts = Post.query.filter(Post.file_url.isnot(None)).order_by(Post.id.desc()).all()
        orphans: list[dict[str, Any]] = []
        for post in posts:
            stored = post.file_url.rsplit('/', 1)[-1] if post.file_url else None
            if stored and stored not in existing:
                orphans.append({
                    'post_id': post.id,
                    'title': post.title,
                    'file_name': post.file_name,
                    'stored_filename': stored,
                    'created_at': post.created_at.isoformat() if post.created_at else None,
                    'updated_at': post.updated_at.isoformat() if post.updated_at else None,
                })

        return {
            'ok': True,
            'service': 'orphan_file_audit',
            'upload_dir': str(upload_dir),
            'upload_dir_exists': True,
            'scanned': len(posts),
            'total': len(orphans),
            'orphans': orphans[:max(1, int(max_orphans))],
            'truncated': len(orphans) > max_orphans,
            'generated_at': _now_iso(),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='print compact JSON')
    parser.add_argument('--max-orphans', type=int, default=50)
    args = parser.parse_args(argv)

    try:
        with redirect_stdout(sys.stderr):
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
