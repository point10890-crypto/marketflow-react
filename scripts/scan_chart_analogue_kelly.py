"""Scan prepared large-cap chart evidence and publish Kelly research offline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', help='Prepared dated TOP100/quality report JSON; saved for later fixed scans')
    parser.add_argument('--root', help='Research artifact directory')
    parser.add_argument('--index-root', help='Prepared chart index directory')
    parser.add_argument('--as-of', help='Timezone-explicit observation cutoff')
    args = parser.parse_args(argv)
    try:
        from app.services.mirofish import chart_analogue_kelly_store as service
        report = service.run_scan(root=args.root, index_root=args.index_root, universe_path=args.universe, as_of=args.as_of)
        summary = {key: report[key] for key in ('status', 'run_id', 'as_of', 'universe', 'approval', 'portfolio', 'forward')}
        summary['candidates'] = [{key: row[key] for key in ('symbol', 'target', 'score', 'research_status', 'kelly')} for row in report['candidates']]
        print(json.dumps(summary, ensure_ascii=True, allow_nan=False))
        return 0 if report['status'] == 'ready' else 2
    except Exception:
        print(json.dumps({'status': 'unavailable', 'error': 'chart_analogue_kelly_scan_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
