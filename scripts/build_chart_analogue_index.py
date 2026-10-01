"""Offline daily-price index builder; never called by an HTTP request."""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices', type=Path, default=REPO_ROOT / 'data' / 'daily_prices.csv')
    parser.add_argument('--output', type=Path, default=REPO_ROOT / 'data' / 'chart_analogue')
    parser.add_argument('--price-basis', choices=['unadjusted', 'provider_adjusted'], default='unadjusted')
    parser.add_argument('--source-id', default='local_daily_prices')
    options = parser.parse_args()
    from app.services.mirofish.chart_analogue import build_index
    result = build_index(options.prices, options.output, price_basis=options.price_basis, source_id=options.source_id)
    print(json.dumps(result, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
