"""Preview, send once, or recover newly completed AlphaLab detection events."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PUBLIC_KEYS = {'status', 'decision_id', 'digest', 'candidate_count', 'source_session', 'sendable'}
SUCCESS = {'preview', 'delivered', 'already_delivered', 'disabled', 'no_candidates', 'retry_deferred'}


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT/'.env', override=False)


def main(argv=None, *, notifications=None):
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument('--send', action='store_true', help='One explicitly authorized private delivery')
    operation.add_argument('--automatic', action='store_true', help='Use the enabled event-delivery configuration')
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('MARKETFLOW_ALPHA_LAB_ROOT', REPO_ROOT/'data/alpha_lab')))
    args = parser.parse_args(argv)
    try:
        if notifications is None:
            from app.services.mirofish.alpha_lab import telegram_alerts as notifications
        result = (notifications.deliver_latest(args.root, enabled=True if args.send else None)
                  if args.send or args.automatic else notifications.preview_latest(args.root))
        public = {key: value for key, value in result.items() if key in PUBLIC_KEYS}
    except Exception:
        public = {'status': 'notification_unavailable'}
    configure = getattr(sys.stdout, 'reconfigure', None)
    if callable(configure):
        configure(encoding='utf-8')
    print(json.dumps(public, ensure_ascii=False, sort_keys=True))
    return 0 if public.get('status') in SUCCESS else 2


if __name__ == '__main__':
    raise SystemExit(main())
