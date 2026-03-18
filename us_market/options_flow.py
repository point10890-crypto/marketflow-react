#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Options Flow Analyzer
- Collects Put/Call ratio, Open Interest, Unusual Activity
- Identifies institutional positioning
"""

import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OptionsFlowAnalyzer:
    """Analyze options flow for institutional activity signals"""
    
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.dirname(os.path.abspath(__file__))
        self.watchlist = self._load_from_screener()
    
    def _load_from_screener(self, top_n: int = 15) -> List[str]:
        """
        Load watchlist from smart money screener results.
        Falls back to default list if file not found.
        """
        picks_file = os.path.join(self.data_dir, 'output', 'smart_money_picks_v2.csv')
        
        if os.path.exists(picks_file):
            try:
                import pandas as pd
                df = pd.read_csv(picks_file)
                tickers = df['ticker'].tolist()[:top_n]
                logger.info(f"📊 Loaded {len(tickers)} tickers from smart_money_picks_v2.csv")
                return tickers
            except Exception as e:
                logger.warning(f"⚠️ Failed to load screener results: {e}")
        
        # Fallback: Default major options tickers
        logger.info("📊 Using default options watchlist")
        return [
            'AAPL', 'NVDA', 'TSLA', 'MSFT', 'AMZN', 'META', 'GOOGL',
            'SPY', 'QQQ', 'AMD', 'NFLX', 'BA', 'DIS', 'COIN', 'PLTR'
        ]
    
    def get_options_summary(self, ticker: str) -> Dict:
        """Get options summary for a single ticker"""
        try:
            stock = yf.Ticker(ticker)
            
            # Get expiration dates
            expirations = stock.options
            if not expirations:
                return {'error': 'No options data'}
            
            # Get nearest expiration (weekly/monthly)
            nearest_exp = expirations[0]
            
            # Get options chain
            opt = stock.option_chain(nearest_exp)
            calls = opt.calls
            puts = opt.puts
            
            if calls.empty or puts.empty:
                return {'error': 'Empty options chain'}
            
            # Calculate metrics
            total_call_volume = calls['volume'].sum()
            total_put_volume = puts['volume'].sum()
            total_call_oi = calls['openInterest'].sum()
            total_put_oi = puts['openInterest'].sum()
            
            # Put/Call Ratio
            pc_volume_ratio = total_put_volume / total_call_volume if total_call_volume > 0 else 0
            pc_oi_ratio = total_put_oi / total_call_oi if total_call_oi > 0 else 0
            
            # Find highest open interest strikes (institutional positioning)
            max_call_strike = calls.loc[calls['openInterest'].idxmax()] if not calls.empty else None
            max_put_strike = puts.loc[puts['openInterest'].idxmax()] if not puts.empty else None
            
            # Calculate Max Pain (simplified)
            # Max pain is the strike where most options expire worthless
            all_strikes = set(calls['strike'].tolist() + puts['strike'].tolist())
            current_price = stock.info.get('regularMarketPrice', 0)
            
            # Unusual activity detection
            avg_call_volume = calls['volume'].mean()
            avg_put_volume = puts['volume'].mean()
            
            unusual_calls = calls[calls['volume'] > avg_call_volume * 3]
            unusual_puts = puts[puts['volume'] > avg_put_volume * 3]
            
            # Implied Volatility
            avg_call_iv = calls['impliedVolatility'].mean() * 100
            avg_put_iv = puts['impliedVolatility'].mean() * 100
            
            # Signal interpretation
            signal = self._interpret_signal(pc_volume_ratio, pc_oi_ratio, len(unusual_calls), len(unusual_puts))
            
            return {
                'ticker': ticker,
                'expiration': nearest_exp,
                'current_price': round(current_price, 2),
                'metrics': {
                    'pc_volume_ratio': round(pc_volume_ratio, 3),
                    'pc_oi_ratio': round(pc_oi_ratio, 3),
                    'total_call_volume': int(total_call_volume),
                    'total_put_volume': int(total_put_volume),
                    'total_call_oi': int(total_call_oi),
                    'total_put_oi': int(total_put_oi),
                    'call_iv': round(avg_call_iv, 1),
                    'put_iv': round(avg_put_iv, 1)
                },
                'key_levels': {
                    'max_call_strike': float(max_call_strike['strike']) if max_call_strike is not None else 0,
                    'max_call_oi': int(max_call_strike['openInterest']) if max_call_strike is not None else 0,
                    'max_put_strike': float(max_put_strike['strike']) if max_put_strike is not None else 0,
                    'max_put_oi': int(max_put_strike['openInterest']) if max_put_strike is not None else 0
                },
                'unusual_activity': {
                    'unusual_call_count': len(unusual_calls),
                    'unusual_put_count': len(unusual_puts),
                    'top_unusual_calls': unusual_calls.nlargest(3, 'volume')[['strike', 'volume', 'openInterest']].to_dict('records') if not unusual_calls.empty else [],
                    'top_unusual_puts': unusual_puts.nlargest(3, 'volume')[['strike', 'volume', 'openInterest']].to_dict('records') if not unusual_puts.empty else []
                },
                'signal': signal
            }
            
        except Exception as e:
            logger.error(f"Error getting options for {ticker}: {e}")
            return {'ticker': ticker, 'error': str(e)}
    
    def _interpret_signal(self, pc_vol_ratio: float, pc_oi_ratio: float, unusual_calls: int, unusual_puts: int) -> Dict:
        """Interpret options metrics into actionable signals"""
        
        # Sentiment based on Put/Call
        if pc_vol_ratio < 0.5:
            sentiment = "🟢 Very Bullish"
            sentiment_score = 90
        elif pc_vol_ratio < 0.7:
            sentiment = "🟢 Bullish"
            sentiment_score = 70
        elif pc_vol_ratio < 1.0:
            sentiment = "🟡 Neutral"
            sentiment_score = 50
        elif pc_vol_ratio < 1.3:
            sentiment = "🔴 Bearish"
            sentiment_score = 30
        else:
            sentiment = "🔴 Very Bearish"
            sentiment_score = 10
        
        # Unusual activity signal
        if unusual_calls > unusual_puts * 2:
            activity = "📈 Heavy Call Buying"
        elif unusual_puts > unusual_calls * 2:
            activity = "📉 Heavy Put Buying"
        elif unusual_calls > 3 or unusual_puts > 3:
            activity = "⚡ High Unusual Activity"
        else:
            activity = "😴 Normal Activity"
        
        return {
            'sentiment': sentiment,
            'sentiment_score': sentiment_score,
            'activity': activity
        }
    
    def analyze_watchlist(self) -> List[Dict]:
        """Analyze all stocks in watchlist"""
        logger.info(f"📊 Analyzing options flow for {len(self.watchlist)} stocks...")
        
        results = []
        for ticker in self.watchlist:
            logger.info(f"  Processing {ticker}...")
            data = self.get_options_summary(ticker)
            if 'error' not in data:
                results.append(data)
        
        # Sort by unusual activity
        results.sort(key=lambda x: x.get('unusual_activity', {}).get('unusual_call_count', 0) + 
                                   x.get('unusual_activity', {}).get('unusual_put_count', 0), 
                     reverse=True)
        
        return results
    
    def save_data(self, output_dir: str = None):
        """Save options flow data to JSON with metadata"""
        output_dir = output_dir or self.data_dir
        data = self.analyze_watchlist()
        
        output = {
            'metadata': {
                'as_of_date': datetime.now().strftime('%Y-%m-%d'),
                'fetch_time': datetime.now().isoformat(),
                'source': 'yfinance_options',
                'data_quality': 'actual',
                'row_count': len(data)
            },
            'timestamp': datetime.now().isoformat(),  # Legacy field
            'total_analyzed': len(data),
            'watchlist_source': 'output/smart_money_picks_v2.csv',
            'options_flow': data
        }
        
        output_file = os.path.join(output_dir, 'output', 'options_flow.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Saved to {output_file}")
        return output


def main():
    analyzer = OptionsFlowAnalyzer()
    
    print("\n" + "="*70)
    print("📊 OPTIONS FLOW ANALYSIS")
    print("="*70)
    
    results = analyzer.analyze_watchlist()
    
    print(f"\n✅ Analyzed {len(results)} stocks\n")
    
    for stock in results[:10]:  # Show top 10
        ticker = stock['ticker']
        metrics = stock['metrics']
        signal = stock['signal']
        unusual = stock['unusual_activity']
        key_levels = stock['key_levels']
        
        pc_ratio = metrics['pc_volume_ratio']
        
        print(f"\n{'='*50}")
        print(f"📈 {ticker} @ ${stock['current_price']}")
        print(f"{'='*50}")
        print(f"  Put/Call Ratio: {pc_ratio:.2f}")
        print(f"  Sentiment:      {signal['sentiment']}")
        print(f"  Activity:       {signal['activity']}")
        print(f"  Call Volume:    {metrics['total_call_volume']:,}")
        print(f"  Put Volume:     {metrics['total_put_volume']:,}")
        print(f"  Call IV:        {metrics['call_iv']:.1f}%")
        print(f"  Put IV:         {metrics['put_iv']:.1f}%")
        print(f"  Max Call Strike: ${key_levels['max_call_strike']} (OI: {key_levels['max_call_oi']:,})")
        print(f"  Max Put Strike:  ${key_levels['max_put_strike']} (OI: {key_levels['max_put_oi']:,})")
        
        if unusual['unusual_call_count'] > 0:
            print(f"  ⚡ Unusual Calls: {unusual['unusual_call_count']}")
        if unusual['unusual_put_count'] > 0:
            print(f"  ⚡ Unusual Puts: {unusual['unusual_put_count']}")
    
    # Save data
    analyzer.save_data()


if __name__ == "__main__":
    main()
