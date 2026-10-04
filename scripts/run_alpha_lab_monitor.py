"""Prime the official session calendar or run one saved manual-price guard tick."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main(argv=None, *, provider=None, monitor_module=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prime', 'tick', 'calendar-check'))
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('MARKETFLOW_ALPHA_LAB_ROOT', REPO_ROOT/'data/alpha_lab')))
    args = parser.parse_args(argv)
    try:
        if provider is None:
            from dotenv import load_dotenv
            load_dotenv(REPO_ROOT/'.env', override=False)
            from app.services.mirofish.alpha_lab.market_provider import KISMarketProvider
            provider = KISMarketProvider()
        if monitor_module is None:
            from app.services.mirofish.alpha_lab import monitor as monitor_module
        if args.mode == 'calendar-check':
            result = monitor_module.calendar_check(args.root, provider, now=now)
            opened = result.get('is_open')
            print(json.dumps(dict(mode=args.mode, market_state=result.get('market_state'),
                                  calendar_status=result.get('calendar_status')), ensure_ascii=False))
            return 0 if opened is True else 10 if opened is False else 2
        result = monitor_module.run_monitor(args.root, provider, now=now)
        cadence, monitoring = result.get('cadence', {}), result.get('monitoring', {})
        print(json.dumps(dict(mode=args.mode, market_state=cadence.get('market_state'),
                              calendar_status=cadence.get('calendar_status'), monitor_status=monitoring.get('status'))))
        return 2 if cadence.get('calendar_status') in ('failed', 'held') or monitoring.get('status') == 'failed' else 0
    except Exception:
        print(json.dumps(dict(mode=args.mode, error='monitor_unavailable')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
