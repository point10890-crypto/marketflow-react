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
# 검출 0 방지(2026-09-04): CIO 승인 TOP 3 와 별개로, 스캐너 순위 기반 "관찰 후보" 목록을
# 매 사이클 반드시 만든다. 게이트(등락>0·신선도·CIO BUY≥60) 중 하나라도 실패하면
# 이전에는 빈 결과("선정된 종목이 없습니다")만 남아 파이프라인 고장과 구분되지 않았다.
WATCHLIST_SIZE = 5
RESEARCH_LATEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'data', 'admin_mirofish', 'goodrich_research_latest.json',
)


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
    if (
        not isinstance(ai, dict)
        or str(ai.get('provider') or '').lower() != 'openai'
        or ai.get('status') != 'completed'
    ):
        raise GoodrichServiceError('OpenAI 검증이 완료되지 않아 TOP 3를 게시하지 않습니다.')

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
        'ranking_owner': 'kis-quant-plus-openai-bounded-decision',
        'ai_role': 'bounded-rerank-and-reject',
        'ordering_enabled': False,
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
    latest_research = read_research_latest()
    if latest_research:
        result['last_research'] = {
            'fetched_at': latest_research.get('fetched_at'),
            'status': latest_research.get('status'),
            'reason': latest_research.get('reason'),
            'reason_text': stand_aside_reason_text(latest_research.get('reason')) if latest_research.get('reason') else None,
            'gates': latest_research.get('gates') or {},
            'scanner_timestamp': latest_research.get('scanner_timestamp'),
        }
        result['watchlist'] = latest_research.get('watchlist') or []
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
        integration={**(integration or {}), 'stand_aside_reason': reason},
    )


def _row_score(row: dict) -> float:
    score = row.get('score')
    if isinstance(score, dict):
        return _safe_float(score.get('total_enriched') or score.get('total'))
    return _safe_float(score)


def build_watchlist(rows: list, trend_lookup: dict | None = None, *, size: int = WATCHLIST_SIZE) -> list:
    """스캐너 순위(점수) 기반 관찰 후보 — 게이트 통과 여부와 무관하게 항상 만든다.

    각 항목에 게이트 실패 사유(`risk_flags`)를 붙여, 왜 TOP 3 로 선정되지 않았는지가
    메시지·화면에서 그대로 보이게 한다. 우선주·비정상 코드만 제외한다.
    """
    from app.services.mirofish.multi_mcp_orchestrator import trend_gate_checks

    trend_lookup = trend_lookup or {}
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('code') or row.get('symbol') or '').strip()
        name = str(row.get('name') or '').strip()
        if len(symbol) != 6 or not symbol.isdigit() or not name or name.endswith(('우', '우B', '우C')):
            continue
        change_pct = _safe_float(row.get('change_pct'))
        trend = trend_lookup.get(symbol) or {}
        checks = trend_gate_checks(trend) if trend else {}
        risk_flags = [k for k, ok in checks.items() if not ok]
        if change_pct <= 0:
            risk_flags.insert(0, 'negative_session')
        out.append({
            'tier': 'watch',
            'symbol': symbol,
            'name': name,
            'price': _safe_float(row.get('price') or row.get('current_price')),
            'change_pct': change_pct,
            'volume': _safe_float(row.get('volume')),
            'score_total': _row_score(row),
            'grade': row.get('grade'),
            'trend_score': _safe_float(trend.get('trend_score')) if trend else None,
            'risk_flags': risk_flags,
        })
    out.sort(key=lambda r: (r['score_total'], r['change_pct']), reverse=True)
    for rank, item in enumerate(out[:size], start=1):
        item['rank'] = rank
    return out[:size]


def _ranked_analyses(deep_research: dict, *, size: int = 3) -> list:
    """멀티 MCP 분석 결과를 승인 여부와 무관하게 portfolio_score 순으로 돌려준다."""
    rows = [r for r in (deep_research.get('agent_analyses') or []) if isinstance(r, dict)]
    rows.sort(key=lambda r: _safe_float(r.get('portfolio_score')), reverse=True)
    return [{
        'symbol': r.get('symbol'), 'name': r.get('name'), 'approved': bool(r.get('approved')),
        'action': r.get('action'), 'confidence': r.get('confidence'),
        'portfolio_score': r.get('portfolio_score'), 'error': r.get('error'),
    } for r in rows[:size]]


def _persist_research(result: dict, *, status: str, reason: str | None) -> None:
    """마지막 research 결과(관찰 후보·게이트 카운트 포함)를 로컬에 남긴다.

    stand-aside 응답에는 Goodrich 서비스 쪽 picks 가 없으므로, 대시보드 GET 이
    여기서 관찰 후보와 "왜 0개였는지"를 읽는다. 실패해도 research 를 막지 않는다.
    """
    try:
        from app.utils.atomic_json import write_json_atomic

        integration = result.get('integration') if isinstance(result.get('integration'), dict) else {}
        write_json_atomic(RESEARCH_LATEST_PATH, {
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'status': status,
            'reason': reason,
            'picks': result.get('picks') or [],
            'watchlist': integration.get('watchlist') or [],
            'gates': integration.get('gates') or {},
            'multi_mcp': integration.get('multi_mcp'),
            'scanner_timestamp': integration.get('scanner_timestamp'),
            'market_status': integration.get('market_status'),
        })
    except Exception:  # noqa: BLE001 — 기록 실패는 검출을 막지 않는다
        pass


def read_research_latest(*, max_age_hours: float = 24) -> dict | None:
    try:
        with open(RESEARCH_LATEST_PATH, encoding='utf-8') as handle:
            data = json.load(handle)
        fetched = datetime.fromisoformat(str(data.get('fetched_at')))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > timedelta(hours=max_age_hours):
            return None
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def stand_aside_reason_text(reason: str | None) -> str:
    return {
        'profit_quality_gate_below_minimum': '등락률>0 · 정상 종목 조건을 통과한 후보가 없음',
        'multi_mcp_cio_approved_below_minimum': '에이전트 CIO 승인(BUY·신뢰도≥60) 통과 후보가 없음',
    }.get(str(reason or ''), str(reason or '선정 기준 미달'))


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
    trend_lookup: dict[str, dict] = {}
    # run_screening(force=True) 는 방금 실행됐다 — 타임스탬프가 비어 있으면 "지금" 이
    # 사실이며, 비워 두면 신선도 게이트가 전 후보를 조용히 탈락시킨다.
    observed_at = screening.get('timestamp') or datetime.now(timezone.utc).isoformat()
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
        if symbol:
            trend_lookup[symbol] = trend
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
            candidates.append({'symbol': symbol, 'name': name})
            candidate_rows.append({
                'symbol': symbol,
                'name': name,
                'price': _safe_float(row.get('price') or row.get('current_price')),
                'change_pct': change_pct,
                'volume': _safe_float(row.get('volume')),
                'source': 'KIS',
                'observed_at': observed_at,
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
        # 항상 존재하는 관찰 후보 + 게이트별 생존 수 (검출 0 과 파이프라인 고장을 구분)
        'watchlist': build_watchlist(rows[:20], trend_lookup),
        'gates': {
            'scanned': len(rows),
            'positive_session': len(candidates),
            'trend_gate_passed': trend_passed_count,
            'profit_gate_passed': None,
            'cio_approved': None,
        },
    }
    if len(candidates) < MINIMUM_PUBLISHABLE_CANDIDATES:
        result = stand_aside_fund_manager(
            reason='profit_quality_gate_below_minimum',
            candidate_count=len(candidates),
            integration=screening_integration,
        )
        _persist_research(result, status='stand_aside', reason='profit_quality_gate_below_minimum')
        return result

    deep_research = run_multi_mcp_analysis(
        candidate_rows,
        use_llm=True,
        max_parallel=3,
    )
    approved_symbols = {
        str(row.get('symbol') or '')
        for row in deep_research.get('selected') or []
        if isinstance(row, dict)
    }
    candidates = [
        candidate for candidate in candidates
        if candidate['symbol'] in approved_symbols
    ]
    screening_integration['gates'].update({
        'profit_gate_passed': deep_research.get('profit_gate_passed_count'),
        'cio_approved': len(candidates),
    })
    if len(candidates) < MINIMUM_PUBLISHABLE_CANDIDATES:
        result = stand_aside_fund_manager(
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
                    'ranked': _ranked_analyses(deep_research),
                },
            },
        )
        _persist_research(result, status='stand_aside', reason='multi_mcp_cio_approved_below_minimum')
        return result

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
            }
            for row in deep_research.get('selected') or []
            if isinstance(row, dict)
        ],
        'cash_wait_reason': deep_research.get('cash_wait_reason'),
        'architecture': deep_research.get('architecture'),
        'input_mode': deep_research.get('input_mode'),
        'publishable_top3': deep_research.get('publishable_top3'),
        'ranked': _ranked_analyses(deep_research),
    }
    result = _request(
        'POST',
        '/v1/fund-manager/research',
        timeout=RESEARCH_TIMEOUT_SECONDS,
        json_body={'candidates': candidates},
        integration={
            **screening_integration,
            'universe_size': len(candidates),
            'multi_mcp': {
                **multi_mcp_snapshot,
                'cio_selected_count': len(candidates),
            },
        },
    )
    _persist_research(result, status='published' if result.get('picks') else 'empty_picks', reason=None)
    return result


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
