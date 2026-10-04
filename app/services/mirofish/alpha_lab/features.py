"""Original causal factors inspired by Qlib's price/volume research vocabulary.

Reference: https://github.com/microsoft/qlib (MIT), revision
be725493eb1a6bbb42bf11b37aa7669f59610ff1. No upstream code is vendored.
Scores are rankings or predicted net returns, never win probabilities.
"""
from __future__ import annotations

import math
from datetime import date
from statistics import fmean, stdev

FEATURE_NAMES = ('momentum_5', 'momentum_20', 'momentum_60', 'volatility_20',
                 'volume_ratio_20', 'range_position_20', 'candle_body', 'atr_fraction',
                 'gap_return', 'breakout_20')
STRATEGIES = tuple(dict(strategy_id=identifier, name=name,
                       score_interpretation='ranking_score_not_probability')
                   for identifier, name in (
                       ('momentum', '추세 지속'), ('liquidity_breakout', '거래량 동반 돌파'),
                       ('mean_reversion', '과매도 회복'), ('ridge_ranker', '순손익 학습 순위')))
SOURCE_ACKNOWLEDGEMENT = dict(url='https://github.com/microsoft/qlib', license='MIT',
    revision='be725493eb1a6bbb42bf11b37aa7669f59610ff1', implementation='original_factor_implementation_no_vendored_code')


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Factors require finite numeric observations')
    return float(value)


def features_at(rows, index):
    """Compute the observed 61-bar prefix window; future rows are never read."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(rows):
        raise ValueError('Feature index is outside the observed rows')
    window = rows[max(0, index - 60):index + 1]
    normalized = []
    previous_day = None
    for raw in window:
        if not isinstance(raw, dict):
            raise ValueError('Feature observations must be OHLCV objects')
        day = raw.get('date')
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or (previous_day and day <= previous_day):
            raise ValueError('Feature dates must be ordered canonical sessions')
        row = {key: _number(raw.get(key)) for key in ('open', 'high', 'low', 'close', 'volume')}
        if min(row[key] for key in ('open', 'high', 'low', 'close')) <= 0 or row['volume'] < 0:
            raise ValueError('Feature prices must be positive and volume nonnegative')
        if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
            raise ValueError('Feature OHLC extrema are inconsistent')
        normalized.append(row)
        previous_day = day
    if len(normalized) < 61:
        return None
    close = [row['close'] for row in normalized]
    today = normalized[-1]
    returns = [close[i] / close[i - 1] - 1. for i in range(len(close) - 20, len(close))]
    volume_mean = fmean(row['volume'] for row in normalized[-21:-1])
    lows, highs = min(row['low'] for row in normalized[-20:]), max(row['high'] for row in normalized[-20:])
    ranges = [max(row['high'] - row['low'], abs(row['high'] - close[i - 1]),
                  abs(row['low'] - close[i - 1])) for i, row in enumerate(normalized) if i > 0]
    span = today['high'] - today['low']
    result = dict(momentum_5=close[-1] / close[-6] - 1., momentum_20=close[-1] / close[-21] - 1.,
                  momentum_60=close[-1] / close[0] - 1., volatility_20=stdev(returns),
                  volume_ratio_20=today['volume'] / volume_mean if volume_mean > 0 else 0.,
                  range_position_20=(today['close'] - lows) / (highs - lows) if highs > lows else .5,
                  candle_body=(today['close'] - today['open']) / span if span > 0 else 0.,
                  atr_fraction=fmean(ranges[-14:]) / today['close'],
                  gap_return=today['open'] / close[-2] - 1.,
                  breakout_20=today['close'] / max(row['high'] for row in normalized[-21:-1]) - 1.)
    if any(not math.isfinite(value) for value in result.values()):
        raise ValueError('Factor arithmetic exceeded finite bounds')
    return result


def fit_ridge(training_features, net_returns):
    """Fit one preregistered lambda=1 model using training-only normalization."""
    import numpy as np
    if len(training_features) != len(net_returns) or len(net_returns) < 2:
        raise ValueError('Ridge requires matching completed training labels')
    matrix = np.asarray([[_number(row.get(key)) for key in FEATURE_NAMES] for row in training_features], dtype=float)
    target = np.asarray([_number(value) for value in net_returns], dtype=float)
    means, scales = matrix.mean(axis=0), matrix.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.)
    standardized = (matrix - means) / scales
    intercept = float(target.mean())
    coefficients = np.linalg.solve(standardized.T @ standardized + np.eye(len(FEATURE_NAMES)),
                                   standardized.T @ (target - intercept))
    if not np.isfinite(coefficients).all():
        raise ValueError('Ridge model exceeded finite bounds')
    return dict(feature_names=list(FEATURE_NAMES), means=means.tolist(), scales=scales.tolist(),
                coefficients=coefficients.tolist(), intercept=intercept, ridge_lambda=1.,
                training_samples=len(net_returns), normalization='training_only',
                label='completed_future_net_bracket_return')


def score_strategy(strategy_id, features, model=None):
    """Use fixed formulas or the frozen training model, without fitting on input."""
    values = {key: _number(features.get(key)) for key in FEATURE_NAMES}
    volatility = max(values['volatility_20'], .005)
    if strategy_id == 'momentum':
        return (.5 * values['momentum_20'] + .5 * values['momentum_60']) / volatility
    if strategy_id == 'liquidity_breakout':
        return values['breakout_20'] / volatility + .25 * values['volume_ratio_20'] + values['range_position_20'] - .5
    if strategy_id == 'mean_reversion':
        return -values['momentum_5'] / volatility + .2 * (.5 - values['range_position_20'])
    if strategy_id != 'ridge_ranker':
        raise ValueError('Unknown preregistered strategy')
    if model is None:
        return 0.
    if model.get('feature_names') != list(FEATURE_NAMES) or model.get('ridge_lambda') != 1.:
        raise ValueError('Ridge score requires the frozen feature and lambda contract')
    if any(not isinstance(model.get(key), list) or len(model[key]) != len(FEATURE_NAMES)
           for key in ('means', 'scales', 'coefficients')):
        raise ValueError('Ridge vectors must match every frozen feature')
    score = _number(model['intercept'])
    for key, mean, scale, coefficient in zip(FEATURE_NAMES, model['means'], model['scales'], model['coefficients']):
        divisor = _number(scale)
        if divisor <= 0:
            raise ValueError('Ridge scale must be positive')
        score += (values[key] - _number(mean)) / divisor * _number(coefficient)
    return _number(score)
