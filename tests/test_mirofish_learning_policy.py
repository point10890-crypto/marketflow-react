from __future__ import annotations

from datetime import datetime, timezone

from app.services.mirofish import learning_policy


def test_learning_policy_enables_bounded_memory_after_replay_safe_backtest():
    daily = {
        'generated_at': '2026-06-10T00:00:00+00:00',
        'lookahead_safe': True,
        'mature_cutoff_date': '2026-06-02',
        'enhanced': {
            'sample_count': 151,
            'expectancy_r': 0.42,
            'information_coefficient': 0.12,
            'profit_factor': 1.8,
            'win_rate': 0.58,
            'thresholds_met': {
                'expectancy_r': True,
                'information_coefficient': True,
                'profit_factor': True,
                'sample_count': True,
            },
        },
        'plan_a_success': True,
    }
    policy = learning_policy.build_learning_policy(
        {
            'available': True,
            'evaluated_count': 12,
            'hit_rate_recent': 0.62,
            'lookahead_safe': True,
        },
        daily_report=daily,
        rolling_report={'sample_count': 3, 'lookahead_safe': True},
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert policy['backtest_gate']['status'] == 'validated'
    assert policy['score_control']['outcome_memory_enabled'] is True
    assert policy['score_control']['status'] == 'bounded_adaptive'
    assert learning_policy.tag_delta_bounds(policy, default=(-2, 2)) == (-2.0, 2.0)
    assert policy['learning_readiness']['learning_active'] is True


def test_learning_policy_blocks_memory_when_backtest_sample_is_too_small():
    daily = {
        'generated_at': '2026-06-10T00:00:00+00:00',
        'lookahead_safe': True,
        'enhanced': {
            'sample_count': 18,
            'expectancy_r': 0.6,
            'information_coefficient': 0.2,
        },
    }
    policy = learning_policy.build_learning_policy(
        {'available': True, 'evaluated_count': 20, 'hit_rate_recent': 0.7, 'lookahead_safe': True},
        daily_report=daily,
        rolling_report={},
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert policy['backtest_gate']['status'] == 'insufficient_sample'
    assert policy['score_control']['outcome_memory_enabled'] is False
    assert learning_policy.global_delta_bounds(policy, default=(-3, 3)) == (0.0, 0.0)


def test_learning_policy_enables_small_caps_while_backtest_is_maturing(monkeypatch):
    monkeypatch.delenv('MIROFISH_LEARNING_DISABLED', raising=False)
    daily = {
        'generated_at': '2026-06-10T00:00:00+00:00',
        'lookahead_safe': True,
        'enhanced': {
            'sample_count': 52,
            'expectancy_r': 0.19,
            'information_coefficient': 0.09,
            'profit_factor': 1.3,
            'win_rate': 0.54,
            'thresholds_met': {
                'expectancy_r': False,
                'information_coefficient': True,
                'sample_count': False,
            },
        },
    }
    policy = learning_policy.build_learning_policy(
        {'available': True, 'evaluated_count': 20, 'hit_rate_recent': 0.7, 'lookahead_safe': True},
        daily_report=daily,
        rolling_report={},
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert policy['backtest_gate']['status'] == 'maturing'
    assert policy['score_control']['outcome_memory_enabled'] is True
    assert policy['score_control']['status'] == 'bounded_maturing'
    assert learning_policy.tag_delta_bounds(policy, default=(-2, 2)) == (-1.5, 0.75)
    assert learning_policy.global_delta_bounds(policy, default=(-3, 3)) == (-2.0, 1.0)
    assert policy['learning_readiness']['learning_active'] is True


def test_learning_policy_keeps_thirty_nine_samples_observe_only(monkeypatch):
    monkeypatch.setenv('MIROFISH_MIN_BACKTEST_SAMPLES_BOUNDED', '40')
    daily = {
        'generated_at': '2026-06-10T00:00:00+00:00',
        'lookahead_safe': True,
        'enhanced': {
            'sample_count': 39,
            'expectancy_r': 0.5,
            'information_coefficient': 0.2,
        },
    }
    policy = learning_policy.build_learning_policy(
        {'available': True, 'evaluated_count': 20, 'hit_rate_recent': 0.7, 'lookahead_safe': True},
        daily_report=daily,
        rolling_report={},
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert policy['backtest_gate']['status'] == 'insufficient_sample'
    assert policy['backtest_gate']['min_sample_count_bounded'] == 40
    assert policy['score_control']['outcome_memory_enabled'] is False


def test_learning_policy_defensive_mode_blocks_positive_boosts():
    daily = {
        'generated_at': '2026-06-10T00:00:00+00:00',
        'lookahead_safe': True,
        'enhanced': {
            'sample_count': 150,
            'expectancy_r': -0.1,
            'information_coefficient': 0.05,
        },
    }
    policy = learning_policy.build_learning_policy(
        {'available': True, 'evaluated_count': 20, 'hit_rate_recent': 0.7, 'lookahead_safe': True},
        daily_report=daily,
        rolling_report={},
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert policy['backtest_gate']['status'] == 'defensive'
    assert policy['score_control']['outcome_memory_enabled'] is True
    assert learning_policy.tag_delta_bounds(policy, default=(-2, 2)) == (-2.0, 0.0)


def test_learning_policy_env_kill_switch_forces_observe_only(monkeypatch):
    monkeypatch.setenv('MIROFISH_LEARNING_DISABLED', 'true')
    daily = {
        'generated_at': '2026-06-10T00:00:00+00:00',
        'lookahead_safe': True,
        'enhanced': {
            'sample_count': 150,
            'expectancy_r': 0.4,
            'information_coefficient': 0.12,
        },
    }
    policy = learning_policy.build_learning_policy(
        {'available': True, 'evaluated_count': 20, 'hit_rate_recent': 0.7, 'lookahead_safe': True},
        daily_report=daily,
        rolling_report={},
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert policy['score_control']['outcome_memory_enabled'] is False
    assert policy['score_control']['disable_code'] == 'env_disabled'
    assert learning_policy.global_delta_bounds(policy, default=(-3, 3)) == (0.0, 0.0)


def test_learning_policy_guard_disables_after_consecutive_top3_deterioration(monkeypatch):
    monkeypatch.delenv('MIROFISH_LEARNING_DISABLED', raising=False)
    daily = {
        'generated_at': '2026-06-10T00:00:00+00:00',
        'lookahead_safe': True,
        'enhanced': {
            'sample_count': 150,
            'expectancy_r': 0.4,
            'information_coefficient': 0.12,
        },
    }
    top3_worse = {
        'lookahead_safe': True,
        'insufficient': False,
        'evaluated_runs': 6,
        'qualified_runs': 6,
        'total_evaluated_items': 24,
        'pooled': {
            'top3_item_count': 18,
            'top3_return_lift': -0.2,
            'top3_hit_rate': 0.4,
        },
        'macro': {'precision_at_3': 0.4},
    }
    guard_state = {
        'disabled': False,
        'worse_streak': 1,
        'baseline': {
            'top3_return_lift': 0.3,
            'precision_at_3': 0.65,
            'top3_item_count': 18,
        },
    }

    policy = learning_policy.build_learning_policy(
        {'available': True, 'evaluated_count': 20, 'hit_rate_recent': 0.7, 'lookahead_safe': True},
        daily_report=daily,
        rolling_report={},
        top3_report=top3_worse,
        guard_state=guard_state,
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert policy['learning_guard']['disabled'] is True
    assert policy['score_control']['outcome_memory_enabled'] is False
    assert policy['score_control']['disable_code'] == 'guard_disabled'
    assert policy['learning_readiness']['learning_active'] is False
