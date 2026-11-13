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
        {'day': 'd1', 'probability': 0.9, 'raw_score': None, 'outcome': 1},
        {'day': 'd1', 'probability': 0.8, 'raw_score': None, 'outcome': 0},
        {'day': 'd1', 'probability': 0.1, 'raw_score': None, 'outcome': 1},
        {'day': 'd2', 'probability': 0.5, 'raw_score': None, 'outcome': 1},
    ]
    assert metrics.top_k_precision(rows, k=2) == pytest.approx(2 / 3)
    assert metrics.top_k_precision([], k=2) is None


def test_top_k_precision_skips_a_day_whose_cut_is_tied():
    tied = [{'day': 'd1', 'probability': 0.5, 'raw_score': None, 'outcome': outcome} for outcome in (1, 1, 1, 0, 0)]
    assert metrics.top_k_precision(tied, k=3) is None
    clear = [{'day': 'd2', 'probability': 0.9, 'raw_score': None, 'outcome': 0},
             {'day': 'd2', 'probability': 0.1, 'raw_score': None, 'outcome': 1}]
    assert metrics.top_k_precision(tied + clear, k=1) == 0.0
    # 동률이 컷 안쪽(1·2위)에만 있으면 그날은 그대로 쓴다.
    inside = [{'day': 'd3', 'probability': 0.9, 'raw_score': None, 'outcome': 1},
              {'day': 'd3', 'probability': 0.9, 'raw_score': None, 'outcome': 0},
              {'day': 'd3', 'probability': 0.1, 'raw_score': None, 'outcome': 1}]
    assert metrics.top_k_precision(inside, k=2) == 0.5


def test_top_k_precision_breaks_probability_ties_by_raw_score():
    rows = [
        {'day': 'd1', 'probability': 0.5, 'raw_score': 0.1, 'outcome': 0},
        {'day': 'd1', 'probability': 0.5, 'raw_score': 0.9, 'outcome': 1},
        {'day': 'd1', 'probability': 0.5, 'raw_score': None, 'outcome': 0},
        {'day': 'd1', 'probability': 0.5, 'raw_score': 0.7, 'outcome': 1},
    ]
    assert metrics.top_k_precision(rows, k=2) == 1.0
    assert metrics.top_k_precision(rows, k=3) == pytest.approx(2 / 3)  # 점수가 없는 행이 맨 뒤


def test_top_k_precision_groups_by_the_day_key_not_by_timestamp():
    rows = [
        {'day': 'd1', 'asof_ts': 't1', 'probability': 0.9, 'raw_score': None, 'outcome': 1},
        {'day': 'd1', 'asof_ts': 't2', 'probability': 0.8, 'raw_score': None, 'outcome': 0},
        {'day': 'd1', 'asof_ts': 't3', 'probability': 0.7, 'raw_score': None, 'outcome': 0},
    ]
    assert metrics.top_k_precision(rows, k=1) == 1.0


def test_block_bootstrap_is_deterministic_and_brackets_the_mean():
    rows = [{'entry_date': f'd{index % 25:02d}', 'value': float(index % 4)} for index in range(200)]
    stat = lambda sample: sum(row['value'] for row in sample) / len(sample)  # noqa: E731
    first = metrics.block_bootstrap_ci(rows, stat)
    assert first == metrics.block_bootstrap_ci(rows, stat)
    assert first[0] <= stat(rows) <= first[1]


def test_block_bootstrap_resamples_whole_days():
    rows = [{'entry_date': f'd{day:02d}', 'value': float(day % 2)} for day in range(20) for _ in range(5)]
    seen, means = set(), set()

    def stat(sample):
        seen.add(len(sample))
        mean = sum(row['value'] for row in sample) / len(sample)
        means.add(round(mean * 20, 9))
        return mean

    low, high = metrics.block_bootstrap_ci(rows, stat, n_boot=200)
    # 하루(5행)를 통째로 뽑으므로 표본 크기는 늘 100, 평균은 1/20 단위로만 움직인다.
    assert seen == {100} and all(value == int(value) for value in means)
    assert 0.0 < low < 0.5 < high < 1.0


def test_block_bootstrap_needs_twenty_distinct_blocks():
    stat = lambda sample: sum(row['value'] for row in sample) / len(sample)  # noqa: E731
    one_day = [{'entry_date': 'd1', 'value': float(index % 2)} for index in range(100)]
    nineteen = [{'entry_date': f'd{index % 19:02d}', 'value': float(index % 2)} for index in range(190)]
    twenty = [{'entry_date': f'd{index % 20:02d}', 'value': float(index % 3)} for index in range(200)]
    assert metrics.MIN_BLOCKS == 20
    assert metrics.block_bootstrap_ci(one_day, stat) is None
    assert metrics.block_bootstrap_ci(nineteen, stat) is None
    assert metrics.block_bootstrap_ci(twenty, stat) is not None
