"""The fixed candidate policy must earn evidence before exposing proposals."""
from copy import deepcopy
from datetime import date, timedelta
import math

import pytest


def module():
    from app.services.mirofish.alpha_lab import candidate_detection
    return candidate_detection


def sessions(count=756):
    values, day = [], date(2022, 1, 3)
    while len(values) < count:
        if day.weekday() < 5:
            values.append(day.isoformat())
        day += timedelta(days=1)
    return values


def cohort(*, rotating=True, leaders=6, count=756, gap=0.):
    """Six rotating liquid trends plus six slower causal comparison stocks.

    The next open can gap independently of the current close. A +8% gap
    produces losing time/stop labels despite the same qualifying close trend.
    """
    days, result = sessions(count), {}
    for number in range(12):
        symbol, rows, close = f'{number+1:06d}', [], 10_000.
        for at, day in enumerate(days):
            drift = (.0018 + .001 * math.sin(2*math.pi*at/126 + number*math.pi/3)
                     if number < leaders and rotating else .0018 if number < leaders else .0001)
            previous = close
            close *= 1+drift
            opening = previous*(1+gap) if at else close
            rows.append(dict(symbol=symbol, date=day, open=opening,
                             high=max(opening, close)*1.003,
                             low=min(opening, close)*.997, close=close,
                             volume=2_000_000., traded_value=close*2_000_000.))
        result[symbol] = rows
    return result


def test_positive_rotating_pool_produces_up_to_three_causal_conditional_plans():
    prices = cohort(); before = deepcopy(prices)
    result = module().discover_candidates(prices, names={'000001': '한글 종목'})
    assert result['policy_version'] == 'cross-sectional-candidates-v3'
    assert result['inspected_count'] == 12
    assert 1 <= len(result['candidates']) <= 3
    assert result['eligible_count'] >= len(result['candidates'])
    assert prices == before
    assert all(set(item) >= {'id', 'label', 'count'} for item in result['funnel'])
    formation, confirmation = (result['evidence'][key] for key in ('formation', 'confirmation'))
    assert formation['samples'] >= 30 and confirmation['samples'] >= 10
    assert formation['unique_symbols'] >= 5
    assert formation['block_count'] >= 5 and confirmation['block_count'] >= 3
    for phase in (formation, confirmation):
        assert phase['mean_net_return'] > 0 and phase['stress_mean_net_return'] > 0
        assert 'compounded_trade_return' not in phase
        assert phase['block_stress_stats']['samples'] == phase['block_count']
    for index, candidate in enumerate(result['candidates'], 1):
        plan, risk = candidate['plan'], candidate['risk']
        assert candidate['rank'] == index
        close = prices[candidate['symbol']][-1]['close']
        assert plan['entry_price'] == close
        assert plan['entry_upper'] == pytest.approx(close*1.02)
        assert 0 < plan['loss_fraction'] <= .08
        assert plan['stop_price'] < close < plan['target_price']
        assert plan['target_price']-close == pytest.approx(2*(close-plan['stop_price']))
        assert plan['horizon_sessions'] == 10
        assert risk['kelly_fraction'] == .25
        assert risk['reference_weight'] == pytest.approx(min(.05, .25*risk['raw_kelly'], .01/plan['loss_fraction']))
        assert risk['approved_exposure'] == 0 and risk['live_orders'] is False
        assert candidate['reason_facts'] and all(isinstance(value, str) and len(value) <= 240 for value in candidate['reason_facts'])


def test_target_and_peer_future_mutations_do_not_change_cutoff_decision_or_evidence():
    prices = cohort(); cutoff = sessions()[-1]
    expected = module().discover_candidates(prices, as_of=cutoff)
    for symbol, rows in prices.items():
        rows.append(dict(symbol=symbol, date='2035-01-02', open=False, high=-1,
                         low=float('nan'), close='bad', volume=None))
    assert module().discover_candidates(prices, as_of=cutoff) == expected


def test_formation_is_purged_before_embargo_and_immune_to_later_peer_outcomes():
    prices = cohort(); result = module().discover_candidates(prices)
    days = sessions()
    assert result['evidence']['formation']['start'] == days[116]
    assert result['evidence']['formation']['end'] == days[619]
    assert result['evidence']['confirmation']['start'] == days[630]
    assert result['evidence']['confirmation']['end'] == days[755]
    assert result['evidence']['embargo'] == {'start': days[620], 'end': days[629], 'sessions': 10}
    expected = deepcopy(result['audit']['phases']['formation'])
    for rows in prices.values():
        for row in rows[620:]:
            row.update(open=row['open']*1.1, high=row['high']*1.2, low=row['low']*.9,
                       close=row['close']*1.1)
    assert module().discover_candidates(prices)['audit']['phases']['formation'] == expected
    for key in ('formation', 'confirmation'):
        phase = result['evidence'][key]
        trades = result['audit']['phases'][key]['trades']
        assert all(phase['start'] <= row['signal_date'] < row['entry_date'] <= row['exit_date'] <= phase['end'] for row in trades)
        assert all(row['signal_date'] not in days[620:630] for row in trades)


def test_selected_trades_use_actual_next_union_open_identical_stress_fills_and_no_overlap():
    prices = cohort(); result = module().discover_candidates(prices)
    days, indices = sessions(), {day: at for at, day in enumerate(sessions())}
    for key in ('formation', 'confirmation'):
        last_exit = {}
        for trade in result['audit']['phases'][key]['trades']:
            symbol, at = trade['symbol'], indices[trade['signal_date']]
            assert trade['entry_date'] == days[at+1]
            assert trade['entry_price'] == prices[symbol][at+1]['open']
            assert trade['holding_sessions'] <= 10
            assert trade['net_return'] == pytest.approx(trade['exit_price']*.997/(trade['entry_price']*1.001)-1)
            assert trade['stress_net_return'] == pytest.approx(trade['exit_price']*.994/(trade['entry_price']*1.002)-1)
            assert symbol not in last_exit or last_exit[symbol] < trade['entry_date']
            last_exit[symbol] = trade['exit_date']
            ranked = module().discover_candidates({sym: rows[:at+1] for sym, rows in prices.items()})['audit']['current_ranking']
            assert symbol in [item['symbol'] for item in ranked[:3]]


def test_correlated_same_date_peers_do_not_create_extra_calendar_blocks_or_unique_symbols():
    result = module().discover_candidates(cohort(rotating=False, leaders=3))
    phase = result['evidence']['formation']
    assert phase['samples'] >= 30
    assert phase['unique_symbols'] == 3
    assert phase['block_count'] <= 51
    assert phase['block_stress_stats']['samples'] == phase['block_count']
    assert phase['samples'] > phase['block_count']
    assert result['candidates'] == []
    assert 'formation_insufficient_unique_symbols' in result['reasons']


def test_negative_economics_returns_no_candidates_and_names_exact_pool_rejections():
    prices = cohort()
    for rows in prices.values():
        for row in rows:
            row['low'] = row['close']*.90
    result = module().discover_candidates(prices)
    assert result['audit']['current_ranking']
    assert result['evidence']['formation']['mean_net_return'] < 0
    assert result['candidates'] == []
    assert result['eligible_count'] == 0
    assert 'formation_nonpositive_mean_net_return' in result['reasons']
    assert result['rejection_counts']['formation_nonpositive_mean_net_return'] > 0


def test_current_rank_uses_fixed_percentiles_without_padding_failed_stocks():
    prices = cohort()
    # Only one candidate remains above the dated median at the final close.
    for symbol, rows in prices.items():
        if symbol != '000001':
            row = rows[-1]; close = row['close']*.80
            row.update(open=close, high=close*1.003, low=close*.997, close=close)
    result = module().discover_candidates(prices)
    assert [row['symbol'] for row in result['audit']['current_ranking']] == ['000001']
    assert [row['symbol'] for row in result['candidates']] == ['000001']
    assert result['candidates'][0]['strength_score'] <= 100


def test_sparse_holding_is_excluded_and_not_replaced_with_a_later_observed_open():
    prices = cohort(); original = module().discover_candidates(prices)
    trade = original['audit']['phases']['formation']['trades'][0]
    symbol, signal = trade['symbol'], trade['signal_date']
    prices[symbol] = [row for row in prices[symbol] if row['date'] != trade['entry_date']]
    result = module().discover_candidates(prices)
    assert not any(row['symbol'] == symbol and row['signal_date'] == signal
                   for row in result['audit']['phases']['formation']['trades'])
    assert result['audit']['phases']['formation']['diagnostics']['missing_next_union_quote'] >= 1


@pytest.mark.parametrize('field,value', [('close', True), ('high', float('nan')), ('volume', -1.), ('traded_value', float('inf'))])
def test_malformed_numeric_inputs_fail_explicitly(field, value):
    prices = cohort(); prices['000001'][-1][field] = value
    with pytest.raises(ValueError, match='OHLCV|traded_value'):
        module().discover_candidates(prices)


def test_warning_flags_preserve_trend_but_nontradable_flags_block_current_setup():
    prices = cohort(); expected = module().discover_candidates(prices)
    symbol = expected['candidates'][0]['symbol']
    prices[symbol][-1]['quality_flags'] = [{'code': 'provider_price_event_unverified', 'severity': 'warning'}]
    warning = module().discover_candidates(prices)
    assert symbol in [row['symbol'] for row in warning['candidates']]
    assert 'provider_price_event_unverified' in warning['audit']['source_warnings']
    prices[symbol][-1]['quality_flags'] = [{'code': 'zero_volume_nontradable', 'severity': 'nontradable'}]
    blocked = module().discover_candidates(prices)
    assert symbol not in [row['symbol'] for row in blocked['candidates']]
    assert 'quality_flagged_factor_window' in next(row for row in blocked['audit']['current'] if row['symbol'] == symbol)['reasons']


def test_empirical_kelly_handles_mixed_all_winning_and_all_losing_net_returns():
    estimate = module().empirical_long_only_kelly
    assert estimate([.10, -.10]) == 0.
    assert estimate([.10, .02]) == 1.
    assert estimate([-.10, -.02]) == 0.
    # 60% +100%, 40% -100% has the familiar optimum 20%.
    assert estimate([1., 1., 1., -1., -1.]) == pytest.approx(.2)


def test_short_history_exposes_current_funnel_without_fabricating_pool_labels():
    result = module().discover_candidates(cohort(count=100))
    assert result['candidates'] == []
    assert result['audit']['current_ranking']
    assert result['evidence']['formation']['samples'] == 0
    assert 'insufficient_union_history' in result['reasons']


def test_rank_matches_hand_computed_weighted_percentiles_and_volume_cap():
    prices = {}
    for number, (drift, ratio) in enumerate(((.003, 1.), (.002, 20.), (.001, 2.), (0., 1.)), 1):
        symbol, rows = f'{number:06d}', []
        for at, day in enumerate(sessions(61)):
            close = 10_000*(1+drift)**at
            rows.append(dict(symbol=symbol, date=day, open=close, high=close*1.003,
                             low=close*.997, close=close,
                             volume=2_000_000.*(ratio if at == 60 else 1.)))
        prices[symbol] = rows
    ranked = module().discover_candidates(prices)['audit']['current_ranking']
    assert [row['symbol'] for row in ranked] == ['000001', '000002']
    # Momentum20/60 and prior-high order give 1 and 2/3 to the first two.
    # Volume ratios are [1, capped3, 2, 1], so their midranks are 1/6 and 1.
    assert ranked[0]['strength_score'] == pytest.approx(91.66666666666667)
    assert ranked[1]['strength_score'] == pytest.approx(70.)
    assert ranked[1]['volume_ratio'] == 3.


@pytest.mark.parametrize('mutation', ['out_of_order', 'duplicate', 'identity', 'flags'])
def test_malformed_identity_dates_and_flags_fail_instead_of_silently_repairing(mutation):
    prices = cohort(count=100); rows = prices['000001']
    if mutation == 'out_of_order':
        rows[-1], rows[-2] = rows[-2], rows[-1]
    elif mutation == 'duplicate':
        rows.append(deepcopy(rows[-1]))
    elif mutation == 'identity':
        rows[-1]['symbol'] = '999999'
    else:
        rows[-1]['quality_flags'] = [{'code': 'ambiguous'}]
    with pytest.raises(ValueError, match='OHLCV'):
        module().discover_candidates(prices)


@pytest.mark.parametrize('flags', [False, {}, 0, [None], [{'code': 'bad', 'severity': None}]])
def test_malformed_flag_containers_never_silently_turn_into_clean_quotes(flags):
    prices = cohort(count=100)
    prices['000001'][-1]['quality_flags'] = flags
    with pytest.raises(ValueError, match='OHLCV quality'):
        module().discover_candidates(prices)


def test_generated_reason_facts_and_names_remain_bounded_with_large_finite_source_values():
    prices = cohort()
    for rows in prices.values():
        for row in rows:
            row['traded_value'] = 1e300
    result = module().discover_candidates(prices, names={symbol: 'A'*1000 for symbol in prices})
    assert result['candidates']
    assert all(len(row['name']) <= 120 for row in result['candidates'])
    assert all(len(fact) <= 240 for row in result['candidates'] for fact in row['reason_facts'])


def test_entry_ceiling_rejects_gap_labels_and_low_atr_current_proposals_consistently():
    gap = module().discover_candidates(cohort(gap=.08))
    assert gap['audit']['current_ranking']
    assert gap['evidence']['formation']['samples'] == 0
    assert gap['audit']['phases']['formation']['diagnostics']['unfilled_signal'] > 0
    assert gap['candidates'] == []
    prices = cohort()
    for rows in prices.values():
        for row in rows:
            row.update(open=row['close'], high=row['close'], low=row['close'])
    low_atr = module().discover_candidates(prices)
    assert low_atr['audit']['current_ranking']
    assert low_atr['candidates'] == []
    assert low_atr['evidence']['formation']['samples'] == 0
    assert low_atr['rejection_counts']['current_entry_band_invalid'] > 0
