"""관제 기록 저장소 — SQLite (결과·상태·사건·이벤트) + latest.json 스냅샷.

- results: 관측 원본 (보존 기간 RETENTION_DAYS, 오래된 것은 run 때마다 정리)
- check_state: 항목별 현재 상태와 연속 실패/정상 횟수 (사건 판정용)
- incidents: 열림/해소 이력 (사후 수정하지 않고 상태만 갱신)
- events: 알림 발송·조치 제안 등 감사 로그 (추가만)
여러 tier 실행기가 동시에 쓸 수 있으므로 WAL + busy_timeout 을 쓴다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator

from app.services.control_center import cc_dir
from app.services.control_center.model import CheckResult, iso, now_kst

RETENTION_DAYS = 14
DB_NAME = 'control_center.sqlite3'

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tier TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, overall TEXT, counts_json TEXT, pid INTEGER
);
CREATE TABLE IF NOT EXISTS results (
  run_id INTEGER, check_id TEXT NOT NULL, family TEXT NOT NULL, target TEXT, status TEXT NOT NULL,
  severity TEXT, latency_ms INTEGER, detail TEXT, value_json TEXT, observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_results_check ON results(check_id, observed_at);
CREATE INDEX IF NOT EXISTS ix_results_time ON results(observed_at);
CREATE TABLE IF NOT EXISTS check_state (
  check_id TEXT PRIMARY KEY, family TEXT, target TEXT, severity TEXT, status TEXT, detail TEXT,
  latency_ms INTEGER, value_json TEXT, data_json TEXT, tier TEXT,
  consec_fail INTEGER DEFAULT 0, consec_ok INTEGER DEFAULT 0,
  last_change_at TEXT, last_observed_at TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, check_id TEXT NOT NULL, family TEXT, target TEXT,
  severity TEXT, opened_at TEXT NOT NULL, resolved_at TEXT, last_status TEXT, last_detail TEXT,
  occurrences INTEGER DEFAULT 1, flapping INTEGER DEFAULT 0, alerted_open INTEGER DEFAULT 0,
  alerted_resolve INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_incidents_open ON incidents(resolved_at, check_id);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT, payload_json TEXT
);
"""


def db_path(base_dir: str | None = None) -> str:
    return os.path.join(base_dir or cc_dir(), DB_NAME)


@contextmanager
def connect(base_dir: str | None = None, *, read_only: bool = False) -> Iterator[sqlite3.Connection | None]:
    path = db_path(base_dir)
    if read_only:
        try:
            conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        except sqlite3.OperationalError:
            if not os.path.isfile(path):
                yield None
                return
            raise
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        if read_only:
            # A reader may arrive before the first writer has created its tables.
            conn.execute('BEGIN')
            ready = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='check_state'").fetchone()
            yield conn if ready else None
        else:
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript(SCHEMA)
            yield conn
            conn.commit()
    finally:
        conn.close()


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def start_run(conn: sqlite3.Connection, tier: str, started_at: str | None = None) -> int:
    cur = conn.execute('INSERT INTO runs (tier, started_at, pid) VALUES (?, ?, ?)', (tier, started_at or iso(now_kst()), os.getpid()))
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, overall: str, counts: dict[str, int]) -> None:
    conn.execute('UPDATE runs SET finished_at=?, overall=?, counts_json=? WHERE id=?',
                 (iso(now_kst()), overall, _dumps(counts), run_id))


def record_results(conn: sqlite3.Connection, run_id: int, results: list[CheckResult]) -> None:
    conn.executemany(
        'INSERT INTO results (run_id, check_id, family, target, status, severity, latency_ms, detail, value_json, observed_at)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?)',
        [(run_id, r.id, r.family, r.target, r.status, r.severity, r.latency_ms, r.detail[:500], _dumps(r.value), r.observed_at)
         for r in results])


def prune(conn: sqlite3.Connection, days: int = RETENTION_DAYS) -> None:
    cutoff = iso(now_kst() - timedelta(days=days))
    conn.execute('DELETE FROM results WHERE observed_at < ?', (cutoff,))
    conn.execute('DELETE FROM runs WHERE started_at < ? AND id NOT IN ('
                 'SELECT MAX(id) FROM runs WHERE finished_at IS NOT NULL GROUP BY tier)', (cutoff,))
    conn.execute('DELETE FROM events WHERE at < ?', (cutoff,))
    conn.execute('DELETE FROM incidents WHERE resolved_at < ?', (cutoff,))
    conn.execute('DELETE FROM check_state WHERE last_observed_at < ? AND check_id NOT IN ('
                 'SELECT check_id FROM incidents WHERE resolved_at IS NULL)', (cutoff,))


def get_state(conn: sqlite3.Connection, check_id: str) -> dict[str, Any] | None:
    row = conn.execute('SELECT * FROM check_state WHERE check_id=?', (check_id,)).fetchone()
    return dict(row) if row else None


def put_state(conn: sqlite3.Connection, r: CheckResult, tier: str, consec_fail: int, consec_ok: int,
              last_change_at: str | None) -> None:
    conn.execute(
        'INSERT INTO check_state (check_id, family, target, severity, status, detail, latency_ms, value_json, data_json, tier,'
        ' consec_fail, consec_ok, last_change_at, last_observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
        ' ON CONFLICT(check_id) DO UPDATE SET family=excluded.family, target=excluded.target, severity=excluded.severity,'
        ' status=excluded.status, detail=excluded.detail, latency_ms=excluded.latency_ms, value_json=excluded.value_json,'
        ' data_json=excluded.data_json, tier=excluded.tier, consec_fail=excluded.consec_fail, consec_ok=excluded.consec_ok,'
        ' last_change_at=excluded.last_change_at, last_observed_at=excluded.last_observed_at',
        (r.id, r.family, r.target, r.severity, r.status, r.detail[:500], r.latency_ms, _dumps(r.value), _dumps(r.data),
         tier, consec_fail, consec_ok, last_change_at, r.observed_at))


def all_states(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for row in conn.execute('SELECT * FROM check_state ORDER BY family, check_id'):
        d = dict(row)
        d['value'] = json.loads(d.pop('value_json')) if d.get('value_json') else None
        d['data'] = json.loads(d.pop('data_json')) if d.get('data_json') else {}
        out.append(d)
    return out


def open_incidents(conn: sqlite3.Connection, limit: int = -1) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        'SELECT * FROM incidents WHERE resolved_at IS NULL ORDER BY opened_at DESC, id DESC LIMIT ?', (limit,))]


def recent_incidents(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute('SELECT * FROM incidents ORDER BY opened_at DESC LIMIT ?', (limit,))]


def history(conn: sqlite3.Connection, check_id: str, hours: float = 24, limit: int = 500) -> list[dict[str, Any]]:
    cutoff = iso(now_kst() - timedelta(hours=hours))
    rows = conn.execute('SELECT status, latency_ms, detail, observed_at FROM results WHERE check_id=? AND observed_at>=?'
                        ' ORDER BY observed_at DESC LIMIT ?', (check_id, cutoff, limit))
    return [dict(r) for r in rows]


def add_event(conn: sqlite3.Connection, kind: str, ref: str | None, payload: dict[str, Any]) -> None:
    conn.execute('INSERT INTO events (at, kind, ref, payload_json) VALUES (?,?,?,?)', (iso(now_kst()), kind, ref, _dumps(payload)))


def write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        for attempt in range(4):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 3:
                    raise
                time.sleep(0.025 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None
