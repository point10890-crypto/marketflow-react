"""Alpha Brain Agent orchestration for replay-safe scanner learning.

This loop is deliberately conservative: it observes deterministic artifacts,
lets an LLM propose small whitelisted actions, then delegates every mutation to
``agent_actions`` for hard bounds, replay validation, and automatic rollback.
The goal is better Top 3 candidate quality, not MCP automation for its own sake.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.services.mirofish import agent_actions, edge_map
from app.utils.atomic_json import write_json_atomic


logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_DIR = os.path.join(REPO_ROOT, 'data', 'admin_mirofish')
STATE_PATH = os.path.join(DATA_DIR, 'agent_state.json')
JOURNAL_PATH = os.path.join(DATA_DIR, 'agent_journal.jsonl')
BACKTEST_DAILY_PATH = os.path.join(DATA_DIR, 'alpha_backtest_daily.json')

BACKTEST_STALE_HOURS = 30
MIN_EVALUATED_TARGET = 30
CIRCUIT_FAILURE_LIMIT = 3
CIRCUIT_OPEN_HOURS = 24
JOURNAL_TAIL_FOR_PROMPT = 5
MAX_LLM_DECISIONS = 4

LLM_SYSTEM_PROMPT = (
    'You are the Alpha Brain Agent for a Korean stock detection pipeline. '
    'Your only objective is to improve forward-return expectancy of Top 3 '
    'candidate detection. Use only supplied deterministic evidence. Never '
    'invent prices, tickers, filings, or outcomes. Respond with one JSON object.'
)

ALLOWED_LLM_ACTIONS = {
    'refresh_backtest',
    'refresh_outcomes',
    'refresh_learning_feedback',
    'test_hypothesis',
    'apply_scoring_delta',
    'revert_scoring_delta',
    'adjust_parameter',
    'revert_parameter',
}


def build_agent_observation(*, now_iso: str | None = None) -> dict[str, Any]:
    """Build the deterministic Sense payload for the agent cycle."""
    now_dt = _parse_dt(now_iso) or datetime.now(timezone.utc)
    backtest_raw = _read_backtest_daily()
    enhanced = backtest_raw.get('enhanced') or backtest_raw.get('plan_a_false_signal_filter') or {}
    generated_at = str(backtest_raw.get('generated_at') or '')
    age_hours = _age_hours(generated_at, now_dt)
    edge = edge_map.build_edge_map(write=True)
    advisory = _advisory_summary()
    intelligence = _intelligence_summary()
    return {
        'observed_at': now_dt.isoformat(),
        'objective': 'improve Top3 forward-return expectancy with lookahead-safe evidence',
        'edge_map': edge,
        'outcome': advisory,
        'backtest': {
            'generated_at': generated_at or None,
            'age_hours': age_hours,
            'stale': age_hours is None or age_hours > BACKTEST_STALE_HOURS,
            'sample_count': _int(enhanced.get('sample_count')),
            'expectancy_r': _num(enhanced.get('expectancy_r')),
            'information_coefficient': _num(
                enhanced.get('information_coefficient')
                if enhanced.get('information_coefficient') is not None
                else enhanced.get('IC')
            ),
            'profit_factor': _num(enhanced.get('profit_factor')),
            'win_rate': _num(enhanced.get('win_rate')),
            'lookahead_safe': bool(backtest_raw.get('lookahead_safe', True)),
        },
        'active_overrides': _active_overrides(),
        'active_scoring_overlay': agent_actions.scoring_overlay(),
        'recent_journal': read_journal_tail(JOURNAL_TAIL_FOR_PROMPT),
        'interaction_map': intelligence['interaction_map'],
        'regime_distribution': intelligence['regime_distribution'],
        'top3_metrics': intelligence.get('top3_metrics', {}),
    }


def get_learning_summary() -> dict[str, Any]:
    """Return the read-only learning fields used by status dashboards.

    Dashboard reads must not call :func:`build_agent_observation`: that full
    agent-cycle input rebuilds and persists the edge map, reads the journal,
    and performs other maintenance-oriented work.  The UI only needs the
    already persisted interaction/regime summaries.
    """
    return _intelligence_summary(allow_dataset_build=False)


def run_maintenance(observation: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """Run deterministic upkeep that keeps learning data fresh."""
    decisions: list[dict[str, Any]] = []
    backtest = observation.get('backtest') if isinstance(observation.get('backtest'), dict) else {}
    if backtest.get('stale'):
        decisions.append({'action': 'refresh_backtest', 'reason': 'deterministic: backtest stale'})
    outcome = observation.get('outcome') if isinstance(observation.get('outcome'), dict) else {}
    if _int(outcome.get('evaluated_count')) < MIN_EVALUATED_TARGET:
        decisions.append({'action': 'refresh_outcomes', 'reason': 'deterministic: low evaluated outcomes'})
    if not decisions:
        return []
    # Upkeep refreshes read-only/replay artifacts. It is allowed even when the
    # agent is in dry-run mode because it does not alter live scoring knobs.
    return agent_actions.execute_decisions(
        decisions,
        dry_run=False,
        backtest_metrics=backtest,
    )


def run_agent_cycle(
    cycle: str = 'evening',
    *,
    dry_run: bool | None = None,
    llm_call: Callable[[str], str | None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one Sense -> Think -> Act -> Learn cycle.

    Failures are journaled and returned as structured results so the scheduler
    can retry/alert without crashing the process.
    """
    now_dt = now or datetime.now(timezone.utc)
    state = _read_state()
    if _circuit_open(state, now_dt):
        entry = {
            'at': now_dt.isoformat(),
            'cycle': cycle,
            'status': 'skipped_circuit_open',
            'circuit_open_until': state.get('circuit_open_until'),
        }
        _append_journal(entry)
        return entry

    actual_dry_run = _env_bool('MIROFISH_AGENT_DRY_RUN', True) if dry_run is None else bool(dry_run)
    try:
        observation = build_agent_observation(now_iso=now_dt.isoformat())
        backtest = observation.get('backtest') if isinstance(observation.get('backtest'), dict) else {}
        rollbacks = agent_actions.enforce_rollbacks(
            backtest_metrics=backtest,
            backtest_generated_at=str(backtest.get('generated_at') or ''),
        )
        maintenance_results = run_maintenance(observation, dry_run=actual_dry_run)
        llm_outcome = _decide(observation, cycle, llm_call or _default_llm_call)
        llm_results = (
            agent_actions.execute_decisions(
                llm_outcome['decisions'],
                dry_run=actual_dry_run,
                backtest_metrics=backtest,
            )
            if llm_outcome['decisions']
            else []
        )
        outcome = observation.get('outcome') if isinstance(observation.get('outcome'), dict) else {}
        entry = {
            'at': now_dt.isoformat(),
            'cycle': cycle,
            'status': 'completed',
            'dry_run': actual_dry_run,
            'kpi': {
                'evaluated_count': outcome.get('evaluated_count'),
                'hit_rate_recent': outcome.get('hit_rate_recent'),
                'backtest_expectancy_r': backtest.get('expectancy_r'),
                'backtest_ic': backtest.get('information_coefficient'),
            },
            'rollbacks': rollbacks,
            'maintenance': maintenance_results,
            'llm': {
                'status': llm_outcome['status'],
                'note': llm_outcome.get('note'),
                'assessment': llm_outcome.get('assessment'),
                'confidence': llm_outcome.get('confidence'),
                'decision_count': len(llm_outcome['decisions']),
                'rejected_decisions': llm_outcome['rejected_count'],
            },
            'act': {'llm_results': llm_results},
            'active_overrides': _active_overrides(),
            'active_scoring_overlay': agent_actions.scoring_overlay(),
        }
        _append_journal(entry)
        state['consecutive_failures'] = 0
        state.pop('circuit_open_until', None)
        state['last_cycle_at'] = now_dt.isoformat()
        state['last_cycle'] = cycle
        _write_state(state)
        _maybe_send_brief(entry)
        return entry
    except Exception as exc:
        logger.error('[alpha_brain_agent] cycle failed: %s', exc, exc_info=True)
        failures = int(state.get('consecutive_failures') or 0) + 1
        state['consecutive_failures'] = failures
        if failures >= CIRCUIT_FAILURE_LIMIT:
            state['circuit_open_until'] = (now_dt + timedelta(hours=CIRCUIT_OPEN_HOURS)).isoformat()
        _write_state(state)
        entry = {
            'at': now_dt.isoformat(),
            'cycle': cycle,
            'status': 'failed',
            'error': f'{type(exc).__name__}: {exc}',
            'consecutive_failures': failures,
        }
        _append_journal(entry)
        return entry


def get_agent_status() -> dict[str, Any]:
    """Return admin/MCP-visible agent status."""
    state = _read_state()
    return {
        'service': 'mirofish-alpha-brain-agent',
        'enabled': _env_bool('MIROFISH_AGENT_ENABLED', True),
        'dry_run': _env_bool('MIROFISH_AGENT_DRY_RUN', True),
        'state': state,
        'circuit_open': _circuit_open(state, datetime.now(timezone.utc)),
        'active_overrides': _active_overrides(),
        'active_scoring_overlay': agent_actions.scoring_overlay(),
        'edge_map_generated_at': (edge_map.read_edge_map() or {}).get('generated_at'),
        'recent_journal': read_journal_tail(20),
    }


def read_journal_tail(limit: int = 20) -> list[dict[str, Any]]:
    try:
        with open(JOURNAL_PATH, 'r', encoding='utf-8') as handle:
            lines = handle.readlines()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines[-max(1, int(limit)):]:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _decide(
    observation: dict[str, Any],
    cycle: str,
    llm: Callable[[str], str | None],
) -> dict[str, Any]:
    prompt = _build_prompt(observation, cycle)
    for _attempt in range(2):
        raw = llm(prompt)
        if not raw:
            break
        payload = _parse_json(raw)
        if payload is None:
            continue
        clean, rejected = _validate_decisions(payload)
        return {
            'status': 'decided',
            'assessment': str(payload.get('assessment') or '')[:2000],
            'confidence': _num(payload.get('confidence')),
            'decisions': clean,
            'rejected_count': rejected,
        }
    return {
        'status': 'no_decision',
        'decisions': [],
        'rejected_count': 0,
        'note': 'llm unavailable or invalid json',
    }


def _build_prompt(observation: dict[str, Any], cycle: str) -> str:
    schema = {
        'assessment': 'current detection-quality assessment',
        'confidence': '0..1',
        'decisions': [{
            'action': f'one of {sorted(ALLOWED_LLM_ACTIONS)}',
            'reason': 'cite deterministic evidence and bucket stats',
            'tag': 'for tag actions',
            'delta': f'float, abs(delta) <= {agent_actions.TAG_DELTA_CAP}',
            'param': f'for parameter actions, one of {sorted(agent_actions.PARAM_BOUNDS)}',
            'to': 'float target for adjust_parameter',
        }],
    }
    return (
        f'CYCLE: {cycle}\n'
        'OBSERVATION (deterministic, lookahead-safe):\n'
        f'{json.dumps(observation, ensure_ascii=False, default=str)[:24000]}\n\n'
        f'Decide 0-{MAX_LLM_DECISIONS} actions. Empty decisions is valid when evidence is weak.\n'
        'Every mutation will be bounded and replay-validated before effect.\n'
        f'RESPONSE JSON SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}'
    )


def _validate_decisions(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    decisions = payload.get('decisions')
    if not isinstance(decisions, list):
        return [], 0
    clean: list[dict[str, Any]] = []
    rejected = 0
    for item in decisions[:MAX_LLM_DECISIONS]:
        if not isinstance(item, dict):
            rejected += 1
            continue
        action = str(item.get('action') or '').strip()
        if action not in ALLOWED_LLM_ACTIONS:
            rejected += 1
            continue
        clean.append({
            key: item.get(key)
            for key in ('action', 'reason', 'tag', 'delta', 'param', 'to')
            if item.get(key) is not None
        })
    if len(decisions) > MAX_LLM_DECISIONS:
        rejected += len(decisions) - MAX_LLM_DECISIONS
    return clean, rejected


def _default_llm_call(prompt: str) -> str | None:
    from app.services.mirofish import llm_client

    return llm_client.generate_text(
        prompt,
        system=LLM_SYSTEM_PROMPT,
        json_mode=True,
        max_tokens=2048,
        temperature=0.2,
    )


def _parse_json(raw: str) -> dict[str, Any] | None:
    text = str(raw or '').strip()
    if text.startswith('```'):
        text = text.strip('`').strip()
        if text.lower().startswith('json'):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _read_backtest_daily() -> dict[str, Any]:
    try:
        with open(BACKTEST_DAILY_PATH, 'r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _advisory_summary() -> dict[str, Any]:
    try:
        from app.services.mirofish import outcome_tracker

        advisory = outcome_tracker.get_advisory_feedback(horizon_days=5, limit_workflows=200)
    except Exception as exc:
        return {'evaluated_count': 0, 'error': f'{type(exc).__name__}: {exc}'}
    recommendations = advisory.get('recommendations') if isinstance(advisory, dict) else {}
    recommendations = recommendations if isinstance(recommendations, dict) else {}
    return {
        'evaluated_count': _int(advisory.get('evaluated_count')),
        'hit_rate_recent': advisory.get('hit_rate_recent'),
        'horizon_days': advisory.get('horizon_days'),
        'by_strategy_tag': advisory.get('by_strategy_tag') or {},
        'baseline_hit_rate': recommendations.get('baseline_hit_rate'),
        'lookahead_safe': bool(advisory.get('lookahead_safe', True)),
    }


def _intelligence_summary(*, allow_dataset_build: bool = True) -> dict[str, Any]:
    """Attach L2 interaction edges and regime distribution (read-only, isolated)."""
    interaction_map: dict[str, Any] = {}
    regime_distribution: dict[str, Any] = {}
    try:
        from app.services.mirofish.intelligence import interactions as _interactions

        imap = _interactions.read_interaction_map()
        if imap is None:
            imap = _interactions.build_interaction_map(write=True)
        if isinstance(imap, dict):
            interaction_map = {
                'evaluated_count': imap.get('evaluated_count', 0),
                'top_positive': (imap.get('top_positive') or [])[:10],
                'top_negative': (imap.get('top_negative') or [])[:10],
            }
    except Exception as exc:  # never break the observation
        logger.warning('[alpha_brain_agent] interaction map unavailable: %s', exc)
    try:
        from app.services.mirofish.intelligence import dataset as _dataset

        summary = (
            _dataset.dataset_summary()
            if allow_dataset_build
            else _dataset.dataset_summary(allow_build=False)
        )
        if isinstance(summary, dict):
            regime_distribution = summary.get('regime_distribution') or {}
    except Exception as exc:
        logger.warning('[alpha_brain_agent] regime distribution unavailable: %s', exc)
    top3_metrics: dict[str, Any] = {}
    try:
        from app.services.mirofish.intelligence import top3_metrics as _top3_metrics

        summary = _top3_metrics.top3_metrics_summary()
        if isinstance(summary, dict):
            top3_metrics = summary
    except Exception as exc:
        logger.warning('[alpha_brain_agent] top3 metrics unavailable: %s', exc)
    return {
        'interaction_map': interaction_map,
        'regime_distribution': regime_distribution,
        'top3_metrics': top3_metrics,
    }


def _active_overrides() -> dict[str, Any]:
    return {
        name: value
        for name in agent_actions.PARAM_BOUNDS
        for value in [agent_actions.param_override(name)]
        if value is not None
    }


def _read_state() -> dict[str, Any]:
    try:
        with open(STATE_PATH, 'r', encoding='utf-8-sig') as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    state['schema_version'] = 'mirofish.agent_state.v1'
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(STATE_PATH, state, sort_keys=False)


def _append_journal(entry: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    with open(JOURNAL_PATH, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def _maybe_send_brief(entry: dict[str, Any]) -> None:
    if not _env_bool('MIROFISH_AGENT_BRIEF_ENABLED', True):
        return
    try:
        from app.utils.scheduler import _send_telegram_long

        kpi = entry.get('kpi') or {}
        llm = entry.get('llm') or {}
        lines = [
            f"[AlphaBrain] {entry.get('cycle')} {entry.get('status')}"
            + (' (dry-run)' if entry.get('dry_run') else ''),
            (
                f"eval={kpi.get('evaluated_count')} hit={kpi.get('hit_rate_recent')} "
                f"expR={kpi.get('backtest_expectancy_r')} IC={kpi.get('backtest_ic')}"
            ),
            f"decisions={llm.get('decision_count', 0)} rollbacks={len(entry.get('rollbacks') or [])}",
        ]
        if llm.get('assessment'):
            lines.append(str(llm['assessment'])[:300])
        _send_telegram_long('\n'.join(lines), channel=False)
    except Exception as exc:
        logger.warning('[alpha_brain_agent] brief send failed: %s', exc)


def _circuit_open(state: dict[str, Any], now_dt: datetime) -> bool:
    until = _parse_dt(state.get('circuit_open_until'))
    return bool(until and now_dt < until)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_hours(value: str, now_dt: datetime) -> float | None:
    parsed = _parse_dt(value)
    if not parsed:
        return None
    return round(max(0.0, (now_dt - parsed.astimezone(timezone.utc)).total_seconds() / 3600), 2)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _num(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    return int(_num(value))
