#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis - Granger Causality Module
Tests whether one time series has predictive power over another.

ULTRATHINK Design:
- Uses statsmodels.tsa.stattools.grangercausalitytests
- Tests if var1 Granger-causes var2
- Returns p-values for each lag
- Identifies statistically significant causal relationships
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class GrangerResult:
    """Result of Granger Causality test"""
    cause: str  # Potential causing variable
    effect: str  # Potential affected variable
    max_lag: int
    best_lag: int
    best_p_value: float
    is_significant: bool  # p < 0.05
    all_lags: Dict[int, Dict]  # lag -> {f_stat, p_value, is_sig}
    
    def to_dict(self) -> dict:
        return {
            "cause": self.cause,
            "effect": self.effect,
            "best_lag": int(self.best_lag),
            "best_p_value": round(float(self.best_p_value), 4),
            "is_significant": bool(self.is_significant),
            "interpretation": self.get_interpretation()
        }
    
    def get_interpretation(self, lang: str = "ko") -> str:
        if lang == "ko":
            if self.is_significant:
                return f"{self.cause}은(는) {self.effect}을(를) {self.best_lag}기간 선행하여 예측 가능 (p={self.best_p_value:.4f})"
            else:
                return f"{self.cause}은(는) {self.effect}에 대한 예측력이 통계적으로 유의하지 않음"
        else:
            if self.is_significant:
                return f"{self.cause} Granger-causes {self.effect} at lag {self.best_lag} (p={self.best_p_value:.4f})"
            else:
                return f"{self.cause} does not Granger-cause {self.effect} at significance level 0.05"


def granger_causality_test(
    df: pd.DataFrame,
    cause_var: str,
    effect_var: str,
    max_lag: int = 6,
    significance_level: float = 0.05
) -> GrangerResult:
    """
    Perform Granger Causality test.
    
    Tests H0: cause_var does NOT Granger-cause effect_var
    Tests H1: cause_var Granger-causes effect_var
    
    Args:
        df: DataFrame with both variables
        cause_var: Potential causing variable
        effect_var: Potential affected variable
        max_lag: Maximum lag to test
        significance_level: Threshold for significance (default 0.05)
    
    Returns:
        GrangerResult with test details
    """
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
    except ImportError:
        logger.error("statsmodels not installed. Run: pip install statsmodels")
        return GrangerResult(
            cause=cause_var,
            effect=effect_var,
            max_lag=max_lag,
            best_lag=0,
            best_p_value=1.0,
            is_significant=False,
            all_lags={}
        )
    
    if cause_var not in df.columns or effect_var not in df.columns:
        raise ValueError(f"Variables not found: {cause_var}, {effect_var}")
    
    # Prepare data - Granger test expects [effect, cause] order
    test_data = df[[effect_var, cause_var]].dropna()
    
    if len(test_data) < max_lag * 3:
        logger.warning(f"Insufficient data for Granger test: {len(test_data)} rows")
        return GrangerResult(
            cause=cause_var,
            effect=effect_var,
            max_lag=max_lag,
            best_lag=0,
            best_p_value=1.0,
            is_significant=False,
            all_lags={}
        )
    
    try:
        # Run Granger causality test (verbose=False to suppress output)
        results = grangercausalitytests(test_data, maxlag=max_lag, verbose=False)
        
        # Extract results for each lag
        all_lags = {}
        for lag, result in results.items():
            # Get F-test results (most commonly used)
            f_test = result[0]['ssr_ftest']
            f_stat = f_test[0]
            p_value = f_test[1]
            
            all_lags[lag] = {
                "f_statistic": round(f_stat, 4),
                "p_value": round(p_value, 4),
                "is_significant": p_value < significance_level
            }
        
        # Find best lag (lowest p-value)
        best_lag = min(all_lags.keys(), key=lambda k: all_lags[k]['p_value'])
        best_p = all_lags[best_lag]['p_value']
        is_sig = best_p < significance_level
        
        return GrangerResult(
            cause=cause_var,
            effect=effect_var,
            max_lag=max_lag,
            best_lag=best_lag,
            best_p_value=best_p,
            is_significant=is_sig,
            all_lags=all_lags
        )
        
    except Exception as e:
        logger.error(f"Granger test failed: {e}")
        return GrangerResult(
            cause=cause_var,
            effect=effect_var,
            max_lag=max_lag,
            best_lag=0,
            best_p_value=1.0,
            is_significant=False,
            all_lags={}
        )


def bidirectional_granger_test(
    df: pd.DataFrame,
    var1: str,
    var2: str,
    max_lag: int = 6
) -> Tuple[GrangerResult, GrangerResult]:
    """
    Test Granger causality in both directions.
    
    Returns:
        (var1 -> var2 result, var2 -> var1 result)
    """
    result_1_to_2 = granger_causality_test(df, var1, var2, max_lag)
    result_2_to_1 = granger_causality_test(df, var2, var1, max_lag)
    
    return result_1_to_2, result_2_to_1


def find_granger_causal_indicators(
    df: pd.DataFrame,
    target: str,
    variables: Optional[List[str]] = None,
    max_lag: int = 6
) -> List[GrangerResult]:
    """
    Find all variables that Granger-cause the target.
    
    Args:
        df: DataFrame with all variables
        target: Target variable to predict
        variables: List of potential causes (defaults to all columns)
        max_lag: Maximum lag to test
    
    Returns:
        List of GrangerResult for significant relationships only
    """
    if variables is None:
        variables = [c for c in df.columns if c != target]
    
    significant_results = []
    
    for var in variables:
        if var == target:
            continue
        
        try:
            result = granger_causality_test(df, var, target, max_lag)
            if result.is_significant:
                significant_results.append(result)
                logger.info(f"✓ {var} → {target}: p={result.best_p_value:.4f} at lag {result.best_lag}")
        except Exception as e:
            logger.warning(f"Failed to test {var}: {e}")
    
    # Sort by p-value (most significant first)
    significant_results.sort(key=lambda r: r.best_p_value)
    
    return significant_results


def print_granger_results(results: List[GrangerResult], target: str):
    """Print formatted Granger causality results"""
    print(f"\n{'='*70}")
    print(f"🔬 GRANGER CAUSALITY ANALYSIS: What predicts {target}?")
    print(f"{'='*70}\n")
    
    if not results:
        print("❌ No statistically significant Granger-causal relationships found.")
        return
    
    print(f"Found {len(results)} significant predictors:\n")
    
    for i, r in enumerate(results, 1):
        emoji = "⭐" if r.best_p_value < 0.01 else "✅"
        print(f"{i}. {emoji} {r.cause} → {target}")
        print(f"   Lag: {r.best_lag} periods")
        print(f"   P-value: {r.best_p_value:.4f}")
        print(f"   Interpretation: {r.get_interpretation()}")
        print()


if __name__ == "__main__":
    # Test with sample data
    print("\n🔬 Granger Causality Test\n")
    
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
        
        # Create sample data with known causal relationship
        np.random.seed(42)
        n = 200
        
        # X causes Y with some lag
        x = np.random.randn(n).cumsum()
        noise = np.random.randn(n) * 0.5
        y = np.zeros(n)
        for i in range(3, n):
            y[i] = 0.5 * x[i-3] + 0.3 * y[i-1] + noise[i]
        
        # Also create Z (no causal relationship)
        z = np.random.randn(n).cumsum()
        
        df = pd.DataFrame({'X': x, 'Y': y, 'Z': z})
        
        # Test X -> Y (should be significant)
        result_xy = granger_causality_test(df, 'X', 'Y', max_lag=6)
        print(f"X → Y: {result_xy.get_interpretation()}")
        print(f"   Significant: {result_xy.is_significant}, Best Lag: {result_xy.best_lag}")
        
        # Test Z -> Y (should NOT be significant)
        result_zy = granger_causality_test(df, 'Z', 'Y', max_lag=6)
        print(f"\nZ → Y: {result_zy.get_interpretation()}")
        print(f"   Significant: {result_zy.is_significant}")
        
    except ImportError:
        print("❌ statsmodels not installed. Run: pip install statsmodels")
