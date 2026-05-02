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
}


def build_context(target: str) -> dict[str, Any]:
    """Build a live context from MarketFlow output artifacts."""
    resolved = resolve_target(target)
    price = load_price_snapshot(resolved)
    signals = load_signal_snapshots(resolved)
    briefings = load_briefing_snippets(resolved)
    dart = load_dart_snapshot(resolved)

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

    return {
        'target': target,
        'resolved': resolved,
        'price': price,
        'signals': signals,
        'briefings': briefings,
        'dart': dart,
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
    return {'mode': 'live_file_artifacts', 'files': out}


def resolve_target(target: str) -> dict[str, Any]:
    raw = (target or '').strip()
    if not raw:
        raise ValueError('target is required')

    maps = _load_ticker_map()
    lowered = raw.lower().strip()
    compact = re.sub(r'\s+', '', lowered)

    if raw.isdigit():
        symbol = raw.zfill(6)
        meta = maps.get(symbol, {})
        return _resolved(raw, symbol, meta.get('name') or symbol, meta)

    for key, (symbol, name) in _ALIASES.items():
        if key in lowered or key.replace(' ', '') in compact:
            meta = maps.get(symbol, {})
            return _resolved(raw, symbol, meta.get('name') or name, meta)

    for symbol, meta in maps.items():
        name = str(meta.get('name') or '')
        yahoo = str(meta.get('yahoo_ticker') or '')
        if lowered in name.lower() or lowered in yahoo.lower() or compact in re.sub(r'\s+', '', name.lower()):
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
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        if value in (None, ''):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)
