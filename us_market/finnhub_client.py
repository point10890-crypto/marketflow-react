#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Finnhub API Client - yfinance 대체용
Rate limit: 50-60 requests/min (free tier)
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import finnhub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FinnhubClient:
    """
    Finnhub API wrapper with rate limiting.
    Replaces yfinance for US market data.
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('FINNHUB_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Finnhub API key required. Set FINNHUB_API_KEY environment variable or pass api_key."
            )
        self.client = finnhub.Client(api_key=self.api_key)
        self._last_request_time = 0
        self._min_interval = 1.2  # ~50 requests/min
        
    def _rate_limit(self):
        """Ensure we don't exceed rate limits."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get real-time quote for a symbol.
        
        Returns:
            Dict with keys: c (current), h (high), l (low), o (open), 
                           pc (prev close), t (timestamp)
        """
        self._rate_limit()
        try:
            quote = self.client.quote(symbol)
            return {
                'symbol': symbol,
                'current': quote.get('c', 0),
                'high': quote.get('h', 0),
                'low': quote.get('l', 0),
                'open': quote.get('o', 0),
                'prev_close': quote.get('pc', 0),
                'change': quote.get('d', 0),
                'change_pct': quote.get('dp', 0),
                'timestamp': quote.get('t', 0)
            }
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return {'symbol': symbol, 'error': str(e)}
    
    def get_quotes_batch(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get quotes for multiple symbols with rate limiting."""
        results = {}
        for i, symbol in enumerate(symbols):
            if i > 0 and i % 10 == 0:
                logger.info(f"Fetched {i}/{len(symbols)} quotes...")
            results[symbol] = self.get_quote(symbol)
        return results
    
    def get_candles(
        self, 
        symbol: str, 
        resolution: str = 'D',
        from_date: datetime = None,
        to_date: datetime = None,
        days: int = 365
    ) -> Dict[str, Any]:
        """
        Get OHLCV candle data.
        
        Args:
            symbol: Stock symbol
            resolution: D (daily), W (weekly), M (monthly), 1/5/15/30/60 (minutes)
            from_date: Start date
            to_date: End date  
            days: Days of history if dates not specified
            
        Returns:
            Dict with lists: c (close), h (high), l (low), o (open), v (volume), t (timestamps)
        """
        self._rate_limit()
        
        if to_date is None:
            to_date = datetime.now()
        if from_date is None:
            from_date = to_date - timedelta(days=days)
            
        from_ts = int(from_date.timestamp())
        to_ts = int(to_date.timestamp())
        
        try:
            candles = self.client.stock_candles(symbol, resolution, from_ts, to_ts)
            
            if candles.get('s') != 'ok':
                return {'symbol': symbol, 'error': 'No data', 'status': candles.get('s')}
            
            return {
                'symbol': symbol,
                'close': candles.get('c', []),
                'high': candles.get('h', []),
                'low': candles.get('l', []),
                'open': candles.get('o', []),
                'volume': candles.get('v', []),
                'timestamps': candles.get('t', []),
                'status': 'ok'
            }
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")
            return {'symbol': symbol, 'error': str(e)}
    
    def get_company_profile(self, symbol: str) -> Dict[str, Any]:
        """Get company profile info."""
        self._rate_limit()
        try:
            profile = self.client.company_profile2(symbol=symbol)
            return {
                'symbol': symbol,
                'name': profile.get('name', ''),
                'sector': profile.get('finnhubIndustry', ''),
                'country': profile.get('country', ''),
                'market_cap': profile.get('marketCapitalization', 0),
                'shares_outstanding': profile.get('shareOutstanding', 0),
                'ipo': profile.get('ipo', ''),
                'logo': profile.get('logo', ''),
                'website': profile.get('weburl', '')
            }
        except Exception as e:
            logger.error(f"Error fetching profile for {symbol}: {e}")
            return {'symbol': symbol, 'error': str(e)}
    
    def get_basic_financials(self, symbol: str) -> Dict[str, Any]:
        """Get basic financial metrics."""
        self._rate_limit()
        try:
            financials = self.client.company_basic_financials(symbol, 'all')
            metrics = financials.get('metric', {})
            return {
                'symbol': symbol,
                'pe_ratio': metrics.get('peNormalizedAnnual'),
                'pb_ratio': metrics.get('pbAnnual'),
                'dividend_yield': metrics.get('dividendYieldIndicatedAnnual'),
                'eps': metrics.get('epsNormalizedAnnual'),
                'beta': metrics.get('beta'),
                '52_week_high': metrics.get('52WeekHigh'),
                '52_week_low': metrics.get('52WeekLow'),
                'avg_volume_10d': metrics.get('10DayAverageTradingVolume')
            }
        except Exception as e:
            logger.error(f"Error fetching financials for {symbol}: {e}")
            return {'symbol': symbol, 'error': str(e)}
    
    def get_institutional_ownership(self, symbol: str) -> Dict[str, Any]:
        """Get institutional ownership data."""
        self._rate_limit()
        try:
            ownership = self.client.ownership(symbol, limit=20)
            return {
                'symbol': symbol,
                'holders': ownership
            }
        except Exception as e:
            logger.error(f"Error fetching ownership for {symbol}: {e}")
            return {'symbol': symbol, 'error': str(e)}

    def get_insider_transactions(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Get recent insider transactions."""
        self._rate_limit()
        try:
            # Finnhub endpoint for insider transactions
            transactions = self.client.stock_insider_transactions(symbol, limit=limit)
            return {
                'symbol': symbol,
                'transactions': transactions.get('data', [])
            }
        except Exception as e:
            logger.error(f"Error fetching insider txns for {symbol}: {e}")
            return {'symbol': symbol, 'error': str(e)}


# Convenience function for quick testing
def test_client():
    """Test the Finnhub client."""
    client = FinnhubClient()
    
    print("Testing Finnhub Client...")
    print("-" * 40)
    
    # Test quote
    quote = client.get_quote('AAPL')
    print(f"AAPL Quote: ${quote.get('current', 'N/A')}")
    
    # Test profile
    profile = client.get_company_profile('AAPL')
    print(f"Company: {profile.get('name', 'N/A')}")
    print(f"Sector: {profile.get('sector', 'N/A')}")
    
    # Test candles
    candles = client.get_candles('AAPL', days=30)
    if candles.get('status') == 'ok':
        print(f"Got {len(candles.get('close', []))} days of price data")
    
    print("-" * 40)
    print("✅ Finnhub client working!")


if __name__ == "__main__":
    test_client()
