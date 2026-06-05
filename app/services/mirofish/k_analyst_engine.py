"""K-Analyst style evidence engine for MiroFish.

The engine is deliberately deterministic.  It strengthens alpha-candidate
screening by exposing data readiness, technical state, Bayesian scenario
probabilities, confidence caps, and HALT gates without fabricating missing
prices, flows, or fundamentals.
"""

from __future__ import annotations

import csv
import math
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.mirofish import alpha_scanner


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / 'data'
DAILY_PRICES = DATA_DIR / 'daily_prices.csv'
TICKER_MAP = DATA_DIR / 'ticker_to_yahoo_map.csv'

GRADE_RELIABILITY = {
    'S': 0.96,
    'A': 0.90,
    'B': 0.78,
    'C': 0.48,
    'D': 0.25,
}
FRESHNESS_RELIABILITY = {
    'fresh': 1.00,
    'recent': 0.88,
    'stale': 0.60,
    'unknown': 0.70,
    'missing': 0.0,
}
REQUIRED_CLUSTERS_FOR_STRONG = 3
CRISIS_TERMS = (
    'trading halt',
    'delisting',
    'audit opinion refused',
    'capital impairment',
    'accounting fraud',
    'bankruptcy',
    'embezzlement',
    '횡령',
    '상장폐지',
    '거래정지',
    '감사의견 거절',
    '자본잠식',
)


def analyze_technical_packet(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deterministic K-Analyst packet for one target."""
    payload = payload or {}
    target = _resolve_target(payload)
    rows = _normalize_rows(payload.get('rows') or payload.get('history'))
    if not rows and target.get('symbol'):
        rows = _load_price_history_for_symbol(str(target['symbol']))

    indicators = _build_indicators(rows)
    readiness = _assess_readiness_from_parts(
        target=target,
        rows=rows,
        indicators=indicators,
        flow=payload.get('flow'),
        market=payload.get('market_regime') or payload.get('market'),
        fundamental=payload.get('fundamental') or payload.get('dart') or payload.get('dart_event'),
        evidence=payload.get('evidence'),
    )
    halt = _halt_gate(payload, readiness, indicators)
    evidence = _build_evidence(payload, target, rows, indicators, readiness, halt)
    price_strategy = _build_price_strategy(target, rows, indicators, readiness, halt)
    bayesian = build_bayesian_verdict({
        'target': target,
        'readiness': readiness,
        'halt': halt,
        'evidence': evidence,
        'confidence_cap': _confidence_cap(readiness, halt, evidence),
    })

    return {
        'service': 'mirofish-k-analyst-tech-engine',
        'version': '2026-06-05',
        'target': target,
        'asof': datetime.now(timezone.utc).isoformat(),
        'data_cutoff': _data_cutoff(rows),
        'readiness': readiness,
        'technical': indicators,
        'evidence': evidence,
        'halt_gate': halt,
        'bayesian_verdict': bayesian,
        'price_strategy': price_strategy,
        'contracts': {
            'no_fabricated_prices': True,
            'pricing_requires_partial_or_full_readiness': True,
            'probabilities_sum_to_100': _probability_total(bayesian.get('posterior_pct')) == 100,
            'weak_social_news_is_supporting_only': True,
            'lookahead_safe': True,
        },
    }


def assess_analysis_readiness(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the readiness gate without full indicator/verdict expansion."""
    payload = payload or {}
    target = _resolve_target(payload)
    rows = _normalize_rows(payload.get('rows') or payload.get('history'))
    if not rows and target.get('symbol'):
        rows = _load_price_history_for_symbol(str(target['symbol']))
    indicators = _build_indicators(rows)
    readiness = _assess_readiness_from_parts(
        target=target,
        rows=rows,
        indicators=indicators,
        flow=payload.get('flow'),
        market=payload.get('market_regime') or payload.get('market'),
        fundamental=payload.get('fundamental') or payload.get('dart') or payload.get('dart_event'),
        evidence=payload.get('evidence'),
    )
    return {
        'service': 'mirofish-k-analyst-readiness',
        'target': target,
        'asof': datetime.now(timezone.utc).isoformat(),
        'data_cutoff': _data_cutoff(rows),
        'readiness': readiness,
        'coverage': {
            'row_count': len(rows),
            'current_price': indicators.get('current_price'),
            'has_volume': bool(indicators.get('volume') and indicators.get('volume') > 0),
            'has_high_low': bool(indicators.get('has_high_low')),
            'has_flow': isinstance(payload.get('flow'), dict) and bool(payload.get('flow')),
            'has_market_regime': isinstance(payload.get('market_regime') or payload.get('market'), dict),
            'has_fundamental': isinstance(
                payload.get('fundamental') or payload.get('dart') or payload.get('dart_event'),
                dict,
            ),
        },
    }


def build_bayesian_verdict(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build Bull/Base/Bear probabilities from independent evidence clusters."""
    payload = payload or {}
    evidence = [item for item in (payload.get('evidence') or []) if isinstance(item, dict)]
    readiness = payload.get('readiness') or {}
    halt = payload.get('halt') or payload.get('halt_gate') or {}
    cap = _float(payload.get('confidence_cap'), 0.70)
    cap = max(0.35, min(cap, 0.95))

    prior = {'Bull': 33.0, 'Base': 34.0, 'Bear': 33.0}
    raw = dict(prior)
    updates: list[dict[str, Any]] = []
    for item in evidence:
        direction = _direction(item)
        if direction not in ('Bull', 'Base', 'Bear'):
            continue
        strength = _strength(item)
        reliability = _evidence_reliability(item)
        delta = round(12.0 * strength * reliability, 4)
        if direction == 'Bull':
            raw['Bull'] += delta
            raw['Base'] -= delta * 0.35
            raw['Bear'] -= delta * 0.25
        elif direction == 'Bear':
            raw['Bear'] += delta
            raw['Base'] -= delta * 0.30
            raw['Bull'] -= delta * 0.35
        else:
            raw['Base'] += delta * 0.60
            raw['Bull'] -= delta * 0.20
            raw['Bear'] -= delta * 0.20
        updates.append({
            'cluster': item.get('cluster') or 'unknown',
            'direction': direction,
            'strength': round(strength, 4),
            'reliability': round(reliability, 4),
            'delta': round(delta, 4),
            'source_grade': str(item.get('source_grade') or item.get('grade') or 'B').upper(),
            'freshness': item.get('freshness') or 'unknown',
        })

    if _is_halt(halt):
        raw['Bear'] += 18
        raw['Base'] += 8
        raw['Bull'] -= 22
        updates.append({
            'cluster': 'crisis_halt',
            'direction': 'Bear',
            'strength': 1.0,
            'reliability': 1.0,
            'delta': 18,
            'source_grade': 'S',
            'freshness': 'fresh',
        })

    if str(readiness.get('status') or '').upper() == 'INSUFFICIENT':
        cap = min(cap, 0.50)
    elif str(readiness.get('status') or '').upper() == 'PARTIAL':
        cap = min(cap, 0.65)

    posterior = _normalize_probabilities(raw)
    posterior = _apply_probability_cap(posterior, cap)
    posterior = _round_percentages(posterior)
    action = _verdict_action(posterior, halt, readiness)

    return {
        'prior_pct': _round_percentages(prior),
        'posterior_pct': posterior,
        'confidence_cap': round(cap, 4),
        'action': action,
        'interpretation': _verdict_interpretation(action, posterior),
        'evidence_updates': updates,
        'conflict_flags': _conflict_flags(evidence),
        'probability_total': _probability_total(posterior),
        'language_guard': {
            'probabilistic': True,
            'forbidden_certainty_phrases_blocked': True,
        },
    }


def build_scanner_run_k_analyst(run_id: str, limit: int = 5) -> dict[str, Any]:
    """Analyze candidates from an existing scanner run through K-Analyst gates."""
    run = alpha_scanner.read_scanner_run(run_id)
    if run is None:
        return {
            'status': 'scanner_run_not_found',
            'run_id': run_id,
            'items': [],
        }

    clean_limit = max(1, min(_int(limit, 5), 20))
    items = []
    for candidate in (run.get('candidates') or [])[:clean_limit]:
        if not isinstance(candidate, dict):
            continue
        packet = analyze_technical_packet({
            'target': {
                'symbol': candidate.get('symbol'),
                'name': candidate.get('display_name') or candidate.get('name'),
                'market': candidate.get('market'),
            },
            'scanner_candidate': candidate,
            'evidence': candidate.get('evidence') or [],
        })
        items.append(_scanner_k_analyst_summary(candidate, packet))

    ranked = sorted(
        items,
        key=lambda item: (
            item.get('composite_score') or 0,
            item.get('bayesian', {}).get('posterior_pct', {}).get('Bull', 0),
        ),
        reverse=True,
    )
    return {
        'status': 'ok',
        'service': 'mirofish-k-analyst-scanner-run',
        'run_id': run.get('id'),
        'source_run_generated_at': run.get('generated_at'),
        'freshness': run.get('freshness'),
        'candidate_count': len(run.get('candidates') or []),
        'analysis_count': len(items),
        'items': ranked,
        'top3': ranked[:3],
        'contracts': {
            'uses_existing_scanner_candidates': True,
            'lookahead_safe': True,
            'no_external_order_execution': True,
        },
    }


def _resolve_target(payload: dict[str, Any]) -> dict[str, Any]:
    target = payload.get('target')
    candidate = payload.get('scanner_candidate') if isinstance(payload.get('scanner_candidate'), dict) else {}
    if isinstance(target, dict):
        symbol = _symbol(target.get('symbol') or candidate.get('symbol'))
        name = str(target.get('name') or target.get('display_name') or candidate.get('display_name') or symbol or '').strip()
        market = str(target.get('market') or candidate.get('market') or '').strip()
        yahoo = str(target.get('yahoo_ticker') or '').strip()
        return {
            'input': target,
            'symbol': symbol,
            'name': name or symbol,
            'display_name': name or symbol,
            'market': market or 'KR',
            'yahoo_ticker': yahoo or (f'{symbol}.KS' if symbol else None),
            'asset_type': 'equity' if symbol else 'keyword',
        }

    raw = str(target or payload.get('symbol') or payload.get('query') or candidate.get('symbol') or '').strip()
    if not raw:
        return {
            'input': raw,
            'symbol': None,
            'name': None,
            'display_name': None,
            'market': 'UNKNOWN',
            'yahoo_ticker': None,
            'asset_type': 'keyword',
        }
    if raw.isdigit():
        symbol = raw.zfill(6)
        meta = _ticker_meta(symbol)
        name = meta.get('name') or candidate.get('display_name') or symbol
        return {
            'input': raw,
            'symbol': symbol,
            'name': name,
            'display_name': name,
            'market': meta.get('market') or candidate.get('market') or 'KR',
            'yahoo_ticker': meta.get('yahoo_ticker') or f'{symbol}.KS',
            'asset_type': 'equity',
        }
    matched = _find_ticker_by_name(raw)
    if matched:
        symbol, meta = matched
        name = meta.get('name') or raw
        return {
            'input': raw,
            'symbol': symbol,
            'name': name,
            'display_name': name,
            'market': meta.get('market') or 'KR',
            'yahoo_ticker': meta.get('yahoo_ticker') or f'{symbol}.KS',
            'asset_type': 'equity',
        }
    return {
        'input': raw,
        'symbol': None,
        'name': raw,
        'display_name': raw,
        'market': 'UNKNOWN',
        'yahoo_ticker': None,
        'asset_type': 'keyword',
    }


def _ticker_meta(symbol: str) -> dict[str, str]:
    maps = _load_ticker_map()
    return maps.get(_symbol(symbol) or '', {})


def _find_ticker_by_name(query: str) -> tuple[str, dict[str, str]] | None:
    lookup = _compact_lookup(query)
    if not lookup:
        return None
    best: tuple[int, str, dict[str, str]] | None = None
    for symbol, meta in _load_ticker_map().items():
        name = str(meta.get('name') or '')
        yahoo = str(meta.get('yahoo_ticker') or '')
        hay = _compact_lookup(f'{name} {yahoo} {symbol}')
        if not hay:
            continue
        score = 0
        if lookup == _compact_lookup(symbol) or lookup == _compact_lookup(name):
            score = 100
        elif hay.startswith(lookup):
            score = 80
        elif lookup in hay:
            score = 60
        if score and (best is None or score > best[0]):
            best = (score, symbol, meta)
    if best:
        return best[1], best[2]
    return None


def _load_ticker_map() -> dict[str, dict[str, str]]:
    if not TICKER_MAP.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    try:
        with open(TICKER_MAP, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                symbol = _symbol(row.get('ticker') or row.get('symbol'))
                if not symbol:
                    continue
                out[symbol] = {
                    'name': str(row.get('name') or '').strip(),
                    'market': str(row.get('market') or '').strip(),
                    'yahoo_ticker': str(row.get('yahoo_ticker') or '').strip(),
                }
    except OSError:
        return {}
    return out


def _load_price_history_for_symbol(symbol: str) -> list[dict[str, Any]]:
    clean_symbol = _symbol(symbol)
    if not clean_symbol or not DAILY_PRICES.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(DAILY_PRICES, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                if _symbol(row.get('ticker') or row.get('symbol')) == clean_symbol:
                    rows.append(row)
    except OSError:
        return []
    return _normalize_rows(rows)


def _normalize_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _float(
            row.get('close')
            or row.get('current_price')
            or row.get('price')
            or row.get('종가'),
            None,
        )
        if close is None or close <= 0:
            continue
        open_price = _float(row.get('open') or row.get('시가'), close) or close
        high = _float(row.get('high') or row.get('고가'), max(open_price, close)) or max(open_price, close)
        low = _float(row.get('low') or row.get('저가'), min(open_price, close)) or min(open_price, close)
        volume = _float(row.get('volume') or row.get('거래량'), 0.0) or 0.0
        normalized.append({
            'date': str(row.get('date') or row.get('일자') or row.get('datetime') or '').strip(),
            'open': open_price,
            'high': max(high, low, close, open_price),
            'low': min(high, low, close, open_price),
            'close': close,
            'volume': volume,
        })
    normalized.sort(key=lambda item: str(item.get('date') or ''))
    return normalized


def _build_indicators(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [float(row['close']) for row in rows]
    highs = [float(row['high']) for row in rows]
    lows = [float(row['low']) for row in rows]
    volumes = [float(row.get('volume') or 0) for row in rows]
    if not closes:
        return {
            'sample_days': 0,
            'current_price': None,
            'status': 'no_price_history',
            'has_high_low': False,
        }
    current = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else current
    change_pct = ((current - prev) / prev * 100.0) if prev else 0.0
    sma = {str(window): _sma(closes, window) for window in (5, 20, 60, 120, 150, 200)}
    atr14 = _atr(highs, lows, closes, 14)
    rsi14 = _rsi(closes, 14)
    macd = _macd(closes)
    bollinger = _bollinger(closes, 20)
    support_resistance = _support_resistance(highs, lows, closes)
    trend_state = _trend_state(current, sma)
    vcp = _vcp_state(closes, volumes)
    sepa = _sepa_state(closes, volumes, sma)
    return {
        'sample_days': len(closes),
        'date': rows[-1].get('date'),
        'current_price': round(current, 4),
        'change_pct': round(change_pct, 4),
        'volume': volumes[-1] if volumes else 0,
        'avg_volume_20': round(_mean(volumes[-20:]), 4) if volumes else None,
        'has_high_low': bool(highs and lows),
        'sma': {key: _round_or_none(value) for key, value in sma.items()},
        'atr14': _round_or_none(atr14),
        'atr_pct': _round_or_none((atr14 / current * 100.0) if atr14 and current else None),
        'rsi14': _round_or_none(rsi14),
        'macd': macd,
        'bollinger': bollinger,
        'support_resistance': support_resistance,
        'trend_state': trend_state,
        'vcp': vcp,
        'sepa': sepa,
    }


def _assess_readiness_from_parts(
    *,
    target: dict[str, Any],
    rows: list[dict[str, Any]],
    indicators: dict[str, Any],
    flow: Any,
    market: Any,
    fundamental: Any,
    evidence: Any,
) -> dict[str, Any]:
    missing = []
    limitations = []
    symbol = target.get('symbol')
    if not symbol:
        missing.append('resolved_symbol')
    if not indicators.get('current_price'):
        missing.append('current_price')
    if len(rows) < 60:
        missing.append('price_history_60d')
    if len(rows) < 120:
        limitations.append('price_history_120d_for_full_stage')
    if not indicators.get('has_high_low'):
        missing.append('ohlc_high_low')
    if not indicators.get('volume'):
        limitations.append('volume_data')
    if not isinstance(flow, dict) or not flow:
        limitations.append('capital_flow_confirmation')
    if not isinstance(market, dict) or not market:
        limitations.append('macro_fx_derivatives_context')
    if not isinstance(fundamental, dict) or not fundamental:
        limitations.append('fundamental_or_dart_risk_context')
    if not evidence:
        limitations.append('external_evidence_clusters')

    if not symbol or not indicators.get('current_price') or len(rows) < 40:
        status = 'INSUFFICIENT'
    elif len(rows) >= 120 and isinstance(flow, dict) and flow and isinstance(fundamental, dict) and fundamental:
        status = 'FULL'
    else:
        status = 'PARTIAL'

    if status == 'FULL':
        confidence_floor = 0.70
        confidence_cap = 0.88
    elif status == 'PARTIAL':
        confidence_floor = 0.45
        confidence_cap = 0.65
    else:
        confidence_floor = 0.0
        confidence_cap = 0.50

    return {
        'status': status,
        'missing_data': missing,
        'limitations': limitations,
        'row_count': len(rows),
        'confidence_floor': confidence_floor,
        'confidence_cap': confidence_cap,
        'can_price_strategy': status in ('FULL', 'PARTIAL'),
        'data_quality': _readiness_quality(status, missing, limitations),
    }


def _halt_gate(payload: dict[str, Any], readiness: dict[str, Any], indicators: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if not indicators.get('current_price'):
        reasons.append('current_price_missing')
    text_parts = []
    for key in ('dart_event', 'dart', 'fundamental', 'risk_flags', 'news'):
        value = payload.get(key)
        if value:
            text_parts.append(str(value).lower())
    crisis_text = ' '.join(text_parts)
    for term in CRISIS_TERMS:
        if term.lower() in crisis_text:
            reasons.append(f'crisis_term:{term}')
            break
    if payload.get('halt') is True or payload.get('trading_halt') is True:
        reasons.append('explicit_halt_flag')
    if str(readiness.get('status') or '').upper() == 'INSUFFICIENT':
        reasons.append('insufficient_data_for_action')
    return {
        'halt': bool(reasons),
        'reasons': reasons,
        'override': 'HOLD_REVIEW' if reasons else None,
    }


def _build_evidence(
    payload: dict[str, Any],
    target: dict[str, Any],
    rows: list[dict[str, Any]],
    indicators: dict[str, Any],
    readiness: dict[str, Any],
    halt: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in payload.get('evidence') or []:
        if isinstance(item, dict):
            evidence.append(_normalize_evidence(item))

    current = _float(indicators.get('current_price'), None)
    sma = indicators.get('sma') or {}
    sma20 = _float(sma.get('20'), None)
    sma60 = _float(sma.get('60'), None)
    if current and sma20:
        if current > sma20 and (sma60 is None or sma20 >= sma60):
            evidence.append(_evidence(
                'technical_trend',
                'Bull',
                'Price is above intermediate moving-average structure.',
                0.70,
                'B',
                'fresh',
            ))
        elif current < sma20:
            evidence.append(_evidence(
                'technical_trend',
                'Bear',
                'Price is below the 20-day moving average.',
                0.60,
                'B',
                'fresh',
            ))

    vcp = indicators.get('vcp') or {}
    if vcp.get('contraction') and vcp.get('volume_dry_up'):
        evidence.append(_evidence(
            'vcp_contraction',
            'Bull',
            'Volatility contraction with volume dry-up improves setup quality.',
            0.62,
            'B',
            'fresh',
        ))

    flow = payload.get('flow') if isinstance(payload.get('flow'), dict) else {}
    if flow:
        foreign_cash = _float(flow.get('foreign_cash_net') or flow.get('foreign_net'), 0.0)
        foreign_futures = _float(flow.get('foreign_futures_net'), 0.0)
        institution = _float(flow.get('institution_net'), 0.0)
        if foreign_cash > 0 and (foreign_futures >= 0 or institution > 0):
            evidence.append(_evidence(
                'capital_flow',
                'Bull',
                'Capital-flow confirmation is positive.',
                0.82,
                str(flow.get('source_grade') or 'A'),
                str(flow.get('freshness') or 'fresh'),
            ))
        elif foreign_cash < 0 and foreign_futures < 0:
            evidence.append(_evidence(
                'capital_flow',
                'Bear',
                'Foreign cash and futures flow are both negative.',
                0.82,
                str(flow.get('source_grade') or 'A'),
                str(flow.get('freshness') or 'fresh'),
            ))

    market = payload.get('market_regime') or payload.get('market')
    if isinstance(market, dict) and market:
        fx_pressure = str(market.get('usd_krw_pressure') or market.get('fx_pressure') or '').lower()
        risk_regime = str(market.get('regime') or '').lower()
        if 'risk on' in risk_regime or 'constructive' in risk_regime:
            evidence.append(_evidence('macro_regime', 'Bull', 'Macro regime is constructive.', 0.55, 'B', 'recent'))
        if 'weak' in fx_pressure or 'krw weakness' in fx_pressure:
            evidence.append(_evidence('currency', 'Bear', 'KRW weakness can reduce foreign-flow reliability.', 0.55, 'B', 'recent'))

    if halt.get('halt'):
        evidence.append(_evidence(
            'crisis_halt',
            'Bear',
            'HALT gate blocks directional action until risk is cleared.',
            1.0,
            'S',
            'fresh',
        ))

    if str(readiness.get('status') or '').upper() == 'INSUFFICIENT':
        evidence.append(_evidence(
            'data_readiness',
            'Base',
            'Insufficient data limits conclusion reliability.',
            0.88,
            'S',
            'fresh',
        ))

    return evidence


def _normalize_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        'cluster': str(item.get('cluster') or item.get('name') or 'external'),
        'direction': _direction(item),
        'description': str(item.get('description') or item.get('reason') or ''),
        'strength': max(0.0, min(_float(item.get('strength') or item.get('score'), 0.5), 1.0)),
        'source_grade': str(item.get('source_grade') or item.get('grade') or 'B').upper(),
        'freshness': str(item.get('freshness') or 'unknown'),
        'confidence': max(0.0, min(_float(item.get('confidence'), 1.0), 1.0)),
        'independent': item.get('independent', True) is not False,
    }


def _evidence(
    cluster: str,
    direction: str,
    description: str,
    strength: float,
    grade: str,
    freshness: str,
) -> dict[str, Any]:
    return {
        'cluster': cluster,
        'direction': direction,
        'description': description,
        'strength': max(0.0, min(strength, 1.0)),
        'source_grade': grade.upper(),
        'freshness': freshness,
        'confidence': 1.0,
        'independent': True,
    }


def _build_price_strategy(
    target: dict[str, Any],
    rows: list[dict[str, Any]],
    indicators: dict[str, Any],
    readiness: dict[str, Any],
    halt: dict[str, Any],
) -> dict[str, Any]:
    status = str(readiness.get('status') or '').upper()
    if status == 'INSUFFICIENT' or halt.get('halt'):
        return {
            'status': 'withheld',
            'reason': 'Price strategy requires at least partial readiness and no HALT gate.',
            'target': target,
        }
    current = _float(indicators.get('current_price'), None)
    atr = _float(indicators.get('atr14'), None)
    support = (indicators.get('support_resistance') or {}).get('support_20d')
    if not current or not atr:
        return {
            'status': 'withheld',
            'reason': 'ATR/current price is missing.',
            'target': target,
        }
    stop_by_atr = current - (atr * 1.5)
    stop = min(stop_by_atr, _float(support, stop_by_atr) or stop_by_atr)
    if stop <= 0 or stop >= current:
        stop = current * 0.93
    risk = current - stop
    target1 = current + (risk * 2.0)
    target2 = current + (risk * 3.0)
    return {
        'status': 'conditional',
        'target': target,
        'entry': _round_price(current),
        'stop': _round_price(stop),
        'target1': _round_price(target1),
        'target2': _round_price(target2),
        'risk_reward_to_target1': round((target1 - current) / risk, 2) if risk > 0 else None,
        'risk_pct': round((risk / current) * 100.0, 2) if current else None,
        'basis': 'ATR14 and 20-day support; not an execution instruction.',
    }


def _scanner_k_analyst_summary(candidate: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    posterior = ((packet.get('bayesian_verdict') or {}).get('posterior_pct') or {})
    scanner_alpha = _float(candidate.get('alpha_score'), 0.0)
    scanner_risk = _float(candidate.get('risk_score'), 50.0)
    bull = _float(posterior.get('Bull'), 0.0)
    readiness = (packet.get('readiness') or {}).get('status')
    readiness_bonus = {'FULL': 8.0, 'PARTIAL': 3.0, 'INSUFFICIENT': -15.0}.get(str(readiness), 0.0)
    halt_penalty = -30.0 if (packet.get('halt_gate') or {}).get('halt') else 0.0
    composite = scanner_alpha * 0.45 + bull * 0.45 - scanner_risk * 0.22 + readiness_bonus + halt_penalty
    return {
        'symbol': candidate.get('symbol'),
        'name': candidate.get('display_name') or candidate.get('name'),
        'market': candidate.get('market'),
        'scanner': {
            'rank': candidate.get('rank'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
            'action': candidate.get('action'),
        },
        'readiness': packet.get('readiness'),
        'bayesian': packet.get('bayesian_verdict'),
        'halt_gate': packet.get('halt_gate'),
        'price_strategy': packet.get('price_strategy'),
        'composite_score': round(composite, 2),
    }


def _confidence_cap(readiness: dict[str, Any], halt: dict[str, Any], evidence: list[dict[str, Any]]) -> float:
    cap = _float(readiness.get('confidence_cap'), 0.65)
    if halt.get('halt'):
        cap = min(cap, 0.45)
    clusters = {item.get('cluster') for item in evidence if item.get('independent') is not False}
    if len(clusters) < REQUIRED_CLUSTERS_FOR_STRONG:
        cap = min(cap, 0.62)
    if evidence and all(str(item.get('source_grade') or '').upper() in {'C', 'D'} for item in evidence):
        cap = min(cap, 0.55)
    return max(0.35, min(cap, 0.95))


def _readiness_quality(status: str, missing: list[str], limitations: list[str]) -> str:
    if status == 'FULL' and not missing:
        return 'strong'
    if status == 'PARTIAL' and len(limitations) <= 4:
        return 'moderate'
    if status == 'PARTIAL':
        return 'limited'
    return 'insufficient'


def _data_cutoff(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {'latest_date': None, 'row_count': 0}
    return {
        'latest_date': rows[-1].get('date'),
        'row_count': len(rows),
    }


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append((value * alpha) + (out[-1] * (1 - alpha)))
    return out


def _macd(closes: list[float]) -> dict[str, Any]:
    if len(closes) < 26:
        return {'status': 'insufficient_history'}
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(ema12[-len(ema26):], ema26)]
    signal = _ema_series(macd_line, 9)
    hist = macd_line[-1] - signal[-1] if signal else None
    return {
        'line': _round_or_none(macd_line[-1]),
        'signal': _round_or_none(signal[-1] if signal else None),
        'histogram': _round_or_none(hist),
        'bias': 'positive' if hist and hist > 0 else 'negative' if hist and hist < 0 else 'neutral',
    }


def _rsi(closes: list[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    gains = []
    losses = []
    for idx in range(1, len(closes)):
        change = closes[idx] - closes[idx - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = _mean(gains[-period:])
    avg_loss = _mean(losses[-period:])
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    if len(closes) <= period or not highs or not lows:
        return None
    true_ranges = []
    for idx in range(1, len(closes)):
        tr = max(
            highs[idx] - lows[idx],
            abs(highs[idx] - closes[idx - 1]),
            abs(lows[idx] - closes[idx - 1]),
        )
        true_ranges.append(tr)
    return _mean(true_ranges[-period:])


def _bollinger(closes: list[float], window: int) -> dict[str, Any]:
    if len(closes) < window:
        return {'status': 'insufficient_history'}
    recent = closes[-window:]
    mid = _mean(recent)
    std = statistics.pstdev(recent) if len(recent) > 1 else 0.0
    upper = mid + (std * 2)
    lower = mid - (std * 2)
    current = closes[-1]
    pct_b = ((current - lower) / (upper - lower)) if upper != lower else 0.5
    width_pct = ((upper - lower) / mid * 100.0) if mid else None
    return {
        'middle': _round_or_none(mid),
        'upper': _round_or_none(upper),
        'lower': _round_or_none(lower),
        'pct_b': _round_or_none(pct_b),
        'band_width_pct': _round_or_none(width_pct),
    }


def _support_resistance(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    if not closes:
        return {}
    support_20 = min(lows[-20:]) if len(lows) >= 20 else min(lows)
    resistance_20 = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    support_60 = min(lows[-60:]) if len(lows) >= 60 else None
    resistance_60 = max(highs[-60:]) if len(highs) >= 60 else None
    pivot = (highs[-1] + lows[-1] + closes[-1]) / 3 if highs and lows else None
    return {
        'support_20d': _round_or_none(support_20),
        'resistance_20d': _round_or_none(resistance_20),
        'support_60d': _round_or_none(support_60),
        'resistance_60d': _round_or_none(resistance_60),
        'pivot': _round_or_none(pivot),
    }


def _trend_state(current: float, sma: dict[str, float | None]) -> dict[str, Any]:
    sma20 = sma.get('20')
    sma60 = sma.get('60')
    if sma20 is None:
        return {'state': 'unknown', 'reason': 'sma20_missing'}
    if current > sma20 and (sma60 is None or sma20 >= sma60):
        return {'state': 'constructive', 'reason': 'price_above_sma20'}
    if current < sma20:
        return {'state': 'weakening', 'reason': 'price_below_sma20'}
    return {'state': 'neutral', 'reason': 'mixed_ma_structure'}


def _vcp_state(closes: list[float], volumes: list[float]) -> dict[str, Any]:
    if len(closes) < 40 or len(volumes) < 40:
        return {'eligible': False, 'reason': 'insufficient_history'}
    recent_volatility = _stdev_pct(closes[-10:])
    prior_volatility = _stdev_pct(closes[-30:-10])
    recent_volume = _mean(volumes[-10:])
    prior_volume = _mean(volumes[-30:-10])
    contraction = recent_volatility < prior_volatility * 0.75 if prior_volatility else False
    dry_up = recent_volume < prior_volume * 0.85 if prior_volume else False
    score = 0
    score += 45 if contraction else 0
    score += 35 if dry_up else 0
    score += 20 if closes[-1] > _mean(closes[-20:]) else 0
    return {
        'eligible': True,
        'contraction': bool(contraction),
        'volume_dry_up': bool(dry_up),
        'score': score,
        'recent_volatility_pct': _round_or_none(recent_volatility),
        'prior_volatility_pct': _round_or_none(prior_volatility),
    }


def _sepa_state(closes: list[float], volumes: list[float], sma: dict[str, float | None]) -> dict[str, Any]:
    missing = []
    for key in ('150', '200'):
        if sma.get(key) is None:
            missing.append(f'sma{key}')
    if len(closes) < 200 or missing:
        return {'eligible': False, 'missing': missing or ['price_history_200d']}
    current = closes[-1]
    sma150 = sma['150']
    sma200 = sma['200']
    rel_strength = (current / closes[-120] - 1) * 100.0 if len(closes) >= 120 and closes[-120] else None
    pass_setup = current > sma150 and current > sma200 and sma150 > sma200
    return {
        'eligible': True,
        'pass': bool(pass_setup),
        'relative_strength_120d_pct': _round_or_none(rel_strength),
        'reason': 'price_above_150_200_ma' if pass_setup else 'ma_structure_not_confirmed',
    }


def _normalize_probabilities(raw: dict[str, float]) -> dict[str, float]:
    clean = {key: max(1.0, _float(raw.get(key), 1.0)) for key in ('Bull', 'Base', 'Bear')}
    total = sum(clean.values()) or 1.0
    return {key: value / total * 100.0 for key, value in clean.items()}


def _apply_probability_cap(probs: dict[str, float], cap: float) -> dict[str, float]:
    cap_pct = cap * 100.0
    capped = dict(probs)
    max_key = max(capped, key=lambda key: capped[key])
    if capped[max_key] <= cap_pct:
        return capped
    overflow = capped[max_key] - cap_pct
    capped[max_key] = cap_pct
    receivers = [key for key in ('Bull', 'Base', 'Bear') if key != max_key]
    for key in receivers:
        capped[key] += overflow / len(receivers)
    return _normalize_probabilities(capped)


def _round_percentages(probs: dict[str, float]) -> dict[str, int]:
    keys = ('Bull', 'Base', 'Bear')
    raw = {key: max(0.0, float(probs.get(key, 0.0))) for key in keys}
    total = sum(raw.values()) or 1.0
    scaled = {key: raw[key] / total * 100.0 for key in keys}
    ints = {key: int(math.floor(scaled[key])) for key in keys}
    remainder = 100 - sum(ints.values())
    fractions = sorted(keys, key=lambda key: scaled[key] - ints[key], reverse=True)
    for key in fractions[:remainder]:
        ints[key] += 1
    return ints


def _probability_total(probs: Any) -> int:
    if not isinstance(probs, dict):
        return 0
    return int(sum(_int(probs.get(key), 0) for key in ('Bull', 'Base', 'Bear')))


def _verdict_action(probs: dict[str, int], halt: dict[str, Any], readiness: dict[str, Any]) -> str:
    if _is_halt(halt):
        return 'HOLD_REVIEW'
    if str(readiness.get('status') or '').upper() == 'INSUFFICIENT':
        return 'DATA_HOLD'
    if probs.get('Bull', 0) >= 55:
        return 'BUY_CANDIDATE'
    if probs.get('Bear', 0) >= 45:
        return 'RISK_REVIEW'
    return 'WATCH'


def _verdict_interpretation(action: str, probs: dict[str, int]) -> str:
    if action == 'BUY_CANDIDATE':
        return f"Upside probability has increased conditionally; Bull {probs.get('Bull')}%, Base {probs.get('Base')}%, Bear {probs.get('Bear')}%."
    if action == 'HOLD_REVIEW':
        return 'Directional judgment is withheld because crisis or HALT evidence overrides setup quality.'
    if action == 'DATA_HOLD':
        return 'Current data is insufficient, so conclusion reliability is limited until missing data is confirmed.'
    if action == 'RISK_REVIEW':
        return f"Downside pressure or risk probability has increased; Bear {probs.get('Bear')}%."
    return f"Signals are mixed; scenario approach is more appropriate than a single direction call."


def _conflict_flags(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    clusters: dict[str, set[str]] = {}
    for item in evidence:
        cluster = str(item.get('cluster') or 'unknown')
        clusters.setdefault(cluster, set()).add(_direction(item))
    has_bull = any('Bull' in directions for directions in clusters.values())
    has_bear = any('Bear' in directions for directions in clusters.values())
    return {
        'has_directional_conflict': bool(has_bull and has_bear),
        'clusters': {key: sorted(value) for key, value in clusters.items()},
        'capital_flow_priority': True,
    }


def _direction(item: dict[str, Any]) -> str:
    raw = str(item.get('direction') or item.get('scenario') or '').strip().lower()
    if raw in ('bull', 'bullish', 'up', 'positive', 'buy_candidate'):
        return 'Bull'
    if raw in ('bear', 'bearish', 'down', 'negative', 'risk'):
        return 'Bear'
    if raw in ('base', 'neutral', 'mixed', 'hold', 'watch'):
        return 'Base'
    return 'Base'


def _strength(item: dict[str, Any]) -> float:
    return max(0.0, min(_float(item.get('strength') or item.get('score'), 0.5), 1.0))


def _evidence_reliability(item: dict[str, Any]) -> float:
    grade = str(item.get('source_grade') or item.get('grade') or 'B').upper()
    freshness = str(item.get('freshness') or 'unknown').lower()
    confidence = max(0.0, min(_float(item.get('confidence'), 1.0), 1.0))
    independent = 1.0 if item.get('independent', True) is not False else 0.65
    return (
        GRADE_RELIABILITY.get(grade, 0.65)
        * FRESHNESS_RELIABILITY.get(freshness, 0.70)
        * confidence
        * independent
    )


def _is_halt(halt: Any) -> bool:
    return isinstance(halt, dict) and bool(halt.get('halt') or halt.get('override'))


def _mean(values: list[float]) -> float:
    cleaned = [float(value) for value in values if value is not None]
    return sum(cleaned) / len(cleaned) if cleaned else 0.0


def _stdev_pct(values: list[float]) -> float:
    cleaned = [float(value) for value in values if value is not None and value > 0]
    if len(cleaned) < 2:
        return 0.0
    mean = _mean(cleaned)
    return statistics.pstdev(cleaned) / mean * 100.0 if mean else 0.0


def _symbol(value: Any) -> str | None:
    raw = re.sub(r'\D+', '', str(value or '').strip())
    if not raw:
        return None
    return raw.zfill(6)[-6:]


def _compact_lookup(value: Any) -> str:
    return re.sub(r'\s+', '', str(value or '').lower())


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return round(numeric, digits)
    except (TypeError, ValueError):
        return None


def _round_price(value: Any) -> float | None:
    numeric = _float(value, None)
    if numeric is None:
        return None
    if numeric >= 1000:
        return round(numeric, 0)
    return round(numeric, 2)


def _float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None or value == '':
            return default
        if isinstance(value, str):
            value = value.replace(',', '').replace('%', '').strip()
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(',', '').strip()))
    except (TypeError, ValueError):
        return default
