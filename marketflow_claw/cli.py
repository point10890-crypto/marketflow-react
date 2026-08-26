"""CLI: status | doctor | leaders | regime | events | brief | start | replay"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from marketflow_claw import __version__, collectors, delivery, events as ev, gateway, memory, regime as rg, reporter
from marketflow_claw.paths import HEARTBEAT_PATH


def _today() -> str:
    return datetime.now().strftime('%Y%m%d')


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        from marketflow_claw.paths import REPO_ROOT
        load_dotenv(os.path.join(REPO_ROOT, '.env'), override=False)
    except Exception:  # noqa: BLE001
        pass


def cmd_status(a) -> int:
    hb = None
    if os.path.isfile(HEARTBEAT_PATH):
        with open(HEARTBEAT_PATH, encoding='utf-8') as f:
            hb = json.load(f)
    with memory.connect() as con:
        st = memory.stats(con, _today())
    gate = collectors.load_regime_inputs()
    route = delivery.route()
    out = {
        'version': __version__, 'market_open': gateway.market_open_now(), 'heartbeat': hb,
        'today': st, 'gate': {k: gate.get(k) for k in ('status', 'score', 'age_hours')},
        'delivery': {'enabled': delivery._enabled(), **route},
        'drop_confirm_ticks': gateway.drop_confirm_ticks(),
    }
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 0
    print(f"MarketFlow Claw {__version__}")
    print(f"market       {'open' if out['market_open'] else 'closed'}")
    print(f"heartbeat    {hb.get('ts') if hb else '-'}  last_tick={hb.get('last_tick') if hb else '-'}  state={hb.get('state', '-') if hb else '-'}")
    print(f"today        snapshots {st['snapshots']} · events {st['events']} · briefs {st['briefs']} (delivered {st['briefs_delivered']})")
    print(f"last snap    {st['last_snapshot_ts']} ({st['last_source']})")
    print(f"gate         {gate.get('status')} {gate.get('score')}점 · age {gate.get('age_hours')}h")
    print(f"delivery     enabled={out['delivery']['enabled']} · {route['mode']} via {route['token_key']} (token {'set' if route['token_set'] else 'MISSING'}, chat {'set' if route['chat_set'] else 'MISSING'})")
    print(f"drop confirm {out['drop_confirm_ticks']} ticks")
    return 0


def cmd_doctor(a) -> int:
    from marketflow_claw import doctor
    res = doctor.run(network=not a.no_network)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for c in res['checks']:
            mark = {'ok': 'OK  ', 'warn': 'WARN', 'fail': 'FAIL'}[c['status']]
            print(f"[{mark}] {c['name']:<26} {c['detail']}")
        print('RESULT:', 'ok' if res['ok'] else 'FAIL')
    return 0 if res['ok'] else 1


def cmd_leaders(a) -> int:
    snap = collectors.fetch_leaders(a.source)
    if a.json:
        print(json.dumps(snap, ensure_ascii=False, indent=1)); return 0
    print(f"snapshot {snap.get('ts')} · {snap.get('market_status')} · source {snap.get('source')} · {snap.get('by_grade')}"
          + (f" · error={snap['error']}" if snap.get('error') else ''))
    print(f"{'#':>2} {'g':1} {'code':6} {'name':<12} {'score':>5} {'chg%':>7} {'trval억':>8}")
    visible_rows = [r for r in (snap.get('rows') or []) if not r.get('detection_unknown')]
    for i, r in enumerate(visible_rows, 1):
        if i > a.top:
            break
        print(f"{i:>2} {r['grade']:1} {r['code']:6} {r['name']:<12} {r['score']:>5} {r['chg']:>+7.2f} {r['trval_eok']:>8,.0f}")
    return 0


def cmd_regime(a) -> int:
    snap = collectors.fetch_leaders('file')
    reg = rg.evaluate(snap, collectors.load_regime_inputs(), market_open=gateway.market_open_now())
    print(json.dumps(reg, ensure_ascii=False, indent=1) if a.json else
          '\n'.join(f"{k:<14} {v}" for k, v in reg.items()))
    return 0


def cmd_events(a) -> int:
    day = a.date or _today()
    with memory.connect() as con:
        rows = memory.list_events(con, day)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1)); return 0
    print(f"events {day}: {len(rows)}")
    for e in rows:
        print(f"{e['ts'][11:19]}  {e['type']:<15} {e['code']:6} {e['name']:<12} {e['grade_from'] or '-'}→{e['grade_to'] or '-'}  {e['score'] or '-':>3}  {e['chg']:+.1f}%  reported={'✓' if e['reported_at'] else '-'}")
    return 0


def cmd_brief(a) -> int:
    snap = collectors.fetch_leaders('file')
    reg = rg.evaluate(snap, collectors.load_regime_inputs(), market_open=gateway.market_open_now())
    with memory.connect() as con:
        evs = memory.list_events(con, a.date or _today())
        st = memory.stats(con, a.date or _today())
    if a.kind == 'morning':
        text = reporter.morning_message(snap, reg, evs)
    elif a.kind == 'close':
        text = reporter.close_message(snap, reg, evs, st)
    else:
        text = reporter.event_message([dict(e, ts=e['ts']) for e in evs], reg) if evs else '(이벤트 없음)'
    res = delivery.deliver(a.kind, text, send=a.send)
    print(f"[{res['mode']}] kind={res['kind']} sent={res['sent']} digest={res['digest'][:12]}… path={res['path']}"
          + (f" error={res['error']}" if res['error'] else ''))
    print('--- message ---')
    print(text)
    return 0 if not res['error'] else 1


def cmd_start(a) -> int:
    if a.once:
        out = gateway.run_tick(source=a.source, send=a.send)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    return gateway.run_loop(source=a.source, interval=a.interval, send=a.send)


def cmd_replay(a) -> int:
    """과거 스냅샷 파일들을 순서대로 diff — 실데이터로 이벤트 검출 검증."""
    dates = [d.strip() for d in a.dates.split(',') if d.strip()]
    prev = None
    total = 0
    for d in dates:
        snap = collectors.load_leaders_file() if d == 'latest' else collectors.load_leaders_history(d)
        if snap is None:
            print(f"{d}: 파일 없음"); continue
        found = ev.diff(prev, snap)
        print(f"{d}: {snap.get('ts')} rows={len(snap['rows'])} by_grade={snap['by_grade']} → events {len(found)}"
              + ('  (baseline)' if prev is None else ''))
        for e in found:
            print(f"   {e['type']:<15} {e['code']} {e['name']:<12} {e.get('grade_from') or '-'}→{e.get('grade_to') or '-'} {e['score']:>3}점 {e['chg']:+.1f}%")
        total += len(found)
        prev = snap
    print(f"total events: {total}  (replay 는 일 단위 diff 라 DROP 확정 규칙을 적용하지 않음)")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:  # noqa: BLE001
        pass
    _load_env()
    p = argparse.ArgumentParser(prog='marketflow_claw')
    p.add_argument('--version', action='version', version=f'marketflow_claw {__version__}')
    sp = p.add_subparsers(dest='cmd', required=True)

    s = sp.add_parser('status'); s.add_argument('--json', action='store_true'); s.set_defaults(fn=cmd_status)
    s = sp.add_parser('doctor'); s.add_argument('--json', action='store_true'); s.add_argument('--no-network', action='store_true'); s.set_defaults(fn=cmd_doctor)
    s = sp.add_parser('leaders'); s.add_argument('--top', type=int, default=10)
    s.add_argument('--source', choices=['auto', 'file', 'kis'], default='file'); s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_leaders)
    s = sp.add_parser('regime'); s.add_argument('--json', action='store_true'); s.set_defaults(fn=cmd_regime)
    s = sp.add_parser('events'); s.add_argument('--date'); s.add_argument('--json', action='store_true'); s.set_defaults(fn=cmd_events)
    s = sp.add_parser('brief'); s.add_argument('--kind', choices=['morning', 'event', 'close'], default='close')
    s.add_argument('--date'); s.add_argument('--send', action='store_true'); s.set_defaults(fn=cmd_brief)
    s = sp.add_parser('start'); s.add_argument('--once', action='store_true')
    s.add_argument('--source', choices=['auto', 'file', 'kis'], default='auto')
    s.add_argument('--interval', type=int, default=5); s.add_argument('--send', action='store_true'); s.set_defaults(fn=cmd_start)
    s = sp.add_parser('replay'); s.add_argument('--dates', required=True, help='YYYYMMDD,YYYYMMDD,...,latest'); s.set_defaults(fn=cmd_replay)

    a = p.parse_args(argv)
    return a.fn(a)
