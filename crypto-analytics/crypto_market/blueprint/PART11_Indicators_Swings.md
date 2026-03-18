# PART11: 지표 및 스윙 탐지

## `crypto_market/indicators.py` (완전)

```python
import numpy as np
import pandas as pd

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def wick_ratio(open_: float, high: float, low: float, close: float) -> float:
    denom = high - low
    if denom <= 0:
        return 0.0
    return float((high - close) / denom)

def fractal_swings(df: pd.DataFrame, k: int = 3):
    """
    Fractal swing highs/lows.
    Returns ordered swings: [{i, type('H'/'L'), price}, ...]
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    swings = []

    for i in range(k, n - k):
        hi = highs[i]
        lo = lows[i]

        if hi > np.max(highs[i-k:i]) and hi > np.max(highs[i+1:i+k+1]):
            swings.append({"i": i, "type": "H", "price": float(hi)})

        if lo < np.min(lows[i-k:i]) and lo < np.min(lows[i+1:i+k+1]):
            swings.append({"i": i, "type": "L", "price": float(lo)})

    swings.sort(key=lambda x: x["i"])

    # Remove consecutive same-type (keep more extreme)
    cleaned = []
    for s in swings:
        if not cleaned:
            cleaned.append(s)
            continue
        last = cleaned[-1]
        if s["type"] != last["type"]:
            cleaned.append(s)
        else:
            if s["type"] == "H" and s["price"] >= last["price"]:
                cleaned[-1] = s
            elif s["type"] == "L" and s["price"] <= last["price"]:
                cleaned[-1] = s

    return cleaned
```

---

## `crypto_market/vcp_swings.py` (완전)

```python
#!/usr/bin/env python3
"""VCP Swing Point Extraction"""
import pandas as pd
from typing import Optional, Dict


def extract_vcp_from_swings(
    df: pd.DataFrame,
    k: int = 3,
    lookback: int = 200,
    min_r12: float = 1.2,
    min_r23: float = 1.1,
    require_descending_highs: bool = True,
    require_ascending_lows: bool = True,
) -> Optional[Dict]:
    """
    Extract VCP pattern from swing highs/lows
    """
    if len(df) < lookback:
        return None
    
    df = df.tail(lookback).copy()
    high = df["high"]
    low = df["low"]
    
    # Find swing highs
    swing_highs = []
    swing_lows = []
    
    for i in range(k, len(df) - k):
        if high.iloc[i] == high.iloc[i-k:i+k+1].max():
            swing_highs.append((i, high.iloc[i]))
        if low.iloc[i] == low.iloc[i-k:i+k+1].min():
            swing_lows.append((i, low.iloc[i]))
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None
    
    # Calculate contractions
    contractions = []
    for i in range(min(len(swing_highs), len(swing_lows))):
        h = swing_highs[i][1] if i < len(swing_highs) else swing_highs[-1][1]
        l = swing_lows[i][1] if i < len(swing_lows) else swing_lows[-1][1]
        if l > 0:
            range_pct = (h - l) / l * 100
            contractions.append(range_pct)
    
    if len(contractions) < 2:
        return None
    
    c1, c2 = contractions[0], contractions[1]
    c3 = contractions[2] if len(contractions) > 2 else c2 * 0.8
    
    # Check decay ratios
    if c2 > 0 and c1 / c2 < min_r12:
        return None
    if c3 > 0 and c2 / c3 < min_r23:
        return None
    
    # Check structure if required
    if require_descending_highs:
        highs_only = [h[1] for h in swing_highs[-3:]]
        if len(highs_only) >= 2 and highs_only[-1] > highs_only[-2]:
            return None
    
    if require_ascending_lows:
        lows_only = [l[1] for l in swing_lows[-3:]]
        if len(lows_only) >= 2 and lows_only[-1] < lows_only[-2]:
            return None
    
    pivot_high = max(h[1] for h in swing_highs[-3:]) if swing_highs else high.max()
    
    return {
        "pivot_high": pivot_high,
        "c1": c1,
        "c2": c2,
        "c3": c3,
    }
```

---

## 설명

### EMA (Exponential Moving Average)
- 최근 가격에 더 높은 가중치를 부여
- VCP에서 추세 확인용 (EMA50, EMA200)

### ATR (Average True Range)
- 변동성 측정 지표
- VCP 패턴의 수축도 평가에 사용

### Fractal Swings
- 스윙 고점/저점 탐지
- VCP의 3단계 수축 패턴 인식의 기반

### VCP Contraction Ratios
- C1/C2 비율: 첫 번째 수축
- C2/C3 비율: 두 번째 수축
- 비율이 높을수록 더 강한 VCP 패턴
