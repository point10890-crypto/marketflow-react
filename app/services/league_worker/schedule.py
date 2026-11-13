"""시간대별로 넣을 잡. scheduler.py 는 이 함수만 부른다."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.services.forecast_league import clock
from app.services.league_worker import jobs


def enqueue_slot(conn: sqlite3.Connection, slot: str, today: date,
                 trading_day: clock.TradingDay | None = None) -> int:
    day = today.isoformat()
    if slot not in ('morning', 'evening'):
        raise ValueError(f'unknown slot: {slot}')
    if not (trading_day or clock.is_trading_day)(today):
        return 0
    if slot == 'morning':
        asof = clock.previous_trading_day(today, trading_day).isoformat()
        planned = [('sync_universe', {'today': day}, f'sync_universe:{day}'),
                   ('submit_baselines', {'asof_date': asof}, f'submit_baselines:{asof}')]
    elif slot == 'evening':
        planned = [(kind, {'today': day}, f'{kind}:{day}') for kind in ('collect_regular', 'resolve', 'score')]
    else:
        raise ValueError(f'unknown slot: {slot}')
    added, parent = 0, None
    for kind, args, key in planned:
        added += jobs.enqueue(conn, kind, args, key, depends_on=parent, require_success=kind != 'resolve')
        parent = key
    return added
