#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Earnings Analyzer
- Tracks upcoming earnings dates
- Analyzes historical earnings surprises
- Identifies strong earnings momentum
"""

import os
import json
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EarningsAnalyzer:
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        self.output_file = os.path.join(data_dir, 'output', 'earnings_analysis.json')
        
    def get_earnings_data(self, ticker: str) -> Dict:
        """Get earnings calendar and surprise history"""
        try:
            stock = yf.Ticker(ticker)
            
            # 1. Get Calendar (Next Earnings)
            calendar = stock.calendar
            next_date = "N/A"
            if calendar and isinstance(calendar, dict):
                 # yfinance structure varies. Sometimes it's a dict passed as 'Earnings Date' list
                 dates = calendar.get('Earnings Date', [])
                 if dates:
                     next_date = dates[0].strftime('%Y-%m-%d')
            elif hasattr(stock, 'next_earnings_date') and stock.next_earnings_date:
                next_date = stock.next_earnings_date.strftime('%Y-%m-%d')
                
            # 2. Get Earnings History (Quarterly) via INCOME_STMT or generic info if unavailable
            # Actually yf.Ticker object has 'earnings_history' or 'earnings_dates' sometimes depending on version
            # But reliable way is stock.earnings_history which returns dataframe
            
            surprises = []
            
            # Fallback: some versions provide 'earnings_history'
            # Let's try to get earnings trend/surprise
            # Since yfinance API is tricky with earnings, we'll try a few attributes
            
            # Try getting 'quarterly_earnings' (revenue/earnings chart data)
            # But for "Surprise", we need analyst estimates. 
            # yfinance often exposes stock.earnings_history
            
            try:
                # This call is hypothetical based on common yfinance extensions or newer versions
                # If not available, we might skip surprise calculation or simulate
                hist = stock.earnings_history 
                if hist is not None and not hist.empty:
                    # Columns usually: ['EPS Estimate', 'EPS Actual', 'Difference', 'Surprise (%)']
                    # Sort by date descending
                    hist = hist.sort_index(ascending=False).head(4)
                    for date, row in hist.iterrows():
                        surprises.append({
                            'date': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                            'estimate': row.get('EPS Estimate', 0),
                            'actual': row.get('EPS Actual', 0),
                            'surprise_pct': row.get('Surprise (%)', 0)
                        })
            except:
                pass
                
            # Calculate momentum (only from actual surprise data, not growth)
            avg_surprise = 0
            if surprises:
                valid = [s['surprise_pct'] for s in surprises if s.get('surprise_pct') is not None]
                avg_surprise = sum(valid) / len(valid) if valid else 0
                
            return {
                'ticker': ticker,
                'next_earnings_date': next_date,
                'avg_surprise_pct': round(avg_surprise, 2),
                'surprises': surprises,
                'revenue_growth': stock.info.get('revenueGrowth', 0)
            }
            
        except Exception as e:
            logger.debug(f"Error getting earnings for {ticker}: {e}")
            return {'ticker': ticker, 'error': str(e)}

    def analyze_tickers(self, tickers: List[str]) -> Dict:
        """Analyze earnings for list of tickers"""
        logger.info(f"📅 Analyzing earnings for {len(tickers)} tickers...")
        
        results = {}
        upcoming = []
        strong_momentum = []
        
        for ticker in tickers:
            data = self.get_earnings_data(ticker)
            if 'error' not in data:
                results[ticker] = data
                
                # Check for upcoming earnings (within 14 days)
                next_date_str = data.get('next_earnings_date', 'N/A')
                if next_date_str != 'N/A':
                    try:
                        next_date = datetime.strptime(next_date_str, '%Y-%m-%d')
                        days_diff = (next_date - datetime.now()).days
                        if 0 <= days_diff <= 14:
                            upcoming.append({
                                'ticker': ticker,
                                'date': next_date_str,
                                'days_left': days_diff
                            })
                    except:
                        pass
                
                # Check momentum
                if data.get('avg_surprise_pct', 0) > 10: # >10% avg surprise
                    strong_momentum.append({
                        'ticker': ticker,
                        'avg_surprise': data['avg_surprise_pct'],
                        'revenue_growth': data.get('revenue_growth', 0)
                    })
                    
        # Sort lists
        upcoming.sort(key=lambda x: x['days_left'])
        strong_momentum.sort(key=lambda x: x['avg_surprise'], reverse=True)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'upcoming_earnings': upcoming,
            'strong_momentum': strong_momentum,
            'details': results
        }
        
    def save_results(self, data: Dict):
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Saved earnings analysis to {self.output_file}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', nargs='+', help='List of tickers')
    args = parser.parse_args()
    
    analyzer = EarningsAnalyzer()
    
    # Default watchlist from picks
    target_tickers = args.tickers
    if not target_tickers:
        try:
            picks_file = 'output/smart_money_picks_v2.csv'
            if os.path.exists(picks_file):
                df = pd.read_csv(picks_file)
                target_tickers = df['ticker'].tolist()[:30]
            else:
                picks_file = 'smart_money_picks.csv'
                if os.path.exists(picks_file):
                    df = pd.read_csv(picks_file)
                    target_tickers = df['ticker'].tolist()[:30]
                else:
                    target_tickers = ['NVDA', 'MSFT', 'META', 'AMZN', 'AAPL', 'TSLA', 'GOOGL']
        except:
            target_tickers = ['NVDA', 'MSFT']
             
    result = analyzer.analyze_tickers(target_tickers)
    analyzer.save_results(result)
    
    print("\n" + "="*60)
    print("📅 EARNINGS ANALYSIS HIGHLIGHTS")
    print("="*60)
    
    if result['upcoming_earnings']:
        print("\n🚀 Upcoming Earnings (Next 2 Weeks):")
        for item in result['upcoming_earnings']:
            print(f"  - {item['ticker']}: {item['date']} ({item['days_left']} days left)")
    else:
        print("\nℹ️ No upcoming earnings in next 2 weeks for these stocks.")
        
    print("\n💎 Strong Earnings Momentum (Avg Surprise > 10%):")
    for item in result['strong_momentum'][:5]:
        rev = item.get('revenue_growth') or 0
        print(f"  - {item['ticker']}: +{item['avg_surprise']}% Surprise (Rev Growth: {rev*100:.1f}%)")

if __name__ == "__main__":
    main()
