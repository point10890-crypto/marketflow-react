#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto VCP Scanner - Signal Detection Module (Tiered Approach)
ULTRATHINK Design Notes:
- Grade A: Strict classic VCP (close > EMA50 > EMA200, descending highs, ascending lows)
- Grade B: Relaxed VCP (close > EMA50, any swing structure)
- Grade C: Basic contraction (close > EMA200)
- Grade D: Accumulation (no trend requirement - for bear markets)
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
    """BTC regime affects altcoin behavior significantly."""
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
        # Minervini-style: close > EMA50 > EMA200, EMA200 rising
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
        return True  # No trend requirement
    return True


def try_extract_vcp_with_grade(
    df: pd.DataFrame,
    tf: TimeframeCfg,
    grade_params: dict,
) -> Optional[dict]:
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
            # Check trend for this grade
            trend_mode = grade_params.get("trend_mode", "ANY")
            if not check_trend_mode(close, e50, e200, trend_mode):
                continue
            
            # Try VCP extraction
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
            market_regime=f"{regime}|{grade}",  # Encode grade with regime
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
        
        # For setups, we also look for "approaching pivot" (within 2%)
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
