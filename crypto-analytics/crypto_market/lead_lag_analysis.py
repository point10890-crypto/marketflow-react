#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Correlation Analysis Module
시차(Lag) 상관관계 분석 - 선행/후행 지표 관계 파악

Examples:
- Fed 금리 → BTC 가격 (1-3개월 후행)
- M2 통화량 → 위험자산 (2-6개월 후행)
- DXY → BTC (역상관, 0-2주)
"""
import os
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging
import yfinance as yf
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class LaggedCorrelation:
    """Single lagged correlation result"""
    lag: int  # Positive = var1 leads, Negative = var2 leads
    correlation: float
    p_value: Optional[float] = None


@dataclass
class LeadLagResult:
    """Complete lead-lag analysis result"""
    var1_name: str
    var2_name: str
    correlations: Dict[int, float]
    optimal_lag: int
    optimal_correlation: float
    interpretation: str
    
    def to_dict(self) -> dict:
        return {
            "var1": self.var1_name,
            "var2": self.var2_name,
            "optimal_lag": self.optimal_lag,
            "optimal_correlation": round(self.optimal_correlation, 4),
            "interpretation": self.interpretation,
            "all_lags": {str(k): round(v, 4) for k, v in self.correlations.items()}
        }


def compute_lagged_correlation(
    series1: pd.Series,
    series2: pd.Series,
    max_lag: int = 12
) -> Dict[int, float]:
    """
    Compute correlation at different lags.
    
    Positive lag = series1 leads (series1이 선행)
    Negative lag = series2 leads (series2가 선행)
    
    Args:
        series1: First time series (e.g., interest rate)
        series2: Second time series (e.g., BTC price)
        max_lag: Maximum lag to test (in periods)
    
    Returns:
        Dict mapping lag -> correlation
    """
    correlations = {}
    
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            # Shift series1 forward (series1 leads)
            shifted = series1.shift(lag)
            corr = shifted.corr(series2)
        elif lag < 0:
            # Shift series2 forward (series2 leads)
            shifted = series2.shift(-lag)
            corr = series1.corr(shifted)
        else:
            corr = series1.corr(series2)
        
        if not np.isnan(corr):
            correlations[lag] = corr
    
    return correlations


def find_optimal_lag(correlations: Dict[int, float]) -> Tuple[int, float]:
    """Find the lag with strongest correlation (positive or negative)"""
    if not correlations:
        return 0, 0.0
    
    # Find max absolute correlation
    optimal_lag = max(correlations.keys(), key=lambda k: abs(correlations[k]))
    return optimal_lag, correlations[optimal_lag]


def interpret_lag(var1_name: str, var2_name: str, lag: int, corr: float) -> str:
    """Generate human-readable interpretation of the lag relationship"""
    direction = "양의" if corr > 0 else "음의"
    strength = "강한" if abs(corr) > 0.5 else ("중간" if abs(corr) > 0.3 else "약한")
    
    if lag > 0:
        return f"{var1_name}이(가) {var2_name}보다 {abs(lag)}기간 선행 ({strength} {direction} 상관관계, r={corr:.3f})"
    elif lag < 0:
        return f"{var2_name}이(가) {var1_name}보다 {abs(lag)}기간 선행 ({strength} {direction} 상관관계, r={corr:.3f})"
    else:
        return f"{var1_name}과 {var2_name}은 동시 움직임 ({strength} {direction} 상관관계, r={corr:.3f})"


def analyze_lead_lag(
    df: pd.DataFrame,
    var1: str,
    var2: str,
    max_lag: int = 12
) -> LeadLagResult:
    """
    Perform full lead-lag analysis between two variables.
    
    Args:
        df: DataFrame with both variables
        var1: First variable column name
        var2: Second variable column name
        max_lag: Maximum lag to test
    
    Returns:
        LeadLagResult with correlations and interpretation
    """
    correlations = compute_lagged_correlation(df[var1], df[var2], max_lag)
    optimal_lag, optimal_corr = find_optimal_lag(correlations)
    interpretation = interpret_lag(var1, var2, optimal_lag, optimal_corr)
    
    return LeadLagResult(
        var1_name=var1,
        var2_name=var2,
        correlations=correlations,
        optimal_lag=optimal_lag,
        optimal_correlation=optimal_corr,
        interpretation=interpretation
    )


def granger_causality_test(
    df: pd.DataFrame,
    cause_var: str,
    effect_var: str,
    max_lag: int = 6
) -> Dict:
    """
    Perform Granger Causality test.
    Tests if cause_var Granger-causes effect_var.
    
    Returns dict with test results for each lag.
    """
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
        
        # Prepare data (need both columns, effect first)
        test_data = df[[effect_var, cause_var]].dropna()
        
        if len(test_data) < max_lag * 3:
            return {"error": "Insufficient data for Granger test"}
        
        # Run test (verbose=False to suppress output)
        results = grangercausalitytests(test_data, maxlag=max_lag, verbose=False)
        
        # Extract p-values
        granger_results = {}
        for lag, result in results.items():
            # Get F-test p-value
            f_test = result[0]['ssr_ftest']
            granger_results[lag] = {
                "f_statistic": round(f_test[0], 4),
                "p_value": round(f_test[1], 4),
                "is_significant": f_test[1] < 0.05
            }
        
        # Find best lag (lowest p-value)
        best_lag = min(granger_results.keys(), key=lambda k: granger_results[k]['p_value'])
        
        return {
            "cause": cause_var,
            "effect": effect_var,
            "best_lag": best_lag,
            "best_p_value": granger_results[best_lag]['p_value'],
            "is_causal": granger_results[best_lag]['is_significant'],
            "all_lags": granger_results
        }
        
    except ImportError:
        return {"error": "statsmodels not installed. Run: pip install statsmodels"}
    except Exception as e:
        return {"error": str(e)}


# ===== Data Fetching Functions =====

def fetch_macro_data(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch common macro indicators for analysis.
    Uses yfinance for easy access.
    """
    tickers = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD",
        "SPY": "SPY",
        "QQQ": "QQQ",
        "DXY": "DX-Y.NYB",  # Dollar Index
        "GOLD": "GC=F",  # Gold Futures
        "TLT": "TLT",  # 20+ Year Treasury Bond ETF (inverse of rates)
        "VIX": "^VIX",
    }
    
    logger.info(f"Fetching macro data from {start_date} to {end_date}...")
    
    all_data = {}
    for name, ticker in tickers.items():
        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if not df.empty:
                all_data[name] = df['Close']
        except Exception as e:
            logger.warning(f"Failed to fetch {name}: {e}")
    
    if not all_data:
        return pd.DataFrame()
    
    result = pd.DataFrame(all_data)
    
    # Convert to monthly returns for cleaner analysis
    monthly = result.resample('ME').last()
    returns = monthly.pct_change().dropna()
    
    return returns


def run_full_lead_lag_analysis(
    start_date: str = "2020-01-01",
    end_date: str = None,
    max_lag: int = 6
) -> List[LeadLagResult]:
    """
    Run lead-lag analysis on common macro pairs.
    
    Returns list of LeadLagResult for each pair.
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    # Fetch data
    df = fetch_macro_data(start_date, end_date)
    
    if df.empty:
        logger.error("No data fetched")
        return []
    
    # Define pairs to analyze
    pairs = [
        ("DXY", "BTC"),      # Dollar vs Bitcoin
        ("TLT", "BTC"),      # Bonds (inverse rates) vs Bitcoin
        ("VIX", "BTC"),      # Fear vs Bitcoin
        ("GOLD", "BTC"),     # Gold vs Bitcoin
        ("SPY", "BTC"),      # S&P 500 vs Bitcoin
        ("ETH", "BTC"),      # ETH vs BTC
        ("DXY", "GOLD"),     # Dollar vs Gold
        ("VIX", "SPY"),      # Fear vs Stocks
    ]
    
    results = []
    
    for var1, var2 in pairs:
        if var1 in df.columns and var2 in df.columns:
            try:
                result = analyze_lead_lag(df, var1, var2, max_lag)
                results.append(result)
                logger.info(f"✓ {var1} vs {var2}: {result.interpretation}")
            except Exception as e:
                logger.warning(f"Failed to analyze {var1} vs {var2}: {e}")
    
    return results


def print_lead_lag_report(results: List[LeadLagResult]):
    """Print formatted lead-lag analysis report"""
    print("\n" + "=" * 70)
    print("📊 LEAD-LAG CORRELATION ANALYSIS REPORT")
    print("=" * 70)
    
    for r in results:
        # Emoji based on correlation direction
        if r.optimal_correlation > 0:
            emoji = "🟢" if r.optimal_correlation > 0.3 else "🟡"
        else:
            emoji = "🔴" if r.optimal_correlation < -0.3 else "🟡"
        
        print(f"\n{emoji} {r.var1_name} vs {r.var2_name}")
        print(f"   최적 Lag: {r.optimal_lag}개월")
        print(f"   상관계수: {r.optimal_correlation:.3f}")
        print(f"   해석: {r.interpretation}")
        
        # Show lag chart (simple ASCII)
        print("   Lag Chart: ", end="")
        for lag in range(-3, 4):
            if lag in r.correlations:
                val = r.correlations[lag]
                if val > 0.2:
                    print("+", end="")
                elif val < -0.2:
                    print("-", end="")
                else:
                    print(".", end="")
        print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Lead-Lag Correlation Analysis')
    parser.add_argument('--start', default='2020-01-01', help='Start date')
    parser.add_argument('--end', default=None, help='End date')
    parser.add_argument('--max-lag', type=int, default=6, help='Max lag in months')
    
    args = parser.parse_args()
    
    print("\n🔬 Running Lead-Lag Analysis...")
    print(f"Period: {args.start} to {args.end or 'now'}")
    print(f"Max Lag: {args.max_lag} months\n")
    
    results = run_full_lead_lag_analysis(args.start, args.end, args.max_lag)
    
    if results:
        print_lead_lag_report(results)
    else:
        print("❌ No results generated. Check data availability.")
