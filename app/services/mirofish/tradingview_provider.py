"""Optional TradingView MCP enrichment for MiroFish alpha candidates.

The provider is intentionally fail-open: TradingView is a secondary
confirmation layer, not a required market data source.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
DEFAULT_CACHE_PATHS = (
    os.path.join(DATA_ROOT, 'admin_mirofish', 'tradingview_signals.json'),
    os.path.join(DATA_ROOT, 'tradingview_signals_latest.json'),
)
DEFAULT_TIMEOUT_SEC = 8
DEFAULT_CACHE_TTL_SEC = 900
DEFAULT_SCORE_WEIGHT = 0.12


def get_status(*, include_live: bool = False) -> dict[str, Any]:
    """Return redacted TradingView provider status."""
    config = _config()
    status: dict[str, Any] = {
        'provider': 'tradingview_mcp',
        'mode': config['mode'],
        'enabled': config['enabled'],
        'configured': bool(config['url'] or _existing_cache_path()),
        'mcp_url_configured': bool(config['url']),
        'credentials_present': bool(config['auth_token'] or config['api_key']),
        'cache_path': _redact_path(_cache_path()),
        'cache_available': bool(_existing_cache_path()),
        'cache_ttl_sec': config['cache_ttl_sec'],
        'score_weight': config['score_weight'],
        'live_checked': False,
        'healthy': None,
        'checked_at': _now_iso(),
    }
    if not include_live:
        return status
    status['live_checked'] = True
    if not config['enabled']:
        status.update({'healthy': False, 'error': 'provider_disabled'})
        return status
    if not config['url']:
        status.update({'healthy': False, 'error': 'TRADINGVIEW_MCP_URL missing'})
        return status
    try:
        response = _mcp_request(
            config,
            method='tools/list',
            params={},
            request_id='marketflow-tv-status',
        )
        status.update({
            'healthy': bool(response.get('ok')),
            'status_code': response.get('status_code'),
            'server_error': response.get('error'),
            'tool_count': len(response.get('result', {}).get('tools') or []),
        })
    except Exception as exc:  # pragma: no cover - network dependent.
        status.update({'healthy': False, 'error': f'{type(exc).__name__}: {exc}'})
    return status


def load_enrichment_for_symbols(
    symbols: set[str] | list[str],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Load cached and optionally live TradingView signals keyed by KR symbol."""
    config = _config()
    symbol_list = sorted({_symbol(item) for item in symbols if _symbol(item)})
    cache_payload = _read_cache() if config['enabled'] else None
    signals_by_symbol = _index_signals(cache_payload) if config['enabled'] else {}
    source = 'cache' if signals_by_symbol else 'none'
    live_attempted = False
    live_errors: list[str] = []

    if config['enabled'] and config['url'] and config['live_in_scanner']:
        live_attempted = True
        for symbol in symbol_list[:config['max_live_symbols']]:
            try:
                live = fetch_symbol_signal(symbol)
                if live.get('available'):
                    signals_by_symbol[symbol] = live
                    source = 'mcp_live'
            except Exception as exc:  # pragma: no cover - network dependent.
                live_errors.append(f'{symbol}:{type(exc).__name__}')

    return {
        'provider': 'tradingview_mcp',
        'mode': config['mode'],
        'enabled': config['enabled'],
        'source': source,
        'generated_at': generated_at or _now_iso(),
        'cache_available': bool(cache_payload),
        'live_attempted': live_attempted,
        'live_errors': live_errors[:5],
        'signals_by_symbol': signals_by_symbol,
        'status': get_status(include_live=False),
    }


def fetch_symbol_signal(symbol: str) -> dict[str, Any]:
    """Fetch one TradingView signal through a configurable MCP tool."""
    config = _config()
    clean_symbol = _symbol(symbol)
    if not config['enabled']:
        return {'available': False, 'symbol': clean_symbol, 'error': 'provider_disabled'}
    if not config['url']:
        return {'available': False, 'symbol': clean_symbol, 'error': 'TRADINGVIEW_MCP_URL missing'}
    tv_symbol = _tradingview_symbol(clean_symbol)
    args = {
        'symbol': tv_symbol,
        'exchange': os.getenv('TRADINGVIEW_DEFAULT_EXCHANGE', 'KRX'),
        'market': os.getenv('TRADINGVIEW_DEFAULT_MARKET', 'korea'),
    }
    response = _mcp_request(
        config,
        method='tools/call',
        params={
            'name': config['ta_tool'],
            'arguments': args,
        },
        request_id=f'marketflow-tv-{clean_symbol}',
    )
    if not response.get('ok'):
        return {
            'available': False,
            'symbol': clean_symbol,
            'tradingview_symbol': tv_symbol,
            'error': response.get('error') or f"HTTP {response.get('status_code')}",
        }
    return normalize_signal(response.get('result'), default_symbol=clean_symbol, source='mcp_live')


def score_signal(signal: dict[str, Any] | None, price_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert a TradingView signal into bounded alpha/risk adjustments."""
    if not signal:
        return {'available': False, 'applied': False, 'alpha_delta': 0.0, 'risk_delta': 0.0, 'ranking_delta': 0.0}
    normalized = normalize_signal(signal)
    if not normalized.get('available'):
        return {
            **normalized,
            'applied': False,
            'alpha_delta': 0.0,
            'risk_delta': 0.0,
            'ranking_delta': 0.0,
        }
    freshness = normalized.get('freshness') if isinstance(normalized.get('freshness'), dict) else {}
    if freshness.get('status') == 'stale':
        return {
            **normalized,
            'applied': False,
            'alpha_delta': 0.0,
            'risk_delta': 0.0,
            'ranking_delta': 0.0,
            'reason': 'stale_tradingview_signal',
        }

    recommendation = _recommendation(normalized)
    base = {
        'STRONG_BUY': 7.0,
        'BUY': 4.5,
        'NEUTRAL': 0.0,
        'SELL': -6.5,
        'STRONG_SELL': -9.0,
    }.get(recommendation, 0.0)

    frames = normalized.get('timeframes') or {}
    frame_values = [_clean_recommendation(value) for value in frames.values()]
    buy_frames = sum(1 for value in frame_values if value in {'BUY', 'STRONG_BUY'})
    sell_frames = sum(1 for value in frame_values if value in {'SELL', 'STRONG_SELL'})
    if buy_frames >= 2 and sell_frames == 0:
        base += 2.0
    elif sell_frames >= 1 and buy_frames == 0:
        base -= 2.5
    elif buy_frames and sell_frames:
        base -= 1.5

    relative_volume = _float(normalized.get('relative_volume'))
    if relative_volume >= 1.5:
        base += 1.0
    elif 0 < relative_volume < 0.75:
        base -= 0.8

    trend20 = _float((price_metrics or {}).get('trend_20d_pct'))
    if recommendation in {'BUY', 'STRONG_BUY'} and trend20 > 0:
        base += 0.8
    if recommendation in {'SELL', 'STRONG_SELL'} and trend20 < 0:
        base -= 0.8

    scale = _clamp(_config()['score_weight'] / DEFAULT_SCORE_WEIGHT, 0.25, 2.0)
    alpha_delta = round(_clamp(base * scale, -10.0, 8.0), 2)
    risk_delta = round(_clamp(abs(alpha_delta) * 0.55 if alpha_delta < 0 else -alpha_delta * 0.18, -2.0, 8.0), 2)
    reason_parts = [f'TV {recommendation}']
    if frames:
        reason_parts.append('frames ' + '/'.join(f'{key}:{_clean_recommendation(value)}' for key, value in sorted(frames.items())))
    if relative_volume > 0:
        reason_parts.append(f'RVOL {relative_volume:.2f}x')

    return {
        **normalized,
        'applied': True,
        'recommendation': recommendation,
        'alpha_delta': alpha_delta,
        'risk_delta': risk_delta,
        'ranking_delta': alpha_delta,
        'reason': '; '.join(reason_parts),
    }


def normalize_signal(raw_value: Any, *, default_symbol: str = '', source: str = 'cache') -> dict[str, Any]:
    raw = _unwrap_payload(raw_value)
    if not isinstance(raw, dict):
        return {'available': False, 'symbol': _symbol(default_symbol), 'source': source}
    symbol = _symbol(raw.get('symbol') or raw.get('ticker') or raw.get('code') or default_symbol)
    recommendation = _clean_recommendation(
        raw.get('recommendation')
        or raw.get('signal')
        or raw.get('summary')
        or raw.get('rating')
        or _nested_get(raw, ['technical_summary', 'recommendation'])
        or _nested_get(raw, ['summary', 'recommendation'])
    )
    timeframes = _normalize_timeframes(raw.get('timeframes') or raw.get('intervals') or raw.get('frames'))
    fetched_at = (
        raw.get('fetched_at')
        or raw.get('generated_at')
        or raw.get('updated_at')
        or raw.get('time')
        or raw.get('timestamp')
    )
    freshness = _freshness(fetched_at)
    return {
        'available': bool(symbol and recommendation),
        'provider': 'tradingview_mcp',
        'source': raw.get('source') or source,
        'symbol': symbol,
        'tradingview_symbol': raw.get('tradingview_symbol') or raw.get('tv_symbol') or _tradingview_symbol(symbol),
        'recommendation': recommendation or 'UNKNOWN',
        'timeframes': timeframes,
        'relative_volume': _float(raw.get('relative_volume') or raw.get('rvol')),
        'fetched_at': fetched_at,
        'freshness': freshness,
        'raw_status': raw.get('status'),
    }


def _config() -> dict[str, Any]:
    mode = str(os.getenv('TRADINGVIEW_MCP_MODE', 'disabled')).strip().lower() or 'disabled'
    enabled = mode not in {'0', 'off', 'false', 'disabled', 'none'}
    return {
        'mode': mode,
        'enabled': enabled,
        'url': os.getenv('TRADINGVIEW_MCP_URL', '').strip(),
        'auth_token': os.getenv('TRADINGVIEW_MCP_AUTH_TOKEN', '').strip(),
        'api_key': os.getenv('TRADINGVIEW_MCP_API_KEY', '').strip(),
        'ta_tool': os.getenv('TRADINGVIEW_MCP_TA_TOOL', 'get_ta_summary').strip() or 'get_ta_summary',
        'timeout_sec': _int_env('TRADINGVIEW_MCP_TIMEOUT_SEC', DEFAULT_TIMEOUT_SEC),
        'cache_ttl_sec': _int_env('TRADINGVIEW_CACHE_TTL_SEC', DEFAULT_CACHE_TTL_SEC),
        'score_weight': _float_env('TRADINGVIEW_SCORE_WEIGHT', DEFAULT_SCORE_WEIGHT),
        'live_in_scanner': os.getenv('TRADINGVIEW_LIVE_IN_SCANNER', '').strip().lower() in {'1', 'true', 'yes', 'on'},
        'max_live_symbols': _int_env('TRADINGVIEW_MAX_SCANNER_SYMBOLS', 5),
    }


def _mcp_request(config: dict[str, Any], *, method: str, params: dict[str, Any], request_id: str) -> dict[str, Any]:
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'User-Agent': 'MarketFlow-MiroFish/1.0',
    }
    if config.get('auth_token'):
        headers['Authorization'] = f"Bearer {config['auth_token']}"
    if config.get('api_key'):
        headers['X-API-Key'] = config['api_key']
    response = requests.post(
        config['url'],
        headers=headers,
        json={'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params},
        timeout=max(1, int(config.get('timeout_sec') or DEFAULT_TIMEOUT_SEC)),
    )
    payload: Any = None
    text = response.text[:500]
    try:
        payload = response.json()
    except ValueError:
        payload = {'raw': text}
    if response.status_code >= 400:
        return {'ok': False, 'status_code': response.status_code, 'error': text, 'result': payload}
    if isinstance(payload, dict) and payload.get('error'):
        return {'ok': False, 'status_code': response.status_code, 'error': str(payload.get('error')), 'result': payload}
    return {'ok': True, 'status_code': response.status_code, 'result': (payload or {}).get('result', payload)}


def _read_cache() -> Any:
    path = _existing_cache_path()
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _index_signals(payload: Any) -> dict[str, dict[str, Any]]:
    items: list[Any]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get('signals') or payload.get('data') or payload.get('items') or payload.get('results')
        if isinstance(raw_items, list):
            items = raw_items
        elif isinstance(payload.get('symbols'), dict):
            items = [
                {**value, 'symbol': key} if isinstance(value, dict) else {'symbol': key, 'recommendation': value}
                for key, value in payload['symbols'].items()
            ]
        else:
            items = []
    else:
        items = []
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        signal = normalize_signal(item, source='cache')
        symbol = signal.get('symbol')
        if symbol and signal.get('available'):
            indexed[symbol] = signal
    return indexed


def _cache_path() -> str:
    return os.getenv('TRADINGVIEW_CACHE_PATH', '').strip() or DEFAULT_CACHE_PATHS[0]


def _existing_cache_path() -> str | None:
    configured = os.getenv('TRADINGVIEW_CACHE_PATH', '').strip()
    candidates = (configured,) if configured else DEFAULT_CACHE_PATHS
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _unwrap_payload(raw_value: Any) -> Any:
    value = raw_value
    if isinstance(value, dict) and 'content' in value and isinstance(value.get('content'), list):
        for item in value.get('content') or []:
            text = item.get('text') if isinstance(item, dict) else None
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    continue
    if isinstance(value, dict) and 'structuredContent' in value:
        return value.get('structuredContent')
    if isinstance(value, dict) and 'data' in value and isinstance(value.get('data'), dict):
        return value.get('data')
    return value


def _normalize_timeframes(value: Any) -> dict[str, str]:
    frames: dict[str, str] = {}
    if isinstance(value, dict):
        for key, raw in value.items():
            rec = _clean_recommendation(raw.get('recommendation') if isinstance(raw, dict) else raw)
            if rec:
                frames[str(key).upper()] = rec
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            key = item.get('timeframe') or item.get('interval') or item.get('name')
            rec = _clean_recommendation(item.get('recommendation') or item.get('signal') or item.get('rating'))
            if key and rec:
                frames[str(key).upper()] = rec
    return frames


def _recommendation(signal: dict[str, Any]) -> str:
    value = _clean_recommendation(signal.get('recommendation'))
    if value:
        return value
    frames = signal.get('timeframes') or {}
    frame_values = [_clean_recommendation(item) for item in frames.values()]
    score = sum(2 if item == 'STRONG_BUY' else 1 if item == 'BUY' else -1 if item == 'SELL' else -2 if item == 'STRONG_SELL' else 0 for item in frame_values)
    if score >= 3:
        return 'STRONG_BUY'
    if score > 0:
        return 'BUY'
    if score <= -3:
        return 'STRONG_SELL'
    if score < 0:
        return 'SELL'
    return 'NEUTRAL'


def _clean_recommendation(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get('recommendation') or value.get('signal') or value.get('rating') or value.get('summary')
    text = str(value or '').strip().upper().replace(' ', '_')
    text = text.replace('STRONGBUY', 'STRONG_BUY').replace('STRONGSELL', 'STRONG_SELL')
    if text in {'STRONG_BUY', 'BUY', 'NEUTRAL', 'SELL', 'STRONG_SELL'}:
        return text
    if text in {'BULLISH', 'OUTPERFORM'}:
        return 'BUY'
    if text in {'BEARISH', 'UNDERPERFORM'}:
        return 'SELL'
    return ''


def _symbol(value: Any) -> str:
    text = str(value or '').strip().upper()
    if ':' in text:
        text = text.split(':')[-1]
    if '.' in text:
        text = text.split('.')[0]
    digits = re.sub(r'\D+', '', text)
    return digits.zfill(6)[-6:] if digits else ''


def _tradingview_symbol(symbol: str) -> str:
    clean = _symbol(symbol)
    return f"KRX:{clean}" if clean else ''


def _freshness(value: Any) -> dict[str, Any]:
    age_sec = _age_sec(value)
    ttl = _config()['cache_ttl_sec']
    if age_sec is None:
        return {'status': 'unknown', 'age_sec': None}
    return {'status': 'fresh' if age_sec <= ttl else 'stale', 'age_sec': age_sec}


def _age_sec(value: Any) -> int | None:
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return max(0, int(time.time() - timestamp))
    try:
        text = str(value).replace('Z', '+00:00')
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
    except ValueError:
        return None


def _nested_get(value: Any, path: list[str]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _float(value: Any) -> float:
    try:
        if isinstance(value, str):
            value = value.replace(',', '').replace('%', '')
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_path(path: str) -> str:
    basename = os.path.basename(path or '')
    parent = os.path.basename(os.path.dirname(path or ''))
    return f'.../{parent}/{basename}' if basename else ''
