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
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any

from app.services.mirofish.tradingagents import analysts
from app.services.mirofish.tradingagents import data_hub
from app.services.mirofish.tradingagents import research_debate
from app.services.mirofish.tradingagents import trader_risk
from app.services.mirofish.tradingagents import regime as regime_mod
from app.services.mirofish.tradingagents import learning
from app.services.mirofish.tradingagents import run_cache
from app.services.mirofish import evidence_packet as evidence_packet_mod
from app.services.mirofish import llm_client
from app.services.ai_routing.contracts import Operation, ProviderErrorClass, RoutingRequest
from app.services.ai_routing.policy import policy_for
from app.services.ai_routing.router import reserve_openai_fallback, release_openai_reservations
from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)
DIGEST_SYSTEM = '결정론적 점수와 EvidencePacket을 변경하지 말고 짧게 요약하세요.'

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
                      context_line: str = '', profile: str = 'full',
                      evidence_packet: dict[str, Any] | None = None,
                      run_id: str | None = None, force: bool = False,
                      routing_run_id: str | None = None,
                      request_ids: dict[str, str] | None = None,
                      reservation_ids: dict[str, str] | None = None,
                      reservation_owner_tokens: dict[str, str] | None = None,
                      permits_preflighted: bool = False) -> dict[str, Any]:
    """Run an analysis, reusing only immutable validated compact artifacts."""
    profile = str(profile or 'full').strip().lower()
    started = datetime.now(timezone.utc)
    artifact_run_id = run_id or _make_run_id(target, started)
    kwargs = dict(
        symbol=symbol, rounds=rounds, use_llm=use_llm, brain=brain,
        context_line=context_line, profile=profile, evidence_packet=evidence_packet,
        run_id=artifact_run_id, force=force,
        routing_run_id=routing_run_id or artifact_run_id,
        request_ids=request_ids, reservation_ids=reservation_ids,
        reservation_owner_tokens=reservation_owner_tokens,
        permits_preflighted=permits_preflighted,
    )
    try:
        if profile != 'compact' or not evidence_packet or evidence_packet.get('cache_eligible') is False or force:
            return _execute_deep_analysis(target, **kwargs)
        key = evidence_packet_mod.cache_key({**evidence_packet, 'profile': profile})
        cache = run_cache.RunCache(os.path.join(RUNS_ROOT, 'run_cache.sqlite3'))
        return run_cache.execute_cached(
            cache, key, artifact_run_id,
            lambda: _execute_deep_analysis(target, **kwargs),
            lambda result: os.path.join(RUNS_ROOT, f"{result['id']}.json"),
        )
    finally:
        release_compact_permits(reservation_ids, reservation_owner_tokens)


def _execute_deep_analysis(target: str, *, symbol: str | None = None,
                      rounds: int | None = None, use_llm: bool = True,
                      brain: dict[str, Any] | None = None,
                      context_line: str = '', profile: str = 'full',
                      evidence_packet: dict[str, Any] | None = None,
                      run_id: str | None = None, force: bool = False,
                      routing_run_id: str | None = None,
                      request_ids: dict[str, str] | None = None,
                      reservation_ids: dict[str, str] | None = None,
                      reservation_owner_tokens: dict[str, str] | None = None,
                      permits_preflighted: bool = False) -> dict[str, Any]:
    """Run the full deep-verification pipeline for one target and persist it.

    Does NOT check the kill switch (the admin endpoint may run on demand); the
    workflow layer is responsible for gating. `rounds` overrides the env default
    when provided; otherwise MIROFISH_TA_DEBATE_ROUNDS (clamped 1..4) is used.
    `brain`, when provided, is a Brain 13D snapshot used to derive the regime
    context (see `regime.regime_context`) injected into the debate + trader/risk
    prompts and surfaced on the flat verdict.
    """
    started = datetime.now(timezone.utc)
    profile = str(profile or 'full').strip().lower()
    if profile not in {'full', 'compact'}:
        raise ValueError('profile must be full or compact')
    stable_run_id = run_id or _make_run_id(target, started)
    routing_run_id = routing_run_id or stable_run_id
    request_ids = request_ids or {}
    reservation_ids = dict(reservation_ids or {})
    reservation_owner_tokens = dict(reservation_owner_tokens or {})

    if profile == 'compact':
        packet = evidence_packet or {}
        if not symbol or str(packet.get('symbol') or '') != str(symbol) or str(packet.get('name') or '') != str(target):
            raise ValueError('compact EvidencePacket identity mismatch')
        if not packet.get('market'):
            raise ValueError('compact EvidencePacket identity missing market')
        execution_inputs = packet.get('execution_inputs')
        if not isinstance(execution_inputs, dict) or bool(execution_inputs.get('use_llm')) != bool(use_llm):
            raise ValueError('compact EvidencePacket execution mode mismatch')
        packet_brain = execution_inputs.get('brain')
        if brain is not None and json.dumps(brain, sort_keys=True, default=str) != json.dumps(packet_brain, sort_keys=True, default=str):
            raise ValueError('compact EvidencePacket brain mismatch')
        if use_llm and dict(packet.get('models') or {}) != routing_model_ids():
            raise ValueError('compact EvidencePacket model identity mismatch')
        brain = packet_brain
        bundle = data_hub.bundle_from_evidence_packet(packet, brain=brain)
    else:
        bundle = data_hub.gather_bundle(target, brain=brain) or {}
        if symbol and not bundle.get('symbol'):
            bundle['symbol'] = symbol

    rc = regime_mod.regime_context(brain)

    with llm_client.collect_generation_metadata(routing_run_id) as llm_calls:
        reports = analysts.run_analysts(bundle, use_llm=use_llm if profile == 'full' else False)
        compact_digest = None
        digest_llm_enabled = use_llm and (
            not permits_preflighted or bool(reservation_ids.get('bulk_text'))
        )
        if profile == 'compact' and digest_llm_enabled:
            raw_digest, digest_meta = llm_client.generate_text_with_metadata(
                evidence_packet_mod.bound_compact_prompt(
                    _compact_digest_prompt(target, reports, evidence_packet or {}), 'bulk_text',
                ),
                system=DIGEST_SYSTEM,
                temperature=0.2, max_tokens=768, json_mode=True,
                operation='bulk_text', run_id=routing_run_id,
                request_id=request_ids.get('bulk_text') or f'{stable_run_id}:evidence-digest',
                reservation_id=reservation_ids.get('bulk_text'),
                reservation_owner_token=reservation_owner_tokens.get('bulk_text'),
                domain_validator=_digest_domain_validator(
                    set((evidence_packet or {}).get('evidence_ids') or []),
                ),
                symbol=bundle.get('symbol') or symbol, market=bundle.get('market'),
                caller_endpoint='mirofish.tradingagents.compact_digest',
            )
            compact_digest = _parse_json(raw_digest) or {'digest': '', 'evidence_ids': []}
            compact_digest['llm'] = digest_meta
            allowed_evidence = set((evidence_packet or {}).get('evidence_ids') or [])
            digest_ids = list(compact_digest.get('evidence_ids') or [])
            digest_valid = bool(
                str(compact_digest.get('digest') or '').strip()
                and digest_ids
                and set(digest_ids) <= allowed_evidence
            )
            compact_digest['analysis_status'] = (
                str(digest_meta.get('analysis_status') or 'DEGRADED')
                if digest_valid else 'DEGRADED'
            )
        elif profile == 'compact' and use_llm:
            compact_digest = {
                'digest': '', 'evidence_ids': [], 'analysis_status': 'DEGRADED',
                'degraded_reason': 'preflight_permit_unavailable', 'llm': None,
            }

        effective_rounds = int(rounds) if rounds is not None else _env_rounds()
        effective_rounds = max(_MIN_ROUNDS, min(effective_rounds, _MAX_ROUNDS))
        if profile == 'compact':
            debate_llm_enabled = use_llm and (
                not permits_preflighted or bool(reservation_ids.get('compact_debate'))
            )
            debate = research_debate.run_compact_debate(
                target, reports, use_llm=debate_llm_enabled, run_id=routing_run_id,
                request_id=request_ids.get('compact_debate') or f'{stable_run_id}:compact-debate',
                reservation_id=reservation_ids.get('compact_debate'), evidence_packet=evidence_packet,
                reservation_owner_token=reservation_owner_tokens.get('compact_debate'),
            )
            if use_llm and not debate_llm_enabled:
                debate['analysis_status'] = 'DEGRADED'
                debate['degraded_reason'] = 'preflight_permit_unavailable'
        else:
            debate = research_debate.run_research_debate(
                target, reports, rounds=effective_rounds, use_llm=use_llm,
                regime_line=rc['line'], context_line=context_line,
                run_id=routing_run_id, symbol=bundle.get('symbol') or symbol,
                market=bundle.get('market'), name=bundle.get('display_name') or target,
            )
        debate['_analyst_mean'] = _mean_scores(reports)

        decisive_llm_enabled = use_llm and (
            not permits_preflighted or bool(reservation_ids.get('decisive_text'))
        )
        tr = trader_risk.run_trader_and_risk(
            target, bundle, debate, use_llm=decisive_llm_enabled,
            regime_line=rc['line'], regime_adjustment=rc['adjustment'],
            profile=profile, run_id=routing_run_id,
            symbol=bundle.get('symbol') or symbol, market=bundle.get('market'),
            name=bundle.get('display_name') or target, evidence_packet=evidence_packet,
            request_id=request_ids.get('decisive_text'),
            reservation_id=reservation_ids.get('decisive_text'),
            reservation_owner_token=reservation_owner_tokens.get('decisive_text'),
        )
        if use_llm and not decisive_llm_enabled:
            tr['analysis_status'] = 'HOLD_REVIEW'
            (tr.get('pm_decision') or {})['analysis_status'] = 'HOLD_REVIEW'

    analysis_status = str(tr.get('analysis_status') or 'SUCCESS_PRIMARY')
    if analysis_status == 'HOLD_REVIEW' or str(debate.get('analysis_status')) == 'HOLD_REVIEW':
        analysis_status = 'HOLD_REVIEW'
    elif profile == 'compact' and use_llm and (
        str((compact_digest or {}).get('analysis_status')) not in {'SUCCESS_PRIMARY', 'SUCCESS_FALLBACK'}
        or str(debate.get('analysis_status')) not in {'SUCCESS_PRIMARY', 'SUCCESS_FALLBACK'}
    ):
        analysis_status = 'DEGRADED'
    verdict = _flat_verdict(debate, tr, rc, analysis_status=analysis_status)
    method = _aggregate_method(reports, debate, tr)

    completed = datetime.now(timezone.utc)
    record = {
        'id': stable_run_id,
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
        'analysis_status': analysis_status,
        'profile': profile,
        'evidence_fingerprint': (evidence_packet or {}).get('fingerprint'),
        'evidence_packet': evidence_packet,
        'compact_digest': compact_digest,
        'force': bool(force),
        'routing_run_id': routing_run_id,
        'cache_hit': False,
        'source_run_id': stable_run_id,
    }

    _persist(record)
    return record


def routing_model_ids() -> dict[str, str]:
    """All primary/fallback model IDs that participate in compact cache identity."""
    out: dict[str, str] = {}
    for operation in (Operation.BULK_TEXT, Operation.COMPACT_DEBATE, Operation.DECISIVE_TEXT):
        for provider, model in policy_for(operation).models.items():
            out[f'{operation.value}.{provider}'] = model
    return out


def _digest_domain_validator(allowed: set[str]):
    def validate(data: Any) -> ProviderErrorClass | None:
        if not isinstance(data, dict) or not str(data.get('digest') or '').strip():
            return ProviderErrorClass.INVALID_JSON
        evidence_ids = data.get('evidence_ids')
        if not isinstance(evidence_ids, list) or not evidence_ids:
            return ProviderErrorClass.INVALID_JSON
        if any(not isinstance(value, str) for value in evidence_ids) or not set(evidence_ids) <= allowed:
            return ProviderErrorClass.INVALID_JSON
        return None
    return validate


def compact_request_ids(run_id: str, packet: dict[str, Any]) -> dict[str, str]:
    identity = f"{run_id}:{packet['symbol']}:{packet['fingerprint']}"
    return {operation.value: f'{identity}:{operation.value}' for operation in (
        Operation.BULK_TEXT, Operation.COMPACT_DEBATE, Operation.DECISIVE_TEXT,
    )}


def release_compact_permits(
    reservation_ids: dict[str, str] | None,
    reservation_owner_tokens: dict[str, str] | None = None,
) -> None:
    """Idempotently release every preflight hold not already settled/released."""
    if reservation_ids and reservation_owner_tokens:
        release_openai_reservations([
            (reservation_id, reservation_owner_tokens.get(operation, ''))
            for operation, reservation_id in reservation_ids.items()
        ])


def reserve_compact_batch(
    run_id: str, packets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reserve decisive permits first, then low-priority stages, before futures."""
    prepared: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    try:
        for packet in packets:
            ids = compact_request_ids(run_id, packet)
            request = RoutingRequest(
                operation=Operation.DECISIVE_TEXT,
                prompt=evidence_packet_mod.compact_reservation_prompt('decisive_text'),
                system=trader_risk.PM_SYSTEM,
                run_id=run_id, request_id=ids['decisive_text'],
                symbol=packet['symbol'], market=packet['market'], json_mode=True,
                max_output_tokens=1200,
            )
            permit = reserve_openai_fallback(
                request, owner_token=f'compact:{os.getpid()}:{uuid4()}',
            )
            record = {'symbol': packet['symbol'], 'request_ids': ids,
                      'permits': {}, 'status': 'admitted' if permit.approved else 'deferred',
                      'reason': permit.reason}
            if permit.approved and permit.acquired_by_caller and permit.reservation_id and permit.owner_token:
                record['permits']['decisive_text'] = permit.reservation_id
                prepared.append({'packet': packet, 'request_ids': ids,
                                 'reservation_ids': record['permits'],
                                 'reservation_owner_tokens': {'decisive_text': permit.owner_token}})
            records.append(record)
        by_symbol = {item['packet']['symbol']: item for item in prepared}
        for operation, cap in ((Operation.BULK_TEXT, 768), (Operation.COMPACT_DEBATE, 768)):
            for record in records:
                item = by_symbol.get(record['symbol'])
                if not item:
                    continue
                request = RoutingRequest(
                    operation=operation,
                    prompt=evidence_packet_mod.compact_reservation_prompt(operation.value),
                    system=(DIGEST_SYSTEM if operation is Operation.BULK_TEXT
                            else research_debate.COMPACT_DEBATE_SYSTEM),
                    run_id=run_id, request_id=item['request_ids'][operation.value],
                    symbol=item['packet']['symbol'], market=item['packet']['market'],
                    json_mode=True, max_output_tokens=cap,
                )
                permit = reserve_openai_fallback(
                    request, owner_token=f'compact:{os.getpid()}:{uuid4()}',
                )
                if permit.approved and permit.acquired_by_caller and permit.reservation_id and permit.owner_token:
                    item['reservation_ids'][operation.value] = permit.reservation_id
                    item['reservation_owner_tokens'][operation.value] = permit.owner_token
                    record['permits'][operation.value] = permit.reservation_id
                else:
                    record.setdefault('degraded_stages', []).append(
                        {'operation': operation.value, 'reason': permit.reason})
    except BaseException:
        for item in prepared:
            release_compact_permits(
                item.get('reservation_ids'), item.get('reservation_owner_tokens'),
            )
        raise
    return prepared, records


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
                  rc: dict[str, Any] | None = None, *,
                  analysis_status: str | None = None) -> dict[str, Any]:
    pm = tr.get('pm_decision') or {}
    rc = rc or {'regime': 'unknown', 'direction': 'neutral', 'alignment': None, 'adjustment': 0.0}
    incomplete = str(analysis_status or pm.get('analysis_status') or '') == 'HOLD_REVIEW'
    return {
        'verdict': 'HOLD_REVIEW' if incomplete else pm.get('verdict', 'HOLD'),
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
        'analysis_status': 'HOLD_REVIEW' if incomplete else str(analysis_status or 'SUCCESS_PRIMARY'),
        'rule_candidate_verdict': tr.get('rule_candidate_verdict') or pm.get('rule_candidate_verdict'),
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


def _compact_digest_prompt(target: str, reports: list[dict[str, Any]], packet: dict[str, Any]) -> str:
    return (
        f'분석 대상: {target}\n결정론 리포트: {json.dumps(reports, ensure_ascii=False, default=str)}\n'
        f'EvidencePacket: {json.dumps(packet, ensure_ascii=False, default=str)}\n'
        'JSON: {"digest":"...","evidence_ids":["..."]}'
    )


def _parse_json(raw: Any) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw or '')
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None
