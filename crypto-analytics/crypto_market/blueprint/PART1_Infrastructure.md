# PART1: 인프라 설정

## 1. 프로젝트 구조

```bash
mkdir -p crypto_market/{lead_lag,vcp_backtest,operations,analysis}
mkdir -p templates static

touch flask_app.py .env requirements.txt
touch crypto_market/__init__.py
touch crypto_market/lead_lag/__init__.py
touch crypto_market/vcp_backtest/__init__.py
touch crypto_market/operations/__init__.py
```

---

## 2. `requirements.txt`

```text
flask==3.0.0
pandas==2.1.0
numpy==1.26.0
yfinance==0.2.33
ccxt==4.1.0
statsmodels==0.14.0
python-dotenv==1.0.0
requests==2.31.0
google-generativeai==0.3.0
aiohttp==3.9.0
sqlalchemy==2.0.0
python-dateutil==2.8.2
```

---

## 3. `.env`

```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 4. `crypto_market/indicators.py`

```python
#!/usr/bin/env python3
import pandas as pd

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    
    return tr.rolling(period).mean()

def wick_ratio(o: float, h: float, l: float, c: float) -> float:
    body = abs(c - o)
    total = h - l
    if total <= 0:
        return 0.0
    return (total - body) / total
```

---

## ✅ 검증

```bash
pip install -r requirements.txt
python3 -c "import flask, pandas, yfinance, ccxt; print('OK!')"
```
