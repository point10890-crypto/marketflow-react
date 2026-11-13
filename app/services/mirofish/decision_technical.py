"""Read-only bridge from immutable 20-session receipts to stock decisions.

This is another interpretation of the same KIS price/volume evidence, never an
independent vote. A stored profile is usable only after deterministic replay.
"""
from datetime import date
import json
import math
from pathlib import Path
import re

from .kongming_technical import service
from .kongming_technical.profile import CALENDAR_SOURCE, SOURCE, build_profile


_SUMMARY = {
    'ready': '완료된 20거래일의 거래량 집중 구간을 확인했습니다.',
    'pending': '20거래일 매물대 분석을 기다리고 있습니다.',
    'stale': '이전 매물대 자료입니다. 최신 거래일 확인 전에는 현재 판단에 사용하지 않습니다.',
    'insufficient_history': '20거래일의 유효한 거래 자료가 부족하여 가격 구간을 제시하지 않습니다.',
    'price_event_review': '주가 변동 행사 확인이 필요하여 가격 구간을 제시하지 않습니다.',
    'source_unavailable': '검증된 매물대 자료를 현재 확인할 수 없습니다.',
    'not_requested': '아직 저장된 20거래일 매물대 분석이 없습니다.',
    'unsupported_market': '20거래일 매물대 분석은 국내 종목 코드에만 제공됩니다.',
}
_HASH = re.compile(r'[0-9a-f]{64}')
_DYNAMIC_FIELDS = {'status', 'reason'}


def is_domestic_symbol(code):
    """Accept canonical KRX codes, including digit-leading alphanumeric codes."""
    return (isinstance(code, str) and re.fullmatch(r'[0-9][0-9A-Z]{5}', code) is not None
            and code != '000000')


def _envelope(symbol, status, profile=None):
    return dict(schema_version=1, agent=service.AGENT,
                symbol=symbol if isinstance(symbol, str) and len(symbol) <= 32 else '',
                market='KR' if is_domestic_symbol(symbol) else 'unsupported', status=status,
                profile=profile, summary=_SUMMARY[status],
                observations=_observations(profile) if status == 'ready' else [],
                independent_evidence=False)


def _same_fields(saved, expected, *, omitted=()):
    """Project allowlisted fields and reject NaN, booleans or altered types too."""
    if not isinstance(saved, dict):
        raise ValueError('invalid_profile')
    keys = expected.keys() - set(omitted)
    left = {key: saved[key] for key in keys}
    right = {key: expected[key] for key in keys}
    if (json.dumps(left, sort_keys=True, ensure_ascii=False, allow_nan=False)
            != json.dumps(right, sort_keys=True, ensure_ascii=False, allow_nan=False)):
        raise ValueError('profile_mismatch')


def _reconstruct(symbol, row, root, current):
    fingerprint = row.get('fingerprint')
    # Validate before using an artifact identifier as a path component.
    if not isinstance(fingerprint, str) or _HASH.fullmatch(fingerprint) is None:
        raise ValueError('invalid_fingerprint')
    receipt = service._read(root / 'history' / symbol / f'{fingerprint}.json')
    source, calendar, saved = receipt['input'], receipt['calendar'], receipt['profile']
    if source['source'] != SOURCE or calendar['source'] != CALENDAR_SOURCE:
        raise ValueError('invalid_provenance')
    fetched, captured = service._clock(source['fetched_at']), service._clock(calendar['captured_at'])
    through = calendar['through']
    if date.fromisoformat(through).isoformat() != through:
        raise ValueError('invalid_calendar')
    if (captured > fetched or fetched > current or through > service.completed_through(current)
            or not service._valid_calendar(calendar, through, current)):
        raise ValueError('invalid_clock')
    # No provider calls occur here: the engine replays the bounded immutable
    # receipt, including exact identity, session count, OHLCV and event checks.
    expected = build_profile(symbol, saved['name'], source['bars'], calendar['sessions'],
                             fetched_at=source['fetched_at'], source=source['source'],
                             calendar_source=calendar['source'])
    if expected['fingerprint'] != fingerprint:
        raise ValueError('fingerprint_mismatch')
    if source.get('name') and source['name'].strip() != expected['name']:
        raise ValueError('name_mismatch')
    _same_fields(saved, expected)
    # Receipts are immutable and keyed by content, not acquisition time. The
    # worker can fetch identical evidence again (e.g. missing profile recovery)
    # and retain the first receipt while updating the current capture clock.
    # Validate both clocks, then replay identical content at the newer clock;
    # every other saved field must still match the original evidence exactly.
    latest_fetched = service._clock(row['fetched_at'])
    if not fetched <= latest_fetched <= current:
        raise ValueError('invalid_clock')
    expected = build_profile(symbol, expected['name'], source['bars'], calendar['sessions'],
                             fetched_at=row['fetched_at'], source=source['source'],
                             calendar_source=calendar['source'])
    _same_fields(row, expected, omitted=_DYNAMIC_FIELDS)
    # read_view overlays freshness/error status. Check the on-disk calculation
    # separately so the overlay cannot conceal tampered original status/reason.
    _same_fields(service._read(root / 'profiles' / f'{symbol}.json'), expected)
    if row['status'] == 'stale':
        if expected['status'] != 'ready':
            raise ValueError('invalid_stale_profile')
        expected.update(status='stale', reason='next_session_refresh_pending')
    elif row['status'] != expected['status'] or row.get('reason') != expected['reason']:
        raise ValueError('invalid_status')
    return expected


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('invalid_number')
    return value


def _observations(profile):
    reference = _number(profile['reference_price'])
    if reference <= 0:
        raise ValueError('invalid_reference')
    as_of = profile['as_of']
    if date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError('invalid_date')
    lines = [f'기준가는 {as_of} 완료 거래일 종가 {reference:,.2f}원이며 실시간 시세가 아닙니다.']
    for field, label in [('support', '지지 후보'), ('resistance', '저항 후보')]:
        zone = profile[field]
        if zone is None:
            lines.append(f'{label}: 기준 종가와 분리된 거래량 집중 구간이 없습니다.')
            continue
        low, high, volume, share, value = (_number(zone[key]) for key in
                                         ('low', 'high', 'volume', 'volume_pct', 'traded_value'))
        if not 0 < low <= high or volume < 0 or not 0 <= share <= 100 or value < 0:
            raise ValueError('invalid_zone')
        distance_low, distance_high = (low / reference - 1) * 100, (high / reference - 1) * 100
        lines.append(f'{label} {low:,.2f}~{high:,.2f}원: 추정 거래량 {volume:,.2f}주 '
                     f'({share:.2f}%), 거래대금 {value:,.2f}원, '
                     f'기준 종가 대비 거리 {distance_low:+.2f}%~{distance_high:+.2f}%.')
    lines.append('일봉 범위에 균등 배분한 과거 거래 추정치이며 현재 보유 물량이나 매수 신호가 아닙니다.')
    return lines


def read_analysis(symbol, *, now=None, root=None):
    """Return a bounded public envelope; never enqueue, acquire, or write files."""
    if not is_domestic_symbol(symbol):
        return _envelope(symbol, 'unsupported_market')
    try:
        current = service._clock(now)
        root = Path(service.ROOT if root is None else root)
        view = service.read_view(root, symbol=symbol, now=current)
        if view.get('schema_version') != 1 or view.get('agent') != service.AGENT:
            raise ValueError('invalid_view')
        rows = view['items']
        if not isinstance(rows, list) or len(rows) > 1:
            raise ValueError('invalid_items')
        if not rows:
            return _envelope(symbol, 'not_requested')
        row = rows[0]
        if row.get('symbol') != symbol:
            raise ValueError('invalid_identity')
        status = row['status']
        if status in {'pending', 'source_unavailable'}:
            return _envelope(symbol, status)
        if status not in {'ready', 'stale', 'insufficient_history', 'price_event_review'}:
            raise ValueError('invalid_status')
        profile = _reconstruct(symbol, row, root, current)
        return _envelope(symbol, status, profile)
    except Exception:
        # Source/state failures must not block the main decision or disclose
        # provider payloads, local paths, credentials, or exception text.
        return _envelope(symbol, 'source_unavailable')


def format_context(analysis):
    """Add one ready technical interpretation to an existing LLM context."""
    try:
        if (not isinstance(analysis, dict) or analysis.get('status') != 'ready'
                or analysis.get('schema_version') != 1 or analysis.get('agent') != service.AGENT
                or analysis.get('market') != 'KR' or analysis.get('independent_evidence') is not False
                or not is_domestic_symbol(analysis.get('symbol'))):
            return ''
        profile = analysis['profile']
        if (profile['status'] != 'ready' or profile['symbol'] != analysis['symbol']
                or _HASH.fullmatch(profile['fingerprint']) is None):
            return ''
        # Recompute text instead of copying arbitrary observations or names.
        lines = [f"[20거래일 매물대 · {analysis['symbol']} · {profile['as_of']}]",
                 '기존 가격·거래량과 같은 KIS 자료의 재해석입니다. 독립 근거나 별도 매수 표로 집계하지 마세요.',
                 f"자료 지문: {profile['fingerprint']}", *_observations(profile)]
        return '\n'.join(lines)[:2000]
    except Exception:
        return ''
