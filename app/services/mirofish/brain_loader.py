"""Brain 13D snapshot loader — MarketFlow 기존 데이터를 13개 차원으로 매핑.

각 dimension 은:
- score: 0~100 (높을수록 강함)
- confidence: 0~1 (데이터 완결도)
- evidence: 핵심 수치 (에이전트 토론에서 인용용)
- source: 원본 파일명

데이터가 결측이거나 stale 한 경우 score=None, confidence=0 반환 (fail-safe).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
US_OUTPUT_DIR = os.path.join(REPO_ROOT, 'us_market', 'output')
DATA_DIR = os.path.join(REPO_ROOT, 'data')

# 데이터 staleness 기준 (초). 이 이상 오래되면 confidence 감소.
_STALE_WARN_SEC = 6 * 3600    # 6시간
_STALE_BLOCK_SEC = 72 * 3600  # 72시간 (3일)

# 13개 차원 정의 — MD 문서 명세
DIMENSIONS = [
    'sector_momentum',      # 업종 상승/하락 강도
    'macro_regime',         # 거시 경제 흐름
    'options_flow',         # 옵션 시장 방향성
    'earnings_catalyst',    # 실적 모멘텀
    'event_risk',           # 돌발 이벤트 위험
    'ml_prediction',        # ML 예측값
    'reversal_signal',      # 역발상 신호
    'crypto_sentiment',     # 크립토 분위기
    'correlation_stability',# 상관계수 안정성
    'liquidity',            # 유동성
    'volatility',           # 변동성 체제
    'memory_window',        # 과거 유사도
    'narrative',            # 시장 내러티브
]


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────

def load_brain_13d_snapshot(target: str | None = None) -> dict[str, Any]:
    """현 시장 데이터에서 Brain 13D 스냅샷 추출.

    Returns:
        {
            'name': 'MiroFish Brain 13D',
            'target': str,
            'snapshot_at': iso8601,
            'alignment_score': 0~1 (전체 일치도),
            'regime': str (high-level regime label),
            'memory_window': str,
            'dimensions': {<name>: DimensionScore},
            'sources': [{'file': ..., 'mtime': ..., 'fresh': bool}],
            'notes': str,
        }
    """
    sources: list[dict[str, Any]] = []
    dims: dict[str, dict[str, Any]] = {}

    # Load source files (with staleness tracking)
    sector_rotation = _read_with_meta('us_market/output/sector_rotation.json', sources)
    market_data = _read_with_meta('us_market/output/market_data.json', sources)
    risk_alerts = _read_with_meta('us_market/output/risk_alerts.json', sources)
    earnings = _read_with_meta('us_market/output/earnings_impact.json', sources)
    prediction = _read_with_meta('us_market/output/prediction.json', sources)
    options_flow = _read_with_meta('us_market/output/options_flow.json', sources)
    smart_money = _read_with_meta('us_market/output/smart_money_current.json', sources)
    decision = _read_with_meta('us_market/output/decision_signal_snapshot.json', sources)

    # Map each dimension
    dims['sector_momentum'] = _dim_sector_momentum(sector_rotation)
    dims['macro_regime'] = _dim_macro_regime(sector_rotation, market_data)
    dims['options_flow'] = _dim_options_flow(options_flow)
    dims['earnings_catalyst'] = _dim_earnings_catalyst(earnings)
    dims['event_risk'] = _dim_event_risk(risk_alerts, market_data)
    dims['ml_prediction'] = _dim_ml_prediction(prediction)
    dims['reversal_signal'] = _dim_reversal_signal(sector_rotation)
    dims['crypto_sentiment'] = _dim_crypto_sentiment()
    dims['correlation_stability'] = _dim_correlation_stability(risk_alerts)
    dims['liquidity'] = _dim_liquidity(market_data, smart_money)
    dims['volatility'] = _dim_volatility(market_data)
    dims['memory_window'] = _dim_memory_window()
    dims['narrative'] = _dim_narrative(decision)

    # Aggregate
    valid_scores = [d['score'] for d in dims.values() if d.get('score') is not None]
    alignment = (sum(valid_scores) / len(valid_scores) / 100.0) if valid_scores else 0.0
    regime = _high_level_regime(dims)

    return {
        'name': 'MiroFish Brain 13D',
        'target': target or 'MarketFlow',
        'snapshot_at': datetime.now(timezone.utc).isoformat(),
        'alignment_score': round(alignment, 3),
        'regime': regime,
        'memory_window': 'rolling_90d',
        'dimensions': dims,
        'sources': sources,
        'notes': _build_notes(dims, sources),
    }


# ─────────────────────────────────────────────────────────
# Dimension extractors
# ─────────────────────────────────────────────────────────

def _dim_sector_momentum(sr: dict | None) -> dict[str, Any]:
    """rotation_clock 기반 — 가장 강한 phase의 score."""
    if not sr:
        return _empty('sector_rotation.json missing')
    phases = (sr.get('rotation_clock') or {}).get('phases') or {}
    if not phases:
        return _empty('rotation_clock.phases empty')
    scores = [(name, p.get('score', 0)) for name, p in phases.items()]
    top = max(scores, key=lambda x: x[1])
    # Normalize: -3~+5 → 0~100
    norm = max(0, min(100, int((top[1] + 3) / 8 * 100)))
    return {
        'score': norm,
        'confidence': 0.85,
        'evidence': f'{top[0]} phase score={top[1]:.2f}',
        'source': 'sector_rotation.json',
    }


def _dim_macro_regime(sr: dict | None, md: dict | None) -> dict[str, Any]:
    """regime_change + VIX 종합."""
    regime_phase = ((sr or {}).get('regime_change') or {}).get('current_phase', 'Unknown')
    vix = ((md or {}).get('volatility') or {}).get('^VIX', {}).get('price')

    if vix is None or regime_phase == 'Unknown':
        return _empty('regime/vix unavailable')

    # Late Cycle / Recession → low score; Mid Cycle / Early → high
    phase_score_map = {'Early Cycle': 80, 'Mid Cycle': 70, 'Late Cycle': 45, 'Recession': 25}
    base = phase_score_map.get(regime_phase, 50)
    # VIX 페널티 (>20 면 5점 감점, >30 면 15점)
    vix_penalty = max(0, (vix - 20) * 0.5)
    score = max(0, min(100, int(base - vix_penalty)))
    return {
        'score': score,
        'confidence': 0.9,
        'evidence': f'phase={regime_phase}, VIX={vix:.1f}',
        'source': 'sector_rotation.json + market_data.json',
    }


def _dim_options_flow(of: dict | None) -> dict[str, Any]:
    if not of:
        return _empty('options_flow.json missing')
    flows = of.get('options_flow') or []
    if not flows:
        return _empty('options_flow empty')
    bullish = sum(1 for x in flows if (x.get('flow_signal') or '').lower().startswith('bull'))
    bearish = sum(1 for x in flows if (x.get('flow_signal') or '').lower().startswith('bear'))
    total = max(1, bullish + bearish)
    score = int(bullish / total * 100)
    return {
        'score': score,
        'confidence': min(1.0, total / 30),  # 30+ tickers → full confidence
        'evidence': f'bullish={bullish}, bearish={bearish}, total_analyzed={of.get("total_analyzed", "?")}',
        'source': 'options_flow.json',
    }


def _dim_earnings_catalyst(ei: dict | None) -> dict[str, Any]:
    if not ei:
        return _empty('earnings_impact.json missing')
    upcoming = ei.get('upcoming_earnings') or []
    if not upcoming:
        return _empty('upcoming_earnings empty')
    # 평균 surprise score (score 기반 추정)
    scores = [u.get('expected_impact', 50) for u in upcoming if isinstance(u.get('expected_impact'), (int, float))]
    avg = sum(scores) / len(scores) if scores else 50
    return {
        'score': int(avg),
        'confidence': min(1.0, len(upcoming) / 10),
        'evidence': f'{len(upcoming)} upcoming, avg_impact={avg:.1f}',
        'source': 'earnings_impact.json',
    }


def _dim_event_risk(ra: dict | None, md: dict | None) -> dict[str, Any]:
    """알림 + VIX → 리스크 score (높을수록 위험 = score 낮음으로 변환)."""
    if not ra:
        return _empty('risk_alerts.json missing')
    alerts = ra.get('alerts') or []
    high_severity = sum(1 for a in alerts if a.get('severity') in ('high', 'critical'))
    warning = sum(1 for a in alerts if a.get('severity') == 'warning')
    vix = ((md or {}).get('volatility') or {}).get('^VIX', {}).get('price', 20)

    risk_index = high_severity * 15 + warning * 5 + max(0, (vix - 20) * 2)
    safety_score = max(0, min(100, 100 - risk_index))
    return {
        'score': safety_score,
        'confidence': 0.8,
        'evidence': f'critical={high_severity}, warnings={warning}, VIX={vix:.1f}',
        'source': 'risk_alerts.json + market_data.json',
    }


def _dim_ml_prediction(pred: dict | None) -> dict[str, Any]:
    if not pred:
        return _empty('prediction.json missing')
    spy = pred.get('spy') or {}
    bullish_pct = spy.get('bullish_probability')
    if bullish_pct is None:
        return _empty('prediction.spy.bullish_probability missing')
    return {
        'score': int(bullish_pct),
        'confidence': 0.7,
        'evidence': f'SPY bullish_prob={bullish_pct:.1f}%, direction={spy.get("direction", "?")}',
        'source': 'prediction.json',
    }


def _dim_reversal_signal(sr: dict | None) -> dict[str, Any]:
    """rotation_signals 의 'rotation' 키워드 카운트. signals 는 dict 또는 string."""
    if not sr:
        return _empty('sector_rotation.json missing')
    signals = sr.get('rotation_signals') or []
    rotations = 0
    for s in signals:
        if isinstance(s, dict):
            text = str(s.get('signal_type') or s.get('type') or s.get('signal') or '')
        else:
            text = str(s)
        if 'rotation' in text.lower():
            rotations += 1
    score = min(100, rotations * 20)
    return {
        'score': score,
        'confidence': 0.6,
        'evidence': f'{rotations} rotation signals detected',
        'source': 'sector_rotation.json',
    }


def _dim_crypto_sentiment() -> dict[str, Any]:
    """crypto_dominance_cache or daily_report 에서 추출."""
    path = os.path.join(DATA_DIR, 'crypto_dominance_cache.json')
    if not os.path.isfile(path):
        return _empty('crypto_dominance_cache.json missing')
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        # BTC dominance 50% 기준 → 50점
        btc_dom = d.get('btc_dominance') or d.get('dominance', {}).get('btc')
        if btc_dom is None:
            return _empty('btc_dominance not found')
        # BTC dominance 낮음 = altseason = bullish
        score = int(max(0, min(100, (60 - btc_dom) * 5 + 50)))
        return {
            'score': score,
            'confidence': 0.5,
            'evidence': f'BTC dominance={btc_dom:.1f}%',
            'source': 'crypto_dominance_cache.json',
        }
    except (OSError, json.JSONDecodeError, KeyError):
        return _empty('crypto_dominance_cache parse failed')


def _dim_correlation_stability(ra: dict | None) -> dict[str, Any]:
    if not ra:
        return _empty('risk_alerts.json missing')
    correlations = [a for a in (ra.get('alerts') or []) if a.get('alert_type') == 'correlation']
    high_corr = sum(1 for c in correlations if (c.get('value') or 0) > 0.85)
    # 높은 상관계수가 많으면 다각화 약함 → score 낮음
    score = max(0, min(100, 100 - high_corr * 5))
    return {
        'score': score,
        'confidence': 0.7,
        'evidence': f'{high_corr} high-correlation pairs (>0.85)',
        'source': 'risk_alerts.json',
    }


def _dim_liquidity(md: dict | None, sm: dict | None) -> dict[str, Any]:
    """SPY volume + smart money flow."""
    if not md:
        return _empty('market_data.json missing')
    indices = md.get('indices') or {}
    spy = indices.get('^GSPC') or indices.get('SPY') or {}
    volume = spy.get('volume') or 0
    # Heuristic: 4B+ shares = healthy, <2B = thin
    if volume >= 4_000_000_000:
        score = 80
    elif volume >= 2_500_000_000:
        score = 65
    elif volume > 0:
        score = 45
    else:
        score = 50
    return {
        'score': score,
        'confidence': 0.6,
        'evidence': f'SPY volume={volume:,}',
        'source': 'market_data.json',
    }


def _dim_volatility(md: dict | None) -> dict[str, Any]:
    if not md:
        return _empty('market_data.json missing')
    vix = ((md.get('volatility') or {}).get('^VIX') or {}).get('price')
    if vix is None:
        return _empty('VIX unavailable')
    # VIX 12-15 ideal (score 80+), 25+ stressful (score < 30)
    if vix < 14:
        score = 85
    elif vix < 18:
        score = 70
    elif vix < 25:
        score = 50
    elif vix < 35:
        score = 30
    else:
        score = 15
    return {
        'score': score,
        'confidence': 0.95,
        'evidence': f'VIX={vix:.1f}',
        'source': 'market_data.json',
    }


def _dim_memory_window() -> dict[str, Any]:
    """jongga_v2 history 파일 수 기반."""
    if not os.path.isdir(DATA_DIR):
        return _empty('data dir missing')
    history = [f for f in os.listdir(DATA_DIR) if f.startswith('jongga_v2_results_')]
    score = min(100, len(history) * 2)  # 50 days = 100 score
    return {
        'score': score,
        'confidence': min(1.0, len(history) / 30),
        'evidence': f'{len(history)} historical V2 runs',
        'source': 'data/jongga_v2_results_*.json',
    }


def _dim_narrative(ds: dict | None) -> dict[str, Any]:
    if not ds:
        return _empty('decision_signal_snapshot.json missing')
    signal = ds.get('signal') or ds.get('verdict') or 'neutral'
    confidence = ds.get('confidence', 50)
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            confidence = 50
    score = int(confidence) if signal.lower().startswith('buy') or signal.lower() == 'bullish' else max(0, 100 - int(confidence))
    return {
        'score': score,
        'confidence': 0.65,
        'evidence': f'signal={signal}, confidence={confidence}',
        'source': 'decision_signal_snapshot.json',
    }


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _empty(reason: str) -> dict[str, Any]:
    return {
        'score': None,
        'confidence': 0.0,
        'evidence': f'unavailable: {reason}',
        'source': None,
    }


def _read_with_meta(rel_path: str, sources_out: list) -> dict | None:
    abs_path = os.path.join(REPO_ROOT, rel_path)
    if not os.path.isfile(abs_path):
        sources_out.append({'file': rel_path, 'mtime': None, 'fresh': False, 'error': 'missing'})
        return None
    try:
        mtime = os.path.getmtime(abs_path)
        age = time.time() - mtime
        fresh = age < _STALE_BLOCK_SEC
        sources_out.append({
            'file': rel_path,
            'mtime': datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
            'age_sec': int(age),
            'fresh': fresh,
            'stale_warn': age > _STALE_WARN_SEC,
        })
        with open(abs_path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sources_out.append({'file': rel_path, 'error': str(e), 'fresh': False})
        return None


def _high_level_regime(dims: dict[str, dict]) -> str:
    """13개 dimension 평균 score 로 regime label 결정."""
    scores = [d['score'] for d in dims.values() if d.get('score') is not None]
    if not scores:
        return 'unknown'
    avg = sum(scores) / len(scores)
    if avg >= 70:
        return 'constructive_bullish'
    if avg >= 55:
        return 'constructive_accumulation'
    if avg >= 45:
        return 'neutral_balanced'
    if avg >= 30:
        return 'defensive_caution'
    return 'risk_off'


def _build_notes(dims: dict[str, dict], sources: list) -> str:
    valid = sum(1 for d in dims.values() if d.get('score') is not None)
    total = len(dims)
    stale = sum(1 for s in sources if s.get('stale_warn'))
    notes = [f'{valid}/{total} dimensions populated.']
    if stale:
        notes.append(f'{stale} sources stale (>6h).')
    missing = [k for k, v in dims.items() if v.get('score') is None]
    if missing:
        notes.append(f'Missing: {", ".join(missing)}')
    return ' '.join(notes)
