#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Insider Trading Tracker
- Scrapes recent insider transactions from Finviz
- Generates output/insider_trading.json
"""

import os
import json
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36'
}


class InsiderTracker:
    """Scrape Finviz insider trading page for recent transactions."""

    FINVIZ_URL = 'https://finviz.com/insidertrading.ashx'

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        os.makedirs(os.path.join(data_dir, 'output'), exist_ok=True)
        self.output_file = os.path.join(data_dir, 'output', 'insider_trading.json')

    def scrape_insider_transactions(self, max_pages: int = 3) -> List[Dict]:
        """Scrape Finviz insider trading table for recent transactions."""
        all_transactions = []

        for page in range(1, max_pages + 1):
            try:
                params = {'tc': 1}  # tc=1 = purchases only
                if page > 1:
                    params['r'] = (page - 1) * 20 + 1  # Finviz pagination offset

                resp = requests.get(self.FINVIZ_URL, params=params,
                                    headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')

                # Find the insider trading data table
                # Finviz uses class 'styled-table-new' for the main data table
                table = soup.find('table', class_='styled-table-new')
                if not table:
                    # Fallback: find any table with Ticker/Owner headers
                    for t in soup.find_all('table'):
                        header_text = t.get_text()[:200].lower()
                        if 'ticker' in header_text and 'owner' in header_text:
                            table = t
                            break

                if not table:
                    logger.warning(f"Could not find insider trading table on page {page}")
                    break

                rows = table.find_all('tr')[1:]  # Skip header row
                page_count = 0

                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) < 8:
                        continue

                    try:
                        # Finviz columns: Ticker, Owner, Relationship, Date,
                        #   Transaction, Cost, #Shares, Value($), #SharesTotal, SEC Form 4
                        ticker = cols[0].get_text(strip=True)
                        name = cols[1].get_text(strip=True)       # Owner name
                        title = cols[2].get_text(strip=True)       # Relationship
                        trade_date = cols[3].get_text(strip=True)
                        transaction_type = cols[4].get_text(strip=True)

                        shares_text = cols[6].get_text(strip=True).replace(',', '')
                        value_text = cols[7].get_text(strip=True).replace(',', '')

                        # Parse numeric values (may contain non-digit chars)
                        shares = int(''.join(c for c in shares_text if c.isdigit()) or '0')
                        value = int(''.join(c for c in value_text if c.isdigit()) or '0')

                        date_str = self._parse_date(trade_date)

                        transaction = {
                            'ticker': ticker.upper(),
                            'name': name,
                            'title': title,
                            'transaction_type': transaction_type,
                            'shares': shares,
                            'value': value,
                            'date': date_str,
                        }
                        all_transactions.append(transaction)
                        page_count += 1

                    except (ValueError, IndexError):
                        continue

                logger.info(f"  Page {page}: scraped {page_count} transactions")

            except requests.RequestException as e:
                logger.error(f"Error fetching page {page}: {e}")
                break

        logger.info(f"Total insider transactions scraped: {len(all_transactions)}")
        return all_transactions

    def _parse_date(self, date_str: str) -> str:
        """Try multiple date formats from Finviz."""
        for fmt in ("%b %d '%y", '%b %d', '%Y-%m-%d', '%m/%d/%Y', '%b %d %I:%M %p'):
            try:
                dt = datetime.strptime(date_str, fmt)
                # If year is 1900 (no year in format), use current year
                if dt.year == 1900:
                    dt = dt.replace(year=datetime.now().year)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        return date_str

    def save_results(self, transactions: List[Dict]):
        """Save to output/insider_trading.json with `transactions` key."""
        data = {
            'timestamp': datetime.now().isoformat(),
            'total_count': len(transactions),
            'transactions': transactions,
        }
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Saved {len(transactions)} insider transactions to {self.output_file}")


def main():
    tracker = InsiderTracker()
    transactions = tracker.scrape_insider_transactions(max_pages=3)
    tracker.save_results(transactions)

    print("\n" + "=" * 60)
    print("🕵️ INSIDER TRADING (Recent Purchases)")
    print("=" * 60)

    for t in transactions[:10]:
        print(f"  {t['date']}  {t['ticker']:6}  {t['name'][:25]:25}  "
              f"{t['title'][:20]:20}  ${t['value']:>12,}  {t['shares']:>8,} shares")


if __name__ == "__main__":
    main()
