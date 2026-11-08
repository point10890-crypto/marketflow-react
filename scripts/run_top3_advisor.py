"""Advance the saved TOP3 debate without running inference on API threads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    project = Path(__file__).resolve().parents[1]
    parser.add_argument('--root', type=Path)
    parser.add_argument('--article-root', type=Path)
    parser.add_argument('--alpha-root', type=Path)
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(project/'.env', override=False)
        from filelock import Timeout
        from app.services.mirofish.alpha_lab import advisor
        try:
            result = advisor.run_once(root=args.root or advisor.ROOT,
                article_root=args.article_root or advisor.articles.ROOT,
                alpha_root=args.alpha_root or advisor.ALPHA_ROOT,
                deadline=time.monotonic()+210)
        except Timeout:
            result = dict(status='already_running')
        # Task history excludes prompts, provider error bodies and private receipts.
        summary = {key: result[key] for key in ('status', 'completed_stages', 'attempted_stages',
                    'debate_complete', 'selected_count', 'empty_reason') if key in result}
        if isinstance(result.get('top3'), list):
            summary['selected_count'] = len(result['top3'])
        if isinstance(result.get('debate'), dict):
            summary['debate_complete'] = result['debate'].get('debate_complete', False)
            summary['completed_stages'] = sum(stage.get('status') in {'SUCCESS_PRIMARY', 'SUCCESS_FALLBACK'}
                                              for stage in result['debate'].get('stages', []))
        print(json.dumps(summary, ensure_ascii=True))
        return 1 if result.get('status') in {'failed', 'unavailable'} else 0
    except Exception:
        print(json.dumps(dict(status='failed', error='top3_advisor_unavailable')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
