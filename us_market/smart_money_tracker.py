#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart Money Tracker with History
- Saves daily analysis with timestamps
- Tracks price at recommendation vs current price
- Shows performance since recommendation
"""

import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime, date
from typing import Dict, List
import logging

# Setup curl_cffi session to bypass Yahoo bot protection
try:
    from curl_cffi import requests as curl_requests
    session = curl_requests.Session(impersonate="chrome")
    yf.Ticker._request_session = session
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SmartMoneyTracker:
    """Track Smart Money picks with historical performance"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.history_dir = os.path.join(data_dir, 'history')
        self.current_file = os.path.join(data_dir, 'output', 'smart_money_current.json')
        
        # Create history directory
        os.makedirs(self.history_dir, exist_ok=True)
    
    def get_today_filename(self) -> str:
        """Get filename for today's analysis"""
        return os.path.join(self.history_dir, f"picks_{date.today().isoformat()}.json")
    
    def load_current_data(self) -> Dict:
        """Load smart money picks and AI summaries"""
        # Load quantitative data
        quant_path = os.path.join(self.data_dir, 'output', 'smart_money_picks_v2.csv')
        if not os.path.exists(quant_path):
            raise FileNotFoundError(f"Smart money picks not found: {quant_path}")
        quant_df = pd.read_csv(quant_path)
        
        # Load AI summaries
        ai_path = os.path.join(self.data_dir, 'output', 'ai_summaries.json')
        ai_summaries = {}
        if os.path.exists(ai_path):
            with open(ai_path, 'r', encoding='utf-8') as f:
                ai_summaries = json.load(f)
        
        # Load final report
        report_path = os.path.join(self.data_dir, 'output', 'final_top10_report.json')
        final_report = {}
        if os.path.exists(report_path):
            with open(report_path, 'r', encoding='utf-8') as f:
                final_report = json.load(f)
        
        return quant_df, ai_summaries, final_report
    
    def get_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """Fetch current prices from local CSV or Yahoo Finance"""
        prices = {}

        # Try local CSV first (more reliable)
        csv_path = os.path.join(self.data_dir, 'data', 'us_daily_prices.csv')
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                # Get latest date
                latest_date = df['Date'].max()
                latest_df = df[df['Date'] == latest_date]

                for ticker in tickers:
                    row = latest_df[latest_df['Ticker'] == ticker]
                    if not row.empty:
                        prices[ticker] = round(float(row['Close'].iloc[0]), 2)
                return prices
            except Exception as e:
                logger.warning(f"CSV read failed, trying Yahoo: {e}")

        # Fallback to Yahoo Finance
        try:
            try:
                from curl_cffi import requests as curl_requests
                sess = curl_requests.Session(impersonate="chrome")
                data = yf.download(tickers, period='5d', progress=False, session=sess)
            except ImportError:
                data = yf.download(tickers, period='5d', progress=False)

            if not data.empty:
                closes = data['Close'].iloc[-1]
                for ticker in tickers:
                    if isinstance(closes, pd.Series):
                        price = closes.get(ticker, 0)
                        if pd.notna(price):
                            prices[ticker] = round(float(price), 2)
                    else:
                        prices[tickers[0]] = round(float(closes), 2)
        except Exception as e:
            logger.error(f"Error fetching prices: {e}")
        return prices
    
    def create_daily_snapshot(self, top_n: int = 10) -> Dict:
        """Create today's snapshot with all data"""
        logger.info("📸 Creating daily snapshot...")
        
        quant_df, ai_summaries, final_report = self.load_current_data()
        
        # Get top picks from final report
        top_picks = final_report.get('top_picks', [])[:top_n]
        
        if not top_picks:
            logger.warning("No top picks found in final report")
            return {}
        
        # Current prices
        tickers = [p['ticker'] for p in top_picks]
        current_prices = self.get_current_prices(tickers)
        
        # Create snapshot
        snapshot = {
            'analysis_date': date.today().isoformat(),
            'analysis_timestamp': datetime.now().isoformat(),
            'picks': []
        }
        
        for pick in top_picks:
            ticker = pick['ticker']
            price_at_analysis = pick.get('current_price', 0)
            
            snapshot['picks'].append({
                'ticker': ticker,
                'name': pick.get('name', ticker),
                'rank': pick.get('rank', 0),
                'final_score': pick.get('final_score', 0),
                'quant_score': pick.get('quant_score', 0),
                'ai_bonus': pick.get('ai_bonus', 0),
                'ai_recommendation': pick.get('ai_recommendation', 'N/A'),
                'price_at_analysis': price_at_analysis,
                'target_upside': pick.get('target_upside', 0),
                'sd_stage': pick.get('sd_stage', 'N/A'),
                'inst_pct': pick.get('inst_pct', 0),
                'rsi': pick.get('rsi', 0),
                'ai_summary': pick.get('ai_summary', '')[:300]
            })
        
        # Save to history
        history_file = self.get_today_filename()
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Saved to {history_file}")
        
        # Also save as current
        with open(self.current_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Updated current file: {self.current_file}")
        
        return snapshot
    
    def get_picks_with_performance(self) -> Dict:
        """Get current picks with performance tracking"""
        if not os.path.exists(self.current_file):
            return {'error': 'No analysis found. Run tracker first.'}
        
        with open(self.current_file, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)
        
        # Get current prices
        tickers = [p['ticker'] for p in snapshot['picks']]
        current_prices = self.get_current_prices(tickers)
        
        # Calculate performance
        result = {
            'analysis_date': snapshot['analysis_date'],
            'analysis_timestamp': snapshot['analysis_timestamp'],
            'picks': []
        }
        
        for pick in snapshot['picks']:
            ticker = pick['ticker']
            price_at_analysis = pick['price_at_analysis']
            current_price = current_prices.get(ticker, price_at_analysis)
            
            # Calculate change
            if price_at_analysis > 0:
                change_pct = ((current_price / price_at_analysis) - 1) * 100
            else:
                change_pct = 0
            
            pick_with_perf = {
                **pick,
                'current_price': current_price,
                'change_since_rec': round(change_pct, 2),
                'change_absolute': round(current_price - price_at_analysis, 2)
            }
            result['picks'].append(pick_with_perf)
        
        return result
    
    def list_history(self) -> List[str]:
        """List all historical analysis dates"""
        files = []
        for f in os.listdir(self.history_dir):
            if f.startswith('picks_') and f.endswith('.json'):
                date_str = f[6:-5]  # Extract date from filename
                files.append(date_str)
        return sorted(files, reverse=True)
    
    def get_historical_performance(self, analysis_date: str) -> Dict:
        """Get performance for a specific historical analysis with benchmark comparison"""
        import numpy as np
        
        history_file = os.path.join(self.history_dir, f"picks_{analysis_date}.json")
        
        if not os.path.exists(history_file):
            return {'error': f'No analysis found for {analysis_date}'}
        
        with open(history_file, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)
        
        # Get current prices
        tickers = [p['ticker'] for p in snapshot['picks']]
        current_prices = self.get_current_prices(tickers + ['SPY'])
        
        # Calculate SPY benchmark return from CSV
        spy_return = 0.0
        csv_path = os.path.join(self.data_dir, 'data', 'us_daily_prices.csv')
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                spy_df = df[df['Ticker'] == 'SPY'].copy()
                spy_df = spy_df[spy_df['Date'] >= analysis_date].sort_values('Date')
                if len(spy_df) >= 2:
                    spy_start = spy_df['Close'].iloc[0]
                    spy_end = spy_df['Close'].iloc[-1]
                    spy_return = ((spy_end / spy_start) - 1) * 100
            except Exception as e:
                logger.warning(f"SPY calculation error: {e}")
        
        result = {
            'analysis_date': snapshot['analysis_date'],
            'picks': []
        }
        
        changes = []
        for pick in snapshot['picks']:
            ticker = pick['ticker']
            price_at_analysis = pick['price_at_analysis']
            current_price = current_prices.get(ticker, price_at_analysis)
            
            if price_at_analysis > 0:
                change_pct = ((current_price / price_at_analysis) - 1) * 100
            else:
                change_pct = 0
            
            changes.append(change_pct)
            
            result['picks'].append({
                'ticker': ticker,
                'name': pick.get('name', ticker),
                'rank': pick.get('rank', 0),
                'final_score': pick.get('final_score', 0),
                'price_at_rec': price_at_analysis,
                'current_price': current_price,
                'change_pct': round(change_pct, 2)
            })
        
        # Calculate statistics
        if changes:
            avg_return = np.mean(changes)
            win_count = len([c for c in changes if c > 0])
            loss_count = len([c for c in changes if c <= 0])
            
            result['statistics'] = {
                'avg_return': round(avg_return, 2),
                'spy_return': round(spy_return, 2),
                'alpha': round(avg_return - spy_return, 2),
                'win_rate': round(win_count / len(changes) * 100, 1),
                'win_count': win_count,
                'loss_count': loss_count,
                'volatility': round(np.std(changes), 2),
                'best_pick': max(result['picks'], key=lambda x: x['change_pct']),
                'worst_pick': min(result['picks'], key=lambda x: x['change_pct']),
                'max_gain': round(max(changes), 2),
                'max_loss': round(min(changes), 2)
            }
        else:
            result['statistics'] = {}
        
        # Legacy field for backward compatibility
        result['avg_performance'] = result['statistics'].get('avg_return', 0)
        
        return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Smart Money Tracker')
    parser.add_argument('--dir', default='.', help='Data directory')
    parser.add_argument('--save', action='store_true', help='Create daily snapshot')
    parser.add_argument('--show', action='store_true', help='Show current picks with performance')
    parser.add_argument('--history', type=str, help='Show historical performance for date (YYYY-MM-DD)')
    parser.add_argument('--list', action='store_true', help='List all historical dates')
    args = parser.parse_args()
    
    tracker = SmartMoneyTracker(data_dir=args.dir)
    
    if args.save:
        snapshot = tracker.create_daily_snapshot()
        print(f"\n📅 Analysis saved for {snapshot.get('analysis_date', 'today')}")
        print(f"📊 {len(snapshot.get('picks', []))} picks recorded")
    
    elif args.show:
        result = tracker.get_picks_with_performance()
        if 'error' in result:
            print(f"❌ {result['error']}")
            return
        
        print(f"\n{'='*100}")
        print(f"📅 Analysis Date: {result['analysis_date']}")
        print(f"{'='*100}")
        
        for pick in result['picks']:
            change = pick['change_since_rec']
            emoji = "🟢" if change >= 0 else "🔴"
            
            print(f"\n#{pick['rank']} {pick['ticker']} - {pick['name']}")
            print(f"   💰 Score: {pick['final_score']}/100 | {pick['ai_recommendation']}")
            print(f"   📊 추천가: ${pick['price_at_analysis']:.2f} → 현재가: ${pick['current_price']:.2f}")
            print(f"   {emoji} 변동: {change:+.2f}% (${pick['change_absolute']:+.2f})")
    
    elif args.history:
        result = tracker.get_historical_performance(args.history)
        if 'error' in result:
            print(f"❌ {result['error']}")
            return
        
        print(f"\n📅 Historical Performance: {args.history}")
        print(f"📊 Average Return: {result['avg_performance']:+.2f}%")
        print("-" * 60)
        
        for pick in result['picks']:
            change = pick['change_pct']
            emoji = "🟢" if change >= 0 else "🔴"
            print(f"{emoji} {pick['ticker']}: ${pick['price_at_rec']:.2f} → ${pick['current_price']:.2f} ({change:+.2f}%)")
    
    elif args.list:
        dates = tracker.list_history()
        print(f"\n📅 Historical Analyses:")
        for d in dates:
            print(f"   - {d}")

    else:
        # Default: save daily snapshot when run without arguments (for update_all.py)
        snapshot = tracker.create_daily_snapshot()
        print(f"\n📅 Analysis saved for {snapshot.get('analysis_date', 'today')}")
        print(f"📊 {len(snapshot.get('picks', []))} picks recorded")


if __name__ == "__main__":
    main()
