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
import json
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
        self.output_dir = os.path.join(data_dir, 'output')

    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            if value is None or pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _safe_str(value, default=''):
        try:
            if value is None or pd.isna(value):
                return default
            return str(value)
        except Exception:
            return default
        
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
                'name': self._safe_str(row.get('name'), ticker),
                'sector': self._safe_str(row.get('sector'), 'Unknown'),
                'rec_date': rec_date.strftime('%Y-%m-%d'),
                'strategy': row.get('strategy_type', 'Unknown'),
                'grade': self._safe_str(row.get('grade'), '-'),
                'recommendation': self._safe_str(row.get('recommendation'), ''),
                'composite_score': self._safe_float(row.get('composite_score')),
                'rec_price': self._safe_float(rec_price),
                'curr_price': self._safe_float(curr_price),
                'return': self._safe_float(total_return),
                'alpha': self._safe_float(alpha),
                'days': int(days_held)
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
        
        # Save reports used by scheduler verification and /api/us/track-record.
        os.makedirs(self.output_dir, exist_ok=True)
        csv_path = os.path.join(self.output_dir, 'performance_report.csv')
        json_path = os.path.join(self.output_dir, 'performance_report.json')
        results_df.to_csv(csv_path, index=False)

        returns = results_df['return'].tolist()
        alphas = results_df['alpha'].tolist()
        by_date = []
        for rec_date, group in results_df.groupby('rec_date'):
            group_returns = group['return'].tolist()
            win_count = int((group['return'] > 0).sum())
            by_date.append({
                'date': rec_date,
                'picks_count': int(len(group)),
                'avg_return': round(float(np.mean(group_returns)), 2),
                'avg_alpha': round(float(group['alpha'].mean()), 2),
                'win_rate': round(win_count / len(group) * 100, 1),
                'win_count': win_count,
                'loss_count': int(len(group) - win_count),
            })
        by_date = sorted(by_date, key=lambda x: x['date'], reverse=True)

        best = results_df.loc[results_df['return'].idxmax()]
        worst = results_df.loc[results_df['return'].idxmin()]
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': {
                'total_picks': int(len(results_df)),
                'unique_tickers': int(results_df['ticker'].nunique()),
                'snapshots': int(results_df['rec_date'].nunique()),
                'tracking_period': f"{results_df['rec_date'].min()} ~ {results_df['rec_date'].max()}",
                'win_rate': round(float((results_df['return'] > 0).mean() * 100), 1),
                'avg_return': round(float(np.mean(returns)), 2),
                'avg_alpha': round(float(np.mean(alphas)), 2),
                'max_gain': {'pct': round(float(best['return']), 2), 'ticker': best['ticker']},
                'max_loss': {'pct': round(float(worst['return']), 2), 'ticker': worst['ticker']},
                'total_winners': int((results_df['return'] > 0).sum()),
                'total_losers': int((results_df['return'] <= 0).sum()),
            },
            'snapshots': by_date,
            'picks': [
                {
                    'ticker': row['ticker'],
                    'name': row['name'],
                    'sector': row['sector'],
                    'snapshot_date': row['rec_date'],
                    'entry_price': round(float(row['rec_price']), 2),
                    'current_price': round(float(row['curr_price']), 2),
                    'return_pct': round(float(row['return']), 2),
                    'alpha': round(float(row['alpha']), 2),
                    'days': int(row['days']),
                    'composite_score': round(float(row.get('composite_score', 0)), 1),
                    'grade': row.get('grade', '-'),
                    'recommendation': row.get('recommendation', ''),
                    'strategy': row.get('strategy', ''),
                }
                for _, row in results_df.sort_values(['rec_date', 'return'], ascending=[False, False]).iterrows()
            ],
            'by_grade': results_df['grade'].fillna('-').value_counts().to_dict(),
            'by_sector': results_df['sector'].fillna('Unknown').value_counts().to_dict(),
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Saved detailed reports to %s and %s", csv_path, json_path)

if __name__ == "__main__":
    tracker = PerformanceTracker()
    tracker.run()
