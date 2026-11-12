"""KST 시각, 거래일, 제출 마감 계산."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

KST = timezone(timedelta(hours=9))
SESSION_OPEN = time(9, 0)
TradingDay = Callable[[date], bool]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime:
    """UTC 오프셋이 있는 ISO 시각만 받는다."""
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('timestamp needs a UTC offset')
    return parsed.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def kst_date(value: datetime) -> str:
    return value.astimezone(KST).date().isoformat()


def close_ts(session_date: str) -> str:
    return f'{session_date}T15:30:00+09:00'


def is_trading_day(day: date) -> bool:
    """KRX 거래일 여부. 판정기를 못 부르면 평일은 거래일로 본다."""
    if day.weekday() >= 5:
        return False
    try:
        from app.services.kis_screener import _is_kr_trading_day
        return bool(_is_kr_trading_day(datetime.combine(day, time.min)))
    except Exception:
        return True


def next_session_open_after(ts: datetime, trading_day: TradingDay | None = None) -> datetime:
    """ts 보다 뒤에 오는 첫 정규장 시작 시각(UTC)."""
    check = trading_day or is_trading_day
    local = ts.astimezone(KST)
    day = local.date()
    for _ in range(30):
        opening = datetime.combine(day, SESSION_OPEN, KST)
        if check(day) and local < opening:
            return opening.astimezone(timezone.utc)
        day += timedelta(days=1)
    raise ValueError('no trading session within 30 days')


def trading_days(start: str, end: str, trading_day: TradingDay | None = None) -> list[str]:
    """start~end(포함) 사이의 거래일 목록."""
    check = trading_day or is_trading_day
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    days: list[str] = []
    while day <= last:
        if check(day):
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def previous_trading_day(day: date, trading_day: TradingDay | None = None) -> date:
    check = trading_day or is_trading_day
    cursor = day - timedelta(days=1)
    for _ in range(30):
        if check(cursor):
            return cursor
        cursor -= timedelta(days=1)
    raise ValueError('no trading session within 30 days')
