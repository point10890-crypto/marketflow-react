"""Multi-MCP deep-research orchestration for profit-quality stock detection.

The MCP domains remain deterministic evidence owners. LLM agents may interpret,
challenge, reject, and rank evidence, but may not create symbols or market facts.
"""

from __future__ import annotations

import os
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services.mirofish import crash_rebound_gate, fear_index
from app.services.mirofish import evidence_packet as evidence_packet_mod
from app.services.mirofish import mcp_resource_catalog
from app.services.mirofish.alpha_scanner import get_price_trend_metrics
from app.services.mirofish.tradingagents import engine as tradingagents
from app.services.mirofish.tradingagents import run_cache as ta_run_cache
from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
RUNS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'multi_mcp_runs')

# Deterministic trend measurements remain a shared evidence contract. They are
# risk signals for the agents, not an admission gate that suppresses a genuine
# candidate before it can be analysed.
TREND_GATE_RULES = {
    'minimum_sample_days': 20,
    'minimum_trend_score': 8,
    'maximum_drawdown_20d_pct': 15,
    'positive_5d_and_20d': True,
    'above_ma20': True,
}


def trend_gate_checks(trend: dict[str, Any] | None) -> dict[str, bool]:
    """Return each deterministic trend rule and whether the candidate met it."""
    metrics = trend or {}
    return {
        'sample_days': _float(metrics.get('sample_days')) >= TREND_GATE_RULES['minimum_sample_days'],
        'positive_5d': _float(metrics.get('trend_5d_pct')) > 0,
        'positive_20d': _float(metrics.get('trend_20d_pct')) > 0,
        'above_ma20': _float(metrics.get('over_ma20_pct')) >= 0,
        'trend_score': _float(metrics.get('trend_score')) >= TREND_GATE_RULES['minimum_trend_score'],
        'drawdown': _float(metrics.get('drawdown_20d_pct')) <= TREND_GATE_RULES['maximum_drawdown_20d_pct'],
    }


def passes_trend_gate(trend: dict[str, Any] | None) -> bool:
    return all(trend_gate_checks(trend).values())


def architecture_manifest() -> dict[str, Any]:
    return {
        'schema_version': 'mirofish.multi_mcp.architecture.v1',
        'objective': 'forward_profit_quality_with_cash_wait',
        'numeric_authority': 'deterministic_mcp_tools_only',
        'mcp_domains': [
            {'id': 'market', 'owner': 'KIS/regime', 'mode': 'read_only'},
            {'id': 'technical', 'owner': 'trend/price structure', 'mode': 'read_only'},
            {'id': 'evidence', 'owner': 'DART/news/GraphRAG/freshness', 'mode': 'read_only'},
            {'id': 'memory', 'owner': 'look-ahead-safe outcomes', 'mode': 'read_only'},
            {'id': 'debate', 'owner': 'bull/bear/analyst cross-examination', 'mode': 'compute'},
            {'id': 'cio', 'owner': 'portfolio approval/rejection/cash wait', 'mode': 'compute'},
        ],
        'agent_flow': [
            'candidate_detection',
            'parallel_mcp_evidence',
            'profit_quality_gate',
            'four_analyst_reports',
            'bull_bear_cross_examination',
            'trader_risk_review',
            'cio_selection_or_cash_wait',
            'outcome_memory',
        ],
        'hard_rules': {
            'positive_5d_and_20d_trend': TREND_GATE_RULES['positive_5d_and_20d'],
            'above_ma20': TREND_GATE_RULES['above_ma20'],
            'minimum_sample_days': TREND_GATE_RULES['minimum_sample_days'],
            'minimum_trend_score': TREND_GATE_RULES['minimum_trend_score'],
            'maximum_drawdown_20d_pct': TREND_GATE_RULES['maximum_drawdown_20d_pct'],
            'minimum_cio_confidence': 60,
            'forced_top3': False,
            'automatic_ordering': False,
        },
    }


def run_multi_mcp_analysis(
    candidates: list[dict[str, Any]],
    *,
    use_llm: bool = True,
    max_parallel: int = 3,
    input_mode: str = 'verified_kis_pipeline',
    max_candidates: int = 5,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    run_id = f"multi_mcp_{started:%Y%m%d_%H%M%S_%f}"
    normalized = [_normalize_candidate(row) for row in candidates[:20]]
    clean_candidates = []
    seen_symbols: set[str] = set()
    for row in normalized:
        if not row or row['symbol'] in seen_symbols:
            continue
        seen_symbols.add(row['symbol'])
        clean_candidates.append(row)
    market_context = {
        'crash_rebound': crash_rebound_gate.read_latest_crash_rebound_gate(),
        'fear_index': fear_index.read_latest_fear_index(),
    }
    evidence_context = mcp_resource_catalog.build_mcp_resource_snapshot(
        include_deferred=False,
    )

    evidence_packets = [_evidence_packet(row, use_llm=use_llm) for row in clean_candidates]
    eligible = [packet for packet in evidence_packets if packet['profit_gate']['passed']]
    admission = ta_run_cache.AdmissionManager(os.path.join(RUNS_ROOT, 'candidate_admission.sqlite3'))
    admitted, budget_summary = admission.admit(run_id, eligible, limit=max(0, min(int(max_candidates), 5)))
    prepared_by_symbol: dict[str, dict[str, Any]] = {}
    if use_llm:
        prepared, permit_records = tradingagents.reserve_compact_batch(run_id, admitted)
        prepared_by_symbol = {item['packet']['symbol']: item for item in prepared}
        admitted = [packet for packet in admitted if packet['symbol'] in prepared_by_symbol]
        budget_summary['provider_permits'] = permit_records
        budget_summary['deferred'] += budget_summary['admitted'] - len(admitted)
        budget_summary['admitted'] = len(admitted)
    analyses: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(max_parallel), 5))) as pool:
        pending = {
            pool.submit(
                tradingagents.run_deep_analysis,
                packet['name'],
                symbol=packet['symbol'],
                use_llm=use_llm,
                profile='compact', evidence_packet=packet,
                routing_run_id=run_id,
                request_ids=(prepared_by_symbol.get(packet['symbol']) or {}).get('request_ids'),
                reservation_ids=(prepared_by_symbol.get(packet['symbol']) or {}).get('reservation_ids'),
                reservation_owner_tokens=(prepared_by_symbol.get(packet['symbol']) or {}).get('reservation_owner_tokens'),
                permits_preflighted=use_llm,
            ): packet
            for packet in admitted
        }
        for future, packet in pending.items():
            reservation_ids = (prepared_by_symbol.get(packet['symbol']) or {}).get('reservation_ids')
            owner_tokens = (prepared_by_symbol.get(packet['symbol']) or {}).get('reservation_owner_tokens')
            if reservation_ids:
                future.add_done_callback(
                    lambda _future, permits=dict(reservation_ids), owners=dict(owner_tokens or {}):
                    tradingagents.release_compact_permits(permits, owners)
                )
        for future in as_completed(pending):
            packet = pending[future]
            try:
                deep_run = future.result()
                analyses.append(_critic_review(packet, deep_run))
            except Exception as exc:  # isolate one agent branch
                analyses.append({
                    'symbol': packet['symbol'],
                    'name': packet['name'],
                    'approved': False,
                    'error': type(exc).__name__,
                    'reason': str(exc)[:240],
                })

    approved = sorted(
        [row for row in analyses if row.get('approved')],
        key=lambda row: row.get('portfolio_score', 0),
        reverse=True,
    )[:3]
    status = (
        'portfolio_ready' if len(approved) == 3
        else 'selective_portfolio' if approved
        else 'cash_wait'
    )
    completed = datetime.now(timezone.utc)
    result = {
        'schema_version': 'mirofish.multi_mcp.run.v1',
        'id': run_id,
        'status': status,
        'input_mode': input_mode,
        'publishable_top3': input_mode in {'live_kis_scan', 'verified_kis_pipeline'},
        'created_at': started.isoformat(),
        'completed_at': completed.isoformat(),
        'elapsed_ms': int((completed - started).total_seconds() * 1000),
        'architecture': architecture_manifest(),
        'market_context': market_context,
        'evidence_context': {
            'status': evidence_context.get('status'),
            'resource_count': len(evidence_context.get('resources') or []),
        },
        'candidate_count': len(clean_candidates),
        'profit_gate_passed_count': len(eligible),
        'budget_summary': budget_summary,
        'evidence_packets': evidence_packets,
        'agent_analyses': analyses,
        'selected': approved,
        'cash_wait_reason': (
            'No candidate survived deterministic trend gates and CIO review.'
            if not approved else None
        ),
    }
    os.makedirs(RUNS_ROOT, exist_ok=True)
    write_json_atomic(os.path.join(RUNS_ROOT, f'{run_id}.json'), result)
    write_json_atomic(os.path.join(RUNS_ROOT, 'latest.json'), result)
    return result


def run_live_market_scan(*, use_llm: bool = True, max_parallel: int = 3) -> dict[str, Any]:
    """Detect live KIS candidates, then run the complete Multi-MCP pipeline."""
    from app.services.kis_screener import run_screening

    screening = run_screening(force=True)
    candidates = screening.get('candidate_pool') if isinstance(screening, dict) else []
    if isinstance(candidates, list):
        observed_at = screening.get('timestamp')
        candidates = [
            {
                **row, 'source': 'KIS', 'observed_at': row.get('observed_at') or observed_at,
                'source_packets': row.get('source_packets') or [{
                    'evidence_id': f"kis-screen-{row.get('code') or row.get('symbol')}",
                    'source': 'KIS', 'source_type': 'market_screen',
                    'title': row.get('name'), 'fetched_at': row.get('observed_at') or observed_at,
                    'freshness': 'live', 'confidence': 1.0,
                    'content': {'price': row.get('price'), 'change_pct': row.get('change_pct'),
                                'volume': row.get('volume')},
                }],
            }
            for row in candidates
            if isinstance(row, dict)
        ]
    result = run_multi_mcp_analysis(
        candidates if isinstance(candidates, list) else [],
        use_llm=use_llm,
        max_parallel=max_parallel,
        input_mode='live_kis_scan',
    )
    result['scanner'] = {
        'timestamp': screening.get('timestamp') if isinstance(screening, dict) else None,
        'market_status': screening.get('market_status') if isinstance(screening, dict) else None,
        'quote_mode': screening.get('quote_mode') if isinstance(screening, dict) else None,
        'source_counts': screening.get('source_counts') if isinstance(screening, dict) else None,
    }
    return result


def _normalize_candidate(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get('symbol') or row.get('code') or '').strip()
    name = str(row.get('name') or '').strip()
    if len(symbol) != 6 or not symbol.isdigit() or not name:
        return None
    source = str(row.get('source') or '').strip().upper()
    market = str(row.get('market') or '').strip()
    current_price = _float(row.get('current_price') or row.get('price'))
    if source != 'KIS' or current_price <= 0 or not market:
        return None
    return {
        'symbol': symbol,
        'name': name,
        'current_price': current_price,
        'change_rate': _float(row.get('change_rate') or row.get('change_pct')),
        'volume': _float(row.get('volume')),
        'source': source,
        'observed_at': row.get('observed_at'),
        'market': market,
        'source_packets': row.get('source_packets') or [],
        'source_cutoff': row.get('source_cutoff') or max((
            str(packet.get('fetched_at') or packet.get('observed_at') or '')
            for packet in (row.get('source_packets') or []) if isinstance(packet, dict)
        ), default=str(row.get('observed_at') or '')),
    }


def _evidence_packet(candidate: dict[str, Any], *, use_llm: bool = True) -> dict[str, Any]:
    trend = get_price_trend_metrics(
        candidate['symbol'],
        current_price=candidate['current_price'],
        change_rate=candidate['change_rate'],
        volume=candidate['volume'],
    )
    admission_checks = {
        'fresh_observation': _is_fresh_observation(candidate.get('observed_at')),
        'positive_session': candidate['change_rate'] > 0,
    }
    trend_checks = trend_gate_checks(trend)
    risk_flags = [
        name for name, passed in trend_checks.items()
        if not passed
    ]
    checks = {
        **admission_checks,
        **trend_gate_checks(trend),
    }
    legacy = {
        **candidate,
        'trend': trend,
        'profit_gate': {
            # Only a verified, fresh positive market observation may enter
            # agent analysis. Trend failures are retained as explicit risk
            # evidence for the analyst and CIO instead of silently deleting
            # the candidate before analysis.
            'passed': all(admission_checks.values()),
            'checks': checks,
            'risk_flags': risk_flags,
        },
    }
    canonical = evidence_packet_mod.build_evidence_packet(
        {**legacy, 'as_of': candidate.get('source_cutoff'), 'risk_flags': risk_flags},
        profile='compact',
        models=tradingagents.routing_model_ids(),
        deterministic_scores={
            'alpha': candidate.get('alpha_score'), 'risk': candidate.get('risk_score'),
            'trend': trend.get('trend_score'), 'relative_strength': candidate.get('rs_rating'),
        }, risk_gates=checks, execution_inputs={'use_llm': bool(use_llm), 'brain': None},
    )
    return {**legacy, **canonical, 'profit_gate': legacy['profit_gate'], 'trend': trend}


def _critic_review(packet: dict[str, Any], deep_run: dict[str, Any]) -> dict[str, Any]:
    verdict = deep_run.get('verdict') or {}
    action = str(verdict.get('verdict') or 'HOLD').upper()
    confidence = _float(verdict.get('confidence'))
    confidence_valid = 0 <= confidence <= 100
    approved = (
        str(deep_run.get('analysis_status') or verdict.get('analysis_status') or 'SUCCESS_PRIMARY')
        in {'SUCCESS_PRIMARY', 'SUCCESS_FALLBACK'}
        and action != 'HOLD_REVIEW'
        and action in {'BUY', 'STRONG_BUY', 'BUY_CANDIDATE'}
        and confidence_valid
        and confidence >= 60
    )
    trend_score = _float((packet.get('trend') or {}).get('trend_score'))
    portfolio_score = (
        round((confidence * 0.65) + (trend_score / 15 * 35), 2)
        if confidence_valid else 0.0
    )
    return {
        'symbol': packet['symbol'],
        'name': packet['name'],
        'approved': approved,
        'action': action,
        'confidence': confidence,
        'confidence_valid': confidence_valid,
        'portfolio_score': portfolio_score,
        'trend': packet['trend'],
        'analyst_reports': deep_run.get('analyst_reports') or [],
        'debate': deep_run.get('research_debate') or {},
        'risk_review': deep_run.get('trader_risk') or {},
        'cio_reasoning': verdict.get('reasoning'),
        'deep_run_id': deep_run.get('id'),
        'analysis_status': deep_run.get('analysis_status') or verdict.get('analysis_status'),
    }


def _float(value: Any) -> float:
    try:
        parsed = float(value or 0)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_fresh_observation(value: Any) -> bool:
    try:
        observed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=ZoneInfo('Asia/Seoul'))
        age_seconds = (
            datetime.now(timezone.utc) - observed.astimezone(timezone.utc)
        ).total_seconds()
        return -300 <= age_seconds <= 5400
    except (TypeError, ValueError):
        return False
