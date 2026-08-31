# -*- coding: utf-8 -*-
"""AI Brain 서비스 가드 수동 실행 — 운영자 즉석 점검용.

    python scripts/aibrain_guard.py            # 가드 1회 (알림 없음)
    python scripts/aibrain_guard.py --prewarm  # 판단 캐시 프리웜 포함
    python scripts/aibrain_guard.py --json     # 기계용 출력
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
except Exception:  # noqa: BLE001
    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--prewarm', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    from app.services.mirofish import service_guard

    result = service_guard.run_guard(send_fn=None)
    if args.prewarm:
        result['prewarm'] = service_guard.prewarm_decision_cache()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"overall: {result['overall']}  ({result['generated_at']})")
        for name, svc in result['services'].items():
            label = service_guard.SERVICE_LABEL.get(name, name)
            print(f"  [{svc['status'].upper():4}] {label:10} {svc['checked_ms']}ms  {svc.get('detail')}")
        if 'prewarm' in result:
            pw = result['prewarm']
            print(f"  prewarm: warmed {len(pw['warmed'])} · skipped {len(pw['skipped'])} · errors {len(pw['errors'])}")
    return 0 if result['overall'] != 'fail' else 1


if __name__ == '__main__':
    raise SystemExit(main())
