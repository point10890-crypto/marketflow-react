"""One KIS index request and one raw KRX daily request per stock acquisition.

Both endpoints support real/paper accounts. Authentication, pacing, timeouts and
the bounded expired-token retry belong to the shared read-only KIS transport.
Positive index activity confirms observed sessions; absent dates remain unknown.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re

from ..alpha_lab.market_provider import MarketDataError, _kis_request
from .profile import (
    CALENDAR_SOURCE, PRICE_BASIS, SOURCE, ProfileError, _bar, _clock,
    _completed_through, _flags, _number, _sessions, _stamp, _symbol, _text,
)


DAILY_PATH = '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
INDEX_PATH = '/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice'
SOURCE_CONTRACT = dict(version='kis-daily-j-d-1-profile-v1', provider='KIS',
                       path=DAILY_PATH, tr_id='FHKST03010100', market='J', period='D',
                       adjusted_request='1', price_basis=PRICE_BASIS, max_requests=1,
                       page_rows=100, sessions_required=20)
_FIELDS = dict(open='stck_oprc', high='stck_hgpr', low='stck_lwpr', close='stck_clpr',
               volume='acml_vol', traded_value='acml_tr_pbmn')


def completed_through(now):
    """Latest date eligible after the acquisition buffer, not a holiday guess."""
    return _completed_through(now)


def _day(value, code):
    try:
        if not isinstance(value, str) or re.fullmatch(r'[0-9]{8}', value) is None:
            raise ValueError()
        return date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat()
    except ValueError:
        raise ProfileError(code) from None


def _identity(value, symbol):
    for key in ('stck_shrn_iscd', 'symbol'):
        if key in value and value[key] != symbol:
            raise ProfileError('daily_identity')


class TechnicalProvider:
    def __init__(self, *, request=None, clock=None):
        self.request = request or _kis_request
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _get(self, path, tr_id, params):
        try:
            response = self.request(path, tr_id, params)
        except MarketDataError as error:
            raise ProfileError(error.code) from None
        except Exception:
            raise ProfileError('kis_transport_failure') from None
        if getattr(response, 'status_code', None) != 200:
            raise ProfileError('kis_http_failure')
        try:
            body = response.json()
        except Exception:
            raise ProfileError('kis_payload_invalid') from None
        if not isinstance(body, dict):
            raise ProfileError('kis_payload_invalid')
        if body.get('rt_cd') != '0':
            raise ProfileError('kis_api_failure')
        return body

    def _captured(self, started):
        captured = _clock(self.clock())
        if captured < started:
            raise ProfileError('invalid_clock')
        return _stamp(captured)

    def fetch_sessions(self, now=None):
        started = _clock(self.clock() if now is None else now)
        through = completed_through(started)
        start = (date.fromisoformat(through) - timedelta(days=99)).isoformat()
        body = self._get(INDEX_PATH, 'FHKUP03500100', dict(
            FID_COND_MRKT_DIV_CODE='U', FID_INPUT_ISCD='0001',
            FID_INPUT_DATE_1=start.replace('-', ''), FID_INPUT_DATE_2=through.replace('-', ''),
            FID_PERIOD_DIV_CODE='D'))
        head, rows = body.get('output1'), body.get('output2')
        if (not isinstance(head, dict) or head.get('bstp_cls_code') != '0001'
                or not isinstance(rows, list) or len(rows) > 100):
            raise ProfileError('calendar_invalid')
        found, seen = [], set()
        for raw in rows:
            if not isinstance(raw, dict):
                raise ProfileError('calendar_invalid')
            day = _day(raw.get('stck_bsop_date'), 'calendar_invalid')
            if (day in seen or not start <= day <= through or date.fromisoformat(day).weekday() >= 5
                    or raw.get('bstp_cls_code', '0001') != '0001'):
                raise ProfileError('calendar_invalid')
            seen.add(day)
            volume = _number(raw.get('acml_vol'), 'volume', 'calendar_invalid')
            # An empty/zero activity row does not supply a trading session.
            level = _number(raw.get('bstp_nmix_prpr'), 'traded_value', 'calendar_invalid')
            if volume > 0 and level > 0:
                found.append(day)
        if len(found) < 20:
            raise ProfileError('calendar_incomplete')
        return dict(sessions=sorted(found)[-20:], source=CALENDAR_SOURCE,
                    captured_at=self._captured(started), through=through)

    def fetch_history(self, symbol, sessions, now=None):
        symbol, sessions = _symbol(symbol), _sessions(sessions)
        started = _clock(self.clock() if now is None else now)
        if sessions[-1] > completed_through(started):
            raise ProfileError('daily_session_incomplete')
        body = self._get(DAILY_PATH, 'FHKST03010100', dict(
            FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=symbol,
            FID_INPUT_DATE_1=sessions[0].replace('-', ''), FID_INPUT_DATE_2=sessions[-1].replace('-', ''),
            FID_PERIOD_DIV_CODE='D', FID_ORG_ADJ_PRC='1'))
        head, rows = body.get('output1'), body.get('output2')
        if not isinstance(head, dict) or not isinstance(rows, list):
            raise ProfileError('daily_payload')
        if head.get('stck_shrn_iscd') != symbol:
            raise ProfileError('daily_identity')
        _identity(head, symbol)
        if len(rows) > 100:
            raise ProfileError('daily_page_size')
        found, raw_found = {}, {}
        for raw in rows:
            if not isinstance(raw, dict):
                raise ProfileError('daily_payload')
            _identity(raw, symbol)
            day = _day(raw.get('stck_bsop_date'), 'daily_session')
            if day in found:
                raise ProfileError('daily_duplicate')
            if day > sessions[-1]:
                raise ProfileError('daily_future_row')
            if day not in sessions:
                raise ProfileError('daily_session_mismatch')
            flags = _flags(raw)
            found[day] = _bar(dict(symbol=symbol, date=day, source_flags=flags,
                                  **{field: raw.get(provider) for field, provider in _FIELDS.items()}), symbol)
            # Persist only validated price fields, identity, and provider event
            # flags. Response bodies, account headers and arbitrary keys stop here.
            public = dict(stck_bsop_date=raw['stck_bsop_date'], stck_shrn_iscd=symbol)
            public.update({key: raw[key] for key in _FIELDS.values()})
            public.update(flags)
            raw_found[day] = public
        name = head.get('hts_kor_isnm') or head.get('prdt_abrv_name') or symbol
        return dict(bars=[found[day] for day in sorted(found)],
                    raw_bars=[raw_found[day] for day in sorted(raw_found)],
                    name=_text(name, 160), source=SOURCE, source_contract=dict(SOURCE_CONTRACT),
                    fetched_at=self._captured(started))
