#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Stock Daily Prices Collection Script
Collects daily price data for NASDAQ and S&P 500 stocks
Uses hybrid data_fetcher (yfinance with rate limiting + Finnhub fallback)
"""

import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from tqdm import tqdm

# Use hybrid data fetcher instead of direct yfinance
from data_fetcher import USStockDataFetcher

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class USStockDailyPricesCreator:
    def print_header(self, msg):
        print(f"\n{'='*60}\n{msg}\n{'='*60}\n")
        
    def __init__(self):
        self.data_dir = os.getenv('DATA_DIR', '.')
        self.output_dir = self.data_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Data file paths
        self.prices_file = os.path.join(self.output_dir, 'data', 'us_daily_prices.csv')
        self.stocks_list_file = os.path.join(self.output_dir, 'data', 'us_stocks_list.csv')
        
        # Start date for historical data
        self.start_date = datetime(2020, 1, 1)
        self.end_date = datetime.now()
        
    def fetch_sp500_from_wikipedia(self) -> List[str]:
        """
        Fetch current S&P 500 tickers from Wikipedia.
        Returns list of tickers with proper formatting for yfinance.
        """
        import requests
        from io import StringIO
        
        logger.info("🌐 Fetching S&P 500 tickers from Wikipedia...")
        
        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            tables = pd.read_html(StringIO(response.text))
            df = tables[0]
            
            # Get Symbol column and convert to yfinance format
            # Wikipedia uses "." but yfinance uses "-" (e.g., BRK.B -> BRK-B)
            df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False)

            # Extract sector/industry from GICS columns
            result = df[['Symbol']].copy()
            result.columns = ['ticker']
            result['name'] = df.get('Security', df['Symbol'])
            result['sector'] = df.get('GICS Sector', 'Unknown')
            result['industry'] = df.get('GICS Sub-Industry', 'Unknown')

            logger.info(f"✅ Fetched {len(result)} tickers with sector data from Wikipedia")
            return result
            
        except Exception as e:
            logger.warning(f"⚠️ Wikipedia fetch failed: {e}")
            return []
    
    def fetch_nasdaq100_from_wikipedia(self) -> List[str]:
        """
        Fetch current NASDAQ 100 tickers from Wikipedia.
        """
        import requests
        from io import StringIO
        
        logger.info("🌐 Fetching NASDAQ 100 tickers from Wikipedia...")
        
        try:
            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            tables = pd.read_html(StringIO(response.text))
            # The table index for Nasdaq 100 constituents might vary, usually it's the 4th table (index 4)
            # but we should check headers or content. Table 4 is typically constituents
            # Let's inspect based on column name 'Ticker' or 'Symbol'
            target_table = None
            for table in tables:
                if 'Ticker' in table.columns or 'Symbol' in table.columns:
                    target_table = table
                    break
            
            if target_table is None: 
                # Fallback to index 4 if detection fails, commonly correct for this wiki page
                if len(tables) > 4:
                    target_table = tables[4]
                else: 
                    raise ValueError("Could not find constituents table")

            col_name = 'Ticker' if 'Ticker' in target_table.columns else 'Symbol'
            tickers = target_table[col_name].str.replace('.', '-', regex=False).tolist()
            
            logger.info(f"✅ Fetched {len(tickers)} tickers from Nasdaq 100")
            return tickers
            
        except Exception as e:
            logger.warning(f"⚠️ Nasdaq 100 fetch failed: {e}")
            return []

    def get_all_tickers(self) -> pd.DataFrame:
        """
        Get combined S&P 500 and Nasdaq 100 tickers list.
        Returns DataFrame with 'ticker', 'name', 'market' columns.
        """
        logger.info("📊 Loading Market Universe (S&P 500 + Nasdaq 100)...")
        
        # 1. Fetch S&P 500 (returns DataFrame with sector data)
        sp500_df = self.fetch_sp500_from_wikipedia()

        # 2. Fetch Nasdaq 100 (returns list of tickers)
        nasdaq_tickers = self.fetch_nasdaq100_from_wikipedia()

        # Fallback to cache if both failed
        if (sp500_df is None or (isinstance(sp500_df, (list, pd.DataFrame)) and len(sp500_df) == 0)) and not nasdaq_tickers and os.path.exists(self.stocks_list_file):
            logger.info("📂 Using cached stock list as fallback...")
            return pd.read_csv(self.stocks_list_file)

        # Handle legacy list return (backward compat)
        if isinstance(sp500_df, list):
            sp500_df = pd.DataFrame({'ticker': sp500_df, 'name': sp500_df, 'sector': 'Unknown', 'industry': 'Unknown'})

        # Add market column
        sp500_df['market'] = 'S&P500'

        # Merge Nasdaq 100
        existing_tickers = set(sp500_df['ticker'].tolist())
        nasdaq_only = [t for t in nasdaq_tickers if t not in existing_tickers]

        # Mark overlapping tickers
        sp500_df.loc[sp500_df['ticker'].isin(nasdaq_tickers), 'market'] = 'S&P500,NASDAQ100'

        # Add Nasdaq-only tickers
        if nasdaq_only:
            nasdaq_df = pd.DataFrame({
                'ticker': nasdaq_only,
                'name': nasdaq_only,
                'market': 'NASDAQ100',
                'sector': 'Unknown',
                'industry': 'Unknown',
            })
            df = pd.concat([sp500_df, nasdaq_df], ignore_index=True)
        else:
            df = sp500_df

        return df
        
    def run(self):
        """Main execution flow"""
        self.print_header("US Market Data Collection (S&P 500 + Nasdaq 100)")
        
        # 1. Get Tickers
        df_tickers = self.get_all_tickers()
        
        if df_tickers.empty:
            logger.error("❌ No tickers found. Aborting.")
            return

        # Save stock list
        logger.info(f"💾 Saving {len(df_tickers)} combined tickers to {self.stocks_list_file}")
        df_tickers.to_csv(self.stocks_list_file, index=False)
        
        tickers_list = df_tickers['ticker'].tolist()
        logger.info(f"🔢 Total Universe Size: {len(tickers_list)}")

        # 2. Fetch Prices (Incremental Update)
        self.update_prices(tickers_list)

    def update_prices(self, tickers: List[str]):
        """Fetch and update price data incrementally"""
        # Load existing price data if available
        if os.path.exists(self.prices_file):
            logger.info("📂 Loading existing price data...")
            try:
                # Optimized load: read only headers first or use chunking if huge
                # For 500-600 stocks, standard read_csv is okay (~100MB)
                existing_df = pd.read_csv(self.prices_file)
                existing_df['Date'] = pd.to_datetime(existing_df['Date'])
                
                # Pivot to get last date per ticker
                # Structure: Date, Open, High, Low, Close, Volume, Ticker
                last_dates = existing_df.groupby('Ticker')['Date'].max()
                logger.info(f"✅ Loaded history for {len(last_dates)} tickers")
                
            except Exception as e:
                logger.warning(f"⚠️ Error reading existing file: {e}. Starting fresh.")
                last_dates = pd.Series()
                existing_df = pd.DataFrame()
        else:
            last_dates = pd.Series()
            existing_df = pd.DataFrame()

        # Determine download ranges
        new_data_list = []
        
        # Batch size for downloading
        batch_size = 50 
        
        # Identify new vs existing tickers
        tickers_to_process = []
        for ticker in tickers:
            last_date = last_dates.get(ticker)
            start_date = self.start_date
            
            if pd.notna(last_date):
                start_date = last_date + timedelta(days=1)
                
            if start_date < self.end_date:
                tickers_to_process.append((ticker, start_date))
        
        if not tickers_to_process:
            logger.info("✨ All data is up to date!")
            return

        logger.info(f"🔄 Need to update {len(tickers_to_process)} tickers")
        
        # Group by start date to optimize batch downloads
        # (Many will share the same start date)
        from collections import defaultdict
        date_groups = defaultdict(list)
        for t, d in tickers_to_process:
            date_groups[d].append(t)
        
        # Initialize hybrid data fetcher (yfinance + Finnhub fallback)
        fetcher = USStockDataFetcher()
            
        # Download using hybrid fetcher with rate limiting
        for start_d, group_tickers in date_groups.items():
            logger.info(f"⬇️ Downloading {len(group_tickers)} stocks from {start_d.date()}...")
            
            try:
                # Use hybrid fetcher with rate limiting and Finnhub fallback
                data = fetcher.download_history(
                    symbols=group_tickers,
                    start_date=start_d,
                    end_date=self.end_date,
                    batch_size=25,  # Smaller batches to avoid rate limits
                    delay_between_batches=5.0  # 5 second delay between batches
                )
                
                if not data.empty:
                    new_data_list.append(data)
                    logger.info(f"   ✅ Got {len(data)} rows")
                    
            except Exception as e:
                logger.error(f"❌ Download failed for group starting {start_d.date()}: {e}")
        
        # Combine and Save
        if new_data_list:
            new_df = pd.concat(new_data_list)
            
            # Standardize columns
            # Ensure columns: Date, Ticker, Open, High, Low, Close, Volume
            # Make sure we have these columns (case sensitive check might be needed)
            # yfinance usually returns Proper Case (Open, Close...)
            
            # Merge with existing
            if not existing_df.empty:
                full_df = pd.concat([existing_df, new_df])
            else:
                full_df = new_df
                
            # Remove duplicates just in case
            full_df.drop_duplicates(subset=['Date', 'Ticker'], inplace=True)
            
            # Sort
            full_df.sort_values(['Ticker', 'Date'], inplace=True)
            
            # Save
            logger.info(f"💾 Saving updated data to {self.prices_file}")
            full_df.to_csv(self.prices_file, index=False)
            logger.info("✨ Update complete!")
        else:
            logger.info("⚠️ No new data downloaded.")



def main():
    """Main execution function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='US Stock Daily Prices Collector')
    parser.add_argument('--full', action='store_true', help='Full refresh (ignore existing data)')
    args = parser.parse_args()
    
    creator = USStockDailyPricesCreator()
    # Note: full_refresh is not implemented in new run() yet, so strictly ignoring args.full for now
    success = creator.run()
    
    if success:
        print("\n🎉 US Stock Daily Prices collection completed!")
        print(f"📁 File location: ./us_daily_prices.csv")
    else:
        print("\n❌ Collection failed.")


if __name__ == "__main__":
    main()
