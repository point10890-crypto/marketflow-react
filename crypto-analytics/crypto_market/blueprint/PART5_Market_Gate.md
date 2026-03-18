# PART5: Market Gate (시장 건전성 평가)

## `crypto_market/market_gate.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Gate - "스캔할 만한 장인가?" 판단 시스템

🧠 ULTRATHINK Scoring (100점 만점):
- Trend (35점): BTC EMA 배열 + 기울기
- Volatility (18점): ATR% 기반 안정성
- Participation (18점): 거래량 Z-score
- Breadth (18점): 알트 EMA50 위 비율
- Leverage (11점): 펀딩/OI

Gate 결정:
- GREEN: score >= 72 (공격 모드)
- YELLOW: score >= 48 (주의 모드)
- RED: score < 48 (관망 모드)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional, Any
import numpy as np
import pandas as pd

from models import Candle
from indicators import ema, atr


@dataclass
class MarketGateResult:
    gate: str          # "GREEN" | "YELLOW" | "RED"
    score: int         # 0~100
    reasons: List[str]
    metrics: Dict[str, Any]


def candles_to_df(candles: List[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([{
        "ts": c.ts, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume
    } for c in candles]).sort_values("ts").reset_index(drop=True)
    return df


def zscore_last(series: pd.Series, window: int = 50) -> Optional[float]:
    """최근 값의 Z-score 계산"""
    if len(series) < window + 5:
        return None
    s = series.tail(window)
    mu = float(s.mean())
    sd = float(s.std(ddof=0))
    if sd <= 0:
        return 0.0
    return float((s.iloc[-1] - mu) / sd)


def slope_pct(series: pd.Series, lookback: int = 20) -> Optional[float]:
    """기울기 % 계산"""
    if len(series) < lookback + 2:
        return None
    a = float(series.iloc[-1])
    b = float(series.iloc[-1 - lookback])
    if b == 0:
        return None
    return (a - b) / b * 100.0


def compute_alt_breadth_above_ema50(
    candles_map: Dict[Tuple[str, str], List[Candle]],
    symbols: List[str],
    timeframe: str = "1d",
    lookback: int = 220
) -> Optional[float]:
    """알트 breadth: EMA50 위 종목 비율"""
    ok = 0
    total = 0

    for sym in symbols:
        c = candles_map.get((sym, timeframe))
        if not c or len(c) < lookback:
            continue
        df = candles_to_df(c)
        close = df["close"]
        e50 = ema(close, 50)
        if pd.isna(e50.iloc[-1]):
            continue
        total += 1
        if float(close.iloc[-1]) > float(e50.iloc[-1]):
            ok += 1

    if total < 5:
        return None
    return ok / total


def evaluate_market_gate(
    btc_candles_1d: List[Candle],
    btc_candles_4h: List[Candle],
    candles_map: Dict[Tuple[str, str], List[Candle]],
    alt_symbols: List[str],
    funding_rate: Optional[float] = None,
    open_interest_delta_z: Optional[float] = None,
) -> MarketGateResult:
    """
    🧠 ULTRATHINK: 5-Component Market Gate
    
    총점 100점:
    - Trend: 35점 (가장 중요)
    - Volatility: 18점
    - Participation: 18점  
    - Breadth: 18점
    - Leverage: 11점
    """
    reasons: List[str] = []
    metrics: Dict[str, Any] = {}

    if not btc_candles_1d or len(btc_candles_1d) < 260:
        return MarketGateResult(
            gate="RED",
            score=0,
            reasons=["BTC 1D 데이터 부족"],
            metrics={}
        )

    btc1 = candles_to_df(btc_candles_1d)
    close = btc1["close"]
    vol = btc1["volume"]

    e50 = ema(close, 50)
    e200 = ema(close, 200)

    price = float(close.iloc[-1])
    ema50 = float(e50.iloc[-1])
    ema200 = float(e200.iloc[-1])
    ema200_slope = slope_pct(e200, 20)
    vol_z = zscore_last(vol, 50)

    a = atr(btc1, 14)
    atrp = float(a.iloc[-1] / price * 100.0) if price > 0 else None

    metrics.update({
        "btc_price": price,
        "btc_ema50": ema50,
        "btc_ema200": ema200,
        "btc_ema200_slope_pct_20": ema200_slope,
        "btc_volume_z_50": vol_z,
        "btc_atrp_14_pct": atrp,
    })

    # ============================================================
    # 1) TREND (0~35점) - 가장 중요
    # ============================================================
    trend = 0.0
    
    # EMA 배열: close > EMA50 > EMA200
    if price > ema50 > ema200:
        trend += 22.0
    elif price > ema50:
        trend += 12.0
        reasons.append("BTC가 EMA50 위지만 EMA200 아래 (단기 반등)")
    else:
        reasons.append("BTC가 EMA50 아래 (하락 추세)")

    # EMA200 기울기
    if ema200_slope is not None:
        if ema200_slope > 1.0:
            trend += 13.0
        elif ema200_slope > 0:
            trend += 8.0
        elif ema200_slope > -1.0:
            trend += 3.0
            reasons.append("EMA200 기울기 약함 (모멘텀 부족)")
        else:
            reasons.append("EMA200 하락 중 (장기 약세)")

    # ============================================================
    # 2) VOLATILITY (0~18점) - 낮을수록 좋음
    # ============================================================
    vol_score = 0.0
    if atrp is not None:
        if atrp <= 2.0:
            vol_score = 18.0
        elif atrp <= 3.5:
            vol_score = 14.0
        elif atrp <= 5.0:
            vol_score = 8.0
            reasons.append("변동성 다소 높음 (휩쏘 주의)")
        else:
            vol_score = 2.0
            reasons.append("변동성 급증 (시장 불안정)")
    else:
        vol_score = 9.0

    # ============================================================
    # 3) PARTICIPATION (0~18점) - 거래량
    # ============================================================
    part = 0.0
    if vol_z is not None:
        if vol_z >= 1.0:
            part = 18.0
        elif vol_z >= 0.3:
            part = 12.0
        elif vol_z >= -0.3:
            part = 6.0
            reasons.append("거래량 평범 (유동성 유입 약함)")
        else:
            part = 2.0
            reasons.append("거래량 부족 (관심 저조)")
    else:
        part = 9.0

    # ============================================================
    # 4) BREADTH (0~18점) - 알트 건강도
    # ============================================================
    breadth_ratio = compute_alt_breadth_above_ema50(
        candles_map=candles_map,
        symbols=alt_symbols,
        timeframe="1d",
    )
    metrics["alt_breadth_above_ema50"] = breadth_ratio

    breadth = 0.0
    if breadth_ratio is not None:
        if breadth_ratio >= 0.65:
            breadth = 18.0
        elif breadth_ratio >= 0.50:
            breadth = 12.0
        elif breadth_ratio >= 0.35:
            breadth = 6.0
            reasons.append(f"알트 breadth 약함 ({breadth_ratio:.0%} > EMA50)")
        else:
            breadth = 2.0
            reasons.append(f"알트 breadth 붕괴 ({breadth_ratio:.0%} > EMA50)")
    else:
        breadth = 9.0

    # ============================================================
    # 5) LEVERAGE (0~11점) - 펀딩/OI
    # ============================================================
    lev = 0.0
    metrics["funding_rate"] = funding_rate
    metrics["open_interest_delta_z"] = open_interest_delta_z

    if funding_rate is not None:
        if -0.0003 < funding_rate < 0.0005:
            lev = 9.0  # 중립
        elif funding_rate > 0.001:
            lev = 2.0
            reasons.append(f"펀딩 과열 ({funding_rate*100:.3f}%) - 롱 과밀")
        elif funding_rate < -0.0005:
            lev = 4.0
            reasons.append(f"펀딩 공포 ({funding_rate*100:.3f}%) - 숏 과밀")
        else:
            lev = 6.0
    else:
        lev = 5.5

    if open_interest_delta_z is not None and open_interest_delta_z > 2.0:
        reasons.append("OI 급증 (레버 과다)")
        lev = max(0.0, lev - 2.0)

    lev = min(lev, 11.0)

    # ============================================================
    # 총점 계산 (100점 만점)
    # ============================================================
    total = trend + vol_score + part + breadth + lev
    score = int(round(max(0.0, min(100.0, total))))
    
    metrics["gate_score_components"] = {
        "trend": round(trend, 1),
        "volatility": round(vol_score, 1),
        "participation": round(part, 1),
        "breadth": round(breadth, 1),
        "leverage": round(lev, 1),
    }

    # Gate 결정
    if score >= 72:
        gate = "GREEN"
    elif score >= 48:
        gate = "YELLOW"
    else:
        gate = "RED"

    reasons = reasons[:5] if reasons else ["조건이 전반적으로 양호함"]

    return MarketGateResult(
        gate=gate,
        score=score,
        reasons=reasons,
        metrics=metrics,
    )


# ============================================================
# Flask API Sync Wrapper
# ============================================================
def run_market_gate_sync() -> MarketGateResult:
    """
    Sync wrapper for Flask API.
    Fetches BTC candles, Top Alts (Breadth), and Funding Rate.
    """
    import yfinance as yf
    import requests
    
    try:
        # 1. Fetch BTC 1D data
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="2y")
        
        if hist.empty or len(hist) < 260:
            return MarketGateResult(
                gate="YELLOW", score=50,
                reasons=["BTC 데이터 부족"], metrics={}
            )
        
        candles_1d = [Candle(
            ts=int(idx.timestamp() * 1000),
            open=float(row['Open']),
            high=float(row['High']),
            low=float(row['Low']),
            close=float(row['Close']),
            volume=float(row['Volume'])
        ) for idx, row in hist.iterrows()]
        
        # 2. Fetch Altcoin Breadth
        alt_tickers = ["ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", 
                       "DOGE-USD", "TRX-USD", "DOT-USD", "LINK-USD", "AVAX-USD"]
        candles_map = {}
        
        try:
            alt_data = yf.download(alt_tickers, period="1y", progress=False)
            for ticker in alt_tickers:
                try:
                    if isinstance(alt_data.columns, pd.MultiIndex):
                        if ticker in alt_data['Close'].columns:
                            close_series = alt_data['Close'][ticker]
                            if not close_series.isna().all():
                                alt_candles = [Candle(
                                    ts=int(ts.timestamp() * 1000),
                                    open=price, high=price, low=price, close=price, volume=0
                                ) for ts, price in close_series.items() if not pd.isna(price)]
                                candles_map[(ticker.replace("-USD", ""), "1d")] = alt_candles
                except Exception:
                    continue
        except Exception:
            pass
        
        # 3. Fetch Funding Rate
        funding_rate = None
        try:
            url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
            resp = requests.get(url, timeout=3)
            data = resp.json()
            if 'lastFundingRate' in data:
                funding_rate = float(data['lastFundingRate'])
        except Exception:
            funding_rate = 0.0001
        
        # 4. Fetch Fear & Greed Index
        fng_index = None
        try:
            fng_resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=3)
            fng_data = fng_resp.json()
            if 'data' in fng_data and len(fng_data['data']) > 0:
                fng_index = int(fng_data['data'][0]['value'])
        except Exception:
            fng_index = 50
        
        result = evaluate_market_gate(
            btc_candles_1d=candles_1d,
            btc_candles_4h=[],
            candles_map=candles_map,
            alt_symbols=[t.replace("-USD", "") for t in alt_tickers],
            funding_rate=funding_rate,
        )
        
        if fng_index is not None:
            result.metrics["fear_greed_index"] = fng_index
        
        result.gate_color = result.gate
        result.summary = f"BTC 시장 상태: {result.gate} (점수: {result.score}/100)"
        result.top_reasons = result.reasons
        
        return result
        
    except Exception as e:
        return MarketGateResult(
            gate="YELLOW", score=50,
            reasons=[f"분석 오류: {str(e)}"], metrics={}
        )
```

---

## 스코어링 컴포넌트

| 항목 | 배점 | 설명 |
|------|------|------|
| **Trend** | 35점 | close > EMA50 > EMA200, EMA200 기울기 |
| **Volatility** | 18점 | ATR% 낮을수록 좋음 |
| **Participation** | 18점 | 거래량 Z-Score |
| **Breadth** | 18점 | 알트 EMA50 위 비율 |
| **Leverage** | 11점 | 펀딩비 중립 여부 |

### Gate 해석
- **GREEN (72+)**: 공격적 진입 가능
- **YELLOW (48-71)**: 주의하며 진입
- **RED (0-47)**: 관망 또는 헤지
