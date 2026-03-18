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
