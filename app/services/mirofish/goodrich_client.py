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


def _base_url() -> str:
    value = (os.getenv('GOODRICH_API_BASE_URL') or DEFAULT_BASE_URL).strip().rstrip('/')
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
        raise GoodrichServiceError('Goodrich 서비스 주소 설정이 올바르지 않습니다.', status_code=503)
    return value


def _request(method: str, path: str, *, timeout: float) -> dict:
    try:
        response = requests.request(
            method,
            f'{_base_url()}{path}',
            timeout=timeout,
            headers={'Accept': 'application/json'},
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
    return _validate_and_envelope(payload)


def _validate_and_envelope(payload: dict) -> dict:
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
        'universe': 'fixed-6',
        'universe_size': 6,
        'ranking_owner': 'goodrich-deterministic-rules',
        'ai_role': 'verified-explanation-only',
        'ordering_enabled': False,
    }
    return result


def get_fund_manager() -> dict:
    return _request('GET', '/v1/fund-manager', timeout=DEFAULT_TIMEOUT_SECONDS)


def run_research() -> dict:
    return _request('POST', '/v1/fund-manager/research', timeout=RESEARCH_TIMEOUT_SECONDS)
