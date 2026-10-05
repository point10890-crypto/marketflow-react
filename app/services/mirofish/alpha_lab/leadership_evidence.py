"""Strict public boundary for optional observational leadership evidence.

This never supplies approval, position sizing, a market index or a probability.
Unknown private extensions are discarded; malformed/binding-mismatched context
is omitted without changing the original sealed opportunity decision.
"""
from copy import deepcopy
import math
import re

POLICY = 'quality-leadership-context-v1'
CHECKS = ('top3', 'fresh', 'trend', 'near_high')
METRICS = ('reference_price', 'ret_21', 'ret_63', 'from_high_252', 'trend_quality')
ROW_KEYS = ('symbol', 'name', 'rank', 'status', *METRICS, 'checks', 'points', 'available_checks', 'reasons')
KEYS = ('policy_version', 'input_fingerprint', 'source_audit_hash', 'latest_session',
        'status', 'cohort', 'market', 'selected', 'watchlist')


def _int(value, maximum=100):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _text(value):
    return (isinstance(value, str) and 0 < len(value.strip()) <= 100
            and not re.search(r'[\x00-\x1f\x7f]|[A-Za-z]:[\\/]|\.env\b|<[^>]*>|\bBearer\s|\bTraceback\b|'
                              r'(?:^|\s)/(?:home|srv|tmp|Users|private)\b|'
                              r'(?:api[_-]?key|access[_-]?token|secret)\s*[:=]|'
                              r'(?:미래|예상)\s*승률|(?:수익|승률).*보장', value, re.I))


def _row(value, comparative, valid):
    if not isinstance(value, dict) or any(key not in value for key in ROW_KEYS):
        return None
    symbol = value['symbol']
    if (not isinstance(symbol, str) or not re.fullmatch('[0-9]{6}', symbol) or symbol == '000000'
            or not _text(value['name']) or value['status'] not in ('ready', 'unavailable')
            or not isinstance(value['checks'], dict) or any(key not in value['checks'] for key in CHECKS)
            or not _int(value['points'], 4) or not _int(value['available_checks'], 4)
            or not isinstance(value['reasons'], list) or len(value['reasons']) > 20
            or any(not isinstance(code, str) or re.fullmatch('[a-z][a-z0-9_]{0,95}', code) is None for code in value['reasons'])):
        return None
    checks = {key: value['checks'][key] for key in CHECKS}
    if (any(v is not None and not isinstance(v, bool) for v in checks.values())
            or value['points'] != sum(v is True for v in checks.values())
            or value['available_checks'] != sum(v is not None for v in checks.values())):
        return None
    rank = value['rank']
    if rank is not None and (not _int(rank, valid) or rank == 0):
        return None
    if value['status'] == 'unavailable':
        if (rank is not None or any(value[key] is not None for key in METRICS)
                or any(v is not None for v in checks.values()) or not value['reasons']):
            return None
    else:
        if (not all(_finite(value[key]) for key in METRICS if key != 'trend_quality')
                or not (_finite(value['trend_quality']) or value['trend_quality'] is None and 'undefined_trend_quality' in value['reasons'])
                or value['reference_price'] <= 0
                or min(value['ret_21'], value['ret_63']) <= -1
                or not -1 < value['from_high_252'] <= 1e-10
                or any(checks[key] is None for key in ('fresh', 'trend', 'near_high'))
                or checks['fresh'] != (.1 <= value['ret_21'] <= .4)
                or checks['near_high'] != (value['from_high_252'] >= -.25)
                or checks['trend'] is True and checks['near_high'] is not True):
            return None
        if comparative:
            if ((rank is not None) != checks['trend']
                    or checks['top3'] != (rank is not None and rank <= 3)):
                return None
        elif rank is not None or checks['top3'] is not None:
            return None
    result = {key: deepcopy(value[key]) for key in ROW_KEYS}
    result['checks'] = checks
    return result


def public_leadership_context(value, board):
    """Return canonical, source-bound context, or None when it cannot be read."""
    if not isinstance(value, dict) or not isinstance(board, dict) or any(key not in value for key in KEYS):
        return None
    if (value['policy_version'] != POLICY or value['status'] not in ('ready', 'unavailable')
            or any(value[key] != board.get(key) for key in ('input_fingerprint', 'source_audit_hash', 'latest_session'))
            or not isinstance(value['cohort'], dict) or not isinstance(value['market'], dict)
            or not isinstance(value['selected'], list) or not isinstance(value['watchlist'], list)
            or len(value['selected']) > 3 or len(value['watchlist']) > 7):
        return None
    cohort = {key: value['cohort'].get(key) for key in ('inspected', 'valid', 'above_ma200', 'strict_trend')}
    if (not all(_int(v) for v in cohort.values())
            or not cohort['strict_trend'] <= cohort['above_ma200'] <= cohort['valid'] <= cohort['inspected']):
        return None
    comparative = cohort['valid'] >= 8
    market = {key: value['market'].get(key) for key in ('basis', 'state', 'ratio')}
    ratio = market['ratio']
    if market['basis'] != 'quality_cohort_price_breadth' or value['status'] != ('ready' if comparative else 'unavailable'):
        return None
    if comparative:
        expected = cohort['above_ma200']/cohort['valid']
        state = 'broad' if expected >= .6 else 'mixed' if expected >= .4 else 'weak'
        if not _finite(ratio) or not math.isclose(ratio, expected, rel_tol=1e-9, abs_tol=1e-10) or market['state'] != state:
            return None
    elif ratio is not None or market['state'] != 'unknown' or value['watchlist']:
        return None
    selected = [_row(row, comparative, cohort['valid']) for row in value['selected']]
    watchlist = [_row(row, comparative, cohort['valid']) for row in value['watchlist']]
    if any(row is None for row in [*selected, *watchlist]):
        return None
    if [row['symbol'] for row in selected] != [row.get('symbol') for row in board.get('candidates', [])]:
        return None
    # Symbols/hashes are authoritative; align display labels after the helper's
    # bounded-name fallback so a safe existing label never breaks the client.
    for row, candidate in zip(selected, board.get('candidates', [])):
        if candidate.get('name') is not None:
            if not _text(candidate['name']):
                return None
            row['name'] = candidate['name']
    if (len({row['symbol'] for row in [*selected, *watchlist]}) != len(selected)+len(watchlist)
            or any(row['status'] != 'ready' or row['checks']['trend'] is not True for row in watchlist)):
        return None
    ranks = [row['rank'] for row in watchlist]
    known_ranks = [row['rank'] for row in [*selected, *watchlist] if row['rank'] is not None]
    if (any(rank is None for rank in ranks) or ranks != sorted(ranks) or len(set(known_ranks)) != len(known_ranks)
            or any(rank > cohort['strict_trend'] for rank in known_ranks)):
        return None
    result = {key: deepcopy(value[key]) for key in KEYS}
    result.update(cohort=cohort, market=market, selected=selected, watchlist=watchlist)
    return result
