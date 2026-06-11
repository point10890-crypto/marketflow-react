"""Replay-safe learning policy for MiroFish alpha detection.

The scanner should improve from verified outcomes, but only inside bounded
guards. This module turns outcome and backtest artifacts into a compact policy
that callers can use to decide whether adaptive ranking memory is safe to use.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / 'data' / 'admin_mirofish'
ALPHA_BACKTEST_DAILY_PATH = DATA_ROOT / 'alpha_backtest_daily.json'
ALPHA_BACKTEST_ROLLING_PATH = DATA_ROOT / 'alpha_backtest_rolling_7d.json'

MIN_OUTCOME_EVALUATED = 9
MIN_BACKTEST_SAMPLES = 100
MAX_BACKTEST_AGE_DAYS = 3


def build_learning_policy(
    performance_advisory: dict[str, Any] | None = None,
    *,
    daily_report: dict[str, Any] | None = None,
    rolling_report: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the current scanner learning policy from replay-safe artifacts."""
    now_dt = now or datetime.now(timezone.utc)
    advisory = performance_advisory if isinstance(performance_advisory, dict) else {}
    daily = daily_report if isinstance(daily_report, dict) else _read_json(ALPHA_BACKTEST_DAILY_PATH)
    rolling = rolling_report if isinstance(rolling_report, dict) else _read_json(ALPHA_BACKTEST_ROLLING_PATH)

    backtest = _backtest_state(daily, rolling, now_dt)
    outcome = _outcome_state(advisory)
    control = _score_control(backtest, outcome)

    return {
        'schema_version': 'mirofish.learning_policy.v1',
        'generated_at': now_dt.isoformat(),
        'primary_objective': 'improve Top3 alpha candidate detection from replay-safe outcomes',
        'mode': 'bounded_adaptive_scoring',
        'lookahead_safe': bool(backtest.get('lookahead_safe', True) and outcome.get('lookahead_safe', True)),
        'production_weights_mutated': False,
        'outcome_memory': outcome,
        'backtest_gate': backtest,
        'score_control': control,
    }


def tag_delta_bounds(policy: dict[str, Any] | None, *, default: tuple[float, float]) -> tuple[float, float]:
    """Return negative/positive tag-memory bounds from a learning policy."""
    control = (policy or {}).get('score_control') if isinstance(policy, dict) else {}
    if not isinstance(control, dict):
        return default
    if not control.get('outcome_memory_enabled'):
        return (0.0, 0.0)
    negative = _number(control.get('negative_tag_delta_cap'), default[0])
    positive = _number(control.get('positive_tag_delta_cap'), default[1])
    return (min(0.0, negative), max(0.0, positive))


def global_delta_bounds(policy: dict[str, Any] | None, *, default: tuple[float, float]) -> tuple[float, float]:
    """Return negative/positive global outcome-memory bounds from a policy."""
    control = (policy or {}).get('score_control') if isinstance(policy, dict) else {}
    if not isinstance(control, dict):
        return default
    if not control.get('outcome_memory_enabled'):
        return (0.0, 0.0)
    negative = _number(control.get('negative_global_delta_cap'), default[0])
    positive = _number(control.get('positive_global_delta_cap'), default[1])
    return (min(0.0, negative), max(0.0, positive))


def _backtest_state(
    daily: dict[str, Any],
    rolling: dict[str, Any],
    now_dt: datetime,
) -> dict[str, Any]:
    if not daily:
        return {
            'available': False,
            'status': 'missing',
            'ready': False,
            'reason': 'alpha_backtest_daily artifact is missing',
            'lookahead_safe': True,
        }

    enhanced = daily.get('enhanced') or daily.get('plan_a_false_signal_filter') or {}
    thresholds = enhanced.get('thresholds_met') if isinstance(enhanced.get('thresholds_met'), dict) else {}
    generated_at = str(daily.get('generated_at') or '')
    age_days = _age_days(generated_at, now_dt)
    sample_count = int(_number(enhanced.get('sample_count')))
    expectancy_r = _number(enhanced.get('expectancy_r'))
    ic = _number(enhanced.get('information_coefficient') if enhanced.get('information_coefficient') is not None else enhanced.get('IC'))
    profit_factor = _number(enhanced.get('profit_factor'))
    win_rate = _number(enhanced.get('win_rate'))
    lookahead_safe = bool(daily.get('lookahead_safe', True))

    status = 'ready'
    reason = 'backtest sample is sufficient for bounded learning gates'
    if not lookahead_safe:
        status = 'unsafe'
        reason = 'backtest artifact is not marked lookahead_safe'
    elif age_days is not None and age_days > MAX_BACKTEST_AGE_DAYS:
        status = 'stale'
        reason = 'backtest artifact is stale'
    elif sample_count < MIN_BACKTEST_SAMPLES:
        status = 'insufficient_sample'
        reason = 'backtest sample is below the minimum learning gate'
    elif expectancy_r < 0 or ic < 0:
        status = 'defensive'
        reason = 'recent scanner backtest has negative expectancy or IC'
    elif thresholds and not (thresholds.get('expectancy_r') and thresholds.get('information_coefficient')):
        status = 'watch'
        reason = 'sample is sufficient but quality thresholds are not fully met'
    elif daily.get('plan_a_success') is True:
        status = 'validated'
        reason = 'Plan A filter passed replay-safe success thresholds'

    rolling_summary = {
        'available': bool(rolling),
        'sample_count': rolling.get('sample_count') if isinstance(rolling, dict) else 0,
        'avg_expectancy_r': rolling.get('avg_expectancy_r') if isinstance(rolling, dict) else None,
        'avg_information_coefficient': rolling.get('avg_information_coefficient') if isinstance(rolling, dict) else None,
        'avg_win_rate': rolling.get('avg_win_rate') if isinstance(rolling, dict) else None,
        'lookahead_safe': bool((rolling or {}).get('lookahead_safe', True)) if isinstance(rolling, dict) else True,
    }
    return {
        'available': True,
        'status': status,
        'ready': status in {'validated', 'ready', 'watch', 'defensive'},
        'reason': reason,
        'generated_at': generated_at or None,
        'age_days': age_days,
        'mature_cutoff_date': daily.get('mature_cutoff_date'),
        'price_date_count': daily.get('price_date_count'),
        'run_count': daily.get('run_count'),
        'sample_count': sample_count,
        'expectancy_r': expectancy_r,
        'information_coefficient': ic,
        'profit_factor': profit_factor,
        'win_rate': win_rate,
        'thresholds_met': thresholds,
        'plan_a_success': bool(daily.get('plan_a_success')),
        'rolling': rolling_summary,
        'min_sample_count': MIN_BACKTEST_SAMPLES,
        'max_age_days': MAX_BACKTEST_AGE_DAYS,
        'lookahead_safe': lookahead_safe and bool(rolling_summary.get('lookahead_safe', True)),
    }


def _outcome_state(advisory: dict[str, Any]) -> dict[str, Any]:
    evaluated = int(_number(advisory.get('evaluated_count')))
    hit_rate = _number(advisory.get('hit_rate_recent')) if advisory.get('hit_rate_recent') not in (None, '') else None
    return {
        'available': bool(advisory.get('available') or evaluated),
        'ready': evaluated >= MIN_OUTCOME_EVALUATED,
        'evaluated_count': evaluated,
        'min_evaluated_count': MIN_OUTCOME_EVALUATED,
        'hit_rate_recent': hit_rate,
        'horizon_days': advisory.get('horizon_days'),
        'lookahead_safe': bool(advisory.get('lookahead_safe', True)),
        'source': advisory.get('source') or 'workflow_outcomes',
    }


def _score_control(backtest: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    if not outcome.get('ready'):
        return {
            'outcome_memory_enabled': False,
            'status': 'observe_only',
            'reason': 'not enough evaluated workflow outcomes',
            'positive_tag_delta_cap': 0.0,
            'negative_tag_delta_cap': 0.0,
            'positive_global_delta_cap': 0.0,
            'negative_global_delta_cap': 0.0,
        }
    if not backtest.get('available') or backtest.get('status') in {'missing', 'stale', 'unsafe', 'insufficient_sample'}:
        return {
            'outcome_memory_enabled': False,
            'status': 'observe_only',
            'reason': backtest.get('reason') or 'backtest gate is not ready',
            'positive_tag_delta_cap': 0.0,
            'negative_tag_delta_cap': 0.0,
            'positive_global_delta_cap': 0.0,
            'negative_global_delta_cap': 0.0,
        }
    if backtest.get('status') == 'defensive':
        return {
            'outcome_memory_enabled': True,
            'status': 'defensive_learning',
            'reason': 'apply only downside/risk memory until backtest recovers',
            'positive_tag_delta_cap': 0.0,
            'negative_tag_delta_cap': -2.0,
            'positive_global_delta_cap': 0.0,
            'negative_global_delta_cap': -3.0,
        }
    if backtest.get('status') == 'watch':
        return {
            'outcome_memory_enabled': True,
            'status': 'bounded_watch',
            'reason': 'allow small adaptive ranking nudges while thresholds are incomplete',
            'positive_tag_delta_cap': 0.75,
            'negative_tag_delta_cap': -1.5,
            'positive_global_delta_cap': 1.0,
            'negative_global_delta_cap': -2.0,
        }
    return {
        'outcome_memory_enabled': True,
        'status': 'bounded_adaptive',
        'reason': 'outcome and backtest gates allow bounded learning memory',
        'positive_tag_delta_cap': 2.0,
        'negative_tag_delta_cap': -2.0,
        'positive_global_delta_cap': 3.0,
        'negative_global_delta_cap': -3.0,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open('r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _age_days(value: str, now_dt: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round(max(0.0, (now_dt - parsed.astimezone(timezone.utc)).total_seconds() / 86400), 3)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return default
