#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEC EDGAR Filings Collector
- Fetches 10-K, 10-Q, 8-K filings from SEC EDGAR API
- Extracts Risk Factors and key sections
- Provides AI summary of recent filings
"""

import os
import json
import requests
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SECFilingsCollector:
    """Collect and analyze SEC filings using official EDGAR API"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'sec_filings.json')
        
        # SEC EDGAR API base URL
        self.base_url = "https://data.sec.gov"
        
        # User-Agent required by SEC
        self.headers = {
            'User-Agent': 'StockAnalysis/1.0 (personal use, contact@example.com)',
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'data.sec.gov'
        }
        
        # CIK cache file
        self.cik_cache_file = os.path.join(data_dir, 'output', 'cik_cache.json')
        self.cik_cache = self._load_cik_cache()
    
    def _load_cik_cache(self) -> Dict:
        """Load CIK mapping cache"""
        if os.path.exists(self.cik_cache_file):
            try:
                with open(self.cik_cache_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_cik_cache(self):
        """Save CIK mapping cache"""
        with open(self.cik_cache_file, 'w') as f:
            json.dump(self.cik_cache, f, indent=2)
    
    def get_cik_from_ticker(self, ticker: str) -> Optional[str]:
        """
        Get CIK number from ticker symbol.
        Uses SEC's company tickers JSON.
        """
        ticker = ticker.upper()
        
        # Check cache first
        if ticker in self.cik_cache:
            return self.cik_cache[ticker]
        
        try:
            # SEC provides a ticker-to-CIK mapping
            url = "https://www.sec.gov/files/company_tickers.json"
            
            # www.sec.gov requires different User-Agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Find ticker in the data
                for entry in data.values():
                    if entry.get('ticker', '').upper() == ticker:
                        cik = str(entry['cik_str']).zfill(10)
                        self.cik_cache[ticker] = cik
                        self._save_cik_cache()
                        return cik
        except Exception as e:
            logger.warning(f"Error getting CIK for {ticker}: {e}")
        
        return None
    
    def get_company_filings(self, ticker: str, limit: int = 10) -> Dict:
        """
        Get recent SEC filings for a company.
        Returns list of 10-K, 10-Q, 8-K filings.
        """
        cik = self.get_cik_from_ticker(ticker)
        if not cik:
            return {'ticker': ticker, 'error': 'CIK not found'}
        
        try:
            # Get company submissions
            url = f"{self.base_url}/submissions/CIK{cik}.json"
            response = requests.get(url, headers=self.headers, timeout=15)
            
            if response.status_code != 200:
                return {'ticker': ticker, 'error': f'SEC API error: {response.status_code}'}
            
            data = response.json()
            
            # Company info
            company_info = {
                'name': data.get('name', ''),
                'cik': cik,
                'sic': data.get('sic', ''),
                'sic_description': data.get('sicDescription', ''),
                'state': data.get('stateOfIncorporation', ''),
                'fiscal_year_end': data.get('fiscalYearEnd', '')
            }
            
            # Recent filings
            filings = data.get('filings', {}).get('recent', {})
            
            form_types = filings.get('form', [])
            filing_dates = filings.get('filingDate', [])
            accession_numbers = filings.get('accessionNumber', [])
            primary_documents = filings.get('primaryDocument', [])
            descriptions = filings.get('primaryDocDescription', [])
            
            # Filter for 10-K, 10-Q, 8-K
            target_forms = ['10-K', '10-Q', '8-K', '10-K/A', '10-Q/A', '8-K/A']
            
            filtered_filings = []
            for i in range(min(len(form_types), 50)):  # Check up to 50 recent
                form = form_types[i]
                if form in target_forms:
                    accession = accession_numbers[i].replace('-', '')
                    
                    filing = {
                        'form': form,
                        'filing_date': filing_dates[i],
                        'accession_number': accession_numbers[i],
                        'document': primary_documents[i],
                        'description': descriptions[i] if i < len(descriptions) else '',
                        'url': f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{primary_documents[i]}"
                    }
                    filtered_filings.append(filing)
                    
                    if len(filtered_filings) >= limit:
                        break
            
            return {
                'ticker': ticker,
                'company': company_info,
                'filings': filtered_filings,
                'fetch_time': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting filings for {ticker}: {e}")
            return {'ticker': ticker, 'error': str(e)}
    
    def get_filing_content(self, filing_url: str, max_chars: int = 50000) -> str:
        """
        Fetch and parse filing content (HTML).
        Extracts plain text for AI analysis.
        """
        try:
            response = requests.get(filing_url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
            }, timeout=30)
            
            if response.status_code != 200:
                return ""
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove scripts and styles
            for element in soup(['script', 'style']):
                element.decompose()
            
            text = soup.get_text(separator=' ', strip=True)
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text)
            
            return text[:max_chars]
            
        except Exception as e:
            logger.debug(f"Error fetching filing content: {e}")
            return ""
    
    def extract_risk_factors(self, ticker: str) -> Dict:
        """
        Extract Risk Factors section from latest 10-K.
        """
        filings = self.get_company_filings(ticker, limit=5)
        
        if 'error' in filings:
            return filings
        
        # Find latest 10-K
        ten_k = None
        for f in filings.get('filings', []):
            if f['form'] in ['10-K', '10-K/A']:
                ten_k = f
                break
        
        if not ten_k:
            return {'ticker': ticker, 'error': 'No 10-K found'}
        
        # Fetch content
        content = self.get_filing_content(ten_k['url'], max_chars=100000)
        
        if not content:
            return {
                'ticker': ticker,
                'filing_date': ten_k['filing_date'],
                'error': 'Could not fetch filing content'
            }
        
        # Extract Risk Factors section
        # Look for "Item 1A" or "Risk Factors"
        risk_start = re.search(r'(ITEM\s*1A\.?\s*RISK\s*FACTORS)', content, re.IGNORECASE)
        if risk_start:
            start_idx = risk_start.end()
            
            # Find end (next Item)
            risk_end = re.search(r'ITEM\s*(1B|2)\.?', content[start_idx:], re.IGNORECASE)
            end_idx = start_idx + risk_end.start() if risk_end else start_idx + 15000
            
            risk_text = content[start_idx:end_idx].strip()
            
            # Truncate to reasonable length
            risk_text = risk_text[:10000]
            
            return {
                'ticker': ticker,
                'filing_date': ten_k['filing_date'],
                'filing_url': ten_k['url'],
                'risk_factors_text': risk_text,
                'risk_factors_length': len(risk_text)
            }
        
        return {
            'ticker': ticker,
            'filing_date': ten_k['filing_date'],
            'error': 'Risk Factors section not found'
        }
    
    def analyze_tickers(self, tickers: List[str]) -> Dict:
        """Collect filings for multiple tickers"""
        logger.info(f"📋 Collecting SEC filings for {len(tickers)} tickers...")
        
        results = {}
        
        for ticker in tickers:
            logger.info(f"  Processing {ticker}...")
            filings = self.get_company_filings(ticker, limit=5)
            results[ticker] = filings
            time.sleep(0.2)  # Rate limiting (SEC requests 10 req/sec max)
        
        return {
            'metadata': {
                'as_of_date': datetime.now().strftime('%Y-%m-%d'),
                'fetch_time': datetime.now().isoformat(),
                'source': 'sec_edgar_api',
                'ticker_count': len(tickers)
            },
            'filings': results
        }
    
    def save_results(self, data: Dict):
        """Save results to JSON"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Saved to {self.output_file}")


def main():
    import argparse
    import pandas as pd
    
    parser = argparse.ArgumentParser(description='SEC EDGAR Filings Collector')
    parser.add_argument('--tickers', nargs='+', help='List of tickers')
    parser.add_argument('--risk', type=str, help='Extract risk factors for ticker')
    args = parser.parse_args()
    
    collector = SECFilingsCollector()
    
    if args.risk:
        # Extract risk factors for single ticker
        result = collector.extract_risk_factors(args.risk)
        print(f"\n📋 Risk Factors for {args.risk}")
        print("=" * 60)
        if 'error' in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Filing Date: {result['filing_date']}")
            print(f"URL: {result['filing_url']}")
            print(f"\nRisk Factors Preview (first 1000 chars):")
            print("-" * 40)
            print(result.get('risk_factors_text', '')[:1000])
        return
    
    # Default: collect filings for top picks
    target_tickers = args.tickers
    if not target_tickers:
        try:
            picks_file = 'output/smart_money_picks_v2.csv'
            if os.path.exists(picks_file):
                df = pd.read_csv(picks_file)
                target_tickers = df['ticker'].tolist()[:20]
            else:
                target_tickers = ['AAPL', 'MSFT', 'NVDA', 'META', 'GOOGL']
        except:
            target_tickers = ['AAPL', 'MSFT', 'NVDA']
    
    result = collector.analyze_tickers(target_tickers)
    collector.save_results(result)
    
    print("\n" + "=" * 60)
    print("📋 SEC FILINGS SUMMARY")
    print("=" * 60)
    
    for ticker, data in result['filings'].items():
        if 'error' in data:
            print(f"\n{ticker}: Error - {data['error']}")
        else:
            company = data.get('company', {})
            filings = data.get('filings', [])
            print(f"\n📄 {ticker} ({company.get('name', 'N/A')[:40]})")
            for f in filings[:3]:
                print(f"   {f['form']} - {f['filing_date']}")


if __name__ == "__main__":
    main()
