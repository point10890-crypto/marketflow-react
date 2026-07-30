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
from app.services.mirofish import mcp_resource_catalog
from app.services.mirofish.alpha_scanner import get_price_trend_metrics
from app.services.mirofish.tradingagents import engine as tradingagents
from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
RUNS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'multi_mcp_runs')

# Single source of truth for the deterministic trend gate. Every upstream
# detector must screen with this exact rule set: a candidate that reaches deep
# research without passing it can only end in a late stand aside, after the
# LLM budget has already been spent.
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
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
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

    evidence_packets = [_evidence_packet(row) for row in clean_candidates]
    eligible = [packet for packet in evidence_packets if packet['profit_gate']['passed']]
    analyses: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(max_parallel), 5))) as pool:
        pending = {
            pool.submit(
                tradingagents.run_deep_analysis,
                packet['name'],
                symbol=packet['symbol'],
                use_llm=use_llm,
            ): packet
            for packet in eligible
        }
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
    run_id = f"multi_mcp_{started:%Y%m%d_%H%M%S_%f}"
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
            {**row, 'source': 'KIS', 'observed_at': row.get('observed_at') or observed_at}
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
    current_price = _float(row.get('current_price') or row.get('price'))
    if source != 'KIS' or current_price <= 0:
        return None
    return {
        'symbol': symbol,
        'name': name,
        'current_price': current_price,
        'change_rate': _float(row.get('change_rate') or row.get('change_pct')),
        'volume': _float(row.get('volume')),
        'source': source,
        'observed_at': row.get('observed_at'),
    }


def _evidence_packet(candidate: dict[str, Any]) -> dict[str, Any]:
    trend = get_price_trend_metrics(
        candidate['symbol'],
        current_price=candidate['current_price'],
        change_rate=candidate['change_rate'],
        volume=candidate['volume'],
    )
    checks = {
        'fresh_observation': _is_fresh_observation(candidate.get('observed_at')),
        **trend_gate_checks(trend),
        'positive_session': candidate['change_rate'] > 0,
    }
    return {
        **candidate,
        'trend': trend,
        'profit_gate': {
            'passed': all(checks.values()),
            'checks': checks,
        },
    }


def _critic_review(packet: dict[str, Any], deep_run: dict[str, Any]) -> dict[str, Any]:
    verdict = deep_run.get('verdict') or {}
    action = str(verdict.get('verdict') or 'HOLD').upper()
    confidence = _float(verdict.get('confidence'))
    confidence_valid = 0 <= confidence <= 100
    approved = (
        action in {'BUY', 'STRONG_BUY', 'BUY_CANDIDATE'}
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
