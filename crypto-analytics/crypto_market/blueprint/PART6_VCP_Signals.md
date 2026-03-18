# PART6: VCP 시그널 탐지

## 1. `crypto_market/signals.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto VCP Scanner - Signal Detection Module (Tiered Approach)
- Grade A: Strict classic VCP (close > EMA50 > EMA200)
- Grade B: Relaxed VCP (close > EMA50)
- Grade C: Basic contraction (close > EMA200)
- Grade D: Accumulation (no trend requirement)
"""
from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import pandas as pd

from models import Candle, SetupCandidate, SignalEvent
from indicators import ema, atr, wick_ratio as wick_ratio_fn
from vcp_swings import extract_vcp_from_swings
from config import TimeframeCfg, ALL_GRADES
from universe import liquidity_bucket_from_quote_volume


def candles_to_df(candles: List[Candle]) -> pd.DataFrame:
    return pd.DataFrame([{
        "ts": c.ts, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume
    } for c in candles]).sort_values("ts").reset_index(drop=True)


def market_regime_from_btc(btc_df: pd.DataFrame) -> str:
    """BTC regime affects altcoin behavior."""
    if len(btc_df) < 50:
        return "BTC_SIDE"
    close = btc_df["close"]
    e50 = ema(close, 50)
    slope = float(e50.iloc[-1] - e50.iloc[-21])
    if close.iloc[-1] > e50.iloc[-1] and slope > 0:
        return "BTC_UP"
    if close.iloc[-1] < e50.iloc[-1] and slope < 0:
        return "BTC_DOWN"
    return "BTC_SIDE"


def check_trend_mode(close: pd.Series, e50: pd.Series, e200: pd.Series, mode: str) -> bool:
    """Check trend based on mode"""
    if mode == "STRICT":
        if not (close.iloc[-1] > e50.iloc[-1] > e200.iloc[-1]):
            return False
        if len(e200) > 21 and (e200.iloc[-1] - e200.iloc[-21]) <= 0:
            return False
        return True
    elif mode == "ABOVE_EMA50":
        return close.iloc[-1] > e50.iloc[-1]
    elif mode == "ABOVE_EMA200":
        return close.iloc[-1] > e200.iloc[-1]
    elif mode == "ANY":
        return True
    return True


def try_extract_vcp_with_grade(df: pd.DataFrame, tf: TimeframeCfg, grade_params: dict) -> Optional[dict]:
    """Try to extract VCP with specific grade parameters"""
    return extract_vcp_from_swings(
        df=df,
        k=tf.swing_k,
        lookback=tf.max_swings_lookback,
        min_r12=grade_params["min_r12"],
        min_r23=grade_params["min_r23"],
        require_descending_highs=grade_params["require_descending_highs"],
        require_ascending_lows=grade_params["require_ascending_lows"],
    )


def detect_setups(
    exchange_name: str,
    symbols_with_qv: List[Tuple[str, float]],
    candles_map: Dict[Tuple[str, str], List[Candle]],
    btc_candles: List[Candle],
    tf: TimeframeCfg,
) -> List[SetupCandidate]:
    """
    TIERED Setup Detection:
    - Tries grades A → B → C → D in order
    - Assigns the highest matching grade
    """
    setups: List[SetupCandidate] = []

    btc_df = candles_to_df(btc_candles) if btc_candles else pd.DataFrame(columns=["close"])
    regime = market_regime_from_btc(btc_df) if len(btc_df) else "BTC_SIDE"

    for sym, qv in symbols_with_qv:
        key = (sym, tf.timeframe)
        candles = candles_map.get(key)
        if not candles or len(candles) < 260:
            continue

        df = candles_to_df(candles)
        close = df["close"]

        e50 = ema(close, 50)
        e200 = ema(close, 200)
        if pd.isna(e200.iloc[-1]) or pd.isna(e50.iloc[-1]):
            continue

        # Try each grade in order (A -> B -> C -> D)
        vcp_result = None
        grade = None
        
        for grade_params, grade_name in ALL_GRADES:
            trend_mode = grade_params.get("trend_mode", "ANY")
            if not check_trend_mode(close, e50, e200, trend_mode):
                continue
            
            vcp = try_extract_vcp_with_grade(df, tf, grade_params)
            if vcp:
                vcp_result = vcp
                grade = grade_name
                break

        if not vcp_result:
            continue

        pivot_high = vcp_result["pivot_high"]
        c1, c2, c3 = vcp_result["c1"], vcp_result["c2"], vcp_result["c3"]

        # ATR%
        a = atr(df, 14)
        atrp = float(a.iloc[-1] / close.iloc[-1] * 100.0) if close.iloc[-1] > 0 else 0.0

        # Above EMA50 ratio (last 20)
        tail_n = 20
        above_ratio = float((df.tail(tail_n)["close"].values > e50.tail(tail_n).values).mean())

        # EMA separation %
        ema_sep_pct = float((e50.iloc[-1] - e200.iloc[-1]) / e200.iloc[-1] * 100.0) if e200.iloc[-1] != 0 else 0.0

        # Volume MA20
        vol_ma20 = float(df["volume"].rolling(20).mean().iloc[-1]) if len(df) >= 20 else float(df["volume"].mean())

        liq_bucket = liquidity_bucket_from_quote_volume(qv)

        setups.append(SetupCandidate(
            exchange=exchange_name,
            symbol=sym,
            timeframe=tf.timeframe,
            event_ts=int(df["ts"].iloc[-1]),
            pivot_high=float(pivot_high),
            c1_range_pct=float(c1),
            c2_range_pct=float(c2),
            c3_range_pct=float(c3),
            atrp_pct=float(atrp),
            ema50=float(e50.iloc[-1]),
            ema200=float(e200.iloc[-1]),
            ema_sep_pct=float(ema_sep_pct),
            above_ema50_ratio=float(above_ratio),
            vol_ma20=float(vol_ma20),
            liquidity_bucket=liq_bucket,
            market_regime=f"{regime}|{grade}",
        ))

    return setups


def detect_breakouts(
    setups: List[SetupCandidate],
    candles_map: Dict[Tuple[str, str], List[Candle]],
    tf: TimeframeCfg
) -> List[SignalEvent]:
    """Detect breakout signals from setups"""
    out: List[SignalEvent] = []
    for s in setups:
        candles = candles_map.get((s.symbol, s.timeframe))
        if not candles:
            continue
        last = candles[-1]

        if s.pivot_high <= 0:
            continue

        breakout_close_pct = (last.close - s.pivot_high) / s.pivot_high * 100.0
        
        approaching = -2.0 <= breakout_close_pct <= 0
        breaking_out = last.close > s.pivot_high and tf.breakout_min_pct <= breakout_close_pct <= tf.breakout_max_pct
        
        if not (approaching or breaking_out):
            continue

        vol_ratio = (last.volume / s.vol_ma20) if s.vol_ma20 > 0 else 0.0
        wr = wick_ratio_fn(last.open, last.high, last.low, last.close)

        signal_type = "BREAKOUT" if breaking_out else "APPROACHING"

        out.append(SignalEvent(
            exchange=s.exchange,
            symbol=s.symbol,
            timeframe=s.timeframe,
            event_ts=s.event_ts,
            signal_type=signal_type,
            pivot_high=s.pivot_high,
            c1_range_pct=s.c1_range_pct,
            c2_range_pct=s.c2_range_pct,
            c3_range_pct=s.c3_range_pct,
            atrp_pct=s.atrp_pct,
            ema_sep_pct=s.ema_sep_pct,
            above_ema50_ratio=s.above_ema50_ratio,
            liquidity_bucket=s.liquidity_bucket,
            market_regime=s.market_regime,
            breakout_close_pct=float(breakout_close_pct),
            vol_ratio=float(vol_ratio),
            wick_ratio=float(wr),
        ))
    return out


def detect_retests(
    setups: List[SetupCandidate],
    recent_breakouts: List[SignalEvent],
    candles_map: Dict[Tuple[str, str], List[Candle]],
    tf: TimeframeCfg,
) -> List[SignalEvent]:
    """Detect retest confirmations after breakouts"""
    out: List[SignalEvent] = []
    br_map = {(b.symbol, b.timeframe): b for b in recent_breakouts if b.signal_type == "BREAKOUT"}

    for s in setups:
        b = br_map.get((s.symbol, s.timeframe))
        if not b:
            continue

        candles = candles_map.get((s.symbol, s.timeframe))
        if not candles:
            continue

        after = [c for c in candles if c.ts > b.event_ts]
        if not after:
            continue
        after = after[-tf.max_bars_after_breakout:]

        pivot = s.pivot_high
        tol = tf.retest_tol_pct
        tol_low = pivot * (1 - tol/100.0)
        tol_high = pivot * (1 + tol/100.0)

        dipped = None
        for c in after:
            if tol_low <= c.low <= tol_high:
                dipped = c
                break
        if not dipped:
            continue

        confirm = after[-1]
        if confirm.close < pivot:
            continue

        retest_vol_ratio = (confirm.volume / s.vol_ma20) if s.vol_ma20 > 0 else 0.0
        retest_depth_pct = (pivot - dipped.low) / pivot * 100.0 if pivot > 0 else 0.0

        wr = wick_ratio_fn(confirm.open, confirm.high, confirm.low, confirm.close)

        out.append(SignalEvent(
            exchange=s.exchange,
            symbol=s.symbol,
            timeframe=s.timeframe,
            event_ts=s.event_ts,
            signal_type="RETEST_OK",
            pivot_high=pivot,
            c1_range_pct=s.c1_range_pct,
            c2_range_pct=s.c2_range_pct,
            c3_range_pct=s.c3_range_pct,
            atrp_pct=s.atrp_pct,
            ema_sep_pct=s.ema_sep_pct,
            above_ema50_ratio=s.above_ema50_ratio,
            liquidity_bucket=s.liquidity_bucket,
            market_regime=s.market_regime,
            breakout_close_pct=b.breakout_close_pct,
            vol_ratio=b.vol_ratio,
            wick_ratio=float(wr),
            retest_tolerance_pct=float(tol),
            retest_depth_pct=float(retest_depth_pct),
            retest_vol_ratio=float(retest_vol_ratio),
            retest_close_above=1,
        ))
    return out
```

---

## 2. `crypto_market/scoring.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto VCP Scanner - Scoring Engine
Total score 0-100:
  - Contraction Quality (40%): How tight/clean is the VCP?
  - Trend Strength (25%): How solid is the uptrend?
  - Trigger Quality (25%): How clean was the breakout/retest?
  - Risk/Liquidity (10%): Market regime + liquidity tier
"""
from models import SignalEvent
from config import TimeframeCfg


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def norm(x: float, lo: float, hi: float) -> float:
    """Normalize x to [0, 1] range"""
    if hi == lo:
        return 0.0
    return clamp((x - lo) / (hi - lo), 0.0, 1.0)


def score_signal(evt: SignalEvent, tf: TimeframeCfg) -> int:
    """
    ULTRATHINK Scoring:
    1. CONTRACTION (40 points)
    2. TREND (25 points)
    3. TRIGGER (25 points)
    4. RISK/LIQUIDITY (10 points)
    """
    eps = 1e-9
    c1, c2, c3 = evt.c1_range_pct, evt.c2_range_pct, evt.c3_range_pct
    r12 = c1 / max(c2, eps)
    r23 = c2 / max(c3, eps)

    # === CONTRACTION (40 pts) ===
    s_decay = 0.5 * norm(r12, 1.1, 1.8) + 0.5 * norm(r23, 1.05, 1.6)
    s_c3 = 1.0 - norm(c3, tf.c3_lo, tf.c3_hi)
    s_atrp = 1.0 - norm(evt.atrp_pct, tf.atrp_lo, tf.atrp_hi)
    contraction = 40.0 * (0.45*s_decay + 0.35*s_c3 + 0.20*s_atrp)

    # === TREND (25 pts) ===
    s_hold = norm(evt.above_ema50_ratio, 0.55, 0.85)
    s_sep = norm(evt.ema_sep_pct, tf.sep_lo, tf.sep_hi)
    trend = 25.0 * (0.65*s_hold + 0.35*s_sep)

    # === TRIGGER (25 pts) ===
    if evt.signal_type == "BREAKOUT":
        s_break = 1.0 - abs(norm(evt.breakout_close_pct, tf.breakout_min_pct, tf.breakout_max_pct) - 0.55) * 1.6
        s_break = clamp(s_break, 0.0, 1.0)
        s_vol = norm(evt.vol_ratio, 1.2, 2.5)
        trigger = 25.0 * (0.55*s_break + 0.45*s_vol)
    else:  # RETEST_OK
        tol_hi = 1.0 if tf.timeframe == "1d" else 0.6
        depth = evt.retest_depth_pct or 0.0
        s_depth = 1.0 - abs(norm(depth, 0.0, tol_hi) - 0.65) * 1.4
        s_depth = clamp(s_depth, 0.0, 1.0)
        s_hold2 = float(evt.retest_close_above or 0)
        rv = evt.retest_vol_ratio or 2.0
        s_vol2 = 1.0 - norm(rv, 0.9, 1.6)
        trigger = 25.0 * (0.45*s_depth + 0.35*s_hold2 + 0.20*s_vol2)

    # === RISK/LIQUIDITY (10 pts) ===
    s_wick = 1.0 - norm(evt.wick_ratio, 0.25, 0.65)
    s_liq = {"A": 1.0, "B": 0.6, "C": 0.2}.get(evt.liquidity_bucket, 0.2)
    s_reg = {"BTC_UP": 1.0, "BTC_SIDE": 0.7, "BTC_DOWN": 0.3}.get(evt.market_regime, 0.7)
    risk_liq = 10.0 * (0.5*s_wick + 0.35*s_liq + 0.15*s_reg)

    total = contraction + trend + trigger + risk_liq
    return int(round(clamp(total, 0.0, 100.0)))


def score_batch(evts: list[SignalEvent], tf: TimeframeCfg) -> list[SignalEvent]:
    """Score all signals in batch"""
    for e in evts:
        e.score = score_signal(e, tf)
    return evts
```

---

## 3. `crypto_market/vcp_swings.py`

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

## VCP 탐지 플로우

```
1. symbols_with_qv: 거래량 상위 200개 코인
         ↓
2. detect_setups(): Grade A→B→C→D 순서로 VCP 탐색
         ↓
3. detect_breakouts(): 돌파 감지 (pivot 위 종가)
         ↓
4. detect_retests(): 리테스트 확인 (지지선 터치 후 반등)
         ↓
5. score_batch(): 0~100점 품질 점수
```
