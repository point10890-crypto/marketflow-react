"""Deep-analysis engine — orchestrates the TradingAgents pipeline + persistence.

Pipeline architecture ported from TauricResearch/TradingAgents (Apache-2.0):
    data_hub → analysts (4) → research_debate (bull/bear + manager)
             → trader_risk (trader → risk team → PM) → flat verdict.

One entry point, `run_deep_analysis(target)`, gathers the KR-native data bundle,
runs the four-analyst layer, the bull/bear research debate, and the trader/risk/
PM tail, then flat-merges the verdict and persists the run atomically. Every run
is retained under RUNS_ROOT plus a rolling `latest.json` pointer.

Run schema (LOCKED — Task 6/7 consume this):
    {
        'id', 'target', 'symbol', 'market', 'created_at', 'completed_at', 'elapsed_ms',
        'bundle_meta': {'errors', 'has_price', 'has_technical', 'has_rs',
                        'has_fundamentals', 'corpus_chars'},
        'analyst_reports': list, 'research_debate': dict, 'trader_risk': dict,
        'verdict': {'verdict','confidence','strong_buy','reasoning',
                    'bull_case','bear_case','risk_summary'},
        'method': 'llm'|'rule'|'mixed',
    }

Env (read at call time, never at import):
    MIROFISH_TRADINGAGENTS_DISABLED  kill switch (default false) — is_disabled()
    MIROFISH_TA_DEBATE_ROUNDS        debate rounds (default 2, clamp 1..4)
    MIROFISH_TA_MAX_CANDIDATES       (default 5)   exposed via get_status()['config']
    MIROFISH_TA_BOOST_STRONG         (default 8.0) exposed via get_status()['config']
    MIROFISH_TA_BOOST_BUY            (default 5.0) exposed via get_status()['config']
    MIROFISH_TA_PENALTY_HOLD         (default 3.0) exposed via get_status()['config']
    MIROFISH_TA_SELL_EXCLUDE_MIN_CONFIDENCE (default 65.0) hard-exclusion gate
    MIROFISH_TA_PENALTY_UNCERTAIN_SELL       (default 5.0) soft SELL penalty

Note: `run_deep_analysis` does NOT check the kill switch — the on-demand admin
endpoint may run regardless. The Task 6 workflow layer gates on `is_disabled()`.
"""

from __future__ import annotations

import glob
import hashlib
import itertools
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from app.services.mirofish.tradingagents import analysts
from app.services.mirofish.tradingagents import data_hub
from app.services.mirofish.tradingagents import research_debate
from app.services.mirofish.tradingagents import trader_risk
from app.services.mirofish.tradingagents import regime as regime_mod
from app.services.mirofish.tradingagents import learning
from app.services.mirofish import llm_client
from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
RUNS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'tradingagents_runs')

LATEST_NAME = 'latest.json'
_RUN_ID_RE = re.compile(r'^ta_[0-9_]+_[0-9a-f]{6}$')

_MIN_ROUNDS = 1
_MAX_ROUNDS = 4

# Monotonic per-process sequence — guarantees distinct run ids for same-second,
# same-target runs even when the wall clock is coarse (Windows datetime.now()
# ticks ~15ms, so %f microseconds alone can repeat back-to-back).
_run_seq = itertools.count()


# ── Public API ──────────────────────────────────────────────────────

def run_deep_analysis(target: str, *, symbol: str | None = None,
                      rounds: int | None = None, use_llm: bool = True,
                      brain: dict[str, Any] | None = None,
                      context_line: str = '') -> dict[str, Any]:
    """Run the full deep-verification pipeline for one target and persist it.

    Does NOT check the kill switch (the admin endpoint may run on demand); the
    workflow layer is responsible for gating. `rounds` overrides the env default
    when provided; otherwise MIROFISH_TA_DEBATE_ROUNDS (clamped 1..4) is used.
    `brain`, when provided, is a Brain 13D snapshot used to derive the regime
    context (see `regime.regime_context`) injected into the debate + trader/risk
    prompts and surfaced on the flat verdict.
    """
    started = datetime.now(timezone.utc)

    bundle = data_hub.gather_bundle(target, brain=brain) or {}
    if symbol and not bundle.get('symbol'):
        bundle['symbol'] = symbol

    rc = regime_mod.regime_context(brain)

    with llm_client.collect_generation_metadata() as llm_calls:
        reports = analysts.run_analysts(bundle, use_llm=use_llm)

        effective_rounds = int(rounds) if rounds is not None else _env_rounds()
        effective_rounds = max(_MIN_ROUNDS, min(effective_rounds, _MAX_ROUNDS))
        debate = research_debate.run_research_debate(
            target, reports, rounds=effective_rounds, use_llm=use_llm,
            regime_line=rc['line'], context_line=context_line,
        )
        debate['_analyst_mean'] = _mean_scores(reports)

        tr = trader_risk.run_trader_and_risk(
            target, bundle, debate, use_llm=use_llm,
            regime_line=rc['line'], regime_adjustment=rc['adjustment'],
        )

    verdict = _flat_verdict(debate, tr, rc)
    method = _aggregate_method(reports, debate, tr)

    completed = datetime.now(timezone.utc)
    run_id = _make_run_id(target, started)
    record = {
        'id': run_id,
        'target': target,
        'symbol': bundle.get('symbol') or symbol,
        'market': bundle.get('market'),
        'created_at': started.isoformat(),
        'completed_at': completed.isoformat(),
        'elapsed_ms': int((completed - started).total_seconds() * 1000),
        'bundle_meta': _bundle_meta(bundle),
        'analyst_reports': reports,
        'research_debate': debate,
        'trader_risk': tr,
        'verdict': verdict,
        'regime_context': rc,
        'method': method,
        'provider_usage': _provider_usage(llm_calls),
    }

    _persist(record)
    return record


def is_disabled() -> bool:
    """True when MIROFISH_TRADINGAGENTS_DISABLED is a truthy flag (call-time read)."""
    return _env_flag('MIROFISH_TRADINGAGENTS_DISABLED')


def get_status() -> dict[str, Any]:
    """Enabled flag + tuning config + last-run pointer (all read at call time)."""
    latest = _read_latest()
    return {
        'enabled': not is_disabled(),
        'config': {
            'max_candidates': _env_int('MIROFISH_TA_MAX_CANDIDATES', 5),
            'debate_rounds': _env_rounds(),
            'boost_strong': _env_float('MIROFISH_TA_BOOST_STRONG', 8.0),
            'boost_buy': _env_float('MIROFISH_TA_BOOST_BUY', 5.0),
            'penalty_hold': _env_float('MIROFISH_TA_PENALTY_HOLD', 3.0),
            'sell_exclude_min_confidence': _env_float(
                'MIROFISH_TA_SELL_EXCLUDE_MIN_CONFIDENCE', 65.0,
            ),
            'penalty_uncertain_sell': _env_float(
                'MIROFISH_TA_PENALTY_UNCERTAIN_SELL', 5.0,
            ),
        },
        'last_run_id': (latest or {}).get('id'),
        'last_run_at': (latest or {}).get('completed_at'),
        'runs_count': _count_runs(),
        'llm': {
            'provider_order': llm_client.provider_order(),
            'providers': {
                'deepseek': {
                    'configured': bool(os.getenv('DEEPSEEK_API_KEY')),
                    'model': llm_client.deepseek_model(),
                },
                'openai': {
                    'configured': bool(os.getenv('OPENAI_API_KEY')),
                    'model': llm_client.openai_model(),
                },
            },
        },
        'learning': learning.get_workflow_policy(),
    }


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Return run summaries (newest first) — summary fields only, no heavy payloads."""
    summaries: list[dict[str, Any]] = []
    for path in _run_paths_newest_first():
        data = _read_json(path)
        if not isinstance(data, dict) or not data.get('id'):
            continue
        summaries.append(_summarize(data))
        if len(summaries) >= max(1, int(limit)):
            break
    return summaries


def get_run(run_id: str) -> dict[str, Any] | None:
    """Return one full run by id, or None. Rejects ids that fail the strict regex."""
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        return None
    path = os.path.join(RUNS_ROOT, f'{run_id}.json')
    data = _read_json(path)
    return data if isinstance(data, dict) else None


# ── Assembly helpers ────────────────────────────────────────────────

def _flat_verdict(debate: dict[str, Any], tr: dict[str, Any],
                  rc: dict[str, Any] | None = None) -> dict[str, Any]:
    pm = tr.get('pm_decision') or {}
    rc = rc or {'regime': 'unknown', 'direction': 'neutral', 'alignment': None, 'adjustment': 0.0}
    return {
        'verdict': pm.get('verdict', 'HOLD'),
        'confidence': pm.get('confidence', 0.0),
        'strong_buy': bool(pm.get('strong_buy', False)),
        'reasoning': pm.get('reasoning', ''),
        'bull_case': debate.get('bull_case', ''),
        'bear_case': debate.get('bear_case', ''),
        'risk_summary': _risk_summary(tr.get('risk_debate') or []),
        'regime': rc.get('regime', 'unknown'),
        'regime_adjustment': {
            'direction': rc.get('direction', 'neutral'),
            'alignment': rc.get('alignment'),
            'applied': rc.get('adjustment', 0.0),
        },
    }


def _risk_summary(risk_debate: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for entry in risk_debate:
        role = str(entry.get('role') or '?')
        first_line = str(entry.get('message') or '').splitlines()[0].strip() \
            if entry.get('message') else ''
        parts.append(f'{role}: {first_line}')
    return ' / '.join(parts)


def _bundle_meta(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        'errors': bundle.get('errors') or {},
        'has_price': bool(bundle.get('price')),
        'has_technical': bool(bundle.get('technical')),
        'has_rs': bool(bundle.get('rs')),
        'has_fundamentals': bool(bundle.get('fundamentals')),
        'corpus_chars': len(str(bundle.get('corpus') or '')),
    }


def _aggregate_method(reports: list[dict[str, Any]], debate: dict[str, Any],
                      tr: dict[str, Any]) -> str:
    methods = {str(r.get('method')) for r in reports}
    methods.add(str(debate.get('method')))
    methods.add(str(tr.get('method')))
    if methods == {'rule'}:
        return 'rule'
    if methods == {'llm'}:
        return 'llm'
    return 'mixed'


def _mean_scores(reports: list[dict[str, Any]]) -> float:
    scores = [_safe_float(r.get('score')) for r in (reports or [])]
    scores = [s for s in scores if s is not None]
    return sum(scores) / len(scores) if scores else 0.0


def _provider_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    providers: dict[str, dict[str, int]] = {}
    for call in calls:
        selected = str(call.get('provider') or 'none')
        for attempt in call.get('attempts') or []:
            provider = str(attempt.get('provider') or 'none')
            bucket = providers.setdefault(provider, {
                'attempts': 0, 'successes': 0, 'failures': 0, 'selected': 0,
            })
            bucket['attempts'] += 1
            bucket['successes'] += int(bool(attempt.get('success')))
            bucket['failures'] += int(not attempt.get('success'))
        if call.get('success'):
            providers.setdefault(selected, {
                'attempts': 0, 'successes': 0, 'failures': 0, 'selected': 0,
            })['selected'] += 1
    return {
        'calls': len(calls),
        'successes': sum(int(bool(call.get('success'))) for call in calls),
        'failures': sum(int(not call.get('success')) for call in calls),
        'fallbacks': sum(int(bool(call.get('fallback_used'))) for call in calls),
        'providers': providers,
        'attempts': sum(len(call.get('attempts') or []) for call in calls),
    }


def _make_run_id(target: str, when: datetime) -> str:
    # `ta_<YYYYMMDD_HHMMSS_ffffff>_<seq>_<sha1(target)[:6]>`. Microseconds handle
    # cross-second spacing; the monotonic seq guarantees uniqueness under a coarse
    # clock. Both live in the middle `[0-9_]+` group so `_RUN_ID_RE` still matches
    # and get_run() round-trips.
    digest = hashlib.sha1(str(target).encode('utf-8')).hexdigest()[:6]
    seq = next(_run_seq) % 1_000_000
    return f"ta_{when.strftime('%Y%m%d_%H%M%S_%f')}_{seq:06d}_{digest}"


def _summarize(data: dict[str, Any]) -> dict[str, Any]:
    verdict = data.get('verdict') or {}
    return {
        'id': data.get('id'),
        'target': data.get('target'),
        'symbol': data.get('symbol'),
        'created_at': data.get('created_at'),
        'verdict': verdict.get('verdict'),
        'confidence': verdict.get('confidence'),
        'strong_buy': bool(verdict.get('strong_buy', False)),
        'method': data.get('method'),
    }


# ── Persistence ─────────────────────────────────────────────────────

def _persist(record: dict[str, Any]) -> None:
    # `latest.json` is a rolling pointer to the most recently finished run; under
    # concurrent runs the last writer wins (the per-id file always survives).
    try:
        os.makedirs(RUNS_ROOT, exist_ok=True)
        write_json_atomic(os.path.join(RUNS_ROOT, f"{record['id']}.json"), record)
        write_json_atomic(os.path.join(RUNS_ROOT, LATEST_NAME), record)
    except Exception as exc:  # noqa: BLE001 — persistence must not abort a run
        logger.warning('[ta_engine] failed to persist run %s: %s', record.get('id'), exc)


def _run_paths_newest_first() -> list[str]:
    pattern = os.path.join(RUNS_ROOT, 'ta_*.json')
    paths = [p for p in glob.glob(pattern) if os.path.basename(p) != LATEST_NAME]
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return paths


def _count_runs() -> int:
    return len(_run_paths_newest_first())


def _read_latest() -> dict[str, Any] | None:
    data = _read_json(os.path.join(RUNS_ROOT, LATEST_NAME))
    return data if isinstance(data, dict) else None


def _read_json(path: str) -> Any:
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── Env readers (call-time only) ────────────────────────────────────

def _env_rounds() -> int:
    value = _env_int('MIROFISH_TA_DEBATE_ROUNDS', 2)
    return max(_MIN_ROUNDS, min(value, _MAX_ROUNDS))


def _env_flag(name: str) -> bool:
    return os.getenv(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        if isinstance(value, str):
            value = value.replace(',', '')
        return float(value)
    except (TypeError, ValueError):
        return None
