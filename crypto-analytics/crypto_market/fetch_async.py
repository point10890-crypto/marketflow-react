from __future__ import annotations
import asyncio
from typing import Dict, Tuple, List
import ccxt.async_support as ccxt
from models import Candle

def ohlcv_to_candles(ohlcv) -> List[Candle]:
    return [
        Candle(
            ts=int(x[0]),
            open=float(x[1]),
            high=float(x[2]),
            low=float(x[3]),
            close=float(x[4]),
            volume=float(x[5]),
        ) for x in ohlcv
    ]

async def fetch_ohlcv_safe(ex, symbol: str, timeframe: str, limit: int, sem: asyncio.Semaphore):
    async with sem:
        try:
            ohlcv = await ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            return symbol, timeframe, ohlcv_to_candles(ohlcv)
        except Exception:
            return symbol, timeframe, None

async def fetch_all_candles(
    symbols: List[str],
    timeframes: List[str],
    limit: int,
    max_concurrency: int = 10,
) -> Dict[Tuple[str, str], List[Candle]]:
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    sem = asyncio.Semaphore(max_concurrency)
    tasks = [fetch_ohlcv_safe(ex, sym, tf, limit, sem) for sym in symbols for tf in timeframes]

    out: Dict[Tuple[str, str], List[Candle]] = {}
    try:
        for coro in asyncio.as_completed(tasks):
            sym, tf, candles = await coro
            if candles:
                out[(sym, tf)] = candles
    finally:
        await ex.close()

    return out
