#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fake Breakout Filters
Filters to detect and reject false/fake breakouts (특히 코인에서 효과적).

Features:
1. Hold Rule: N봉 내 pivot 위 마감 유지 확인
2. High Confirmation: 돌파 캔들이 직전 N봉 고점도 갱신 확인
3. Wick Rejection: 긴 윗꼬리 거부
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class BreakoutQuality:
    """Result of breakout quality assessment"""
    is_valid: bool
    score_penalty: int  # 0-30 penalty to apply to signal score
    reasons: List[str]
    
    def apply_to_score(self, original_score: int) -> int:
        """Apply penalty to original score"""
        return max(0, original_score - self.score_penalty)


class FakeBreakoutFilter:
    """
    Filters for detecting fake/false breakouts.
    """
    
    def __init__(
        self,
        hold_bars: int = 3,          # Bars to confirm hold above pivot
        high_lookback: int = 5,       # Bars to check for new high confirmation
        max_wick_ratio: float = 0.5,  # Max wick/body ratio (higher = more wick = worse)
        min_close_above_pivot_pct: float = 0.5  # Min % close must be above pivot
    ):
        self.hold_bars = hold_bars
        self.high_lookback = high_lookback
        self.max_wick_ratio = max_wick_ratio
        self.min_close_above_pivot_pct = min_close_above_pivot_pct
    
    def check_hold_rule(
        self,
        pivot_high: float,
        candles_after_breakout: List
    ) -> Tuple[bool, str]:
        """
        Check if price holds above pivot for N bars after breakout.
        
        Args:
            pivot_high: The pivot/resistance level that was broken
            candles_after_breakout: List of candles after the breakout
        
        Returns:
            (passed, reason)
        """
        if len(candles_after_breakout) < self.hold_bars:
            return True, "Insufficient bars for hold check (passed by default)"
        
        for i in range(self.hold_bars):
            candle = candles_after_breakout[i]
            close = candle.close if hasattr(candle, 'close') else candle.get('close', 0)
            
            if close < pivot_high:
                return False, f"Failed hold rule: Bar {i+1} closed below pivot ({close:.2f} < {pivot_high:.2f})"
        
        return True, f"Held above pivot for {self.hold_bars} bars"
    
    def check_high_confirmation(
        self,
        breakout_candle,
        prior_candles: List
    ) -> Tuple[bool, str]:
        """
        Check if breakout candle also makes new N-bar high.
        
        A genuine breakout should break not just the pivot, but also
        the recent high (showing real momentum).
        """
        if len(prior_candles) < self.high_lookback:
            return True, "Insufficient prior bars (passed by default)"
        
        breakout_high = breakout_candle.high if hasattr(breakout_candle, 'high') else breakout_candle.get('high', 0)
        
        # Find highest high in lookback period
        lookback_high = max(
            c.high if hasattr(c, 'high') else c.get('high', 0)
            for c in prior_candles[-self.high_lookback:]
        )
        
        if breakout_high > lookback_high:
            return True, f"Made new {self.high_lookback}-bar high ({breakout_high:.2f} > {lookback_high:.2f})"
        else:
            return False, f"Did not make new high ({breakout_high:.2f} <= {lookback_high:.2f})"
    
    def check_wick_rejection(
        self,
        candle
    ) -> Tuple[bool, str]:
        """
        Check if breakout candle has excessive upper wick.
        
        Large upper wick indicates selling pressure at higher levels,
        suggesting the breakout may fail.
        """
        o = candle.open if hasattr(candle, 'open') else candle.get('open', 0)
        h = candle.high if hasattr(candle, 'high') else candle.get('high', 0)
        l = candle.low if hasattr(candle, 'low') else candle.get('low', 0)
        c = candle.close if hasattr(candle, 'close') else candle.get('close', 0)
        
        body = abs(c - o)
        upper_wick = h - max(o, c)
        
        if body <= 0:
            return True, "Doji candle (passed)"
        
        wick_ratio = upper_wick / body
        
        if wick_ratio > self.max_wick_ratio:
            return False, f"Excessive upper wick (ratio={wick_ratio:.2f} > {self.max_wick_ratio})"
        
        return True, f"Wick ratio OK ({wick_ratio:.2f})"
    
    def check_close_above_pivot(
        self,
        candle,
        pivot_high: float
    ) -> Tuple[bool, str]:
        """
        Check if close is sufficiently above pivot.
        
        A weak close just barely above pivot is suspicious.
        """
        c = candle.close if hasattr(candle, 'close') else candle.get('close', 0)
        
        if pivot_high <= 0:
            return True, "Invalid pivot (passed)"
        
        above_pct = (c - pivot_high) / pivot_high * 100
        
        if above_pct < self.min_close_above_pivot_pct:
            return False, f"Close barely above pivot ({above_pct:.2f}% < {self.min_close_above_pivot_pct}%)"
        
        return True, f"Close {above_pct:.2f}% above pivot"
    
    def evaluate_breakout(
        self,
        breakout_candle,
        pivot_high: float,
        prior_candles: List = None,
        candles_after: List = None
    ) -> BreakoutQuality:
        """
        Run all filters and return overall quality assessment.
        
        Returns:
            BreakoutQuality with pass/fail, penalty, and reasons
        """
        reasons = []
        total_penalty = 0
        is_valid = True
        
        # 1. Check wick rejection
        passed, msg = self.check_wick_rejection(breakout_candle)
        if not passed:
            reasons.append(msg)
            total_penalty += 10
        
        # 2. Check close above pivot
        passed, msg = self.check_close_above_pivot(breakout_candle, pivot_high)
        if not passed:
            reasons.append(msg)
            total_penalty += 5
        
        # 3. Check high confirmation (if prior candles available)
        if prior_candles:
            passed, msg = self.check_high_confirmation(breakout_candle, prior_candles)
            if not passed:
                reasons.append(msg)
                total_penalty += 10
        
        # 4. Check hold rule (if candles after available)
        if candles_after:
            passed, msg = self.check_hold_rule(pivot_high, candles_after)
            if not passed:
                reasons.append(msg)
                total_penalty += 15
                is_valid = False  # Hard fail on hold rule
        
        if not reasons:
            reasons = ["All breakout quality checks passed"]
        
        return BreakoutQuality(
            is_valid=is_valid,
            score_penalty=min(30, total_penalty),  # Cap penalty at 30
            reasons=reasons
        )


def apply_breakout_filter(
    signals: list,
    candle_getter,
    filter_config: FakeBreakoutFilter = None
) -> list:
    """
    Apply breakout filter to list of signals.
    
    Returns filtered list with updated scores.
    """
    if filter_config is None:
        filter_config = FakeBreakoutFilter()
    
    filtered = []
    
    for signal in signals:
        # Get breakout candle
        candle = candle_getter(signal.symbol, signal.event_ts)
        if not candle:
            filtered.append(signal)
            continue
        
        # Evaluate breakout quality
        quality = filter_config.evaluate_breakout(
            breakout_candle=candle,
            pivot_high=signal.pivot_high,
            prior_candles=None,  # Would need additional getter
            candles_after=None   # Would need additional getter
        )
        
        if quality.is_valid:
            # Apply penalty to score
            new_score = quality.apply_to_score(signal.score)
            signal.score = new_score
            filtered.append(signal)
        else:
            logger.debug(f"Filtered out {signal.symbol}: {quality.reasons}")
    
    return filtered


if __name__ == "__main__":
    from dataclasses import dataclass
    
    @dataclass 
    class MockCandle:
        open: float
        high: float
        low: float
        close: float
    
    print("\n🔍 FAKE BREAKOUT FILTER TEST")
    print("=" * 50)
    
    filter = FakeBreakoutFilter(hold_bars=3, max_wick_ratio=0.5)
    
    # Test 1: Good breakout
    good_candle = MockCandle(open=100, high=110, low=99, close=108)
    quality = filter.evaluate_breakout(good_candle, pivot_high=105)
    print(f"\n✅ Good breakout: valid={quality.is_valid}, penalty={quality.score_penalty}")
    print(f"   Reasons: {quality.reasons}")
    
    # Test 2: Wick rejection (big upper wick)
    wick_candle = MockCandle(open=100, high=115, low=99, close=102)
    quality = filter.evaluate_breakout(wick_candle, pivot_high=100)
    print(f"\n⚠️ Wick rejection: valid={quality.is_valid}, penalty={quality.score_penalty}")
    print(f"   Reasons: {quality.reasons}")
    
    # Test 3: Failed hold rule
    candles_after = [
        MockCandle(open=108, high=110, low=104, close=104),  # Below pivot
    ]
    quality = filter.evaluate_breakout(good_candle, pivot_high=105, candles_after=candles_after)
    print(f"\n❌ Failed hold: valid={quality.is_valid}, penalty={quality.score_penalty}")
    print(f"   Reasons: {quality.reasons}")
    
    print("\n✅ Fake Breakout Filter test complete!")
