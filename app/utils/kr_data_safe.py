"""KR 주식 OHLCV 조회 통합 래퍼 — FDR 우선 + pykrx 폴백 + 하드 타임아웃.

엔진/라우트/스케줄러가 모두 이 모듈을 거치도록 해서 pykrx 단일 의존성을 제거한다.
스크래핑 차단/지연이 Flask 워커/스케줄러 스레드를 막지 않도록 ThreadPoolExecutor
기반 하드 타임아웃을 강제한다.

폴백 체인: FinanceDataReader (네이버 파이낸스) → pykrx (KRX 직접) → None
두 소스는 독립된 백엔드를 사용하므로 KRX 차단 시 FDR가, 네이버 차단 시 pykrx가 살아남는다.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='kr-data-safe')


def _run(fn, timeout: float):
    future = _pool.submit(fn)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        future.cancel()
        raise TimeoutError(f"kr_data_safe timeout >{timeout}s")


def _normalize_ohlcv(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """FDR/pykrx 응답을 표준 컬럼 [Open, High, Low, Close, Volume] 으로 정규화."""
    if df is None or df.empty:
        return pd.DataFrame()

    if source == 'pykrx':
        # pykrx: 시가/고가/저가/종가/거래량/거래대금/등락률
        rename = {'시가': 'Open', '고가': 'High', '저가': 'Low',
                  '종가': 'Close', '거래량': 'Volume', '거래대금': 'Amount'}
        df = df.rename(columns=rename)
    # FDR: 이미 Open/High/Low/Close/Volume 영문 컬럼
    keep = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount'] if c in df.columns]
    return df[keep].copy()


def get_ohlcv_safe(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    lookback_days: int = 200,
    timeout: float = 10.0,
) -> pd.DataFrame:
    """단일 종목 일봉 OHLCV — FDR 우선, pykrx 폴백.

    Args:
        ticker: 종목코드 (e.g., "005930")
        start: YYYY-MM-DD or YYYYMMDD (None 이면 lookback_days 기준 자동 계산)
        end:   YYYY-MM-DD or YYYYMMDD (None 이면 오늘)
        lookback_days: start 미지정 시 뒤로 몇 일까지
        timeout: 각 소스 호출 타임아웃(초)

    Returns:
        표준화된 DataFrame (Open, High, Low, Close, Volume, [Amount]).
        실패 시 빈 DataFrame.
    """
    today = datetime.now()
    if end is None:
        end = today.strftime('%Y-%m-%d')
    if start is None:
        start = (today - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    # FDR는 YYYY-MM-DD, pykrx는 YYYYMMDD
    start_dash = start if '-' in start else f"{start[:4]}-{start[4:6]}-{start[6:8]}"
    end_dash = end if '-' in end else f"{end[:4]}-{end[4:6]}-{end[6:8]}"
    start_compact = start.replace('-', '')
    end_compact = end.replace('-', '')

    # 1) FDR 우선 (네이버 파이낸스)
    try:
        import FinanceDataReader as fdr

        def _fdr_fetch():
            return fdr.DataReader(ticker, start_dash, end_dash)

        df = _run(_fdr_fetch, timeout)
        if df is not None and not df.empty:
            return _normalize_ohlcv(df, 'fdr')
        logger.debug(f"[kr_data_safe] FDR empty for {ticker}")
    except TimeoutError:
        logger.warning(f"[kr_data_safe] FDR timeout >{timeout}s for {ticker}")
    except Exception as e:
        logger.warning(f"[kr_data_safe] FDR error for {ticker}: {type(e).__name__}: {e}")

    # 2) pykrx 폴백 (KRX 직접)
    try:
        from pykrx import stock as pykrx_stock

        def _pykrx_fetch():
            return pykrx_stock.get_market_ohlcv(start_compact, end_compact, ticker)

        df = _run(_pykrx_fetch, timeout)
        if df is not None and not df.empty:
            return _normalize_ohlcv(df, 'pykrx')
        logger.debug(f"[kr_data_safe] pykrx empty for {ticker}")
    except TimeoutError:
        logger.warning(f"[kr_data_safe] pykrx timeout >{timeout}s for {ticker}")
    except Exception as e:
        logger.warning(f"[kr_data_safe] pykrx error for {ticker}: {type(e).__name__}: {e}")

    return pd.DataFrame()


def get_today_ohlcv_safe(ticker: str, timeout: float = 8.0) -> pd.DataFrame:
    """당일 1행 OHLCV — 장중/장후 실시간성 조회용.

    네이버 파이낸스(FDR)는 지연이 거의 없고, pykrx는 장 마감 후 확정 데이터.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    return get_ohlcv_safe(ticker, start=today, end=today, timeout=timeout)
