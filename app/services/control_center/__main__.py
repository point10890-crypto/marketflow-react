"""관제 센터 CLI.

  python -m app.services.control_center run --tier fast|standard|deep|all
  python -m app.services.control_center status            # 요약 (latest.json)
  python -m app.services.control_center inventory --write # 엔드포인트 목록 갱신 (별도 프로세스에서 앱 생성)
  python -m app.services.control_center coverage          # 감시 범위 요약
"""
from __future__ import annotations

import argparse
import os
import sys


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    from app.utils.paths import BASE_DIR

    load_dotenv(os.path.join(BASE_DIR, '.env'), override=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='control_center')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sp = sub.add_parser('run')
    sp.add_argument('--tier', default='fast', choices=['fast', 'standard', 'deep', 'all'])
    sp.add_argument('--no-alerts', action='store_true')
    sub.add_parser('status')
    sp = sub.add_parser('inventory')
    sp.add_argument('--write', action='store_true')
    sub.add_parser('coverage')
    args = ap.parse_args(argv)
    _load_env()

    from app.services.control_center import cc_dir, runner, store

    if args.cmd == 'run':
        tiers = ['fast', 'standard', 'deep'] if args.tier == 'all' else [args.tier]
        worst_code = 0
        for t in tiers:
            try:
                res = runner.run(t, send_alerts=False if args.no_alerts else None)
            except Exception as exc:
                print(f'[control-center] {t}: runner error ({type(exc).__name__})', file=sys.stderr)
                worst_code = 2
                continue
            print(f"[control-center] {t}: {res.get('overall', res.get('skipped'))} "
                  f"results={res.get('results', 0)} changes={len(res.get('changes', []))} alerts={res.get('alerts_sent', 0)}")
            if res.get('runner_failed'):
                worst_code = 2
        return worst_code
    if args.cmd == 'status':
        snap = runner.read_snapshot()
        c = snap.get('counts') or {}
        print(f"overall={snap.get('overall')} monitor={snap['monitor']['status']} checks={c.get('checks', 0)} "
              f"fail={c.get('fail', 0)} warn={c.get('warn', 0)} open_incidents={c.get('open_incidents', 0)}")
        for s in snap.get('failing', [])[:20]:
            print(f"  FAIL [{s['severity']}] {s['check_id']} — {s['detail']}")
        return 0
    if args.cmd == 'inventory':
        payload = runner.build_inventory_payload()
        if args.write:
            store.write_json_atomic(os.path.join(cc_dir(), runner.INVENTORY_FILE), payload)
        print(f"routes={len(payload['routes'])} release={payload['release']}")
        return 0
    if args.cmd == 'coverage':
        from app.services.control_center import contracts
        from app.services.control_center.inventory import coverage

        inv = runner.load_inventory()
        if not inv:
            print('inventory unavailable')
            return 1
        cov = coverage(inv['routes'], contracts.load())
        print(runner.dumps(cov['totals']))
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
