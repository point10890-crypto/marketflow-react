#!/usr/bin/env python3
"""Bridge cloud scheduling to the isolated root Crypto pipeline."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
while str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

def _load_root_scheduler():
    import scheduler  # noqa: E402  (project root is forced to sys.path[0])

    return scheduler


def main() -> int:
    # The outer cloud scheduler owns the process group. The root worker must
    # stay in that group so an outer timeout can terminate the complete tree.
    runtime_values = {
        "MARKETFLOW_CRYPTO_INHERIT_PROCESS_GROUP": "1",
        "MARKETFLOW_PRESERVE_ENV": "1",
    }
    previous = {key: os.environ.get(key) for key in runtime_values}
    os.environ.update(runtime_values)
    try:
        try:
            root_scheduler = _load_root_scheduler()
            succeeded = root_scheduler.run_crypto_pipeline(skip_sync=True, no_notify=True)
        except BaseException:
            return 1
        return 0 if succeeded is True else 1
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
