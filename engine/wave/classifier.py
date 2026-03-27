"""
32가지 M&W 파동 분류기
5점 전환점의 비율, 대칭성, 넥라인 기울기로 패턴 타입을 결정한다.
"""
import numpy as np
from typing import List, Optional, Dict
from .models import (
    TurningPoint, FivePointPattern, PatternClass, WaveType, WAVE_META,
)


def _bottom_sharpness(group: List[TurningPoint], closes: np.ndarray, idx: int) -> float:
    """저점/고점의 뾰족함(Adam) vs 둥근(Eve) 판별. 0=뾰족, 1=둥근"""
    tp = group[idx]
    center = tp.index
    window = max(2, (group[min(idx + 1, 4)].index - group[max(idx - 1, 0)].index) // 6)
    start = max(0, center - window)
    end = min(len(closes), center + window + 1)
    segment = closes[start:end]
    if len(segment) < 3:
        return 0.5
    spread = float(np.max(segment) - np.min(segment))
    avg_dev = float(np.mean(np.abs(segment - np.mean(segment))))
    price_range = max(float(np.mean(segment)) * 0.01, 1)
    return min(1.0, avg_dev / max(spread, price_range))


def classify_pattern(
    group: List[TurningPoint],
    closes: np.ndarray,
    volumes: Optional[np.ndarray] = None,
    current_price: Optional[float] = None,
) -> FivePointPattern:
    """
    5점 그룹을 받아 32가지 중 하나로 분류.
    group[0..4]: 5개 TurningPoint (M 또는 W 배열)
    """
    p1, p2, p3, p4, p5 = group
    types = [p.point_type for p in group]

    # M or W 판별
    if types == ["LOW", "HIGH", "LOW", "HIGH", "LOW"]:
        pat_class = PatternClass.M
        peak1, peak2 = p2, p4
        trough1, trough2, trough3 = p1, p3, p5
        # 넥라인 = 두 고점 사이의 저점 (p3)
        neckline = p3.price
    else:
        pat_class = PatternClass.W
        trough1, trough2 = p2, p4
        peak1, peak2, peak3 = p1, p3, p5
        # 넥라인 = 두 저점 사이의 고점 (p3)
        neckline = p3.price

    # ── 비율 계산 ──
    if pat_class == PatternClass.M:
        peak_ratio = peak2.price / max(peak1.price, 1)       # >1이면 우상향
        trough_diff_pct = (trough3.price - trough1.price) / max(trough1.price, 1) * 100
        neckline_slope = (p3.price - p1.price) / max(p3.index - p1.index, 1)
    else:
        trough_ratio = trough2.price / max(trough1.price, 1)  # <1이면 우하향
        peak_diff_pct = (peak3.price - peak1.price) / max(peak1.price, 1) * 100
        neckline_slope = (p3.price - p1.price) / max(p3.index - p1.index, 1)

    # 시간 대칭
    left_span = p3.index - p1.index
    right_span = p5.index - p3.index
    symmetry_ratio = min(left_span, right_span) / max(left_span, right_span, 1)

    # 가격 범위
    all_prices = [p.price for p in group]
    pattern_height = max(all_prices) - min(all_prices)
    avg_price = np.mean(all_prices)

    # ── 분류 로직 ──
    wave_type = _classify_m(group, closes, peak_ratio, neckline_slope, symmetry_ratio, pattern_height, avg_price) \
        if pat_class == PatternClass.M else \
        _classify_w(group, closes, trough_ratio, neckline_slope, symmetry_ratio, pattern_height, avg_price)

    # ── 넥라인 거리 ──
    cur = current_price if current_price else closes[-1] if len(closes) > 0 else neckline
    neckline_dist = (float(cur) - neckline) / max(neckline, 1) * 100

    # ── 완성도 ──
    completion = _calc_completion(group, pat_class, closes)

    # ── 거래량 확인 ──
    vol_confirmed = False
    if volumes is not None and len(volumes) > p5.index:
        vol_confirmed = _check_volume(group, volumes, pat_class)

    # ── 신뢰도 ──
    meta = WAVE_META.get(wave_type, {"reliability": 50})
    base_conf = meta["reliability"]
    conf = base_conf
    if vol_confirmed:
        conf = min(100, conf + 10)
    if symmetry_ratio > 0.7:
        conf = min(100, conf + 5)
    if completion > 90:
        conf = min(100, conf + 5)

    return FivePointPattern(
        points=list(group),
        pattern_class=pat_class.value,
        wave_type=wave_type,
        neckline_price=round(neckline, 2),
        confidence=conf,
        completion_pct=completion,
        neckline_distance_pct=round(neckline_dist, 2),
        bullish_bias=WAVE_META.get(wave_type, {}).get("bias", 0),
        volume_confirmed=vol_confirmed,
    )


def _classify_m(group, closes, peak_ratio, neckline_slope, symmetry, height, avg_price) -> str:
    p1, p2, p3, p4, p5 = group
    left_span = p3.index - p1.index
    right_span = p5.index - p3.index
    width_bars = p5.index - p1.index

    # Head & Shoulders: 중간 고점(p2 or p4)이 나머지보다 현저히 높음
    if p2.price > p4.price * 1.03 and p2.price > p1.price and p2.price > p5.price:
        return WaveType.HEAD_SHOULDERS

    # Triple top: p2 ≈ p4 and p1 ≈ p3 ≈ p5
    peaks_close = abs(p2.price - p4.price) / max(avg_price, 1) < 0.02
    troughs_close = abs(p1.price - p3.price) / max(avg_price, 1) < 0.02 and abs(p3.price - p5.price) / max(avg_price, 1) < 0.02
    if peaks_close and troughs_close:
        return WaveType.M_TRIPLE_TOP

    # Sharpness (Adam/Eve)
    sharp2 = _bottom_sharpness(group, closes, 1)
    sharp4 = _bottom_sharpness(group, closes, 3)
    adam2 = sharp2 < 0.4
    adam4 = sharp4 < 0.4

    # Width
    if width_bars > 80:
        return WaveType.M_WIDE
    if width_bars < 15:
        return WaveType.M_NARROW

    # Neckline slope
    slope_pct = neckline_slope / max(avg_price, 1) * 100
    if slope_pct > 0.3:
        return WaveType.M_ASCENDING_NECKLINE
    if slope_pct < -0.3:
        return WaveType.M_DESCENDING_NECKLINE

    # Peak ratio
    if peak_ratio > 1.02:
        return WaveType.M_RIGHT_HIGHER
    if peak_ratio < 0.98:
        return WaveType.M_LEFT_HIGHER

    # Adam/Eve
    if adam2 and adam4:
        return WaveType.M_ADAM_ADAM
    if adam2 and not adam4:
        return WaveType.M_ADAM_EVE
    if not adam2 and adam4:
        return WaveType.M_EVE_ADAM
    if not adam2 and not adam4:
        return WaveType.M_EVE_EVE

    return WaveType.M_SYMMETRIC


def _classify_w(group, closes, trough_ratio, neckline_slope, symmetry, height, avg_price) -> str:
    p1, p2, p3, p4, p5 = group
    left_span = p3.index - p1.index
    right_span = p5.index - p3.index
    width_bars = p5.index - p1.index

    # Inverse Head & Shoulders: 중간 저점이 나머지보다 현저히 낮음
    if p2.price < p4.price * 0.97 and p2.price < p1.price and p2.price < p5.price:
        return WaveType.INV_HEAD_SHOULDERS

    # Triple bottom
    troughs_close = abs(p2.price - p4.price) / max(avg_price, 1) < 0.02
    peaks_close = abs(p1.price - p3.price) / max(avg_price, 1) < 0.02 and abs(p3.price - p5.price) / max(avg_price, 1) < 0.02
    if troughs_close and peaks_close:
        return WaveType.W_TRIPLE_BOTTOM

    # Sharpness
    sharp2 = _bottom_sharpness(group, closes, 1)
    sharp4 = _bottom_sharpness(group, closes, 3)
    adam2 = sharp2 < 0.4
    adam4 = sharp4 < 0.4

    # Width
    if width_bars > 80:
        return WaveType.W_WIDE
    if width_bars < 15:
        return WaveType.W_NARROW

    # Neckline slope
    slope_pct = neckline_slope / max(avg_price, 1) * 100
    if slope_pct > 0.3:
        return WaveType.W_ASCENDING_NECKLINE
    if slope_pct < -0.3:
        return WaveType.W_DESCENDING_NECKLINE

    # Trough ratio
    if trough_ratio < 0.98:
        return WaveType.W_RIGHT_HIGHER  # 두번째 저점이 높음 → 상승 시사
    if trough_ratio > 1.02:
        return WaveType.W_LEFT_HIGHER

    # Adam/Eve
    if adam2 and adam4:
        return WaveType.W_ADAM_ADAM
    if adam2 and not adam4:
        return WaveType.W_ADAM_EVE
    if not adam2 and adam4:
        return WaveType.W_EVE_ADAM
    if not adam2 and not adam4:
        return WaveType.W_EVE_EVE

    return WaveType.W_SYMMETRIC


def _calc_completion(group: List[TurningPoint], pat_class: PatternClass, closes: np.ndarray) -> float:
    """패턴 완성도 계산 (0-100)"""
    p1, p2, p3, p4, p5 = group
    last_close = float(closes[-1]) if len(closes) > 0 else p5.price
    last_idx = len(closes) - 1

    # P5까지 형성 완료 = 80% 기본
    base = 80.0

    # 넥라인 돌파 여부로 나머지 20%
    neckline = p3.price
    if pat_class == PatternClass.W:
        # W: 현재가가 넥라인 위 → 100%
        if last_close > neckline:
            base = 100.0
        else:
            # 넥라인까지 남은 거리 비율
            pattern_range = neckline - min(p2.price, p4.price)
            if pattern_range > 0:
                progress = (last_close - min(p2.price, p4.price)) / pattern_range
                base = 80.0 + max(0, min(20, progress * 20))
    else:
        # M: 현재가가 넥라인 아래 → 100%
        if last_close < neckline:
            base = 100.0
        else:
            pattern_range = max(p2.price, p4.price) - neckline
            if pattern_range > 0:
                progress = (max(p2.price, p4.price) - last_close) / pattern_range
                base = 80.0 + max(0, min(20, progress * 20))

    return round(base, 1)


def _check_volume(group: List[TurningPoint], volumes: np.ndarray, pat_class: PatternClass) -> bool:
    """거래량 확인: 전환점에서 거래량 팽창 여부"""
    p1, p2, p3, p4, p5 = group
    if p5.index >= len(volumes):
        return False

    # P1~P5 구간 평균 거래량
    seg_start = max(0, p1.index)
    seg_end = min(len(volumes), p5.index + 1)
    avg_vol = float(np.mean(volumes[seg_start:seg_end])) if seg_end > seg_start else 1

    if avg_vol <= 0:
        return False

    # 전환점 거래량이 평균보다 높은지
    confirmed = 0
    for tp in [p2, p4]:
        if tp.index < len(volumes):
            # 전환점 ±2일 최대 거래량
            window_start = max(0, tp.index - 2)
            window_end = min(len(volumes), tp.index + 3)
            peak_vol = float(np.max(volumes[window_start:window_end]))
            if peak_vol > avg_vol * 1.3:
                confirmed += 1

    return confirmed >= 1
