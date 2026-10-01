"""Collect completed adjusted daily closes in a separate offline snapshot."""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices', type=Path, default=REPO_ROOT / 'data' / 'daily_prices.csv', help='Raw source used only for six-digit symbol names')
    parser.add_argument('--output', type=Path, default=REPO_ROOT / 'data' / 'chart_analogue' / 'closed_prices.csv')
    parser.add_argument('--symbols', help='Optional comma-separated smoke-check symbols from the universe')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-seconds', type=float, default=900, help='Stop scheduling work after this global budget (at most 900 seconds)')
    options = parser.parse_args()
    from app.services.mirofish.chart_analogue_source import refresh_prices
    def progress(stats):
        print(json.dumps({'progress': stats}, separators=(',', ':')), file=sys.stderr, flush=True)
    result = refresh_prices(options.prices, options.output, symbols=options.symbols, workers=options.workers, progress=progress, max_seconds=options.max_seconds)
    print(json.dumps(result, ensure_ascii=True, separators=(',', ':')), flush=True)
    return 1 if result['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
