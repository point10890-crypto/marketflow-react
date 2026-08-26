"""Safe schema bootstrap and read-only status CLI.

Examples::

    # Default SHADOW mode: creates schema only, no capital or intent events.
    python -m app.services.alpha_core bootstrap

    # Read status without creating or changing the DB.
    python -m app.services.alpha_core status
"""

from __future__ import annotations

import argparse
import json

from .config import default_db_path, resolve_mode
from .paper_ledger import PaperLedger


def main() -> int:
    parser = argparse.ArgumentParser(description="AlphaCore safe paper-ledger utilities")
    parser.add_argument("command", choices=("bootstrap", "status"))
    parser.add_argument("--db", default=None, help="isolated paper.db path")
    args = parser.parse_args()
    path = args.db or default_db_path()
    mode = resolve_mode()
    if args.command == "bootstrap":
        ledger = PaperLedger(path, mode=mode)
        ledger.initialize()
    else:
        ledger = PaperLedger(path, mode=mode, read_only=True)
    print(json.dumps(ledger.status(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
