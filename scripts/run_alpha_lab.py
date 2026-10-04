"""Run the fixed, costed research tournament and freeze prospective watchlists."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.mirofish.alpha_lab.service import ROOT, scan_once


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Private AlphaLab artifacts and canonical input pointer')
    args = parser.parse_args(argv)
    status = scan_once(args.root)
    report = status.get('report') or {}
    print(json.dumps(dict(state=status['state'], error=status['error'],
        inspected=(report.get('universe') or {}).get('inspected_count', 0),
        latest_session=report.get('latest_session'), champion=(report.get('champion') or {}).get('strategy_id'),
        candidates=[dict(symbol=row['symbol'], name=row['name'], weight=row['risk']['weight'])
                    for row in report.get('candidates', [])], forward=report.get('forward')), ensure_ascii=False))
    return 1 if status['state'] == 'failed' else 2 if status['state'] == 'running' else 0


if __name__ == '__main__':
    raise SystemExit(main())
