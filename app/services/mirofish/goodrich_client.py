"""Boundary client for the separately deployed Goodrich TradingOS service.

Goodrich owns KIS market facts, deterministic ranking, and price levels.
MarketFlow only authenticates access, forwards requests, and validates the
minimum response contract before presenting it to AI Brain subscribers.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests


DEFAULT_BASE_URL = 'http://127.0.0.1:8000'
DEFAULT_TIMEOUT_SECONDS = 12.0
RESEARCH_TIMEOUT_SECONDS = 90.0
# A selective, fully validated portfolio is publishable. Requiring three CIO
# approvals converted ordinary low-breadth conditions into a detection outage.
MINIMUM_PUBLISHABLE_CANDIDATES = 1


class GoodrichServiceError(RuntimeError):
    """Safe upstream error that can be returned without leaking credentials."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _base_url() -> str:
    value = (os.getenv('GOODRICH_API_BASE_URL') or DEFAULT_BASE_URL).strip().rstrip('/')
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
        raise GoodrichServiceError('Goodrich 서비스 주소 설정이 올바르지 않습니다.', status_code=503)
    return value


def _request(
    method: str,
    path: str,
    *,
    timeout: float,
    json_body: dict | None = None,
    integration: dict | None = None,
    validate_fund_manager: bool = True,
) -> dict:
    try:
        response = requests.request(
            method,
            f'{_base_url()}{path}',
            timeout=timeout,
            headers={'Accept': 'application/json'},
            json=json_body,
        )
    except requests.Timeout as exc:
        raise GoodrichServiceError('Goodrich 서비스 응답 시간이 초과되었습니다.', status_code=504) from exc
    except requests.RequestException as exc:
        raise GoodrichServiceError('Goodrich 서비스에 연결할 수 없습니다.', status_code=503) from exc

    if response.status_code >= 400:
        status = 503 if response.status_code >= 500 else 502
        raise GoodrichServiceError('Goodrich 서비스가 요청을 처리하지 못했습니다.', status_code=status)

    try:
        payload = response.json()
    except ValueError as exc:
        raise GoodrichServiceError('Goodrich 서비스 응답 형식이 올바르지 않습니다.') from exc
    if not isinstance(payload, dict):
        raise GoodrichServiceError('Goodrich 서비스 응답 형식이 올바르지 않습니다.')
    if validate_fund_manager:
        return _validate_and_envelope(payload, integration=integration)
    return payload


def _validate_market_leader_contract(payload: dict, picks: list) -> None:
    if not picks:
        return
    selection = payload.get('selection')
    if (
        not isinstance(selection, dict)
        or selection.get('source') != 'kis_detected_market_leaders'
        or selection.get('market_data_source') != 'KIS'
        or selection.get('simulation') is not False
    ):
        raise GoodrichServiceError('검증된 KIS 시장 주도주 출처가 아니므로 TOP 3를 게시하지 않습니다.')
    if not 1 <= len(picks) <= 3:
        raise GoodrichServiceError('검증된 시장 주도주가 없어 결과를 게시하지 않습니다.')
    ai = payload.get('ai')
    ai_provider = str((ai or {}).get('provider') or '').lower()
    fallback_from = str((ai or {}).get('fallback_from') or '').lower()
    if (
        not isinstance(ai, dict)
        or not (
            ai_provider == 'deepseek'
            or (ai_provider == 'openai' and fallback_from == 'deepseek')
        )
        or ai.get('status') != 'completed'
    ):
        raise GoodrichServiceError(
            'DeepSeek 우선 또는 검증된 OpenAI 백업 분석이 완료되지 않아 '
            'TOP 3를 게시하지 않습니다.'
        )

    seen_symbols: set[str] = set()
    now = datetime.now(timezone.utc)
    for pick in picks:
        if not isinstance(pick, dict):
            raise GoodrichServiceError('Goodrich TOP 3 응답 형식이 올바르지 않습니다.')
        symbol = str(pick.get('symbol') or '').strip()
        if len(symbol) != 6 or not symbol.isdigit() or symbol in seen_symbols:
            raise GoodrichServiceError('실제 상장 종목 식별정보가 유효하지 않습니다.')
        current_price = _safe_float(pick.get('current_price'))
        target_price = _safe_float(pick.get('target_price'))
        stop_price = _safe_float(pick.get('stop_price'))
        if current_price <= 0 or not (0 < stop_price < current_price < target_price):
            raise GoodrichServiceError('KIS 현재가·목표가·손절가 검증에 실패해 TOP 3를 게시하지 않습니다.')
        try:
            observed_at = datetime.fromisoformat(str(pick.get('observed_at') or '').replace('Z', '+00:00'))
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            age = now - observed_at.astimezone(timezone.utc)
        except (TypeError, ValueError):
            raise GoodrichServiceError('KIS 관측시각이 없어 TOP 3를 게시하지 않습니다.') from None
        if age < -timedelta(minutes=5) or age > timedelta(minutes=90):
            raise GoodrichServiceError('KIS 현재가가 최신 장중 데이터가 아니므로 TOP 3를 게시하지 않습니다.')
        seen_symbols.add(symbol)


def _validate_and_envelope(payload: dict, *, integration: dict | None = None) -> dict:
    picks = payload.get('picks')
    if not isinstance(picks, list):
        raise GoodrichServiceError('Goodrich TOP 3 응답에 종목 목록이 없습니다.')

    normalized_picks = []
    for pick in picks[:3]:
        if not isinstance(pick, dict):
            raise GoodrichServiceError('Goodrich 종목 응답 형식이 올바르지 않습니다.')
        symbol = str(pick.get('symbol') or '').strip()
        if not symbol or not pick.get('name'):
            raise GoodrichServiceError('Goodrich 종목 식별 정보가 누락되었습니다.')
        normalized_picks.append(dict(pick))

    _validate_market_leader_contract(payload, normalized_picks)
    result = dict(payload)
    result['picks'] = normalized_picks
    result['integration'] = {
        'service': 'goodrich-tradingos',
        'source': 'goodrich-api',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'universe': 'kis-market-leaders',
        'universe_size': len(normalized_picks),
        'ranking_owner': 'kis-quant-plus-deepseek-primary-openai-fallback',
        'ai_role': 'deepseek-primary-openai-fallback-plus-kis-recovery',
        'provider_priority': ['deepseek', 'openai_fallback'],
        'ordering_enabled': True,
        **(integration or {}),
    }
    if isinstance(result['integration'].get('multi_mcp'), dict):
        result['multi_mcp'] = result['integration']['multi_mcp']
    return result


def get_fund_manager() -> dict:
    result = _request('GET', '/v1/fund-manager', timeout=DEFAULT_TIMEOUT_SECONDS)
    try:
        from app.services.mirofish.multi_mcp_orchestrator import RUNS_ROOT

        with open(os.path.join(RUNS_ROOT, 'latest.json'), encoding='utf-8') as handle:
            latest = json.load(handle)
        if isinstance(latest, dict) and latest.get('publishable_top3') is True:
            result['multi_mcp'] = {
                'id': latest.get('id'),
                'status': latest.get('status'),
                'completed_at': latest.get('completed_at'),
                'candidate_count': latest.get('candidate_count'),
                'profit_gate_passed_count': latest.get('profit_gate_passed_count'),
                'selected': [
                    {
                        'symbol': row.get('symbol'),
                        'name': row.get('name'),
                        'action': row.get('action'),
                        'confidence': row.get('confidence'),
                        'portfolio_score': row.get('portfolio_score'),
                    }
                    for row in latest.get('selected') or []
                    if isinstance(row, dict)
                ],
                'analysis_candidates': [
                    {
                        'symbol': row.get('symbol'),
                        'name': row.get('name'),
                        'action': row.get('action'),
                        'confidence': row.get('confidence'),
                        'portfolio_score': row.get('portfolio_score'),
                        'reasoning': row.get('cio_reasoning'),
                    }
                    for row in latest.get('agent_analyses') or []
                    if isinstance(row, dict)
                ],
                'cash_wait_reason': latest.get('cash_wait_reason'),
                'architecture': latest.get('architecture'),
                'input_mode': latest.get('input_mode'),
                'publishable_top3': True,
            }
    except (OSError, ValueError, TypeError):
        pass
    return result


def monitor_fund_manager() -> dict:
    return _request(
        'POST',
        '/v1/fund-manager/monitor',
        timeout=DEFAULT_TIMEOUT_SECONDS,
        validate_fund_manager=False,
    )


def stand_aside_fund_manager(
    *,
    reason: str,
    candidate_count: int,
    integration: dict | None = None,
) -> dict:
    return _request(
        'POST',
        '/v1/fund-manager/stand-aside',
        timeout=DEFAULT_TIMEOUT_SECONDS,
        json_body={
            'reason': reason,
            'candidate_count': max(0, int(candidate_count)),
        },
        integration=integration,
    )


def run_research() -> dict:
    from app.services.kis_screener import run_screening
    from app.services.mirofish.alpha_scanner import get_price_trend_metrics
    from app.services.mirofish.multi_mcp_orchestrator import (
        TREND_GATE_RULES,
        passes_trend_gate,
        run_multi_mcp_analysis,
    )

    screening = run_screening(force=True)
    rows = screening.get('candidate_pool') if isinstance(screening, dict) else None
    using_candidate_pool = isinstance(rows, list)
    if not isinstance(rows, list):
        rows = screening.get('results') if isinstance(screening, dict) else None
    if not isinstance(rows, list):
        rows = []

    candidates = []
    candidate_rows = []
    rejected = []
    trend_passed_count = 0
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('code') or row.get('symbol') or '').strip()
        name = str(row.get('name') or '').strip()
        change_pct = _safe_float(row.get('change_pct'))
        trend = get_price_trend_metrics(
            symbol,
            current_price=_safe_float(row.get('price') or row.get('current_price')),
            change_rate=change_pct,
            volume=_safe_float(row.get('volume')),
        )
        if passes_trend_gate(trend):
            trend_passed_count += 1
        is_preferred = name.endswith(('우', '우B', '우C'))
        if (
            len(symbol) == 6
            and symbol.isdigit()
            and name
            and not is_preferred
            # Goodrich is the decision layer. Scanner score and trend are
            # evidence for the agents, not pre-analysis rejection rules.
            and change_pct > 0
        ):
            from app.services.kis_screener import resolve_symbol_market
            market = str(row.get('market') or resolve_symbol_market(symbol) or '').strip()
            if not market:
                rejected.append({'symbol': symbol, 'reason': 'market_unresolved', 'trend': trend})
                continue
            candidates.append({'symbol': symbol, 'name': name})
            candidate_rows.append({
                'symbol': symbol,
                'name': name,
                'price': _safe_float(row.get('price') or row.get('current_price')),
                'change_pct': change_pct,
                'volume': _safe_float(row.get('volume')),
                'source': 'KIS',
                'observed_at': screening.get('timestamp'),
                'market': market,
                'score': (
                    dict(row.get('score') or {})
                    if isinstance(row.get('score'), dict) else {}
                ),
                'score_complete': bool(row.get('score_complete')),
                'grade': row.get('grade'),
                'eligible': row.get('eligible'),
                'rejection_reason': row.get('rejection_reason'),
                'incomplete_reasons': row.get('incomplete_reasons') or [],
                'trading_value': _safe_float(row.get('trading_value')),
                'source_packets': [{
                    'evidence_id': f'kis-screen-{symbol}', 'source': 'KIS',
                    'source_type': 'market_screen', 'title': name,
                    'fetched_at': screening.get('timestamp'), 'freshness': 'live',
                    'confidence': 1.0,
                    'content': {'price': _safe_float(row.get('price') or row.get('current_price')),
                                'change_pct': change_pct, 'volume': _safe_float(row.get('volume'))},
                }],
            })
        else:
            rejected.append({'symbol': symbol, 'trend': trend})

    screening_integration = {
        'source': 'marketflow-kis-leading-scanner',
        'universe': 'live-kospi-kosdaq-leaders',
        'universe_size': len(candidates),
        'candidate_count': len(rows),
        'trend_gate': {
            'required': False,
            'role': 'agent_risk_evidence',
            'rule_source': 'multi_mcp_orchestrator.TREND_GATE_RULES',
            **TREND_GATE_RULES,
            'passed_count': trend_passed_count,
            'rejected_count': len(rejected),
        },
        'scanner_timestamp': screening.get('timestamp'),
        'market_status': screening.get('market_status'),
        'ranking_owner': 'marketflow-kis-rules-then-goodrich-quant',
    }
    if len(candidates) < MINIMUM_PUBLISHABLE_CANDIDATES:
        return stand_aside_fund_manager(
            reason='profit_quality_gate_below_minimum',
            candidate_count=len(candidates),
            integration=screening_integration,
        )

    deep_research = run_multi_mcp_analysis(
        candidate_rows,
        use_llm=True,
        max_parallel=3,
        input_mode='verified_kis_pipeline',
    )
    selected_symbols = [
        str(row.get('symbol') or '')
        for row in deep_research.get('selected') or []
        if isinstance(row, dict)
    ]
    candidate_by_symbol = {
        candidate['symbol']: candidate for candidate in candidates
    }
    candidates = [
        candidate_by_symbol[symbol]
        for symbol in dict.fromkeys(selected_symbols)
        if symbol in candidate_by_symbol
    ]
    if len(candidates) < MINIMUM_PUBLISHABLE_CANDIDATES:
        return stand_aside_fund_manager(
            reason='multi_mcp_cio_approved_below_minimum',
            candidate_count=len(candidates),
            integration={
                **screening_integration,
                'universe_size': len(candidates),
                'multi_mcp': {
                    'id': deep_research.get('id'),
                    'status': deep_research.get('status'),
                    'candidate_count': deep_research.get('candidate_count'),
                    'profit_gate_passed_count': deep_research.get('profit_gate_passed_count'),
                    'cash_wait_reason': deep_research.get('cash_wait_reason'),
                    'publishable_top3': deep_research.get('publishable_top3'),
                    'cio_selected_count': len(candidates),
                    'selection_mode': deep_research.get('selection_mode'),
                    'ai_selected_count': deep_research.get('ai_selected_count'),
                    'deterministic_fallback_count': deep_research.get('deterministic_fallback_count'),
                    'top3_shortfall': deep_research.get('top3_shortfall'),
                    'top3_guarantee_met': deep_research.get('top3_guarantee_met'),
                },
            },
        )

    multi_mcp_snapshot = {
        'id': deep_research.get('id'),
        'status': deep_research.get('status'),
        'completed_at': deep_research.get('completed_at'),
        'candidate_count': deep_research.get('candidate_count'),
        'profit_gate_passed_count': deep_research.get('profit_gate_passed_count'),
        'selected': [
            {
                'symbol': row.get('symbol'),
                'name': row.get('name'),
                'action': row.get('action'),
                'confidence': row.get('confidence'),
                'portfolio_score': row.get('portfolio_score'),
                'selection_source': row.get('selection_source'),
                'selection_rank': row.get('selection_rank'),
                'deterministic_score': row.get('deterministic_score'),
            }
            for row in deep_research.get('selected') or []
            if isinstance(row, dict)
        ],
        'cash_wait_reason': deep_research.get('cash_wait_reason'),
        'architecture': deep_research.get('architecture'),
        'input_mode': deep_research.get('input_mode'),
        'publishable_top3': deep_research.get('publishable_top3'),
        'selection_mode': deep_research.get('selection_mode'),
        'ai_selected_count': deep_research.get('ai_selected_count'),
        'deterministic_fallback_count': deep_research.get('deterministic_fallback_count'),
        'top3_shortfall': deep_research.get('top3_shortfall'),
        'top3_guarantee_met': deep_research.get('top3_guarantee_met'),
        'data_shortage_reason': deep_research.get('data_shortage_reason'),
    }
    selected_by_symbol = {
        str(row.get('symbol') or ''): row
        for row in deep_research.get('selected') or []
        if isinstance(row, dict)
    }
    ranked_candidates = [
        {
            'symbol': candidate['symbol'],
            'name': candidate['name'],
            'rank': rank,
            'score': _safe_float(
                (selected_by_symbol.get(candidate['symbol']) or {}).get(
                    'portfolio_score'
                )
            ),
            'tier': str(
                (selected_by_symbol.get(candidate['symbol']) or {}).get(
                    'selection_source'
                ) or 'deterministic_kis_fallback'
            ),
        }
        for rank, candidate in enumerate(candidates, start=1)
    ]
    research = _request(
        'POST',
        '/v1/fund-manager/research',
        timeout=RESEARCH_TIMEOUT_SECONDS,
        json_body={
            'candidates': candidates,
            'ranked_candidates': ranked_candidates,
        },
        integration={
            **screening_integration,
            'universe_size': len(candidates),
            'multi_mcp': {
                **multi_mcp_snapshot,
                'cio_selected_count': len(candidates),
            },
        },
    )
    returned_by_symbol = {
        str(row.get('symbol') or ''): row
        for row in research.get('picks') or []
        if isinstance(row, dict)
    }
    expected_symbols = [candidate['symbol'] for candidate in candidates]
    if set(returned_by_symbol) != set(expected_symbols):
        raise GoodrichServiceError(
            'Goodrich 응답이 요청한 검증 TOP3와 일치하지 않습니다.'
        )
    research['picks'] = [
        {
            **returned_by_symbol[symbol],
            'rank': rank,
            'selection_source': str(
                (selected_by_symbol.get(symbol) or {}).get('selection_source') or ''
            ),
        }
        for rank, symbol in enumerate(expected_symbols, start=1)
    ]
    return research


def get_detection_history(*, limit: int = 20, offset: int = 0) -> dict:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    return _request(
        'GET',
        f'/v1/fund-manager/history?limit={safe_limit}&offset={safe_offset}',
        timeout=DEFAULT_TIMEOUT_SECONDS,
        validate_fund_manager=False,
    )


def get_performance(*, window_days: int = 30) -> dict:
    safe_window = max(1, min(int(window_days), 365))
    return _request(
        'GET',
        f'/v1/fund-manager/performance?window_days={safe_window}',
        timeout=DEFAULT_TIMEOUT_SECONDS,
        validate_fund_manager=False,
    )
