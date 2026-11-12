"""미해소 예측 해소. 정규장 봉만 쓰고, 같은 예측을 다시 해소해도 행이 늘지 않는다."""
from __future__ import annotations

import sqlite3

from app.services.forecast_league import bars, clock, events
from app.services.mirofish import costs

VOID_AFTER_SESSIONS = 20


def _now():
    return clock.now_utc()


def entry_date(asof_ts: str, trading_day: clock.TradingDay | None = None) -> str:
    """기준 시각 뒤 첫 정규장의 날짜."""
    return clock.kst_date(clock.next_session_open_after(clock.parse_ts(asof_ts), trading_day))


def unresolved(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        'SELECT f.forecast_id, f.stock_code, f.asof_ts FROM forecasts f '
        'LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE r.forecast_id IS NULL AND f.event_id = 'E1' ORDER BY f.asof_ts, f.forecast_id").fetchall()


def resolve_pending(conn: sqlite3.Connection, *, today: str,
                    trading_day: clock.TradingDay | None = None) -> dict[str, int]:
    summary = {'resolved': 0, 'void': 0, 'pending': 0}
    cost = costs.round_trip_cost_pct()
    for row in unresolved(conn):
        first = entry_date(row['asof_ts'], trading_day)
        expected = clock.trading_days(first, today, trading_day) if first <= today else []
        stored = {bar['date']: bar for bar in bars.get_bars(conn, row['stock_code'], bars.BASIS_REGULAR, first, today)}
        sequence = []
        for day in expected[:events.E1_MAX_SESSIONS]:
            if day not in stored:
                break
            sequence.append(stored[day])
        result = events.evaluate_e1(sequence, cost_pct=cost)
        if result is not None:
            conn.execute(
                'INSERT OR IGNORE INTO resolutions (forecast_id, status, outcome, resolved_at, entry_date, '
                "entry_price, exit_date, exit_price, exit_reason, net_return, price_source_version) "
                "VALUES (?, 'resolved', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row['forecast_id'], result['outcome'], clock.iso(_now()), result['entry_date'],
                 result['entry_price'], result['exit_date'], result['exit_price'], result['exit_reason'],
                 result['net_return_pct'], bars.REGULAR_SOURCE_VERSION))
            summary['resolved'] += 1
        elif len(expected) > VOID_AFTER_SESSIONS:
            conn.execute(
                'INSERT OR IGNORE INTO resolutions (forecast_id, status, resolved_at, price_source_version) '
                "VALUES (?, 'void', ?, ?)",
                (row['forecast_id'], clock.iso(_now()), bars.REGULAR_SOURCE_VERSION))
            summary['void'] += 1
        else:
            summary['pending'] += 1
    return summary
