"""Row-level institutional evidence for new scans, evaluated at their own as-of."""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.services.institutional_collection_status import _required_session

KST = ZoneInfo('Asia/Seoul')


@lru_cache(maxsize=512)
def _trading_day(day):
    from app.services.kis_screener import _is_kr_trading_day
    return day.weekday() < 5 and _is_kr_trading_day(day)


def _integer(value):
    if isinstance(value,bool) or value is None:
        raise ValueError('invalid_integer')
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise ValueError('invalid_integer')
    return int(parsed)


def institutional_row_is_usable(row, *, as_of: datetime | None) -> bool:
    """Require the verified producer schema; never substitute file mtime for date.

    Use the same KR session deadline as source-quality monitoring (17:30).
    Intraday/replay availability is an additional caller-owned check.
    Legacy rows lacking an actual data_date cannot establish usable evidence.
    """
    if not isinstance(row,dict) or not isinstance(as_of,datetime):
        return False
    try:
        if row.get('data_source') != 'naver_finance_trend_api':
            return False
        moment = (as_of if as_of.tzinfo else as_of.replace(tzinfo=KST)).astimezone(KST)
        source = date.fromisoformat(str(row['data_date']))
        scraped = date.fromisoformat(str(row['scrape_date']))
        if not (_required_session(moment) <= source <= scraped <= moment.date()):
            return False
        if not _trading_day(source) or not 5 <= _integer(row['total_days']) <= 60:
            return False
        _integer(row['foreign_net_buy_5d'])
        _integer(row['institutional_net_buy_5d'])
        return True
    except (ValueError,TypeError,KeyError,OverflowError,InvalidOperation):
        return False


def institutional_row_is_available(row, *, as_of: datetime, file_observed_at: datetime) -> bool:
    """A file-backed new scan cannot use a daily row before close or acquisition."""
    if not institutional_row_is_usable(row, as_of=as_of) or not isinstance(file_observed_at,datetime):
        return False
    moment = (as_of if as_of.tzinfo else as_of.replace(tzinfo=KST)).astimezone(KST)
    observed = (file_observed_at if file_observed_at.tzinfo else file_observed_at.replace(tzinfo=KST)).astimezone(KST)
    source_close = datetime.combine(date.fromisoformat(str(row['data_date'])),time(15,30),tzinfo=KST)
    return source_close <= moment and observed <= moment and observed.date() >= date.fromisoformat(str(row['scrape_date']))
