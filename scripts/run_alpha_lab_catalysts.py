# 기존 캐시 뉴스만 사용해 AlphaLab 보조 맥락을 명시적으로 갱신한다.
"""Refresh saved catalyst chronology from the existing local Omni ledger."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main(argv=None, *, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('MARKETFLOW_ALPHA_LAB_ROOT', REPO_ROOT/'data'/'alpha_lab')))
    parser.add_argument('--db-path', type=Path, default=REPO_ROOT/'data'/'omni'/'omni.db')
    args = parser.parse_args(argv)
    try:
        from app.services.mirofish.alpha_lab.catalyst_store import refresh_context
        result = refresh_context(args.root, now=now, db_path=args.db_path)
    except Exception:
        result = dict(status='failed', error='catalyst_refresh_unavailable')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('status') == 'ready' else 2


if __name__ == '__main__':
    raise SystemExit(main())
