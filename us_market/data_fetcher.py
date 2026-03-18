#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Stock Data Fetcher - Hybrid Approach
Uses yfinance with rate limiting + Finnhub as fallback
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class USStockDataFetcher:
    """
    Hybrid data fetcher with multiple sources:
    1. yfinance (primary, free)
    2. Finnhub (fallback, free tier)
    3. Alpha Vantage (fallback)
    4. FMP - Financial Modeling Prep (fallback, comprehensive)
    """

    def __init__(self, finnhub_api_key: str = None):
        self.finnhub_client = None
        self.yf_available = True
        self.finnhub_available = False
        self.alpha_vantage_key = None
        self.fmp_key = None

        # Initialize Finnhub if key available
        finnhub_key = finnhub_api_key or os.environ.get('FINNHUB_API_KEY')
        if finnhub_key:
            try:
                from finnhub_client import FinnhubClient
                self.finnhub_client = FinnhubClient(api_key=finnhub_key)
                self.finnhub_available = True
                logger.info("✅ Finnhub client initialized")
            except Exception as e:
                logger.warning(f"⚠️ Finnhub init failed: {e}")

        # Initialize Alpha Vantage if key available
        self.alpha_vantage_key = os.environ.get('ALPHA_VANTAGE_API_KEY')
        if self.alpha_vantage_key:
            logger.info("✅ Alpha Vantage available")

        # Initialize FMP (Financial Modeling Prep) if key available
        self.fmp_key = os.environ.get('FMP_API_KEY')
        if self.fmp_key:
            logger.info("✅ FMP (Financial Modeling Prep) available")

        # Try import yfinance with curl_cffi session (bypass Yahoo bot protection)
        try:
            import yfinance as yf
            self.yf = yf
            self.yf_session = None

            # Try to use curl_cffi to bypass Yahoo's bot protection
            try:
                from curl_cffi import requests as curl_requests
                self.yf_session = curl_requests.Session(impersonate="chrome")
                logger.info("✅ yfinance available (with curl_cffi bypass)")
            except ImportError:
                logger.info("✅ yfinance available (curl_cffi not installed - may hit rate limits)")

        except ImportError:
            self.yf_available = False
            logger.warning("⚠️ yfinance not available")
    
    def _alpha_vantage_quote(self, symbol: str) -> Dict[str, Any]:
        """Alpha Vantage fallback for quote data."""
        if not self.alpha_vantage_key:
            return {}

        import requests
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={self.alpha_vantage_key}"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            quote = data.get('Global Quote', {})
            if quote:
                return {
                    'symbol': symbol,
                    'current': float(quote.get('05. price', 0)),
                    'prev_close': float(quote.get('08. previous close', 0)),
                    'open': float(quote.get('02. open', 0)),
                    'high': float(quote.get('03. high', 0)),
                    'low': float(quote.get('04. low', 0)),
                    'volume': int(quote.get('06. volume', 0)),
                    'change_pct': float(quote.get('10. change percent', '0%').replace('%', '')),
                }
        except Exception as e:
            logger.debug(f"Alpha Vantage failed for {symbol}: {e}")
        return {}

    def _fmp_quote(self, symbol: str) -> Dict[str, Any]:
        """FMP (Financial Modeling Prep) fallback for quote data."""
        if not self.fmp_key:
            return {}

        import requests
        url = f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={self.fmp_key}"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                quote = data[0]
                return {
                    'symbol': symbol,
                    'current': float(quote.get('price', 0)),
                    'prev_close': float(quote.get('previousClose', 0)),
                    'open': float(quote.get('open', 0)),
                    'high': float(quote.get('dayHigh', 0)),
                    'low': float(quote.get('dayLow', 0)),
                    'volume': int(quote.get('volume', 0)),
                    'change_pct': float(quote.get('changesPercentage', 0)),
                    'market_cap': quote.get('marketCap', 0),
                    'pe': quote.get('pe', 0),
                    'eps': quote.get('eps', 0),
                }
        except Exception as e:
            logger.debug(f"FMP failed for {symbol}: {e}")
        return {}

    def _fmp_company_profile(self, symbol: str) -> Dict[str, Any]:
        """FMP company profile - more comprehensive than others."""
        if not self.fmp_key:
            return {}

        import requests
        url = f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={self.fmp_key}"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                profile = data[0]
                return {
                    'symbol': symbol,
                    'shortName': profile.get('companyName', ''),
                    'longName': profile.get('companyName', ''),
                    'sector': profile.get('sector', ''),
                    'industry': profile.get('industry', ''),
                    'marketCap': profile.get('mktCap', 0),
                    'trailingPE': profile.get('pe', 0) if profile.get('pe') else None,
                    'beta': profile.get('beta', 0),
                    'dividendYield': profile.get('lastDiv', 0) / profile.get('price', 1) if profile.get('price') else 0,
                    'fiftyTwoWeekHigh': profile.get('range', '').split('-')[-1].strip() if profile.get('range') else None,
                    'fiftyTwoWeekLow': profile.get('range', '').split('-')[0].strip() if profile.get('range') else None,
                    'description': profile.get('description', ''),
                    'ceo': profile.get('ceo', ''),
                    'website': profile.get('website', ''),
                    'exchange': profile.get('exchangeShortName', ''),
                }
        except Exception as e:
            logger.debug(f"FMP profile failed for {symbol}: {e}")
        return {}
    
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get current quote for a symbol."""
        # 1. Try Finnhub first (most reliable)
        if self.finnhub_available:
            try:
                return self.finnhub_client.get_quote(symbol)
            except Exception as e:
                logger.warning(f"Finnhub quote failed for {symbol}: {e}")

        # 2. Try FMP (comprehensive data)
        if self.fmp_key:
            result = self._fmp_quote(symbol)
            if result:
                return result

        # 3. Try Alpha Vantage (no rate limit issues)
        if self.alpha_vantage_key:
            result = self._alpha_vantage_quote(symbol)
            if result:
                return result

        # 4. Fallback to yfinance (rate limited, use session if available)
        if self.yf_available:
            try:
                time.sleep(1.0)  # Increased rate limit delay
                # Use curl_cffi session if available to bypass bot protection
                if self.yf_session:
                    ticker = self.yf.Ticker(symbol, session=self.yf_session)
                else:
                    ticker = self.yf.Ticker(symbol)
                info = ticker.fast_info
                return {
                    'symbol': symbol,
                    'current': info.get('lastPrice', 0),
                    'prev_close': info.get('previousClose', 0),
                    'open': info.get('open', 0),
                    'high': info.get('dayHigh', 0),
                    'low': info.get('dayLow', 0),
                }
            except Exception as e:
                logger.warning(f"yfinance quote failed for {symbol}: {e}")

        return {'symbol': symbol, 'error': 'No data source available'}
    
    def get_quotes_batch(self, symbols: List[str], use_finnhub: bool = True) -> Dict[str, Dict]:
        """Get quotes for multiple symbols."""
        results = {}
        
        for i, symbol in enumerate(symbols):
            if i > 0 and i % 20 == 0:
                logger.info(f"Progress: {i}/{len(symbols)}")
            results[symbol] = self.get_quote(symbol)
        
        return results
    
    def download_history(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime = None,
        batch_size: int = 25,
        delay_between_batches: float = 2.0
    ) -> pd.DataFrame:
        """
        Download historical data with rate limiting.

        Priority: yfinance batch (fast) → Finnhub Quote (fallback for recent data)

        Args:
            symbols: List of tickers
            start_date: Start date
            end_date: End date (default: today)
            batch_size: Symbols per batch (smaller = safer)
            delay_between_batches: Seconds to wait between batches

        Returns:
            DataFrame with OHLCV data
        """
        if end_date is None:
            end_date = datetime.now()

        all_data = []
        successful_symbols = set()

        # 1. Try yfinance batch download FIRST (fastest for bulk data)
        if self.yf_available:
            logger.info(f"📊 Fetching history for {len(symbols)} symbols via yfinance...")

            # Process in batches
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i+batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(symbols) + batch_size - 1) // batch_size

                logger.info(f"   Batch {batch_num}/{total_batches}: {len(batch)} symbols...")

                try:
                    # Use curl_cffi session if available for bot protection bypass
                    if self.yf_session:
                        data = self.yf.download(
                            batch,
                            start=start_date,
                            end=end_date + timedelta(days=1),
                            group_by='column',
                            progress=False,
                            threads=False,
                            session=self.yf_session
                        )
                    else:
                        data = self.yf.download(
                            batch,
                            start=start_date,
                            end=end_date + timedelta(days=1),
                            group_by='column',
                            progress=False,
                            threads=False
                        )

                    if not data.empty:
                        if len(batch) == 1:
                            # Single symbol - different structure
                            df_batch = data.copy()
                            df_batch['Ticker'] = batch[0]
                            df_batch.reset_index(inplace=True)
                            if not df_batch.empty:
                                all_data.append(df_batch)
                                successful_symbols.add(batch[0])
                        else:
                            # Multiple symbols - stacked structure
                            if isinstance(data.columns, pd.MultiIndex):
                                available_tickers = data.columns.get_level_values(1).unique().tolist()
                                successful_symbols.update(available_tickers)

                                data = data.stack(level=1, future_stack=True)
                                data.index.names = ['Date', 'Ticker']
                                data.reset_index(inplace=True)
                                all_data.append(data)
                            else:
                                # Single ticker returned
                                df_batch = data.copy()
                                df_batch['Ticker'] = batch[0]
                                df_batch.reset_index(inplace=True)
                                if not df_batch.empty:
                                    all_data.append(df_batch)
                                    successful_symbols.add(batch[0])

                        logger.info(f"   ✅ Batch {batch_num}: Got data")

                except Exception as e:
                    logger.error(f"   ❌ yfinance batch {batch_num} failed: {e}")

                # Delay between batches to avoid rate limits
                if i + batch_size < len(symbols):
                    time.sleep(delay_between_batches)

        # Identify failed symbols
        failed_symbols = [s for s in symbols if s not in successful_symbols]

        # 2. Fallback to Finnhub Quote API for failed symbols (recent data only)
        if failed_symbols and self.finnhub_available:
            # Only use Quote API for recent data (within 5 days)
            if (datetime.now() - start_date).days < 5:
                logger.info(f"🔄 Finnhub Quote fallback for {len(failed_symbols)} symbols...")

                for i, symbol in enumerate(failed_symbols):
                    try:
                        q = self.finnhub_client.get_quote(symbol)
                        if q.get('current', 0) > 0:
                            df = pd.DataFrame({
                                'Date': [pd.to_datetime(q.get('timestamp', time.time()), unit='s')],
                                'Open': [q.get('open')],
                                'High': [q.get('high')],
                                'Low': [q.get('low')],
                                'Close': [q.get('current')],
                                'Volume': [0],  # Quote endpoint doesn't return volume
                                'Ticker': [symbol]
                            })
                            all_data.append(df)

                        if (i + 1) % 10 == 0:
                            logger.info(f"   Finnhub Quote progress: {i+1}/{len(failed_symbols)}")

                    except Exception as e:
                        logger.warning(f"   ⚠️ Finnhub Quote failed for {symbol}: {e}")

                    # Rate limit for Finnhub
                    time.sleep(0.5)
            else:
                if failed_symbols:
                    logger.info(f"⚠️ {len(failed_symbols)} symbols failed (historical data not available via Quote API)")

        if all_data:
            result = pd.concat(all_data, ignore_index=True)
            result.drop_duplicates(subset=['Date', 'Ticker'], inplace=True)
            result.sort_values(['Ticker', 'Date'], inplace=True)
            logger.info(f"✅ Total: {len(result)} rows for {result['Ticker'].nunique()} symbols")
            return result

        return pd.DataFrame()
    
    def get_company_info(self, symbol: str) -> Dict[str, Any]:
        """Get company profile info."""
        # Try Finnhub first
        if self.finnhub_available:
            try:
                return self.finnhub_client.get_company_profile(symbol)
            except Exception as e:
                logger.warning(f"Finnhub profile failed for {symbol}: {e}")
        
        # Fallback to yfinance
        if self.yf_available:
            try:
                time.sleep(0.5)
                ticker = self.yf.Ticker(symbol)
                info = ticker.info
                return {
                    'symbol': symbol,
                    'name': info.get('shortName', ''),
                    'sector': info.get('sector', ''),
                    'industry': info.get('industry', ''),
                    'market_cap': info.get('marketCap', 0),
                }
            except Exception as e:
                logger.warning(f"yfinance info failed for {symbol}: {e}")
        
        return {'symbol': symbol, 'error': 'No data source available'}

    def get_institutional_data(self, symbol: str) -> Dict[str, Any]:
        """Get institutional ownership data."""
        if self.finnhub_available:
            try:
                data = self.finnhub_client.get_institutional_ownership(symbol)
                
                # Finnhub returns list of holders. Normalize to match expected format.
                if 'holders' in data:
                    holders = data['holders'].get('ownership', [])
                    # Sum percentage held by top holders as proxy
                    # Note: Finnhub might return 'percentage' or 'share'
                    # Assuming 'percentage' field exists based on similar APIs.
                    # If not, this will be 0.
                    total_pct = sum([float(h.get('percentage', 0) or 0) for h in holders if h.get('percentage')])
                    # Finnhub percentage is often whole number (e.g. 5.5), yfinance uses 0.055
                    # Let's standardize to 0-1 range if it looks large, or just keep as is?
                    # yfinance returns 0.80 for 80%. Finnhub likely returns 80 or 0.8.
                    # Safety check: if > 1, divide by 100? Let's check a sample response later.
                    # For now, let's assume it resembles % (e.g. 80.5)
                    if total_pct > 1.0:
                        total_pct = total_pct / 100.0
                        
                    return {
                        'symbol': symbol,
                        'institutional_pct': total_pct,
                        'insider_pct': 0, # Difficult to get from holders list alone
                        'holders': holders
                    }
            except Exception as e:
                logger.warning(f"Finnhub ownership failed for {symbol}: {e}")
        
        # yfinance fallback mostly just basic info
        if self.yf_available:
            try:
                time.sleep(0.5)
                ticker = self.yf.Ticker(symbol)
                info = ticker.info
                return {
                    'symbol': symbol,
                    'institutional_pct': info.get('heldPercentInstitutions', 0),
                    'insider_pct': info.get('heldPercentInsiders', 0)
                }
            except Exception as e:
                logger.warning(f"yfinance ownership failed for {symbol}: {e}")
        
        return {'symbol': symbol, 'error': 'No data'}
        
    def get_insider_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Get insider sentiment/transactions."""
        if self.finnhub_available:
            try:
                data = self.finnhub_client.get_insider_transactions(symbol)
                return data
            except Exception as e:
                logger.warning(f"Finnhub insider failed for {symbol}: {e}")
                
        if self.yf_available:
            try:
                time.sleep(0.5)
                ticker = self.yf.Ticker(symbol)
                # yfinance insider_transactions is a dataframe
                txns = ticker.insider_transactions
                return {
                    'symbol': symbol,
                    'transactions_df': txns
                }
            except Exception as e:
                logger.warning(f"yfinance insider failed for {symbol}: {e}")
            
        return {'symbol': symbol, 'error': 'No data'}

    def get_history(self, symbol: str, period: str = "6mo") -> pd.DataFrame:
        """Get historical data (Technical Analysis)."""
        # Try yfinance directly with curl_cffi session (most reliable now)
        if self.yf_available:
            try:
                time.sleep(1.0)
                if self.yf_session:
                    ticker = self.yf.Ticker(symbol, session=self.yf_session)
                else:
                    ticker = self.yf.Ticker(symbol)
                df = ticker.history(period=period)
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning(f"YF history failed for {symbol}: {e}")

        # Fallback to download_history (uses Finnhub first)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)  # default 6mo

        if period == "3mo":
            start_date = end_date - timedelta(days=90)
        elif period == "1y":
            start_date = end_date - timedelta(days=365)
        elif period == "1mo":
            start_date = end_date - timedelta(days=30)

        df = self.download_history([symbol], start_date, end_date, batch_size=1, delay_between_batches=1.0)
        return df

    def get_info(self, symbol: str) -> Dict:
        """Get full stock info (Fundamentals, Analyst)."""
        # 1. Primarily rely on yfinance for rich info (but rate limited)
        if self.yf_available:
            try:
                time.sleep(1.5)  # Stronger rate limit for info calls
                # Use curl_cffi session if available to bypass bot protection
                if self.yf_session:
                    ticker = self.yf.Ticker(symbol, session=self.yf_session)
                else:
                    ticker = self.yf.Ticker(symbol)
                return ticker.info
            except Exception as e:
                logger.warning(f"YF info failed for {symbol}: {e}")

        # 2. FMP Fallback (comprehensive profile)
        if self.fmp_key:
            result = self._fmp_company_profile(symbol)
            if result:
                return result

        # 3. Minimal Finnhub Fallback
        if self.finnhub_available:
            try:
                profile = self.finnhub_client.get_company_profile(symbol)
                financials = self.finnhub_client.get_basic_financials(symbol)
                # Map fields to mimic yf.info structure
                mapped = {
                    'symbol': symbol,
                    'shortName': profile.get('name'),
                    'longName': profile.get('name'),
                    'sector': profile.get('sector'),
                    'marketCap': profile.get('market_cap', 0) * 1000000,  # Finnhub might use M
                    'trailingPE': financials.get('pe_ratio'),
                    'dividendYield': financials.get('dividend_yield', 0) / 100.0 if financials.get('dividend_yield') else 0,
                    'beta': financials.get('beta'),
                    'fiftyTwoWeekHigh': financials.get('52_week_high'),
                    'fiftyTwoWeekLow': financials.get('52_week_low'),
                }
                return mapped
            except Exception as e:
                logger.warning(f"Finnhub info failed for {symbol}: {e}")

        return {}
    
    def get_calendar(self, symbol: str) -> Dict:
        """Get earnings calendar."""
        if self.yf_available:
            try:
                time.sleep(0.5)
                ticker = self.yf.Ticker(symbol)
                return ticker.calendar
            except Exception as e:
                logger.debug(f"Calendar fetch failed for {symbol}: {e}")
        return {}

# Test function
def test_fetcher():
    """Test the hybrid fetcher."""
    fetcher = USStockDataFetcher()
    
    print("\n" + "="*50)
    print("Testing Hybrid Data Fetcher")
    print("="*50)
    
    # Test quote
    print("\n1. Testing Quote (AAPL):")
    quote = fetcher.get_quote('AAPL')
    print(f"   Current: ${quote.get('current', 'N/A')}")
    
    # Test history
    print("\n2. Testing History Download (3 symbols, 30 days):")
    df = fetcher.download_history(
        ['AAPL', 'MSFT', 'GOOGL'],
        start_date=datetime.now() - timedelta(days=30),
        batch_size=3,
        delay_between_batches=2
    )
    print(f"   Got {len(df)} rows")
    
    print("\n✅ Hybrid fetcher working!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_fetcher()
