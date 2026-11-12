"""리그 전용 가격 봉.

krx_regular    정규장(09:00~15:30) 봉. 해소·채점에만 쓴다. 한 번 저장하면 바꾸지 않는다.
provider_daily 공급자 일봉. 정규장 보증이 없어 기준선의 입력 추정치로만 쓴다.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

BASIS_REGULAR = 'krx_regular'
BASIS_UNIVERSE = 'provider_daily'
REGULAR_SOURCE_VERSION = 'krx_regular/kis-regular-j-minute-v1'
_BASES = frozenset({BASIS_REGULAR, BASIS_UNIVERSE})


def _valid(session_date: str, basis: str, open_: float, high: float, low: float, close: float) -> bool:
    try:
        if basis not in _BASES or date.fromisoformat(session_date).isoformat() != session_date:
            return False
        open_, high, low, close = float(open_), float(high), float(low), float(close)
    except (TypeError, ValueError):
        return False
    return min(open_, high, low, close) > 0 and low <= min(open_, close) and high >= max(open_, close)


def put_bar(conn: sqlite3.Connection, *, stock_code: str, session_date: str, basis: str,
            open: float, high: float, low: float, close: float, captured_at: str,
            evidence_hash: str | None = None, replace: bool = False) -> bool:
    """저장했으면 True. 값이 봉으로 성립하지 않거나 이미 있으면 False."""
    if replace and basis == BASIS_REGULAR:
        raise ValueError('regular-session bars are never replaced')
    if not _valid(session_date, basis, open, high, low, close):
        return False
    verb = 'INSERT OR REPLACE' if replace else 'INSERT OR IGNORE'
    cursor = conn.execute(
        f'{verb} INTO bars (stock_code, session_date, basis, open, high, low, close, captured_at, evidence_hash) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (stock_code, session_date, basis, float(open), float(high), float(low), float(close),
         captured_at, evidence_hash))
    return cursor.rowcount == 1


def get_bars(conn: sqlite3.Connection, stock_code: str, basis: str, start_date: str,
             end_date: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        'SELECT session_date AS date, open, high, low, close FROM bars '
        'WHERE stock_code = ? AND basis = ? AND session_date >= ? AND session_date <= ? ORDER BY session_date',
        (stock_code, basis, start_date, end_date or '9999-12-31')).fetchall()
    return [dict(row) for row in rows]
