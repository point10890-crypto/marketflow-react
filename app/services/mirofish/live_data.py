"""Live-data helpers for the admin MiroFish pipeline.

The pipeline is intentionally file-backed because MarketFlow already produces
trusted local artifacts through the scheduler.  This module turns those
artifacts into a compact target context for Brain, GraphRAG, debate, and CIO.
"""

from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / 'data'

_ALIASES: dict[str, tuple[str, str]] = {
    'samsung': ('005930', 'Samsung Electronics'),
    'samsung electronics': ('005930', 'Samsung Electronics'),
    '삼성': ('005930', '삼성전자'),
    '삼성전자': ('005930', '삼성전자'),
    'sk hynix': ('000660', 'SK Hynix'),
    'sk하이닉스': ('000660', 'SK하이닉스'),
    '하이닉스': ('000660', 'SK하이닉스'),
    'naver': ('035420', 'NAVER'),
    '네이버': ('035420', 'NAVER'),
    'kakao': ('035720', 'Kakao'),
    '카카오': ('035720', '카카오'),
    's-oil': ('010950', 'S-Oil'),
    'soil': ('010950', 'S-Oil'),
    '에스오일': ('010950', 'S-Oil'),
    '에쓰오일': ('010950', 'S-Oil'),
}

_CHOSEONG = (
    'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ',
    'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ',
)

_KIS_CACHE_TTL_SECONDS = int(os.getenv('MIROFISH_KIS_CACHE_TTL_SECONDS', '30'))
_kis_cache_lock = threading.Lock()
_kis_snapshot_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def build_context(target: str) -> dict[str, Any]:
    """Build a live context from MarketFlow output artifacts."""
    resolved = resolve_target(target)
    price = load_price_snapshot(resolved)
    signals = load_signal_snapshots(resolved)
    briefings = load_briefing_snippets(resolved)
    dart = load_dart_snapshot(resolved)
    kis = load_kis_snapshot(resolved)
    price = _apply_kis_price(price, kis)

    documents = []
    if price.get('found'):
        documents.append(
            f"{resolved['display_name']} latest cached price is {price.get('price')} "
            f"KRW on {price.get('date')} with {price.get('change_pct')}% change. "
            f"Volume {price.get('volume')}."
        )
    for source_name, item in signals.items():
        if item:
            documents.append(f"{source_name}: {json.dumps(item, ensure_ascii=False)[:1200]}")
    if dart:
        documents.append(f"DART financial snapshot: {json.dumps(dart, ensure_ascii=False)[:1600]}")
    if kis.get('found'):
        documents.extend(_kis_documents(resolved, kis))
    for item in briefings:
        documents.append(f"{item.get('source')}: {item.get('text')}")

    corpus = '\n\n'.join(documents).strip()
    if not corpus:
        corpus = f"No dedicated artifact found for {target}. Use broad MarketFlow Brain state only."

    sources = []
    sources.extend(price.get('sources', []))
    for item in signals.values():
        if item and item.get('source_file'):
            sources.append(item['source_file'])
    for item in briefings:
        if item.get('source_file'):
            sources.append(item['source_file'])
    if dart and dart.get('source_file'):
        sources.append(dart['source_file'])
    sources.extend(kis.get('sources') or [])

    return {
        'target': target,
        'resolved': resolved,
        'price': price,
        'signals': signals,
        'briefings': briefings,
        'dart': dart,
        'kis': kis,
        'corpus': corpus,
        'source_files': sorted(set(sources)),
        'built_at': datetime.now(timezone.utc).isoformat(),
    }


def summarize_data_sources() -> dict[str, Any]:
    """Return health/freshness info for artifacts used by MiroFish."""
    files = [
        DATA_DIR / 'daily_prices.csv',
        DATA_DIR / 'screener_leading_latest.json',
        DATA_DIR / 'jongga_v2_latest.json',
        DATA_DIR / 'vcp_kr_latest.json',
        DATA_DIR / 'kr_ai_analysis.json',
        DATA_DIR / 'kis_token_cache.json',
        DATA_DIR / 'admin_mirofish' / 'ekg.json',
    ]
    out = []
    for path in files:
        if path.exists():
            out.append({
                'file': _rel(path),
                'exists': True,
                'bytes': path.stat().st_size,
                'modified_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            })
        else:
            out.append({'file': _rel(path), 'exists': False})
    return {
        'mode': 'live_file_artifacts',
        'files': out,
        'live_sources': [
            {
                'source': 'KIS API',
                'enabled': _kis_enabled(),
                'configured': _kis_configured(),
                'paper': os.environ.get('KIS_PAPER', 'true').lower() in ('true', '1'),
                'cache_ttl_seconds': _KIS_CACHE_TTL_SECONDS,
            },
        ],
    }


def resolve_target(target: str) -> dict[str, Any]:
    raw = (target or '').strip()
    if not raw:
        raise ValueError('target is required')

    maps = _load_ticker_map()
    lowered = raw.lower().strip()

    if raw.isdigit():
        symbol = raw.zfill(6)
        meta = maps.get(symbol, {})
        return _resolved(raw, symbol, meta.get('name') or symbol, meta)

    for key, (symbol, name) in _ALIASES.items():
        if _matches_target_query(raw, key):
            meta = maps.get(symbol, {})
            return _resolved(raw, symbol, meta.get('name') or name, meta)

    for symbol, meta in maps.items():
        name = str(meta.get('name') or '')
        yahoo = str(meta.get('yahoo_ticker') or '')
        digit_query = re.sub(r'\D+', '', raw)
        if (
            (digit_query and symbol.startswith(digit_query))
            or _matches_target_query(raw, name)
            or _matches_target_query(raw, yahoo)
        ):
            return _resolved(raw, symbol, name or raw, meta)

    return {
        'input': raw,
        'symbol': None,
        'name': raw,
        'display_name': raw,
        'market': 'UNKNOWN',
        'yahoo_ticker': None,
        'asset_type': 'keyword',
    }


def load_price_snapshot(resolved: dict[str, Any]) -> dict[str, Any]:
    symbol = resolved.get('symbol')
    if not symbol:
        return {'found': False, 'sources': []}
    path = DATA_DIR / 'daily_prices.csv'
    if not path.exists():
        return {'found': False, 'sources': []}

    rows: list[dict[str, str]] = []
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            if str(row.get('ticker', '')).zfill(6) == symbol:
                rows.append(row)
    if not rows:
        return {'found': False, 'sources': [_rel(path)]}

    rows.sort(key=lambda r: str(r.get('date') or ''))
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    price = _float(last.get('current_price'))
    prev_price = _float(prev.get('current_price')) if prev else None
    change_pct = _float(last.get('change_rate'))
    if (change_pct is None or abs(change_pct) < 0.000001) and price is not None and prev_price:
        change_pct = (price / prev_price - 1) * 100

    return {
        'found': True,
        'symbol': symbol,
        'name': last.get('name') or resolved.get('display_name'),
        'price': price,
        'change_pct': round(change_pct or 0.0, 3),
        'date': last.get('date'),
        'open': _float(last.get('open')),
        'high': _float(last.get('high')),
        'low': _float(last.get('low')),
        'volume': _int(last.get('volume')),
        'updated_at': last.get('update_time'),
        'sources': [_rel(path)],
    }


def load_signal_snapshots(resolved: dict[str, Any]) -> dict[str, Any]:
    symbol = resolved.get('symbol')
    if not symbol:
        return {}
    return {
        'jongga_v2': _find_in_json_list(DATA_DIR / 'jongga_v2_latest.json', ['signals'], symbol),
        'vcp_kr': _find_in_json_list(DATA_DIR / 'vcp_kr_latest.json', ['signals'], symbol),
        'leading_screener': _find_in_json_list(DATA_DIR / 'screener_leading_latest.json', ['results', 'signals'], symbol),
        'kr_ai_analysis': _find_in_json_list(DATA_DIR / 'kr_ai_analysis.json', ['signals'], symbol),
    }


def load_briefing_snippets(resolved: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    terms = [str(resolved.get('input') or ''), str(resolved.get('name') or ''), str(resolved.get('display_name') or '')]
    if resolved.get('symbol'):
        terms.append(str(resolved['symbol']))
    terms = [t for t in {t.strip() for t in terms} if t]

    root = DATA_DIR / 'briefing'
    if not root.exists():
        return []
    hits: list[dict[str, Any]] = []
    for path in sorted(root.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        chunks = []
        for key in ('title', 'summary', 'content'):
            value = data.get(key)
            if isinstance(value, str):
                chunks.append(value)
        for section in data.get('sections') or []:
            if isinstance(section, dict):
                chunks.extend(str(section.get(k) or '') for k in ('title', 'summary', 'content'))
        text = '\n'.join(chunks)
        if not text:
            continue
        if not any(term.lower() in text.lower() for term in terms):
            continue
        hits.append({
            'source': path.stem,
            'source_file': _rel(path),
            'text': _compact_text(text, 650),
            'modified_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        })
        if len(hits) >= limit:
            break
    return hits


def load_dart_snapshot(resolved: dict[str, Any]) -> dict[str, Any] | None:
    symbol = resolved.get('symbol')
    if not symbol:
        return None
    root = DATA_DIR / 'dart_deep' / 'raw'
    if not root.exists():
        return None
    files = sorted(root.glob(f'{symbol}_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    path = files[0]
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    years = data.get('years') or []
    latest_year = str(max(years)) if years else None
    latest = (data.get('data') or {}).get(latest_year, {}) if latest_year else {}
    return {
        'stock_code': symbol,
        'latest_year': latest_year,
        'latest': latest,
        'source_file': _rel(path),
    }


def load_kis_snapshot(resolved: dict[str, Any]) -> dict[str, Any]:
    """Fetch optional live KIS quote/investor data for a resolved KR equity."""
    symbol = str(resolved.get('symbol') or '').zfill(6)
    if not _kis_enabled():
        return {'source': 'KIS API', 'enabled': False, 'found': False, 'sources': []}
    if not symbol or len(symbol) != 6 or not symbol.isdigit() or not symbol.strip('0'):
        return {'source': 'KIS API', 'enabled': True, 'found': False, 'reason': 'unsupported_target', 'sources': []}

    now = time.time()
    with _kis_cache_lock:
        cached = _kis_snapshot_cache.get(symbol)
        if cached and now - cached[0] < _KIS_CACHE_TTL_SECONDS:
            return {**cached[1], 'cached': True}

    snapshot = _fetch_kis_snapshot_uncached(symbol)
    with _kis_cache_lock:
        _kis_snapshot_cache[symbol] = (now, snapshot)
    return snapshot


def _fetch_kis_snapshot_uncached(symbol: str) -> dict[str, Any]:
    try:
        from app.services import kis_screener
    except Exception as exc:
        return {
            'source': 'KIS API',
            'enabled': True,
            'found': False,
            'error': f'import_failed:{type(exc).__name__}',
            'sources': [],
        }

    if not _kis_configured():
        return {'source': 'KIS API', 'enabled': True, 'found': False, 'error': 'credentials_unavailable', 'sources': []}

    try:
        token = kis_screener.get_token()
        if not token:
            return {'source': 'KIS API', 'enabled': True, 'found': False, 'error': 'token_unavailable', 'sources': []}
        price_detail = kis_screener.fetch_price_detail(token, symbol) or {}
        investor_rows = kis_screener.fetch_investor(token, symbol) or []
        quote = _normalize_kis_quote(symbol, price_detail)
        investor = _normalize_kis_investor(investor_rows)
        sources = []
        if quote:
            sources.append('KIS API: inquire-price')
        if investor:
            sources.append('KIS API: inquire-investor')
        return {
            'source': 'KIS API',
            'enabled': True,
            'found': bool(quote or investor),
            'symbol': symbol,
            'quote': quote,
            'investor': investor,
            'sources': sources,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            'source': 'KIS API',
            'enabled': True,
            'found': False,
            'symbol': symbol,
            'error': type(exc).__name__,
            'sources': [],
            'fetched_at': datetime.now(timezone.utc).isoformat(),
        }


def _normalize_kis_quote(symbol: str, data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or not data:
        return {}
    price = _int(data.get('stck_prpr'))
    if price is None:
        return {}
    return {
        'symbol': symbol,
        'price': price,
        'change': _int(data.get('prdy_vrss')),
        'change_pct': _float(data.get('prdy_ctrt')),
        'open': _int(data.get('stck_oprc')),
        'high': _int(data.get('stck_hgpr')),
        'low': _int(data.get('stck_lwpr')),
        'volume': _int(data.get('acml_vol')),
        'trading_value': _int(data.get('acml_tr_pbmn')),
        'market_cap_eok': _int(data.get('hts_avls')),
        'per': _float(data.get('per')),
        'pbr': _float(data.get('pbr')),
        'eps': _float(data.get('eps')),
        'bps': _float(data.get('bps')),
        'high_52w': _int(data.get('stck_dryy_hgpr')),
        'high_52w_date': data.get('dryy_hgpr_date'),
        'low_52w': _int(data.get('stck_dryy_lwpr')),
        'low_52w_date': data.get('dryy_lwpr_date'),
    }


def _normalize_kis_investor(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        return {}
    today = rows[0] if isinstance(rows[0], dict) else {}
    if not today:
        return {}
    return {
        'foreign_net_qty': _int(today.get('frgn_ntby_qty')),
        'institution_net_qty': _int(today.get('orgn_ntby_qty')),
        'individual_net_qty': _int(today.get('prsn_ntby_qty')),
        'foreign_net_value': _int(today.get('frgn_ntby_tr_pbmn')),
        'institution_net_value': _int(today.get('orgn_ntby_tr_pbmn')),
        'individual_net_value': _int(today.get('prsn_ntby_tr_pbmn')),
    }


def _apply_kis_price(price: dict[str, Any], kis: dict[str, Any]) -> dict[str, Any]:
    quote = kis.get('quote') if isinstance(kis, dict) else None
    if not isinstance(quote, dict) or quote.get('price') is None:
        return price
    merged = dict(price or {})
    merged.update({
        'found': True,
        'source': 'kis_api',
        'symbol': quote.get('symbol') or merged.get('symbol'),
        'price': quote.get('price'),
        'change_pct': quote.get('change_pct') if quote.get('change_pct') is not None else merged.get('change_pct', 0),
        'open': quote.get('open'),
        'high': quote.get('high'),
        'low': quote.get('low'),
        'volume': quote.get('volume'),
        'trading_value': quote.get('trading_value'),
        'market_cap_eok': quote.get('market_cap_eok'),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'updated_at': kis.get('fetched_at'),
    })
    merged['sources'] = sorted(set((price or {}).get('sources', []) + (kis.get('sources') or [])))
    return merged


def _kis_documents(resolved: dict[str, Any], kis: dict[str, Any]) -> list[str]:
    display = resolved.get('display_name') or resolved.get('name') or resolved.get('symbol') or 'target'
    quote = kis.get('quote') or {}
    investor = kis.get('investor') or {}
    docs: list[str] = []
    if quote:
        docs.append(
            f"KIS API live quote for {display} ({quote.get('symbol')}): "
            f"price {quote.get('price')} KRW, change {quote.get('change')} KRW "
            f"({quote.get('change_pct')}%), intraday open/high/low "
            f"{quote.get('open')}/{quote.get('high')}/{quote.get('low')}, "
            f"volume {quote.get('volume')}, trading value {quote.get('trading_value')}, "
            f"market cap {quote.get('market_cap_eok')} eok KRW, "
            f"52-week high/low {quote.get('high_52w')}/{quote.get('low_52w')}."
        )
    if investor:
        docs.append(
            f"KIS API investor flow for {display}: foreign net quantity "
            f"{investor.get('foreign_net_qty')}, institution net quantity "
            f"{investor.get('institution_net_qty')}, individual net quantity "
            f"{investor.get('individual_net_qty')}."
        )
    return docs


def _kis_enabled() -> bool:
    return os.getenv('MIROFISH_USE_KIS', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def _kis_configured() -> bool:
    return bool(os.getenv('KIS_APP_KEY') and os.getenv('KIS_APP_SECRET'))


def _matches_target_query(query: str, candidate: str) -> bool:
    q = str(query or '').strip()
    c = str(candidate or '').strip()
    if not q or not c:
        return False

    q_lower = q.lower()
    c_lower = c.lower()
    q_compact = re.sub(r'\s+', '', q_lower)
    c_compact = re.sub(r'\s+', '', c_lower)
    q_lookup = _normalize_lookup(q)
    c_lookup = _normalize_lookup(c)

    if q_lower in c_lower or q_compact in c_compact:
        return True
    if q_lookup and c_lookup and q_lookup in c_lookup:
        return True

    q_initials = _hangul_initials(q)
    c_initials = _hangul_initials(c)
    return bool(q_initials and c_initials and _is_initial_query(q_initials) and q_initials in c_initials)


def _normalize_lookup(value: str) -> str:
    return re.sub(r'[^0-9a-z가-힣ㄱ-ㅎ]+', '', str(value or '').lower())


def _hangul_initials(value: str) -> str:
    out: list[str] = []
    for char in str(value or '').strip():
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            out.append(_CHOSEONG[(code - 0xAC00) // 588])
        elif 'ㄱ' <= char <= 'ㅎ':
            out.append(char)
        elif char.isascii() and char.isalnum():
            out.append(char.lower())
    return ''.join(out)


def _is_initial_query(value: str) -> bool:
    return bool(value) and all('ㄱ' <= char <= 'ㅎ' for char in value)


def _load_ticker_map() -> dict[str, dict[str, str]]:
    candidates = [REPO_ROOT / 'ticker_to_yahoo_map.csv', DATA_DIR / 'ticker_to_yahoo_map.csv']
    for path in candidates:
        if not path.exists():
            continue
        out: dict[str, dict[str, str]] = {}
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                symbol = str(row.get('ticker') or '').zfill(6)
                if not symbol.strip('0'):
                    continue
                out[symbol] = {
                    'market': str(row.get('market') or ''),
                    'yahoo_ticker': str(row.get('yahoo_ticker') or ''),
                    'name': str(row.get('name') or symbol),
                }
        return out
    return {}


def _resolved(raw: str, symbol: str, name: str, meta: dict[str, str]) -> dict[str, Any]:
    return {
        'input': raw,
        'symbol': symbol,
        'name': name,
        'display_name': name,
        'market': meta.get('market') or 'KR',
        'yahoo_ticker': meta.get('yahoo_ticker') or f'{symbol}.KS',
        'asset_type': 'equity',
    }


def _find_in_json_list(path: Path, keys: list[str], symbol: str) -> dict[str, Any] | None:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    candidates: list[Any] = []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    for item in candidates:
        if not isinstance(item, dict):
            continue
        code = str(item.get('stock_code') or item.get('ticker') or item.get('symbol') or item.get('code') or '').zfill(6)
        if code == symbol:
            out = dict(item)
            out['source_file'] = _rel(path)
            return out
    return None


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _compact_text(text: str, max_len: int) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= max_len else text[:max_len - 1] + '…'


def _float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        if isinstance(value, str):
            value = value.replace(',', '')
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        if value in (None, ''):
            return None
        if isinstance(value, str):
            value = value.replace(',', '')
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)
