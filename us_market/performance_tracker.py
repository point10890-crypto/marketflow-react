#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Tracker for Smart Money Picks
- Reads archived recommendation files (us_market/archive/*.csv)
- Fetches current prices using yfinance
- Calculates Win Rate, Average Return, and Alpha vs SPY
- Generates a summary report
"""

import os
import glob
import pandas as pd
import yfinance as yf
import logging
from datetime import datetime, timedelta
import numpy as np

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PerformanceTracker:
    def __init__(self, data_dir: str = 'us_market'):
        self.data_dir = data_dir
        self.archive_dir = os.path.join(data_dir, 'archive')
        
    def load_archives(self) -> pd.DataFrame:
        """Load all archived pick files"""
        all_picks = []
        files = glob.glob(os.path.join(self.archive_dir, 'picks_*.csv'))
        
        if not files:
            logger.warning("⚠️ No archived picks found.")
            return pd.DataFrame()
            
        logger.info(f"📂 Found {len(files)} archive files.")
        
        for f in files:
            try:
                # Extract date from filename: picks_YYYYMMDD.csv
                basename = os.path.basename(f)
                date_str = basename.replace('picks_', '').replace('.csv', '')
                rec_date = datetime.strptime(date_str, '%Y%m%d')
                
                df = pd.read_csv(f)
                df['rec_date'] = rec_date
                
                # Keep only top 10 for performance tracking to be strict
                df = df.head(10)
                
                all_picks.append(df)
            except Exception as e:
                logger.error(f"Error reading {f}: {e}")
                
        if not all_picks:
            return pd.DataFrame()
            
        combined_df = pd.concat(all_picks, ignore_index=True)
        return combined_df

    def fetch_current_prices(self, tickers: list) -> dict:
        """Fetch current prices for all tickers"""
        if not tickers:
            return {}
            
        logger.info(f"💰 Fetching current prices for {len(tickers)} stocks...")
        try:
            # Batch download is efficient
            # We also need SPY for benchmark
            tickers_with_spy = tickers + ['SPY']
            data = yf.download(tickers_with_spy, period='5d', progress=False)['Close']
            
            current_prices = {}
            if not data.empty:
                last_prices = data.iloc[-1]
                for t in tickers_with_spy:
                    if t in last_prices:
                        current_prices[t] = last_prices[t]
            return current_prices
        except Exception as e:
            logger.error(f"Error fetching prices: {e}")
            return {}

    def run(self):
        """Run performance analysis"""
        logger.info("🚀 Starting Performance Tracking...")
        
        df = self.load_archives()
        if df.empty:
            logger.warning("No data to analyze.")
            return
        
        # Get unique tickers
        tickers = df['ticker'].unique().tolist()
        current_prices = self.fetch_current_prices(tickers)
        spy_price = current_prices.get('SPY')
        
        if not current_prices:
            logger.error("Failed to fetch current prices.")
            return

        # Calculate returns
        results = []
        
        # We need SPY history to calculate Alpha properly (SPY return from rec_date to now)
        # For simplicity in this version, we will approximate Alpha using current SPY vs 'rec_price' of SPY if recorded.
        # Since we didn't record SPY price in archive, we will fetch SPY history.
        spy_hist = yf.Ticker("SPY").history(period="1y")['Close']
        
        for idx, row in df.iterrows():
            ticker = row['ticker']
            rec_price = row['current_price'] # Price at recommendation
            rec_date = row['rec_date']
            curr_price = current_prices.get(ticker)
            
            if curr_price is None or pd.isna(curr_price):
                continue
                
            # Calculate metrics
            total_return = (curr_price - rec_price) / rec_price * 100
            days_held = (datetime.now() - rec_date).days
            
            # SPY Return over same period
            try:
                # Find closest trading day for SPY rec price
                spy_rec_price = spy_hist.asof(rec_date)
                if pd.isna(spy_rec_price):
                    # Fallback if too old or weekend
                    spy_rec_price = spy_hist.iloc[0] 
                
                spy_return = (spy_price - spy_rec_price) / spy_rec_price * 100
            except:
                spy_return = 0
            
            alpha = total_return - spy_return
            
            results.append({
                'ticker': ticker,
                'rec_date': rec_date.strftime('%Y-%m-%d'),
                'strategy': row.get('strategy_type', 'Unknown'),
                'rec_price': rec_price,
                'curr_price': curr_price,
                'return': total_return,
                'alpha': alpha,
                'days': days_held
            })
            
        if not results:
            logger.warning("No results calculated.")
            return
            
        results_df = pd.DataFrame(results)
        
        # Summary Statistics
        avg_return = results_df['return'].mean()
        win_rate = (results_df['return'] > 0).mean() * 100
        avg_alpha = results_df['alpha'].mean()
        
        print(f"\n{'='*60}")
        print(f"📊 PERFORMANCE REPORT (Forward Testing)")
        print(f"{'='*60}")
        print(f"Total Recommendations: {len(results_df)}")
        print(f"✅ Win Rate: {win_rate:.1f}%")
        print(f"📈 Avg Return: {avg_return:+.1f}%")
        print(f"🦁 Avg Alpha (vs SPY): {avg_alpha:+.1f}%")
        
        print(f"\n🏆 Best Performers:")
        print(results_df.nlargest(3, 'return')[['ticker', 'rec_date', 'return', 'alpha']].to_string(index=False))
        
        print(f"\n💀 Worst Performers:")
        print(results_df.nsmallest(3, 'return')[['ticker', 'rec_date', 'return', 'alpha']].to_string(index=False))
        
        # Save report
        results_df.to_csv(os.path.join(self.data_dir, 'output', 'performance_report.csv'), index=False)
        logger.info("Saved detailed report to us_market/performance_report.csv")

if __name__ == "__main__":
    tracker = PerformanceTracker()
    tracker.run()
