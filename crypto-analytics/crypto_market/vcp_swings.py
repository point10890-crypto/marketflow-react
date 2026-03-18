from __future__ import annotations
from typing import Optional, Dict, List
import pandas as pd
from indicators import fractal_swings

def extract_vcp_from_swings(
    df: pd.DataFrame,
    k: int,
    lookback: int,
    min_r12: float,
    min_r23: float,
    require_descending_highs: bool = True,
    require_ascending_lows: bool = True,
) -> Optional[Dict]:
    """
    Find VCP contraction structure using swing points.
    
    UPDATED LOGIC:
    - Primary pattern: H1 L1 H2 L2 H3 (5 points minimum)
    - L3 is optional (can use current price range as C3 proxy)
    - pivot_high = H3
    - C1=(H1-L1)/H1, C2=(H2-L2)/H2, C3=(H3-current_low)/H3 or (H3-L3)/H3
    """
    w = df.tail(lookback).reset_index(drop=True)
    swings = fractal_swings(w, k=k)
    
    if len(swings) < 5:  # Relaxed from 8
        return None

    last_idx = len(w) - 1
    
    # Get all highs up to last closed candle
    highs = [s for s in swings if s["type"] == "H"]
    lows = [s for s in swings if s["type"] == "L"]
    
    if len(highs) < 3 or len(lows) < 2:
        return None
    
    # Use most recent 3 highs
    H1, H2, H3 = highs[-3], highs[-2], highs[-1]
    
    # Find lows between H1-H2 and H2-H3
    lows_h1_h2 = [l for l in lows if H1["i"] < l["i"] < H2["i"]]
    lows_h2_h3 = [l for l in lows if H2["i"] < l["i"] < H3["i"]]
    
    if not lows_h1_h2 or not lows_h2_h3:
        return None
    
    L1 = min(lows_h1_h2, key=lambda x: x["price"])
    L2 = min(lows_h2_h3, key=lambda x: x["price"])
    
    # L3: either a swing low after H3, or use recent low
    lows_after_h3 = [l for l in lows if l["i"] > H3["i"]]
    if lows_after_h3:
        L3 = min(lows_after_h3, key=lambda x: x["price"])
        L3_price = L3["price"]
    else:
        # No formal L3 swing yet - use the lowest low since H3
        if H3["i"] < last_idx:
            recent_lows = w["low"].iloc[H3["i"]:last_idx+1]
            L3_price = float(recent_lows.min())
        else:
            L3_price = float(w["low"].iloc[-1])
    
    # Calculate contractions
    if H1["price"] <= 0 or H2["price"] <= 0 or H3["price"] <= 0:
        return None
    
    c1 = (H1["price"] - L1["price"]) / H1["price"] * 100.0
    c2 = (H2["price"] - L2["price"]) / H2["price"] * 100.0
    c3 = (H3["price"] - L3_price) / H3["price"] * 100.0
    
    # Must have decreasing contractions
    if not (c1 > c2 > c3 > 0):
        return None
    
    # Check ratio requirements
    r12 = c1 / max(c2, 1e-9)
    r23 = c2 / max(c3, 1e-9)
    if r12 < min_r12 or r23 < min_r23:
        return None
    
    # Optional: check descending highs
    if require_descending_highs:
        if not (H1["price"] > H2["price"] > H3["price"]):
            return None
    
    # Optional: check ascending lows
    if require_ascending_lows:
        if not (L1["price"] < L2["price"] < L3_price):
            return None
    
    return {
        "pivot_high": float(H3["price"]),
        "c1": float(c1),
        "c2": float(c2),
        "c3": float(c3),
        "r12": float(r12),
        "r23": float(r23),
        "swing_points": [H1, L1, H2, L2, H3],
    }
