"""Causal, deterministic AlphaLab factor and training-only model contracts."""
import copy
import importlib
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def engine():
    assert (ROOT / 'app/services/mirofish/alpha_lab/features.py').exists(), 'AlphaLab causal features are not implemented'
    return importlib.import_module('app.services.mirofish.alpha_lab.features')


def bars(n=100):
    rows = []
    last = 100.
    for index in range(n):
        close = 100. * math.exp(.002 * index + .01 * math.sin(index / 3))
        rows.append(dict(symbol='000001', date=(date(2024, 1, 1) + timedelta(days=index)).isoformat(),
                         open=last, high=max(last, close) * 1.01, low=min(last, close) * .99,
                         close=close, volume=1000. + index))
        last = close
    return rows


def test_prefix_factors_ignore_future_append_and_preserve_input():
    module = engine()
    rows = bars()
    untouched = copy.deepcopy(rows)
    prefix = module.features_at(rows[:71], 70)
    rows[80]['close'] = 1e9  # Malformed future data must not be examined.
    assert module.features_at(rows, 70) == prefix
    assert module.features_at(untouched, 70) == prefix
    assert rows[:71] == untouched[:71]
    assert module.features_at(untouched, 59) is None


def test_momentum_and_volume_oracles_use_only_observed_prefix():
    module = engine()
    rows = bars()
    result = module.features_at(rows, 60)
    assert result['momentum_5'] == pytest.approx(rows[60]['close'] / rows[55]['close'] - 1)
    assert result['momentum_60'] == pytest.approx(rows[60]['close'] / rows[0]['close'] - 1)
    assert result['volume_ratio_20'] == pytest.approx(rows[60]['volume'] / (sum(row['volume'] for row in rows[40:60]) / 20))
    assert all(math.isfinite(value) for value in result.values())


def test_zero_volume_and_flat_ranges_do_not_invent_liquidity_or_variance():
    module = engine()
    rows = [dict(row, open=100., high=100., low=100., close=100., volume=0.) for row in bars()]
    result = module.features_at(rows, 70)
    assert result['volatility_20'] == result['volume_ratio_20'] == result['atr_fraction'] == 0
    assert result['range_position_20'] == .5


def test_invalid_observed_bars_fail_closed():
    module = engine()
    rows = bars()
    rows[50]['volume'] = float('nan')
    with pytest.raises(ValueError):
        module.features_at(rows, 70)


def test_fixed_strategy_catalogue_is_explicit_and_scores_are_not_probabilities():
    module = engine()
    assert [row['strategy_id'] for row in module.STRATEGIES] == ['momentum', 'liquidity_breakout', 'mean_reversion', 'ridge_ranker']
    feature = module.features_at(bars(), 70)
    for row in module.STRATEGIES:
        assert row['score_interpretation'] == 'ranking_score_not_probability'
        assert math.isfinite(module.score_strategy(row['strategy_id'], feature))
    with pytest.raises(ValueError):
        module.score_strategy('hyperparameter_search', feature)


def test_ridge_standardization_is_fitted_only_to_training_rows():
    module = engine()
    training = [{name: float(index) for name in module.FEATURE_NAMES} for index in range(4)]
    model = module.fit_ridge(training, [-.03, -.01, .01, .03])
    assert model['means'] == pytest.approx([1.5] * len(module.FEATURE_NAMES))
    assert model['ridge_lambda'] == 1.
    saved = copy.deepcopy(model)
    high = {name: 1000. for name in module.FEATURE_NAMES}
    module.score_strategy('ridge_ranker', high, model)
    assert model == saved
    assert module.fit_ridge(training, [-.03, -.01, .01, .03]) == model
    assert module.score_strategy('ridge_ranker', training[3], model) > module.score_strategy('ridge_ranker', training[0], model)


def test_ridge_rejects_nonfinite_labels_instead_of_imputing_them():
    module = engine()
    training = [module.features_at(bars(), index) for index in (60, 65)]
    with pytest.raises(ValueError):
        module.fit_ridge(training, [0., float('nan')])

def test_saved_model_cannot_silently_drop_feature_coefficients():
    module = engine()
    training = [module.features_at(bars(), index) for index in (60, 65, 70)]
    model = module.fit_ridge(training, [-.02, .01, .02])
    model['coefficients'].pop()
    with pytest.raises(ValueError):
        module.score_strategy('ridge_ranker', training[-1], model)
