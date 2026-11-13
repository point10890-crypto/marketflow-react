"""영속 잡 큐. 같은 dedupe_key 는 한 번만 들어간다."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any

from app.services.forecast_league import clock

MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=5)


def _now():
    return clock.now_utc()


def enqueue(conn: sqlite3.Connection, kind: str, args: dict[str, Any], dedupe_key: str,
            *, depends_on: str | None = None, require_success: bool = True) -> bool:
    stamp = clock.iso(_now())
    cursor = conn.execute(
        'INSERT OR IGNORE INTO jobs (kind, args, dedupe_key, status, attempts, not_before, created_at, updated_at) '
        "VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)",
        (kind, json.dumps(args, sort_keys=True), dedupe_key, stamp, stamp, stamp))
    added = cursor.rowcount == 1
    if depends_on:
        parent = conn.execute('SELECT job_id FROM jobs WHERE dedupe_key=?', (depends_on,)).fetchone()
        if parent is None:
            raise ValueError('missing job dependency')
        child = conn.execute('SELECT job_id FROM jobs WHERE dedupe_key=?', (dedupe_key,)).fetchone()
        conn.execute('INSERT OR IGNORE INTO job_dependencies VALUES (?,?,?)', (child[0], parent[0], int(require_success)))
    return added


def recover_running(conn: sqlite3.Connection) -> int:
    """중단된 실행이 남긴 running 잡을 대기 상태로 되돌린다."""
    cursor = conn.execute("UPDATE jobs SET status = CASE WHEN attempts >= ? THEN 'failed' ELSE 'queued' END, "
                          "updated_at = ? WHERE status = 'running'", (MAX_ATTEMPTS, clock.iso(_now())))
    return cursor.rowcount


def claim_next(conn: sqlite3.Connection) -> dict[str, Any] | None:
    stamp = clock.iso(_now())
    # Propagate terminal prerequisite failure; unrelated/new-date jobs stay runnable.
    while conn.execute("UPDATE jobs SET status='blocked', last_error='prerequisite_failed', updated_at=? "
                       "WHERE status='queued' AND EXISTS (SELECT 1 FROM job_dependencies d JOIN jobs p "
                       "ON p.job_id=d.parent_id WHERE d.job_id=jobs.job_id AND d.require_success=1 AND p.status IN ('failed','blocked'))",
                       (stamp,)).rowcount:
        pass
    row = conn.execute("UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE job_id=("
                       "SELECT j.job_id FROM jobs j WHERE j.status='queued' AND j.not_before<=? "
                       "AND j.attempts<? AND NOT EXISTS (SELECT 1 FROM job_dependencies d JOIN jobs p "
                       "ON p.job_id=d.parent_id WHERE d.job_id=j.job_id AND p.status!='done' AND (d.require_success=1 OR p.status NOT IN ('failed','blocked'))) "
                       "ORDER BY j.job_id LIMIT 1) RETURNING *", (stamp, stamp, MAX_ATTEMPTS)).fetchone()
    if row is None:
        return None
    return dict(row)


def complete(conn: sqlite3.Connection, job_id: int, result: Any) -> None:
    conn.execute("UPDATE jobs SET status = 'done', result = ?, last_error = NULL, updated_at = ? WHERE job_id = ?",
                 (json.dumps(result, sort_keys=True, default=str), clock.iso(_now()), job_id))


def fail(conn: sqlite3.Connection, job_id: int, error: str) -> bool:
    """실패를 기록한다. 더 재시도하지 않으면 True."""
    attempts = conn.execute('SELECT attempts FROM jobs WHERE job_id = ?', (job_id,)).fetchone()['attempts']
    final = attempts >= MAX_ATTEMPTS
    now = _now()
    conn.execute('UPDATE jobs SET status = ?, last_error = ?, not_before = ?, updated_at = ? WHERE job_id = ?',
                 ('failed' if final else 'queued', error[:500], clock.iso(now + RETRY_DELAY), clock.iso(now), job_id))
    return final


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {row['status']: row['n'] for row in conn.execute('SELECT status, COUNT(*) AS n FROM jobs GROUP BY status')}
