"""Bounded project-owned KIS daily prices, with public-only acquisition evidence.

Request 0/J/D is a source contract, not historical-vintage or corporate-action
certification. All HTTP credential/pacing/token work stays in _kis_request.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import math
import re

from .market_provider import MarketDataError, _kis_request

KST = timezone(timedelta(hours=9))
SOURCE_CONTRACT = dict(version='kis-daily-j-d-0-v1', provider='KIS', tr_id='FHKST03010100',
    path='/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice',
    market='J', period='D', adjusted_request='0', page_rows=100, max_pages=12,
    request_timeout_seconds=10, requested_sessions=756,
    price_basis='KIS_request_0_not_vintage_or_corporate_action_certified')
_CODES = {'invalid_clock', 'invalid_symbol', 'daily_session', 'daily_session_incomplete',
    'daily_count', 'daily_identity', 'daily_ohlcv', 'daily_payload', 'daily_page_size',
    'daily_duplicate_conflict', 'daily_future_row', 'daily_cursor', 'daily_page_limit',
    'daily_no_history', 'daily_latest_missing', 'kis_token_unavailable',
    'kis_transport_failure', 'kis_http_failure', 'kis_api_failure', 'kis_payload_invalid'}
_PRICE_FIELDS = {'open': 'stck_oprc', 'high': 'stck_hgpr', 'low': 'stck_lwpr',
    'close': 'stck_clpr', 'volume': 'acml_vol', 'traded_value': 'acml_tr_pbmn'}
_EVENT_FIELDS = ('flng_cls_code', 'prtt_rate', 'mod_yn', 'revl_issu_reas')


class DailySourceError(ValueError):
    """Never forward raw provider bodies, request details or exception text."""
    def __init__(self, code):
        self.code = code if code in _CODES else 'kis_transport_failure'
        super().__init__(self.code)


def _clock(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError()
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise DailySourceError('invalid_clock') from None


def _stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def _session(value):
    try:
        if isinstance(value, str) and date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise DailySourceError('daily_session')


def _symbol(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9]{6}', value) is None or value == '000000':
        raise DailySourceError('invalid_symbol')
    return value


def _cutoff(session):
    return datetime.combine(date.fromisoformat(_session(session)), time(20, 30), KST).astimezone(timezone.utc)


def _number(value, field):
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError()
        result = float(value)
        maximum = 1e20 if field == 'traded_value' else 1e15 if field == 'volume' else 1e12
        if not math.isfinite(result) or result < 0 or result > maximum:
            raise ValueError()
        if field not in ('volume', 'traded_value') and result <= 0:
            raise ValueError()
        if field == 'volume' and not result.is_integer():
            raise ValueError()
        return result
    except (TypeError, ValueError, OverflowError):
        raise DailySourceError('daily_ohlcv') from None


def _identity(value, symbol):
    for field in ('stck_shrn_iscd', 'symbol'):
        if field in value and value[field] != symbol:
            raise DailySourceError('daily_identity')


def _bar(raw, symbol):
    if not isinstance(raw, dict):
        raise DailySourceError('daily_payload')
    _identity(raw, symbol)
    day = raw.get('stck_bsop_date')
    try:
        if not isinstance(day, str) or re.fullmatch(r'[0-9]{8}', day) is None:
            raise ValueError()
        day = date(int(day[:4]), int(day[4:6]), int(day[6:])).isoformat()
    except ValueError:
        raise DailySourceError('daily_session') from None
    row = dict(symbol=symbol, date=day)
    row.update({field: _number(raw.get(source), field) for field, source in _PRICE_FIELDS.items()})
    if not (row['low'] <= row['open'] <= row['high'] and row['low'] <= row['close'] <= row['high']):
        raise DailySourceError('daily_ohlcv')
    events = {}
    for field in _EVENT_FIELDS:
        if field in raw:
            value = raw[field]
            if not isinstance(value, str) or len(value) > 80 or any(ord(c) < 32 for c in value):
                raise DailySourceError('daily_payload')
            events[field] = value
    flags = []
    if row['volume'] == 0:
        flags.append(dict(code='zero_volume_nontradable', severity='nontradable'))
    neutral = dict(flng_cls_code={'', '00', '0'}, prtt_rate={'', '0', '0.00'},
                   mod_yn={'', 'N'}, revl_issu_reas={'', '00', '0'})
    if any(value not in neutral[field] for field, value in events.items()):
        flags.append(dict(code='provider_price_event_unverified', severity='warning'))
    row.update(tradable=row['volume'] > 0, quality_flags=flags, source_flags=events)
    # Keep only validated public price fields: never serialize arbitrary body keys.
    public = {'stck_bsop_date': raw['stck_bsop_date']}
    public.update({field: raw[field] for field in _PRICE_FIELDS.values()})
    public.update(events)
    return row, public


class KISDailyProvider:
    def __init__(self, *, request=None, clock=None):
        self.request = request or _kis_request
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _get(self, params):
        try:
            response = self.request(SOURCE_CONTRACT['path'], SOURCE_CONTRACT['tr_id'], params)
        except MarketDataError as exc:
            raise DailySourceError(exc.code) from None
        except Exception:
            raise DailySourceError('kis_transport_failure') from None
        if getattr(response, 'status_code', None) != 200:
            raise DailySourceError('kis_http_failure')
        try:
            body = response.json()
        except Exception:
            raise DailySourceError('kis_payload_invalid') from None
        if not isinstance(body, dict):
            raise DailySourceError('kis_payload_invalid')
        if body.get('rt_cd') != '0':
            raise DailySourceError('kis_api_failure')
        return body

    def fetch_history(self, symbol, end_session, *, count=756):
        symbol, end_session = _symbol(symbol), _session(end_session)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 756:
            raise DailySourceError('daily_count')
        started = _clock(self.clock())
        if started < _cutoff(end_session):
            raise DailySourceError('daily_session_incomplete')
        cursor, found, pages, stamps = date.fromisoformat(end_session), {}, [], []
        exhausted = False
        for _ in range(12):
            start = cursor - timedelta(days=370)
            params = dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=symbol,
                FID_INPUT_DATE_1=start.strftime('%Y%m%d'), FID_INPUT_DATE_2=cursor.strftime('%Y%m%d'),
                FID_PERIOD_DIV_CODE='D', FID_ORG_ADJ_PRC='0')
            body = self._get(params)
            captured = _clock(self.clock())
            if captured < started or stamps and captured < stamps[-1]:
                raise DailySourceError('invalid_clock')
            metadata, raw_rows = body.get('output1'), body.get('output2')
            if not isinstance(metadata, dict) or not isinstance(raw_rows, list):
                raise DailySourceError('daily_payload')
            _identity(metadata, symbol)
            if metadata.get('stck_shrn_iscd') != symbol:
                raise DailySourceError('daily_identity')
            if len(raw_rows) > 100:
                raise DailySourceError('daily_page_size')
            public_rows, page_days = [], []
            for raw in raw_rows:
                row, public = _bar(raw, symbol)
                day = row['date']
                if day in found and found[day] != row:
                    raise DailySourceError('daily_duplicate_conflict')
                if day > end_session:
                    raise DailySourceError('daily_future_row')
                if not start.isoformat() <= day <= cursor.isoformat():
                    raise DailySourceError('daily_cursor')
                found[day] = row
                page_days.append(day)
                public_rows.append(public)
            stamps.append(captured)
            pages.append(dict(params=params, captured_at=_stamp(captured), response=dict(rt_cd='0',
                output1=dict(stck_shrn_iscd=symbol), output2=public_rows)))
            if not page_days:
                exhausted = True
                break
            earliest = date.fromisoformat(min(page_days))
            next_cursor = earliest-timedelta(days=1)
            if next_cursor >= cursor:
                raise DailySourceError('daily_cursor')
            cursor = next_cursor
            if len(found) >= count:
                break
        if not found:
            raise DailySourceError('daily_no_history')
        if max(found) != end_session:
            raise DailySourceError('daily_latest_missing')
        if len(found) < count and not exhausted:
            raise DailySourceError('daily_page_limit')
        rows = [found[day] for day in sorted(found)[-count:]]
        return dict(symbol=symbol, bars=rows, source=deepcopy(SOURCE_CONTRACT), pages=pages,
            captured_at=_stamp(stamps[-1]), capture=dict(first=_stamp(stamps[0]), last=_stamp(stamps[-1])),
            history_status='complete' if len(rows) == count else 'insufficient_history')
