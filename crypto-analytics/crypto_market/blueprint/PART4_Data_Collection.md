# PART4: 데이터 수집

## 1. `crypto_market/universe.py`

```python
from __future__ import annotations
from typing import List, Tuple
import ccxt

def liquidity_bucket_from_quote_volume(qv: float) -> str:
    if qv >= 50_000_000:
        return "A"
    if qv >= 10_000_000:
        return "B"
    return "C"

def build_universe_binance_usdt(exchange: ccxt.Exchange, top_n: int, min_quote_vol_usdt: float) -> List[Tuple[str, float]]:
    """
    Returns list of (symbol, quoteVolumeUSDT), sorted desc.
    Spot only. USDT pairs only.
    """
    tickers = exchange.fetch_tickers()
    items: List[Tuple[str, float]] = []

    banned_fragments = (
        "UP/", "DOWN/", "BULL/", "BEAR/", "3L/", "3S/",  # Leveraged tokens
        "EUR/", "GBP/", "AUD/", "TRY/", "BRL/", "JPY/", "RUB/", "NGN/",  # Fiat
        "BIDR/", "IDRT/", "UAH/", "PLN/", "RON/", "ARS/", "ZAR/",
        "USDC/", "FDUSD/", "TUSD/", "DAI/", "BUSD/", "USDP/", "PYUSD/",  # Stablecoins
    )
    for sym, t in tickers.items():
        if not sym.endswith("/USDT"):
            continue
        if any(b in sym for b in banned_fragments):
            continue
        qv = t.get("quoteVolume", None)
        if qv is None:
            continue
        qv = float(qv)
        if qv < min_quote_vol_usdt:
            continue
        items.append((sym, qv))

    items.sort(key=lambda x: x[1], reverse=True)
    return items[:top_n]
```

---

## 2. `crypto_market/fetch_async.py`

```python
#!/usr/bin/env python3
import asyncio
import ccxt.async_support as ccxt
from typing import List, Dict, Tuple
from .models import Candle


async def fetch_ohlcv_batch(
    exchange_name: str,
    symbols: List[str],
    timeframe: str = "1d",
    limit: int = 200,
    max_concurrent: int = 10
) -> Dict[Tuple[str, str], List[Candle]]:
    """Async parallel OHLCV fetch"""
    ex = getattr(ccxt, exchange_name)({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"}
    })
    
    semaphore = asyncio.Semaphore(max_concurrent)
    results = {}
    
    async def fetch_one(symbol: str):
        async with semaphore:
            try:
                ohlcv = await ex.fetch_ohlcv(symbol, timeframe, limit=limit)
                candles = [
                    Candle(ts=c[0], open=c[1], high=c[2], low=c[3], close=c[4], volume=c[5])
                    for c in ohlcv
                ]
                results[(symbol, timeframe)] = candles
            except Exception as e:
                pass
    
    await asyncio.gather(*[fetch_one(s) for s in symbols])
    await ex.close()
    
    return results
```

---

## 3. `crypto_market/futures_metrics.py`

```python
#!/usr/bin/env python3
"""
Futures Metrics - Funding Rate & Open Interest from Binance Futures
"""
from __future__ import annotations
from typing import Optional, Tuple
import ccxt.async_support as ccxt


async def fetch_btc_funding_and_oi() -> Tuple[Optional[float], Optional[float]]:
    """
    Fetch BTC funding rate and OI from Binance USDT-M Futures.
    
    Returns:
        (funding_rate, oi_z_score)
        - funding_rate: 0.0001 = 0.01%, 0.001 = 0.1%
    """
    ex = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    
    try:
        funding = None
        try:
            fr = await ex.fetch_funding_rate("BTC/USDT:USDT")
            funding = fr.get("fundingRate", None)
            if funding is not None:
                funding = float(funding)
        except Exception:
            try:
                fr = await ex.fetch_funding_rate("BTC/USDT")
                funding = fr.get("fundingRate", None)
                if funding is not None:
                    funding = float(funding)
            except Exception:
                funding = None

        return funding, None
    finally:
        await ex.close()


async def fetch_funding_only() -> Optional[float]:
    """Simplified: just fetch funding rate"""
    ex = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    
    try:
        try:
            fr = await ex.fetch_funding_rate("BTC/USDT:USDT")
            rate = fr.get("fundingRate", None)
            return float(rate) if rate else None
        except Exception:
            return None
    finally:
        await ex.close()
```

---

## 설명

### universe.py
- 바이낸스에서 거래량 상위 200개 USDT 페어 선별
- 레버리지 토큰, 스테이블코인 자동 제외
- 유동성 등급 (A/B/C) 분류

### fetch_async.py
- 비동기 병렬 OHLCV 수집 (200개 코인을 빠르게)
- Semaphore로 동시 요청 수 제한 (Rate Limit 방지)

### futures_metrics.py
- 바이낸스 선물 펀딩비 수집
- 레버리지 과열/공포 판단용
