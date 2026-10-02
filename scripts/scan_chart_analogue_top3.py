"""Scan the prepared chart index for TOP3 candidates without network or LLM calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', help='Local TOP3 scan artifact directory')
    parser.add_argument('--index-root', help='Local prepared chart index directory')
    parser.add_argument('--as-of', help='Timezone-explicit cutoff for the offline scan')
    args = parser.parse_args(argv)
    try:
        from app.services.mirofish import chart_analogue_top3 as service

        report = service.run_scan(root=args.root, index_root=args.index_root, as_of=args.as_of)
        if report['status'] not in {'ready', 'insufficient_candidates', 'running', 'joined'}:
            raise ValueError('scan_not_ready')
        universe = report.get('universe') or {}
        summary = {
            'status': report['status'],
            'generated_at': report.get('generated_at'),
            'universe': {key: universe[key] for key in ('indexed', 'processed', 'eligible', 'rejected')
                         if key in universe},
            'candidates': [{key: row[key] for key in ('symbol', 'target', 'score') if key in row}
                           for row in report.get('candidates', [])],
        }
        output = json.dumps(summary, ensure_ascii=True, allow_nan=False)
    except Exception:
        # This operator boundary must never expose local paths or provider exceptions.
        print(json.dumps({'status': 'unavailable', 'error': 'chart_top3_scan_failed'}))
        return 1
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
