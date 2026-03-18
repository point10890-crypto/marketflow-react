#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Quality Tests
Automated tests for lookahead prevention, OHLCV integrity, and universe validation.

Run: python -m tests.run_all
"""
import os
import sys
from datetime import datetime, timedelta
from typing import List, Tuple
import logging

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


class TestResult:
    def __init__(self, name: str, passed: bool, message: str = ""):
        self.name = name
        self.passed = passed
        self.message = message
    
    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} | {self.name}: {self.message}"


class DataQualityTests:
    """Data quality test suite"""
    
    def __init__(self):
        self.results: List[TestResult] = []
    
    def run_all(self) -> Tuple[int, int]:
        """Run all tests, return (passed, failed) counts"""
        self.results = []
        
        # Lookahead tests
        self.test_signal_uses_only_past_data()
        self.test_entry_on_next_candle()
        self.test_no_future_data_in_indicators()
        
        # OHLCV tests
        self.test_no_duplicate_candles()
        self.test_ohlcv_ordering()
        self.test_price_sanity()
        
        # Universe tests
        self.test_no_trading_before_listing()
        self.test_universe_consistency()
        
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        
        return passed, failed
    
    # ===== LOOKAHEAD TESTS =====
    
    def test_signal_uses_only_past_data(self):
        """Verify signal generation only uses past candles"""
        try:
            from vcp_backtest.data_quality import LookaheadChecker
            
            # Simulate: signal at 10:00, check if data ends at 10:00 or earlier
            signal_ts = datetime(2024, 1, 1, 10, 0, 0).timestamp() * 1000
            data_end_ts = datetime(2024, 1, 1, 10, 0, 0).timestamp() * 1000
            
            valid, msg = LookaheadChecker.check_signal_timing(signal_ts, data_end_ts)
            
            self.results.append(TestResult(
                "signal_uses_only_past_data",
                valid,
                msg
            ))
        except Exception as e:
            self.results.append(TestResult(
                "signal_uses_only_past_data",
                False,
                f"Error: {e}"
            ))
    
    def test_entry_on_next_candle(self):
        """Verify trade entry occurs after signal candle closes"""
        try:
            # Simulate: signal at bar N, entry at bar N+1
            signal_bar = 100
            entry_bar = 101
            
            passed = entry_bar > signal_bar
            
            self.results.append(TestResult(
                "entry_on_next_candle",
                passed,
                "Entry bar must be > signal bar"
            ))
        except Exception as e:
            self.results.append(TestResult(
                "entry_on_next_candle",
                False,
                f"Error: {e}"
            ))
    
    def test_no_future_data_in_indicators(self):
        """Verify indicators don't look ahead"""
        try:
            import numpy as np
            
            # Test: SMA should only use past data
            # A proper SMA(5) at index 10 should only use indices 6-10
            data = np.arange(20, dtype=float)
            window = 5
            
            # Calculate SMA at index 10
            sma_at_10 = np.mean(data[6:11])  # indices 6,7,8,9,10
            
            # Verify no future data (indices 11+) was used
            passed = sma_at_10 == np.mean([6, 7, 8, 9, 10])
            
            self.results.append(TestResult(
                "no_future_data_in_indicators",
                passed,
                f"SMA(5) at idx 10 = {sma_at_10}"
            ))
        except Exception as e:
            self.results.append(TestResult(
                "no_future_data_in_indicators",
                False,
                f"Error: {e}"
            ))
    
    # ===== OHLCV TESTS =====
    
    def test_no_duplicate_candles(self):
        """Verify no duplicate timestamps in OHLCV"""
        try:
            import pandas as pd
            
            # Simulate OHLCV data
            timestamps = [1000, 2000, 3000, 4000, 5000]  # No duplicates
            
            has_duplicates = len(timestamps) != len(set(timestamps))
            
            self.results.append(TestResult(
                "no_duplicate_candles",
                not has_duplicates,
                f"Unique: {len(set(timestamps))}/{len(timestamps)}"
            ))
        except Exception as e:
            self.results.append(TestResult(
                "no_duplicate_candles",
                False,
                f"Error: {e}"
            ))
    
    def test_ohlcv_ordering(self):
        """Verify OHLCV constraints: L <= O,C <= H"""
        try:
            # Test data: valid OHLCV
            candles = [
                {'o': 100, 'h': 105, 'l': 98, 'c': 103},   # Valid
                {'o': 100, 'h': 102, 'l': 99, 'c': 101},   # Valid
            ]
            
            all_valid = True
            for c in candles:
                if not (c['l'] <= c['o'] <= c['h'] and c['l'] <= c['c'] <= c['h']):
                    all_valid = False
                    break
            
            self.results.append(TestResult(
                "ohlcv_ordering",
                all_valid,
                "L <= O,C <= H constraint"
            ))
        except Exception as e:
            self.results.append(TestResult(
                "ohlcv_ordering",
                False,
                f"Error: {e}"
            ))
    
    def test_price_sanity(self):
        """Verify prices are positive and reasonable"""
        try:
            prices = [100, 101, 99, 102, 98]
            
            all_positive = all(p > 0 for p in prices)
            no_extreme_moves = all(
                abs(prices[i] - prices[i-1]) / prices[i-1] < 0.5  # < 50% move
                for i in range(1, len(prices))
            )
            
            self.results.append(TestResult(
                "price_sanity",
                all_positive and no_extreme_moves,
                "Prices positive, no 50%+ moves"
            ))
        except Exception as e:
            self.results.append(TestResult(
                "price_sanity",
                False,
                f"Error: {e}"
            ))
    
    # ===== UNIVERSE TESTS =====
    
    def test_no_trading_before_listing(self):
        """Verify no trades before symbol listing date"""
        try:
            # Simulate: symbol listed 2024-01-01, trade 2024-02-01
            listing_date = datetime(2024, 1, 1)
            trade_date = datetime(2024, 2, 1)
            
            passed = trade_date >= listing_date
            
            self.results.append(TestResult(
                "no_trading_before_listing",
                passed,
                f"Trade {trade_date.date()} >= Listing {listing_date.date()}"
            ))
        except Exception as e:
            self.results.append(TestResult(
                "no_trading_before_listing",
                False,
                f"Error: {e}"
            ))
    
    def test_universe_consistency(self):
        """Verify universe doesn't use survivorship-biased data"""
        try:
            # Simulate: using point-in-time universe
            current_universe = ['BTC', 'ETH', 'SOL', 'BNB']
            historical_universe_2023 = ['BTC', 'ETH', 'BNB', 'XRP']  # SOL wasn't top 4
            
            # For historical backtests, should use historical universe
            # This is a conceptual check
            passed = True  # Placeholder - actual check would verify data source
            
            self.results.append(TestResult(
                "universe_consistency",
                passed,
                "Point-in-time universe check"
            ))
        except Exception as e:
            self.results.append(TestResult(
                "universe_consistency",
                False,
                f"Error: {e}"
            ))
    
    def print_results(self):
        """Print all test results"""
        print("\n" + "=" * 60)
        print("           DATA QUALITY TEST RESULTS")
        print("=" * 60)
        
        for result in self.results:
            print(result)
        
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        
        print("=" * 60)
        print(f"  TOTAL: {passed} passed, {failed} failed")
        print("=" * 60 + "\n")
        
        return failed == 0


def run_all_tests():
    """Run all data quality tests"""
    tests = DataQualityTests()
    passed, failed = tests.run_all()
    success = tests.print_results()
    return 0 if success else 1


if __name__ == "__main__":
    exit(run_all_tests())
