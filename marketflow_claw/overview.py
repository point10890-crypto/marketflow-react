"""대시보드용 읽기전용 집계 — GET /api/kr/claw/overview 의 본체.

claw.db · heartbeat.json · screener_leading_latest.json · market_gate_cache.json 만 읽는다.
비밀값은 어떤 필드에도 넣지 않는다. 섹션별로 try/except 격리해 부분 실패를 허용한다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from marketflow_claw import collectors, delivery, memory, regime as rg
from marketflow_claw.paths import DB_PATH, HEARTBEAT_PATH

HEARTBEAT_DEAD_SECONDS = 180
LEADER_GRADES = ('S', 'A')
BRIEF_TEXT_MAX = 4000


def _env_flag(name: str, default: str = '0') -> bool:
    return os.environ.get(name, default).strip().lower() in {'1', 'true', 'yes', 'on'}


def _drop_confirm_ticks() -> int:
    try:
        return max(1, int(os.environ.get('CLAW_DROP_CONFIRM_TICKS', '3')))
    except ValueError:
        return 3


def _market_open() -> bool:
    try:
        from app.services.kis_screener import is_market_open
        return bool(is_market_open())
    except Exception:  # noqa: BLE001
        return False


def _read_heartbeat() -> dict[str, Any] | None:
    if not os.path.isfile(HEARTBEAT_PATH):
        return None
    with open(HEARTBEAT_PATH, encoding='utf-8') as f:
        return json.load(f)


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        return max(0.0, (now - datetime.fromisoformat(ts)).total_seconds())
    except ValueError:
        return None


def build_close_leaders(day: str | None = None) -> dict[str, Any]:
    """마감 기준 주도주 — GET /api/kr/claw/close-leaders 의 본체 (마스터 플랜 P3).

    마감 기준 = 대상 세션(day, 기본: DB 최신 세션)의 마지막 정상 스냅샷.
    종목별 당일 이벤트 타임라인과 close 브리핑 발송 여부를 함께 반환한다.
    읽기전용 · claw.db 만 접근 · 실패는 error 필드로 격리.
    """
    out: dict[str, Any] = {'day': day, 'snapshot_ts': None, 'market_status': None,
                           'by_grade': {}, 'rows': [], 'events_count': 0,
                           'close_brief': None, 'error': None}
    try:
        with memory.connect() as con:
            if not day:
                row = con.execute('SELECT day FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
                if not row:
                    out['error'] = 'no_snapshot'
                    return out
                day = row[0]
            out['day'] = day
            snap = con.execute(
                'SELECT ts, market_status, by_grade, rows_json FROM snapshots '
                "WHERE day=? AND (error IS NULL OR error='') ORDER BY id DESC LIMIT 1", (day,)).fetchone()
            if not snap:
                out['error'] = 'no_snapshot'
                return out
            events = memory.list_events(con, day)
            session_date = f'{day[:4]}-{day[4:6]}-{day[6:]}'
            brief = con.execute(
                "SELECT ts, delivered FROM briefs WHERE kind='close' AND substr(ts,1,10)=? "
                'ORDER BY id DESC LIMIT 1', (session_date,)).fetchone()
    except Exception as e:  # noqa: BLE001
        out['error'] = f'{type(e).__name__}: {e}'
        return out

    by_code: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        by_code.setdefault(e['code'], []).append(
            {'ts': e['ts'], 'type': e['type'], 'grade_from': e['grade_from'], 'grade_to': e['grade_to']})

    rows = json.loads(snap[3] or '[]')
    ordered = sorted(rows, key=lambda x: ({'S': 3, 'A': 2, 'B': 1}.get(x.get('grade'), 0),
                                          x.get('score') or 0), reverse=True)
    out.update({
        'snapshot_ts': snap[0], 'market_status': snap[1],
        'by_grade': json.loads(snap[2] or '{}'),
        'events_count': len(events),
        'close_brief': {'ts': brief[0], 'delivered': bool(brief[1])} if brief else None,
        'rows': [{
            'code': r.get('code'), 'name': r.get('name'), 'grade': r.get('grade'),
            'score': r.get('score'), 'chg': r.get('chg'), 'trval_eok': r.get('trval_eok'),
            'price': r.get('price'), 'events': by_code.get(r.get('code'), []),
        } for r in ordered],
    })
    return out


def build_overview(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    day = now.strftime('%Y%m%d')
    errors: dict[str, str] = {}
    out: dict[str, Any] = {'generated_at': now.isoformat(timespec='seconds'), 'errors': errors}

    # ── loop / regime ─────────────────────────────────────────────────────
    market_open = _market_open()
    hb = None
    try:
        hb = _read_heartbeat()
    except Exception as e:  # noqa: BLE001
        errors['heartbeat'] = f'{type(e).__name__}'
    hb_age = _age_seconds((hb or {}).get('ts'), now)

    snap: dict[str, Any] = {'rows': [], 'by_grade': {}, 'error': 'leaders_file_missing', 'ts': None}
    reg: dict[str, Any] = {'regime': 'UNKNOWN', 'halt': False, 'reasons': []}
    try:
        snap = collectors.fetch_leaders('file')
        reg = rg.evaluate(snap, collectors.load_regime_inputs(), market_open=market_open)
    except Exception as e:  # noqa: BLE001
        errors['leaders'] = f'{type(e).__name__}: {e}'

    if hb is None or hb_age is None or hb_age > HEARTBEAT_DEAD_SECONDS:
        state = 'dead'
    elif bool((hb or {}).get('halt')) or (market_open and reg.get('halt')):
        state = 'halt'
    elif market_open:
        state = 'running'
    else:
        state = 'idle'
    out['loop'] = {
        'state': state,
        'market_open': market_open,
        'heartbeat_age_s': round(hb_age) if hb_age is not None else None,
        'heartbeat_state': (hb or {}).get('state'),
        'last_tick_ts': (hb or {}).get('last_tick') or snap.get('ts'),
        'source': snap.get('source'),
        'source_age_s': round(snap.get('file_age_s')) if snap.get('file_age_s') is not None else None,
    }
    out['regime'] = {
        'regime': reg.get('regime'), 'gate_status': reg.get('gate_status'), 'gate_score': reg.get('gate_score'),
        'gate_age_hours': reg.get('gate_age_hours'), 'breadth_pct': reg.get('breadth_pct'),
        'leader_count': reg.get('leader_count'), 'halt': bool(reg.get('halt')), 'reasons': list(reg.get('reasons') or []),
    }

    # ── events / briefs / stats (DB) ──────────────────────────────────────
    events: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    briefs: list[dict[str, Any]] = []
    kis_calls_today = 0
    try:
        with memory.connect() as con:
            events = memory.list_events(con, day)
            stats = memory.stats(con, day)
            kis_calls_today = con.execute(
                "SELECT COUNT(*) FROM snapshots WHERE day=? AND source='kis'", (day,)).fetchone()[0]
            rows = con.execute(
                'SELECT ts, kind, digest, path, delivered, error FROM briefs WHERE substr(ts,1,10)=? ORDER BY id DESC LIMIT 10',
                (f'{day[:4]}-{day[4:6]}-{day[6:]}',)).fetchall()
        for ts, kind, digest, path, delivered, error in rows:
            text = ''
            try:
                with open(path, encoding='utf-8') as f:
                    text = f.read(BRIEF_TEXT_MAX)
            except OSError:
                pass
            briefs.append({'ts': ts, 'kind': kind, 'digest': (digest or '')[:12], 'delivered': bool(delivered),
                           'error': error, 'text': text})
    except Exception as e:  # noqa: BLE001
        errors['db'] = f'{type(e).__name__}: {e}'

    counts: dict[str, int] = {}
    first_event: dict[str, dict[str, Any]] = {}
    for e in events:
        counts[e['type']] = counts.get(e['type'], 0) + 1
        if e.get('code') and e['code'] not in first_event:
            first_event[e['code']] = e
    out['events'] = {'day': day, 'counts': counts, 'items': events}
    out['briefs'] = {'items': briefs}

    # ── leaders ───────────────────────────────────────────────────────────
    leaders = []
    for r in sorted(snap.get('rows') or [], key=lambda x: ({'S': 3, 'A': 2, 'B': 1}.get(x.get('grade'), 0), x.get('score', 0)), reverse=True):
        fe = first_event.get(r['code'])
        since = fe['ts'] if fe and fe['type'] in ('LEADER_NEW', 'LEADER_UPGRADE') and r.get('grade') in LEADER_GRADES else None
        leaders.append({
            'code': r['code'], 'name': r['name'], 'grade': r.get('grade'), 'score': r.get('score'),
            'chg': r.get('chg'), 'trval_eok': r.get('trval_eok'), 'since_ts': since,
            'today_event': {'type': fe['type'], 'ts': fe['ts']} if fe else None,
        })
    out['leaders'] = {
        'snapshot_ts': snap.get('ts'), 'market_status': snap.get('market_status'), 'source': snap.get('source'),
        'by_grade': snap.get('by_grade') or {}, 'error': snap.get('error'), 'rows': leaders,
    }

    # ── system ────────────────────────────────────────────────────────────
    route = delivery.route()
    try:
        db_bytes = os.path.getsize(DB_PATH) if os.path.isfile(DB_PATH) else 0
    except OSError:
        db_bytes = 0
    out['system'] = {
        'snapshots_today': stats.get('snapshots', 0), 'events_today': stats.get('events', 0),
        'briefs_today': stats.get('briefs', 0), 'briefs_delivered_today': stats.get('briefs_delivered', 0),
        'kis_calls_today': kis_calls_today, 'db_bytes': db_bytes, 'drop_confirm_ticks': _drop_confirm_ticks(),
        'delivery': {'enabled': delivery._enabled(), 'mode': route['mode'], 'token_key': route['token_key'],
                     'configured': bool(route['token_set'] and route['chat_set'])},
        'kill_switches': {'CLAW_ENABLED': _env_flag('CLAW_ENABLED', '1'), 'CLAW_DELIVERY_ENABLED': delivery._enabled(),
                          'CLAW_LLM_ENABLED': _env_flag('CLAW_LLM_ENABLED', '0')},
    }
    return out
