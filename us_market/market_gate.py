#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Market Gate - Enhanced Scoring v2.0
🧠 ULTRATHINK: RSI, MACD, Volume, and Relative Strength
"""

import yfinance as yf
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class SectorResult:
    name: str
    ticker: str
    score: int
    signal: str
    price: float
    change_1d: float
    rsi: float
    rs_vs_spy: float

@dataclass
class USMarketGateResult:
    gate: str
    score: int
    reasons: List[str]
    sectors: List[SectorResult]
    metrics: Dict[str, Any]

SECTORS = {
    "Technology": "XLK", "Health Care": "XLV", "Financials": "XLF",
    "Cons Disc": "XLY", "Cons Staples": "XLP", "Energy": "XLE",
    "Industrials": "XLI", "Materials": "XLB", "Real Estate": "XLRE",
    "Utilities": "XLU", "Communication": "XLC"
}

def calculate_rsi(series: pd.Series, period: int = 14) -> float:
    """Calculate RSI (Relative Strength Index)"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

def calculate_macd_signal(series: pd.Series) -> str:
    """Calculate MACD and return signal: BULLISH, BEARISH, NEUTRAL"""
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    
    # Check crossover
    curr_macd = macd_line.iloc[-1]
    curr_signal = signal_line.iloc[-1]
    prev_macd = macd_line.iloc[-2]
    prev_signal = signal_line.iloc[-2]
    
    if curr_macd > curr_signal and prev_macd <= prev_signal:
        return "BULLISH"  # Golden cross
    elif curr_macd < curr_signal and prev_macd >= prev_signal:
        return "BEARISH"  # Death cross
    elif curr_macd > curr_signal:
        return "BULLISH"
    else:
        return "BEARISH"

def calculate_volume_ratio(volume: pd.Series, period: int = 20) -> float:
    """Calculate current volume vs avg volume ratio"""
    avg_vol = volume.rolling(period).mean().iloc[-1]
    curr_vol = volume.iloc[-1]
    return float(curr_vol / avg_vol) if avg_vol > 0 else 1.0

def calculate_rs_vs_benchmark(sector_close: pd.Series, benchmark_close: pd.Series, period: int = 20) -> float:
    """Calculate Relative Strength vs benchmark (SPY)"""
    sector_ret = (sector_close.iloc[-1] - sector_close.iloc[-period]) / sector_close.iloc[-period]
    bench_ret = (benchmark_close.iloc[-1] - benchmark_close.iloc[-period]) / benchmark_close.iloc[-period]
    return float((sector_ret - bench_ret) * 100)  # Outperformance in %

def calculate_enhanced_score(close: pd.Series, volume: pd.Series, spy_close: pd.Series = None) -> Tuple[int, str, dict]:
    """Enhanced scoring with RSI, MACD, Volume, RS"""
    if len(close) < 200:
        return 50, "NEUTRAL", {}
    
    score = 0
    details = {}
    
    # 1. Trend Alignment (25 pts)
    e50 = close.rolling(50).mean()
    e200 = close.rolling(200).mean()
    curr_price, curr_e50, curr_e200 = close.iloc[-1], e50.iloc[-1], e200.iloc[-1]
    
    if curr_price > curr_e50 > curr_e200:
        score += 25
        details['trend'] = 'Strong Uptrend'
    elif curr_price > curr_e50:
        score += 15
        details['trend'] = 'Mild Uptrend'
    elif curr_price > curr_e200:
        score += 10
        details['trend'] = 'Above 200MA'
    else:
        details['trend'] = 'Downtrend'
    
    # 2. RSI (25 pts)
    rsi = calculate_rsi(close)
    details['rsi'] = rsi
    if 50 <= rsi <= 70:  # Healthy bullish zone
        score += 25
    elif 40 <= rsi < 50:  # Neutral
        score += 15
    elif 30 <= rsi < 40:  # Oversold (potential buy)
        score += 20
    elif rsi < 30:  # Extremely oversold
        score += 10
    # RSI > 70 = overbought, no points
    
    # 3. MACD Signal (20 pts)
    macd_sig = calculate_macd_signal(close)
    details['macd'] = macd_sig
    if macd_sig == "BULLISH":
        score += 20
    elif macd_sig == "NEUTRAL":
        score += 10
    
    # 4. Volume Confirmation (15 pts)
    vol_ratio = calculate_volume_ratio(volume)
    details['vol_ratio'] = vol_ratio
    if vol_ratio > 1.2:  # Above average volume confirms trend
        score += 15
    elif vol_ratio > 0.8:
        score += 10
    
    # 5. Relative Strength vs SPY (15 pts)
    if spy_close is not None:
        rs = calculate_rs_vs_benchmark(close, spy_close)
        details['rs_vs_spy'] = rs
        if rs > 2:  # Outperforming SPY by 2%+
            score += 15
        elif rs > 0:
            score += 10
        elif rs > -2:
            score += 5
    else:
        details['rs_vs_spy'] = 0
    
    score = int(min(100, max(0, score)))
    signal = "BULLISH" if score >= 70 else ("BEARISH" if score < 40 else "NEUTRAL")
    return score, signal, details

def run_us_market_gate() -> USMarketGateResult:
    """Run enhanced US Market Gate Analysis"""
    logger.info("🇺🇸 Starting Enhanced US Market Gate Analysis...")
    
    all_tickers = ["SPY", "QQQ", "^VIX"] + list(SECTORS.values())
    try:
        data = yf.download(all_tickers, period="1y", progress=False)
        if data.empty:
            raise ValueError("No data from yfinance")
        
        # SPY Analysis for overall gate
        spy_close = data['Close']['SPY'].dropna()
        spy_volume = data['Volume']['SPY'].dropna()
        overall_score, overall_signal, overall_details = calculate_enhanced_score(spy_close, spy_volume)
        
        # Sector breakdown
        sectors_results = []
        for name, ticker in SECTORS.items():
            try:
                s_close = data['Close'][ticker].dropna()
                s_volume = data['Volume'][ticker].dropna()
                s_score, s_signal, s_details = calculate_enhanced_score(s_close, s_volume, spy_close)
                
                price = float(s_close.iloc[-1])
                prev = float(s_close.iloc[-2])
                change_1d = (price - prev) / prev * 100
                
                sectors_results.append(SectorResult(
                    name=name, ticker=ticker, score=s_score, signal=s_signal,
                    price=price, change_1d=change_1d,
                    rsi=s_details.get('rsi', 50),
                    rs_vs_spy=s_details.get('rs_vs_spy', 0)
                ))
            except Exception as e:
                logger.error(f"Error analyzing sector {ticker}: {e}")
        
        # Sort by score descending
        sectors_results.sort(key=lambda x: x.score, reverse=True)
        
        # Reasons
        reasons = []
        vix = float(data['Close']['^VIX'].iloc[-1])
        
        if overall_score >= 70:
            reasons.append(f"SPY shows strong alignment: {overall_details.get('trend', 'N/A')}.")
        elif overall_score < 40:
            reasons.append("Market is in a downtrend. Exercise caution.")
        else:
            reasons.append("Market is consolidating. Wait for clarity.")
        
        reasons.append(f"RSI({overall_details.get('rsi', 0):.1f}), MACD: {overall_details.get('macd', 'N/A')}")
        
        if vix > 25:
            reasons.append(f"⚠️ VIX elevated at {vix:.1f}")
        
        # Top/Bottom sectors
        if sectors_results:
            reasons.append(f"🔥 Top: {sectors_results[0].name} ({sectors_results[0].score})")
            reasons.append(f"❄️ Bottom: {sectors_results[-1].name} ({sectors_results[-1].score})")
        
        # Gate Decision
        if overall_score >= 70: gate = "GREEN"
        elif overall_score >= 45: gate = "YELLOW"
        else: gate = "RED"
        
        return USMarketGateResult(
            gate=gate, score=overall_score, reasons=reasons,
            sectors=sectors_results,
            metrics={"vix": vix, "spy_price": float(spy_close.iloc[-1]), "rsi": overall_details.get('rsi', 50)}
        )
        
    except Exception as e:
        logger.error(f"US Market Gate Error: {e}")
        return USMarketGateResult(gate="YELLOW", score=50, reasons=[str(e)], sectors=[], metrics={"vix": None, "spy_price": None, "rsi": None})

if __name__ == "__main__":
    res = run_us_market_gate()
    print(f"\n🇺🇸 US Gate: {res.gate} ({res.score}/100)")
    print(f"Reasons: {res.reasons}")
    for s in res.sectors:
        print(f"  - {s.name}: {s.score} | RSI: {s.rsi:.1f} | RS: {s.rs_vs_spy:+.1f}%")
