#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Quality Layer - OHLCV Cache & Reproducibility
Ensures reproducible backtest results with cached data snapshots.

Features:
1. Parquet-based OHLCV cache (fast, columnar, compressed)
2. Universe snapshots by date (for survivorship bias mitigation)
3. Lookahead prevention checks
"""
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


class OHLCVCache:
    """
    Parquet-based OHLCV data cache for reproducible backtesting.
    """
    
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        self.cache_dir = cache_dir
        self.ohlcv_dir = os.path.join(cache_dir, "ohlcv")
        self.universe_dir = os.path.join(cache_dir, "universe_snapshots")
        
        os.makedirs(self.ohlcv_dir, exist_ok=True)
        os.makedirs(self.universe_dir, exist_ok=True)
    
    def _get_cache_path(self, symbol: str, timeframe: str, source: str) -> str:
        """Generate cache file path for symbol/timeframe combo"""
        # Sanitize symbol (e.g., BTC/USDT -> BTC_USDT)
        safe_symbol = symbol.replace("/", "_").replace("-", "_")
        filename = f"{safe_symbol}_{timeframe}_{source}.parquet"
        return os.path.join(self.ohlcv_dir, filename)
    
    def has_cached(self, symbol: str, timeframe: str, source: str = "binance") -> bool:
        """Check if cached data exists"""
        path = self._get_cache_path(symbol, timeframe, source)
        return os.path.exists(path)
    
    def save_ohlcv(
        self, 
        df: pd.DataFrame, 
        symbol: str, 
        timeframe: str,
        source: str = "binance"
    ) -> str:
        """
        Save OHLCV DataFrame to Parquet cache.
        
        Expected columns: ts (or index), open, high, low, close, volume
        """
        path = self._get_cache_path(symbol, timeframe, source)
        
        # Ensure we have the required columns
        required = ['open', 'high', 'low', 'close', 'volume']
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Add metadata
        df = df.copy()
        df['_symbol'] = symbol
        df['_timeframe'] = timeframe
        df['_source'] = source
        df['_cached_at'] = datetime.now().isoformat()
        
        df.to_parquet(path, index=True, compression='snappy')
        logger.info(f"Cached {len(df)} rows for {symbol} ({timeframe}) → {path}")
        
        return path
    
    def load_ohlcv(
        self, 
        symbol: str, 
        timeframe: str,
        source: str = "binance",
        start_date: str = None,
        end_date: str = None
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLCV data from Parquet cache.
        
        Returns None if not cached.
        """
        path = self._get_cache_path(symbol, timeframe, source)
        
        if not os.path.exists(path):
            return None
        
        df = pd.read_parquet(path)
        
        # Filter by date range if specified
        if start_date:
            start_ts = pd.Timestamp(start_date)
            if df.index.dtype == 'int64':
                start_ts = int(start_ts.timestamp() * 1000)
            df = df[df.index >= start_ts]
        
        if end_date:
            end_ts = pd.Timestamp(end_date)
            if df.index.dtype == 'int64':
                end_ts = int(end_ts.timestamp() * 1000)
            df = df[df.index <= end_ts]
        
        logger.info(f"Loaded {len(df)} cached rows for {symbol}")
        return df
    
    def get_cache_info(self) -> List[Dict]:
        """Get info about all cached data"""
        info = []
        
        for filename in os.listdir(self.ohlcv_dir):
            if filename.endswith('.parquet'):
                path = os.path.join(self.ohlcv_dir, filename)
                stat = os.stat(path)
                
                # Parse filename
                parts = filename.replace('.parquet', '').split('_')
                
                info.append({
                    'filename': filename,
                    'size_mb': round(stat.st_size / 1024 / 1024, 2),
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return info


class UniverseSnapshot:
    """
    Universe snapshots for survivorship bias mitigation.
    Stores which symbols were in top-N at specific points in time.
    """
    
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "cache", "universe_snapshots")
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def _get_snapshot_path(self, date: str, source: str) -> str:
        """Generate snapshot file path"""
        return os.path.join(self.cache_dir, f"universe_{source}_{date}.json")
    
    def save_snapshot(
        self,
        date: str,
        symbols: List[str],
        source: str = "binance",
        metadata: Dict = None
    ):
        """Save universe snapshot for a specific date"""
        import json
        
        path = self._get_snapshot_path(date, source)
        
        data = {
            'date': date,
            'source': source,
            'symbols': symbols,
            'count': len(symbols),
            'metadata': metadata or {},
            'created_at': datetime.now().isoformat()
        }
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved universe snapshot: {len(symbols)} symbols for {date}")
    
    def load_snapshot(
        self,
        date: str,
        source: str = "binance"
    ) -> Optional[List[str]]:
        """Load universe snapshot for a specific date"""
        import json
        
        path = self._get_snapshot_path(date, source)
        
        if not os.path.exists(path):
            return None

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data.get('symbols', [])
    
    def get_nearest_snapshot(
        self,
        target_date: str,
        source: str = "binance",
        max_days_diff: int = 30
    ) -> Tuple[str, List[str]]:
        """
        Find the nearest available snapshot to target date.
        Useful when exact date snapshot doesn't exist.
        """
        import json
        from datetime import timedelta
        
        target = pd.Timestamp(target_date)
        
        # Search for closest snapshot
        for days_offset in range(max_days_diff + 1):
            for direction in [0, 1, -1]:
                check_date = target + timedelta(days=days_offset * direction)
                check_str = check_date.strftime('%Y-%m-%d')
                
                path = self._get_snapshot_path(check_str, source)
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    return check_str, data.get('symbols', [])
        
        return None, []


class LookaheadChecker:
    """
    Lookahead prevention checks for signal generation.
    Ensures signals don't use future data.
    """
    
    @staticmethod
    def check_signal_timing(
        signal_timestamp: int,
        data_used_end_timestamp: int,
        candle_duration_ms: int = 4 * 60 * 60 * 1000  # 4h default
    ) -> Tuple[bool, str]:
        """
        Check if signal generation uses only past data.
        
        Returns:
            (is_valid, message)
        """
        # Signal should be generated using data UP TO the signal candle (inclusive)
        # But NOT using data AFTER the signal candle
        
        if data_used_end_timestamp > signal_timestamp:
            return False, f"LOOKAHEAD: Data timestamp {data_used_end_timestamp} > Signal timestamp {signal_timestamp}"
        
        # Check if signal is generated on current candle close (valid)
        # or next candle (invalid lookahead)
        diff = signal_timestamp - data_used_end_timestamp
        
        if diff < 0:
            return False, "Signal uses future data (negative diff)"
        
        if diff > candle_duration_ms:
            return True, f"Signal uses data from {diff / candle_duration_ms:.1f} candles ago (conservative)"
        
        return True, "Signal timing is valid"
    
    @staticmethod
    def check_entry_timing(
        signal_timestamp: int,
        entry_timestamp: int,
        candle_duration_ms: int = 4 * 60 * 60 * 1000
    ) -> Tuple[bool, str]:
        """
        Check if entry occurs AFTER signal (on next candle open).
        
        Valid: Entry at next candle open
        Invalid: Entry on same candle as signal
        """
        if entry_timestamp <= signal_timestamp:
            return False, f"Entry at or before signal time (same candle entry not realistic)"
        
        # Entry should be at next candle open
        diff = entry_timestamp - signal_timestamp
        
        if diff < candle_duration_ms:
            # Could be valid if signal is at candle N close, entry at candle N+1 open
            # But if diff is very small, might be unrealistic
            return True, f"Entry {diff / 60000:.0f} minutes after signal (check if realistic)"
        
        return True, "Entry timing valid (next candle or later)"


# Convenience function for quick cache usage
def get_default_cache() -> OHLCVCache:
    """Get the default cache instance"""
    return OHLCVCache()


if __name__ == "__main__":
    # Test the cache
    cache = OHLCVCache()
    
    print("📁 OHLCV Cache Directory:", cache.cache_dir)
    print("📊 Cached files:", cache.get_cache_info())
    
    # Test universe snapshot
    snapshot = UniverseSnapshot()
    snapshot.save_snapshot(
        date="2024-01-01",
        symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        source="binance",
        metadata={"top_n": 200, "min_volume": 5_000_000}
    )
    
    print("✅ Universe snapshot saved")
    
    # Test lookahead checker
    checker = LookaheadChecker()
    valid, msg = checker.check_signal_timing(
        signal_timestamp=1704067200000,  # 2024-01-01 00:00:00
        data_used_end_timestamp=1704067200000
    )
    print(f"🔍 Lookahead check: {msg}")
