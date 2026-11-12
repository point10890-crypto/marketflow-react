import math

import pytest

from app.services.forecast_league import metrics


def test_brier_and_log_loss():
    pairs = [(0.8, 1), (0.2, 0), (0.6, 0)]
    assert metrics.brier(pairs) == pytest.approx((0.04 + 0.04 + 0.36) / 3)
    assert metrics.log_loss(pairs) == pytest.approx(-(math.log(0.8) + math.log(0.8) + math.log(0.4)) / 3)


def test_calibration_groups_by_probability_bin():
    rows = metrics.calibration([(0.05, 0), (0.07, 1), (0.95, 1), (0.98, 1)], bins=10)
    assert rows == [
        {'lo': 0.0, 'hi': 0.1, 'n': 2, 'mean_probability': pytest.approx(0.06), 'hit_rate': 0.5},
        {'lo': 0.9, 'hi': 1.0, 'n': 2, 'mean_probability': pytest.approx(0.965), 'hit_rate': 1.0},
    ]


def test_top_k_precision_takes_the_highest_probabilities_per_day():
    rows = [
        {'asof_ts': 'd1', 'stock_code': 'a', 'probability': 0.9, 'outcome': 1},
        {'asof_ts': 'd1', 'stock_code': 'b', 'probability': 0.8, 'outcome': 0},
        {'asof_ts': 'd1', 'stock_code': 'c', 'probability': 0.1, 'outcome': 1},
        {'asof_ts': 'd2', 'stock_code': 'a', 'probability': 0.5, 'outcome': 1},
    ]
    assert metrics.top_k_precision(rows, k=2) == pytest.approx(2 / 3)
    assert metrics.top_k_precision([], k=2) is None


def test_block_bootstrap_is_deterministic_and_brackets_the_mean():
    rows = [{'entry_date': f'd{index % 10}', 'value': float(index % 4)} for index in range(200)]
    stat = lambda sample: sum(row['value'] for row in sample) / len(sample)  # noqa: E731
    first = metrics.block_bootstrap_ci(rows, stat)
    assert first == metrics.block_bootstrap_ci(rows, stat)
    assert first[0] <= stat(rows) <= first[1]


def test_block_bootstrap_resamples_whole_days():
    rows = [{'entry_date': 'd1', 'value': 0.0}] * 50 + [{'entry_date': 'd2', 'value': 1.0}] * 50
    seen = set()
    stat = lambda sample: seen.add(len(sample)) or sum(row['value'] for row in sample) / len(sample)  # noqa: E731
    low, high = metrics.block_bootstrap_ci(rows, stat, n_boot=200)
    assert seen == {100} and (low, high) == (0.0, 1.0)
