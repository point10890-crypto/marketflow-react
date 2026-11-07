"""Advance the saved article and candidate interpretation worker once."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    project = Path(__file__).resolve().parents[1]
    parser.add_argument('--root', type=Path, default=project/'data'/'evidence_review')
    parser.add_argument('--article-root', type=Path, default=project/'data'/'kongming_article_candidates')
    parser.add_argument('--alpha-root', type=Path, default=project/'data'/'alpha_lab')
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(project/'.env', override=False)
        from filelock import Timeout
        from app.services.evidence_review import run_once
        try:
            result = run_once(root=args.root, article_root=args.article_root, alpha_root=args.alpha_root,
                              deadline=time.monotonic()+210)
        except Timeout:
            result = dict(status='already_running')
        print(json.dumps(result, ensure_ascii=True))
        return 1 if result.get('status') == 'failed' else 0
    except Exception:
        # No provider error body, path, key, or raw prompt in task history.
        print(json.dumps(dict(status='failed', error='evidence_review_unavailable')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
