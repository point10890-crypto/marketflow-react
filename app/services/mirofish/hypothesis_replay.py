"""Offline replay validation for MiroFish tag scoring hypotheses.

The validator replays a proposed tag delta over mature historical scanner
samples only. It does not call live data providers or LLMs; prices and forward
returns come through scripts/backtest_alpha_signals.py helpers so the same
lookahead-safe entry/exit rules are reused here.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
BACKTEST_SCRIPT = os.path.join(REPO_ROOT, 'scripts', 'backtest_alpha_signals.py')

MAX_ABS_DELTA = 2.0
PASS_MIN_SAMPLES = 60
PASS_MIN_TAGGED = 10
PASS_MIN_IC_GAIN = 0.01
PASS_MIN_TOP_RETURN_GAIN = 0.0
TOP_FRACTION = 0.25


@lru_cache(maxsize=1)
def _backtest_module():
    """Load the non-package backtest script without executing its CLI entrypoint."""
    spec = importlib.util.spec_from_file_location('backtest_alpha_signals', BACKTEST_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load backtest helper script: {BACKTEST_SCRIPT}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay_tag_delta(
    tag: str,
    delta: float,
    *,
    horizon_days: int = 5,
    limit_runs: int = 4000,
) -> dict[str, Any]:
    """Validate whether applying a bounded tag delta improves historical ranking.

    Acceptance requires enough total and tagged samples, positive IC gain, and a
    higher top-quartile forward-return average after replay.
    """
    clean_tag = str(tag or '').strip()
    try:
        requested_delta = float(delta)
    except (TypeError, ValueError):
        requested_delta = 0.0
        invalid_delta = True
    else:
        invalid_delta = False
    bounded_delta = _clamp(requested_delta, -MAX_ABS_DELTA, MAX_ABS_DELTA)
    horizon = _positive_int(horizon_days, 5)
    run_limit = _positive_int(limit_runs, 4000)

    base: dict[str, Any] = {
        'schema_version': 'mirofish.hypothesis_replay.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'status': 'rejected',
        'passed': False,
        'tag': clean_tag,
        'requested_delta': round(requested_delta, 4),
        'bounded_delta': round(bounded_delta, 4),
        'delta': round(bounded_delta, 4),
        'delta_was_clamped': bounded_delta != requested_delta,
        'max_abs_delta': MAX_ABS_DELTA,
        'horizon_days': horizon,
        'limit_runs': run_limit,
        'sample_count': 0,
        'tagged_count': 0,
        'min_sample_count': PASS_MIN_SAMPLES,
        'min_tagged_count': PASS_MIN_TAGGED,
        'top_fraction': TOP_FRACTION,
        'cohort': {
            'tagged_average_return_pct': None,
            'untagged_average_return_pct': None,
        },
        'baseline': _ranking_quality([], []),
        'adjusted': _ranking_quality([], []),
        'metric_delta': {
            'ic': 0.0,
            'top_bucket_avg_return_pct': 0.0,
            'average_return_pct': 0.0,
            'score_avg': 0.0,
        },
        'ic_gain': 0.0,
        'top_bucket_avg_return_gain_pct': 0.0,
    }
    if not clean_tag:
        return {**base, 'reason': 'invalid_tag'}
    if invalid_delta:
        return {**base, 'reason': 'invalid_delta'}
    if bounded_delta == 0.0:
        return {**base, 'reason': 'zero_delta'}

    samples = _collect_samples(horizon_days=horizon, limit_runs=run_limit)
    samples = [sample for sample in samples if isinstance(sample, dict)]
    tagged_count = sum(1 for sample in samples if clean_tag in _sample_tags(sample))
    base.update({
        'sample_count': len(samples),
        'tagged_count': tagged_count,
        'cohort': _cohort_metrics(samples, clean_tag),
    })

    baseline_scores = [_score(sample) for sample in samples]
    adjusted_scores = [
        score + (bounded_delta if clean_tag in _sample_tags(sample) else 0.0)
        for score, sample in zip(baseline_scores, samples)
    ]
    returns = [_num(sample.get('return_pct')) for sample in samples]
    baseline = _ranking_quality(baseline_scores, returns)
    adjusted = _ranking_quality(adjusted_scores, returns)
    metric_delta = _metric_delta(baseline, adjusted)
    scored = {
        **base,
        'baseline': baseline,
        'adjusted': adjusted,
        'metric_delta': metric_delta,
        'ic_gain': metric_delta['ic'],
        'top_bucket_avg_return_gain_pct': metric_delta['top_bucket_avg_return_pct'],
    }

    if len(samples) < PASS_MIN_SAMPLES:
        return {**scored, 'reason': 'insufficient_samples'}
    if tagged_count < PASS_MIN_TAGGED:
        return {**scored, 'reason': 'insufficient_tagged_samples'}

    ic_gain = metric_delta['ic']
    top_gain = metric_delta['top_bucket_avg_return_pct']
    passed = ic_gain >= PASS_MIN_IC_GAIN and top_gain > PASS_MIN_TOP_RETURN_GAIN
    if passed:
        return {
            **scored,
            'status': 'accepted',
            'passed': True,
            'reason': 'replay_improves_ic_and_top_bucket_return',
        }
    if ic_gain < PASS_MIN_IC_GAIN and top_gain <= PASS_MIN_TOP_RETURN_GAIN:
        reason = 'insufficient_ic_and_top_return_gain'
    elif ic_gain < PASS_MIN_IC_GAIN:
        reason = 'insufficient_ic_gain'
    else:
        reason = 'top_bucket_return_not_improved'
    return {**scored, 'reason': reason}


def _collect_samples(*, horizon_days: int, limit_runs: int) -> list[dict[str, Any]]:
    """Load mature scanner-run samples joined to forward returns and tags."""
    module = _backtest_module()
    price_dates = module._load_price_dates(module.DEFAULT_PRICES)
    mature_cutoff = module._mature_cutoff_date(price_dates, horizon_days)
    runs = module._load_runs(
        module.DEFAULT_SCANNER_ROOT,
        limit_runs=limit_runs,
        mature_cutoff_date=mature_cutoff,
    )

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    symbols: set[str] = set()
    for run in runs:
        if not isinstance(run, dict):
            continue
        for candidate in run.get('candidates') or []:
            if not isinstance(candidate, dict):
                continue
            if candidate.get('action') not in {'BUY_CANDIDATE', 'WATCH'}:
                continue
            symbol = module._symbol(candidate.get('symbol'))
            if not symbol:
                continue
            pairs.append((run, candidate))
            symbols.add(symbol)

    prices = module._load_prices(module.DEFAULT_PRICES, symbols=symbols)
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for run, candidate in pairs:
        sample = module._sample(candidate, prices, horizon_days)
        if not sample:
            continue
        signal_key = (
            str(sample.get('symbol') or ''),
            str(sample.get('entry_date') or ''),
            str(candidate.get('action') or ''),
        )
        if signal_key in seen:
            continue
        seen.add(signal_key)
        sample['run_id'] = run.get('id')
        sample['generated_at'] = run.get('generated_at') or run.get('created_at')
        sample['strategy_tags'] = _candidate_tags(candidate)
        samples.append(sample)
    return samples


def _ranking_quality(scores: list[float], returns: list[float]) -> dict[str, Any]:
    if not scores or len(scores) != len(returns):
        return {
            'sample_count': 0,
            'ic': None,
            'top_bucket_n': 0,
            'top_bucket_avg_return_pct': None,
            'average_return_pct': None,
            'score_avg': None,
        }
    module = _backtest_module()
    ic = module._correlation(scores, returns) if len(scores) >= 3 else None
    order = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)
    top_n = max(1, int(len(order) * TOP_FRACTION))
    top_returns = [returns[idx] for idx in order[:top_n]]
    return {
        'sample_count': len(scores),
        'ic': round(ic, 4) if ic is not None else None,
        'top_bucket_n': top_n,
        'top_bucket_avg_return_pct': round(sum(top_returns) / top_n, 4),
        'average_return_pct': round(sum(returns) / len(returns), 4),
        'score_avg': round(sum(scores) / len(scores), 4),
    }


def _metric_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    return {
        'ic': round(_num(after.get('ic')) - _num(before.get('ic')), 4),
        'top_bucket_avg_return_pct': round(
            _num(after.get('top_bucket_avg_return_pct'))
            - _num(before.get('top_bucket_avg_return_pct')),
            4,
        ),
        'average_return_pct': round(
            _num(after.get('average_return_pct')) - _num(before.get('average_return_pct')),
            4,
        ),
        'score_avg': round(_num(after.get('score_avg')) - _num(before.get('score_avg')), 4),
    }


def _cohort_metrics(samples: list[dict[str, Any]], tag: str) -> dict[str, Any]:
    tagged_returns = [
        _num(sample.get('return_pct'))
        for sample in samples
        if tag in _sample_tags(sample)
    ]
    other_returns = [
        _num(sample.get('return_pct'))
        for sample in samples
        if tag not in _sample_tags(sample)
    ]
    return {
        'tagged_average_return_pct': _average_or_none(tagged_returns),
        'untagged_average_return_pct': _average_or_none(other_returns),
    }


def _score(sample: dict[str, Any]) -> float:
    if sample.get('ranking_score') not in (None, ''):
        return _num(sample.get('ranking_score'))
    return _num(sample.get('alpha_score'))


def _sample_tags(sample: dict[str, Any]) -> set[str]:
    return set(_candidate_tags(sample))


def _candidate_tags(candidate: dict[str, Any]) -> list[str]:
    raw_tags = candidate.get('strategy_tags')
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    if not isinstance(raw_tags, (list, tuple, set)):
        return []
    return [str(tag).strip() for tag in raw_tags if str(tag or '').strip()]


def _average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, number)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _num(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0
