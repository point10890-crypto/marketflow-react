#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Super Performance Scanner v2.0 (Enhanced VCP Detector)
Based on Mark Minervini's SEPA methodology with production-grade filters:
1. Trend Template (Stage 2 Uptrend)
2. Volatility Contraction Pattern (VCP) - Multi-contraction detection
3. Fundamental Filters (EPS/Revenue Growth, ROE)
4. Market Regime Filter (SPY Stage 2)
5. Pivot/Breakout Validation
6. Liquidity & Operational Filters
"""

import os
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timedelta
from tqdm import tqdm
import warnings

warnings.filterwarnings('ignore')

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SuperPerformanceScanner:
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'super_performance_picks.csv')
        self.prices_df = None
        self.spy_data = None
        self.market_regime_ok = True
        # Thresholds (overridden by regime config if available)
        self.min_trend_score = 6
        self.min_rs_rating = 60
        self.max_base_depth = 0.30
        self._load_regime_config()

    def _load_regime_config(self):
        """Load adaptive thresholds from regime_config.json if available"""
        config_path = os.path.join(self.data_dir, 'output', 'regime_config.json')
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    import json
                    config = json.load(f)
                vcp_cfg = config.get('vcp_scanner', {})
                if vcp_cfg:
                    self.min_trend_score = vcp_cfg.get('min_trend_score', self.min_trend_score)
                    self.min_rs_rating = vcp_cfg.get('min_rs_rating', self.min_rs_rating)
                    self.max_base_depth = vcp_cfg.get('max_base_depth', self.max_base_depth)
                    logger.info("📋 Loaded regime config for vcp_scanner")
        except Exception:
            pass
        
    def load_data(self):
        """Load necessary data"""
        try:
            # Load SPY for Relative Strength and Market Regime
            spy = yf.Ticker("SPY")
            self.spy_data = spy.history(period="1y")
            
            # Check market regime first
            self.market_regime_ok = self.check_market_regime()
            
            # Use stocks list
            stocks_file = os.path.join(self.data_dir, 'data', 'us_stocks_list.csv')
            if os.path.exists(stocks_file):
                self.stocks_df = pd.read_csv(stocks_file)
                return True
            else:
                # Fallback: create from universe seed or volume analysis
                vol_file = os.path.join(self.data_dir, 'output', 'us_volume_analysis.csv')
                if os.path.exists(vol_file):
                    self.stocks_df = pd.read_csv(vol_file)[['ticker']]
                    return True
            return False
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            return False

    # ==================== MARKET REGIME FILTER ====================
    def check_market_regime(self) -> bool:
        """Check if SPY is in Stage 2 (favorable market regime)"""
        try:
            if self.spy_data is None or len(self.spy_data) < 200:
                return True  # Fail-open if no data
                
            close = self.spy_data['Close']
            sma_50 = close.rolling(50).mean().iloc[-1]
            sma_200 = close.rolling(200).mean().iloc[-1]
            sma_200_slope = close.rolling(200).mean().iloc[-1] - close.rolling(200).mean().iloc[-20]
            current = close.iloc[-1]
            
            is_ok = current > sma_50 and current > sma_200 and sma_200_slope > 0
            
            if not is_ok:
                logger.warning("⚠️  MARKET REGIME WARNING: SPY not in Stage 2 uptrend!")
            else:
                logger.info("✅ Market Regime: SPY in Stage 2 uptrend")
                
            return is_ok
        except Exception as e:
            logger.warning(f"Market regime check failed: {e}")
            return True  # Fail-open

    # ==================== TREND TEMPLATE ====================
    def check_trend_template(self, hist: pd.DataFrame) -> dict:
        """
        Mark Minervini's Trend Template (Stage 2)
        Returns trend_score (0-7) based on criteria passed
        """
        try:
            if len(hist) < 200:
                return {'passed': False, 'reason': 'Insufficient Data', 'trend_score': 0}
                
            close = hist['Close']
            
            # Moving Averages
            sma_50 = close.rolling(window=50).mean().iloc[-1]
            sma_150 = close.rolling(window=150).mean().iloc[-1]
            sma_200 = close.rolling(window=200).mean().iloc[-1]
            
            # 200 SMA Trend (Slope of last 20 days)
            sma_200_series = close.rolling(window=200).mean()
            sma_200_slope = (sma_200_series.iloc[-1] - sma_200_series.iloc[-20]) / 20
            
            # 52-Week High/Low (use available data if fewer than 252 bars)
            window_52w = min(252, len(close))
            low_52w = close.rolling(window=window_52w).min().iloc[-1]
            high_52w = close.rolling(window=window_52w).max().iloc[-1]
            current_price = close.iloc[-1]
            
            # Conditions
            c1 = current_price > sma_150 and current_price > sma_200
            c2 = sma_150 > sma_200
            c3 = sma_200_slope > 0
            c4 = sma_50 > sma_150 and sma_50 > sma_200
            c5 = current_price > sma_50
            c6 = current_price >= (1.25 * low_52w)  # 25% above 52w low
            c7 = current_price >= (0.75 * high_52w)  # Within 25% of 52w high
            
            trend_score = sum([c1, c2, c3, c4, c5, c6, c7])
            passed = trend_score >= 6  # Allow 1 miss
            
            return {
                'passed': passed,
                'current_price': current_price,
                'sma_50': sma_50,
                'sma_200': sma_200,
                'high_52w': high_52w,
                'pct_off_high': (current_price / high_52w) - 1,
                'trend_score': trend_score
            }
        except Exception as e:
            return {'passed': False, 'reason': str(e), 'trend_score': 0}

    # ==================== FUNDAMENTAL FILTERS ====================
    def check_fundamentals(self, info: dict) -> dict:
        """Check fundamental quality (EPS growth, ROE, margins)"""
        try:
            eps_growth = info.get('earningsQuarterlyGrowth') or 0
            revenue_growth = info.get('revenueGrowth') or 0
            roe = info.get('returnOnEquity') or 0
            profit_margin = info.get('profitMargins') or 0
            
            fund_score = 0
            
            # EPS Growth
            if eps_growth > 0.20: fund_score += 15
            if eps_growth > 0.25: fund_score += 10  # Acceleration bonus
            
            # Revenue Growth
            if revenue_growth > 0.10: fund_score += 10
            if revenue_growth > 0.20: fund_score += 5
            
            # Profitability
            if roe > 0.15: fund_score += 10
            if profit_margin > 0.10: fund_score += 5
            
            return {
                'fund_score': fund_score,
                'eps_growth': round(eps_growth * 100, 1) if eps_growth else 0,
                'revenue_growth': round(revenue_growth * 100, 1) if revenue_growth else 0,
                'roe': round(roe * 100, 1) if roe else 0
            }
        except:
            return {'fund_score': 0, 'eps_growth': 0, 'revenue_growth': 0, 'roe': 0}

    # ==================== ENHANCED VCP DETECTION ====================
    def detect_vcp_pattern(self, hist: pd.DataFrame) -> dict:
        """
        Enhanced VCP Detection with multi-contraction analysis
        - Detects sequential contractions with diminishing depth
        - Validates volume dry-up during each contraction
        - Identifies pivot point formation
        """
        try:
            close = hist['Close'].values
            volume = hist['Volume'].values
            
            # 1. Find local peaks and troughs for contraction detection
            contractions = self._find_contractions(close)
            
            # 2. Check for diminishing contraction depths
            is_diminishing = False
            num_contractions = len(contractions)
            
            if num_contractions >= 2:
                depths = [c['depth'] for c in contractions[-3:]]  # Last 3
                is_diminishing = all(depths[i] > depths[i+1] for i in range(len(depths)-1))
            
            # 3. Base depth and duration constraints
            if contractions:
                last_contraction = contractions[-1]
                base_depth = last_contraction['depth']
                base_duration = last_contraction.get('duration', 0)
                
                # Exclude too deep (>35%) or too shallow (<5%) bases
                valid_depth = 0.05 <= base_depth <= 0.35
                # Base duration: 3-26 weeks (15-130 trading days)
                valid_duration = 15 <= base_duration <= 130
            else:
                base_depth = 0
                base_duration = 0
                valid_depth = False
                valid_duration = True  # Don't penalize if no clear base
            
            # 4. Price Tightness (current consolidation)
            recent_20 = hist['Close'].iloc[-20:]
            recent_vol = recent_20.std() / recent_20.mean()
            is_tight = recent_vol < 0.05  # < 5% volatility
            
            # 5. Volume Dry Up
            # Exclude last 10 days from baseline to avoid diluting the comparison
            vol_10_avg = hist['Volume'].iloc[-10:].mean()
            vol_baseline = hist['Volume'].iloc[-50:-10].mean() if len(hist) >= 50 else hist['Volume'].iloc[:-10].mean()
            volume_dry_up = vol_10_avg < (vol_baseline * 0.7)  # 30% below baseline
            
            # 6. Pivot Point (last 5 days extremely tight)
            last_5 = hist['Close'].iloc[-5:]
            pivot_range = (last_5.max() - last_5.min()) / last_5.mean()
            is_pivot = pivot_range < 0.03  # range < 3%
            pivot_price = last_5.max()
            
            # Calculate VCP Score (0-100)
            vcp_score = 0
            if is_tight: vcp_score += 25
            if volume_dry_up: vcp_score += 20
            if is_pivot: vcp_score += 25
            if is_diminishing: vcp_score += 15
            if valid_depth: vcp_score += 10
            if num_contractions >= 2: vcp_score += 5
            
            return {
                'vcp_score': min(vcp_score, 100),
                'is_pivot': is_pivot,
                'pivot_price': round(pivot_price, 2),
                'tightness': round(recent_vol * 100, 2),
                'pivot_range': round(pivot_range * 100, 2),
                'volume_dry': volume_dry_up,
                'num_contractions': num_contractions,
                'is_diminishing': is_diminishing,
                'base_depth': round(base_depth * 100, 1),
                'base_valid': valid_depth and valid_duration
            }
        except Exception as e:
            return {
                'vcp_score': 0, 'is_pivot': False, 'pivot_price': 0,
                'tightness': 0, 'pivot_range': 0, 'volume_dry': False,
                'num_contractions': 0, 'is_diminishing': False,
                'base_depth': 0, 'base_valid': False
            }
    
    def _find_contractions(self, close: np.ndarray) -> list:
        """Find price contractions (pullbacks from local highs).

        After finding a contraction, skip forward past the trough to avoid
        detecting overlapping contractions from nearby peaks.
        """
        contractions = []
        try:
            window = 10
            i = window
            while i < len(close) - window:
                # Local high
                if close[i] == max(close[i-window:i+window+1]):
                    # Find next local low
                    found = False
                    for j in range(i+1, min(i+60, len(close)-window)):
                        if close[j] == min(close[max(0,j-window):j+window+1]):
                            depth = (close[i] - close[j]) / close[i]
                            if depth > 0.03:  # Minimum 3% pullback
                                contractions.append({
                                    'high_idx': i,
                                    'low_idx': j,
                                    'depth': depth,
                                    'duration': j - i
                                })
                                # Skip forward past the trough to avoid overlapping
                                i = j + window
                                found = True
                            break
                    if not found:
                        i += 1
                else:
                    i += 1
        except Exception:
            pass
        return contractions

    # ==================== BREAKOUT VALIDATION ====================
    def validate_breakout(self, hist: pd.DataFrame, pivot_price: float) -> dict:
        """Validate if breakout is confirmed with volume"""
        try:
            current_price = hist['Close'].iloc[-1]
            current_volume = hist['Volume'].iloc[-1]
            avg_volume_50 = hist['Volume'].iloc[-50:].mean()
            
            is_above_pivot = current_price > pivot_price
            volume_ratio = current_volume / avg_volume_50 if avg_volume_50 > 0 else 1
            volume_surge = volume_ratio > 1.5  # 50% above average
            
            # Extended check: not more than 5% above pivot (avoid chasing)
            pct_above_pivot = (current_price / pivot_price - 1) * 100
            is_extended = pct_above_pivot > 5
            
            breakout_confirmed = is_above_pivot and volume_surge and not is_extended
            
            return {
                'breakout_confirmed': breakout_confirmed,
                'pct_above_pivot': round(pct_above_pivot, 2),
                'volume_ratio': round(volume_ratio, 2),
                'is_extended': is_extended
            }
        except:
            return {'breakout_confirmed': False, 'pct_above_pivot': 0, 'volume_ratio': 1, 'is_extended': False}

    # ==================== LIQUIDITY FILTER ====================
    def check_liquidity(self, hist: pd.DataFrame, current_price: float) -> dict:
        """Check liquidity requirements"""
        try:
            avg_vol = hist['Volume'].iloc[-20:].mean()
            avg_dollar_vol = avg_vol * current_price
            
            meets_volume = avg_vol > 200000  # 200K shares
            meets_dollar_vol = avg_dollar_vol > 2_000_000  # $2M daily
            meets_price = current_price > 5  # Above $5
            
            liquidity_ok = meets_volume and meets_dollar_vol and meets_price
            
            return {
                'liquidity_ok': liquidity_ok,
                'avg_volume': int(avg_vol),
                'avg_dollar_vol': round(avg_dollar_vol / 1_000_000, 2)  # in millions
            }
        except:
            return {'liquidity_ok': False, 'avg_volume': 0, 'avg_dollar_vol': 0}

    # ==================== RELATIVE STRENGTH ====================
    def calculate_rs_rating(self, hist: pd.DataFrame) -> float:
        """Calculate Relative Strength Rating (1-99)"""
        try:
            if self.spy_data is None:
                return 50
                
            # 3 month performance vs SPY
            stock_ret = (hist['Close'].iloc[-1] / hist['Close'].iloc[-63]) - 1 if len(hist) >= 63 else 0
            
            spy_slice = self.spy_data.iloc[-63:] if len(self.spy_data) >= 63 else self.spy_data
            spy_ret = (spy_slice['Close'].iloc[-1] / spy_slice['Close'].iloc[0]) - 1 if len(spy_slice) > 0 else 0
            
            rs_raw = stock_ret - spy_ret
            # Normalize to 1-99 scale
            rs_rating = 50 + (rs_raw * 200)  # Amplify difference
            return min(99, max(1, rs_rating))
        except:
            return 50

    # ==================== MAIN ANALYSIS ====================
    def analyze_stock(self, ticker: str) -> dict:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1y")
            
            if len(hist) < 200:
                return None
            
            # 1. Trend Template Check
            trend = self.check_trend_template(hist)
            if not trend['passed'] and trend['trend_score'] < (self.min_trend_score - 1):
                return None
            
            # 2. Liquidity Check
            liquidity = self.check_liquidity(hist, trend['current_price'])
            if not liquidity['liquidity_ok']:
                return None
                
            # 3. RS Rating
            rs_rating = self.calculate_rs_rating(hist)
            if rs_rating < self.min_rs_rating:  # Must be stronger than market
                return None
                
            # 4. VCP Pattern Check
            vcp = self.detect_vcp_pattern(hist)
            
            # 5. Breakout Validation
            breakout = self.validate_breakout(hist, vcp['pivot_price'])
            
            # 6. Fundamental Check
            info = stock.info
            fundamentals = self.check_fundamentals(info)
            
            # 7. Calculate Composite Score
            score = (
                trend['trend_score'] * 10 +      # 0-70
                vcp['vcp_score'] +                # 0-100
                fundamentals['fund_score'] +      # 0-55
                rs_rating * 0.3 +                 # 0-30
                (20 if breakout['breakout_confirmed'] else 0)  # Breakout bonus
            )
            
            # Apply market regime penalty
            if not self.market_regime_ok:
                score *= 0.8  # 20% penalty in bearish market
            
            # Determine Phase
            setup_phase = self._determine_phase(vcp, trend, breakout)
            
            # Company info
            nm = info.get('shortName') or info.get('longName') or ticker
            sector = info.get('sector', 'Unknown')
            
            return {
                'ticker': ticker,
                'name': nm[:30],  # Truncate long names
                'sector': sector,
                'price': round(trend['current_price'], 2),
                'rs_rating': round(rs_rating, 1),
                'vcp_score': vcp['vcp_score'],
                'fund_score': fundamentals['fund_score'],
                'setup_phase': setup_phase,
                'pivot_tightness': f"{vcp['pivot_range']:.1f}%",
                'vol_dry_up': "Yes" if vcp['volume_dry'] else "No",
                'contractions': vcp['num_contractions'],
                'base_depth': f"{vcp['base_depth']:.0f}%",
                'eps_growth': f"{fundamentals['eps_growth']:.0f}%",
                'breakout': "Yes" if breakout['breakout_confirmed'] else "No",
                'pivot_price': vcp['pivot_price'],
                'score': round(score, 1)
            }
            
        except Exception as e:
            return None

    def _determine_phase(self, vcp: dict, trend: dict, breakout: dict) -> str:
        """Determine the current setup phase"""
        if breakout['breakout_confirmed']:
            return "🔥 Breakout"
        elif vcp['is_pivot']:
            return "⚡ Pivot"
        elif vcp['vcp_score'] >= 70:
            return "📊 Tightening"
        elif trend['pct_off_high'] > -0.05:
            return "📈 Near Highs"
        elif vcp['num_contractions'] >= 2:
            return "⏳ Building"
        else:
            return "Consolidating"

    def run(self):
        logger.info("🚀 Starting Super Performance Scanner v2.0 (Enhanced VCP)...")
        if not self.load_data():
            logger.error("Failed to load base data.")
            return
            
        tickers = self.stocks_df['ticker'].tolist()
        results = []
        
        logger.info(f"🔍 Scanning {len(tickers)} stocks for VCP patterns...")
        for ticker in tqdm(tickers):
            res = self.analyze_stock(ticker)
            if res:
                results.append(res)
                
        if not results:
            logger.warning("No VCP candidates found.")
            return
            
        df = pd.DataFrame(results)
        df = df.sort_values('score', ascending=False).head(30)  # Top 30
        
        df.to_csv(self.output_file, index=False)
        logger.info(f"✅ Saved {len(df)} Super Performance Candidates to {self.output_file}")
        
        # Print summary
        print("\n" + "="*60)
        print("🏆 TOP 10 VCP CANDIDATES")
        print("="*60)
        print(df[['ticker', 'name', 'setup_phase', 'vcp_score', 'score']].head(10).to_string(index=False))
        print("="*60)
        
        # Breakout alerts
        breakouts = df[df['breakout'] == 'Yes']
        if len(breakouts) > 0:
            print("\n🔥 BREAKOUT ALERTS:")
            print(breakouts[['ticker', 'name', 'price', 'score']].to_string(index=False))


if __name__ == "__main__":
    scanner = SuperPerformanceScanner(data_dir=os.path.dirname(os.path.abspath(__file__)))
    scanner.run()
