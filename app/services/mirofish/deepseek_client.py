"""DeepSeek API adapter for MiroFish analysis enrichment.

Numeric alpha/risk scores stay deterministic in the scanner. DeepSeek is used
to explain evidence and, when explicitly enabled, to provide a bounded
second-pass quality overlay for candidate ranking.
"""

from __future__ import annotations

import json
import os
import html
import re
from datetime import datetime, timezone
from typing import Any

import requests

from app.services.mirofish import llm_response_cache


DEFAULT_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-v4-pro'
DEFAULT_TIMEOUT_SECONDS = 45
# rerank 는 temperature 0 + 같은 evidence → 같은 판정. 스캐너가 30분 안에 같은 후보 집합으로
# 재실행되면(수동 재실행, 워치독 재기동) 재과금 없이 이전 overlay 를 쓴다.
RERANK_CACHE_TTL_SECONDS = 1800

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
            'scanner_rerank': 'Bounded second-pass quality overlay for already-computed scanner candidates.',
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


def rerank_scanner_candidates(
    candidates: list[dict[str, Any]],
    *,
    run_context: dict[str, Any] | None = None,
    limit: int = 30,
    model: str | None = None,
    max_adjustment: float = 8.0,
    cache_ttl: int | None = RERANK_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    """Return a bounded DeepSeek V4 quality overlay for scanner candidates.

    The model is never allowed to invent new candidates or raw market values.
    Alpha/risk remain deterministic; this function only asks for a small
    confidence adjustment and qualitative risk flags using supplied evidence.

    cache_ttl: 같은 후보 집합(압축된 evidence JSON)·모델·max_adjustment 에 대한 응답을
    ``data/llm_response_cache.db`` 에 보관한다(기본 30분, temperature 0 이라 결정적).
    run_context(generated_at 등)는 키에 넣지 않는다 — 후보 evidence 가 같으면 같은 판정.
    None/0 이면 캐시를 쓰지 않는다.
    """
    compact_candidates = _compact_rerank_candidates(candidates[:_clean_limit(limit, max_value=60)])
    if not compact_candidates:
        raise DeepSeekError('scanner candidate pool is empty')

    clean_max_adjustment = max(0.0, min(float(max_adjustment or 0), 12.0))
    resolved_model = model or _default_model()
    max_tokens = _deepseek_int_env('MIROFISH_DEEPSEEK_RERANK_MAX_TOKENS', 9000, minimum=2000, maximum=16000)

    cache_key = ''
    if cache_ttl is not None and int(cache_ttl) > 0 and not llm_response_cache.is_disabled():
        cache_key = llm_response_cache.make_key(
            'deepseek_rerank_v1', resolved_model, clean_max_adjustment, max_tokens, compact_candidates,
        )
        hit = llm_response_cache.get(cache_key)
        if hit and hit.get('text'):
            try:
                cached = json.loads(hit['text'])
            except ValueError:
                cached = None
            if isinstance(cached, dict) and isinstance(cached.get('overlay'), dict):
                return {**cached, 'cache_hit': True, 'usage': None}

    payload = {
        'model': resolved_model,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are an institutional Korean equity alpha-quality reviewer for MiroFish. '
                    'Review only the supplied scanner candidates. Do not add symbols, prices, scores, '
                    'or facts that are not present in the JSON. Your job is to identify false positives, '
                    'evidence conflicts, and candidates whose evidence quality justifies a small bounded '
                    'ranking adjustment. Preserve ticker symbols exactly.'
                ),
            },
            {
                'role': 'user',
                'content': json.dumps({
                    'task': 'bounded KR stock scanner rerank overlay',
                    'required_language': 'ko',
                    'max_abs_adjustment': clean_max_adjustment,
                    'rules': [
                        'Do not create or remove candidates.',
                        'Use only candidate JSON evidence.',
                        'Return adjustment between -max_abs_adjustment and +max_abs_adjustment.',
                        'Penalize thin liquidity spikes, single-day overextension, stale/missing sources, and evidence conflict.',
                        'Reward multi-source confirmation, capital-flow support, controlled risk, and replay-safe evidence.',
                    ],
                    'output_contract': {
                        'portfolio_note_ko': 'string',
                        'items': [
                            {
                                'symbol': 'same ticker string from input',
                                'deepseek_conviction': 'number 0..100',
                                'ranking_adjustment': f'number between -{clean_max_adjustment} and +{clean_max_adjustment}',
                                'risk_flags': ['string'],
                                'positive_evidence': ['string'],
                                'rationale_ko': 'one concise sentence',
                            },
                        ],
                    },
                    'run_context': run_context or {},
                    'candidates': compact_candidates,
                }, ensure_ascii=False),
            },
        ],
        'temperature': 0.0,
        'max_tokens': max_tokens,
        'response_format': {'type': 'json_object'},
        'thinking': {'type': 'enabled'},
        'reasoning_effort': 'max',
        'user_id': 'marketflow_alpha_scanner',
    }

    raw = _request_json('POST', '/chat/completions', payload=payload)
    content = _message_content(raw)
    parsed = _parse_json_content(content)
    items = parsed.get('items') if isinstance(parsed.get('items'), list) else []
    result = {
        'provider': 'deepseek',
        'model': raw.get('model') or payload['model'],
        'candidate_count': len(compact_candidates),
        'thinking': True,
        'reasoning_effort': 'max',
        'max_abs_adjustment': clean_max_adjustment,
        'overlay': {
            'portfolio_note_ko': parsed.get('portfolio_note_ko') or '',
            'items': items,
        },
        'usage': raw.get('usage'),
        'finish_reason': _finish_reason(raw),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'cache_hit': False,
    }
    if cache_key and items:
        usage = raw.get('usage') if isinstance(raw.get('usage'), dict) else None
        llm_response_cache.put(
            cache_key, provider='deepseek', model=str(result['model']),
            text=json.dumps(result, ensure_ascii=False, default=str),
            usage=usage, ttl=int(cache_ttl or 0),
        )
    return result


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


def _compact_rerank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for candidate in candidates:
        profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
        scorecard = profile.get('profitability_scorecard') if isinstance(profile.get('profitability_scorecard'), dict) else {}
        price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
        entry = candidate.get('entry_plan') if isinstance(candidate.get('entry_plan'), dict) else {}
        compact.append({
            'pool_rank': candidate.get('pool_rank'),
            'symbol': candidate.get('symbol'),
            'display_name': candidate.get('display_name'),
            'market': candidate.get('market'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
            'ranking_score': candidate.get('ranking_score'),
            'action': candidate.get('action'),
            'signal_quality': candidate.get('signal_quality'),
            'strategy_tags': candidate.get('strategy_tags') or [],
            'price': {
                'date': price.get('date'),
                'current_price': price.get('current_price'),
                'change_rate': price.get('change_rate'),
                'volume': price.get('volume'),
                'trading_value': price.get('trading_value'),
            },
            'entry_plan': {
                'entry_zone': entry.get('entry_zone'),
                'stop_loss': entry.get('stop_loss'),
                'risk_note': entry.get('risk_note'),
            },
            'analysis_profile': {
                'source_count': profile.get('source_count'),
                'evidence_quality': profile.get('evidence_quality'),
                'confidence_cap': profile.get('confidence_cap'),
                'capital_flow_confirmation': profile.get('capital_flow_confirmation'),
                'false_signal_gates': profile.get('false_signal_gates'),
                'trend_5d_pct': profile.get('trend_5d_pct'),
                'trend_20d_pct': profile.get('trend_20d_pct'),
                'volume_ratio': profile.get('volume_ratio'),
                'drawdown_20d_pct': profile.get('drawdown_20d_pct'),
                'over_ma20_pct': profile.get('over_ma20_pct'),
                'profitability_scorecard': {
                    'goal_verdict': scorecard.get('goal_verdict'),
                    'confidence_score': scorecard.get('confidence_score'),
                    'hard_blockers': scorecard.get('hard_blockers') or [],
                    'warnings': scorecard.get('warnings') or [],
                },
            },
            'freshness': candidate.get('freshness'),
            'evidence': [
                {
                    'source': item.get('source'),
                    'field': item.get('field'),
                    'score': item.get('score'),
                    'value': item.get('value'),
                    'confidence': item.get('confidence'),
                }
                for item in (candidate.get('evidence') or [])[:8]
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
        extracted = _extract_json_object(content)
        if extracted is None:
            raise DeepSeekError('DeepSeek response content is not valid JSON') from exc
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError as nested_exc:
            raise DeepSeekError('DeepSeek response content is not valid JSON') from nested_exc
    if not isinstance(parsed, dict):
        raise DeepSeekError('DeepSeek JSON response must be an object')
    return parsed


def _extract_json_object(content: str) -> str | None:
    text = str(content or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*```$', '', text)
    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end <= start:
        return None
    return text[start:end + 1]


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


def _deepseek_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _clean_limit(value: Any, *, max_value: int = 20) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 5
    return max(1, min(limit, max(1, int(max_value))))
