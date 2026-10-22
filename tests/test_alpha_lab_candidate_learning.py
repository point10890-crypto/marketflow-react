"""A separate contextual inference model cannot reuse confirmation labels."""
from copy import deepcopy
from datetime import date, timedelta
import math

import pytest


def api():
    from app.services.mirofish.alpha_lab import candidate_learning
    return candidate_learning


def cohort(count=756):
    days, day = [], date(2022, 1, 3)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    prices = {}
    for number in range(12):
        symbol, rows, close = f'{number+1:06d}', [], 10_000.
        for at, day in enumerate(days):
            drift = .0018+.001*math.sin(2*math.pi*at/126+number*math.pi/3) if number < 6 else .0001
            previous = close; close *= 1+drift
            rows.append(dict(symbol=symbol, date=day, open=previous,
                             high=max(previous, close)*1.003, low=min(previous, close)*.997,
                             close=close, volume=2_000_000., traded_value=close*2_000_000.))
        prices[symbol] = rows
    return prices


def test_context_inference_uses_other_symbols_and_causal_formation_memory_only():
    prices = cohort(); before = deepcopy(prices)
    result = api().discover_context_candidates(prices)
    assert result['policy_version'] == 'contextual-candidates-v4'
    assert result['model'] == dict(name='causal-context-neighbors-v1', status='experimental',
                                   training_end=prices['000001'][619]['date'],
                                   comparison_interpretation='v3_unconditional_retrospective_control_not_v4_holdout',
                                   validation='forward_collecting')
    assert 1 <= len(result['candidates']) <= 3
    assert prices == before
    for candidate in result['candidates']:
        evidence = candidate['model_evidence']
        assert evidence['samples'] >= 30 and evidence['block_count'] >= 5
        assert evidence['unique_symbols'] >= 5
        assert evidence['neighbors_exclude_target'] is True
        assert evidence['training_end'] == prices['000001'][619]['date']
        assert evidence['mean_net_return'] > 0 and evidence['stress_mean_net_return'] > 0
        assert evidence['expected_net_return'] > 0 and evidence['expected_stress_net_return'] > 0
        neighbors = result['audit']['contexts'][candidate['symbol']]['neighbors']
        assert 30 <= len(neighbors) <= 60
        assert all(row['symbol'] != candidate['symbol'] for row in neighbors)
        assert all(row['exit_date'] <= evidence['training_end'] for row in neighbors)
        plan, risk = candidate['plan'], candidate['risk']
        assert plan['stop_price'] < plan['entry_price'] < plan['entry_upper'] < plan['target_price']
        assert plan['entry_upper'] == pytest.approx(plan['entry_price']*1.02)
        assert risk['reference_weight'] == min(.01, .25*risk['raw_kelly'], .01/plan['loss_fraction'])
        assert risk['kelly_fraction'] == .25 and risk['approved_exposure'] == 0 and risk['live_orders'] is False


def test_future_target_and_peer_rows_cannot_change_a_fixed_cutoff_result():
    prices = cohort(); cutoff = prices['000001'][-1]['date']
    expected = api().discover_context_candidates(prices, as_of=cutoff)
    for symbol, rows in prices.items():
        rows.append(dict(symbol=symbol, date='2035-01-02', open=False, close=float('nan'), volume=-1))
    assert api().discover_context_candidates(prices, as_of=cutoff) == expected


def test_negative_global_comparison_remains_visible_without_becoming_model_training_or_gate():
    prices = cohort()
    expected = api().discover_context_candidates(prices)
    for rows in prices.values():
        for row in rows[630:695]:
            row['low'] = row['close']*.90
    result = api().discover_context_candidates(prices)
    assert result['evidence']['confirmation']['mean_net_return'] < 0
    assert result['evidence']['confirmation']['stress_mean_net_return'] < 0
    assert result['candidates'] == expected['candidates']
    assert result['audit']['training_scales'] == expected['audit']['training_scales']
    assert result['audit']['contexts'] == expected['audit']['contexts']
    from app.services.mirofish.alpha_lab.candidate_detection import discover_candidates
    control = discover_candidates(prices)
    assert result['evidence']['formation'] == control['evidence']['formation']
    assert result['evidence']['confirmation'] == control['evidence']['confirmation']
    assert control['candidates'] == []


def test_same_block_duplicates_do_not_inflate_equal_block_estimate_or_coverage():
    events = [dict(symbol='000001', block=0, net_return=.10, stress_net_return=.08),
              dict(symbol='000002', block=1, net_return=0., stress_net_return=0.)]
    first = api()._estimate(events, prior_net=.02, prior_stress=.01)
    duplicate = api()._estimate(events+[dict(events[0]) for _ in range(40)], prior_net=.02, prior_stress=.01)
    assert first['block_count'] == duplicate['block_count'] == 2
    assert first['mean_net_return'] == pytest.approx(.05)
    assert duplicate['mean_net_return'] == pytest.approx(.05)
    assert first['stress_mean_net_return'] == pytest.approx(.04)
    assert duplicate['stress_mean_net_return'] == pytest.approx(.04)
    assert first['expected_net_return'] == pytest.approx(.02857142857142857)
    assert duplicate['expected_net_return'] == pytest.approx(.02857142857142857)
    assert first['expected_stress_net_return'] == pytest.approx(.018571428571428572)
    assert duplicate['expected_stress_net_return'] == pytest.approx(.018571428571428572)


def test_negative_contexts_cannot_be_padded_into_proposals():
    prices = cohort()
    for rows in prices.values():
        for row in rows:
            row['low'] = row['close']*.90
    result = api().discover_context_candidates(prices)
    assert result['audit']['current_ranking']
    assert result['candidates'] == [] and result['eligible_count'] == 0
    assert result['rejection_counts']['nonpositive_expected_stress_net_return'] > 0
    assert result['reasons']


def test_only_one_current_setup_returns_one_model_proposal_without_padding():
    prices = cohort()
    for symbol, rows in prices.items():
        if symbol != '000001':
            close = rows[-1]['close']*.80
            rows[-1].update(open=close, high=close*1.003, low=close*.997, close=close)
    result = api().discover_context_candidates(prices)
    assert [row['symbol'] for row in result['candidates']] == ['000001']
    assert result['candidates'][0]['rank'] == 1


def test_short_history_has_no_training_labels_or_inference_proposals():
    result = api().discover_context_candidates(cohort(100))
    assert result['candidates'] == []
    assert result['model']['training_end'] is None
    assert 'insufficient_union_history' in result['reasons']
    assert result['audit']['training_scales'] == []


def test_target_training_outcome_mutation_cannot_leak_through_prior_or_scaling():
    prices = cohort(); expected = api().discover_context_candidates(prices)
    symbol = expected['candidates'][0]['symbol']
    for row in prices[symbol][116:620]:
        row['low'] = row['close']*.90
    result = api().discover_context_candidates(prices)
    assert result['evidence']['formation'] != expected['evidence']['formation']
    assert result['audit']['contexts'][symbol] == expected['audit']['contexts'][symbol]
    assert result['audit']['training_scales'][symbol] == expected['audit']['training_scales'][symbol]
    current = next(row for row in result['candidates'] if row['symbol'] == symbol)
    original = next(row for row in expected['candidates'] if row['symbol'] == symbol)
    assert current['model_evidence'] == original['model_evidence']
    assert current['plan'] == original['plan']
    assert current['risk'] == original['risk']


def test_standardized_distance_ignores_zero_variance_and_uses_training_scale():
    scales = [dict(standard_deviation=2.), dict(standard_deviation=0.), dict(standard_deviation=4.)]
    assert api()._distance((1., 999., 2.), (7., -999., 18.), scales) == 5.


def test_euclidean_distance_is_exactly_invariant_to_feature_accumulation_order():
    scales = [dict(standard_deviation=1.) for _ in range(8)]
    large_first = (1e8, 1., 1., 1., 1., 1., 1., 1.)
    large_last = tuple(reversed(large_first))
    origin = (0.,)*8
    assert api()._distance(large_first, origin, scales) == api()._distance(large_last, origin, scales)
    assert api()._distance(large_first, origin, scales) == 100000000.00000004
