#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 ULTRATHINK: Crypto Monthly Report Generator

Generates comprehensive monthly crypto market reports:
- BTC/ETH performance and dominance
- Major altcoins (SOL, XRP, BNB, ADA, DOGE, etc.)
- DeFi indicators (AAVE, UNI, LINK)
- Stablecoins (USDT, USDC)
- Market metrics
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
from dataclasses import dataclass, field
import logging
import time

from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class CryptoMonthlyData:
    """크립토 월별 데이터"""
    year: int
    month: int
    start_date: str
    end_date: str
    
    # BTC
    btc_return: float
    btc_high: float
    btc_low: float
    btc_avg: float
    btc_dominance_change: float
    
    # ETH
    eth_return: float
    eth_btc_ratio_change: float
    
    # Major Alts
    alt_performance: Dict[str, float] = field(default_factory=dict)
    best_alt: str = ""
    worst_alt: str = ""
    
    # DeFi
    defi_performance: Dict[str, float] = field(default_factory=dict)
    
    # Market Metrics
    total_mcap_change: float = 0.0
    
    # Correlation with TradFi
    btc_spy_correlation: float = 0.0
    btc_gold_correlation: float = 0.0
    
    # AI Summary
    ai_summary: str = ""


class CryptoMonthlyReportGenerator:
    """크립토 월별 보고서 생성기"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_dir = os.path.join(data_dir, 'crypto_monthly_reports')
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Major cryptos
        self.cryptos = {
            # Top coins
            'BTC': 'BTC-USD',
            'ETH': 'ETH-USD',
            'SOL': 'SOL-USD',
            'XRP': 'XRP-USD',
            'BNB': 'BNB-USD',
            'ADA': 'ADA-USD',
            'DOGE': 'DOGE-USD',
            'AVAX': 'AVAX-USD',
            'DOT': 'DOT-USD',
            'MATIC': 'MATIC-USD',
            'LINK': 'LINK-USD',
            'ATOM': 'ATOM-USD',
            'LTC': 'LTC-USD',
            'UNI': 'UNI-USD',
            'AAVE': 'AAVE-USD',
        }
        
        # TradFi for correlation
        self.tradfi = {
            'SPY': 'SPY',
            'GOLD': 'GC=F',
            'DXY': 'DX-Y.NYB',
        }
        
        self._data_cache: Dict[str, pd.DataFrame] = {}
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
    
    def _get_month_range(self, year: int, month: int) -> Tuple[str, str]:
        """Get first and last day of month"""
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = datetime(year, month + 1, 1) - timedelta(days=1)
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
    
    def _fetch_data(self, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data"""
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
            start_val = df['Close'].iloc[0]
            end_val = df['Close'].iloc[-1]
            if hasattr(start_val, 'iloc'):
                start_val = start_val.iloc[0]
            if hasattr(end_val, 'iloc'):
                end_val = end_val.iloc[0]
            return ((float(end_val) / float(start_val)) - 1) * 100
        except:
            return 0.0
    
    def _safe_value(self, df: Optional[pd.DataFrame], col: str = 'Close', agg: str = 'last') -> float:
        """Get aggregated value safely"""
        if df is None or len(df) == 0:
            return 0.0
        try:
            series = df[col]
            if agg == 'last':
                val = series.iloc[-1]
            elif agg == 'first':
                val = series.iloc[0]
            elif agg == 'max':
                val = series.max()
            elif agg == 'min':
                val = series.min()
            elif agg == 'mean':
                val = series.mean()
            else:
                val = series.iloc[-1]
            
            if hasattr(val, 'iloc'):
                val = val.iloc[0]
            return float(val)
        except:
            return 0.0
    
    def _calculate_correlation(self, df1: Optional[pd.DataFrame], df2: Optional[pd.DataFrame]) -> float:
        """Calculate correlation between two price series"""
        if df1 is None or df2 is None or len(df1) < 10 or len(df2) < 10:
            return 0.0
        try:
            # Align by date
            close1 = df1['Close'].pct_change().dropna()
            close2 = df2['Close'].pct_change().dropna()
            
            # Get common dates
            common = close1.index.intersection(close2.index)
            if len(common) < 10:
                return 0.0
            
            corr = close1.loc[common].corr(close2.loc[common])
            return float(corr) if not pd.isna(corr) else 0.0
        except:
            return 0.0
    
    def _generate_ai_summary(self, data: CryptoMonthlyData) -> str:
        """Generate AI summary using Gemini"""
        if not self.google_api_key:
            return ""
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.google_api_key)
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            
            # Build alt performance string
            alt_str = ", ".join([f"{k}: {v:+.1f}%" for k, v in sorted(
                data.alt_performance.items(), key=lambda x: x[1], reverse=True
            )[:5]])
            
            prompt = f"""You are a crypto market analyst. Analyze the following crypto market data for {data.year}-{data.month:02d} and provide a brief summary (3-5 bullet points) of key events.
            Provide the analysis in BOTH English and Korean.

## Market Data:
- Bitcoin: {data.btc_return:+.2f}% (High: ${data.btc_high:,.0f}, Low: ${data.btc_low:,.0f})
- Ethereum: {data.eth_return:+.2f}%
- ETH/BTC Ratio Change: {data.eth_btc_ratio_change:+.2f}%
- Top Alts: {alt_str}
- Best Alt: {data.best_alt}
- Worst Alt: {data.worst_alt}
- BTC-SPY Correlation: {data.btc_spy_correlation:.2f}
- BTC-Gold Correlation: {data.btc_gold_correlation:.2f}

Based on these metrics and your knowledge of what happened in crypto during {data.year}-{data.month:02d}, provide:
1. Key crypto events (halving, ETF news, protocol upgrades, hacks)
2. Why the market moved the way it did
3. Alt season or BTC dominance trends

Format exactly as follows:
[ENGLISH]
* (English bullet points)

[KOREAN]
* (Korean bullet points)
"""
            
            response = model.generate_content(prompt)
            time.sleep(1)
            return response.text.strip()
        except Exception as e:
            logger.warning(f"AI summary failed: {e}")
            return ""
    
    def generate_month_data(self, year: int, month: int) -> CryptoMonthlyData:
        """Generate data for a single month"""
        start, end = self._get_month_range(year, month)
        extended_start = (datetime.strptime(start, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')
        
        logger.info(f"Generating crypto data for {year}-{month:02d}...")
        
        # Fetch crypto data
        crypto_data = {}
        for name, ticker in self.cryptos.items():
            crypto_data[name] = self._fetch_data(ticker, extended_start, end)
        
        # Fetch TradFi for correlation
        tradfi_data = {}
        for name, ticker in self.tradfi.items():
            tradfi_data[name] = self._fetch_data(ticker, extended_start, end)
        
        # Calculate alt performance
        alt_perf = {}
        for name in self.cryptos.keys():
            if name not in ['BTC', 'ETH']:
                alt_perf[name] = self._safe_return(crypto_data.get(name))
        
        best_alt = max(alt_perf.items(), key=lambda x: x[1])[0] if alt_perf else "N/A"
        worst_alt = min(alt_perf.items(), key=lambda x: x[1])[0] if alt_perf else "N/A"
        
        # DeFi performance
        defi_perf = {k: alt_perf.get(k, 0.0) for k in ['AAVE', 'UNI', 'LINK'] if k in alt_perf}
        
        # ETH/BTC ratio
        eth_df = crypto_data.get('ETH')
        btc_df = crypto_data.get('BTC')
        eth_btc_change = 0.0
        if eth_df is not None and btc_df is not None and len(eth_df) > 1 and len(btc_df) > 1:
            try:
                eth_start = self._safe_value(eth_df, 'Close', 'first')
                eth_end = self._safe_value(eth_df, 'Close', 'last')
                btc_start = self._safe_value(btc_df, 'Close', 'first')
                btc_end = self._safe_value(btc_df, 'Close', 'last')
                
                if btc_start > 0 and btc_end > 0:
                    ratio_start = eth_start / btc_start
                    ratio_end = eth_end / btc_end
                    if ratio_start > 0:
                        eth_btc_change = ((ratio_end / ratio_start) - 1) * 100
            except:
                pass
        
        return CryptoMonthlyData(
            year=year,
            month=month,
            start_date=start,
            end_date=end,
            
            # BTC
            btc_return=self._safe_return(crypto_data.get('BTC')),
            btc_high=self._safe_value(crypto_data.get('BTC'), 'High', 'max'),
            btc_low=self._safe_value(crypto_data.get('BTC'), 'Low', 'min'),
            btc_avg=self._safe_value(crypto_data.get('BTC'), 'Close', 'mean'),
            btc_dominance_change=0.0,  # Would need CoinGecko API
            
            # ETH
            eth_return=self._safe_return(crypto_data.get('ETH')),
            eth_btc_ratio_change=eth_btc_change,
            
            # Alts
            alt_performance=alt_perf,
            best_alt=best_alt,
            worst_alt=worst_alt,
            
            # DeFi
            defi_performance=defi_perf,
            
            # Correlations
            btc_spy_correlation=self._calculate_correlation(crypto_data.get('BTC'), tradfi_data.get('SPY')),
            btc_gold_correlation=self._calculate_correlation(crypto_data.get('BTC'), tradfi_data.get('GOLD')),
        )
    
    def generate_report_markdown(self, data: CryptoMonthlyData) -> str:
        """Generate markdown report"""
        # Market condition
        if data.btc_return > 20:
            condition = "🟢 Strong Bull"
        elif data.btc_return > 0:
            condition = "🟡 Mild Bull"
        elif data.btc_return > -20:
            condition = "🟡 Mild Bear"
        else:
            condition = "🔴 Strong Bear"
        
        report = f"""# Crypto Market Monthly Report: {data.year}-{data.month:02d}

**Period**: {data.start_date} ~ {data.end_date}
**Condition**: {condition}

---

## ₿ Bitcoin

| Metric | Value |
|--------|-------|
| Return | {data.btc_return:+.2f}% |
| High | ${data.btc_high:,.0f} |
| Low | ${data.btc_low:,.0f} |
| Average | ${data.btc_avg:,.0f} |

---

## Ξ Ethereum

| Metric | Value |
|--------|-------|
| Return | {data.eth_return:+.2f}% |
| ETH/BTC Ratio | {data.eth_btc_ratio_change:+.2f}% |

---

## 🪙 Altcoin Performance

| Coin | Return | Rank |
|------|--------|------|
"""
        # Sort alts by performance
        sorted_alts = sorted(data.alt_performance.items(), key=lambda x: x[1], reverse=True)
        for i, (coin, ret) in enumerate(sorted_alts, 1):
            emoji = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else ""))
            report += f"| {coin} | {ret:+.2f}% | {emoji} {i} |\n"
        
        report += f"""
**Best**: {data.best_alt}
**Worst**: {data.worst_alt}

---

## 🏦 DeFi Performance

| Protocol | Return |
|----------|--------|
"""
        for protocol, ret in data.defi_performance.items():
            report += f"| {protocol} | {ret:+.2f}% |\n"
        
        report += f"""
---

## 📊 Correlations

| Pair | Correlation |
|------|-------------|
| BTC-SPY | {data.btc_spy_correlation:.2f} |
| BTC-Gold | {data.btc_gold_correlation:.2f} |

---

## 📋 Summary

### Key Metrics
- **Bitcoin**: {'📈 Bullish' if data.btc_return > 0 else '📉 Bearish'} ({data.btc_return:+.2f}%)
- **Ethereum**: {'📈 Bullish' if data.eth_return > 0 else '📉 Bearish'} ({data.eth_return:+.2f}%)
- **Alt Season**: {'🚀 Yes' if data.eth_btc_ratio_change > 5 else '❌ No'} (ETH/BTC {data.eth_btc_ratio_change:+.2f}%)
- **TradFi Correlation**: {'High' if abs(data.btc_spy_correlation) > 0.5 else 'Low'} (SPY: {data.btc_spy_correlation:.2f})

"""
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
                if year == current.year and month > current.month:
                    break
                
                try:
                    self.generate_single_month(year, month, with_ai=with_ai)
                except Exception as e:
                    logger.error(f"Failed {year}-{month:02d}: {e}")
        
        logger.info(f"All reports saved to: {self.output_dir}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate Crypto Monthly Reports")
    parser.add_argument('--year', type=int, help='Specific year')
    parser.add_argument('--month', type=int, help='Specific month')
    parser.add_argument('--all', action='store_true', help='Generate all reports from 2020 to current')
    parser.add_argument('--ai', action='store_true', help='Include AI summary')
    parser.add_argument('--preview', action='store_true', help='Print to console')
    
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    generator = CryptoMonthlyReportGenerator(data_dir=script_dir)
    
    if args.all:
        generator.generate_all_reports(with_ai=args.ai)
    elif args.year and args.month:
        report = generator.generate_single_month(args.year, args.month, save=not args.preview, with_ai=args.ai)
        if args.preview:
            print(report)
    else:
        now = datetime.now()
        report = generator.generate_single_month(now.year, now.month, save=True, with_ai=args.ai)
        print(f"Generated report for {now.year}-{now.month:02d}")


if __name__ == "__main__":
    main()
