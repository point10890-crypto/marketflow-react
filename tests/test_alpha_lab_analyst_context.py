"""Fixed current-cohort context must remain descriptive and prefix-only."""
from copy import deepcopy
from datetime import date, timedelta
import importlib
import math

import pytest

FINGERPRINT = 'a' * 64
IDS = ['rev_5', 'low_vol_60', 'anti_max_21', 'attention_fade']


def module():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.analyst_context')
    except ModuleNotFoundError:
        pytest.fail('The analyst context implementation is missing')


def bars(symbol, count=61, last_rise=0.):
    start = date(2026, 7, 1)
    result = [dict(symbol=symbol, date=(start+timedelta(days=i)).isoformat(),
                   open=100., high=101., low=99., close=100., volume=1000.) for i in range(count)]
    result[-1].update(close=100.+last_rise, high=101.+last_rise)
    return result


def cohort(count=8, rises=None):
    return {f'{i+1:06d}': bars(f'{i+1:06d}', last_rise=(rises[i] if rises else 0.)) for i in range(count)}


def build(prices, **kwargs):
    return module().build_analyst_context(prices, as_of=kwargs.pop('as_of', '2026-08-30'),
                                          input_fingerprint=kwargs.pop('input_fingerprint', FINGERPRINT), **kwargs)


def test_observed_metrics_have_exact_windows_and_amount_is_a_price_volume_proxy():
    prices = cohort(rises=[100.] * 8)
    row = build(prices)['000001']
    metrics = {item['id']: item['metric_value'] for item in row['analysts']}
    # 59 zero daily returns and one +100% return have sample variance 1/60.
    assert metrics == pytest.approx(dict(rev_5=1., low_vol_60=math.sqrt(4.2), anti_max_21=1.,
                                        attention_fade=1.180327868852459))
    assert row['status'] == 'ready' and row['score'] == 50.
    assert [item['id'] for item in row['analysts']] == IDS
    assert all(item['percentile'] == 50. and item['stance'] == 'neutral' for item in row['analysts'])
    assert (row['favorable_count'], row['caution_count'], row['neutral_count']) == (0, 0, 4)
    assert row['cohort_count'] == row['comparison_count'] == 8
    assert row['symbol'] == '000001' and row['as_of'] == '2026-08-30'
    assert row['input_fingerprint'] == FINGERPRINT and row['scope'] == 'current_quality_cohort'
    assert row['schema_version'] == 1 and row['policy_version'] == 'quality-analyst-context-v1'
    assert row['reasons'] == []


def test_anti_max_includes_exactly_last_twenty_one_daily_returns():
    prices = cohort()
    for rows in prices.values():
        rows[39].update(close=200., high=201.)
    assert build(prices)['000001']['analysts'][2]['metric_value'] == 0.
    for rows in prices.values():
        rows[39].update(close=100., high=101.)
        rows[40].update(close=200., high=201.)
    assert build(prices)['000001']['analysts'][2]['metric_value'] == 1.


def test_low_vol_uses_sample_sixty_daily_returns_and_reversal_uses_five_session_return():
    prices = cohort()
    for rows in prices.values():
        rows[0].update(open=50., high=51., low=49., close=50.)
        rows[55].update(open=80., high=81., low=79., close=80.)
    row = build(prices)['000001']
    assert row['analysts'][0]['metric_value'] == .25
    assert row['analysts'][1]['metric_value'] > 2.  # Oldest of sixty returns is still included.


def test_lower_metrics_are_favorable_with_average_ties_and_stable_symbol_order():
    prices = cohort(rises=[0., 0., 10., 20., 30., 40., 50., 60.])
    expected = build(prices)
    assert build(dict(reversed(list(prices.items())))) == expected
    for symbol in ('000001', '000002'):
        assert expected[symbol]['score'] == 92.857143
        assert expected[symbol]['favorable_count'] == 4
        assert all(item['percentile'] == 92.857143 for item in expected[symbol]['analysts'])
    assert expected['000008']['score'] == 0. and expected['000008']['caution_count'] == 4


def test_stances_follow_displayed_rounded_boundary_percentiles():
    result = build(cohort(10, [10.*i for i in range(10)]))
    assert result['000004']['score'] == 66.666667 and result['000004']['favorable_count'] == 4
    assert result['000007']['score'] == 33.333333 and result['000007']['caution_count'] == 4


def test_future_invalid_bars_do_not_change_calendar_factors_or_inputs():
    prices = cohort(rises=[10.*i for i in range(8)])
    original = deepcopy(prices)
    expected = build(prices)
    later = deepcopy(prices)
    for rows in later.values():
        rows.append(dict(date='2026-08-31', close=float('nan'), volume=False, quality_flags='corrupt_price'))
    future_copy = deepcopy(later)
    assert build(later) == expected
    assert prices == original and later == future_copy


def assert_unavailable(row, comparison_count):
    assert row['status'] == 'unavailable' and row['score'] is None
    assert row['comparison_count'] == comparison_count
    assert (row['favorable_count'], row['caution_count'], row['neutral_count']) == (0, 0, 0)
    assert [item['id'] for item in row['analysts']] == IDS
    assert all(item['metric_value'] is None and item['percentile'] is None
               and item['stance'] == 'unavailable' for item in row['analysts'])


def test_fewer_than_eight_common_valid_names_do_not_publish_optimistic_ranks():
    for row in build(cohort(7)).values():
        assert_unavailable(row, 7)
        assert row['reasons'] == ['insufficient_cohort']
    prices = cohort(); prices['000001'][-1]['volume'] = 0.
    result = build(prices)
    for row in result.values():
        assert_unavailable(row, 7)
    assert 'latest_quote_nontradable' in result['000001']['reasons']


@pytest.mark.parametrize('change,reason', [
    (lambda rows: rows.pop(), 'missing_current_quote'),
    (lambda rows: rows.pop(30), 'sparse_factor_window'),
    (lambda rows: rows.append(deepcopy(rows[-1])), 'invalid_observation'),
    (lambda rows: rows.reverse(), 'invalid_observation'),
    (lambda rows: rows[-1].update(date='2026-02-30'), 'invalid_observation'),
    (lambda rows: rows[-1].update(close=float('nan')), 'invalid_observation'),
    (lambda rows: rows[-1].update(high=float('inf')), 'invalid_observation'),
    (lambda rows: rows[-1].update(close=True), 'invalid_observation'),
    (lambda rows: rows[-1].update(volume=False), 'invalid_observation'),
    (lambda rows: rows[-1].update(volume=-1.), 'invalid_observation'),
    (lambda rows: rows[-1].update(low=101.), 'invalid_observation'),
    (lambda rows: rows[-1].update(open=0.), 'invalid_observation'),
    (lambda rows: rows[-1].update(symbol='999999'), 'invalid_observation'),
    (lambda rows: rows[20].update(quality_flags='invalid_bar'), 'flagged_observation'),
    (lambda rows: rows[20].update(flags=['suspicious_source']), 'flagged_observation'),
    (lambda rows: rows[-1].update(volume=0.), 'latest_quote_nontradable'),
])
def test_one_malformed_or_sparse_symbol_is_not_repaired_or_counted(change, reason):
    prices = cohort(9); change(prices['000001'])
    result = build(prices)
    assert_unavailable(result['000001'], 8)
    assert reason in result['000001']['reasons']
    assert all(row['status'] == 'ready' and row['comparison_count'] == 8
               for symbol, row in result.items() if symbol != '000001')


@pytest.mark.parametrize('rows,reason', [(None, 'missing_prices'), ([], 'missing_prices'),
                                       ('unknown', 'invalid_observation'), ([{}], 'invalid_observation')])
def test_missing_or_unknown_price_groups_remain_typed_unavailable(rows, reason):
    prices = cohort(9); prices['000001'] = rows
    row = build(prices)['000001']
    assert_unavailable(row, 8)
    assert reason in row['reasons']


def test_short_history_and_nonpositive_estimated_amount_are_unavailable():
    prices = cohort(9); prices['000001'] = prices['000001'][-60:]
    assert 'insufficient_history' in build(prices)['000001']['reasons']
    prices = cohort(9)
    for row in prices['000001']:
        row.update(open=1e-300, high=1e-300, low=1e-300, close=1e-300, volume=1e-300)
    row = build(prices)['000001']
    assert_unavailable(row, 8)
    assert 'nonpositive_amount_mean' in row['reasons']


def test_extreme_finite_prices_cannot_feed_nonfinite_daily_returns_to_statistics():
    prices = cohort(9)
    for row in prices['000001']:
        row.update(open=1e-308, high=1e-308, low=1e-308, close=1e-308, volume=1.)
    prices['000001'][-1].update(open=1e308, high=1e308, low=1e308, close=1e308)
    row = build(prices)['000001']
    assert_unavailable(row, 8)
    assert 'invalid_observation' in row['reasons']


@pytest.mark.parametrize('bad_key', [True, 1, None, 'ABCDEF'])
def test_invalid_cohort_symbols_are_rejected_before_sorting(bad_key):
    prices = cohort(); prices[bad_key] = bars('000009')
    with pytest.raises(ValueError):
        build(prices)


@pytest.mark.parametrize('kwargs', [dict(as_of=None), dict(as_of=True), dict(as_of='2026-02-30'),
                                  dict(input_fingerprint=True), dict(input_fingerprint='a'*63),
                                  dict(input_fingerprint='g'*64), dict(input_fingerprint='A'*64)])
def test_invalid_requested_cutoff_or_input_binding_is_rejected(kwargs):
    with pytest.raises(ValueError):
        build(cohort(), **kwargs)


def test_entry_guard_is_bound_manual_reference_math_without_backtest_or_order_claim():
    result = module().build_entry_guard('196170', '2026-08-30', 100.1234567, FINGERPRINT)
    assert result == dict(policy_version='reference-chase-cap-v1', symbol='196170', as_of='2026-08-30',
        input_fingerprint=FINGERPRINT, reference_price=100.1234567, max_chase_fraction=.02,
        max_entry_price=102.125926, applies_to='manual_next_open_reference', backtest_applied=False)


@pytest.mark.parametrize('symbol,session,price,fingerprint', [
    (True, '2026-08-30', 100., FINGERPRINT), ('123', '2026-08-30', 100., FINGERPRINT),
    ('196170', True, 100., FINGERPRINT), ('196170', '2026-02-30', 100., FINGERPRINT),
    ('196170', '2026-08-30', True, FINGERPRINT), ('196170', '2026-08-30', '100', FINGERPRINT),
    ('196170', '2026-08-30', 0., FINGERPRINT), ('196170', '2026-08-30', -100., FINGERPRINT),
    ('196170', '2026-08-30', float('nan'), FINGERPRINT), ('196170', '2026-08-30', float('inf'), FINGERPRINT),
    ('196170', '2026-08-30', 1.79e308, FINGERPRINT), ('196170', '2026-08-30', 100., 'x'*64),
    ('196170', '2026-08-30', 100., 'A'*64),
])
def test_entry_guard_rejects_invalid_identity_clock_numeric_or_fingerprint(symbol, session, price, fingerprint):
    with pytest.raises(ValueError):
        module().build_entry_guard(symbol, session, price, fingerprint)
