#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis - Data Fetcher Module
Fetches macro indicators from FRED, yfinance, and processes for analysis.

ULTRATHINK Design:
- Primary: yfinance for market data (reliable, free)
- Secondary: FRED API via pandas_datareader for economic data
- Fallback: OpenBB if available
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class DataSource:
    """Data source configuration"""
    name: str
    ticker: str
    source: str  # 'yfinance', 'fred', 'calculated'
    description: str
    frequency: str  # 'daily', 'weekly', 'monthly'
    transform: str = 'price'  # 'price', 'return', 'change', 'yoy'


# ===== DATA SOURCE DEFINITIONS =====

MARKET_SOURCES = [
    DataSource("BTC", "BTC-USD", "yfinance", "Bitcoin Price", "daily"),
    DataSource("ETH", "ETH-USD", "yfinance", "Ethereum Price", "daily"),
    DataSource("SPY", "SPY", "yfinance", "S&P 500 ETF", "daily"),
    DataSource("QQQ", "QQQ", "yfinance", "NASDAQ 100 ETF", "daily"),
    DataSource("DXY", "DX-Y.NYB", "yfinance", "US Dollar Index", "daily"),
    DataSource("GOLD", "GC=F", "yfinance", "Gold Futures", "daily"),
    DataSource("TLT", "TLT", "yfinance", "20+ Year Treasury Bond ETF", "daily"),
    DataSource("VIX", "^VIX", "yfinance", "Volatility Index", "daily"),
    DataSource("TNX", "^TNX", "yfinance", "10-Year Treasury Yield", "daily"),
    DataSource("OIL", "CL=F", "yfinance", "Crude Oil Futures", "daily"),
]

FRED_SOURCES = [
    DataSource("FEDFUNDS", "FEDFUNDS", "fred", "Federal Funds Rate", "monthly"),
    DataSource("M2", "M2SL", "fred", "M2 Money Supply", "monthly", transform="yoy"),
    DataSource("UNRATE", "UNRATE", "fred", "Unemployment Rate", "monthly"),
    DataSource("CPIAUCSL", "CPIAUCSL", "fred", "Consumer Price Index", "monthly", transform="yoy"),
    DataSource("T10Y2Y", "T10Y2Y", "fred", "10Y-2Y Treasury Spread", "daily"),
    DataSource("WALCL", "WALCL", "fred", "Fed Balance Sheet", "weekly", transform="yoy"),
]


def fetch_yfinance_data(
    sources: List[DataSource],
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    Fetch market data from yfinance.
    Returns DataFrame with columns for each source.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return pd.DataFrame()
    
    tickers = [s.ticker for s in sources]
    names = [s.name for s in sources]
    
    logger.info(f"Fetching {len(tickers)} tickers from yfinance...")
    
    try:
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)
        
        if data.empty:
            return pd.DataFrame()
        
        # Extract Close prices
        if 'Close' in data.columns:
            if len(tickers) == 1:
                result = data['Close'].to_frame()
                result.columns = names
            else:
                result = data['Close']
                result.columns = names
        else:
            result = data
        
        logger.info(f"Fetched {len(result)} rows from yfinance")
        return result
        
    except Exception as e:
        logger.error(f"yfinance fetch error: {e}")
        return pd.DataFrame()


def fetch_fred_data(
    sources: List[DataSource],
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    Fetch economic data from FRED.
    Uses pandas_datareader or fallback to direct API.
    """
    try:
        from pandas_datareader import data as pdr
        import pandas_datareader.fred as fred_reader
    except ImportError:
        logger.warning("pandas_datareader not installed. Skipping FRED data.")
        return pd.DataFrame()
    
    results = {}
    
    for source in sources:
        try:
            logger.info(f"Fetching {source.name} from FRED...")
            series = pdr.DataReader(source.ticker, 'fred', start_date, end_date)
            
            if not series.empty:
                # Apply transformation
                if source.transform == 'yoy':
                    # Year-over-year change
                    series = series.pct_change(periods=12) * 100
                elif source.transform == 'change':
                    series = series.diff()
                
                results[source.name] = series.iloc[:, 0]
                
        except Exception as e:
            logger.warning(f"Failed to fetch {source.name}: {e}")
    
    if not results:
        return pd.DataFrame()
    
    return pd.DataFrame(results)


def resample_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily data to monthly (end of month)"""
    return df.resample('ME').last()


def calculate_returns(df: pd.DataFrame, periods: int = 1) -> pd.DataFrame:
    """Calculate percentage returns"""
    return df.pct_change(periods=periods) * 100


def calculate_yoy_change(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate year-over-year percentage change"""
    return df.pct_change(periods=12) * 100


def fetch_all_data(
    start_date: str = "2018-01-01",
    end_date: str = None,
    resample: str = "monthly",
    include_derivatives: bool = True  # NEW: Add MoM/YoY derivatives
) -> pd.DataFrame:
    """
    Fetch all data sources and combine into single DataFrame.
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (defaults to today)
        resample: 'daily', 'weekly', 'monthly'
        include_derivatives: If True, add MoM and YoY change columns
    
    Returns:
        Combined DataFrame with all indicators
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    logger.info(f"Fetching all data from {start_date} to {end_date}...")
    
    # Fetch market data
    market_df = fetch_yfinance_data(MARKET_SOURCES, start_date, end_date)
    
    # Fetch FRED data
    fred_df = fetch_fred_data(FRED_SOURCES, start_date, end_date)
    
    # Combine
    if market_df.empty and fred_df.empty:
        logger.error("No data fetched from any source")
        return pd.DataFrame()
    
    if market_df.empty:
        combined = fred_df
    elif fred_df.empty:
        combined = market_df
    else:
        # Merge on date index
        combined = market_df.join(fred_df, how='outer')
    
    # Resample if needed
    if resample == "monthly":
        combined = resample_to_monthly(combined)
    elif resample == "weekly":
        combined = combined.resample('W').last()
    
    # ===== DERIVATIVES: MoM and YoY transformations =====
    if include_derivatives:
        derivative_cols = {}
        
        # Price-based columns -> Returns (MoM %)
        price_cols = ['BTC', 'ETH', 'SPY', 'QQQ', 'DXY', 'GOLD', 'TLT', 'OIL', 'VIX', 'TNX']
        for col in price_cols:
            if col in combined.columns:
                # MoM return (전월대비 변동률)
                derivative_cols[f'{col}_MoM'] = combined[col].pct_change(periods=1) * 100
                # YoY return (전년대비 변동률) - 12 months
                derivative_cols[f'{col}_YoY'] = combined[col].pct_change(periods=12) * 100
                # 3-month momentum
                derivative_cols[f'{col}_3M'] = combined[col].pct_change(periods=3) * 100
        
        # FRED economic indicators -> Changes
        econ_cols = ['FEDFUNDS', 'UNRATE', 'T10Y2Y']
        for col in econ_cols:
            if col in combined.columns:
                # MoM change (bp or %)
                derivative_cols[f'{col}_MoM'] = combined[col].diff(periods=1)
                # YoY change
                derivative_cols[f'{col}_YoY'] = combined[col].diff(periods=12)
                # 3-month change
                derivative_cols[f'{col}_3M'] = combined[col].diff(periods=3)
        
        # M2, WALCL -> YoY growth rate (already computed in FRED, but add MoM)
        growth_cols = ['M2', 'CPIAUCSL', 'WALCL']
        for col in growth_cols:
            if col in combined.columns:
                # These are already YoY %, add MoM change of this rate
                derivative_cols[f'{col}_MoM'] = combined[col].diff(periods=1)
                # Rate acceleration (2nd derivative)
                derivative_cols[f'{col}_Accel'] = combined[col].diff(periods=1).diff(periods=1)
        
        # Add all derivatives to DataFrame
        for col_name, series in derivative_cols.items():
            combined[col_name] = series
        
        logger.info(f"Added {len(derivative_cols)} derivative columns (MoM, YoY, 3M, Accel)")
    
    # Forward fill and drop NAs
    combined = combined.ffill().dropna()
    
    logger.info(f"Combined dataset: {len(combined)} rows, {len(combined.columns)} columns")
    
    return combined


def get_data_summary(df: pd.DataFrame) -> Dict:
    """Generate summary statistics for the dataset"""
    summary = {
        "date_range": {
            "start": df.index.min().strftime("%Y-%m-%d"),
            "end": df.index.max().strftime("%Y-%m-%d"),
            "periods": len(df)
        },
        "columns": list(df.columns),
        "missing_pct": (df.isnull().sum() / len(df) * 100).to_dict(),
        "correlations_with_btc": {}
    }
    
    if 'BTC_ret' in df.columns:
        for col in df.columns:
            if col != 'BTC_ret' and col != 'BTC':
                corr = df['BTC_ret'].corr(df[col])
                if not np.isnan(corr):
                    summary["correlations_with_btc"][col] = round(corr, 3)
    
    return summary


if __name__ == "__main__":
    print("\n🔬 Lead-Lag Data Fetcher Test\n")
    
    df = fetch_all_data(
        start_date="2020-01-01",
        resample="monthly"
    )
    
    if not df.empty:
        print(f"✅ Fetched {len(df)} monthly observations")
        print(f"📊 Columns: {list(df.columns)}")
        print(f"\n📈 Date Range: {df.index.min()} to {df.index.max()}")
        
        summary = get_data_summary(df)
        print("\n🔗 Correlations with BTC Returns:")
        for col, corr in sorted(summary["correlations_with_btc"].items(), 
                                key=lambda x: abs(x[1]), reverse=True)[:10]:
            emoji = "🟢" if corr > 0.3 else ("🔴" if corr < -0.3 else "🟡")
            print(f"   {emoji} {col}: {corr:+.3f}")
    else:
        print("❌ No data fetched")
