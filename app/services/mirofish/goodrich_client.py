"""Boundary client for the separately deployed Goodrich TradingOS service.

Goodrich owns KIS market facts, deterministic ranking, and price levels.
MarketFlow only authenticates access, forwards requests, and validates the
minimum response contract before presenting it to AI Brain subscribers.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


DEFAULT_BASE_URL = 'http://127.0.0.1:8000'
DEFAULT_TIMEOUT_SECONDS = 12.0
RESEARCH_TIMEOUT_SECONDS = 90.0


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

    result = dict(payload)
    result['picks'] = normalized_picks
    result['integration'] = {
        'service': 'goodrich-tradingos',
        'source': 'goodrich-api',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'universe': 'kis-market-leaders',
        'universe_size': len(normalized_picks),
        'ranking_owner': 'goodrich-deterministic-rules',
        'ai_role': 'verified-explanation-only',
        'ordering_enabled': False,
        **(integration or {}),
    }
    return result


def get_fund_manager() -> dict:
    return _request('GET', '/v1/fund-manager', timeout=DEFAULT_TIMEOUT_SECONDS)


def run_research() -> dict:
    from app.services.kis_screener import run_screening

    screening = run_screening(force=True)
    rows = screening.get('results') if isinstance(screening, dict) else None
    if not isinstance(rows, list) or len(rows) < 3:
        raise GoodrichServiceError(
            'KIS 시장 주도주 검출 결과가 3개 미만입니다. 이전 고정 종목으로 대체하지 않습니다.',
            status_code=503,
        )

    candidates = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('code') or row.get('symbol') or '').strip()
        name = str(row.get('name') or '').strip()
        change_pct = _safe_float(row.get('change_pct'))
        score = row.get('score')
        total_score = _safe_float(score.get('total')) if isinstance(score, dict) else _safe_float(score)
        is_preferred = name.endswith('우') or name.endswith('우B') or name.endswith('우C')
        if (
            len(symbol) == 6
            and symbol.isdigit()
            and name
            and not is_preferred
            and change_pct > -2
            and total_score >= 45
        ):
            candidates.append({'symbol': symbol, 'name': name})
    if len(candidates) < 3:
        raise GoodrichServiceError('검증 가능한 KIS 시장 주도주 후보가 3개 미만입니다.', status_code=503)

    return _request(
        'POST',
        '/v1/fund-manager/research',
        timeout=RESEARCH_TIMEOUT_SECONDS,
        json_body={'candidates': candidates},
        integration={
            'source': 'marketflow-kis-leading-scanner',
            'universe': 'live-kospi-kosdaq-leaders',
            'universe_size': len(candidates),
            'candidate_count': len(rows),
            'scanner_timestamp': screening.get('timestamp'),
            'market_status': screening.get('market_status'),
            'ranking_owner': 'marketflow-kis-rules-then-goodrich-quant',
        },
    )


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
