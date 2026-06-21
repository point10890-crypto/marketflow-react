"""Replay-safe learning policy for MiroFish alpha detection.

The scanner should improve from verified outcomes, but only inside bounded
guards. This module turns outcome and backtest artifacts into a compact policy
that callers can use to decide whether adaptive ranking memory is safe to use.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.atomic_json import write_json_atomic


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / 'data' / 'admin_mirofish'
ALPHA_BACKTEST_DAILY_PATH = DATA_ROOT / 'alpha_backtest_daily.json'
ALPHA_BACKTEST_ROLLING_PATH = DATA_ROOT / 'alpha_backtest_rolling_7d.json'
TOP3_METRICS_PATH = DATA_ROOT / 'intelligence' / 'top3_metrics.json'
LEARNING_GUARD_PATH = DATA_ROOT / 'learning_guard.json'

MIN_OUTCOME_EVALUATED = 9
MIN_BACKTEST_SAMPLES_BOUNDED = 40
MIN_BACKTEST_SAMPLES = 100
MAX_BACKTEST_AGE_DAYS = 3
LEARNING_DISABLED_ENV = 'MIROFISH_LEARNING_DISABLED'
MIN_BACKTEST_SAMPLES_BOUNDED_ENV = 'MIROFISH_MIN_BACKTEST_SAMPLES_BOUNDED'
GUARD_MIN_TOP3_ITEMS_ENV = 'MIROFISH_LEARNING_GUARD_MIN_TOP3_ITEMS'
GUARD_CONSECUTIVE_WORSE_ENV = 'MIROFISH_LEARNING_GUARD_CONSECUTIVE_WORSE'


def build_learning_policy(
    performance_advisory: dict[str, Any] | None = None,
    *,
    daily_report: dict[str, Any] | None = None,
    rolling_report: dict[str, Any] | None = None,
    top3_report: dict[str, Any] | None = None,
    guard_state: dict[str, Any] | None = None,
    persist_guard: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the current scanner learning policy from replay-safe artifacts."""
    now_dt = now or datetime.now(timezone.utc)
    advisory = performance_advisory if isinstance(performance_advisory, dict) else {}
    daily = daily_report if isinstance(daily_report, dict) else _read_json(ALPHA_BACKTEST_DAILY_PATH)
    rolling = rolling_report if isinstance(rolling_report, dict) else _read_json(ALPHA_BACKTEST_ROLLING_PATH)
    top3 = top3_report if isinstance(top3_report, dict) else _read_json(TOP3_METRICS_PATH)

    backtest = _backtest_state(daily, rolling, now_dt)
    outcome = _outcome_state(advisory)
    base_control = _score_control(backtest, outcome)
    guard = _learning_guard_state(
        top3,
        now_dt,
        base_control=base_control,
        guard_state=guard_state,
        persist_guard=persist_guard,
    )
    control = _apply_policy_disables(base_control, guard)
    readiness = _learning_readiness(
        now_dt,
        backtest=backtest,
        outcome=outcome,
        control=control,
        guard=guard,
        top3=top3,
    )

    return {
        'schema_version': 'mirofish.learning_policy.v1',
        'generated_at': now_dt.isoformat(),
        'primary_objective': 'improve Top3 alpha candidate detection from replay-safe outcomes',
        'mode': 'bounded_adaptive_scoring',
        'lookahead_safe': bool(backtest.get('lookahead_safe', True) and outcome.get('lookahead_safe', True)),
        'production_weights_mutated': False,
        'outcome_memory': outcome,
        'backtest_gate': backtest,
        'top3_metrics': _top3_metrics_summary(top3),
        'learning_guard': guard,
        'score_control': control,
        'learning_readiness': readiness,
    }


def build_learning_readiness_snapshot(
    performance_advisory: dict[str, Any] | None = None,
    *,
    persist_guard: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return an operator-facing learning readiness snapshot."""
    advisory = performance_advisory
    if advisory is None:
        try:
            from app.services.mirofish import outcome_tracker

            advisory = outcome_tracker.get_advisory_feedback(horizon_days=5, limit_workflows=200)
        except Exception as exc:
            advisory = {
                'available': False,
                'evaluated_count': 0,
                'lookahead_safe': True,
                'source': 'workflow_outcomes',
                'error': f'{type(exc).__name__}: {exc}',
            }
    policy = build_learning_policy(
        advisory if isinstance(advisory, dict) else {},
        persist_guard=persist_guard,
        now=now,
    )
    readiness = dict(policy.get('learning_readiness') or {})
    readiness['links'] = {
        'feedback': '/api/admin/mirofish/autonomous/learning',
        'refresh': '/api/admin/mirofish/autonomous/learning/refresh',
        'alpha_endpoints': '/api/admin/mirofish/mcp/alpha-endpoints',
    }
    return readiness


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

    bounded_min = _bounded_sample_min()
    status = 'ready'
    reason = 'backtest sample is sufficient for bounded learning gates'
    if not lookahead_safe:
        status = 'unsafe'
        reason = 'backtest artifact is not marked lookahead_safe'
    elif age_days is not None and age_days > MAX_BACKTEST_AGE_DAYS:
        status = 'stale'
        reason = 'backtest artifact is stale'
    elif sample_count < bounded_min:
        status = 'insufficient_sample'
        reason = 'backtest sample is below the bounded learning gate'
    elif expectancy_r < 0 or ic < 0:
        status = 'defensive'
        reason = 'recent scanner backtest has negative expectancy or IC'
    elif sample_count < MIN_BACKTEST_SAMPLES:
        status = 'maturing'
        reason = 'backtest sample is enough for small capped learning, but below the full adaptive gate'
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
        'ready': status in {'validated', 'ready', 'maturing', 'watch', 'defensive'},
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
        'min_sample_count': bounded_min,
        'min_sample_count_bounded': bounded_min,
        'min_sample_count_full': MIN_BACKTEST_SAMPLES,
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
    if backtest.get('status') == 'maturing':
        return {
            'outcome_memory_enabled': True,
            'status': 'bounded_maturing',
            'reason': 'allow small adaptive ranking nudges while the backtest sample matures',
            'positive_tag_delta_cap': 0.75,
            'negative_tag_delta_cap': -1.5,
            'positive_global_delta_cap': 1.0,
            'negative_global_delta_cap': -2.0,
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


def _apply_policy_disables(control: dict[str, Any], guard: dict[str, Any]) -> dict[str, Any]:
    if _env_bool(LEARNING_DISABLED_ENV, False):
        return _disabled_control('manual learning kill switch is enabled', status='observe_only', disable_code='env_disabled')
    if guard.get('disabled'):
        return _disabled_control(guard.get('reason') or 'learning guard disabled adaptive scoring', status='observe_only', disable_code='guard_disabled')
    return control


def _disabled_control(reason: str, *, status: str, disable_code: str) -> dict[str, Any]:
    return {
        'outcome_memory_enabled': False,
        'status': status,
        'reason': reason,
        'disable_code': disable_code,
        'positive_tag_delta_cap': 0.0,
        'negative_tag_delta_cap': 0.0,
        'positive_global_delta_cap': 0.0,
        'negative_global_delta_cap': 0.0,
    }


def _learning_guard_state(
    top3: dict[str, Any],
    now_dt: datetime,
    *,
    base_control: dict[str, Any],
    guard_state: dict[str, Any] | None,
    persist_guard: bool,
) -> dict[str, Any]:
    current = _top3_metrics_summary(top3)
    record = guard_state if isinstance(guard_state, dict) else _read_json(LEARNING_GUARD_PATH)
    if record.get('disabled') is True:
        return {
            'schema_version': 'mirofish.learning_guard.v1',
            'status': 'disabled',
            'disabled': True,
            'reason': record.get('reason') or 'learning guard previously disabled adaptive scoring',
            'disabled_at': record.get('disabled_at'),
            'worse_streak': int(_number(record.get('worse_streak'))),
            'baseline': record.get('baseline') if isinstance(record.get('baseline'), dict) else {},
            'current': current,
            'min_top3_items': _guard_min_top3_items(),
        }
    if not base_control.get('outcome_memory_enabled'):
        return {
            'schema_version': 'mirofish.learning_guard.v1',
            'status': 'inactive',
            'disabled': False,
            'reason': 'learning is not active, guard is observing only',
            'current': current,
            'min_top3_items': _guard_min_top3_items(),
        }
    if not current.get('qualified'):
        return {
            'schema_version': 'mirofish.learning_guard.v1',
            'status': 'insufficient_top3_metrics',
            'disabled': False,
            'reason': 'top3 metrics are not yet qualified for automatic rollback',
            'current': current,
            'min_top3_items': _guard_min_top3_items(),
        }

    baseline = record.get('baseline') if isinstance(record.get('baseline'), dict) else {}
    if not baseline:
        state = {
            'schema_version': 'mirofish.learning_guard.v1',
            'disabled': False,
            'status': 'baseline_captured',
            'reason': 'baseline captured for learning rollback guard',
            'baseline': _guard_metric_block(current, captured_at=now_dt.isoformat()),
            'current': current,
            'worse_streak': 0,
            'last_evaluated_at': now_dt.isoformat(),
            'min_top3_items': _guard_min_top3_items(),
            'consecutive_worse_required': _guard_consecutive_worse(),
        }
        if persist_guard:
            _write_guard_state(state)
        return state

    deteriorated = _guard_deteriorated(current, baseline)
    worse_streak = (int(_number(record.get('worse_streak'))) + 1) if deteriorated else 0
    disabled = worse_streak >= _guard_consecutive_worse()
    reason = (
        'top3 return lift or precision deteriorated for consecutive evaluations'
        if disabled else
        ('top3 metric deterioration observed' if deteriorated else 'top3 metrics are within guard baseline')
    )
    state = {
        'schema_version': 'mirofish.learning_guard.v1',
        'disabled': disabled,
        'status': 'disabled' if disabled else ('watching_deterioration' if deteriorated else 'tracking'),
        'reason': reason,
        'baseline': baseline,
        'current': current,
        'worse_streak': worse_streak,
        'last_evaluated_at': now_dt.isoformat(),
        'disabled_at': now_dt.isoformat() if disabled else None,
        'min_top3_items': _guard_min_top3_items(),
        'consecutive_worse_required': _guard_consecutive_worse(),
    }
    if persist_guard:
        _write_guard_state(state)
    return state


def _learning_readiness(
    now_dt: datetime,
    *,
    backtest: dict[str, Any],
    outcome: dict[str, Any],
    control: dict[str, Any],
    guard: dict[str, Any],
    top3: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    if not outcome.get('ready'):
        blockers.append(f"outcomes {outcome.get('evaluated_count', 0)}/{outcome.get('min_evaluated_count', MIN_OUTCOME_EVALUATED)}")
    if not backtest.get('ready'):
        blockers.append(str(backtest.get('reason') or 'backtest gate is not ready'))
    if control.get('disable_code') == 'guard_disabled':
        blockers.append('learning guard disabled adaptive scoring')
    if control.get('disable_code') == 'env_disabled':
        blockers.append('manual learning kill switch enabled')
    return {
        'schema_version': 'mirofish.learning_readiness.v1',
        'service': 'mirofish-learning-readiness',
        'generated_at': now_dt.isoformat(),
        'ready': bool(control.get('outcome_memory_enabled')),
        'learning_active': bool(control.get('outcome_memory_enabled')),
        'status': control.get('status') or 'observe_only',
        'mode': 'bounded_outcome_memory',
        'primary_objective': 'improve Top3 alpha candidate detection from replay-safe outcomes',
        'lookahead_safe': bool(backtest.get('lookahead_safe', True) and outcome.get('lookahead_safe', True)),
        'production_weights_mutated': False,
        'blockers': blockers,
        'blocker_count': len(blockers),
        'outcome_memory': outcome,
        'backtest_gate': backtest,
        'score_control': control,
        'learning_guard': guard,
        'top3_metrics': _top3_metrics_summary(top3),
    }


def _top3_metrics_summary(top3: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(top3, dict) or not top3:
        return {
            'available': False,
            'qualified': False,
            'reason': 'top3_metrics artifact is missing',
        }
    pooled = top3.get('pooled') if isinstance(top3.get('pooled'), dict) else {}
    macro = top3.get('macro') if isinstance(top3.get('macro'), dict) else {}
    top3_items = int(_number(pooled.get('top3_item_count')))
    min_items = _guard_min_top3_items()
    qualified = bool(
        top3.get('lookahead_safe', True)
        and not top3.get('insufficient')
        and top3_items >= min_items
    )
    precision = _optional_number(macro.get('precision_at_3'))
    if precision is None:
        precision = _optional_number(pooled.get('top3_hit_rate'))
    return {
        'available': True,
        'qualified': qualified,
        'lookahead_safe': bool(top3.get('lookahead_safe', True)),
        'insufficient': bool(top3.get('insufficient')),
        'evaluated_runs': int(_number(top3.get('evaluated_runs'))),
        'qualified_runs': int(_number(top3.get('qualified_runs'))),
        'total_evaluated_items': int(_number(top3.get('total_evaluated_items'))),
        'top3_item_count': top3_items,
        'min_top3_items': min_items,
        'precision_at_3': precision,
        'top3_return_lift': _optional_number(pooled.get('top3_return_lift')),
        'top3_hit_lift': _optional_number(pooled.get('top3_hit_lift')),
        'top3_mean_return_pct': _optional_number(pooled.get('top3_mean_return_pct')),
        'baseline_hit_rate': _optional_number(pooled.get('baseline_hit_rate')),
    }


def _guard_metric_block(summary: dict[str, Any], *, captured_at: str | None = None) -> dict[str, Any]:
    block = {
        'precision_at_3': summary.get('precision_at_3'),
        'top3_return_lift': summary.get('top3_return_lift'),
        'top3_item_count': summary.get('top3_item_count'),
        'qualified_runs': summary.get('qualified_runs'),
    }
    if captured_at:
        block['captured_at'] = captured_at
    return block


def _guard_deteriorated(current: dict[str, Any], baseline: dict[str, Any]) -> bool:
    checks: list[bool] = []
    for key in ('top3_return_lift', 'precision_at_3'):
        now_value = _optional_number(current.get(key))
        base_value = _optional_number(baseline.get(key))
        if now_value is None or base_value is None:
            continue
        checks.append(now_value < base_value - 0.001)
    return any(checks)


def _write_guard_state(state: dict[str, Any]) -> None:
    try:
        write_json_atomic(str(LEARNING_GUARD_PATH), state, sort_keys=False)
    except Exception:
        pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open('r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _bounded_sample_min() -> int:
    return max(1, min(MIN_BACKTEST_SAMPLES, _env_int(MIN_BACKTEST_SAMPLES_BOUNDED_ENV, MIN_BACKTEST_SAMPLES_BOUNDED)))


def _guard_min_top3_items() -> int:
    return max(1, _env_int(GUARD_MIN_TOP3_ITEMS_ENV, 5))


def _guard_consecutive_worse() -> int:
    return max(1, _env_int(GUARD_CONSECUTIVE_WORSE_ENV, 2))


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


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


def _optional_number(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None
