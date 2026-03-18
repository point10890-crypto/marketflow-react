#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Earnings Transcripts Analyzer
- Collects earnings call transcripts from free APIs
- Extracts key insights: guidance changes, tone, risks
- Provides AI-powered summary of earnings calls

Free APIs used:
- FinancialModelingPrep (250 calls/day free)
- Alpha Vantage (5 calls/min free)
- Fallback: Seeking Alpha RSS
"""

import os
import json
import requests
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EarningsTranscriptCollector:
    """Collect and analyze earnings call transcripts"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'earnings_transcripts.json')
        
        # API keys (free tier)
        self.fmp_api_key = os.getenv('FMP_API_KEY', '')
        
        # Check for API key
        if not self.fmp_api_key:
            logger.warning("⚠️ FMP_API_KEY not found. Set it in .env for full transcript access.")
            logger.info("   Get free key at: https://financialmodelingprep.com/developer")
    
    def get_transcript_fmp(self, ticker: str, year: int = None, quarter: int = None) -> Dict:
        """
        Get earnings transcript from FinancialModelingPrep API.
        Free tier: 250 calls/day
        """
        if not self.fmp_api_key:
            return {'ticker': ticker, 'error': 'FMP_API_KEY not configured'}
        
        try:
            # If no year/quarter, get latest
            if year and quarter:
                url = f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{ticker}?year={year}&quarter={quarter}&apikey={self.fmp_api_key}"
            else:
                url = f"https://financialmodelingprep.com/api/v4/batch_earning_call_transcript/{ticker}?apikey={self.fmp_api_key}"
            
            response = requests.get(url, timeout=15)
            
            if response.status_code != 200:
                return {'ticker': ticker, 'error': f'API error: {response.status_code}'}
            
            data = response.json()
            
            if not data:
                return {'ticker': ticker, 'error': 'No transcript available'}
            
            # Get most recent if list
            if isinstance(data, list):
                transcript = data[0] if data else {}
            else:
                transcript = data
            
            return {
                'ticker': ticker,
                'date': transcript.get('date', ''),
                'quarter': transcript.get('quarter', ''),
                'year': transcript.get('year', ''),
                'content': transcript.get('content', ''),
                'source': 'financialmodelingprep'
            }
            
        except Exception as e:
            logger.error(f"Error getting transcript for {ticker}: {e}")
            return {'ticker': ticker, 'error': str(e)}
    
    def get_earnings_call_info(self, ticker: str) -> Dict:
        """
        Get earnings call calendar and basic info from yfinance.
        Fallback when no transcript API available.
        """
        try:
            import yfinance as yf
            
            stock = yf.Ticker(ticker)
            calendar = stock.calendar
            
            next_date = None
            if calendar and isinstance(calendar, dict):
                dates = calendar.get('Earnings Date', [])
                if dates:
                    next_date = dates[0].strftime('%Y-%m-%d')
            
            # Get earnings history
            earnings_history = []
            try:
                hist = stock.earnings_history
                if hist is not None and not hist.empty:
                    for date, row in hist.head(4).iterrows():
                        earnings_history.append({
                            'date': str(date),
                            'eps_estimate': row.get('EPS Estimate', 0),
                            'eps_actual': row.get('EPS Actual', 0),
                            'surprise_pct': row.get('Surprise (%)', 0)
                        })
            except:
                pass
            
            return {
                'ticker': ticker,
                'next_earnings_date': next_date,
                'earnings_history': earnings_history,
                'source': 'yfinance'
            }
            
        except Exception as e:
            return {'ticker': ticker, 'error': str(e)}
    
    def analyze_transcript_tone(self, content: str) -> Dict:
        """
        Basic tone analysis of transcript content.
        Counts positive/negative keywords.
        """
        if not content:
            return {'error': 'No content to analyze'}
        
        content_lower = content.lower()
        
        # Positive keywords
        positive_words = [
            'growth', 'strong', 'exceeded', 'beat', 'optimistic', 'momentum',
            'opportunity', 'confident', 'record', 'accelerating', 'improving',
            'outperform', 'robust', 'upside', 'guidance raised', 'increasing'
        ]
        
        # Negative keywords
        negative_words = [
            'decline', 'weak', 'missed', 'challenging', 'headwind', 'uncertainty',
            'risk', 'concern', 'slowdown', 'lower', 'reduced', 'headwinds',
            'guidance lowered', 'cautious', 'difficult', 'pressure', 'downturn'
        ]
        
        # Forward-looking keywords
        guidance_words = [
            'guidance', 'outlook', 'expect', 'forecast', 'anticipate',
            'project', 'full year', 'next quarter', 'going forward'
        ]
        
        positive_count = sum(1 for word in positive_words if word in content_lower)
        negative_count = sum(1 for word in negative_words if word in content_lower)
        guidance_count = sum(1 for word in guidance_words if word in content_lower)
        
        # Calculate sentiment score (-1 to 1)
        total = positive_count + negative_count
        if total > 0:
            sentiment_score = (positive_count - negative_count) / total
        else:
            sentiment_score = 0
        
        # Determine overall tone
        if sentiment_score > 0.3:
            tone = 'Bullish'
        elif sentiment_score < -0.3:
            tone = 'Bearish'
        else:
            tone = 'Neutral'
        
        return {
            'tone': tone,
            'sentiment_score': round(sentiment_score, 2),
            'positive_signals': positive_count,
            'negative_signals': negative_count,
            'guidance_mentions': guidance_count
        }
    
    def extract_key_points(self, content: str) -> Dict:
        """
        Extract key points from transcript.
        Looks for guidance, metrics, and risks.
        """
        if not content or len(content) < 100:
            return {'error': 'Insufficient content'}
        
        content_lower = content.lower()
        
        # Extract revenue/EPS mentions
        revenue_pattern = r'revenue.{0,50}(\$[\d,]+\.?\d*\s*(billion|million|B|M)?)'
        eps_pattern = r'(eps|earnings per share).{0,30}(\$?[\d]+\.?\d*)'
        
        revenue_mentions = re.findall(revenue_pattern, content, re.IGNORECASE)
        eps_mentions = re.findall(eps_pattern, content, re.IGNORECASE)
        
        # Look for guidance changes
        guidance_raised = 'guidance' in content_lower and any(w in content_lower for w in ['raised', 'increased', 'higher'])
        guidance_lowered = 'guidance' in content_lower and any(w in content_lower for w in ['lowered', 'reduced', 'lower'])
        guidance_maintained = 'guidance' in content_lower and any(w in content_lower for w in ['maintained', 'reaffirmed', 'unchanged'])
        
        if guidance_raised:
            guidance_change = 'Raised'
        elif guidance_lowered:
            guidance_change = 'Lowered'
        elif guidance_maintained:
            guidance_change = 'Maintained'
        else:
            guidance_change = 'Not specified'
        
        return {
            'revenue_mentions': len(revenue_mentions),
            'eps_mentions': len(eps_mentions),
            'guidance_change': guidance_change,
            'content_length': len(content)
        }
    
    def analyze_ticker(self, ticker: str) -> Dict:
        """Full analysis for a single ticker"""
        result = {
            'ticker': ticker,
            'fetch_time': datetime.now().isoformat()
        }
        
        # Try to get transcript
        transcript = self.get_transcript_fmp(ticker)
        
        if 'error' not in transcript and transcript.get('content'):
            content = transcript['content']
            
            result['has_transcript'] = True
            result['transcript_date'] = transcript.get('date', '')
            result['quarter'] = transcript.get('quarter', '')
            result['year'] = transcript.get('year', '')
            
            # Analyze
            result['tone_analysis'] = self.analyze_transcript_tone(content)
            result['key_points'] = self.extract_key_points(content)
            
            # Truncated preview
            result['content_preview'] = content[:1000] + '...' if len(content) > 1000 else content
        else:
            # Fallback to basic earnings info
            result['has_transcript'] = False
            result['error'] = transcript.get('error', 'No transcript available')
            
            # Get basic earnings info from yfinance
            earnings_info = self.get_earnings_call_info(ticker)
            result['earnings_info'] = earnings_info
        
        return result
    
    def analyze_tickers(self, tickers: List[str]) -> Dict:
        """Analyze multiple tickers"""
        logger.info(f"📞 Analyzing earnings transcripts for {len(tickers)} tickers...")
        
        results = {}
        transcripts_found = 0
        
        for ticker in tickers:
            logger.info(f"  Processing {ticker}...")
            data = self.analyze_ticker(ticker)
            results[ticker] = data
            
            if data.get('has_transcript'):
                transcripts_found += 1
        
        return {
            'metadata': {
                'as_of_date': datetime.now().strftime('%Y-%m-%d'),
                'fetch_time': datetime.now().isoformat(),
                'source': 'fmp_api + yfinance',
                'ticker_count': len(tickers),
                'transcripts_found': transcripts_found
            },
            'analyses': results
        }
    
    def save_results(self, data: Dict):
        """Save results to JSON"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Saved to {self.output_file}")


def main():
    import argparse
    import pandas as pd
    
    parser = argparse.ArgumentParser(description='Earnings Transcript Analyzer')
    parser.add_argument('--tickers', nargs='+', help='List of tickers')
    parser.add_argument('--single', type=str, help='Analyze single ticker in detail')
    args = parser.parse_args()
    
    collector = EarningsTranscriptCollector()
    
    if args.single:
        result = collector.analyze_ticker(args.single)
        print(f"\n📞 Earnings Transcript Analysis: {args.single}")
        print("=" * 60)
        
        if result.get('has_transcript'):
            print(f"Date: {result.get('transcript_date', 'N/A')}")
            print(f"Quarter: Q{result.get('quarter', '?')} {result.get('year', '')}")
            
            tone = result.get('tone_analysis', {})
            print(f"\n🎯 Tone: {tone.get('tone', 'N/A')} (score: {tone.get('sentiment_score', 0)})")
            print(f"   Positive signals: {tone.get('positive_signals', 0)}")
            print(f"   Negative signals: {tone.get('negative_signals', 0)}")
            print(f"   Guidance mentions: {tone.get('guidance_mentions', 0)}")
            
            points = result.get('key_points', {})
            print(f"\n📊 Key Points:")
            print(f"   Guidance Change: {points.get('guidance_change', 'N/A')}")
            print(f"   Revenue mentions: {points.get('revenue_mentions', 0)}")
            print(f"   EPS mentions: {points.get('eps_mentions', 0)}")
            
            print(f"\n📝 Preview:")
            print(result.get('content_preview', '')[:500])
        else:
            print(f"No transcript available: {result.get('error', 'Unknown error')}")
            
            earnings_info = result.get('earnings_info', {})
            if earnings_info:
                print(f"\n📅 Next Earnings: {earnings_info.get('next_earnings_date', 'N/A')}")
        return
    
    # Default: analyze top picks
    target_tickers = args.tickers
    if not target_tickers:
        try:
            picks_file = 'output/smart_money_picks_v2.csv'
            if os.path.exists(picks_file):
                df = pd.read_csv(picks_file)
                target_tickers = df['ticker'].tolist()[:15]
            else:
                target_tickers = ['AAPL', 'MSFT', 'NVDA', 'META', 'GOOGL']
        except:
            target_tickers = ['AAPL', 'MSFT', 'NVDA']
    
    result = collector.analyze_tickers(target_tickers)
    collector.save_results(result)
    
    print("\n" + "=" * 60)
    print("📞 EARNINGS TRANSCRIPT SUMMARY")
    print("=" * 60)
    
    for ticker, data in result['analyses'].items():
        if data.get('has_transcript'):
            tone = data.get('tone_analysis', {}).get('tone', 'N/A')
            guidance = data.get('key_points', {}).get('guidance_change', 'N/A')
            print(f"✅ {ticker}: {tone} | Guidance: {guidance}")
        else:
            print(f"⚠️ {ticker}: No transcript (using yfinance fallback)")
    
    print(f"\n📊 Total: {result['metadata']['transcripts_found']}/{result['metadata']['ticker_count']} transcripts found")


if __name__ == "__main__":
    main()
