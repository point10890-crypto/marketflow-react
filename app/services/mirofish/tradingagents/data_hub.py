"""KR-native data bundle for TradingAgents deep verification.

`gather_bundle(target)` assembles every input the analyst layer needs from a
single entry point. It reuses trusted MiroFish collectors and isolates each
source: any collector that raises is caught, its field falls back to ``{}``,
and the exception string is recorded under ``errors[source]`` so the pipeline
never aborts on a single bad source.

Design note — technical shape:
    `technical` holds the raw `analyze_target_with_levels` result (real vocab:
    trend='bullish'|'neutral'|'bearish', plus `indicators`/`levels`). It is NOT
    normalized here; the analyst layer reads both the real vocab and the
    normalized 'up'/'down'/`ma_aligned` test vocab. A soft failure (result with
    an 'error' key) is treated as a failure → ``{}`` + errors entry.

Contract (LOCKED — later tasks depend on this exact schema):
    {
        'target': str, 'symbol': str|None, 'market': str|None, 'display_name': str,
        'price': dict,        # live_data context['price']
        'corpus': str,        # live_data context['corpus']
        'technical': dict,    # analyze_target_with_levels result, {} on failure
        'rs': dict,           # per-symbol RS entry, {} when unavailable
        'fundamentals': dict, # yfinance info subset + dart snapshot, {} on failure
        'errors': dict,       # {source_name: error_str}
        'brain': dict,        # 엔진 주입 Brain 13D 스냅샷 (기본 {})
    }
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.mirofish import live_data
from app.services.mirofish import sector_rs
from app.services.mirofish import technical_analysis

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')

# yfinance .info keys surfaced into the fundamentals slice.
_YF_INFO_KEYS = (
    'marketCap', 'trailingPE', 'forwardPE', 'priceToBook',
    'returnOnEquity', 'revenueGrowth', 'debtToEquity',
)


def gather_bundle(target: str, *, brain: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the deep-analysis data bundle for one KR target.

    Each source is isolated: a raising collector yields ``{}`` for its field and
    an ``errors[source]`` entry. `live_data.build_context` is called once for
    resolution/price/corpus/dart; the remaining sources run independently.
    """
    errors: dict[str, str] = {}

    # ── live_data: resolution + price + corpus + dart (single call) ──
    try:
        context = live_data.build_context(target) or {}
    except Exception as exc:  # noqa: BLE001 — isolate source failure
        context = {}
        errors['live_data'] = f'{type(exc).__name__}: {exc}'
        logger.warning('[data_hub] build_context failed for %r: %s', target, exc)

    resolved = context.get('resolved') or {}
    symbol = resolved.get('symbol')
    market = resolved.get('market')
    display_name = resolved.get('display_name') or resolved.get('name') or target
    price = context.get('price') or {}
    corpus = context.get('corpus') or ''

    # ── technical: trend + levels ──
    technical: dict[str, Any] = {}
    try:
        result = technical_analysis.analyze_target_with_levels(target) or {}
        if isinstance(result, dict) and result.get('error'):
            errors['technical'] = str(result['error'])
        else:
            technical = result if isinstance(result, dict) else {}
    except Exception as exc:  # noqa: BLE001
        errors['technical'] = f'{type(exc).__name__}: {exc}'
        logger.warning('[data_hub] technical failed for %r: %s', target, exc)

    # ── relative strength (cache-only; never trigger the ~40s CSV pass here) ──
    rs: dict[str, Any] = {}
    try:
        rs = _load_rs_entry(symbol) or {}
    except Exception as exc:  # noqa: BLE001
        errors['rs'] = f'{type(exc).__name__}: {exc}'
        logger.warning('[data_hub] rs lookup failed for %r: %s', symbol, exc)

    # ── fundamentals: yfinance info subset + dart snapshot ──
    fundamentals: dict[str, Any] = {}
    try:
        fundamentals = _load_fundamentals(symbol, market, context) or {}
    except Exception as exc:  # noqa: BLE001
        errors['fundamentals'] = f'{type(exc).__name__}: {exc}'
        logger.warning('[data_hub] fundamentals failed for %r: %s', symbol, exc)

    return {
        'target': target,
        'symbol': symbol,
        'market': market,
        'display_name': display_name,
        'price': price,
        'corpus': corpus,
        'technical': technical,
        'rs': rs,
        'fundamentals': fundamentals,
        'errors': errors,
        'brain': brain or {},   # 외부(엔진) 주입 Brain 13D 스냅샷 pass-through
    }


def bundle_from_evidence_packet(packet: dict[str, Any], *, brain: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the compact deterministic bundle exclusively from a frozen packet."""
    numeric = packet.get('numeric_inputs') or {}
    scores = packet.get('deterministic_scores') or {}
    contents = [source.get('content') for source in packet.get('sources') or []]
    corpus = ' '.join(
        str(content.get('text') if isinstance(content, dict) and 'text' in content else content)
        for content in contents if content
    )
    trend_score = scores.get('trend')
    try:
        trend = 'bullish' if float(trend_score) > 0 else 'bearish' if float(trend_score) < 0 else 'neutral'
    except (TypeError, ValueError):
        trend = 'neutral'
    return {
        'target': packet['name'], 'symbol': packet['symbol'], 'market': packet['market'],
        'display_name': packet['name'],
        'price': {'price': numeric.get('current_price'), 'current_price': numeric.get('current_price'),
                  'change_pct': numeric.get('change_pct'), 'volume': numeric.get('volume'),
                  'date': packet.get('as_of')},
        'corpus': corpus, 'technical': {'trend': trend},
        'rs': {'rs_rating': scores.get('relative_strength')},
        'fundamentals': dict(packet.get('fundamentals') or {}), 'errors': {}, 'brain': brain or {},
        'risk_gates': dict(packet.get('risk_gates') or {}),
    }


def _load_rs_entry(symbol: str | None) -> dict[str, Any]:
    """Return the per-symbol RS entry from the cached artifact (no recompute).

    `allow_compute=False` keeps this cheap: deep verification must not pay the
    universe-wide CSV pass. Missing/stale cache simply yields ``{}``.
    """
    if not symbol:
        return {}
    payload = sector_rs.get_rs_ratings(data_root=DATA_ROOT, allow_compute=False)
    entries = payload.get('entries') if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}
    key = str(symbol).zfill(6)
    entry = entries.get(key) or entries.get(str(symbol))
    return entry if isinstance(entry, dict) else {}


def _load_fundamentals(symbol: str | None, market: str | None,
                       context: dict[str, Any]) -> dict[str, Any]:
    """yfinance `.info` subset for the KR ticker, plus a DART snapshot fallback.

    yfinance failures (ImportError, network) are swallowed so the DART snapshot
    still survives; only an unexpected raise escapes to `gather_bundle`, which
    records it and falls back to ``{}``.
    """
    out: dict[str, Any] = {}

    dart_snapshot = _dart_subset(context)
    if dart_snapshot:
        out['dart'] = dart_snapshot

    if symbol and str(symbol).isdigit():
        suffix = '.KQ' if str(market or '').upper() in ('KOSDAQ', 'KQ') else '.KS'
        info = _yfinance_info(f'{symbol}{suffix}')
        for key in _YF_INFO_KEYS:
            value = info.get(key)
            if value is not None:
                out[key] = value

    return out


def _yfinance_info(yahoo_ticker: str) -> dict[str, Any]:
    """Best-effort yfinance `.info`; empty dict on any failure (import/network)."""
    try:
        import yfinance as yf
    except ImportError:
        logger.info('[data_hub] yfinance not installed — fundamentals dart-only')
        return {}
    try:
        info = yf.Ticker(yahoo_ticker).info
    except Exception as exc:  # noqa: BLE001 — network/parse issues → dart-only
        logger.warning('[data_hub] yfinance info failed for %s: %s', yahoo_ticker, exc)
        return {}
    return info if isinstance(info, dict) else {}


def _dart_subset(context: dict[str, Any]) -> dict[str, Any]:
    """Compact snapshot of the DART filing block from the live context."""
    dart = context.get('dart') if isinstance(context, dict) else None
    if not isinstance(dart, dict) or not dart:
        return {}
    return {
        'latest_year': dart.get('latest_year'),
        'latest': dart.get('latest'),
        'source_file': dart.get('source_file'),
    }
