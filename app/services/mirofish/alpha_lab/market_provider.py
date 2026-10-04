"""Strict read-only KIS session/quote boundary; no pandas, orders or body logs.

Official API contracts: koreainvestment/open-trading-api examples_llm/
domestic_stock/{chk_holiday,inquire_price,inquire_time_itemchartprice}.
The injected request(path, tr_id, params) returns an HTTP-response-like object.
Minute close carries its provider timestamp; opening_price is the DAILY open
from inquire-price, never a minute bar's opening. Minute volume by itself is
not proof of a new trade (KIS documents a first-row carry-over behavior).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
import re

KST = timezone(timedelta(hours=9))
CALENDAR_SOURCE = 'KIS:CTCA0903R'
QUOTE_SOURCE = 'KIS:J:FHKST03010200+FHKST01010100'
MAX_TRADE_AGE_SECONDS = 120
_ERRORS = {'invalid_clock', 'invalid_session', 'invalid_symbol', 'kis_token_unavailable',
           'kis_transport_failure', 'kis_http_failure', 'kis_api_failure', 'kis_payload_invalid',
           'calendar_invalid', 'quote_invalid', 'quote_nontradable', 'quote_stale',
           'quote_future', 'quote_session_mismatch'}


class MarketDataError(ValueError):
    """Only bounded public reason codes cross the provider boundary."""
    def __init__(self, code):
        self.code = code if code in _ERRORS else 'kis_transport_failure'
        super().__init__(self.code)


def _clock(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError()
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise MarketDataError('invalid_clock') from None


def _stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def _session(value):
    try:
        if isinstance(value, str) and date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise MarketDataError('invalid_session')


def _provider_day(value, error):
    try:
        if not isinstance(value, str) or re.fullmatch(r'[0-9]{8}', value) is None:
            raise ValueError()
        return date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat()
    except ValueError:
        raise MarketDataError(error) from None


def _positive(value):
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError()
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError()
        return value
    except (ValueError, TypeError, OverflowError):
        raise MarketDataError('quote_invalid') from None


def _identity(raw, symbol):
    for key in ('stck_shrn_iscd', 'symbol'):
        if key in raw and raw[key] != symbol:
            raise MarketDataError('quote_invalid')


def _kis_request(path, tr_id, params):
    """Reuse existing credentials/pacing; bounded token retry, no response logs."""
    try:
        from app.services import kis_screener as kis
        token = kis.get_token()
        if not token:
            raise MarketDataError('kis_token_unavailable')
        for attempt in range(2):
            kis._pace_api_request()
            response = kis._http_get(f'{kis.BASE_URL}{path}', headers=kis._headers(token, tr_id),
                                     params=params, timeout=10)
            try:
                body = response.json()
            except Exception:
                body = None
            expired = response.status_code == 401 or isinstance(body, dict) and body.get('msg_cd') == 'EGW00123'
            if expired and attempt == 0:
                kis.invalidate_token(expected_token=token)
                token = kis.get_token()
                if not token:
                    raise MarketDataError('kis_token_unavailable')
                continue
            if isinstance(body, dict) and body.get('msg_cd') == 'EGW00201':
                kis._publish_shared_rate_limit_backoff(kis._rate_limit_backoff_seconds())
            return response
    except MarketDataError:
        raise
    except Exception:
        raise MarketDataError('kis_transport_failure') from None


class KISMarketProvider:
    def __init__(self, *, request=None, clock=None):
        self.request = request or _kis_request
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self, now):
        return _clock(self.clock() if now is None else now)

    def _get(self, path, tr_id, params):
        try:
            response = self.request(path, tr_id, params)
        except MarketDataError:
            raise
        except Exception:
            raise MarketDataError('kis_transport_failure') from None
        if getattr(response, 'status_code', None) != 200:
            raise MarketDataError('kis_http_failure')
        try:
            body = response.json()
        except Exception:
            raise MarketDataError('kis_payload_invalid') from None
        if not isinstance(body, dict):
            raise MarketDataError('kis_payload_invalid')
        if body.get('rt_cd') != '0':
            raise MarketDataError('kis_api_failure')
        return body

    def fetch_calendar(self, base_date, now=None):
        base_date = _session(base_date)
        self._now(now)  # Validate the clock before any external request.
        body = self._get('/uapi/domestic-stock/v1/quotations/chk-holiday', 'CTCA0903R',
                         dict(BASS_DT=base_date.replace('-', ''), CTX_AREA_FK='', CTX_AREA_NK=''))
        rows = body.get('output')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 370:
            raise MarketDataError('calendar_invalid')
        days = {}
        for raw in rows:
            if not isinstance(raw, dict):
                raise MarketDataError('calendar_invalid')
            day = _provider_day(raw.get('bass_dt'), 'calendar_invalid')
            trade, opened = raw.get('tr_day_yn'), raw.get('opnd_yn')
            if day < base_date or day in days or trade not in ('Y', 'N') or opened not in ('Y', 'N'):
                raise MarketDataError('calendar_invalid')
            days[day] = trade == opened == 'Y'
        return dict(source=CALENDAR_SOURCE, captured_at=_stamp(self._now(now)),
                    days=[dict(date=day, is_open=days[day]) for day in sorted(days)])

    def fetch_quote(self, symbol, now=None):
        if not isinstance(symbol, str) or re.fullmatch(r'[0-9]{6}', symbol) is None or symbol == '000000':
            raise MarketDataError('invalid_symbol')
        current = self._now(now)
        params = dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=symbol)
        daily = self._get('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100', params).get('output')
        if not isinstance(daily, dict):
            raise MarketDataError('quote_invalid')
        _identity(daily, symbol)
        opening = _positive(daily.get('stck_oprc'))
        _positive(daily.get('stck_prpr'))
        if daily.get('temp_stop_yn') != 'N':
            raise MarketDataError('quote_nontradable')
        try:
            _positive(daily.get('acml_vol'))
        except MarketDataError:
            raise MarketDataError('quote_nontradable') from None
        minute_params = dict(params, FID_INPUT_HOUR_1=current.astimezone(KST).strftime('%H%M%S'),
                             FID_PW_DATA_INCU_YN='N', FID_ETC_CLS_CODE='')
        body = self._get('/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice', 'FHKST03010200', minute_params)
        bars = body.get('output2')
        if not isinstance(body.get('output1'), dict) or not isinstance(bars, list) or not 1 <= len(bars) <= 30:
            raise MarketDataError('quote_invalid')
        fetched = self._now(now)
        observed = {}
        for raw in bars:
            if not isinstance(raw, dict):
                raise MarketDataError('quote_invalid')
            _identity(raw, symbol)
            day = _provider_day(raw.get('stck_bsop_date'), 'quote_invalid')
            if day != fetched.astimezone(KST).date().isoformat():
                raise MarketDataError('quote_session_mismatch')
            hour = raw.get('stck_cntg_hour')
            try:
                if not isinstance(hour, str) or re.fullmatch(r'[0-9]{6}', hour) is None:
                    raise ValueError()
                at = datetime.fromisoformat(day).replace(hour=int(hour[:2]), minute=int(hour[2:4]),
                    second=int(hour[4:]), tzinfo=KST).astimezone(timezone.utc)
            except ValueError:
                raise MarketDataError('quote_invalid') from None
            if at > fetched:
                raise MarketDataError('quote_future')
            if at in observed:
                raise MarketDataError('quote_invalid')
            observed[at] = _positive(raw.get('stck_prpr'))
        at = max(observed)
        if (fetched-at).total_seconds() > MAX_TRADE_AGE_SECONDS:
            raise MarketDataError('quote_stale')
        return dict(symbol=symbol, price=observed[at], opening_price=opening,
                    quote_at=_stamp(at), fetched_at=_stamp(fetched), source=QUOTE_SOURCE)
