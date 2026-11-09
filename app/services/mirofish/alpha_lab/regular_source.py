"""Date-addressed KIS J minute evidence for the latest regular-session OHLC.

This cross-check uses a different KIS endpoint, not an independent exchange
feed or certified historical corporate-action data. Persist only public rows.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re

from .daily_source import DailySourceError, _clock, _cutoff, _session, _stamp, _symbol
from .market_provider import MarketDataError, _kis_request

_OPEN = '090000'
_CLOSE = '153000'
SOURCE_CONTRACT = dict(
    version='kis-regular-j-minute-v1', provider='KIS', market='J',
    tr_id='FHKST03010230',
    path='/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice',
    open_kst=_OPEN, close_kst=_CLOSE, acquisition_buffer_kst='203000',
    page_rows=120, max_pages=5, cursor='earliest_returned_time_minus_one_minute',
    request_timeout_seconds=10, past_data='N', fake_tick='',
    price_basis='KIS_J_regular_session_minute_OHLC',
    volume_basis='sum_regular_minute_cntg_vol',
    traded_value_basis='closing_minute_acml_tr_pbmn_when_available',
    verification_basis='same_provider_cross_endpoint',
    independent_krx_certification=False, historical_corporate_action_certification=False,
)
_FIELDS = dict(open='stck_oprc', high='stck_hgpr', low='stck_lwpr',
               close='stck_prpr', volume='cntg_vol')
_IDENTITIES = ('stck_shrn_iscd', 'symbol')
_CODES = {
    'invalid_symbol', 'invalid_clock', 'regular_session', 'regular_session_incomplete',
    'regular_payload', 'regular_identity', 'regular_page_size', 'regular_cursor',
    'regular_duplicate_conflict', 'regular_ohlcv', 'regular_boundaries',
    'regular_page_limit', 'regular_replay', 'kis_token_unavailable',
    'kis_transport_failure', 'kis_http_failure', 'kis_api_failure', 'kis_payload_invalid',
}


class RegularSourceError(ValueError):
    """Expose bounded reason codes, never request errors or response bodies."""

    def __init__(self, code):
        self.code = code if code in _CODES else 'kis_transport_failure'
        super().__init__(self.code)


def _target(symbol, session):
    try:
        return _symbol(symbol), _session(session)
    except DailySourceError as exc:
        raise RegularSourceError('regular_session' if exc.code == 'daily_session' else exc.code) from None


def _time(value):
    try:
        return _clock(value)
    except DailySourceError as exc:
        raise RegularSourceError(exc.code) from None


def _params(symbol, session, cursor):
    return dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=symbol,
                FID_INPUT_DATE_1=session.replace('-', ''), FID_INPUT_HOUR_1=cursor,
                FID_PW_DATA_INCU_YN='N', FID_FAKE_TICK_INCU_YN='')


def _number(value, *, integral=False, positive=False, maximum=1e20):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RegularSourceError('regular_ohlcv')
    if isinstance(value, str) and not re.fullmatch(r'[0-9]{1,21}(?:\.[0-9]{1,12})?', value):
        raise RegularSourceError('regular_ohlcv')
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise RegularSourceError('regular_ohlcv') from None
    if (not math.isfinite(number) or not 0 <= number <= maximum
            or positive and number == 0 or integral and not number.is_integer()):
        raise RegularSourceError('regular_ohlcv')
    return int(number) if integral else number


def _identity(raw, symbol):
    for key in _IDENTITIES:
        if key in raw and raw[key] != symbol:
            raise RegularSourceError('regular_identity')
    return {key: symbol for key in _IDENTITIES if key in raw}


def _row(raw, symbol, day):
    if not isinstance(raw, dict):
        raise RegularSourceError('regular_payload')
    public = _identity(raw, symbol)
    if raw.get('stck_bsop_date') != day:
        raise RegularSourceError('regular_session')
    hms = raw.get('stck_cntg_hour')
    if not isinstance(hms, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3])[0-5][0-9]00', hms):
        raise RegularSourceError('regular_cursor')
    public.update(stck_bsop_date=day, stck_cntg_hour=hms)
    bar = {}
    for key, field in _FIELDS.items():
        volume = key == 'volume'
        bar[key] = _number(raw.get(field), integral=volume, positive=not volume,
                           maximum=1e15 if volume else 1e12)
        public[field] = raw[field]
    if not (bar['low'] <= min(bar['open'], bar['close'])
            <= max(bar['open'], bar['close']) <= bar['high']):
        raise RegularSourceError('regular_ohlcv')
    bar['traded_value'] = None
    if 'acml_tr_pbmn' in raw:
        try:
            bar['traded_value'] = _number(raw['acml_tr_pbmn'])
        except RegularSourceError:
            pass  # Optional and never used as the canonical daily turnover.
        else:
            public['acml_tr_pbmn'] = raw['acml_tr_pbmn']
    return hms, bar, public


def _page(body, params, found):
    if not isinstance(body, dict) or body.get('rt_cd') != '0':
        raise RegularSourceError('regular_payload')
    raw_rows, metadata = body.get('output2'), body.get('output1')
    if not isinstance(raw_rows, list) or not isinstance(metadata, dict):
        raise RegularSourceError('regular_payload')
    if not 1 <= len(raw_rows) <= SOURCE_CONTRACT['page_rows']:
        raise RegularSourceError('regular_page_size')
    symbol, day = params['FID_INPUT_ISCD'], params['FID_INPUT_DATE_1']
    cursor = params['FID_INPUT_HOUR_1']
    public_meta = _identity(metadata, symbol)
    public_rows, previous = [], cursor
    for raw in raw_rows:
        hms, bar, public = _row(raw, symbol, day)
        if hms in found and found[hms] != bar:
            raise RegularSourceError('regular_duplicate_conflict')
        if hms > previous:
            raise RegularSourceError('regular_cursor')
        previous = hms
        found[hms] = bar
        public_rows.append(public)
    result = dict(rt_cd='0', output1=public_meta, output2=public_rows)
    if previous <= _OPEN:
        return result, None
    earliest = datetime.strptime(previous, '%H%M%S')
    # KIS rounds nonzero seconds up and would return this same minute again.
    next_cursor = (earliest - timedelta(minutes=1)).strftime('%H%M%S')
    if next_cursor >= cursor:
        raise RegularSourceError('regular_cursor')
    return result, next_cursor


def _aggregate(found):
    first, last = found.get(_OPEN), found.get(_CLOSE)
    if not first or not last or not first['volume'] or not last['volume']:
        raise RegularSourceError('regular_boundaries')
    regular = [bar for hms, bar in found.items() if _OPEN <= hms <= _CLOSE]
    return dict(open=first['open'], high=max(bar['high'] for bar in regular),
                low=min(bar['low'] for bar in regular), close=last['close'],
                volume=sum(bar['volume'] for bar in regular), traded_value=last['traded_value'])


def _result(symbol, session, found, pages, first, last):
    return dict(symbol=symbol, session=session, bar=_aggregate(found), pages=pages,
                captured_at=_stamp(last), capture=dict(first=_stamp(first), last=_stamp(last)),
                source=deepcopy(SOURCE_CONTRACT))


class KISRegularProvider:
    def __init__(self, request=None, clock=None):
        self.request = _kis_request if request is None else request
        self.clock = (lambda: datetime.now(timezone.utc)) if clock is None else clock

    def _now(self):
        try:
            return _time(self.clock())
        except RegularSourceError:
            raise
        except Exception:
            raise RegularSourceError('invalid_clock') from None

    def _get(self, params):
        try:
            response = self.request(SOURCE_CONTRACT['path'], SOURCE_CONTRACT['tr_id'], dict(params))
        except MarketDataError as exc:
            raise RegularSourceError(exc.code) from None
        except Exception:
            raise RegularSourceError('kis_transport_failure') from None
        if getattr(response, 'status_code', None) != 200:
            raise RegularSourceError('kis_http_failure')
        try:
            body = response.json()
        except Exception:
            raise RegularSourceError('kis_payload_invalid') from None
        if not isinstance(body, dict):
            raise RegularSourceError('kis_payload_invalid')
        if body.get('rt_cd') != '0':
            raise RegularSourceError('kis_api_failure')
        return body

    def fetch_session(self, symbol, session):
        symbol, session = _target(symbol, session)
        started = self._now()
        if started < _cutoff(session):
            raise RegularSourceError('regular_session_incomplete')
        cursor, found, pages, last = _CLOSE, {}, [], started
        for _ in range(SOURCE_CONTRACT['max_pages']):
            params = _params(symbol, session, cursor)
            body = self._get(params)
            captured = self._now()
            if captured < last:
                raise RegularSourceError('invalid_clock')
            last = captured
            public, cursor = _page(body, params, found)
            pages.append(dict(params=params, captured_at=_stamp(last), response=public))
            if cursor is None:
                return _result(symbol, session, found, pages, started, last)
        raise RegularSourceError('regular_page_limit')


def replay(result, symbol, session, now):
    """Rebuild OHLC and capture evidence without credentials or network access."""
    symbol, session = _target(symbol, session)
    now = _time(now)
    if (not isinstance(result, dict) or result.get('source') != SOURCE_CONTRACT
            or result.get('symbol') != symbol or result.get('session') != session):
        raise RegularSourceError('regular_replay')
    pages, capture = result.get('pages'), result.get('capture')
    if (not isinstance(pages, list) or not 1 <= len(pages) <= SOURCE_CONTRACT['max_pages']
            or not isinstance(capture, dict)):
        raise RegularSourceError('regular_replay')
    started = _time(capture.get('first'))
    if not _cutoff(session) <= started <= now:
        raise RegularSourceError('invalid_clock')
    cursor, found, clean_pages, last = _CLOSE, {}, [], started
    for page in pages:
        if cursor is None or not isinstance(page, dict):
            raise RegularSourceError('regular_cursor')
        params = _params(symbol, session, cursor)
        if page.get('params') != params:
            raise RegularSourceError('regular_cursor')
        captured = _time(page.get('captured_at'))
        if not last <= captured <= now:
            raise RegularSourceError('invalid_clock')
        last = captured
        public, cursor = _page(page.get('response'), params, found)
        clean_pages.append(dict(params=params, captured_at=_stamp(last), response=public))
    if cursor is not None:
        raise RegularSourceError('regular_boundaries')
    clean = _result(symbol, session, found, clean_pages, started, last)
    if result != clean:
        raise RegularSourceError('regular_replay')
    return clean
