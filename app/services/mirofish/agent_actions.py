"""Bounded action executor for the MiroFish Alpha Brain Agent.

LLM decisions are proposals only. This module validates each proposal against a
small action whitelist, hard numeric bounds, known alpha tags, and replay gates
before mutating local agent stores. Rollback is deterministic and compares later
backtests against the baseline captured at apply time.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Mapping

try:
    from app.services.mirofish import edge_map
except ImportError:  # pragma: no cover - only used while adjacent slice is absent
    edge_map = None  # type: ignore[assignment]

try:
    from app.services.mirofish import hypothesis_replay
except ImportError:  # pragma: no cover - keeps this slice importable on its own

    class _MissingHypothesisReplay:
        @staticmethod
        def replay_tag_delta(tag: str, delta: float, **_kwargs: Any) -> dict[str, Any]:
            return {
                'passed': False,
                'reason': 'hypothesis_replay_unavailable',
                'tag': tag,
                'delta': delta,
            }

    hypothesis_replay = _MissingHypothesisReplay()  # type: ignore[assignment]

from app.utils.atomic_json import write_json_atomic


logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_DIR = os.path.join(REPO_ROOT, 'data', 'admin_mirofish')
OVERRIDES_PATH = os.path.join(DATA_DIR, 'agent_overrides.json')
OVERLAY_PATH = os.path.join(DATA_DIR, 'agent_scoring_overlay.json')
BACKTEST_SCRIPT = os.path.join(REPO_ROOT, 'scripts', 'backtest_alpha_signals.py')

PARAM_BOUNDS: dict[str, dict[str, float]] = {
    'min_alpha': {'min': 60.0, 'max': 85.0, 'max_step': 3.0, 'default': 70.0},
    'max_risk': {'min': 35.0, 'max': 55.0, 'max_step': 3.0, 'default': 45.0},
    'min_top_score': {'min': 40.0, 'max': 70.0, 'max_step': 5.0, 'default': 50.0},
}

TAG_DELTA_CAP = 2.0
ROLLBACK_WORSE_LIMIT = 2
ROLLBACK_TOLERANCE = 0.02

STORE_MUTATING_ACTIONS = {
    'adjust_parameter',
    'apply_scoring_delta',
    'revert_parameter',
    'revert_scoring_delta',
}
ALLOWED_ACTIONS = STORE_MUTATING_ACTIONS | {
    'refresh_backtest',
    'refresh_outcomes',
    'refresh_learning_feedback',
    'test_hypothesis',
}

DEFAULT_KNOWN_TAGS = frozenset({
    'artifact_candidate',
    'credit_pressure',
    'dart_hard_risk',
    'deepseek_v4_confirmed',
    'deepseek_v4_risk_flag',
    'dual_flow_buy',
    'foreign_buy',
    'institutional_buy',
    'jongga_setup',
    'kalman_pass',
    'kind_blacklist',
    'kis_live_dual_flow',
    'leading_screener',
    'momentum',
    'news_theme_social_supporting_only',
    'outcome_tag_memory_adjusted',
    'risk_penalty',
    'support_signal_without_core_confirmation',
    'thin_liquidity_spike',
    'tradingview_confirmed',
    'tradingview_warning',
    'trend_quality',
    'upper_wick_risk',
    'vcp_entry',
    'volume_accumulation',
    'volume_surge',
})
TAG_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')


def read_overrides() -> dict[str, Any]:
    """Return the raw parameter override store, or an empty dict."""
    return _read(OVERRIDES_PATH)


def active_parameter_overrides() -> dict[str, dict[str, Any]]:
    """Return valid active parameter override entries keyed by parameter name."""
    entries = read_overrides().get('params')
    if not isinstance(entries, dict):
        return {}
    active: dict[str, dict[str, Any]] = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict) or name not in PARAM_BOUNDS:
            continue
        value = _finite_float(entry.get('value'))
        bounds = PARAM_BOUNDS[name]
        if value is None or not (bounds['min'] <= value <= bounds['max']):
            continue
        cleaned = dict(entry)
        cleaned['value'] = value
        active[str(name)] = cleaned
    return active


def read_effective_overrides(defaults: Mapping[str, float] | None = None) -> dict[str, float]:
    """Return effective bounded parameter values.

    Without defaults, this returns only active agent overrides. With defaults,
    it overlays valid agent values on top of the supplied defaults.
    """
    active = {name: float(entry['value']) for name, entry in active_parameter_overrides().items()}
    if defaults is None:
        return active
    out = {str(name): float(value) for name, value in defaults.items()}
    for name, value in active.items():
        if name in out:
            out[name] = value
    return out


def param_override(name: str) -> float | None:
    """Return one valid active override, if present."""
    entry = active_parameter_overrides().get(str(name or '').strip())
    return float(entry['value']) if entry else None


def param_value(name: str, default: float) -> float:
    """Return agent override value or the caller's default."""
    value = param_override(name)
    return value if value is not None else float(default)


def read_scoring_overlay() -> dict[str, Any]:
    """Return the raw scoring overlay store, or an empty dict."""
    return _read(OVERLAY_PATH)


def scoring_overlay() -> dict[str, dict[str, Any]]:
    """Return valid active tag-scoring entries keyed by tag."""
    entries = read_scoring_overlay().get('tags')
    if not isinstance(entries, dict):
        return {}
    active: dict[str, dict[str, Any]] = {}
    for tag, entry in entries.items():
        tag_text = str(tag or '').strip()
        if not _valid_tag_name(tag_text) or not _is_known_tag(tag_text):
            continue
        if not isinstance(entry, dict):
            continue
        delta = _finite_float(entry.get('delta'))
        if delta is None or not (0 < abs(delta) <= TAG_DELTA_CAP):
            continue
        cleaned = dict(entry)
        cleaned['delta'] = delta
        active[tag_text] = cleaned
    return active


def scoring_overlay_deltas() -> dict[str, float]:
    """Return the effective tag -> bounded score delta mapping."""
    return {tag: float(entry['delta']) for tag, entry in scoring_overlay().items()}


def read_effective_scoring_overlay() -> dict[str, float]:
    """Alias for consumers that want only effective bounded deltas."""
    return scoring_overlay_deltas()


def execute_decisions(
    decisions: list[dict[str, Any]] | None,
    *,
    dry_run: bool,
    backtest_metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate and execute whitelisted Alpha Brain decisions."""
    results: list[dict[str, Any]] = []
    for decision in decisions or []:
        if not isinstance(decision, dict):
            results.append(_result({}, 'rejected', 'invalid_decision'))
            continue
        action = str(decision.get('action') or '').strip()
        if action not in ALLOWED_ACTIONS:
            results.append(_result(decision, 'rejected', 'unknown_action'))
            continue
        if dry_run and action in STORE_MUTATING_ACTIONS:
            results.append(_result(decision, 'proposed_only', 'dry_run'))
            continue
        try:
            results.append(_HANDLERS[action](decision, backtest_metrics or {}))
        except Exception as exc:  # keep one bad action from killing the cycle
            logger.warning('[agent_actions] %s failed: %s', action, exc, exc_info=True)
            results.append(_result(decision, 'error', f'{type(exc).__name__}: {exc}'))
    return results


def apply_parameter_override(
    name: str,
    value: float,
    *,
    reason: str = '',
    backtest_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one bounded parameter override through the same executor path."""
    return _do_adjust_parameter(
        {'action': 'adjust_parameter', 'param': name, 'to': value, 'reason': reason},
        backtest_metrics or {},
    )


def revert_parameter_override(name: str, *, reason: str = '') -> dict[str, Any]:
    """Remove one active parameter override."""
    return _do_revert_parameter(
        {'action': 'revert_parameter', 'param': name, 'reason': reason},
        {},
    )


def apply_tag_scoring_delta(
    tag: str,
    delta: float,
    *,
    reason: str = '',
    backtest_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one replay-gated tag scoring delta."""
    return _do_apply_scoring_delta(
        {'action': 'apply_scoring_delta', 'tag': tag, 'delta': delta, 'reason': reason},
        backtest_metrics or {},
    )


def revert_tag_scoring_delta(tag: str, *, reason: str = '') -> dict[str, Any]:
    """Remove one active tag scoring delta."""
    return _do_revert_scoring_delta(
        {'action': 'revert_scoring_delta', 'tag': tag, 'reason': reason},
        {},
    )


def enforce_rollbacks(
    *,
    backtest_metrics: dict[str, Any],
    backtest_generated_at: str,
) -> list[dict[str, str]]:
    """Revert entries after two distinct worse backtests.

    Each override stores its own baseline. A backtest is worse when expectancy_r
    or information_coefficient falls below that baseline by ROLLBACK_TOLERANCE.
    The same generated_at value is counted at most once per entry.
    """
    reverted: list[dict[str, str]] = []
    current = _baseline(backtest_metrics)
    generated_at = str(backtest_generated_at or '').strip() or _now()

    for path, schema, kind, container_key in (
        (OVERLAY_PATH, 'mirofish.agent_scoring_overlay.v1', 'scoring_delta', 'tags'),
        (OVERRIDES_PATH, 'mirofish.agent_overrides.v1', 'parameter', 'params'),
    ):
        store = _read(path)
        entries = store.get(container_key)
        if not isinstance(entries, dict):
            continue
        changed = False
        for key in list(entries.keys()):
            entry = entries.get(key)
            if not isinstance(entry, dict):
                continue
            if entry.get('last_eval_backtest_at') == generated_at:
                continue
            baseline = entry.get('baseline') if isinstance(entry.get('baseline'), dict) else {}
            worse = _is_worse(current, baseline)
            entry['last_eval_backtest_at'] = generated_at
            entry['last_eval_metrics'] = current
            entry['last_eval_status'] = 'worse' if worse else 'recovered'
            entry['worse_count'] = int(entry.get('worse_count') or 0) + 1 if worse else 0
            changed = True
            if entry['worse_count'] >= ROLLBACK_WORSE_LIMIT:
                del entries[key]
                reverted.append({'kind': kind, 'key': str(key)})
                logger.warning('[agent_actions] auto-rollback %s %s', kind, key)
        if changed:
            _write(path, store, schema)
    return reverted


def _do_adjust_parameter(decision: dict[str, Any], backtest: dict[str, Any]) -> dict[str, Any]:
    name = str(decision.get('param') or '').strip()
    bounds = PARAM_BOUNDS.get(name)
    if not bounds:
        return _result(decision, 'rejected', 'unknown_param')
    target = _finite_float(decision.get('to'))
    if target is None:
        return _result(decision, 'rejected', 'invalid_target_value')
    if not (bounds['min'] <= target <= bounds['max']):
        return _result(decision, 'rejected', 'out_of_bounds')
    current = param_value(name, bounds['default'])
    if abs(target - current) > bounds['max_step']:
        return _result(decision, 'rejected', 'step_too_large')

    store = _read(OVERRIDES_PATH)
    params = store.get('params')
    if not isinstance(params, dict):
        params = {}
        store['params'] = params
    params[name] = {
        'param': name,
        'value': target,
        'previous_value': current,
        'applied_at': _now(),
        'reason': _clean_reason(decision.get('reason')),
        'baseline': _baseline(backtest),
        'rollback': _rollback_metadata(),
        'worse_count': 0,
        'last_eval_backtest_at': None,
    }
    _write(OVERRIDES_PATH, store, 'mirofish.agent_overrides.v1')
    return _result(decision, 'applied', f'{name}: {current:g} -> {target:g}')


def _do_revert_parameter(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    name = str(decision.get('param') or '').strip()
    if name not in PARAM_BOUNDS:
        return _result(decision, 'rejected', 'unknown_param')
    store = _read(OVERRIDES_PATH)
    params = store.get('params')
    if not isinstance(params, dict) or name not in params:
        return _result(decision, 'rejected', 'no_active_override')
    del params[name]
    _write(OVERRIDES_PATH, store, 'mirofish.agent_overrides.v1')
    return _result(decision, 'applied', f'{name} override removed')


def _do_apply_scoring_delta(decision: dict[str, Any], backtest: dict[str, Any]) -> dict[str, Any]:
    tag = str(decision.get('tag') or '').strip()
    tag_error = _tag_error(tag)
    if tag_error:
        return _result(decision, 'rejected', tag_error)
    delta = _finite_float(decision.get('delta'))
    if delta is None:
        return _result(decision, 'rejected', 'invalid_delta')
    if not delta or abs(delta) > TAG_DELTA_CAP:
        return _result(decision, 'rejected', 'delta_over_cap')

    replay = hypothesis_replay.replay_tag_delta(tag, delta)
    if not isinstance(replay, dict) or not replay.get('passed'):
        reason = replay.get('reason') if isinstance(replay, dict) else 'invalid_replay_result'
        return _result(decision, 'rejected', f'replay_failed: {reason}')

    store = _read(OVERLAY_PATH)
    tags = store.get('tags')
    if not isinstance(tags, dict):
        tags = {}
        store['tags'] = tags
    tags[tag] = {
        'tag': tag,
        'delta': delta,
        'applied_at': _now(),
        'reason': _clean_reason(decision.get('reason')),
        'replay': {
            key: replay.get(key)
            for key in ('passed', 'reason', 'ic_gain', 'sample_count', 'tagged_count')
            if key in replay
        },
        'baseline': _baseline(backtest),
        'rollback': _rollback_metadata(),
        'worse_count': 0,
        'last_eval_backtest_at': None,
    }
    _write(OVERLAY_PATH, store, 'mirofish.agent_scoring_overlay.v1')
    return _result(decision, 'applied', f'tag {tag} delta {delta:+.2f}')


def _do_revert_scoring_delta(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    tag = str(decision.get('tag') or '').strip()
    if not _valid_tag_name(tag):
        return _result(decision, 'rejected', 'invalid_tag')
    store = _read(OVERLAY_PATH)
    tags = store.get('tags')
    if not isinstance(tags, dict) or tag not in tags:
        return _result(decision, 'rejected', 'no_active_delta')
    del tags[tag]
    _write(OVERLAY_PATH, store, 'mirofish.agent_scoring_overlay.v1')
    return _result(decision, 'applied', f'tag {tag} delta removed')


def _do_test_hypothesis(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    tag = str(decision.get('tag') or '').strip()
    tag_error = _tag_error(tag)
    if tag_error:
        return _result(decision, 'rejected', tag_error)
    delta = _finite_float(decision.get('delta'))
    if delta is None:
        return _result(decision, 'rejected', 'invalid_delta')
    if not delta or abs(delta) > TAG_DELTA_CAP:
        return _result(decision, 'rejected', 'delta_over_cap')
    replay = hypothesis_replay.replay_tag_delta(tag, delta)
    status = 'evaluated' if isinstance(replay, dict) else 'error'
    reason = 'replay_passed' if isinstance(replay, dict) and replay.get('passed') else 'replay_failed'
    result = _result(decision, status, reason)
    result['replay'] = replay if isinstance(replay, dict) else {'error': 'invalid_replay_result'}
    return result


def _do_refresh_backtest(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    module = _backtest_module()
    report = module.evaluate_runs(horizon_days=5)
    module.write_report(report)
    module.write_rolling_report(current_report=report)
    enhanced = report.get('enhanced') or report.get('plan_a_false_signal_filter') or {}
    return _result(
        decision,
        'applied',
        f"backtest refreshed: samples={enhanced.get('sample_count')}",
    )


def _do_refresh_outcomes(decision: dict[str, Any], _backtest: dict[str, Any]) -> dict[str, Any]:
    from app.services.mirofish import autonomous_mcp

    if hasattr(autonomous_mcp, 'refresh_learning_feedback_trusted'):
        feedback = autonomous_mcp.refresh_learning_feedback_trusted(limit=50)
    else:
        feedback = autonomous_mcp.refresh_learning_feedback({'limit': 50, 'commit': False})
    return _result(
        decision,
        'applied',
        f"outcomes refreshed: evaluated={feedback.get('evaluated_count')}",
    )


_HANDLERS = {
    'adjust_parameter': _do_adjust_parameter,
    'revert_parameter': _do_revert_parameter,
    'apply_scoring_delta': _do_apply_scoring_delta,
    'revert_scoring_delta': _do_revert_scoring_delta,
    'test_hypothesis': _do_test_hypothesis,
    'refresh_backtest': _do_refresh_backtest,
    'refresh_outcomes': _do_refresh_outcomes,
    'refresh_learning_feedback': _do_refresh_outcomes,
}


def _tag_error(tag: str) -> str | None:
    if not tag:
        return 'missing_tag'
    if not _valid_tag_name(tag):
        return 'invalid_tag'
    if not _is_known_tag(tag):
        return 'unknown_tag'
    return None


def _valid_tag_name(tag: str) -> bool:
    return bool(TAG_NAME_RE.fullmatch(str(tag or '').strip()))


def _is_known_tag(tag: str) -> bool:
    tag = str(tag or '').strip()
    if tag in DEFAULT_KNOWN_TAGS:
        return True
    return tag in _edge_map_tags()


def _edge_map_tags() -> set[str]:
    if edge_map is None:
        return set()
    try:
        payload = edge_map.read_edge_map()
    except Exception:
        return set()
    if not isinstance(payload, dict):
        return set()
    tags = payload.get('by_tag')
    if not isinstance(tags, dict):
        return set()
    return {str(tag).strip() for tag in tags if _valid_tag_name(str(tag).strip())}


def _baseline(backtest: dict[str, Any] | None) -> dict[str, float]:
    backtest = backtest if isinstance(backtest, dict) else {}
    return {
        'expectancy_r': _metric(backtest.get('expectancy_r')),
        'information_coefficient': _metric(backtest.get('information_coefficient')),
    }


def _is_worse(current: dict[str, Any], baseline: dict[str, Any]) -> bool:
    return (
        _metric(current.get('expectancy_r')) < _metric(baseline.get('expectancy_r')) - ROLLBACK_TOLERANCE
        or _metric(current.get('information_coefficient'))
        < _metric(baseline.get('information_coefficient')) - ROLLBACK_TOLERANCE
    )


def _rollback_metadata() -> dict[str, Any]:
    return {
        'worse_limit': ROLLBACK_WORSE_LIMIT,
        'tolerance': ROLLBACK_TOLERANCE,
        'metrics': ['expectancy_r', 'information_coefficient'],
    }


def _result(decision: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        'action': str(decision.get('action') or ''),
        'status': status,
        'reason': reason,
        'decision': {k: v for k, v in decision.items() if k != 'action'},
        'at': _now(),
    }


def _read(path: str) -> dict[str, Any]:
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: str, store: dict[str, Any], schema: str) -> None:
    store['schema_version'] = schema
    store['updated_at'] = _now()
    write_json_atomic(path, store, sort_keys=False)


def _backtest_module() -> Any:
    spec = importlib.util.spec_from_file_location('backtest_alpha_signals', BACKTEST_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError('backtest_script_unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_reason(value: Any) -> str:
    return str(value or '').strip()[:500]


def _finite_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        out = float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _metric(value: Any) -> float:
    parsed = _finite_float(value)
    return parsed if parsed is not None else 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
