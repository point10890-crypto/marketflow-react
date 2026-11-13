"""Run the independent bounded Kongming technical agent (no orders or LLM)."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=project/'data'/'kongming_technical')
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        from filelock import Timeout
        from app.services.mirofish.kongming_technical.service import run_once
        load_dotenv(project/'.env', override=False)
        try:
            result = run_once(args.root)
        except Timeout:
            result = dict(status='busy')
    except Exception:
        result = dict(status='failed', reason='technical_worker_unavailable')
    status = result.get('status') if isinstance(result, dict) else None
    status = status if status in {'ready', 'partial', 'busy', 'failed'} else 'failed'
    summary = dict(status=status)
    for key in ('processed', 'failed'):
        if isinstance(result, dict) and type(result.get(key)) is int and 0 <= result[key] <= 10:
            summary[key] = result[key]
    print(json.dumps(summary))
    return 1 if status == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
