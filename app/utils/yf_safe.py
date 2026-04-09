"""Shared yfinance helpers with hard timeout via ThreadPoolExecutor.

Flask 요청 스레드에서 yfinance 를 직접 호출하면 외부 API 지연(5~15s+)이
워커 스레드를 그대로 점유 → 동시요청 20+ 시 스레드풀 고갈.

이 모듈은 전역 executor (2 worker) + hard timeout 으로 감싸 요청 스레드가
항상 결정론적 시간 내에 반환되도록 보장한다. Timeout 시 빈 DataFrame 반환.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# 프로세스 전역 executor — us_market.py 의 로컬 executor 와 별개지만 의미상 동일
_yf_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='yfinance-safe')


def yf_download_safe(tickers, timeout: float = 10.0, **kwargs) -> pd.DataFrame:
    """yf.download with hard timeout. Returns empty DataFrame on timeout/error."""
    def _fetch():
        return yf.download(tickers, progress=False, threads=True, **kwargs)

    future = _yf_pool.submit(_fetch)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.warning(f"[yf_safe] download timeout >{timeout}s: {tickers}")
        future.cancel()
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"[yf_safe] download error: {type(e).__name__}: {e}")
        return pd.DataFrame()


def yf_ticker_history_safe(symbol: str, timeout: float = 10.0, **kwargs) -> pd.DataFrame:
    """yf.Ticker(symbol).history(**kwargs) with hard timeout."""
    def _fetch():
        return yf.Ticker(symbol).history(**kwargs)

    future = _yf_pool.submit(_fetch)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.warning(f"[yf_safe] ticker history timeout >{timeout}s: {symbol}")
        future.cancel()
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"[yf_safe] ticker history error {symbol}: {type(e).__name__}: {e}")
        return pd.DataFrame()


def yf_ticker_info_safe(symbol: str, timeout: float = 10.0) -> dict[str, Any]:
    """yf.Ticker(symbol).info with hard timeout. Returns empty dict on failure."""
    def _fetch():
        return yf.Ticker(symbol).info or {}

    future = _yf_pool.submit(_fetch)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.warning(f"[yf_safe] ticker info timeout >{timeout}s: {symbol}")
        future.cancel()
        return {}
    except Exception as e:
        logger.warning(f"[yf_safe] ticker info error {symbol}: {type(e).__name__}: {e}")
        return {}
