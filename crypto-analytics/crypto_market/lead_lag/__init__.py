#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis Package
"""
from .data_fetcher import (
    fetch_all_data,
    fetch_yfinance_data,
    get_data_summary,
    MARKET_SOURCES,
    FRED_SOURCES
)

from .cross_correlation import (
    LeadLagResult,
    LeadLagMatrix,
    analyze_lead_lag,
    build_lead_lag_matrix,
    compute_lagged_correlation,
    print_lead_lag_matrix
)

from .granger import (
    GrangerResult,
    granger_causality_test,
    bidirectional_granger_test,
    find_granger_causal_indicators,
    print_granger_results
)

from .llm_interpreter import (
    interpret_lead_lag_results,
    interpret_granger_results,
    generate_trading_signal_interpretation
)

__all__ = [
    # Data
    "fetch_all_data",
    "fetch_yfinance_data",
    "get_data_summary",
    "MARKET_SOURCES",
    "FRED_SOURCES",
    
    # Cross-Correlation
    "LeadLagResult",
    "LeadLagMatrix",
    "analyze_lead_lag",
    "build_lead_lag_matrix",
    "compute_lagged_correlation",
    "print_lead_lag_matrix",
    
    # Granger
    "GrangerResult",
    "granger_causality_test",
    "bidirectional_granger_test",
    "find_granger_causal_indicators",
    "print_granger_results",
    
    # LLM
    "interpret_lead_lag_results",
    "interpret_granger_results",
    "generate_trading_signal_interpretation",
]
