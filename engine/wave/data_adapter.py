"""
데이터 어댑터 — daily_prices.csv / yfinance / pykrx 에서 OHLCV 로드
"""
import os
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DAILY_PRICES_PATH = os.path.join(_BASE_DIR, 'data', 'daily_prices.csv')


def load_ohlcv_from_csv(
    ticker: str,
    lookback: int = 200,
) -> Optional[Dict[str, np.ndarray]]:
    """
    daily_prices.csv에서 종목 데이터 로드.
    Returns: {dates, opens, highs, lows, closes, volumes} or None
    """
    if not os.path.exists(_DAILY_PRICES_PATH):
        logger.warning("daily_prices.csv not found: %s", _DAILY_PRICES_PATH)
        return None

    try:
        df = pd.read_csv(
            _DAILY_PRICES_PATH,
            dtype={'ticker': str},
            parse_dates=['date'],
            low_memory=False,
        )
    except Exception as e:
        logger.error("Failed to read daily_prices.csv: %s", e)
        return None

    # 종목 필터
    mask = df['ticker'] == ticker
    stock_df = df[mask].sort_values('date').tail(lookback)

    if len(stock_df) < 30:
        logger.info("Not enough data for %s: %d rows", ticker, len(stock_df))
        return None

    dates = stock_df['date'].dt.strftime('%Y-%m-%d').tolist()

    # 컬럼 매핑 (daily_prices.csv 구조에 맞춤)
    closes = stock_df['current_price'].values.astype(float) if 'current_price' in stock_df.columns else stock_df['close'].values.astype(float)
    opens = stock_df['open'].values.astype(float) if 'open' in stock_df.columns else closes.copy()
    highs = stock_df['high'].values.astype(float) if 'high' in stock_df.columns else closes.copy()
    lows = stock_df['low'].values.astype(float) if 'low' in stock_df.columns else closes.copy()
    volumes = stock_df['volume'].values.astype(float) if 'volume' in stock_df.columns else np.ones(len(closes))

    return {
        'dates': dates,
        'opens': opens,
        'highs': highs,
        'lows': lows,
        'closes': closes,
        'volumes': volumes,
    }


def load_ohlcv_yfinance(
    ticker: str,
    lookback: int = 200,
    interval: str = '1d',
) -> Optional[Dict[str, np.ndarray]]:
    """yfinance에서 데이터 로드 (US/Crypto 등)"""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed")
        return None

    try:
        period = '2y' if lookback > 252 else '1y'
        df = yf.download(ticker, period=period, interval=interval, progress=False)

        if df is None or len(df) < 30:
            return None

        # MultiIndex 처리
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.tail(lookback)
        dates = df.index.strftime('%Y-%m-%d').tolist()

        return {
            'dates': dates,
            'opens': df['Open'].values.astype(float),
            'highs': df['High'].values.astype(float),
            'lows': df['Low'].values.astype(float),
            'closes': df['Close'].values.astype(float),
            'volumes': df['Volume'].values.astype(float),
        }
    except Exception as e:
        logger.error("yfinance load failed for %s: %s", ticker, e)
        return None


def load_ohlcv(
    ticker: str,
    market: str = 'KR',
    lookback: int = 200,
) -> Optional[Dict[str, np.ndarray]]:
    """
    시장별 자동 데이터 로드.
    KR → daily_prices.csv 우선 → pykrx 폴백
    US/CRYPTO → yfinance
    """
    if market == 'KR':
        data = load_ohlcv_from_csv(ticker, lookback)
        if data is not None:
            return data
        # pykrx 폴백
        return _load_pykrx(ticker, lookback)
    else:
        return load_ohlcv_yfinance(ticker, lookback)


def _load_pykrx(ticker: str, lookback: int) -> Optional[Dict[str, np.ndarray]]:
    """pykrx 폴백"""
    try:
        from pykrx import stock as pykrx_stock
    except ImportError:
        return None

    try:
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=lookback * 2)).strftime('%Y%m%d')
        df = pykrx_stock.get_market_ohlcv(start, end, ticker)

        if df is None or len(df) < 30:
            return None

        df = df.tail(lookback)
        dates = df.index.strftime('%Y-%m-%d').tolist()

        return {
            'dates': dates,
            'opens': df['시가'].values.astype(float),
            'highs': df['고가'].values.astype(float),
            'lows': df['저가'].values.astype(float),
            'closes': df['종가'].values.astype(float),
            'volumes': df['거래량'].values.astype(float),
        }
    except Exception as e:
        logger.error("pykrx load failed for %s: %s", ticker, e)
        return None


def ohlcv_to_chart_data(data: Dict[str, np.ndarray]) -> List[Dict]:
    """OHLCV dict → 프론트엔드용 chart_data 리스트 변환"""
    dates = data['dates']
    result = []
    for i in range(len(dates)):
        result.append({
            'date': dates[i],
            'open': float(data['opens'][i]),
            'high': float(data['highs'][i]),
            'low': float(data['lows'][i]),
            'close': float(data['closes'][i]),
            'volume': float(data['volumes'][i]),
        })
    return result
