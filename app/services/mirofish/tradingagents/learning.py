"""Replay-safe decision memory for the KR TradingAgents pipeline.

This module deliberately has no market-data, LLM, or order side effects.  It
turns already persisted decisions and forward outcomes into deterministic
statistics and lessons.  Callers must supply outcomes produced after the
decision reference date; unsafe observations are retained for audit but never
used for scoring.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable

from app.utils.atomic_json import write_json_atomic


SCHEMA_VERSION = 1
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_WORKFLOWS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'workflows')
DEFAULT_MEMORY_PATH = os.path.join(
    REPO_ROOT, 'data', 'admin_mirofish', 'tradingagents', 'learning_memory.json'
)
POSITIVE_VERDICTS = frozenset({'STRONG_BUY', 'BUY', 'OVERWEIGHT'})
NEGATIVE_VERDICTS = frozenset({'SELL', 'UNDERWEIGHT', 'AVOID', 'REJECT'})


def build_decision_record(
    workflow_id: str,
    before_candidates: Iterable[dict[str, Any]],
    after_candidates: Iterable[dict[str, Any]],
    analyses: Iterable[dict[str, Any]],
    *,
    reference_date: str,
) -> dict[str, Any]:
    """Build an immutable intervention snapshot before outcomes are known."""
    before = [_candidate_snapshot(item, rank) for rank, item in enumerate(before_candidates, 1)]
    after = [_candidate_snapshot(item, rank) for rank, item in enumerate(after_candidates, 1)]
    before_symbols = {item['symbol'] for item in before if item['symbol']}
    after_symbols = {item['symbol'] for item in after if item['symbol']}
    analysis_by_symbol = {
        str(item.get('symbol') or '').strip(): _analysis_snapshot(item)
        for item in analyses if isinstance(item, dict) and item.get('symbol')
    }
    return {
        'schema_version': SCHEMA_VERSION,
        'workflow_id': str(workflow_id),
        'reference_date': str(reference_date),
        'before_candidates': before,
        'after_candidates': after,
        'intervention': {
            'promoted': sorted(after_symbols - before_symbols),
            'removed': sorted(before_symbols - after_symbols),
            'retained': sorted(before_symbols & after_symbols),
        },
        'analyses': analysis_by_symbol,
        'outcomes': {},
        'status': 'pending',
    }


def attach_forward_outcomes(
    record: dict[str, Any], outcomes: Iterable[dict[str, Any]], *, neutral_band_pct: float = 1.0
) -> dict[str, Any]:
    """Return a copy with outcome audits and replay-safe score cards attached."""
    result = json.loads(json.dumps(record, ensure_ascii=False))
    audits: dict[str, dict[str, Any]] = {}
    for raw in outcomes:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get('symbol') or '').strip()
        if not symbol:
            continue
        safe = _is_safe_outcome(raw, str(result.get('reference_date') or ''))
        evaluated = raw.get('status') in {'partial', 'evaluated', 'verified', 'completed'} and _number(raw.get('forward_return_pct')) is not None
        value = _number(raw.get('forward_return_pct'))
        audit: dict[str, Any] = {
            'status': raw.get('status') or 'pending',
            'horizon_days': raw.get('horizon_days'),
            'entry_date': raw.get('entry_date'),
            'exit_date': raw.get('exit_date'),
            'forward_return_pct': value,
            'benchmark_return_pct': _number(raw.get('benchmark_return_pct')),
            'lookahead_safe': safe,
            'eligible_for_learning': bool(safe and evaluated),
        }
        if audit['eligible_for_learning']:
            analysis = (result.get('analyses') or {}).get(symbol) or {}
            audit['agent_accuracy'] = {
                role: _stance_correct(report.get('stance'), value, neutral_band_pct)
                for role, report in (analysis.get('agents') or {}).items()
            }
            audit['verdict_correct'] = _verdict_correct(analysis.get('verdict'), value, neutral_band_pct)
        audits[symbol] = audit
    result['outcomes'] = audits
    eligible = sum(1 for item in audits.values() if item['eligible_for_learning'])
    result['status'] = 'evaluated' if eligible else 'pending'
    result['eligible_outcome_count'] = eligible
    return result


def aggregate_learning(records: Iterable[dict[str, Any]], *, min_samples: int = 5) -> dict[str, Any]:
    """Aggregate only replay-safe outcomes into bounded advisory statistics."""
    agents: dict[str, list[bool]] = {}
    verdicts: dict[str, list[bool]] = {}
    total_outcomes = unsafe = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        for symbol, outcome in (record.get('outcomes') or {}).items():
            if not isinstance(outcome, dict):
                continue
            total_outcomes += 1
            if not outcome.get('eligible_for_learning'):
                unsafe += int(not outcome.get('lookahead_safe', False))
                continue
            analysis = (record.get('analyses') or {}).get(symbol) or {}
            for role, correct in (outcome.get('agent_accuracy') or {}).items():
                if isinstance(correct, bool):
                    agents.setdefault(role, []).append(correct)
            verdict = str(analysis.get('verdict') or 'UNKNOWN').upper()
            correct = outcome.get('verdict_correct')
            if isinstance(correct, bool):
                verdicts.setdefault(verdict, []).append(correct)

    agent_stats = {role: _stats(values, min_samples) for role, values in sorted(agents.items())}
    verdict_stats = {name: _stats(values, min_samples) for name, values in sorted(verdicts.items())}
    samples = sum(item['sample_count'] for item in verdict_stats.values())
    return {
        'schema_version': SCHEMA_VERSION,
        'lookahead_safe_only': True,
        'total_outcome_count': total_outcomes,
        'excluded_unsafe_count': unsafe,
        'evaluated_sample_count': samples,
        'minimum_samples_for_adjustment': int(min_samples),
        'agent_accuracy': agent_stats,
        'verdict_accuracy': verdict_stats,
        'lessons': build_lessons(agent_stats, verdict_stats, min_samples=min_samples),
    }


def get_workflow_policy(path: str | None = None) -> dict[str, Any]:
    """Translate persisted replay-safe statistics into a bounded workflow policy."""
    memory = load_memory(path or DEFAULT_MEMORY_PATH, default={}) or {}
    min_samples = max(1, int(memory.get('minimum_samples_for_adjustment') or 20))
    sample_count = int(memory.get('evaluated_sample_count') or 0)
    verdict_weights: dict[str, float] = {}
    confidence_caps: dict[str, float] = {}
    for verdict, stats in (memory.get('verdict_accuracy') or {}).items():
        count = int(stats.get('sample_count') or 0)
        if count < min_samples:
            continue
        rate = float(stats.get('hit_rate_pct') or 0.0)
        verdict_weights[str(verdict).upper()] = round(max(0.8, min(1.2, 0.8 + rate / 250.0)), 3)
        if rate < 45.0:
            confidence_caps[str(verdict).upper()] = 70.0
    return {
        'enabled': True,
        'lookahead_safe': memory.get('lookahead_safe_only') is True,
        'sample_count': sample_count,
        'min_samples': min_samples,
        'verdict_weights': verdict_weights,
        'verdict_confidence_caps': confidence_caps,
        'confidence_cap': min(confidence_caps.values(), default=100.0),
        'agent_accuracy': memory.get('agent_accuracy') or {},
        'lessons': memory.get('lessons') or [],
    }


def refresh_memory_from_workflows(
    *, workflows_root: str | None = None, memory_path: str | None = None, min_samples: int = 20
) -> dict[str, Any]:
    """Aggregate persisted workflow records and atomically refresh global memory."""
    root = workflows_root or DEFAULT_WORKFLOWS_ROOT
    records: list[dict[str, Any]] = []
    if os.path.isdir(root):
        for entry in os.scandir(root):
            if not entry.is_dir():
                continue
            record = load_memory(os.path.join(entry.path, 'tradingagents_learning.json'))
            if isinstance(record, dict):
                records.append(record)
    memory = aggregate_learning(records, min_samples=min_samples)
    save_memory(memory_path or DEFAULT_MEMORY_PATH, memory)
    return memory


def persist_workflow_learning(
    workflow_id: str,
    before_candidates: Iterable[dict[str, Any]],
    after_candidates: Iterable[dict[str, Any]],
    analyses: Iterable[dict[str, Any]],
    outcomes: Iterable[dict[str, Any]],
    *,
    reference_date: str,
    workflows_root: str | None = None,
    memory_path: str | None = None,
    min_samples: int = 20,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist one audit record, then refresh the cross-workflow learning memory."""
    root = workflows_root or DEFAULT_WORKFLOWS_ROOT
    record = build_decision_record(
        workflow_id, before_candidates, after_candidates, analyses,
        reference_date=reference_date,
    )
    normalized = [_normalize_outcome(item) for item in outcomes if isinstance(item, dict)]
    record = attach_forward_outcomes(record, normalized)
    save_memory(os.path.join(root, workflow_id, 'tradingagents_learning.json'), record)
    memory = refresh_memory_from_workflows(
        workflows_root=root, memory_path=memory_path, min_samples=min_samples,
    )
    return record, memory


def build_lessons(agent_stats: dict[str, Any], verdict_stats: dict[str, Any], *, min_samples: int = 5) -> list[dict[str, Any]]:
    """Create deterministic advisories; never directly mutate production weights."""
    lessons: list[dict[str, Any]] = []
    for role, stats in sorted(agent_stats.items()):
        if stats.get('sample_count', 0) < min_samples:
            continue
        rate = float(stats.get('hit_rate_pct') or 0)
        if rate >= 65:
            lessons.append({'scope': 'agent', 'key': role, 'signal': 'reliable', 'suggested_weight_delta': 0.05})
        elif rate < 45:
            lessons.append({'scope': 'agent', 'key': role, 'signal': 'weak', 'suggested_weight_delta': -0.05})
    for verdict, stats in sorted(verdict_stats.items()):
        if stats.get('sample_count', 0) >= min_samples and float(stats.get('hit_rate_pct') or 0) < 45:
            lessons.append({'scope': 'verdict', 'key': verdict, 'signal': 'overconfident', 'suggested_confidence_cap_delta': -5})
    return lessons


def save_memory(path: str, payload: dict[str, Any]) -> None:
    """Atomically persist a decision record or aggregate memory."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    write_json_atomic(path, payload, sort_keys=False)


def load_memory(path: str, default: Any = None) -> Any:
    if not os.path.isfile(path):
        return default
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _candidate_snapshot(item: dict[str, Any], rank: int) -> dict[str, Any]:
    candidate = item.get('candidate') if isinstance(item.get('candidate'), dict) else item
    return {
        'rank': rank,
        'symbol': str(candidate.get('symbol') or '').strip(),
        'name': candidate.get('name') or candidate.get('display_name'),
        'market': candidate.get('market'),
        'score': _number(item.get('ta_adjusted_score', item.get('final_score', candidate.get('score', candidate.get('alpha_score'))))),
    }


def _normalize_outcome(raw: dict[str, Any]) -> dict[str, Any]:
    item = dict(raw)
    primary = item.get('primary_horizon')
    horizon = (item.get('horizons') or {}).get(str(primary), {}) if primary else {}
    item.setdefault('horizon_days', primary)
    item.setdefault('exit_date', horizon.get('exit_date'))
    item.setdefault('forward_return_pct', horizon.get('return_pct'))
    item['lookahead_safe'] = item.get('lookahead_safe') is True
    return item


def _analysis_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    reports = item.get('analyst_reports') or []
    agents = {
        str(report.get('role')): {'stance': str(report.get('stance') or 'neutral'), 'score': _number(report.get('score'))}
        for report in reports if isinstance(report, dict) and report.get('role')
    }
    debate = item.get('research_debate') or {}
    manager = debate.get('manager') or {}
    if manager:
        agents['research_manager'] = {'stance': manager.get('stance', 'neutral'), 'confidence': _number(manager.get('confidence'))}
    verdict = item.get('verdict') or {}
    return {
        'agents': agents,
        'verdict': str(verdict.get('verdict') or item.get('verdict_label') or 'HOLD').upper(),
        'confidence': _number(verdict.get('confidence')),
        'method': item.get('method'),
    }


def _is_safe_outcome(outcome: dict[str, Any], reference_date: str) -> bool:
    if outcome.get('lookahead_safe') is not True:
        return False
    entry = str(outcome.get('entry_date') or '')
    exit_date = str(outcome.get('exit_date') or '')
    return bool(reference_date and entry and exit_date and entry >= reference_date[:10] and exit_date >= entry)


def _stance_correct(stance: Any, value: float | None, neutral_band: float) -> bool | None:
    if value is None:
        return None
    normalized = str(stance or '').lower()
    if normalized in {'bull', 'bullish', 'buy'}:
        return value > neutral_band
    if normalized in {'bear', 'bearish', 'sell'}:
        return value < -neutral_band
    return abs(value) <= neutral_band


def _verdict_correct(verdict: Any, value: float | None, neutral_band: float) -> bool | None:
    name = str(verdict or '').upper()
    if name in POSITIVE_VERDICTS:
        return _stance_correct('bull', value, neutral_band)
    if name in NEGATIVE_VERDICTS:
        return _stance_correct('bear', value, neutral_band)
    return _stance_correct('neutral', value, neutral_band)


def _stats(values: list[bool], min_samples: int) -> dict[str, Any]:
    hits = sum(values)
    count = len(values)
    return {
        'sample_count': count,
        'hit_count': hits,
        'hit_rate_pct': round(hits * 100 / count, 2) if count else None,
        'adjustment_ready': count >= min_samples,
    }


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 6) if value is not None else None
    except (TypeError, ValueError):
        return None
