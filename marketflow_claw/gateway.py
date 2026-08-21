"""상주 루프 — 틱 1회 = 수집 → 메모리 → 이벤트 → 레짐 → (이벤트 있으면) 보고.

- PID 락: data/claw/claw.pid (단일 인스턴스)
- 하트비트: data/claw/heartbeat.json (워치독 180초 기준)
- LEADER_DROP 은 CLAW_DROP_CONFIRM_TICKS(기본 3) 연속 틱 확정 후에만 발행
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

from marketflow_claw import collectors, delivery, events as ev, memory, regime as rg, reporter
from marketflow_claw.paths import CLAW_DIR, HEARTBEAT_PATH, ensure_dirs

PID_PATH = os.path.join(CLAW_DIR, 'claw.pid')


def drop_confirm_ticks() -> int:
    try:
        return max(1, int(os.environ.get('CLAW_DROP_CONFIRM_TICKS', '3')))
    except ValueError:
        return 3


def market_open_now() -> bool:
    from app.services.kis_screener import is_market_open
    return bool(is_market_open())


def write_heartbeat(extra: dict[str, Any] | None = None) -> None:
    ensure_dirs()
    payload = {'ts': datetime.now().isoformat(timespec='seconds'), 'pid': os.getpid(), **(extra or {})}
    tmp = HEARTBEAT_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, HEARTBEAT_PATH)


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def acquire_pid_lock() -> bool:
    """다른 인스턴스가 살아 있으면 False. 죽은 PID 파일은 덮어쓴다."""
    ensure_dirs()
    if os.path.isfile(PID_PATH):
        try:
            other = int(open(PID_PATH, encoding='utf-8').read().strip() or 0)
        except ValueError:
            other = 0
        if other and other != os.getpid() and _pid_alive(other):
            return False
    with open(PID_PATH, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    return True


def release_pid_lock() -> None:
    try:
        if os.path.isfile(PID_PATH) and open(PID_PATH, encoding='utf-8').read().strip() == str(os.getpid()):
            os.remove(PID_PATH)
    except OSError:
        pass


def run_tick(*, source: str = 'auto', send: bool = False) -> dict[str, Any]:
    t0 = time.time()
    snap = collectors.fetch_leaders(source)
    gate = collectors.load_regime_inputs()
    reg = rg.evaluate(snap, gate, market_open=market_open_now())
    day = snap['ts'][:10].replace('-', '')
    n_confirm = drop_confirm_ticks()

    with memory.connect() as con:
        prev = memory.last_snapshot(con)
        snap_id = memory.save_snapshot(con, snap)
        memory.save_regime(con, snap['ts'], reg)
        already = memory.today_event_keys(con, day)
        if reg['halt']:
            found: list[dict[str, Any]] = []
        else:
            found = ev.diff(prev, snap, already=already, include_drops=(n_confirm <= 1))
            if n_confirm > 1:
                window = memory.last_n_snapshots(con, n_confirm + 1, day=day)
                found += ev.confirmed_drops(window, n_confirm, already=already)
        new_n = memory.save_events(con, found)

    report = None
    if found:
        text = reporter.event_message(found, reg)
        report = delivery.deliver('event', text, send=send)
        with memory.connect() as con:
            memory.mark_reported(con, found, datetime.now().isoformat(timespec='seconds'))
    elif reg['halt']:
        text = reporter.halt_message(reg)
        report = delivery.deliver('halt', text, send=send)

    out = {
        'ts': snap['ts'], 'source': snap.get('source'), 'rows': len(snap.get('rows') or []),
        'by_grade': snap.get('by_grade'), 'snapshot_id': snap_id, 'baseline': prev is None,
        'events_found': len(found), 'events_new': new_n, 'drop_confirm_ticks': n_confirm,
        'regime': reg['regime'], 'halt': reg['halt'], 'halt_reasons': reg['reasons'],
        'report': report, 'elapsed_s': round(time.time() - t0, 1),
    }
    write_heartbeat({'last_tick': out['ts'], 'halt': reg['halt'], 'events_found': len(found)})
    return out


def run_loop(*, source: str = 'auto', interval: int = 5, idle_interval: int = 60, send: bool = False) -> int:
    if not acquire_pid_lock():
        print('[claw] another instance holds data/claw/claw.pid — exiting')
        return 2
    consecutive_errors = 0
    try:
        write_heartbeat({'state': 'starting'})
        while True:
            try:
                if not market_open_now():
                    write_heartbeat({'state': 'idle'})
                    time.sleep(idle_interval)
                    continue
                out = run_tick(source=source, send=send)
                consecutive_errors = 0
                print(json.dumps(out, ensure_ascii=False), flush=True)
                time.sleep(interval)
            except KeyboardInterrupt:
                return 0
            except Exception as e:  # noqa: BLE001
                consecutive_errors += 1
                print(f"[claw] tick error #{consecutive_errors}: {type(e).__name__}: {e}", flush=True)
                write_heartbeat({'state': 'error', 'consecutive_errors': consecutive_errors})
                time.sleep(30 if consecutive_errors >= 3 else interval)
    finally:
        release_pid_lock()
