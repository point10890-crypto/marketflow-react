#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Stock Supply/Demand Analysis - Volume Technical Indicators
Calculates OBV, Accumulation/Distribution Line, Volume Surge Detection
"""

import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from tqdm import tqdm

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VolumeAnalyzer:
    """Volume-based technical analysis for supply/demand detection"""
    
    def __init__(self, data_dir: str = None):
        if data_dir is None or data_dir == '.':
            # Default to script directory for robustness
            data_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.data_dir = data_dir
        self.prices_file = os.path.join(data_dir, 'data', 'us_daily_prices.csv')
        self.output_file = os.path.join(data_dir, 'output', 'us_volume_analysis.csv')
        
    def load_prices(self) -> pd.DataFrame:
        """Load daily price data"""
        if not os.path.exists(self.prices_file):
            raise FileNotFoundError(f"Price file not found: {self.prices_file}")
        
        logger.info(f"📂 Loading prices from {self.prices_file}")
        df = pd.read_csv(self.prices_file)
        # Normalize columns: lowercase and map Close -> current_price
        df.columns = [c.lower() for c in df.columns]
        if 'close' in df.columns and 'current_price' not in df.columns:
            df.rename(columns={'close': 'current_price'}, inplace=True)
            
        if 'date' not in df.columns:
             # Fallback if normalization failed or different name
             if 'Date' in df.columns: df.rename(columns={'Date': 'date'}, inplace=True)
             
        df['date'] = pd.to_datetime(df['date'])
        return df
    
    def calculate_obv(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate On-Balance Volume (OBV)
        - Price up: Add volume
        - Price down: Subtract volume
        - Price unchanged: No change
        """
        obv = [0]
        for i in range(1, len(df)):
            if df['current_price'].iloc[i] > df['current_price'].iloc[i-1]:
                obv.append(obv[-1] + df['volume'].iloc[i])
            elif df['current_price'].iloc[i] < df['current_price'].iloc[i-1]:
                obv.append(obv[-1] - df['volume'].iloc[i])
            else:
                obv.append(obv[-1])
        return pd.Series(obv, index=df.index)
    
    def calculate_ad_line(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate Accumulation/Distribution Line
        CLV = ((Close - Low) - (High - Close)) / (High - Low)
        A/D = Previous A/D + CLV * Volume
        """
        high_low = df['high'] - df['low']
        high_low = high_low.replace(0, 0.0001)  # Avoid division by zero
        
        clv = ((df['current_price'] - df['low']) - (df['high'] - df['current_price'])) / high_low
        ad = (clv * df['volume']).cumsum()
        return ad
    
    def calculate_volume_sma(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Calculate Volume Simple Moving Average"""
        return df['volume'].rolling(window=period).mean()
    
    def detect_volume_surge(self, df: pd.DataFrame, threshold: float = 2.0) -> pd.Series:
        """
        Detect volume surges (volume > threshold * SMA)
        Returns boolean series
        """
        vol_sma = self.calculate_volume_sma(df, 20)
        return df['volume'] > (vol_sma * threshold)
    
    def calculate_mfi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calculate Money Flow Index (MFI) - Volume-weighted RSI
        """
        typical_price = (df['high'] + df['low'] + df['current_price']) / 3
        money_flow = typical_price * df['volume']
        
        delta = typical_price.diff()
        positive_flow = money_flow.where(delta > 0, 0)
        negative_flow = money_flow.where(delta < 0, 0)
        
        positive_mf = positive_flow.rolling(window=period).sum()
        negative_mf = negative_flow.rolling(window=period).sum()
        
        mfi = 100 - (100 / (1 + positive_mf / negative_mf.replace(0, 0.0001)))
        return mfi
    
    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Calculate Volume Weighted Average Price (daily VWAP approximation)"""
        typical_price = (df['high'] + df['low'] + df['current_price']) / 3
        return (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
    
    def analyze_supply_demand(self, df: pd.DataFrame) -> Dict:
        """
        Comprehensive supply/demand analysis
        Returns a dictionary with all indicators
        """
        if len(df) < 30:
            return None
        
        # Calculate all indicators
        df = df.sort_values('date').reset_index(drop=True)
        
        obv = self.calculate_obv(df)
        ad_line = self.calculate_ad_line(df)
        mfi = self.calculate_mfi(df)
        vol_surge = self.detect_volume_surge(df)
        
        # Get recent values
        latest = df.iloc[-1]
        recent_20 = df.tail(20)
        
        # OBV Trend (20-day) — use max absolute value as denominator to avoid near-zero noise
        obv_denom = max(abs(obv.iloc[-20]), abs(obv.tail(20).mean()), 1)
        obv_change = (obv.iloc[-1] - obv.iloc[-20]) / obv_denom * 100

        # A/D Trend (20-day)
        ad_denom = max(abs(ad_line.iloc[-20]), abs(ad_line.tail(20).mean()), 1)
        ad_change = (ad_line.iloc[-1] - ad_line.iloc[-20]) / ad_denom * 100
        
        # Volume Ratio (5-day avg vs 20-day avg)
        vol_5d = df['volume'].tail(5).mean()
        vol_20d = df['volume'].tail(20).mean()
        vol_ratio = vol_5d / vol_20d if vol_20d > 0 else 1
        
        # Recent volume surges
        surge_count_5d = vol_surge.tail(5).sum()
        surge_count_20d = vol_surge.tail(20).sum()
        
        # MFI current value
        mfi_current = mfi.iloc[-1] if not pd.isna(mfi.iloc[-1]) else 50
        
        # Supply/Demand Score (0-100)
        score = 50
        
        # OBV contribution
        if obv_change > 10:
            score += 15
        elif obv_change > 5:
            score += 10
        elif obv_change < -10:
            score -= 15
        elif obv_change < -5:
            score -= 10
        
        # A/D contribution
        if ad_change > 10:
            score += 15
        elif ad_change > 5:
            score += 10
        elif ad_change < -10:
            score -= 15
        elif ad_change < -5:
            score -= 10
        
        # Volume ratio contribution
        if vol_ratio > 1.5:
            score += 10
        elif vol_ratio > 1.2:
            score += 5
        elif vol_ratio < 0.7:
            score -= 5
        
        # MFI contribution
        if mfi_current > 70:
            score += 5  # Overbought but with buying pressure
        elif mfi_current < 30:
            score -= 5  # Oversold, possible capitulation
        
        score = max(0, min(100, score))
        
        # Determine stage
        if score >= 70:
            stage = "Strong Accumulation"
        elif score >= 55:
            stage = "Accumulation"
        elif score >= 45:
            stage = "Neutral"
        elif score >= 30:
            stage = "Distribution"
        else:
            stage = "Strong Distribution"
        
        return {
            'date': latest['date'],
            'obv': obv.iloc[-1],
            'obv_change_20d': round(obv_change, 2),
            'ad_line': ad_line.iloc[-1],
            'ad_change_20d': round(ad_change, 2),
            'mfi': round(mfi_current, 1),
            'vol_ratio_5d_20d': round(vol_ratio, 2),
            'surge_count_5d': int(surge_count_5d),
            'surge_count_20d': int(surge_count_20d),
            'supply_demand_score': round(score, 1),
            'supply_demand_stage': stage
        }
    
    def run(self) -> pd.DataFrame:
        """Run volume analysis for all stocks"""
        logger.info("🚀 Starting Volume Analysis...")
        
        # Load data
        df = self.load_prices()
        
        # Get unique tickers
        tickers = df['ticker'].unique()
        logger.info(f"📊 Analyzing {len(tickers)} stocks")
        
        results = []
        
        for ticker in tqdm(tickers, desc="Analyzing volume"):
            ticker_data = df[df['ticker'] == ticker].copy()
            
            if len(ticker_data) < 30:
                continue
            
            analysis = self.analyze_supply_demand(ticker_data)
            
            if analysis:
                result = {
                    'ticker': ticker,
                    'name': ticker_data['name'].iloc[-1] if 'name' in ticker_data.columns else ticker,
                    **analysis
                }
                results.append(result)
        
        # Create DataFrame
        results_df = pd.DataFrame(results)
        
        # Save results
        results_df.to_csv(self.output_file, index=False)
        logger.info(f"✅ Analysis complete! Saved to {self.output_file}")
        
        # Print summary
        logger.info("\n📊 Summary:")
        stage_counts = results_df['supply_demand_stage'].value_counts()
        for stage, count in stage_counts.items():
            logger.info(f"   {stage}: {count} stocks")
        
        return results_df


def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description='US Stock Volume Analysis')
    parser.add_argument('--dir', default='.', help='Data directory')
    args = parser.parse_args()
    
    analyzer = VolumeAnalyzer(data_dir=args.dir)
    results = analyzer.run()
    
    # Show top 10 accumulation stocks
    print("\n🔥 Top 10 Accumulation Stocks:")
    top_10 = results.nlargest(10, 'supply_demand_score')
    for _, row in top_10.iterrows():
        print(f"   {row['ticker']}: Score {row['supply_demand_score']} - {row['supply_demand_stage']}")


if __name__ == "__main__":
    main()
