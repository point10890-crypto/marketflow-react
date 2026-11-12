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
            # 저장되지 않을 봉의 근거 캡슐을 남기지 않도록 먼저 확인한다.
            if not bars.is_valid_bar(stock_code=code, session_date=session, basis=bars.BASIS_REGULAR,
                                     open=bar['open'], high=bar['high'], low=bar['low'], close=bar['close']):
                failed.append([code, session, 'invalid_bar'])
                continue
            # 응답만 해시한다. 수집 시각이 섞이면 같은 자료를 다시 받아도 해시가 달라져 재검증할 수 없다.
            responses = [page.get('response') if isinstance(page, dict) else page
                         for page in (result.get('pages') or [])]
            pages = json.dumps(responses, sort_keys=True, ensure_ascii=False).encode('utf-8')
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
                       reader: Callable[[str, str, str], Any] | None = None,
                       trading_day: clock.TradingDay | None = None) -> dict[str, int]:
    """어제까지의 공급자 일봉을 받아 저장한다. 최근 창은 덮어쓴다.

    아무것도 저장하지 못했거나 절반 넘는 종목이 실패·빈 응답이면 RuntimeError 를 낸다.
    그 전에 저장한 봉은 남는다.
    """
    read = reader or _read_daily
    is_trading_day = trading_day or clock.is_trading_day
    selected = [code for code in (codes if codes is not None else _listed_codes())
                if _STOCK_CODE.fullmatch(str(code))]
    # 종목마다 정한다. 전체 기준이면 첫 수집에서 실패한 종목이 끝내 긴 이력을 받지 못한다.
    known = {row[0] for row in conn.execute('SELECT DISTINCT stock_code FROM bars WHERE basis = ?',
                                            (bars.BASIS_UNIVERSE,))}
    day = date.fromisoformat(today)
    refresh_start = (day - timedelta(days=REFRESH_DAYS)).isoformat()
    initial_start = (day - timedelta(days=INITIAL_DAYS)).isoformat()
    end = (day - timedelta(days=1)).isoformat()
    captured = clock.iso(_now())
    stored = failed = empty = 0
    for index, code in enumerate(selected, start=1):
        try:
            frame = read(code, refresh_start if code in known else initial_start, end)
            if frame is None or len(frame) == 0:
                empty += 1
                continue
            for stamp, row in frame.iterrows():
                session = stamp.strftime('%Y-%m-%d')
                if session >= today:
                    continue
                # 거래일이 아닌 날짜의 봉 하나가 '최근 21거래일' 창을 밀어내 전 종목의 모멘텀을 막는다.
                if not is_trading_day(date.fromisoformat(session)):
                    continue
                if bars.put_bar(conn, stock_code=code, session_date=session, basis=bars.BASIS_UNIVERSE,
                                open=row['Open'], high=row['High'], low=row['Low'], close=row['Close'],
                                captured_at=captured, replace=True):
                    stored += 1
        except Exception:
            failed += 1
        finally:
            if index % 200 == 0:
                conn.commit()
    conn.commit()
    summary = {'codes': len(selected), 'stored': stored, 'failed': failed, 'empty': empty}
    if stored == 0 or (failed + empty) * 2 > len(selected):
        raise RuntimeError('universe sync incomplete: ' + ' '.join(f'{key}={value}' for key, value in summary.items()))
    return summary
