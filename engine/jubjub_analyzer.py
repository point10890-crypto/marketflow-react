"""줍줍이 분석기 — W 패턴 + 저점 매수 시그널 통합.

W 패턴 검출 결과(`screener.json`)를 기반으로:
  1) 줍줍 점수 (0-100) 계산
  2) 매수/1차목표/2차목표/손절 가격 자동 산출
  3) R/R 비율 계산
  4) 상태 뱃지 결정 (진입 임박 / 매수 타이밍 / 막 돌파 / 늦음)

가장 중요한 입력 (best_pattern):
  - pattern_class: 'W' (Bullish) 만 줍줍 대상, 'M' 제외
  - confidence: 0-100
  - completion_pct: 0-100
  - neckline_price: 넥라인 가격
  - neckline_distance_pct: 현재가 대비 (음수=아래, 양수=위)
  - volume_confirmed: boolean
  - points: [{date, price, type: 'trough'|'peak'}, ...]
"""

from __future__ import annotations

from typing import Any


def compute_jubjub(signal: dict[str, Any]) -> dict[str, Any] | None:
    """단일 signal → 줍줍 분석 결과.

    Returns None if signal isn't a valid W (Bullish) candidate.
    """
    if not isinstance(signal, dict):
        return None
    best = signal.get('best_pattern') or {}
    if not isinstance(best, dict):
        return None
    # 줍줍은 Bullish (W) 만
    if str(best.get('pattern_class', '')).upper() != 'W':
        return None

    current_price = _safe_float(signal.get('price'))
    neckline = _safe_float(best.get('neckline_price'))
    confidence = _safe_float(best.get('confidence'))
    completion = _safe_float(best.get('completion_pct'))
    neckline_dist_pct = _safe_float(best.get('neckline_distance_pct'))
    volume_confirmed = bool(best.get('volume_confirmed'))
    bullish_bias = _safe_float(best.get('bullish_bias'))
    points = best.get('points') if isinstance(best.get('points'), list) else []

    if current_price <= 0 or neckline <= 0:
        return None

    # ─── 매수/목표/손절 가격 산출 ─────────────────────────────────
    trough_prices = [
        _safe_float(p.get('price')) for p in points
        if isinstance(p, dict) and str(p.get('type', '')).lower() in {'trough', 'low', 'support'}
    ]
    trough_prices = [x for x in trough_prices if x > 0]
    # 가장 최근 두 trough (없으면 fallback)
    recent_troughs = sorted(trough_prices, reverse=True)[-2:] if len(trough_prices) >= 2 else trough_prices
    avg_trough = sum(recent_troughs) / len(recent_troughs) if recent_troughs else current_price * 0.95
    second_trough = recent_troughs[-1] if recent_troughs else avg_trough

    pattern_depth = max(0.0, neckline - avg_trough)

    entry_price = round(neckline * 1.005, 2)         # 넥라인 +0.5% 돌파 확인 후
    target_1 = round(neckline + pattern_depth * 1.0, 2)
    target_2 = round(neckline + pattern_depth * 1.5, 2)
    stop_price = round(second_trough * 0.99, 2)      # 두 번째 저점 -1%

    # R/R 계산
    risk = entry_price - stop_price
    reward_1 = target_1 - entry_price
    reward_2 = target_2 - entry_price
    rr_1 = round(reward_1 / risk, 2) if risk > 0 else None
    rr_2 = round(reward_2 / risk, 2) if risk > 0 else None

    # ─── 줍줍 점수 (0-100) ─────────────────────────────────────
    # 1) 패턴 신뢰도 (40%)
    score_conf = confidence * 0.40

    # 2) 완성도 (20%)
    score_complete = completion * 0.20

    # 3) 넥라인 근접도 (20%) — -0.5 ~ +0.5% 가 만점, 멀거나 늦으면 감점
    proximity = _proximity_score(neckline_dist_pct) * 20.0

    # 4) 거래량 확인 (10%)
    score_volume = (10.0 if volume_confirmed else 0.0)

    # 5) Bullish bias (10%)
    score_bias = bullish_bias * 10.0

    jubjub_score = round(min(100.0, score_conf + score_complete + proximity + score_volume + score_bias), 1)

    # ─── 상태 뱃지 ─────────────────────────────────────────────
    badge = _badge(neckline_dist_pct, jubjub_score)

    # ─── 별 등급 ─────────────────────────────────────────────
    stars = 3 if jubjub_score >= 80 else 2 if jubjub_score >= 70 else 1 if jubjub_score >= 60 else 0

    return {
        'ticker': signal.get('ticker'),
        'name': signal.get('name'),
        'market': signal.get('market'),
        'current_price': current_price,
        'pattern_class': 'W',
        'wave_type': best.get('wave_type'),
        'wave_label': best.get('wave_label'),
        'confidence': confidence,
        'completion_pct': completion,
        'neckline_price': neckline,
        'neckline_distance_pct': neckline_dist_pct,
        'volume_confirmed': volume_confirmed,
        # 줍줍 핵심
        'jubjub_score': jubjub_score,
        'jubjub_stars': stars,
        'jubjub_badge': badge['code'],          # 'imminent' | 'buy_now' | 'breakout' | 'late' | 'watching'
        'jubjub_badge_label_ko': badge['label'],
        'jubjub_badge_tone': badge['tone'],     # 'amber' | 'emerald' | 'rose' | 'slate'
        # 매매 계획
        'trade_plan': {
            'entry_price': entry_price,
            'target_1': target_1,
            'target_2': target_2,
            'stop_price': stop_price,
            'entry_pct': round((entry_price / current_price - 1) * 100, 2) if current_price > 0 else None,
            'target_1_pct': round((target_1 / current_price - 1) * 100, 2) if current_price > 0 else None,
            'target_2_pct': round((target_2 / current_price - 1) * 100, 2) if current_price > 0 else None,
            'stop_pct': round((stop_price / current_price - 1) * 100, 2) if current_price > 0 else None,
            'rr_1': rr_1,
            'rr_2': rr_2,
            'pattern_depth': round(pattern_depth, 2),
            'second_trough': round(second_trough, 2),
        },
        # 점수 분해 (UI 디버깅용)
        'score_breakdown': {
            'confidence': round(score_conf, 1),
            'completion': round(score_complete, 1),
            'proximity': round(proximity, 1),
            'volume': round(score_volume, 1),
            'bias': round(score_bias, 1),
        },
    }


def filter_and_sort_jubjub(
    signals: list[dict[str, Any]],
    *,
    min_score: float = 60.0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Signals → 줍줍 결과 list, 점수 ≥ min_score, 점수 내림차순."""
    result: list[dict[str, Any]] = []
    for s in signals or []:
        j = compute_jubjub(s)
        if j and j['jubjub_score'] >= min_score:
            result.append(j)
    result.sort(key=lambda r: r['jubjub_score'], reverse=True)
    return result[:max(1, min(limit, 200))]


# ─── 내부 헬퍼 ───────────────────────────────────────────────


def _safe_float(v: Any) -> float:
    try:
        if v is None or v == '':
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _proximity_score(distance_pct: float) -> float:
    """넥라인 근접도 → 0..1 점수.

    - distance -0.5% ~ +0.5%  → 1.0 (만점, 돌파 직전)
    - distance -2%   ~ -0.5%  → 0.7 (접근 중)
    - distance +0.5% ~ +3%    → 0.6 (막 돌파, 추격 OK)
    - distance < -2%          → 0.4 (아직 멀음)
    - distance > +3%          → 0.1 (너무 늦음)
    """
    d = distance_pct
    if -0.5 <= d <= 0.5:
        return 1.0
    if -2.0 <= d < -0.5:
        return 0.7
    if 0.5 < d <= 3.0:
        return 0.6
    if d < -2.0:
        return 0.4
    return 0.1  # d > 3.0


def _badge(distance_pct: float, jubjub_score: float) -> dict[str, str]:
    """상태 뱃지 결정."""
    d = distance_pct
    if d > 3.0:
        return {'code': 'late', 'label': '추격 위험', 'tone': 'slate'}
    if d > 0.5:
        return {'code': 'breakout', 'label': '막 돌파', 'tone': 'emerald'}
    if -0.5 <= d <= 0.5:
        return {'code': 'buy_now', 'label': '🔥 매수 타이밍', 'tone': 'rose'}
    if -2.0 <= d < -0.5:
        return {'code': 'imminent', 'label': '🎯 진입 임박', 'tone': 'amber'}
    # d < -2.0
    if jubjub_score >= 70:
        return {'code': 'watching', 'label': '🪣 줍줍 후보', 'tone': 'emerald'}
    return {'code': 'watching', 'label': '관찰 중', 'tone': 'slate'}
