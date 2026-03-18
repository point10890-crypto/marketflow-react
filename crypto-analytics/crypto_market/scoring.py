#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto VCP Scanner - Scoring Engine
ULTRATHINK Design Notes:
- Total score 0-100 divided into 4 components:
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
    ULTRATHINK Scoring Breakdown:
    
    1. CONTRACTION (40 points)
       - Decay ratio (C1/C2, C2/C3): Higher = better compression
       - C3 tightness: Smaller final contraction = coiled spring
       - ATR%: Lower volatility in base = controlled consolidation
    
    2. TREND (25 points)
       - Above EMA50 ratio: More bars above = stronger trend
       - EMA separation: Wider gap = established momentum
    
    3. TRIGGER (25 points)
       - Breakout: Moderate extension (not too weak, not too stretched)
       - Volume ratio: Higher = institutional participation
       - Retest: Shallow depth + hold = accumulation
    
    4. RISK/LIQUIDITY (10 points)
       - Wick ratio: Lower = cleaner price action
       - Liquidity bucket: A > B > C
       - Market regime: BTC_UP > BTC_SIDE > BTC_DOWN
    """
    eps = 1e-9
    c1, c2, c3 = evt.c1_range_pct, evt.c2_range_pct, evt.c3_range_pct
    r12 = c1 / max(c2, eps)
    r23 = c2 / max(c3, eps)

    # === CONTRACTION (40 pts) ===
    s_decay = 0.5 * norm(r12, 1.1, 1.8) + 0.5 * norm(r23, 1.05, 1.6)
    s_c3 = 1.0 - norm(c3, tf.c3_lo, tf.c3_hi)  # Smaller C3 = better
    s_atrp = 1.0 - norm(evt.atrp_pct, tf.atrp_lo, tf.atrp_hi)  # Lower ATR = better
    contraction = 40.0 * (0.45*s_decay + 0.35*s_c3 + 0.20*s_atrp)

    # === TREND (25 pts) ===
    s_hold = norm(evt.above_ema50_ratio, 0.55, 0.85)
    s_sep = norm(evt.ema_sep_pct, tf.sep_lo, tf.sep_hi)
    trend = 25.0 * (0.65*s_hold + 0.35*s_sep)

    # === TRIGGER (25 pts) ===
    if evt.signal_type == "BREAKOUT":
        # Goldilocks zone: not too weak (< 0.2%), not too extended (> 6%)
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
        s_vol2 = 1.0 - norm(rv, 0.9, 1.6)  # Lower retest volume = healthy dip
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
