#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Backtest - Signal Replay Engine
Generates historical signal timeline by replaying candle data through VCP detection.
"""
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Candle, SignalEvent
from signals import detect_setups, detect_breakouts, detect_retests, candles_to_df, market_regime_from_btc
from scoring import score_batch
from config import ScannerCfg, TimeframeCfg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_historical_candles_ccxt(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    exchange_name: str = "binance"
) -> List[Candle]:
    """
    Load historical candles using ccxt.
    Returns list of Candle objects.
    """
    try:
        import ccxt
        
        exchange_class = getattr(ccxt, exchange_name)
        exchange = exchange_class({'enableRateLimit': True})
        
        tf_map = {"4h": "4h", "1d": "1d", "1h": "1h"}
        ccxt_tf = tf_map.get(timeframe, "4h")
        
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
        
        all_candles = []
        current_ts = start_ts
        
        while current_ts < end_ts:
            ohlcv = exchange.fetch_ohlcv(symbol, ccxt_tf, since=current_ts, limit=1000)
            if not ohlcv:
                break
            
            for o in ohlcv:
                if o[0] >= end_ts:
                    break
                all_candles.append(Candle(
                    ts=o[0],
                    open=float(o[1]),
                    high=float(o[2]),
                    low=float(o[3]),
                    close=float(o[4]),
                    volume=float(o[5])
                ))
            
            current_ts = ohlcv[-1][0] + 1
        
        return all_candles
        
    except Exception as e:
        logger.error(f"Error loading candles for {symbol}: {e}")
        return []


def load_historical_candles_yfinance(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str
) -> List[Candle]:
    """
    Load historical candles using yfinance (for stocks or crypto like BTC-USD).
    """
    try:
        import yfinance as yf
        
        interval_map = {"4h": "1h", "1d": "1d", "1h": "1h"}  # yf doesn't have 4h
        interval = interval_map.get(timeframe, "1d")
        
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date, interval=interval)
        
        if df.empty:
            return []
        
        candles = []
        for idx, row in df.iterrows():
            candles.append(Candle(
                ts=int(idx.timestamp() * 1000),
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=float(row['Volume'])
            ))
        
        # If 4h requested but got 1h, resample
        if timeframe == "4h" and interval == "1h":
            candles = resample_candles(candles, 4)
        
        return candles
        
    except Exception as e:
        logger.error(f"Error loading yfinance data for {symbol}: {e}")
        return []


def resample_candles(candles: List[Candle], factor: int) -> List[Candle]:
    """Resample candles by combining 'factor' candles into one"""
    resampled = []
    for i in range(0, len(candles), factor):
        chunk = candles[i:i+factor]
        if not chunk:
            continue
        resampled.append(Candle(
            ts=chunk[0].ts,
            open=chunk[0].open,
            high=max(c.high for c in chunk),
            low=min(c.low for c in chunk),
            close=chunk[-1].close,
            volume=sum(c.volume for c in chunk)
        ))
    return resampled


class SignalReplayEngine:
    """
    Replays historical data to generate signal timeline.
    Simulates "as if" we ran the scanner at each bar.
    """
    
    def __init__(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        timeframe: str = "4h",
        exchange: str = "binance",
        use_yfinance: bool = False,
        lookback_bars: int = 300  # Bars needed before first signal
    ):
        self.symbols = symbols
        self.start_date = start_date
        self.end_date = end_date
        self.timeframe = timeframe
        self.exchange = exchange
        self.use_yfinance = use_yfinance
        self.lookback_bars = lookback_bars
        
        # Scanner config
        self.cfg = ScannerCfg()
        self.tf_cfg = self.cfg.tf_4h if timeframe == "4h" else self.cfg.tf_1d
        
        # Data cache
        self.candle_cache: Dict[str, List[Candle]] = {}
        self.btc_candles: List[Candle] = []
        
    def load_all_data(self):
        """Pre-load all historical data"""
        logger.info(f"Loading historical data for {len(self.symbols)} symbols...")
        
        # Calculate extended start date for lookback
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        if self.timeframe == "4h":
            extended_start = start_dt - timedelta(days=self.lookback_bars // 6)
        else:
            extended_start = start_dt - timedelta(days=self.lookback_bars)
        extended_start_str = extended_start.strftime("%Y-%m-%d")
        
        # Load BTC for regime detection
        btc_symbol = "BTC/USDT" if not self.use_yfinance else "BTC-USD"
        if self.use_yfinance:
            self.btc_candles = load_historical_candles_yfinance(
                btc_symbol, self.timeframe, extended_start_str, self.end_date
            )
        else:
            self.btc_candles = load_historical_candles_ccxt(
                btc_symbol, self.timeframe, extended_start_str, self.end_date, self.exchange
            )
        
        logger.info(f"Loaded {len(self.btc_candles)} BTC candles")
        
        # Load each symbol
        for i, sym in enumerate(self.symbols):
            if self.use_yfinance:
                candles = load_historical_candles_yfinance(
                    sym, self.timeframe, extended_start_str, self.end_date
                )
            else:
                candles = load_historical_candles_ccxt(
                    sym, self.timeframe, extended_start_str, self.end_date, self.exchange
                )
            
            if candles:
                self.candle_cache[sym] = candles
            
            if (i + 1) % 20 == 0:
                logger.info(f"Loaded {i + 1}/{len(self.symbols)} symbols...")
        
        logger.info(f"Data loading complete. {len(self.candle_cache)} symbols ready.")
    
    def generate_signal_timeline(self) -> List[SignalEvent]:
        """
        Generate chronological signal timeline.
        Simulates running the scanner at each bar.
        """
        if not self.candle_cache:
            self.load_all_data()
        
        all_signals: List[SignalEvent] = []
        
        # Get all unique timestamps from BTC (reference timeline)
        start_ts = int(datetime.strptime(self.start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(self.end_date, "%Y-%m-%d").timestamp() * 1000)
        
        btc_timestamps = [c.ts for c in self.btc_candles if start_ts <= c.ts < end_ts]
        
        logger.info(f"Replaying {len(btc_timestamps)} bars for signal detection...")
        
        # Replay each bar
        for bar_idx, current_ts in enumerate(btc_timestamps):
            if bar_idx % 100 == 0:
                logger.info(f"Processing bar {bar_idx}/{len(btc_timestamps)}...")
            
            # Build candles_map with data up to current_ts
            candles_map = {}
            symbols_with_qv = []
            
            for sym, full_candles in self.candle_cache.items():
                # Get candles up to current timestamp
                candles_up_to_now = [c for c in full_candles if c.ts <= current_ts]
                
                if len(candles_up_to_now) < self.lookback_bars:
                    continue
                
                # Take last N bars for detection
                candles_for_detection = candles_up_to_now[-self.tf_cfg.limit:]
                candles_map[(sym, self.timeframe)] = candles_for_detection
                
                # Estimate quote volume (simplified)
                avg_vol = sum(c.volume * c.close for c in candles_for_detection[-20:]) / 20
                symbols_with_qv.append((sym, avg_vol))
            
            if not candles_map:
                continue
            
            # Get BTC candles up to now
            btc_up_to_now = [c for c in self.btc_candles if c.ts <= current_ts][-260:]
            
            # Run detection pipeline
            try:
                setups = detect_setups(
                    self.exchange,
                    symbols_with_qv,
                    candles_map,
                    btc_up_to_now,
                    self.tf_cfg
                )
                
                if not setups:
                    continue
                
                # Detect breakouts
                breakouts = detect_breakouts(setups, candles_map, self.tf_cfg)
                
                # Score signals
                if breakouts:
                    scored = score_batch(breakouts, self.tf_cfg)
                    for sig in scored:
                        sig.event_ts = current_ts  # Override with replay timestamp
                        all_signals.append(sig)
                
                # TODO: Add retest detection with recent breakouts tracking
                
            except Exception as e:
                logger.warning(f"Error at bar {bar_idx}: {e}")
                continue
        
        logger.info(f"Signal replay complete. Generated {len(all_signals)} signals.")
        return all_signals
    
    def get_candle_at_time(self, symbol: str, timestamp: int) -> Optional[Candle]:
        """Get the candle for a symbol at a specific timestamp"""
        if symbol not in self.candle_cache:
            return None
        
        for c in self.candle_cache[symbol]:
            if c.ts == timestamp:
                return c
        return None
    
    def get_candles_after_time(self, symbol: str, timestamp: int, n_bars: int) -> List[Candle]:
        """Get N candles after a specific timestamp"""
        if symbol not in self.candle_cache:
            return []
        
        candles_after = [c for c in self.candle_cache[symbol] if c.ts > timestamp]
        return candles_after[:n_bars]


def generate_signals_for_backtest(
    symbols: List[str],
    start_date: str,
    end_date: str,
    timeframe: str = "4h",
    use_yfinance: bool = False
) -> Tuple[List[SignalEvent], SignalReplayEngine]:
    """
    Convenience function to generate signals for backtesting.
    Returns both signals and the engine (for later candle lookups).
    """
    engine = SignalReplayEngine(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe,
        use_yfinance=use_yfinance
    )
    
    signals = engine.generate_signal_timeline()
    return signals, engine
