"""사건(incident) 판정 — 한 번의 실패로 소란 떨지 않고, 고쳐지면 스스로 닫는다.

규칙
- fail 이 `open_after` 번 연속이면 사건을 연다 (순간적인 끊김은 사건이 아니다).
- ok 가 `resolve_after` 번 연속이면 닫는다. unknown 은 열지도 닫지도 않는다.
- warn 은 사건을 만들지 않고 화면에만 보인다.
- 닫힌 지 FLAP_WINDOW 안에 다시 열리면 '깜빡임' 으로 표시하고, 치명(critical)이 아니면 알림을 생략한다.
- severity 'info' 항목은 사건을 기록하되 알림을 보내지 않는다.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from app.services.control_center import store
from app.services.control_center.model import CheckResult, iso, now_kst

FLAP_WINDOW = timedelta(minutes=30)
OPEN_AFTER = {'endpoint': 2, 'process': 2, 'page': 2}       # 그 밖의 family 는 1 (이미 유예가 들어간 판정)
RESOLVE_AFTER = 2


def open_after(family: str) -> int:
    return OPEN_AFTER.get(family, 1)


def apply(conn: sqlite3.Connection, r: CheckResult, tier: str) -> dict[str, Any] | None:
    """결과 하나를 상태에 반영하고, 사건이 열리거나 닫히면 그 변화를 돌려준다."""
    prev = store.get_state(conn, r.id) or {}
    fails, oks = int(prev.get('consec_fail') or 0), int(prev.get('consec_ok') or 0)
    if r.status == 'fail':
        fails, oks = fails + 1, 0
    elif r.status == 'ok':
        fails, oks = 0, oks + 1
    else:
        fails, oks = 0, 0
    changed = prev.get('status') != r.status
    store.put_state(conn, r, tier, fails, oks, r.observed_at if changed or not prev else prev.get('last_change_at'))

    current = conn.execute('SELECT * FROM incidents WHERE check_id=? AND resolved_at IS NULL', (r.id,)).fetchone()
    if r.status == 'fail':
        if current:
            conn.execute('UPDATE incidents SET occurrences=occurrences+1, last_status=?, last_detail=? WHERE id=?',
                         (r.status, r.detail[:500], current['id']))
            return None
        if fails < open_after(r.family):
            return None
        last = conn.execute('SELECT resolved_at FROM incidents WHERE check_id=? AND resolved_at IS NOT NULL'
                            ' ORDER BY resolved_at DESC LIMIT 1', (r.id,)).fetchone()
        flapping = 0
        if last and last['resolved_at']:
            try:
                flapping = int(now_kst() - datetime.fromisoformat(last['resolved_at']) < FLAP_WINDOW)
            except ValueError:
                flapping = 0
        cur = conn.execute(
            'INSERT INTO incidents (check_id, family, target, severity, opened_at, last_status, last_detail, flapping)'
            ' VALUES (?,?,?,?,?,?,?,?)', (r.id, r.family, r.target, r.severity, r.observed_at, r.status, r.detail[:500], flapping))
        return {'kind': 'open', 'incident_id': int(cur.lastrowid), 'check_id': r.id, 'family': r.family,
                'target': r.target, 'severity': r.severity, 'detail': r.detail, 'flapping': bool(flapping)}
    if current and r.status == 'ok' and oks >= RESOLVE_AFTER:
        conn.execute('UPDATE incidents SET resolved_at=?, last_status=?, last_detail=? WHERE id=?',
                     (iso(now_kst()), r.status, r.detail[:500], current['id']))
        return {'kind': 'resolve', 'incident_id': int(current['id']), 'check_id': r.id, 'family': r.family,
                'target': r.target, 'severity': current['severity'], 'detail': r.detail,
                'opened_at': current['opened_at']}
    return None


def should_alert(change: dict[str, Any]) -> bool:
    if change['severity'] == 'info':
        return False
    if change.get('flapping') and change['severity'] != 'critical':
        return False
    return True
