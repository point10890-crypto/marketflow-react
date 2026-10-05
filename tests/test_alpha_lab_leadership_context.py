"""Price leadership context preserves cutoff, invalid observations, and BUY3 scope."""
from copy import deepcopy
from datetime import date, timedelta
import importlib
import json

import pytest

FINGERPRINT = 'a' * 64
AUDIT_HASH = 'b' * 64
AS_OF = '2026-09-09'
ROW_KEYS = {'symbol', 'name', 'rank', 'status', 'reference_price', 'ret_21', 'ret_63',
            'from_high_252', 'trend_quality', 'checks', 'points', 'available_checks', 'reasons'}


def module():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.leadership_context')
    except ModuleNotFoundError:
        pytest.fail('The leadership context implementation is missing')


def bars(symbol, count=252, rising=True):
    start = date(2026, 1, 1)
    result = []
    for i in range(count):
        # Linear prices make horizon returns independently hand-checkable.
        price = (100. + i) if rising else (500. - i)
        result.append(dict(symbol=symbol, date=(start + timedelta(days=i)).isoformat(),
                           open=price, high=price + 1., low=price - 1., close=price, volume=1000.))
    return result


def cohort(count=10, rising=True):
    return {f'{i+1:06d}': bars(f'{i+1:06d}', rising=rising) for i in range(count)}


def build(prices, **kwargs):
    return module().build_leadership_context(prices, names=kwargs.pop('names', {}),
        as_of=kwargs.pop('as_of', AS_OF), input_fingerprint=kwargs.pop('input_fingerprint', FINGERPRINT),
        source_audit_hash=kwargs.pop('source_audit_hash', AUDIT_HASH),
        selected_symbols=kwargs.pop('selected_symbols', ['000001', '000002', '000003']), **kwargs)


def test_observed_metrics_strict_trend_breadth_and_selected_watchlist_are_bound():
    result = build(cohort(), names={'000001': 'Alpha'})
    assert result['policy_version'] == 'quality-leadership-context-v1'
    assert result['input_fingerprint'] == FINGERPRINT and result['source_audit_hash'] == AUDIT_HASH
    assert result['latest_session'] == AS_OF and result['status'] == 'ready'
    assert result['cohort'] == {'inspected': 10, 'valid': 10, 'above_ma200': 10, 'strict_trend': 10}
    assert result['market'] == {'basis': 'quality_cohort_price_breadth', 'state': 'broad', 'ratio': 1.}
    row = result['selected'][0]
    assert set(row) == ROW_KEYS and row['name'] == 'Alpha' and row['rank'] == 1
    assert row['status'] == 'ready' and row['reference_price'] == 351.
    assert row['ret_21'] == pytest.approx(351./330.-1.)
    assert row['ret_63'] == pytest.approx(351./288.-1.)
    assert row['from_high_252'] == 0. and row['trend_quality'] > 0.
    assert row['checks'] == {'top3': True, 'fresh': False, 'trend': True, 'near_high': True}
    assert row['points'] == 3 and row['available_checks'] == 4
    assert [x['symbol'] for x in result['watchlist']] == [f'{i:06d}' for i in range(4, 11)]
    assert not set(x['symbol'] for x in result['selected']) & set(x['symbol'] for x in result['watchlist'])
    json.dumps(result, allow_nan=False)


def test_future_invalid_rows_do_not_change_validity_calendar_ranks_or_mutate_inputs():
    prices = cohort()
    expected = build(prices)
    later = deepcopy(prices)
    for rows in later.values():
        rows.extend([dict(date='2026-09-10', close=float('nan'), volume=False, flags=['bad']),
                     dict(date='2026-09-10', close=None)])
    saved = deepcopy(later)
    assert build(later) == expected
    assert later == saved


@pytest.mark.parametrize('change,reason', [
    (lambda rows: rows.pop(30), 'sparse_factor_window'),
    (lambda rows: rows.pop(), 'missing_current_quote'),
    (lambda rows: rows.append(deepcopy(rows[-1])), 'invalid_observation'),
    (lambda rows: rows.reverse(), 'invalid_observation'),
    (lambda rows: rows[20].update(volume=0.), 'nontradable_observation'),
    (lambda rows: rows[-1].update(volume=0.), 'latest_quote_nontradable'),
    (lambda rows: rows[20].update(quality_flags=['bad']), 'flagged_observation'),
    (lambda rows: rows[-1].update(low=400.), 'invalid_observation'),
    (lambda rows: rows[-1].update(close=None), 'invalid_observation'),
    (lambda rows: rows[-1].update(close=float('nan')), 'invalid_observation'),
    (lambda rows: rows[-1].update(high=float('inf')), 'invalid_observation'),
    (lambda rows: rows[-1].update(volume=False), 'invalid_observation'),
    (lambda rows: rows[-1].update(open=0.), 'invalid_observation'),
    (lambda rows: rows[-1].update(symbol='999999'), 'invalid_observation'),
])
def test_sparse_halted_or_bad_bars_stay_unavailable_and_never_enter_watchlist(change, reason):
    prices = cohort(); change(prices['000001'])
    result = build(prices, selected_symbols=['000001'])
    row = result['selected'][0]
    assert result['cohort']['valid'] == 9
    assert row['status'] == 'unavailable' and reason in row['reasons']
    assert row['rank'] is None and row['reference_price'] is None
    assert row['points'] == row['available_checks'] == 0
    assert all(value is None for value in row['checks'].values())
    assert all(x['symbol'] != '000001' for x in result['watchlist'])
    json.dumps(result, allow_nan=False)


def test_thin_cohort_retains_own_metrics_but_has_no_comparative_or_market_claim():
    result = build(cohort(7))
    assert result['status'] == 'unavailable' and result['cohort']['valid'] == 7
    assert result['market'] == {'basis': 'quality_cohort_price_breadth', 'state': 'unknown', 'ratio': None}
    assert result['watchlist'] == []
    for row in result['selected']:
        assert row['status'] == 'ready' and row['ret_21'] is not None
        assert row['rank'] is None and row['checks']['top3'] is None
        assert row['available_checks'] == 3 and 'insufficient_cohort' in row['reasons']


def test_tied_scores_have_stable_symbol_ranks_and_selected_order_is_preserved():
    prices = cohort()
    first = build(prices, selected_symbols=['000003', '000001'])
    assert build(dict(reversed(list(prices.items()))), selected_symbols=['000003', '000001']) == first
    assert [(x['symbol'], x['rank']) for x in first['selected']] == [('000003', 3), ('000001', 1)]


def test_declining_names_are_not_used_to_fill_seven_watchlist_rows():
    prices = cohort(rising=False)
    prices['000004'] = bars('000004')
    result = build(prices)
    assert result['market']['state'] == 'weak' and result['market']['ratio'] == .1
    assert result['cohort']['strict_trend'] == 1
    assert [x['symbol'] for x in result['watchlist']] == ['000004']
    assert result['selected'][0]['checks']['trend'] is False
    assert result['selected'][0]['rank'] is None and result['selected'][0]['checks']['top3'] is False


@pytest.mark.parametrize('rising_count,state,ratio', [(4, 'mixed', .4), (6, 'broad', .6)])
def test_market_breadth_boundaries_use_valid_cohort_counts(rising_count, state, ratio):
    prices = cohort(rising=False)
    for i in range(rising_count):
        symbol = f'{i+1:06d}'
        prices[symbol] = bars(symbol)
    result = build(prices)
    assert result['market']['state'] == state and result['market']['ratio'] == ratio


def test_missing_selected_history_and_invalid_names_keep_safe_annotations():
    prices = cohort(); prices['000002'] = prices['000002'][-251:]
    result = build(prices, names={'000001': True, '000002': 'x'*81, '999999': '\x00bad'},
                   selected_symbols=['000001', '000002', '999999'])
    assert [x['name'] for x in result['selected']] == ['000001', '000002', '999999']
    assert result['selected'][1]['reasons'] == ['insufficient_history']
    assert result['selected'][2]['reasons'] == ['missing_prices']


@pytest.mark.parametrize('unsafe_name', ['<img src=x>', 'C:\\secret\\stock', '../hidden', '.ENV',
                                         'Bearer secret', 'x\x80y'])
def test_unsafe_source_names_fall_back_to_symbol_without_dropping_context(unsafe_name):
    result = build(cohort(), names={'000001': unsafe_name})
    assert result['status'] == 'ready' and result['selected'][0]['status'] == 'ready'
    assert result['selected'][0]['name'] == '000001'
    assert len(result['watchlist']) == 7


def test_zero_volatility_history_has_no_invented_trend_quality():
    prices = cohort()
    for rows in prices.values():
        for row in rows:
            row.update(open=100., high=101., low=99., close=100.)
    result = build(prices)
    row = result['selected'][0]
    assert result['status'] == row['status'] == 'ready'
    assert row['trend_quality'] is None and row['reasons'] == ['undefined_trend_quality']
    assert row['ret_21'] == row['ret_63'] == row['from_high_252'] == 0.
    assert row['checks']['trend'] is False and result['watchlist'] == []
    json.dumps(result, allow_nan=False)


def test_fresh_check_uses_twenty_one_sessions_and_public_output_has_finite_values_only():
    prices = cohort()
    for rows in prices.values():
        for i in range(231, 252):
            value = 330. + (i-230)*3.
            rows[i].update(open=value, high=value+1., low=value-1., close=value)
    result = build(prices)
    assert result['selected'][0]['ret_21'] == pytest.approx(393./330.-1.)
    assert result['selected'][0]['checks']['fresh'] is True
    json.dumps(result, allow_nan=False)


def test_extreme_finite_prices_are_unavailable_instead_of_overflowing_metrics():
    prices = cohort()
    for row in prices['000001']:
        row.update(open=1e-308, high=1e-308, low=1e-308, close=1e-308, volume=1.)
    prices['000001'][-1].update(open=1e308, high=1e308, low=1e308, close=1e308)
    result = build(prices)
    assert result['selected'][0]['status'] == 'unavailable'
    assert result['cohort']['valid'] == 9
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('kwargs', [dict(as_of=None), dict(as_of='2026-02-30'),
    dict(input_fingerprint='A'*64), dict(source_audit_hash='x'*64),
    dict(selected_symbols='000001'), dict(selected_symbols=[True]),
    dict(selected_symbols=['000001', '000001']), dict(names=[])])
def test_invalid_clock_hash_names_or_selected_identity_are_rejected(kwargs):
    with pytest.raises(ValueError):
        build(cohort(), **kwargs)


def test_invalid_cohort_identity_is_rejected_before_sorting():
    prices = cohort(); prices[True] = []
    with pytest.raises(ValueError):
        build(prices)
