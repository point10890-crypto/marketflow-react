"""리그 가격 봉 수집.

정규장 봉은 기존 KISRegularProvider(분봉 09:00~15:30 재구성)로 받는다.
유니버스 봉은 공급자 일봉이며 당일 봉은 저장하지 않는다 — 장 마감 후에도 값이 바뀌는 것을 확인했다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Iterable

from app.services.forecast_league import bars, capsules, clock, events, resolver

REGULAR_READY = time(20, 40)          # 공급자의 수집 가능 시각(20:30)에 여유 10분
INITIAL_DAYS = 420
REFRESH_DAYS = 45
_STOCK_CODE = re.compile(r'[0-9]{6}')


def _now() -> datetime:
    return clock.now_utc()


def needed_regular_targets(conn: sqlite3.Connection, *, now: datetime,
                           trading_day: clock.TradingDay | None = None) -> list[tuple[str, str]]:
    """미해소 예측의 판정에 필요한데 아직 없는 (종목, 거래일)."""
    local = now.astimezone(clock.KST)
    last = local.date() if local.time() >= REGULAR_READY else local.date() - timedelta(days=1)
    targets: set[tuple[str, str]] = set()
    for row in resolver.unresolved(conn):
        first = resolver.entry_date(row['asof_ts'], trading_day)
        if first > last.isoformat():
            continue
        for day in clock.trading_days(first, last.isoformat(), trading_day)[:events.E1_MAX_SESSIONS]:
            targets.add((row['stock_code'], day))
    existing = {(row[0], row[1]) for row in conn.execute(
        'SELECT stock_code, session_date FROM bars WHERE basis = ?', (bars.BASIS_REGULAR,))}
    return sorted(targets - existing)


def collect_regular_bars(conn: sqlite3.Connection, *, provider: Any,
                         targets: Iterable[tuple[str, str]]) -> dict[str, Any]:
    stored, failed = 0, []
    for code, session in targets:
        try:
            result = provider.fetch_session(code, session)
            bar = result['bar']
            pages = json.dumps(result.get('pages'), sort_keys=True, ensure_ascii=False).encode('utf-8')
            evidence = capsules.put_capsule(conn, {
                'stock_code': code, 'session': session, 'bar': bar, 'captured_at': result['captured_at'],
                'source_version': (result.get('source') or {}).get('version'),
                'pages_sha256': hashlib.sha256(pages).hexdigest()})
            if bars.put_bar(conn, stock_code=code, session_date=session, basis=bars.BASIS_REGULAR,
                            open=bar['open'], high=bar['high'], low=bar['low'], close=bar['close'],
                            captured_at=result['captured_at'], evidence_hash=evidence):
                stored += 1
            conn.commit()
        except Exception as error:   # 한 종목의 실패가 나머지를 막지 않는다
            conn.rollback()
            failed.append([code, session, str(getattr(error, 'code', type(error).__name__))])
    return {'stored': stored, 'failed': failed}


def _listed_codes() -> list[str]:
    import FinanceDataReader as fdr
    return [str(code) for code in fdr.StockListing('KRX')['Code']]


def _read_daily(code: str, start: str, end: str):
    import FinanceDataReader as fdr
    return fdr.DataReader(code, start, end)


def sync_universe_bars(conn: sqlite3.Connection, *, today: str, codes: Iterable[str] | None = None,
                       reader: Callable[[str, str, str], Any] | None = None) -> dict[str, int]:
    """어제까지의 공급자 일봉을 받아 저장한다. 최근 창은 덮어쓴다."""
    read = reader or _read_daily
    selected = [code for code in (codes if codes is not None else _listed_codes())
                if _STOCK_CODE.fullmatch(str(code))]
    has_any = conn.execute('SELECT 1 FROM bars WHERE basis = ? LIMIT 1', (bars.BASIS_UNIVERSE,)).fetchone()
    day = date.fromisoformat(today)
    start = (day - timedelta(days=REFRESH_DAYS if has_any else INITIAL_DAYS)).isoformat()
    end = (day - timedelta(days=1)).isoformat()
    captured = clock.iso(_now())
    stored = failed = 0
    for index, code in enumerate(selected, start=1):
        try:
            frame = read(code, start, end)
            for stamp, row in (frame.iterrows() if frame is not None else ()):
                session = stamp.strftime('%Y-%m-%d')
                if session >= today:
                    continue
                if bars.put_bar(conn, stock_code=code, session_date=session, basis=bars.BASIS_UNIVERSE,
                                open=row['Open'], high=row['High'], low=row['Low'], close=row['Close'],
                                captured_at=captured, replace=True):
                    stored += 1
        except Exception:
            failed += 1
        if index % 200 == 0:
            conn.commit()
    conn.commit()
    return {'codes': len(selected), 'stored': stored, 'failed': failed}
