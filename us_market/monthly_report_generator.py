#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 ULTRATHINK: Historical Monthly Report Generator

Generates comprehensive monthly market reports for US market (2020-2024)
using all available data sources:
- Market indices (SPY, QQQ, IWM)
- Volatility (VIX, SKEW)
- Yields (2Y, 10Y, 30Y)
- Currency (DXY)
- Commodities (Gold, Oil, Copper)
- Global markets (KOSPI, Nikkei, DAX, FTSE)
- Sectors (11 SPDR ETFs)
- Crypto (BTC, ETH)
- Market breadth
- AI Summary (Gemini)
"""
import os
import sys
import json
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from pathlib import Path
import time

from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class MonthlyData:
    """월별 데이터 컨테이너"""
    year: int
    month: int
    start_date: str
    end_date: str
    trading_days: int
    
    # Market Performance
    spy_return: float
    qqq_return: float
    iwm_return: float
    spy_high: float
    spy_low: float
    
    # Volatility
    vix_avg: float
    vix_high: float
    vix_low: float
    vix_change: float
    
    # Yields
    yield_10y_start: float
    yield_10y_end: float
    yield_10y_change: float
    yield_2y_10y_spread: float
    
    # Currency
    dxy_change: float
    
    # Commodities
    gold_change: float
    oil_change: float
    copper_change: float
    
    # Global
    kospi_change: float
    nikkei_change: float
    dax_change: float
    ftse_change: float
    
    # Sectors
    sector_performance: Dict[str, float]
    best_sector: str
    worst_sector: str
    
    # Breadth
    breadth_ratio: float  # stocks above 50 DMA
    rsp_spy_spread: float  # Equal weight vs Cap weight
    
    # Crypto
    btc_change: float
    eth_change: float
    
    # AI Summary
    ai_summary: str = ""


class MonthlyReportGenerator:
    """월별 보고서 생성기"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_dir = os.path.join(data_dir, 'monthly_reports')
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Tickers for data fetching
        self.tickers = {
            # Indices
            'SPY': 'SPY', 'QQQ': 'QQQ', 'IWM': 'IWM', 'DIA': 'DIA',
            # Volatility
            'VIX': '^VIX',
            # Yields
            '10Y': '^TNX', '2Y': '^IRX', '30Y': '^TYX',
            # Currency
            'DXY': 'DX-Y.NYB',
            # Commodities
            'GOLD': 'GC=F', 'OIL': 'CL=F', 'COPPER': 'HG=F',
            # Global
            'KOSPI': '^KS11', 'NIKKEI': '^N225', 'DAX': '^GDAXI', 'FTSE': '^FTSE',
            # Breadth
            'RSP': 'RSP',
            # Crypto
            'BTC': 'BTC-USD', 'ETH': 'ETH-USD',
        }
        
        # Sector ETFs
        self.sector_etfs = {
            'Technology': 'XLK',
            'Healthcare': 'XLV',
            'Financials': 'XLF',
            'Consumer Discretionary': 'XLY',
            'Communication': 'XLC',
            'Industrials': 'XLI',
            'Consumer Staples': 'XLP',
            'Energy': 'XLE',
            'Utilities': 'XLU',
            'Real Estate': 'XLRE',
            'Materials': 'XLB',
        }
        
        # Cache for downloaded data
        self._data_cache: Dict[str, pd.DataFrame] = {}
        
        # Gemini API
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
    
    def _generate_ai_summary(self, data: 'MonthlyData') -> str:
        """Generate AI summary using Gemini API"""
        if not self.google_api_key:
            logger.warning("GOOGLE_API_KEY not set, skipping AI summary")
            return ""
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.google_api_key)
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            
            prompt = f"""You are a financial analyst. Analyze the following US market data for {data.year}-{data.month:02d} and provide a brief summary (3-5 bullet points) of the key events and market dynamics.
            Provide the analysis in BOTH English and Korean.

## Market Data:
- S&P 500: {data.spy_return:+.2f}%
- Nasdaq 100: {data.qqq_return:+.2f}%
- Russell 2000: {data.iwm_return:+.2f}%
- VIX Average: {data.vix_avg:.1f} (High: {data.vix_high:.1f})
- 10Y Yield: {data.yield_10y_start:.2f}% → {data.yield_10y_end:.2f}%
- DXY (Dollar): {data.dxy_change:+.2f}%
- Gold: {data.gold_change:+.2f}%
- Oil: {data.oil_change:+.2f}%
- Bitcoin: {data.btc_change:+.2f}%
- Best Sector: {data.best_sector}
- Worst Sector: {data.worst_sector}

Based on these metrics and your knowledge of what happened in {data.year}-{data.month:02d}, provide:
1. Key market events that month (Fed decisions, earnings, geopolitical events)
2. Why the market moved the way it did
3. Notable sector rotations

Format exactly as follows:
[ENGLISH]
* (English bullet points)

[KOREAN]
* (Korean bullet points)
"""
            
            response = model.generate_content(prompt)
            summary = response.text.strip()
            
            # Rate limit
            time.sleep(1)
            
            return summary
        except Exception as e:
            logger.warning(f"AI summary generation failed: {e}")
            return ""
    
    def _get_month_range(self, year: int, month: int) -> Tuple[str, str]:
        """Get first and last day of month"""
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = datetime(year, month + 1, 1) - timedelta(days=1)
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
    
    def _fetch_data(self, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data for a ticker"""
        cache_key = f"{ticker}_{start}_{end}"
        if cache_key in self._data_cache:
            return self._data_cache[cache_key]
        
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if not df.empty:
                self._data_cache[cache_key] = df
                return df
        except Exception as e:
            logger.warning(f"Failed to fetch {ticker}: {e}")
        return None
    
    def _safe_return(self, df: Optional[pd.DataFrame]) -> float:
        """Calculate return safely"""
        if df is None or len(df) < 2:
            return 0.0
        try:
            start = float(df['Close'].iloc[0])
            end = float(df['Close'].iloc[-1])
            if isinstance(start, pd.Series):
                start = start.iloc[0]
            if isinstance(end, pd.Series):
                end = end.iloc[0]
            return ((end / start) - 1) * 100
        except:
            return 0.0
    
    def _safe_value(self, df: Optional[pd.DataFrame], col: str = 'Close', pos: int = -1) -> float:
        """Get value safely"""
        if df is None or len(df) == 0:
            return 0.0
        try:
            val = df[col].iloc[pos]
            if isinstance(val, pd.Series):
                val = val.iloc[0]
            return float(val)
        except:
            return 0.0
    
    def _calculate_breadth(self, year: int, month: int) -> float:
        """Calculate market breadth (% stocks above EMA50)"""
        # Use local daily prices if available
        prices_path = os.path.join(self.data_dir, 'data', 'us_daily_prices.csv')
        if not os.path.exists(prices_path):
            return 0.0
        
        try:
            df = pd.read_csv(prices_path)
            df['Date'] = pd.to_datetime(df['Date'])
            
            # Filter to end of month
            _, end_date = self._get_month_range(year, month)
            end_dt = pd.to_datetime(end_date)
            
            # Get last 60 days for EMA50 calculation
            start_dt = end_dt - timedelta(days=90)
            mask = (df['Date'] >= start_dt) & (df['Date'] <= end_dt)
            df_filtered = df[mask]
            
            if df_filtered.empty:
                return 0.0
            
            # Calculate for each ticker
            above_50 = 0
            total = 0
            
            for ticker in df_filtered['Ticker'].unique():
                ticker_df = df_filtered[df_filtered['Ticker'] == ticker].sort_values('Date')
                if len(ticker_df) < 50:
                    continue
                
                close = ticker_df['Close'].values
                ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().iloc[-1]
                current = close[-1]
                
                total += 1
                if current > ema50:
                    above_50 += 1
            
            return (above_50 / total * 100) if total > 0 else 0.0
        except Exception as e:
            logger.warning(f"Breadth calculation failed: {e}")
            return 0.0
    
    def generate_month_data(self, year: int, month: int) -> MonthlyData:
        """Generate data for a single month"""
        start, end = self._get_month_range(year, month)
        extended_start = (datetime.strptime(start, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')
        
        logger.info(f"Generating data for {year}-{month:02d}...")
        
        # Fetch all data
        data = {}
        all_tickers = {**self.tickers, **{k: v for k, v in self.sector_etfs.items()}}
        
        for name, ticker in all_tickers.items():
            data[name] = self._fetch_data(ticker, extended_start, end)
        
        # Calculate sector performance
        sector_perf = {}
        for sector, _ in self.sector_etfs.items():
            sector_perf[sector] = self._safe_return(data.get(sector))
        
        best_sector = max(sector_perf.items(), key=lambda x: x[1])[0] if sector_perf else "N/A"
        worst_sector = min(sector_perf.items(), key=lambda x: x[1])[0] if sector_perf else "N/A"
        
        # Calculate RSP vs SPY spread
        rsp_ret = self._safe_return(data.get('RSP'))
        spy_ret = self._safe_return(data.get('SPY'))
        
        # VIX stats
        vix_df = data.get('VIX')
        vix_avg = float(vix_df['Close'].mean()) if vix_df is not None and len(vix_df) > 0 else 0
        vix_high = float(vix_df['High'].max()) if vix_df is not None and len(vix_df) > 0 else 0
        vix_low = float(vix_df['Low'].min()) if vix_df is not None and len(vix_df) > 0 else 0
        
        # Trading days
        spy_df = data.get('SPY')
        trading_days = len(spy_df) if spy_df is not None else 0
        
        return MonthlyData(
            year=year,
            month=month,
            start_date=start,
            end_date=end,
            trading_days=trading_days,
            
            # Market
            spy_return=spy_ret,
            qqq_return=self._safe_return(data.get('QQQ')),
            iwm_return=self._safe_return(data.get('IWM')),
            spy_high=self._safe_value(data.get('SPY'), 'High', -1),
            spy_low=self._safe_value(data.get('SPY'), 'Low', -1),
            
            # VIX
            vix_avg=vix_avg,
            vix_high=vix_high,
            vix_low=vix_low,
            vix_change=self._safe_return(data.get('VIX')),
            
            # Yields
            yield_10y_start=self._safe_value(data.get('10Y'), 'Close', 0),
            yield_10y_end=self._safe_value(data.get('10Y'), 'Close', -1),
            yield_10y_change=self._safe_return(data.get('10Y')),
            yield_2y_10y_spread=self._safe_value(data.get('10Y')) - self._safe_value(data.get('2Y')),
            
            # Currency
            dxy_change=self._safe_return(data.get('DXY')),
            
            # Commodities
            gold_change=self._safe_return(data.get('GOLD')),
            oil_change=self._safe_return(data.get('OIL')),
            copper_change=self._safe_return(data.get('COPPER')),
            
            # Global
            kospi_change=self._safe_return(data.get('KOSPI')),
            nikkei_change=self._safe_return(data.get('NIKKEI')),
            dax_change=self._safe_return(data.get('DAX')),
            ftse_change=self._safe_return(data.get('FTSE')),
            
            # Sectors
            sector_performance=sector_perf,
            best_sector=best_sector,
            worst_sector=worst_sector,
            
            # Breadth
            breadth_ratio=self._calculate_breadth(year, month),
            rsp_spy_spread=rsp_ret - spy_ret,
            
            # Crypto
            btc_change=self._safe_return(data.get('BTC')),
            eth_change=self._safe_return(data.get('ETH')),
        )
    
    def generate_report_markdown(self, data: MonthlyData) -> str:
        """Generate markdown report from data"""
        month_name = datetime(data.year, data.month, 1).strftime('%B')
        
        # Determine market condition
        if data.spy_return > 3:
            condition = "🟢 Strong Bull"
        elif data.spy_return > 0:
            condition = "🟡 Mild Bull"
        elif data.spy_return > -3:
            condition = "🟡 Mild Bear"
        else:
            condition = "🔴 Strong Bear"
        
        # VIX condition
        if data.vix_avg > 30:
            vix_cond = "🔴 High Fear"
        elif data.vix_avg > 20:
            vix_cond = "🟡 Elevated"
        else:
            vix_cond = "🟢 Calm"
        
        report = f"""# US Market Monthly Report: {data.year}-{data.month:02d}

**Period**: {data.start_date} ~ {data.end_date} ({data.trading_days} trading days)
**Condition**: {condition}

---

## 📈 Market Performance

| Index | Return | Note |
|-------|--------|------|
| S&P 500 (SPY) | {data.spy_return:+.2f}% | Large Cap |
| Nasdaq 100 (QQQ) | {data.qqq_return:+.2f}% | Tech Heavy |
| Russell 2000 (IWM) | {data.iwm_return:+.2f}% | Small Cap |

**Breadth**: {data.breadth_ratio:.1f}% stocks above EMA50
**RSP vs SPY**: {data.rsp_spy_spread:+.2f}%p (Equal vs Cap Weight)

---

## 📊 Volatility & Risk

| Metric | Value |
|--------|-------|
| VIX Avg | {data.vix_avg:.1f} ({vix_cond}) |
| VIX High | {data.vix_high:.1f} |
| VIX Low | {data.vix_low:.1f} |
| VIX Change | {data.vix_change:+.1f}% |

---

## 💰 Yields & Rates

| Metric | Value |
|--------|-------|
| 10Y Yield | {data.yield_10y_start:.2f}% → {data.yield_10y_end:.2f}% ({data.yield_10y_change:+.1f}%) |
| 2Y-10Y Spread | {data.yield_2y_10y_spread:.2f}% |

---

## 💵 Currency

| Metric | Change |
|--------|--------|
| DXY (Dollar) | {data.dxy_change:+.2f}% |

---

## 🛢 Commodities

| Asset | Change |
|-------|--------|
| Gold | {data.gold_change:+.2f}% |
| Oil (WTI) | {data.oil_change:+.2f}% |
| Copper | {data.copper_change:+.2f}% |

---

## 🌍 Global Markets

| Market | Change |
|--------|--------|
| KOSPI (Korea) | {data.kospi_change:+.2f}% |
| Nikkei (Japan) | {data.nikkei_change:+.2f}% |
| DAX (Germany) | {data.dax_change:+.2f}% |
| FTSE (UK) | {data.ftse_change:+.2f}% |

---

## 🏭 Sector Performance

| Sector | Return | Rank |
|--------|--------|------|
"""
        # Sort sectors by performance
        sorted_sectors = sorted(data.sector_performance.items(), key=lambda x: x[1], reverse=True)
        for i, (sector, ret) in enumerate(sorted_sectors, 1):
            emoji = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else ""))
            report += f"| {sector} | {ret:+.2f}% | {emoji} {i} |\n"
        
        report += f"""
**Best**: {data.best_sector}
**Worst**: {data.worst_sector}

---

## ₿ Crypto

| Asset | Change |
|-------|--------|
| Bitcoin | {data.btc_change:+.2f}% |
| Ethereum | {data.eth_change:+.2f}% |

---

## 📋 Summary

### Key Metrics
- **Market**: {'📈 Bullish' if data.spy_return > 0 else '📉 Bearish'} ({data.spy_return:+.2f}%)
- **Fear Level**: {'High' if data.vix_avg > 25 else 'Low'} (VIX {data.vix_avg:.1f})
- **Yields**: {'Rising' if data.yield_10y_change > 0 else 'Falling'} ({data.yield_10y_change:+.1f}%)
- **Dollar**: {'Strong' if data.dxy_change > 0 else 'Weak'} ({data.dxy_change:+.2f}%)
- **Crypto**: {'🚀 Rally' if data.btc_change > 10 else ('📉 Dump' if data.btc_change < -10 else '➡️ Flat')}

"""
        # Add AI Summary if available
        if data.ai_summary:
            report += f"""### 🤖 AI Analysis

{data.ai_summary}

---

"""
        
        report += f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"
        return report
    
    def generate_single_month(self, year: int, month: int, save: bool = True, with_ai: bool = False) -> str:
        """Generate report for a single month"""
        data = self.generate_month_data(year, month)
        
        # Generate AI summary if requested
        if with_ai:
            logger.info(f"Generating AI summary for {year}-{month:02d}...")
            data.ai_summary = self._generate_ai_summary(data)
        
        report = self.generate_report_markdown(data)
        
        if save:
            filepath = os.path.join(self.output_dir, f"{year}-{month:02d}.md")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"Saved: {filepath}")
        
        return report
    
    def generate_all_reports(self, start_year: int = 2020, end_year: Optional[int] = None, with_ai: bool = False):
        """Generate all monthly reports"""
        current = datetime.now()
        if end_year is None:
            end_year = current.year
            
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                # Skip future months
                if year == current.year and month > current.month:
                    break
                
                try:
                    self.generate_single_month(year, month, with_ai=with_ai)
                except Exception as e:
                    logger.error(f"Failed {year}-{month:02d}: {e}")
        
        logger.info(f"All reports saved to: {self.output_dir}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate Monthly Market Reports")
    parser.add_argument('--year', type=int, help='Specific year')
    parser.add_argument('--month', type=int, help='Specific month')
    parser.add_argument('--all', action='store_true', help='Generate all reports from 2020 to current')
    parser.add_argument('--ai', action='store_true', help='Include AI summary (requires GOOGLE_API_KEY)')
    parser.add_argument('--preview', action='store_true', help='Print to console')
    
    args = parser.parse_args()
    
    # Determine data directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    generator = MonthlyReportGenerator(data_dir=script_dir)
    
    if args.all:
        generator.generate_all_reports(with_ai=args.ai)
    elif args.year and args.month:
        report = generator.generate_single_month(args.year, args.month, save=not args.preview, with_ai=args.ai)
        if args.preview:
            print(report)
    else:
        # Default: generate latest month
        now = datetime.now()
        report = generator.generate_single_month(now.year, now.month, save=True, with_ai=args.ai)
        print(f"Generated report for {now.year}-{now.month:02d}")


if __name__ == "__main__":
    main()

