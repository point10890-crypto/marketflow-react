"""
적응형 ZigZag 알고리즘 + 5점 전환점 추출
ATR(14) 기반 동적 임계값으로 M&W 패턴의 전환점(Turning Point)을 추출한다.
"""
import numpy as np
from typing import List, Tuple
from .models import TurningPoint


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Average True Range 계산"""
    if len(closes) < period + 1:
        return float(np.mean(highs[-period:] - lows[-period:]))

    tr_list = []
    for i in range(-period, 0):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))
    return float(np.mean(tr_list))


def zigzag(
    dates: List[str],
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    reversal_pct: float = None,
) -> List[TurningPoint]:
    """
    적응형 ZigZag — 전환점 리스트 반환.

    reversal_pct를 지정하지 않으면 ATR(14) / 현재가 × 100 으로 자동 결정.
    최소 3%, 최대 15%로 클램핑.
    """
    n = len(closes)
    if n < 20:
        return []

    if reversal_pct is None:
        atr_val = _atr(highs, lows, closes)
        price = closes[-1] if closes[-1] > 0 else 1.0
        reversal_pct = max(3.0, min(15.0, (atr_val / price) * 100 * 2.5))

    threshold = reversal_pct / 100.0
    points: List[TurningPoint] = []

    # 초기 방향 결정
    direction = 1  # 1=상승 추적, -1=하락 추적
    last_high_idx = 0
    last_low_idx = 0
    last_high = highs[0]
    last_low = lows[0]

    for i in range(1, n):
        if direction == 1:  # 상승 추적 중
            if highs[i] > last_high:
                last_high = highs[i]
                last_high_idx = i
            elif closes[i] < last_high * (1 - threshold):
                # 고점 확정 → 하락 전환
                points.append(TurningPoint(
                    index=last_high_idx,
                    date=dates[last_high_idx] if last_high_idx < len(dates) else "",
                    price=float(last_high),
                    point_type="HIGH",
                ))
                direction = -1
                last_low = lows[i]
                last_low_idx = i
        else:  # 하락 추적 중
            if lows[i] < last_low:
                last_low = lows[i]
                last_low_idx = i
            elif closes[i] > last_low * (1 + threshold):
                # 저점 확정 → 상승 전환
                points.append(TurningPoint(
                    index=last_low_idx,
                    date=dates[last_low_idx] if last_low_idx < len(dates) else "",
                    price=float(last_low),
                    point_type="LOW",
                ))
                direction = 1
                last_high = highs[i]
                last_high_idx = i

    # 마지막 미확정 포인트 추가
    if direction == 1 and last_high_idx > (points[-1].index if points else -1):
        points.append(TurningPoint(
            index=last_high_idx,
            date=dates[last_high_idx] if last_high_idx < len(dates) else "",
            price=float(last_high),
            point_type="HIGH",
        ))
    elif direction == -1 and last_low_idx > (points[-1].index if points else -1):
        points.append(TurningPoint(
            index=last_low_idx,
            date=dates[last_low_idx] if last_low_idx < len(dates) else "",
            price=float(last_low),
            point_type="LOW",
        ))

    return points


def extract_five_point_groups(turning_points: List[TurningPoint]) -> List[List[TurningPoint]]:
    """
    연속 5개 전환점 그룹 추출.
    M 패턴: LOW-HIGH-LOW-HIGH-LOW (고점 2개)
    W 패턴: HIGH-LOW-HIGH-LOW-HIGH (저점 2개)
    슬라이딩 윈도우로 모든 가능한 5점 그룹을 반환.
    """
    if len(turning_points) < 5:
        return []

    groups = []
    for i in range(len(turning_points) - 4):
        group = turning_points[i:i + 5]

        types = [p.point_type for p in group]

        # M: LOW-HIGH-LOW-HIGH-LOW
        if types == ["LOW", "HIGH", "LOW", "HIGH", "LOW"]:
            groups.append(group)
        # W: HIGH-LOW-HIGH-LOW-HIGH
        elif types == ["HIGH", "LOW", "HIGH", "LOW", "HIGH"]:
            groups.append(group)

    return groups
