"""Preview or explicitly deliver one verified private alpha scanner alert."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.mirofish.verified_delivery import CONFIRMATION_PHRASE, run_verified_detection  # noqa: E402


def _load_dotenv() -> None:
    """Load local dotenv values if available without exposing any of them."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / '.env', override=False)


def _configure_stdout_utf8(stream=None) -> None:
    """Use a deterministic encoding when the active text stream supports it."""
    stream = sys.stdout if stream is None else stream
    reconfigure = getattr(stream, 'reconfigure', None)
    if callable(reconfigure):
        reconfigure(encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='perform one private Telegram delivery')
    parser.add_argument('--confirm', default='', help=f'required phrase: {CONFIRMATION_PHRASE}')
    args = parser.parse_args(argv)
    _load_dotenv()
    result = run_verified_detection(send=args.send, confirmation=args.confirm)
    _configure_stdout_utf8()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
