"""SQLite 메모리 — 틱 스냅샷, 이벤트, 레짐, 브리핑."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from marketflow_claw.paths import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, day TEXT NOT NULL, source TEXT,
  market_status TEXT, by_grade TEXT, rows_json TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS ix_snap_day ON snapshots(day, ts);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, day TEXT NOT NULL, type TEXT NOT NULL,
  code TEXT NOT NULL, name TEXT, grade_from TEXT, grade_to TEXT, score INTEGER,
  chg REAL, payload TEXT, reported_at TEXT,
  UNIQUE(day, type, code));
CREATE TABLE IF NOT EXISTS regimes (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, regime TEXT, breadth INTEGER,
  halt INTEGER, reasons TEXT);
CREATE TABLE IF NOT EXISTS briefs (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT, digest TEXT UNIQUE,
  path TEXT, delivered INTEGER, error TEXT);
"""


@contextmanager
def connect(path: str | None = None) -> Iterator[sqlite3.Connection]:
    """path 미지정 시 호출 시점의 모듈 DB_PATH 를 쓴다 (테스트 격리를 위해 기본 인자 바인딩 금지)."""
    import marketflow_claw.memory as _self
    ensure_dirs()
    con = sqlite3.connect(path or _self.DB_PATH)
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _day(ts: str) -> str:
    return ts[:10].replace('-', '')


def save_snapshot(con: sqlite3.Connection, snap: dict[str, Any]) -> int:
    cur = con.execute(
        'INSERT INTO snapshots(ts, day, source, market_status, by_grade, rows_json, error) VALUES (?,?,?,?,?,?,?)',
        (snap['ts'], _day(snap['ts']), snap.get('source'), snap.get('market_status'),
         json.dumps(snap.get('by_grade') or {}, ensure_ascii=False),
         json.dumps(snap.get('rows') or [], ensure_ascii=False), snap.get('error')))
    return int(cur.lastrowid)


def last_snapshot(con: sqlite3.Connection, *, before_id: int | None = None,
                  day: str | None = None) -> dict[str, Any] | None:
    """Return the newest snapshot, optionally constrained to one trading day.

    Event detection must never compare the first tick of a session with a
    snapshot from the previous session, so callers can pass ``day`` to make
    that boundary explicit.
    """
    q = 'SELECT ts, source, market_status, by_grade, rows_json, error FROM snapshots'
    where: list[str] = []
    args: list[Any] = []
    if before_id is not None:
        where.append('id < ?')
        args.append(before_id)
    if day is not None:
        where.append('day = ?')
        args.append(day)
    if where:
        q += ' WHERE ' + ' AND '.join(where)
    q += ' ORDER BY id DESC LIMIT 1'
    row = con.execute(q, tuple(args)).fetchone()
    if not row:
        return None
    return {'ts': row[0], 'source': row[1], 'market_status': row[2],
            'by_grade': json.loads(row[3] or '{}'), 'rows': json.loads(row[4] or '[]'), 'error': row[5]}


def last_n_snapshots(con: sqlite3.Connection, n: int, *, day: str | None = None) -> list[dict[str, Any]]:
    """최근 n개 스냅샷, 오래된 것→최신 순. day 지정 시 그 날짜 안에서만(전일 스냅샷과 비교 금지)."""
    q = 'SELECT ts, source, market_status, by_grade, rows_json, error FROM snapshots'
    args: tuple = ()
    if day:
        q += ' WHERE day=?'
        args = (day,)
    q += ' ORDER BY id DESC LIMIT ?'
    rows = con.execute(q, args + (int(n),)).fetchall()
    out = [{'ts': r[0], 'source': r[1], 'market_status': r[2], 'by_grade': json.loads(r[3] or '{}'),
            'rows': json.loads(r[4] or '[]'), 'error': r[5]} for r in rows]
    out.reverse()
    return out


def today_event_keys(con: sqlite3.Connection, day: str) -> set[tuple[str, str]]:
    return {(t, c) for t, c in con.execute('SELECT type, code FROM events WHERE day=?', (day,))}


def save_events(con: sqlite3.Connection, events: list[dict[str, Any]]) -> int:
    n = 0
    for e in events:
        cur = con.execute(
            'INSERT OR IGNORE INTO events(ts, day, type, code, name, grade_from, grade_to, score, chg, payload) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (e['ts'], _day(e['ts']), e['type'], e['code'], e.get('name'), e.get('grade_from'),
             e.get('grade_to'), e.get('score'), e.get('chg'), json.dumps(e, ensure_ascii=False)))
        n += cur.rowcount
    return n


def pending_events(con: sqlite3.Connection, day: str | None = None, *,
                   include_prior: bool = False) -> list[dict[str, Any]]:
    """Return unreported events in FIFO order.

    ``events`` is also the per-day detection dedupe table.  Keeping pending
    rows here (rather than re-detecting them) lets failed and dry-run delivery
    attempts retry without producing duplicate event records.  ``include_prior``
    drains backlog through ``day`` while excluding malformed future-dated rows.
    """
    q = ('SELECT ts, type, code, name, grade_from, grade_to, score, chg, payload '
         'FROM events WHERE reported_at IS NULL')
    args: tuple[Any, ...] = ()
    if day is not None:
        q += ' AND day<=?' if include_prior else ' AND day=?'
        args = (day,)
    q += ' ORDER BY day, ts, id'
    rows = con.execute(q, args).fetchall()
    out: list[dict[str, Any]] = []
    keys = ('ts', 'type', 'code', 'name', 'grade_from', 'grade_to', 'score', 'chg')
    for row in rows:
        try:
            payload = json.loads(row[8] or '{}')
        except (TypeError, ValueError):
            payload = {}
        event = payload if isinstance(payload, dict) else {}
        for key, value in zip(keys, row[:8]):
            event.setdefault(key, value)
        out.append(event)
    return out


def mark_reported(con: sqlite3.Connection, events: list[dict[str, Any]], when: str) -> None:
    for e in events:
        con.execute('UPDATE events SET reported_at=? WHERE day=? AND type=? AND code=? AND reported_at IS NULL',
                    (when, _day(e['ts']), e['type'], e['code']))


def list_events(con: sqlite3.Connection, day: str) -> list[dict[str, Any]]:
    rows = con.execute(
        'SELECT ts, type, code, name, grade_from, grade_to, score, chg, reported_at FROM events WHERE day=? ORDER BY ts, id',
        (day,)).fetchall()
    keys = ['ts', 'type', 'code', 'name', 'grade_from', 'grade_to', 'score', 'chg', 'reported_at']
    return [dict(zip(keys, r)) for r in rows]


def save_regime(con: sqlite3.Connection, ts: str, reg: dict[str, Any]) -> None:
    con.execute('INSERT INTO regimes(ts, regime, breadth, halt, reasons) VALUES (?,?,?,?,?)',
                (ts, reg.get('regime'), reg.get('breadth_pct'), int(bool(reg.get('halt'))),
                 json.dumps(reg.get('reasons') or [], ensure_ascii=False)))


def last_regime(con: sqlite3.Connection) -> dict[str, Any] | None:
    row = con.execute(
        'SELECT ts, regime, breadth, halt, reasons FROM regimes ORDER BY id DESC LIMIT 1'
    ).fetchone()
    if not row:
        return None
    try:
        reasons = json.loads(row[4] or '[]')
    except (TypeError, ValueError):
        reasons = []
    return {'ts': row[0], 'regime': row[1], 'breadth_pct': row[2],
            'halt': bool(row[3]), 'reasons': reasons}


def current_halt_episode(con: sqlite3.Connection, day: str) -> dict[str, Any] | None:
    """Return the first row in today's current consecutive HALT episode."""
    iso_day = f'{day[:4]}-{day[4:6]}-{day[6:]}'
    row = con.execute(
        'SELECT ts, regime, breadth, halt, reasons FROM regimes '
        'WHERE substr(ts,1,10)=? AND halt=1 AND id > COALESCE(('
        '  SELECT MAX(id) FROM regimes WHERE substr(ts,1,10)=? AND halt=0'
        '), 0) ORDER BY id ASC LIMIT 1',
        (iso_day, iso_day),
    ).fetchone()
    if not row:
        return None
    try:
        reasons = json.loads(row[4] or '[]')
    except (TypeError, ValueError):
        reasons = []
    return {'ts': row[0], 'regime': row[1], 'breadth_pct': row[2],
            'halt': True, 'reasons': reasons}


def save_brief(con: sqlite3.Connection, kind: str, digest: str, path: str, delivered: bool, error: str | None) -> bool:
    """digest 당 1행. 나중 시도가 성공하면 delivered=1 로 승격되고, 성공 행은 실패로 되돌아가지 않는다."""
    cur = con.execute(
        'INSERT INTO briefs(ts, kind, digest, path, delivered, error) VALUES (?,?,?,?,?,?) '
        'ON CONFLICT(digest) DO UPDATE SET '
        '  ts=excluded.ts, path=excluded.path, '
        '  delivered=MAX(briefs.delivered, excluded.delivered), '
        '  error=CASE WHEN MAX(briefs.delivered, excluded.delivered)=1 THEN NULL ELSE excluded.error END',
        (datetime.now().isoformat(timespec='seconds'), kind, digest, path, int(delivered), error))
    return cur.rowcount == 1


def brief_exists(con: sqlite3.Connection, digest: str) -> bool:
    return con.execute('SELECT 1 FROM briefs WHERE digest=? AND delivered=1', (digest,)).fetchone() is not None


def stats(con: sqlite3.Connection, day: str) -> dict[str, Any]:
    snaps = con.execute('SELECT COUNT(*) FROM snapshots WHERE day=?', (day,)).fetchone()[0]
    evs = con.execute('SELECT COUNT(*) FROM events WHERE day=?', (day,)).fetchone()[0]
    briefs = con.execute('SELECT COUNT(*), COALESCE(SUM(delivered),0) FROM briefs WHERE substr(ts,1,10)=?',
                         (f'{day[:4]}-{day[4:6]}-{day[6:]}',)).fetchone()
    last = con.execute('SELECT ts, source FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
    return {'snapshots': snaps, 'events': evs, 'briefs': briefs[0], 'briefs_delivered': briefs[1],
            'last_snapshot_ts': last[0] if last else None, 'last_source': last[1] if last else None}
