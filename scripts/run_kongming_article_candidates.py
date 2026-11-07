"""Run the MarketFlow article candidate collector when its saved schedule is due."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / 'data' / 'kongming_article_candidates'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)

    try:
        from app.services.kongming_article_candidates import run_once

        result = run_once(args.data_dir)
        state = 'not_due' if result is None else result['operation']['state']
        if state not in {'not_due', 'ready', 'waiting', 'partial', 'error'}:
            state = 'error'
    except Exception:
        # The task result records failure without emitting upstream response data.
        state = 'error'

    print(json.dumps({'state': state}))
    return 0 if state in {'not_due', 'ready', 'waiting'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
