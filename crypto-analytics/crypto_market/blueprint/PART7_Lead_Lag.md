# PART7: Lead-Lag 분석 (거시지표 선행성 분석)

## 1. `crypto_market/lead_lag/data_fetcher.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis - Data Fetcher Module
Fetches macro indicators from FRED, yfinance for analysis.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DataSource:
    """Data source configuration"""
    name: str
    ticker: str
    source: str  # 'yfinance', 'fred'
    description: str
    frequency: str  # 'daily', 'weekly', 'monthly'
    transform: str = 'price'


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


def fetch_yfinance_data(sources: List[DataSource], start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch market data from yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()
    
    tickers = [s.ticker for s in sources]
    names = [s.name for s in sources]
    
    try:
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)
        
        if data.empty:
            return pd.DataFrame()
        
        if 'Close' in data.columns:
            if len(tickers) == 1:
                result = data['Close'].to_frame()
                result.columns = names
            else:
                result = data['Close']
                result.columns = names
        else:
            result = data
        
        return result
        
    except Exception as e:
        logger.error(f"yfinance fetch error: {e}")
        return pd.DataFrame()


def fetch_all_data(
    start_date: str = "2018-01-01",
    end_date: str = None,
    resample: str = "monthly",
    include_derivatives: bool = True
) -> pd.DataFrame:
    """
    Fetch all data sources and combine.
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    market_df = fetch_yfinance_data(MARKET_SOURCES, start_date, end_date)
    
    if market_df.empty:
        return pd.DataFrame()
    
    combined = market_df
    
    # Resample
    if resample == "monthly":
        combined = combined.resample('M').last()
    elif resample == "weekly":
        combined = combined.resample('W').last()
    
    # Add derivatives (MoM, YoY, 3M)
    if include_derivatives:
        derivative_cols = {}
        
        price_cols = ['BTC', 'ETH', 'SPY', 'QQQ', 'DXY', 'GOLD', 'TLT', 'OIL', 'VIX', 'TNX']
        for col in price_cols:
            if col in combined.columns:
                derivative_cols[f'{col}_MoM'] = combined[col].pct_change(1) * 100
                derivative_cols[f'{col}_YoY'] = combined[col].pct_change(12) * 100
                derivative_cols[f'{col}_3M'] = combined[col].pct_change(3) * 100
        
        for col_name, series in derivative_cols.items():
            combined[col_name] = series
    
    combined = combined.ffill().dropna()
    
    return combined
```

---

## 2. `crypto_market/lead_lag/granger.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis - Granger Causality Module
Tests whether one time series has predictive power over another.
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class GrangerResult:
    """Result of Granger Causality test"""
    cause: str
    effect: str
    max_lag: int
    best_lag: int
    best_p_value: float
    is_significant: bool
    all_lags: Dict[int, Dict]
    
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
                return f"{self.cause} does not Granger-cause {self.effect}"


def granger_causality_test(
    df: pd.DataFrame,
    cause_var: str,
    effect_var: str,
    max_lag: int = 6,
    significance_level: float = 0.05
) -> GrangerResult:
    """
    Perform Granger Causality test.
    
    H0: cause_var does NOT Granger-cause effect_var
    H1: cause_var Granger-causes effect_var
    """
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
    except ImportError:
        return GrangerResult(
            cause=cause_var, effect=effect_var, max_lag=max_lag,
            best_lag=0, best_p_value=1.0, is_significant=False, all_lags={}
        )
    
    if cause_var not in df.columns or effect_var not in df.columns:
        raise ValueError(f"Variables not found: {cause_var}, {effect_var}")
    
    test_data = df[[effect_var, cause_var]].dropna()
    
    if len(test_data) < max_lag * 3:
        return GrangerResult(
            cause=cause_var, effect=effect_var, max_lag=max_lag,
            best_lag=0, best_p_value=1.0, is_significant=False, all_lags={}
        )
    
    try:
        results = grangercausalitytests(test_data, maxlag=max_lag, verbose=False)
        
        all_lags = {}
        for lag, result in results.items():
            f_test = result[0]['ssr_ftest']
            f_stat = f_test[0]
            p_value = f_test[1]
            
            all_lags[lag] = {
                "f_statistic": round(f_stat, 4),
                "p_value": round(p_value, 4),
                "is_significant": p_value < significance_level
            }
        
        best_lag = min(all_lags.keys(), key=lambda k: all_lags[k]['p_value'])
        best_p = all_lags[best_lag]['p_value']
        is_sig = best_p < significance_level
        
        return GrangerResult(
            cause=cause_var, effect=effect_var, max_lag=max_lag,
            best_lag=best_lag, best_p_value=best_p, is_significant=is_sig, all_lags=all_lags
        )
        
    except Exception as e:
        logger.error(f"Granger test failed: {e}")
        return GrangerResult(
            cause=cause_var, effect=effect_var, max_lag=max_lag,
            best_lag=0, best_p_value=1.0, is_significant=False, all_lags={}
        )


def find_granger_causal_indicators(
    df: pd.DataFrame,
    target: str,
    variables: Optional[List[str]] = None,
    max_lag: int = 6
) -> List[GrangerResult]:
    """
    Find all variables that Granger-cause the target.
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
        except Exception as e:
            logger.warning(f"Failed to test {var}: {e}")
    
    significant_results.sort(key=lambda r: r.best_p_value)
    
    return significant_results
```

---

## 3. `crypto_market/lead_lag/__init__.py`

```python
from .granger import (
    GrangerResult,
    granger_causality_test,
    bidirectional_granger_test,
    find_granger_causal_indicators,
)
from .data_fetcher import (
    DataSource,
    MARKET_SOURCES,
    fetch_yfinance_data,
    fetch_all_data,
)
```

---

## 사용법

```python
from crypto_market.lead_lag import fetch_all_data, find_granger_causal_indicators

# 1. 데이터 수집
df = fetch_all_data(start_date="2020-01-01", resample="monthly")

# 2. BTC를 선행하는 지표 찾기
results = find_granger_causal_indicators(df, target="BTC_MoM", max_lag=6)

for r in results:
    print(f"{r.cause} → BTC: lag {r.best_lag}, p={r.best_p_value:.4f}")
```

---

## Granger Causality 해석

| p-value | 해석 |
|---------|------|
| p < 0.01 | ⭐ 강한 선행성 (매우 유의) |
| p < 0.05 | ✅ 유의한 선행성 |
| p < 0.10 | ⚠️ 약한 선행성 (참고용) |
| p >= 0.10 | ❌ 선행성 없음 |
