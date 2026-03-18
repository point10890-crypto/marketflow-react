#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis - Cross-Correlation Engine
Computes lagged correlations to identify lead-lag relationships.

ULTRATHINK Design:
- Tests lags from -max_lag to +max_lag
- Positive lag = var1 leads (moves first)
- Finds optimal lag with strongest absolute correlation
- Generates human-readable interpretations
"""
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class LeadLagResult:
    """Result of lead-lag analysis between two variables"""
    var1: str
    var2: str
    optimal_lag: int
    optimal_correlation: float
    all_lags: Dict[int, float]
    p_value: Optional[float] = None
    interpretation: str = ""
    
    def to_dict(self) -> dict:
        return {
            "var1": self.var1,
            "var2": self.var2,
            "optimal_lag": self.optimal_lag,
            "optimal_correlation": round(self.optimal_correlation, 4),
            "interpretation": self.interpretation,
            "p_value": round(self.p_value, 4) if self.p_value else None,
            "all_lags": {str(k): round(v, 4) for k, v in self.all_lags.items()}
        }


@dataclass
class LeadLagMatrix:
    """Matrix of lead-lag relationships for multiple variables vs target"""
    target: str
    results: List[LeadLagResult] = field(default_factory=list)
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert to DataFrame for easy viewing"""
        rows = []
        for r in self.results:
            rows.append({
                "Variable": r.var1,
                "Target": r.var2,
                "Optimal Lag": r.optimal_lag,
                "Correlation": round(r.optimal_correlation, 3),
                "Interpretation": r.interpretation
            })
        return pd.DataFrame(rows)
    
    def get_leading_indicators(self) -> List[LeadLagResult]:
        """Get variables that lead the target (positive lag)"""
        return [r for r in self.results if r.optimal_lag > 0]
    
    def get_lagging_indicators(self) -> List[LeadLagResult]:
        """Get variables that lag the target (negative lag)"""
        return [r for r in self.results if r.optimal_lag < 0]


def compute_lagged_correlation(
    series1: pd.Series,
    series2: pd.Series,
    max_lag: int = 12
) -> Dict[int, float]:
    """
    Compute correlation at different lags.
    
    Args:
        series1: First time series (potential leader)
        series2: Second time series (potential follower)
        max_lag: Maximum lag to test (in periods)
    
    Returns:
        Dict mapping lag -> correlation
        Positive lag means series1 leads series2
    """
    correlations = {}
    
    # Align series
    aligned = pd.DataFrame({'s1': series1, 's2': series2}).dropna()
    s1 = aligned['s1']
    s2 = aligned['s2']
    
    if len(aligned) < max_lag * 2:
        logger.warning(f"Insufficient data for lag analysis: {len(aligned)} points")
        return {}
    
    for lag in range(-max_lag, max_lag + 1):
        try:
            if lag > 0:
                # Shift series1 forward (series1 leads)
                shifted_s1 = s1.shift(lag)
                corr = shifted_s1.corr(s2)
            elif lag < 0:
                # Shift series2 forward (series2 leads)
                shifted_s2 = s2.shift(-lag)
                corr = s1.corr(shifted_s2)
            else:
                corr = s1.corr(s2)
            
            if not np.isnan(corr):
                correlations[lag] = corr
                
        except Exception as e:
            logger.debug(f"Error at lag {lag}: {e}")
    
    return correlations


def find_optimal_lag(correlations: Dict[int, float]) -> Tuple[int, float]:
    """Find the lag with strongest absolute correlation"""
    if not correlations:
        return 0, 0.0
    
    optimal_lag = max(correlations.keys(), key=lambda k: abs(correlations[k]))
    return optimal_lag, correlations[optimal_lag]


def compute_p_value(
    series1: pd.Series,
    series2: pd.Series,
    lag: int
) -> Optional[float]:
    """
    Compute p-value for correlation using scipy.
    Tests null hypothesis: correlation = 0
    """
    try:
        from scipy import stats
        
        aligned = pd.DataFrame({'s1': series1, 's2': series2}).dropna()
        
        if lag > 0:
            s1_shifted = aligned['s1'].shift(lag)
        elif lag < 0:
            s1_shifted = aligned['s1']
            aligned['s2'] = aligned['s2'].shift(-lag)
        else:
            s1_shifted = aligned['s1']
        
        valid = pd.DataFrame({'a': s1_shifted, 'b': aligned['s2']}).dropna()
        
        if len(valid) < 10:
            return None
        
        _, p_value = stats.pearsonr(valid['a'], valid['b'])
        return p_value
        
    except ImportError:
        return None
    except Exception as e:
        logger.debug(f"P-value calculation error: {e}")
        return None


def interpret_lead_lag(
    var1: str,
    var2: str,
    lag: int,
    corr: float,
    lang: str = "ko"
) -> str:
    """Generate human-readable interpretation"""
    
    abs_corr = abs(corr)
    strength = "강한" if abs_corr > 0.5 else ("중간" if abs_corr > 0.3 else "약한")
    direction = "양의" if corr > 0 else "음의"
    
    if lang == "ko":
        if lag > 0:
            return f"{var1}이(가) {var2}보다 {abs(lag)}기간 선행 ({strength} {direction} 상관관계, r={corr:.3f})"
        elif lag < 0:
            return f"{var2}이(가) {var1}보다 {abs(lag)}기간 선행 ({strength} {direction} 상관관계, r={corr:.3f})"
        else:
            return f"{var1}과(와) {var2}은(는) 동시 변동 ({strength} {direction} 상관관계, r={corr:.3f})"
    else:
        if lag > 0:
            return f"{var1} leads {var2} by {abs(lag)} periods ({strength} {direction} correlation, r={corr:.3f})"
        elif lag < 0:
            return f"{var2} leads {var1} by {abs(lag)} periods ({strength} {direction} correlation, r={corr:.3f})"
        else:
            return f"{var1} and {var2} move simultaneously ({strength} {direction} correlation, r={corr:.3f})"


def analyze_lead_lag(
    df: pd.DataFrame,
    var1: str,
    var2: str,
    max_lag: int = 12,
    lang: str = "ko"
) -> LeadLagResult:
    """
    Perform full lead-lag analysis between two variables.
    
    Args:
        df: DataFrame with both variables
        var1: First variable column name
        var2: Second variable column name
        max_lag: Maximum lag to test
        lang: Language for interpretation ('ko' or 'en')
    
    Returns:
        LeadLagResult with all analysis details
    """
    if var1 not in df.columns or var2 not in df.columns:
        raise ValueError(f"Variables not found in DataFrame: {var1}, {var2}")
    
    correlations = compute_lagged_correlation(df[var1], df[var2], max_lag)
    
    if not correlations:
        return LeadLagResult(
            var1=var1,
            var2=var2,
            optimal_lag=0,
            optimal_correlation=0.0,
            all_lags={},
            interpretation="분석 데이터 부족" if lang == "ko" else "Insufficient data"
        )
    
    optimal_lag, optimal_corr = find_optimal_lag(correlations)
    p_value = compute_p_value(df[var1], df[var2], optimal_lag)
    interpretation = interpret_lead_lag(var1, var2, optimal_lag, optimal_corr, lang)
    
    return LeadLagResult(
        var1=var1,
        var2=var2,
        optimal_lag=optimal_lag,
        optimal_correlation=optimal_corr,
        all_lags=correlations,
        p_value=p_value,
        interpretation=interpretation
    )


def build_lead_lag_matrix(
    df: pd.DataFrame,
    target: str,
    variables: Optional[List[str]] = None,
    max_lag: int = 12,
    lang: str = "ko"
) -> LeadLagMatrix:
    """
    Build matrix showing lead-lag relationships for all variables vs target.
    
    Args:
        df: DataFrame with all variables
        target: Target variable to analyze against
        variables: List of variables to test (defaults to all columns except target)
        max_lag: Maximum lag to test
        lang: Language for interpretation
    
    Returns:
        LeadLagMatrix with all results
    """
    if target not in df.columns:
        raise ValueError(f"Target {target} not in DataFrame")
    
    if variables is None:
        variables = [c for c in df.columns if c != target]
    
    results = []
    
    for var in variables:
        if var == target:
            continue
        
        try:
            result = analyze_lead_lag(df, var, target, max_lag, lang)
            results.append(result)
        except Exception as e:
            logger.warning(f"Failed to analyze {var} vs {target}: {e}")
    
    # Sort by absolute correlation strength
    results.sort(key=lambda r: abs(r.optimal_correlation), reverse=True)
    
    return LeadLagMatrix(target=target, results=results)


def print_lead_lag_matrix(matrix: LeadLagMatrix):
    """Print formatted lead-lag matrix"""
    print(f"\n{'='*70}")
    print(f"📊 LEAD-LAG ANALYSIS: Variables vs {matrix.target}")
    print(f"{'='*70}\n")
    
    print(f"{'Variable':<15} {'Lag':>6} {'Corr':>8} {'P-Value':>10} {'Interpretation'}")
    print("-" * 70)
    
    for r in matrix.results:
        # Emoji based on lead/lag
        if r.optimal_lag > 0:
            emoji = "⬆️"  # Leads
        elif r.optimal_lag < 0:
            emoji = "⬇️"  # Lags
        else:
            emoji = "↔️"  # Same time
        
        p_str = f"{r.p_value:.4f}" if r.p_value else "N/A"
        
        # Color based on correlation direction
        if r.optimal_correlation > 0.3:
            corr_emoji = "🟢"
        elif r.optimal_correlation < -0.3:
            corr_emoji = "🔴"
        else:
            corr_emoji = "🟡"
        
        print(f"{emoji} {r.var1:<12} {r.optimal_lag:>6} {corr_emoji} {r.optimal_correlation:>+.3f} {p_str:>10} {r.interpretation[:30]}...")


if __name__ == "__main__":
    # Test with sample data
    print("\n🔬 Cross-Correlation Engine Test\n")
    
    # Create sample data with known lead-lag relationship
    np.random.seed(42)
    n = 100
    
    # Create a leading indicator
    leader = pd.Series(np.random.randn(n).cumsum())
    
    # Create a follower with 3-period lag
    noise = np.random.randn(n) * 0.3
    follower = leader.shift(3).fillna(0) + noise
    
    df = pd.DataFrame({
        'leader': leader,
        'follower': follower
    })
    
    result = analyze_lead_lag(df, 'leader', 'follower', max_lag=6)
    
    print(f"✅ Detected Lag: {result.optimal_lag} (expected: 3)")
    print(f"✅ Correlation: {result.optimal_correlation:.3f}")
    print(f"✅ Interpretation: {result.interpretation}")
