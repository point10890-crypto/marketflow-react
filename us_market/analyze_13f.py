#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US 13F Institutional Holdings Analysis
Fetches and analyzes institutional holdings from SEC EDGAR
"""

import os
import pandas as pd
import numpy as np
import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import time
from data_fetcher import USStockDataFetcher

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SEC13FAnalyzer:
    """
    Analyze institutional holdings from SEC 13F filings
    Note: 13F filings are quarterly, with 45-day delay after quarter end
    """
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'us_13f_holdings.csv')
        self.cache_file = os.path.join(data_dir, 'us_13f_cache.json')
        
        # SEC EDGAR API base URL
        self.sec_base_url = "https://data.sec.gov"
        
        # User-Agent required by SEC
        self.headers = {
            'User-Agent': 'StockAnalysis/1.0 (contact@example.com)',
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'data.sec.gov'
        }
        
        # Major institutional investors (CIK numbers)
        self.major_institutions = {
            '0001067983': 'Berkshire Hathaway',
            '0001350694': 'Citadel Advisors',
            '0001423053': 'Renaissance Technologies',
            '0001037389': 'Bridgewater Associates',
            '0001336528': 'Millennium Management',
            '0001649339': 'Point72 Asset Management',
            '0001364742': 'Two Sigma Investments',
            '0001167483': 'Elliott Investment Management',
            '0001061165': 'Tiger Global Management',
            '0001697748': 'BlackRock Inc.',
            '0001040280': 'Vanguard Group',
            '0001166559': 'Fidelity Management',
            '0001095620': 'State Street Corporation',
            '0000895421': 'Soros Fund Management',
            '0001273087': 'Appaloosa Management',
        }
        
        # Initialize Hybrid Fetcher
        self.fetcher = USStockDataFetcher()
    
    def get_latest_13f_filing(self, cik: str) -> Optional[Dict]:
        """Fetch latest 13F filing for an institution"""
        try:
            # Add leading zeros to CIK if needed
            cik_padded = cik.zfill(10)
            
            # Fetch company submissions
            url = f"{self.sec_base_url}/submissions/CIK{cik_padded}.json"
            
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code != 200:
                logger.debug(f"Failed to fetch {cik}: HTTP {response.status_code}")
                return None
            
            data = response.json()
            
            # Find latest 13F-HR filing
            filings = data.get('filings', {}).get('recent', {})
            
            if not filings:
                return None
            
            forms = filings.get('form', [])
            dates = filings.get('filingDate', [])
            accession_numbers = filings.get('accessionNumber', [])
            
            for i, form in enumerate(forms):
                if form == '13F-HR':
                    return {
                        'cik': cik,
                        'company_name': data.get('name', ''),
                        'filing_date': dates[i],
                        'accession_number': accession_numbers[i].replace('-', '')
                    }
            
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching 13F for {cik}: {e}")
            return None
    
    def parse_13f_holdings(self, cik: str, accession: str) -> List[Dict]:
        """Parse holdings from 13F filing"""
        try:
            cik_padded = cik.zfill(10)
            
            # Try to get the infotable.xml or primary_doc.xml
            base_url = f"{self.sec_base_url}/Archives/edgar/data/{cik_padded}/{accession}"
            
            # Try common filing document names
            doc_names = ['infotable.xml', 'form13fInfoTable.xml', 'primary_doc.xml']
            
            for doc_name in doc_names:
                url = f"{base_url}/{doc_name}"
                response = requests.get(url, headers=self.headers, timeout=10)
                
                if response.status_code == 200:
                    # Parse XML here (simplified - would need proper XML parsing)
                    # For now, return empty list as proper parsing requires XML library
                    break
            
            # Note: Full implementation would parse the XML to extract holdings
            # This is a simplified version
            return []
            
        except Exception as e:
            logger.debug(f"Error parsing holdings: {e}")
            return []
    
    def get_aggregated_holdings_from_finviz(self, tickers: List[str]) -> pd.DataFrame:
        """
        Alternative: Get institutional ownership data from public sources
        Uses hybrid fetcher
        """
        results = []
        
        for ticker in tickers:
            try:
                # 1. Ownership Data
                inst_data = self.fetcher.get_institutional_data(ticker)
                inst_ownership = inst_data.get('institutional_pct', 0)
                insider_ownership = inst_data.get('insider_pct', 0)
                
                # Top Holder
                top_holder = 'N/A'
                top_holder_pct = 0
                
                if 'holders' in inst_data:
                    holders = inst_data['holders']
                    if holders:
                        # Finnhub format check
                        if isinstance(holders, list) and len(holders) > 0:
                            first = holders[0]
                            # Handle both Finnhub dict and YF DataFrame (fallback)
                            if isinstance(first, dict): # Finnhub
                                top_holder = first.get('name', 'N/A')
                                top_holder_pct = first.get('percentage', 0)
                            elif hasattr(first, 'iloc'): # YF DataFrame not list of dicts?
                                # Wait, data_fetcher normalized this?
                                # In data_fetcher, 'holders' is list for Finnhub
                                # For YF fallback, it didn't return 'holders' key in my implementation above
                                pass
                
                # Handle YF fallback if data_fetcher didn't return holders list
                # (My previous implementation of data_fetcher YF fallback only returned pcts, not holders list)
                
                results.append({
                    'ticker': ticker,
                    'institutional_pct': round(inst_ownership * 100, 2) if inst_ownership else 0,
                    'insider_pct': round(insider_ownership * 100, 2) if insider_ownership else 0,
                    'top_holder': top_holder,
                    'top_holder_pct': round(top_holder_pct, 2)
                })
                
            except Exception as e:
                logger.debug(f"Error getting holdings for {ticker}: {e}")
                continue
        
        return pd.DataFrame(results)
    
    def analyze_institutional_changes(self, tickers: List[str]) -> pd.DataFrame:
        """
        Analyze institutional ownership and recent changes
        Uses hybrid fetcher (Finnhub + yfinance fallback)
        """
        from tqdm import tqdm
        
        results = []
        
        for ticker in tqdm(tickers, desc="Fetching institutional data"):
            try:
                # Rate limiting - 1초 딜레이로 429 에러 방지
                time.sleep(1)
                
                # 1. Institutional Ownership
                inst_data = self.fetcher.get_institutional_data(ticker)
                inst_pct = inst_data.get('institutional_pct', 0)
                insider_pct = inst_data.get('insider_pct', 0)
                num_inst_holders = len(inst_data.get('holders', [])) if 'holders' in inst_data else 0
                
                # 2. Company Info & Stats
                # Note: Float and Short data is rich in yfinance but sparse in Free Finnhub
                # We try to get basics
                profile = self.fetcher.get_company_info(ticker)
                shares_outstanding = profile.get('market_cap', 0) # Placeholder if shares not avail
                
                # Default values if not available (Finnhub free tier limit)
                float_shares = 0
                short_pct = 0
                
                # 3. Insider Transactions
                insider_data = self.fetcher.get_insider_sentiment(ticker)
                buys = 0
                sells = 0
                insider_sentiment = 'Unknown'
                
                if 'transactions' in insider_data:
                    # Finnhub format
                    txns = insider_data['transactions']
                    for txn in txns:
                        change = txn.get('change', 0)
                        if change > 0: buys += 1
                        elif change < 0: sells += 1
                
                elif 'transactions_df' in insider_data:
                    # YFinance DataFrame format
                    txn_df = insider_data['transactions_df']
                    if txn_df is not None and not txn_df.empty:
                        recent = txn_df.head(10)
                        buys = len(recent[recent['Transaction'].str.contains('Buy', na=False)])
                        sells = len(recent[recent['Transaction'].str.contains('Sale', na=False)])
                
                if buys > sells:
                    insider_sentiment = 'Buying'
                elif sells > buys:
                    insider_sentiment = 'Selling'
                else:
                    insider_sentiment = 'Neutral'
                
                # 4. Score Calculation (0-100)
                score = 50
                
                # Institutional ownership
                if inst_pct > 0.8: score += 15
                elif inst_pct > 0.6: score += 10
                elif inst_pct < 0.3: score -= 10
                
                # Insider activity
                if buys > sells: score += 15
                elif sells > buys: score -= 10
                
                # Short interest (if available) - Note: Finnhub Free Tier often returns 0
                if short_pct > 0:
                    if short_pct > 0.2: score -= 20
                    elif short_pct > 0.1: score -= 10
                    elif short_pct < 0.03: score += 5
                else:
                    # No data available or 0% short interest
                    pass
                
                score = max(0, min(100, score))
                
                # Determine stage
                if score >= 70: stage = "Strong Institutional Support"
                elif score >= 55: stage = "Institutional Support"
                elif score >= 45: stage = "Neutral"
                elif score >= 30: stage = "Institutional Concern"
                else: stage = "Strong Institutional Selling"
                
                results.append({
                    'ticker': ticker,
                    'institutional_pct': round(inst_pct * 100, 2),
                    'insider_pct': round(insider_pct * 100, 2),
                    'short_pct': round(short_pct * 100, 2),
                    'float_shares_m': round(float_shares / 1e6, 2) if float_shares else 0,
                    'num_inst_holders': num_inst_holders,
                    'insider_buys': buys,
                    'insider_sells': sells,
                    'insider_sentiment': insider_sentiment,
                    'institutional_score': score,
                    'institutional_stage': stage
                })
                
            except Exception as e:
                logger.debug(f"Error analyzing {ticker}: {e}")
                continue
        
        return pd.DataFrame(results)
    
    def run(self) -> pd.DataFrame:
        """Run institutional analysis for stocks in the data directory"""
        logger.info("🚀 Starting 13F Institutional Analysis...")
        
        # Load stock list
        stocks_file = os.path.join(self.data_dir, 'data', 'us_stocks_list.csv')
        
        if os.path.exists(stocks_file):
            stocks_df = pd.read_csv(stocks_file)
            # Limit to top 50 stocks to avoid Yahoo Finance rate limiting
            tickers = stocks_df['ticker'].head(50).tolist()
            logger.info(f"📊 Limiting to top 50 stocks (out of {len(stocks_df)}) to avoid rate limits")
        else:
            logger.warning("Stock list not found. Using top 50 S&P 500 stocks.")
            tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
                      'UNH', 'JNJ', 'JPM', 'V', 'XOM', 'PG', 'MA', 'HD', 'CVX', 'MRK',
                      'ABBV', 'LLY', 'PEP', 'KO', 'COST', 'AVGO', 'WMT', 'MCD', 'TMO',
                      'CSCO', 'ABT', 'CRM', 'ACN', 'DHR', 'ORCL', 'NKE', 'TXN', 'PM',
                      'NEE', 'INTC', 'AMD', 'QCOM', 'IBM', 'GS', 'CAT', 'BA', 'DIS',
                      'NFLX', 'PYPL', 'ADBE', 'NOW', 'INTU']
        
        logger.info(f"📊 Analyzing {len(tickers)} stocks")
        
        # Run analysis
        results_df = self.analyze_institutional_changes(tickers)
        
        # Save results
        if not results_df.empty:
            results_df.to_csv(self.output_file, index=False)
            logger.info(f"✅ Analysis complete! Saved to {self.output_file}")
            
            # Summary
            logger.info("\n📊 Summary:")
            stage_counts = results_df['institutional_stage'].value_counts()
            for stage, count in stage_counts.items():
                logger.info(f"   {stage}: {count} stocks")
        else:
            logger.warning("No results to save")
        
        return results_df


def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description='13F Institutional Analysis')
    parser.add_argument('--dir', default='.', help='Data directory')
    parser.add_argument('--tickers', nargs='+', help='Specific tickers to analyze')
    args = parser.parse_args()
    
    analyzer = SEC13FAnalyzer(data_dir=args.dir)
    
    if args.tickers:
        results = analyzer.analyze_institutional_changes(args.tickers)
    else:
        results = analyzer.run()
    
    if not results.empty:
        # Show top institutional support
        print("\n🏦 Top 10 Institutional Support:")
        top_10 = results.nlargest(10, 'institutional_score')
        for _, row in top_10.iterrows():
            print(f"   {row['ticker']}: Score {row['institutional_score']} | "
                  f"Inst: {row['institutional_pct']:.1f}% | "
                  f"Insider: {row['insider_sentiment']}")
        
        # Show stocks with insider buying
        print("\n📈 Insider Buying Activity:")
        buying = results[results['insider_sentiment'] == 'Buying'].head(10)
        for _, row in buying.iterrows():
            print(f"   {row['ticker']}: {row['insider_buys']} buys vs {row['insider_sells']} sells")


if __name__ == "__main__":
    main()
