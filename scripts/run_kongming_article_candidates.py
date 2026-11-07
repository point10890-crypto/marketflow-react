"""Run MarketFlow's scheduled article collection and evidence verification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / 'data' / 'kongming_article_candidates'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)
    deadline = time.monotonic() + 95

    try:
        from app.services.kongming_article_candidates import run_once

        result = run_once(args.data_dir)
        state = 'not_due' if result is None else result['operation']['state']
        if state not in {'not_due', 'ready', 'waiting', 'partial', 'error'}:
            state = 'error'
    except Exception:
        # The task result records failure without emitting upstream response data.
        state = 'error'

    try:
        from dotenv import load_dotenv
        from app.services.kongming_verification import run_once as verify

        load_dotenv(DEFAULT_DATA_DIR.parent.parent / '.env', override=False)
        verification = verify(args.data_dir, deadline=deadline)
    except Exception:
        verification = {'state': 'error'}
    print(json.dumps({'state': state, 'verification': verification}))
    return 0 if state in {'not_due', 'ready', 'waiting'} and verification.get('state') != 'error' else 1


if __name__ == '__main__':
    raise SystemExit(main())
