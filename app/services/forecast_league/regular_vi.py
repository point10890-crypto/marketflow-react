"""League-only regular close contract; VI extension requires matching public evidence.

Uses the existing KIS parser but never changes AlphaLab's sealed v1 contract.
15:30 closes are ordinary. A delayed auction must be the single flat-price print
before 15:40 and match a completed 15:30 VI's release minute. Otherwise fail closed.
This is same-provider evidence, not independent KRX certification.
"""
from copy import deepcopy
import re
from datetime import datetime, timedelta

from app.services.forecast_league.clock import session_hours

from app.services.mirofish.alpha_lab import regular_source as v1

SOURCE = dict(v1.SOURCE_CONTRACT, version='league-kis-regular-vi-v2',
              open_kst='announced_session_open',
              close_kst='announced_close_or_verified_VI_release_within_10_minutes',
              initial_cursor='announced_close_plus_9_minutes', hours_version='krx-hours-20261113', vi_tr_id='FHPST01390000',
              vi_path='/uapi/domestic-stock/v1/quotations/inquire-vi-status')


def _vi_params(symbol, session):
    return dict(FID_DIV_CLS_CODE='0', FID_COND_SCR_DIV_CODE='20139', FID_MRKT_CLS_CODE='0',
                FID_INPUT_ISCD=symbol, FID_RANK_SORT_CLS_CODE='0',
                FID_INPUT_DATE_1=session.replace('-', ''), FID_TRGT_CLS_CODE='', FID_TRGT_EXLS_CLS_CODE='')


def _public_vi(body):
    if not isinstance(body, dict) or body.get('rt_cd') != '0':
        raise ValueError('vi_payload')
    rows = body.get('output')
    rows = [rows] if isinstance(rows, dict) else rows
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('vi_payload')
    keys = {'mksc_shrn_iscd', 'bsop_date', 'vi_cls_code', 'cntg_vi_hour', 'vi_cncl_hour'}
    clean = []
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or len(row[k]) > 20 for k in keys):
            raise ValueError('vi_payload')
        clean.append({k: row[k] for k in sorted(keys)})
    return {'rt_cd': '0', 'output': clean}


def _offset(hms, minutes):
    return (datetime.strptime(hms, '%H%M%S') + timedelta(minutes=minutes)).strftime('%H%M%S')


def _sum_regular(found, opening, closing):
    first, last = found.get(opening), found.get(closing)
    if not first or not last or not first['volume'] or not last['volume']:
        raise ValueError('regular_boundaries')
    selected = [bar for t, bar in found.items() if opening <= t <= closing]
    return dict(open=first['open'], high=max(b['high'] for b in selected),
                low=min(b['low'] for b in selected), close=last['close'],
                volume=sum(b['volume'] for b in selected), traded_value=last['traded_value'])


def _aggregate(found, vi, symbol, session):
    opening, closing = session_hours(session)
    limit = _offset(closing, 10)
    late = [t for t, bar in found.items() if t > closing and bar['volume'] > 0]
    if found.get(closing, {}).get('volume', 0) > 0:
        if late or vi is not None:
            raise ValueError('ambiguous_closing_auction')
        return _sum_regular(found, opening, closing), closing
    if len(late) != 1 or not closing < late[0] < limit or vi is None:
        raise ValueError('unverified_closing_auction')
    close = late[0]
    matches = []
    for row in vi['response']['output']:
        fire, release = row['cntg_vi_hour'], row['vi_cncl_hour']
        if not all(re.fullmatch(r'(?:[01][0-9]|2[0-3])[0-5][0-9][0-5][0-9]', t) for t in (fire, release)):
            raise ValueError('vi_clock')
        if (row['mksc_shrn_iscd'] == symbol and row['bsop_date'] == session.replace('-', '')
                and row['vi_cls_code'] == 'N' and closing <= fire < _offset(closing, 1)
                and fire < release < limit and release[:4] + '00' == close):
            matches.append(row)
    auction = found[close]
    if len(matches) != 1 or len({auction[k] for k in ('open', 'high', 'low', 'close')}) != 1:
        raise ValueError('vi_release_mismatch')
    if any(_offset(closing, -10) <= t < close and bar['volume'] > 0 for t, bar in found.items()):
        raise ValueError('ambiguous_closing_auction')
    normalized = {t: bar for t, bar in found.items() if t < closing}
    normalized[closing] = auction
    return _sum_regular(normalized, opening, closing), close


def _result(symbol, session, found, pages, vi, first, last):
    bar, closing = _aggregate(found, vi, symbol, session)
    opening, planned_close = session_hours(session)
    return dict(symbol=symbol, session=session, bar=bar, closing_time=closing,
                session_hours=dict(open=opening, close=planned_close),
                pages=pages, vi=vi, source=deepcopy(SOURCE), captured_at=v1._stamp(last),
                capture=dict(first=v1._stamp(first), last=v1._stamp(last)))


class LeagueRegularProvider(v1.KISRegularProvider):
    def fetch_session(self, symbol, session):
        symbol, session = v1._target(symbol, session)
        first = last = self._now()
        if first < v1._cutoff(session):
            raise ValueError('regular_session_incomplete')
        opening, closing = session_hours(session)
        cursor, found, pages = _offset(closing, 9), {}, []
        for _ in range(SOURCE['max_pages']):
            params = v1._params(symbol, session, cursor)
            body = self._get(params)
            at = self._now()
            if at < last:
                raise ValueError('invalid_clock')
            last = at
            public, cursor = v1._page(body, params, found)
            if min(found) <= opening:
                cursor = None
            pages.append(dict(params=params, captured_at=v1._stamp(last), response=public))
            if cursor is None:
                break
        else:
            raise ValueError('regular_page_limit')
        vi = None
        if not found.get(closing, {}).get('volume', 0):
            params = _vi_params(symbol, session)
            response = self.request(SOURCE['vi_path'], SOURCE['vi_tr_id'], params)
            if getattr(response, 'status_code', None) != 200:
                raise ValueError('vi_http_failure')
            public = _public_vi(response.json())
            at = self._now()
            if at < last:
                raise ValueError('invalid_clock')
            last = at
            vi = dict(params=params, response=public, captured_at=v1._stamp(last))
        return _result(symbol, session, found, pages, vi, first, last)


def replay(result, symbol, session, now):
    symbol, session = v1._target(symbol, session)
    now = v1._time(now)
    if result.get('source') != SOURCE or result.get('symbol') != symbol or result.get('session') != session:
        raise ValueError('regular_replay')
    pages = result.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= SOURCE['max_pages']:
        raise ValueError('regular_replay')
    first = last = v1._time(result['capture']['first'])
    if not v1._cutoff(session) <= first <= now:
        raise ValueError('invalid_clock')
    opening, closing = session_hours(session)
    cursor, found, clean = _offset(closing, 9), {}, []
    for page in pages:
        if cursor is None or page['params'] != v1._params(symbol, session, cursor):
            raise ValueError('regular_cursor')
        at = v1._time(page['captured_at'])
        if not last <= at <= now:
            raise ValueError('invalid_clock')
        last = at
        public, cursor = v1._page(page['response'], page['params'], found)
        if min(found) <= opening:
            cursor = None
        clean.append(dict(params=page['params'], response=public, captured_at=v1._stamp(last)))
    if cursor is not None:
        raise ValueError('regular_boundaries')
    vi = result.get('vi')
    if vi is not None:
        if vi['params'] != _vi_params(symbol, session):
            raise ValueError('vi_identity')
        at = v1._time(vi['captured_at'])
        if not last <= at <= now:
            raise ValueError('invalid_clock')
        last = at
        vi = dict(params=vi['params'], response=_public_vi(vi['response']), captured_at=v1._stamp(last))
    reconstructed = _result(symbol, session, found, clean, vi, first, last)
    if result != reconstructed:
        raise ValueError('regular_replay')
    return reconstructed
