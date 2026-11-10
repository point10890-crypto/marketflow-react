"""Refresh bounded surge-to-catalyst traces outside Flask request threads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    try:
        from dotenv import load_dotenv
        load_dotenv(project / '.env', override=False)
        from app.services.surge_trace import service
        result = service.run_once(root=args.root or service.ROOT,
                                  project_root=project, deadline=time.monotonic()+80)
        operation = result.get('operation') or {}
        summary = dict(status=result['status'], selected_count=len(result.get('items', [])),
                       processed=operation.get('processed', 0), pending=operation.get('pending', 0))
        print(json.dumps(summary, ensure_ascii=True))
        return 1 if result['status'] in {'unavailable', 'failed'} else 0
    except Exception:
        print(json.dumps(dict(status='failed', error='surge_trace_unavailable')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
