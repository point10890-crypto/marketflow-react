"""DeepSeek API adapter for MiroFish analysis enrichment.

Numeric alpha/risk scores stay deterministic in the scanner. DeepSeek is used
only to explain and structure the already-computed evidence for operators.
"""

from __future__ import annotations

import json
import os
import html
from datetime import datetime, timezone
from typing import Any

import requests


DEFAULT_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-v4-flash'
DEFAULT_TIMEOUT_SECONDS = 45

DOCS = {
    'chat_completions': 'https://api-docs.deepseek.com/api/create-chat-completion',
    'models': 'https://api-docs.deepseek.com/api/list-models',
    'balance': 'https://api-docs.deepseek.com/api/get-user-balance',
    'pricing': 'https://api-docs.deepseek.com/quick_start/pricing',
}


class DeepSeekError(RuntimeError):
    """Raised when DeepSeek is not configured or returns an unusable response."""


def get_deepseek_status(*, include_live: bool = False) -> dict[str, Any]:
    configured = bool(_api_key())
    status: dict[str, Any] = {
        'provider': 'deepseek',
        'configured': configured,
        'base_url': _base_url(),
        'default_model': _default_model(),
        'recommended_models': ['deepseek-v4-flash', 'deepseek-v4-pro'],
        'supported_endpoints': {
            'chat_completions': '/chat/completions',
            'models': '/models',
            'balance': '/user/balance',
        },
        'project_usage': {
            'scanner_summary': 'Explain deterministic Alpha/Risk candidates in Korean.',
            'deep_dive': 'Summarize local evidence without inventing numeric values.',
            'operator_health': 'Check model availability and account balance before scheduled calls.',
        },
        'docs': DOCS,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }
    if include_live and configured:
        status['models'] = list_models()
        status['balance'] = get_balance()
    return status


def list_models() -> dict[str, Any]:
    return _request_json('GET', '/models')


def get_balance() -> dict[str, Any]:
    return _request_json('GET', '/user/balance')


def summarize_scanner_run(
    run: dict[str, Any],
    *,
    limit: int = 5,
    model: str | None = None,
    thinking: bool = False,
) -> dict[str, Any]:
    candidates = _compact_candidates((run.get('candidates') or [])[:_clean_limit(limit)])
    if not candidates:
        raise DeepSeekError('scanner run has no candidates to summarize')

    payload = {
        'model': model or _default_model(),
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are MiroFish CIO assistant. Explain stock scanner results in Korean. '
                    'Never invent prices, scores, ranks, tickers, or markets. Preserve ticker symbols exactly. '
                    'Use only the JSON candidate data provided by the user.'
                ),
            },
            {
                'role': 'user',
                'content': json.dumps({
                    'task': 'KR stock alpha candidate explanation',
                    'required_language': 'ko',
                    'output_contract': {
                        'summary_title_ko': 'string',
                        'portfolio_note_ko': 'string',
                        'candidates': [
                            {
                                'rank': 'number',
                                'symbol': 'same ticker string from input',
                                'display_name': 'string',
                                'market': 'string',
                                'action_ko': '매수 후보|관찰|제외',
                                'thesis_ko': '1-2 sentence evidence-based thesis',
                                'risk_ko': '1 sentence risk note',
                                'next_check_ko': '1 sentence next validation step',
                            },
                        ],
                    },
                    'scanner_run': {
                        'id': run.get('id'),
                        'generated_at': run.get('generated_at'),
                        'mode': run.get('mode'),
                        'source': run.get('source'),
                        'freshness': run.get('freshness'),
                    },
                    'candidates': candidates,
                }, ensure_ascii=False),
            },
        ],
        'temperature': 0.2,
        'max_tokens': 2200,
        'response_format': {'type': 'json_object'},
        'thinking': {'type': 'enabled' if thinking else 'disabled'},
    }
    if thinking:
        payload['reasoning_effort'] = 'high'

    raw = _request_json('POST', '/chat/completions', payload=payload)
    content = _message_content(raw)
    parsed = _parse_json_content(content)
    return {
        'provider': 'deepseek',
        'model': raw.get('model') or payload['model'],
        'run_id': run.get('id'),
        'candidate_count': len(candidates),
        'thinking': thinking,
        'summary': parsed,
        'usage': raw.get('usage'),
        'finish_reason': _finish_reason(raw),
        'created_at': datetime.now(timezone.utc).isoformat(),
    }


def build_summary_telegram_message(summary_result: dict[str, Any]) -> str:
    summary = summary_result.get('summary') or {}
    title = summary.get('summary_title_ko') or '미로피쉬 DeepSeek 후보 요약'
    note = summary.get('portfolio_note_ko') or ''
    run_id = summary_result.get('run_id') or ''
    model = summary_result.get('model') or ''
    lines = [
        f"<b>{_escape(title)}</b>",
        f"실행 ID: <code>{_escape(run_id)}</code>",
        f"모델: {_escape(model)}",
    ]
    if note:
        lines.append(f"요약: {_escape(note)}")

    candidates = summary.get('candidates') or []
    for item in candidates[:10]:
        if not isinstance(item, dict):
            continue
        lines.extend([
            '',
            (
                f"#{_escape(item.get('rank'))} <b>{_escape(item.get('display_name'))}</b> "
                f"(<code>{_escape(item.get('symbol'))}</code> {_escape(item.get('market'))})"
            ),
            f"판정: <b>{_escape(item.get('action_ko'))}</b>",
            f"핵심: {_escape(item.get('thesis_ko'))}",
            f"리스크: {_escape(item.get('risk_ko'))}",
            f"다음 확인: {_escape(item.get('next_check_ko'))}",
        ])
    usage = summary_result.get('usage') or {}
    if usage:
        lines.append('')
        lines.append(f"토큰: {_escape(usage.get('total_tokens'))}")
    return '\n'.join(lines)


def _request_json(method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise DeepSeekError('DEEPSEEK_API_KEY is not configured')
    url = f"{_base_url().rstrip('/')}/{path.lstrip('/')}"
    timeout = float(os.getenv('DEEPSEEK_TIMEOUT_SECONDS', str(DEFAULT_TIMEOUT_SECONDS)))
    try:
        response = requests.request(
            method,
            url,
            headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise DeepSeekError(f'DeepSeek request failed: {exc}') from exc
    if response.status_code >= 400:
        raise DeepSeekError(f'DeepSeek HTTP {response.status_code}: {response.text[:500]}')
    try:
        data = response.json()
    except ValueError as exc:
        raise DeepSeekError('DeepSeek returned non-JSON response') from exc
    if not isinstance(data, dict):
        raise DeepSeekError('DeepSeek returned unexpected response shape')
    return data


def _compact_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for candidate in candidates:
        price = candidate.get('price') or {}
        evidence = candidate.get('evidence') or []
        compact.append({
            'rank': candidate.get('rank'),
            'symbol': candidate.get('symbol'),
            'display_name': candidate.get('display_name'),
            'market': candidate.get('market'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
            'ranking_score': candidate.get('ranking_score'),
            'action': candidate.get('action'),
            'horizon': candidate.get('horizon'),
            'strategy_tags': candidate.get('strategy_tags') or [],
            'price': {
                'date': price.get('date'),
                'current_price': price.get('current_price'),
                'change_rate': price.get('change_rate'),
                'volume': price.get('volume'),
                'trading_value': price.get('trading_value'),
            },
            'evidence': [
                {
                    'source': item.get('source'),
                    'field': item.get('field'),
                    'score': item.get('score'),
                    'value': item.get('value'),
                }
                for item in evidence[:5]
                if isinstance(item, dict)
            ],
        })
    return compact


def _message_content(raw: dict[str, Any]) -> str:
    choices = raw.get('choices') or []
    if not choices or not isinstance(choices[0], dict):
        raise DeepSeekError('DeepSeek response has no choices')
    message = choices[0].get('message') or {}
    content = message.get('content')
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekError('DeepSeek response has empty content')
    return content.strip()


def _parse_json_content(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekError('DeepSeek response content is not valid JSON') from exc
    if not isinstance(parsed, dict):
        raise DeepSeekError('DeepSeek JSON response must be an object')
    return parsed


def _finish_reason(raw: dict[str, Any]) -> str | None:
    choices = raw.get('choices') or []
    if choices and isinstance(choices[0], dict):
        return choices[0].get('finish_reason')
    return None


def _escape(value: Any) -> str:
    return html.escape(str(value or ''), quote=False)


def _api_key() -> str:
    return os.getenv('DEEPSEEK_API_KEY', '').strip()


def _base_url() -> str:
    return os.getenv('DEEPSEEK_BASE_URL', DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL


def _default_model() -> str:
    return os.getenv('MIROFISH_DEEPSEEK_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _clean_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 5
    return max(1, min(limit, 20))
