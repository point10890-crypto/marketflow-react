"""Daily high/low overlap estimates, never holdings or executable liquidity.

Twenty confirmed sessions are required, including non-trading stock bars. A
daily bar's volume and actual turnover are allocated independently by overlap
width. This is deliberately coarser than a profile built from intraday trades.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re


KST = timezone(timedelta(hours=9))
SESSIONS_REQUIRED = 20
BIN_COUNT = 24
METHOD = 'daily_uniform_range_overlap_v1'
PRICE_BASIS = 'KIS_KRX_raw_J_D_1'
SOURCE = 'KIS:FHKST03010100:J:D:1'
CALENDAR_SOURCE = 'KIS:KOSPI:FHKUP03500100'
EVENT_FIELDS = ('flng_cls_code', 'prtt_rate', 'mod_yn', 'revl_issu_reas')
PRICE_FIELDS = ('open', 'high', 'low', 'close', 'volume', 'traded_value')
LIMITATIONS = (
    '일봉 저가·고가 범위에 거래량과 거래대금을 균등 배분한 추정치이며 실제 체결가별 분포와 다를 수 있습니다.',
    '과거 누적 거래량이며 현재 보유 물량, 잔존 매물 또는 호가 유동성을 뜻하지 않습니다.',
    '기준가는 마지막 완료 거래일의 종가이며 실시간 시세가 아닙니다.',
    '원주가 요청 결과이며 기업행사 조정·과거 시점 데이터의 완전성을 인증하지 않습니다. 미제공 행사 표시는 확인할 수 없습니다.',
    '거래일은 KOSPI 지수의 양수 거래량 관측으로 확인하며 공식 휴장일 달력의 완전성을 보증하지 않습니다.',
    '지지·저항은 거래량 집중 구간의 후보이며 향후 수익이나 가격 방어를 보장하지 않습니다.',
)
_CODES = {
    'invalid_clock', 'invalid_symbol', 'calendar_invalid', 'calendar_incomplete',
    'daily_session', 'daily_session_incomplete', 'daily_session_mismatch',
    'daily_identity', 'daily_ohlcv', 'daily_payload', 'daily_page_size',
    'daily_duplicate', 'daily_future_row', 'kis_token_unavailable',
    'kis_transport_failure', 'kis_http_failure', 'kis_api_failure', 'kis_payload_invalid',
}


class ProfileError(ValueError):
    """Only bounded public reason codes cross the acquisition boundary."""

    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in _CODES else 'kis_transport_failure'
        super().__init__(self.code)


def _clock(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError()
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise ProfileError('invalid_clock') from None


def _stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def _symbol(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Z0-9]{6}', value) is None or value == '000000':
        raise ProfileError('invalid_symbol')
    return value


def _session(value, code='daily_session'):
    try:
        if isinstance(value, str) and date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise ProfileError(code)


def _sessions(values):
    if not isinstance(values, (list, tuple)) or len(values) != SESSIONS_REQUIRED:
        raise ProfileError('calendar_invalid')
    days = [_session(day, 'calendar_invalid') for day in values]
    if len(set(days)) != SESSIONS_REQUIRED or any(date.fromisoformat(day).weekday() >= 5 for day in days):
        raise ProfileError('calendar_invalid')
    return sorted(days)


def _completed_through(now):
    local = _clock(now).astimezone(KST)
    day = local.date() if local.time() >= time(20, 30) else local.date() - timedelta(days=1)
    return day.isoformat()


def _number(value, field, code='daily_ohlcv'):
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError()
        number = float(value)
        maximum = 1e20 if field == 'traded_value' else 1e15 if field == 'volume' else 1e12
        if not math.isfinite(number) or not 0 <= number <= maximum:
            raise ValueError()
        if field not in ('volume', 'traded_value') and number == 0:
            raise ValueError()
        if field == 'volume' and not number.is_integer():
            raise ValueError()
        return number
    except (ValueError, TypeError, OverflowError):
        raise ProfileError(code) from None


def _flags(value):
    if not isinstance(value, dict):
        raise ProfileError('daily_payload')
    result = {}
    for key in EVENT_FIELDS:
        if key in value:
            text = value[key]
            if not isinstance(text, str) or len(text) > 80 or any(ord(char) < 32 for char in text):
                raise ProfileError('daily_payload')
            result[key] = text
    return result


def _price_event(flags):
    neutral = {'flng_cls_code': {'', '0', '00'}, 'mod_yn': {'', 'N'},
               'revl_issu_reas': {'', '0', '00'}}
    for key, value in flags.items():
        if key == 'prtt_rate':
            try:
                if value and float(value) != 0:
                    return True
            except (ValueError, OverflowError):
                return True
        elif value not in neutral[key]:
            return True
    return False


def _bar(raw, symbol):
    if not isinstance(raw, dict):
        raise ProfileError('daily_payload')
    if raw.get('symbol') != symbol:
        raise ProfileError('daily_identity')
    row = dict(symbol=symbol, date=_session(raw.get('date')))
    row.update({field: _number(raw.get(field), field) for field in PRICE_FIELDS})
    if not (row['low'] <= row['open'] <= row['high'] and row['low'] <= row['close'] <= row['high']):
        raise ProfileError('daily_ohlcv')
    if (row['volume'] == 0) != (row['traded_value'] == 0):
        raise ProfileError('daily_ohlcv')
    row['source_flags'] = _flags(raw.get('source_flags', {}))
    return row


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ProfileError('daily_payload')
    return value.strip()


def _bins(rows):
    low, high = min(row['low'] for row in rows), max(row['high'] for row in rows)
    count = 1 if low == high else BIN_COUNT
    edges = [low + (high-low)*index/count for index in range(count)] + [high]
    volumes, values = [[] for _ in range(count)], [[] for _ in range(count)]
    for row in rows:
        if not row['volume']:
            continue
        if row['low'] == row['high']:
            index = min(count-1, bisect_right(edges, row['low'])-1)
            portions = [(index, 1.0)]
        else:
            width = row['high'] - row['low']
            portions = [(index, max(0.0, min(row['high'], edges[index+1]) - max(row['low'], edges[index]))/width)
                        for index in range(count)]
            portions = [(index, part) for index, part in portions if part > 0]
        # Assign rounding residual to the last occupied bin, preserving both
        # independently observed totals rather than deriving turnover from close.
        allocated_volume, allocated_value = [], []
        for offset, (index, fraction) in enumerate(portions):
            last = offset == len(portions)-1
            volume = row['volume']-math.fsum(allocated_volume) if last else row['volume']*fraction
            value = row['traded_value']-math.fsum(allocated_value) if last else row['traded_value']*fraction
            volumes[index].append(volume)
            values[index].append(value)
            allocated_volume.append(volume)
            allocated_value.append(value)
    total = math.fsum(row['volume'] for row in rows)
    return [dict(index=index, low=edges[index], high=edges[index+1],
                 volume=math.fsum(volumes[index]), volume_pct=math.fsum(volumes[index])/total*100,
                 traded_value=math.fsum(values[index])) for index in range(count)]


def build_profile(symbol, name, bars, sessions, *, fetched_at, source, calendar_source):
    """Return a replayable profile or explicit no-level state; never fetch data."""
    symbol, sessions = _symbol(symbol), _sessions(sessions)
    fetched = _clock(fetched_at)
    if sessions[-1] > _completed_through(fetched):
        raise ProfileError('daily_session_incomplete')
    if not isinstance(bars, (list, tuple)) or len(bars) > 100:
        raise ProfileError('daily_payload')
    found = {}
    for raw in bars:
        row = _bar(raw, symbol)
        day = row['date']
        if day in found:
            raise ProfileError('daily_duplicate')
        if day > sessions[-1]:
            raise ProfileError('daily_future_row')
        if day not in sessions:
            raise ProfileError('daily_session_mismatch')
        found[day] = row
    rows = [found[day] for day in sessions if day in found]
    evidence = dict(symbol=symbol, sessions=sessions, bars=rows, method=METHOD,
                    source=_text(source, 160), calendar_source=_text(calendar_source, 160), price_basis=PRICE_BASIS)
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':'),
                                            ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    result = dict(symbol=symbol, name=_text(name, 160), status='insufficient_history', reason='missing_sessions',
                  as_of=sessions[-1], fetched_at=_stamp(fetched), window_start=sessions[0], window_end=sessions[-1],
                  sessions_required=SESSIONS_REQUIRED, sessions_used=len(rows), reference_price=None,
                  total_volume=None, total_traded_value=None, poc=None, support=None, resistance=None,
                  current_zone=None, bins=[], method=METHOD, source=evidence['source'],
                  calendar_source=evidence['calendar_source'], price_basis=PRICE_BASIS,
                  limitations=list(LIMITATIONS), fingerprint=fingerprint)
    if any(_price_event(row['source_flags']) for row in rows):
        return dict(result, status='price_event_review', reason='provider_price_event_unverified')
    if len(rows) != SESSIONS_REQUIRED:
        return result
    total_volume = math.fsum(row['volume'] for row in rows)
    if total_volume == 0:
        return dict(result, reason='zero_volume_window')
    bins = _bins(rows)
    reference = rows[-1]['close']
    occupied = [zone for zone in bins if zone['volume'] > 0]

    def strongest(zones):
        return max(zones, key=lambda zone: (zone['volume'], -zone['index']), default=None)

    index = min(len(bins)-1, bisect_right([zone['low'] for zone in bins], reference)-1)
    result.update(status='ready', reason='completed_sessions', reference_price=reference,
                  total_volume=total_volume, total_traded_value=math.fsum(row['traded_value'] for row in rows),
                  bins=bins, poc=strongest(occupied), current_zone=bins[index],
                  support=strongest([zone for zone in occupied if zone['high'] < reference]),
                  resistance=strongest([zone for zone in occupied if zone['low'] > reference]))
    return result
