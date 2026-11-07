"""Read-only KRX minute evidence for an article's first observable market window.

KIS Developers domestic-stock contracts 040 (calendar) and 213 (dated minutes).
A price move within the sample is descriptive and does not measure causality.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import math
from pathlib import Path
import re
from time import monotonic

import requests

from app.services.mirofish.alpha_lab.market_provider import (
    CALENDAR_SOURCE, KST, KISMarketProvider, MarketDataError, _clock, _identity,
    _provider_day, _stamp,
)
from app.utils.atomic_json import write_json_atomic

SOURCE = 'KIS:J:FHKST03010230'
MINUTE_PATH = '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice'
MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)
MAX_SEARCH_DAYS = 14
CALENDAR_RETRY_DELAY = timedelta(minutes=15)
CALENDAR_MAX_ATTEMPTS = 2
MINUTE_RETENTION = timedelta(days=365)
WINDOW_MINUTES = 30
PRICE_POLICY = 'kis_krx_post_receipt_minutes_v1'
KRX_ORIGIN = 'https://open.krx.co.kr'
KRX_PAGE = '/contents/MKD/01/0110/01100305/MKD01100305.jsp'
KRX_HOLIDAYS = 'KRX:official-holiday-schedule'
KRX_WEEKEND = 'KRX:regular-market-rules'
INDEX_SOURCE = 'KIS:KOSPI:FHKUP03500100'


class _Deferred(Exception):
    pass


def _calendar_time(value):
    try:
        return _clock(value)
    except MarketDataError:
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MarketDataError('quote_invalid')
    value = str(value)
    if not re.fullmatch(r'[0-9]{1,14}', value):
        raise MarketDataError('quote_invalid')
    return int(value)


def _parse_minutes(body, symbol, session, cursor, fetched):
    head, rows = body.get('output1'), body.get('output2')
    if not isinstance(head, dict) or not isinstance(rows, list) or len(rows) > 120:
        raise MarketDataError('quote_invalid')
    _identity(head, symbol)
    minutes = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise MarketDataError('quote_invalid')
        _identity(raw, symbol)
        if _provider_day(raw.get('stck_bsop_date'), 'quote_invalid') != session.isoformat():
            raise MarketDataError('quote_session_mismatch')
        hhmmss = raw.get('stck_cntg_hour')
        try:
            if not isinstance(hhmmss, str) or re.fullmatch(r'[0-9]{4}00', hhmmss) is None:
                raise ValueError()
            at = datetime.combine(session, time(int(hhmmss[:2]), int(hhmmss[2:4])), KST)
        except ValueError:
            raise MarketDataError('quote_invalid') from None
        if at > fetched:
            raise MarketDataError('quote_future')
        if at > cursor or at in minutes:
            raise MarketDataError('quote_invalid')
        volume = _number(raw.get('cntg_vol'))
        price = _number(raw.get('stck_prpr'))
        if volume and not price:
            raise MarketDataError('quote_invalid')
        minutes[at] = price if volume else None
    return minutes


class _KrxCalendarUnavailable(ValueError):
    pass


def _krx_holidays(http, year):
    options = dict(timeout=(3, 5), allow_redirects=False)
    try:
        receipt = http.get(KRX_ORIGIN + '/contents/COM/GenerateOTP.jspx', params={
            'bld': 'MKD/01/0110/01100305/mkd01100305_01', 'name': 'form',
        }, **options)
        code = receipt.text.strip()
        if receipt.status_code != 200 or not re.fullmatch(r'[A-Za-z0-9+/=_-]{80,512}', code):
            raise _KrxCalendarUnavailable()
        reply = http.post(KRX_ORIGIN + '/contents/OPN/99/OPN99000001.jspx', data={
            'code': code, 'search_bas_yy': str(year), 'gridTp': 'KRX', 'pagePath': KRX_PAGE,
        }, **options)
        if reply.status_code != 200 or len(reply.content) > 100_000:
            raise _KrxCalendarUnavailable()
        body = reply.json()
        rows = body.get('block1') if isinstance(body, dict) else None
        if not isinstance(rows, list) or not 2 <= len(rows) <= 100:
            raise _KrxCalendarUnavailable()
        closed = set()
        for row in rows:
            stamp = row.get('calnd_dd') if isinstance(row, dict) else None
            if not isinstance(stamp, str):
                raise _KrxCalendarUnavailable()
            day = date.fromisoformat(stamp)
            name = row.get('holdy_nm')
            if (day.isoformat() != stamp or day.year != year or day in closed
                    or row.get('calnd_dd_dy') != stamp or not isinstance(name, str) or not name.strip()):
                raise _KrxCalendarUnavailable()
            closed.add(day)
        if min(closed).month > 2 or max(closed).month != 12:
            raise _KrxCalendarUnavailable()
        return closed
    except (requests.RequestException, ValueError):
        raise _KrxCalendarUnavailable() from None


class KongmingPriceProvider:
    """One bounded batch, optionally sharing a daily calendar across worker runs."""

    def __init__(self, *, request=None, clock=None, max_requests=6, calendar_path=None,
                 time_budget_seconds=35, paper=None):
        self._provider = KISMarketProvider(request=request, clock=clock)
        self._paper = paper
        if self._paper is None and request is None:
            from app.services import kis_screener

            self._paper = kis_screener._paper
        self._requests_used = 0
        self._max_requests = max_requests
        self._deadline = monotonic() + time_budget_seconds
        self._minute_pages = {}
        self._calendar_path = Path(calendar_path) if calendar_path is not None else None
        self._calendar = self._read_calendar()

    @property
    def requests_used(self):
        return self._requests_used

    def _reserve(self, count=1):
        if self._requests_used + count > self._max_requests or monotonic() >= self._deadline:
            raise _Deferred()
        self._requests_used += count

    def _read_calendar(self):
        if self._calendar_path is not None:
            try:
                value = json.loads(self._calendar_path.read_text(encoding='utf-8'))
                if (isinstance(value, dict) and value.get('source') == CALENDAR_SOURCE
                        and isinstance(value.get('days'), dict)):
                    return value
            except (OSError, ValueError):
                pass
        return dict(source=CALENDAR_SOURCE, days={})

    def _known_day(self, day, current):
        row = self._calendar['days'].get(day.isoformat())
        if not isinstance(row, dict) or not isinstance(row.get('is_open'), bool):
            return None
        captured = _calendar_time(row.get('captured_at'))
        if captured is None or captured > current or captured.astimezone(KST).date() < day:
            return None
        return row

    def _calendar_day(self, day, current):
        known = self._known_day(day, current)
        if known is not None:
            return known
        today = current.astimezone(KST).date()
        attempts = self._calendar_attempts(current, today)
        if attempts is not None:
            base = min(day, today - timedelta(days=7))
            years = range(base.year, today.year + 1)
            self._reserve(2 * len(years) if self._paper else 1)
            # KIS requests about one lookup per day. Only failed or abandoned
            # calls may get a second attempt, after the persisted cooldown.
            self._calendar.update(
                attempted_day=today.isoformat(), attempted_at=_stamp(current), attempts=attempts + 1,
                state='pending', reason='calendar_attempt_incomplete',
            )
            if self._calendar_path is not None:
                write_json_atomic(self._calendar_path, self._calendar)
            try:
                response, partial = self._fetch_calendar(base, today, years)
                capture = _clock(response['captured_at'])
                # Only sessions on or before acquisition become confirmed rows.
                for row in response['days']:
                    session = date.fromisoformat(row['date'])
                    if today - MINUTE_RETENTION <= session <= capture.astimezone(KST).date():
                        self._calendar['days'][row['date']] = dict(
                            is_open=row['is_open'], captured_at=response['captured_at'],
                            source=row.get('source', response['source']),
                        )
                self._calendar['days'] = {
                    key: row for key, row in self._calendar['days'].items()
                    if key >= (today - MINUTE_RETENTION).isoformat()
                }
                self._calendar.update(
                    state='partial' if partial else 'ready', reason='calendar_day_unconfirmed',
                )
            except MarketDataError as exc:
                self._calendar.update(state='failed', reason=exc.code)
            if self._calendar_path is not None:
                write_json_atomic(self._calendar_path, self._calendar)
            known = self._known_day(day, self._provider._now(None))
        return known

    def _fetch_calendar(self, base, today, years):
        if not self._paper:
            return self._provider.fetch_calendar(base.isoformat()), False
        # CTCA0903R is live-account-only (EGW02006 in paper). Use the public
        # exchange schedule and still require an actual dated KIS trade bar.
        try:
            with requests.Session() as http:
                http.headers.update({
                    'User-Agent': 'Mozilla/5.0 (compatible; MarketFlow/1.0)',
                    'Referer': KRX_ORIGIN + KRX_PAGE, 'X-Requested-With': 'XMLHttpRequest',
                })
                closures = set().union(*(_krx_holidays(http, year) for year in years))
            rows = []
            for offset in range((today - base).days + 1):
                day = base + timedelta(days=offset)
                rows.append(dict(date=day.isoformat(), is_open=day.weekday() < 5 and day not in closures))
            return dict(source=KRX_HOLIDAYS, captured_at=_stamp(self._provider._now(None)), days=rows), False
        except _KrxCalendarUnavailable:
            self._reserve()
            return self._fetch_index_sessions(base, today), True

    def _fetch_index_sessions(self, base, today):
        # Actual KOSPI session activity is positive proof only. Missing
        # weekdays could be source gaps and are deliberately left unknown.
        through = min(today, base + timedelta(days=99))
        body = self._provider._get('/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice',
                                   'FHKUP03500100', dict(
            FID_COND_MRKT_DIV_CODE='U', FID_INPUT_ISCD='0001',
            FID_INPUT_DATE_1=base.strftime('%Y%m%d'), FID_INPUT_DATE_2=through.strftime('%Y%m%d'),
            FID_PERIOD_DIV_CODE='D',
        ))
        head, bars = body.get('output1'), body.get('output2')
        if (not isinstance(head, dict) or head.get('bstp_cls_code') != '0001'
                or not isinstance(bars, list) or len(bars) > 100):
            raise MarketDataError('calendar_invalid')
        confirmed = {}
        for bar in bars:
            if not isinstance(bar, dict):
                raise MarketDataError('calendar_invalid')
            key = _provider_day(bar.get('stck_bsop_date'), 'calendar_invalid')
            day = date.fromisoformat(key)
            try:
                level = float(bar.get('bstp_nmix_prpr'))
                volume = _number(bar.get('acml_vol'))
            except (TypeError, ValueError):
                raise MarketDataError('calendar_invalid') from None
            if (not base <= day <= through or day in confirmed or day.weekday() >= 5
                    or not math.isfinite(level) or level < 0):
                raise MarketDataError('calendar_invalid')
            confirmed[day] = level > 0 and volume > 0
        rows = []
        for offset in range((through - base).days + 1):
            day = base + timedelta(days=offset)
            if confirmed.get(day):
                rows.append(dict(date=day.isoformat(), is_open=True, source=INDEX_SOURCE))
            elif day.weekday() >= 5:
                rows.append(dict(date=day.isoformat(), is_open=False, source=KRX_WEEKEND))
        return dict(source=INDEX_SOURCE, captured_at=_stamp(self._provider._now(None)), days=rows)

    def _calendar_attempts(self, current, today):
        if self._calendar.get('attempted_day') != today.isoformat():
            return 0
        attempted = _calendar_time(self._calendar.get('attempted_at'))
        attempts = self._calendar.get('attempts')
        if (self._calendar.get('state') in {'pending', 'failed', 'partial'}
                and isinstance(attempts, int) and 1 <= attempts < CALENDAR_MAX_ATTEMPTS
                and attempted is not None and current - attempted >= CALENDAR_RETRY_DELAY):
            return attempts
        return None

    def _minute_page(self, symbol, cursor):
        key = (symbol, cursor)
        if key not in self._minute_pages:
            self._reserve()
            try:
                body = self._provider._get(MINUTE_PATH, 'FHKST03010230', {
                    'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': symbol,
                    'FID_INPUT_HOUR_1': cursor.strftime('%H%M%S'),
                    'FID_INPUT_DATE_1': cursor.strftime('%Y%m%d'),
                    'FID_PW_DATA_INCU_YN': 'N', 'FID_FAKE_TICK_INCU_YN': '',
                })
                fetched = self._provider._now(None)
                if fetched < cursor + MINUTE:
                    raise MarketDataError('quote_future')
                self._minute_pages[key] = (_parse_minutes(body, symbol, cursor.date(), cursor, fetched), fetched)
            except MarketDataError as exc:
                self._minute_pages[key] = exc
        page = self._minute_pages[key]
        if isinstance(page, MarketDataError):
            raise page
        return page

    def verify(self, article, symbol, now=None):
        valid_symbol = isinstance(symbol, str) and re.fullmatch(r'[0-9A-Z]{6}', symbol) and symbol != '000000'
        result = dict(source=SOURCE, market='KRX', policy=PRICE_POLICY, symbol=symbol if valid_symbol else None)
        entities = article.get('entities') if isinstance(article, dict) else None
        if (not valid_symbol or not isinstance(entities, list)
                or not any(isinstance(row, dict) and row.get('symbol') == symbol for row in entities)):
            return dict(result, status='invalid_identity', reason='invalid_article_symbol')
        try:
            current = self._provider._now(now)
            reference = max(_clock(article.get('published_at')), _clock(article.get('first_seen_at')))
        except MarketDataError:
            return dict(result, status='invalid_identity', reason='invalid_article_clock')
        if reference > current:
            return dict(result, status='invalid_identity', reason='future_article_clock')
        result.update(reference_at=_stamp(reference))
        if current.astimezone(KST).date() - reference.astimezone(KST).date() > MINUTE_RETENTION:
            return dict(result, status='historical_window_expired', reason='kis_minute_retention')
        try:
            return self._verify_window(result, reference.astimezone(KST), current)
        except _Deferred:
            return dict(result, status='deferred', reason='kis_request_budget')
        except MarketDataError as exc:
            return dict(result, status='source_unavailable', reason=exc.code)

    def _verify_window(self, result, reference, current):
        day = reference.date()
        today = current.astimezone(KST).date()
        earliest = reference.replace(second=0, microsecond=0) + MINUTE
        last_completed = current.replace(second=0, microsecond=0) - MINUTE
        for _ in range(MAX_SEARCH_DAYS):
            if day > today:
                return dict(result, status='awaiting_session', reason='no_open_session_yet')
            # Exclude opening and closing boundary labels. KIS J requests exclude NXT.
            start = max(earliest, datetime.combine(day, time(9, 1), KST))
            regular_end = datetime.combine(day, time(15, 29), KST)
            if start <= regular_end:
                confirmed = self._calendar_day(day, max(current, self._provider._now(None)))
                if confirmed is None:
                    return dict(result, status='calendar_unavailable', reason=self._calendar.get(
                        'reason', 'calendar_day_unconfirmed'))
                if confirmed['is_open']:
                    result.update(session=day.isoformat(), calendar_source=confirmed.get('source', CALENDAR_SOURCE),
                                  calendar_captured_at=confirmed['captured_at'])
                    if start > last_completed:
                        return dict(result, status='awaiting_session', reason='first_minute_not_closed')
                    end = min(start + (WINDOW_MINUTES - 1) * MINUTE, regular_end)
                    return self._observe(result, start, end, min(end, last_completed))
            day += DAY
        return dict(result, status='calendar_unavailable', reason='no_session_in_calendar_window')

    def _observe(self, result, start, end, cursor):
        result.update(window_end_at=_stamp(end.astimezone(timezone.utc)), window_complete=cursor == end)
        minutes, fetched = self._minute_page(result['symbol'], cursor.astimezone(KST))
        observations = sorted((at, price) for at, price in minutes.items() if start <= at <= cursor and price)
        result.update(fetched_at=_stamp(fetched))
        if not observations:
            return dict(result, status='awaiting_post_receipt_data', reason='no_post_receipt_minute')
        first_at, first = observations[0]
        latest_at, latest = observations[-1]
        result.update(status='verified', reason='krx_minutes_observed', close=first, latest_close=latest,
                      observed_at=_stamp(first_at.astimezone(timezone.utc)),
                      latest_observed_at=_stamp(latest_at.astimezone(timezone.utc)))
        if len(observations) > 1:
            result.update(change_pct=round((latest - first) / first * 100, 4))
        return result
