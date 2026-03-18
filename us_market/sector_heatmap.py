#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sector Performance Heatmap Data Collector
- Collects sector ETF performance data
- Provides data for treemap/heatmap visualization
"""

import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import Dict, List
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SectorHeatmapCollector:
    """Collect sector ETF performance data for heatmap visualization"""
    
    def __init__(self):
        # Sector ETFs with full names
        self.sector_etfs = {
            # SPDR Sector ETFs
            'XLK': {'name': 'Technology', 'color': '#4A90A4'},
            'XLF': {'name': 'Financials', 'color': '#6B8E23'},
            'XLV': {'name': 'Healthcare', 'color': '#FF69B4'},
            'XLE': {'name': 'Energy', 'color': '#FF6347'},
            'XLY': {'name': 'Consumer Disc.', 'color': '#FFD700'},
            'XLP': {'name': 'Consumer Staples', 'color': '#98D8C8'},
            'XLI': {'name': 'Industrials', 'color': '#DDA0DD'},
            'XLB': {'name': 'Materials', 'color': '#F0E68C'},
            'XLU': {'name': 'Utilities', 'color': '#87CEEB'},
            'XLRE': {'name': 'Real Estate', 'color': '#CD853F'},
            'XLC': {'name': 'Comm. Services', 'color': '#9370DB'},
        }
        
        # Top stocks by sector for detail view
        self.sector_stocks = {
            'Technology': ['AAPL', 'MSFT', 'NVDA', 'AVGO', 'ORCL', 'CRM', 'AMD', 'ADBE', 'CSCO', 'INTC'],
            'Financials': ['BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'SPGI', 'AXP'],
            'Healthcare': ['LLY', 'UNH', 'JNJ', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR', 'BMY'],
            'Energy': ['XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'PSX', 'VLO', 'OXY', 'WMB'],
            'Consumer Disc.': ['AMZN', 'TSLA', 'HD', 'MCD', 'NKE', 'LOW', 'SBUX', 'TJX', 'BKNG', 'CMG'],
            'Consumer Staples': ['WMT', 'PG', 'COST', 'KO', 'PEP', 'PM', 'MDLZ', 'MO', 'CL', 'KMB'],
            'Industrials': ['CAT', 'GE', 'RTX', 'HON', 'UNP', 'BA', 'DE', 'LMT', 'UPS', 'MMM'],
            'Materials': ['LIN', 'APD', 'SHW', 'FCX', 'ECL', 'NEM', 'NUE', 'DOW', 'DD', 'VMC'],
            'Utilities': ['NEE', 'SO', 'DUK', 'CEG', 'SRE', 'AEP', 'D', 'PCG', 'EXC', 'XEL'],
            'Real Estate': ['PLD', 'AMT', 'EQIX', 'SPG', 'PSA', 'O', 'WELL', 'DLR', 'CCI', 'AVB'],
            'Comm. Services': ['META', 'GOOGL', 'GOOG', 'NFLX', 'DIS', 'T', 'VZ', 'CMCSA', 'TMUS', 'CHTR'],
        }
    
    def get_sector_performance(self, period: str = '1d') -> Dict:
        """Get sector ETF performance data"""
        logger.info(f"📊 Fetching sector performance ({period})...")
        
        tickers = list(self.sector_etfs.keys())
        
        try:
            # Map period to yfinance period
            period_map = {
                '1d': ('1d', '2d'),
                '5d': ('5d', '8d'),
                '1m': ('1mo', '35d'),
                '3m': ('3mo', '95d'),
                'ytd': ('ytd', None),
                '1y': ('1y', None)
            }
            
            yf_period = period_map.get(period, ('5d', '8d'))[0]

            # Use at least 5d to ensure we have enough data points
            fetch_period = yf_period if yf_period != '1d' else '5d'

            data = yf.download(tickers, period=fetch_period, progress=False)

            if data.empty:
                return {'error': 'No data'}

            sectors = []

            for ticker, info in self.sector_etfs.items():
                try:
                    if ticker not in data['Close'].columns:
                        continue

                    prices = data['Close'][ticker].dropna()
                    if len(prices) < 2:
                        continue

                    current_price = prices.iloc[-1]
                    # For 1d period, compare last two trading days
                    # For longer periods, compare first to last
                    if period == '1d':
                        start_price = prices.iloc[-2]
                    else:
                        start_price = prices.iloc[0]
                    change_pct = ((current_price / start_price) - 1) * 100
                    
                    # Get market cap proxy (volume * price)
                    volume = data['Volume'][ticker].iloc[-1] if 'Volume' in data.columns else 1000000
                    market_weight = volume * current_price / 1e6  # Millions
                    
                    sectors.append({
                        'ticker': ticker,
                        'name': info['name'],
                        'price': round(current_price, 2),
                        'change': round(change_pct, 2),
                        'weight': round(market_weight, 0),
                        'color': self._get_color(change_pct)
                    })
                except Exception as e:
                    logger.debug(f"Error processing {ticker}: {e}")
            
            # Sort by weight for treemap
            sectors.sort(key=lambda x: x['weight'], reverse=True)
            
            return {
                'timestamp': datetime.now().isoformat(),
                'period': period,
                'sectors': sectors
            }
            
        except Exception as e:
            logger.error(f"Error fetching sector data: {e}")
            return {'error': str(e)}
    
    def get_sector_stocks_performance(self, sector_name: str) -> List[Dict]:
        """Get individual stock performance within a sector"""
        stocks = self.sector_stocks.get(sector_name, [])
        if not stocks:
            return []
        
        try:
            data = yf.download(stocks, period='2d', progress=False)
            
            if data.empty:
                return []
            
            results = []
            for ticker in stocks:
                try:
                    if ticker not in data['Close'].columns:
                        continue
                    
                    prices = data['Close'][ticker].dropna()
                    if len(prices) < 2:
                        continue
                    
                    current = prices.iloc[-1]
                    prev = prices.iloc[-2]
                    change = ((current / prev) - 1) * 100
                    
                    volume = data['Volume'][ticker].iloc[-1] if 'Volume' in data.columns else 1000000
                    
                    results.append({
                        'ticker': ticker,
                        'price': round(current, 2),
                        'change': round(change, 2),
                        'volume': int(volume),
                        'color': self._get_color(change)
                    })
                except:
                    pass
            
            return sorted(results, key=lambda x: abs(x['change']), reverse=True)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return []
    
    def _get_color(self, change: float) -> str:
        """Get color based on change percentage"""
        if change >= 3:
            return '#00C853'  # Bright green
        elif change >= 1:
            return '#4CAF50'  # Green
        elif change >= 0:
            return '#81C784'  # Light green
        elif change >= -1:
            return '#EF9A9A'  # Light red
        elif change >= -3:
            return '#F44336'  # Red
        else:
            return '#B71C1C'  # Dark red
    
    def get_full_market_map(self, period: str = '5d') -> Dict:
        """Get full market map data (Sectors -> Stocks) for Treemap"""
        logger.info(f"📊 Fetching full market map data ({period})...")
        
        # Collect all tickers
        all_tickers = []
        ticker_to_sector = {}
        
        for sector, stocks in self.sector_stocks.items():
            all_tickers.extend(stocks)
            for stock in stocks:
                ticker_to_sector[stock] = sector
                
        try:
            # Fetch all data at once
            data = yf.download(all_tickers, period=period, progress=False)
            
            if data.empty:
                return {'error': 'No data'}
            
            # Organize data by sector
            market_map = {sector: [] for sector in self.sector_stocks}
            
            for ticker in all_tickers:
                try:
                    if ticker not in data['Close'].columns:
                        continue
                        
                    prices = data['Close'][ticker].dropna()
                    if len(prices) < 2:
                        continue
                        
                    # Calculate change
                    current = prices.iloc[-1]
                    prev = prices.iloc[-2]
                    change = ((current / prev) - 1) * 100
                    
                    # Calculate weight (Market Cap proxy = Price * Volume * Factor)
                    # Note: Using Volume * Price as rough relative weight proxy since Market Cap isn't directly in history
                    # For better accuracy, we'd need Ticker.info but that's slow for 100+ stocks.
                    # Using Close * Volume as "Traded Value" which is a decent activity/importance proxy for heatmap
                    if 'Volume' in data.columns and ticker in data['Volume'].columns:
                        volume = data['Volume'][ticker].iloc[-1]
                        # Handling NaN volume
                        if pd.isna(volume):
                            volume = 1000000
                    else:
                        volume = 1000000
                        
                    weight = current * volume 
                    
                    sector = ticker_to_sector.get(ticker, 'Unknown')
                    if sector in market_map:
                        market_map[sector].append({
                            'x': ticker,  # Label
                            'y': round(weight, 0),  # Size (Weight)
                            'price': round(current, 2),
                            'change': round(change, 2),
                            'color': self._get_color(change) # Pre-calculate color
                        })
                        
                except Exception as e:
                    # logger.debug(f"Error processing {ticker}: {e}")
                    pass
            
            # Format for ApexCharts Treemap
            # Series data: [{name: 'Sector', data: [{x: 'AAPL', y: 100, ...}, ...]}, ...]
            series = []
            for sector_name, stocks in market_map.items():
                if stocks:
                    # Sort stocks by weight (size)
                    stocks.sort(key=lambda x: x['y'], reverse=True)
                    series.append({
                        'name': sector_name,
                        'data': stocks
                    })
            
            # Sort sectors by total weight
            series.sort(key=lambda s: sum(item['y'] for item in s['data']), reverse=True)
            
            # Get last trading date from index
            last_date = data.index[-1].strftime('%Y-%m-%d') if not data.empty and hasattr(data.index, 'strftime') else datetime.now().strftime('%Y-%m-%d')

            return {
                'timestamp': datetime.now().isoformat(),
                'data_date': last_date,
                'period': period,
                'series': series
            }
            
        except Exception as e:
            logger.error(f"Error fetching market map: {e}")
            return {'error': str(e)}

    def save_data(self, output_dir: str = '.'):
        """Save sector data to JSON"""
        # We now save the full market map instead of just sector ETFs
        data = self.get_full_market_map('5d')
        
        output_file = os.path.join(output_dir, 'output', 'sector_heatmap.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Saved to {output_file}")
        return data


def main():
    collector = SectorHeatmapCollector()
    
    # Get 1-day performance
    data = collector.get_sector_performance('1d')
    
    print("\n" + "="*60)
    print("📊 SECTOR HEATMAP DATA")
    print("="*60)
    
    if 'error' in data:
        print(f"❌ Error: {data['error']}")
        return
    
    for sector in data['sectors']:
        change = sector['change']
        emoji = "🟢" if change >= 0 else "🔴"
        bar = "█" * int(abs(change) * 2)
        print(f"{emoji} {sector['name']:18} | {sector['ticker']} | {change:+.2f}% {bar}")
    
    # Save data
    collector.save_data()


if __name__ == "__main__":
    main()
