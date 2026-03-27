"""
패턴 신뢰도 채점 (100점 만점)
"""
import numpy as np
from typing import List, Optional, Dict
from .models import FivePointPattern, TurningPoint, WAVE_META


def score_pattern(
    pattern: FivePointPattern,
    closes: np.ndarray,
    volumes: Optional[np.ndarray] = None,
    market_regime: Optional[str] = None,
) -> int:
    """
    패턴 신뢰도 점수 (0-100)

    | 항목             | 배점  |
    |-----------------|-------|
    | 패턴 완성도       | 0-25  |
    | 넥라인 근접도     | 0-20  |
    | 거래량 확인       | 0-15  |
    | 파동 대칭성       | 0-10  |
    | 패턴 타입 신뢰도  | 0-15  |
    | 시장 레짐 일치    | 0-15  |
    """
    total = 0

    # 1. 패턴 완성도 (0-25)
    total += min(25, int(pattern.completion_pct / 100 * 25))

    # 2. 넥라인 근접도 (0-20) — 가까울수록 높음
    dist = abs(pattern.neckline_distance_pct)
    if dist <= 1:
        total += 20
    elif dist <= 3:
        total += 15
    elif dist <= 5:
        total += 10
    elif dist <= 10:
        total += 5

    # 3. 거래량 확인 (0-15)
    if pattern.volume_confirmed:
        total += 15
    elif volumes is not None and len(volumes) > 0:
        # 부분 점수: 최근 5일 거래량 > 20일 평균
        if len(volumes) >= 20:
            recent = float(np.mean(volumes[-5:]))
            avg20 = float(np.mean(volumes[-20:]))
            if avg20 > 0 and recent / avg20 > 1.2:
                total += 8

    # 4. 파동 대칭성 (0-10)
    points = pattern.points
    if len(points) >= 5:
        left_span = points[2].index - points[0].index
        right_span = points[4].index - points[2].index
        sym = min(left_span, right_span) / max(left_span, right_span, 1)
        total += int(sym * 10)

    # 5. 패턴 타입 신뢰도 (0-15)
    meta = WAVE_META.get(pattern.wave_type, {})
    reliability = meta.get("reliability", 50)
    total += int(reliability / 100 * 15)

    # 6. 시장 레짐 일치 (0-15)
    if market_regime:
        bias = pattern.bullish_bias
        if market_regime == "RISK_ON" and bias > 0:
            total += 15
        elif market_regime == "RISK_OFF" and bias < 0:
            total += 15
        elif market_regime == "NEUTRAL":
            total += 8
        else:
            total += 3  # 역방향이라도 최소 점수

    return min(100, total)
