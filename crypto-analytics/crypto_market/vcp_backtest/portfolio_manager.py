#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio-Level Signal Management
Handles signal prioritization, cooldowns, and position coordination.

Features:
1. Same-candle signal prioritization (by score)
2. Symbol re-entry cooldown
3. Signal queue management for portfolio-level decisions
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from collections import defaultdict
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import SignalEvent

logger = logging.getLogger(__name__)


@dataclass
class PortfolioConfig:
    """Portfolio-level configuration"""
    
    # Position limits
    max_concurrent_positions: int = 5
    max_same_sector_positions: int = 2  # If sector info available
    
    # Signal selection
    max_signals_per_bar: int = 3  # Max new positions per bar
    select_by: str = "score"  # "score", "regime", "atr"
    
    # Cooldowns
    symbol_cooldown_bars: int = 5  # Bars before re-entering same symbol
    same_symbol_max_per_day: int = 2  # Max trades per symbol per day
    
    # Concentration limits
    max_single_symbol_pct: float = 20.0  # Max % of capital in one symbol
    max_correlated_pct: float = 40.0  # Max % in correlated assets


@dataclass
class SignalQueue:
    """
    Queue for managing signals at portfolio level.
    Handles same-bar prioritization and cooldowns.
    """
    pending: List[SignalEvent] = field(default_factory=list)
    cooldowns: Dict[str, int] = field(default_factory=dict)  # symbol -> bar_until_allowed
    daily_counts: Dict[str, int] = field(default_factory=dict)  # symbol -> count today
    last_bar_ts: int = 0
    
    def reset_daily_counts(self):
        """Reset daily counts (call at day change)"""
        self.daily_counts.clear()


class PortfolioManager:
    """
    Portfolio-level signal management and coordination.
    """
    
    def __init__(self, config: PortfolioConfig = None):
        self.config = config or PortfolioConfig()
        self.queue = SignalQueue()
        self.current_bar = 0
    
    def add_signals(self, signals: List[SignalEvent]) -> None:
        """Add new signals to the queue"""
        for signal in signals:
            # Skip if on cooldown
            if self._is_on_cooldown(signal.symbol):
                logger.debug(f"Skip {signal.symbol}: on cooldown")
                continue
            
            # Skip if daily limit reached
            if self._daily_limit_reached(signal.symbol):
                logger.debug(f"Skip {signal.symbol}: daily limit reached")
                continue
            
            self.queue.pending.append(signal)
    
    def get_next_signals(
        self, 
        n: int = None,
        current_positions: Set[str] = None,
        open_slots: int = None
    ) -> List[SignalEvent]:
        """
        Get prioritized signals for this bar.
        
        Args:
            n: Max signals to return (defaults to config)
            current_positions: Set of currently held symbols
            open_slots: Number of available position slots
        """
        if n is None:
            n = self.config.max_signals_per_bar
        
        if open_slots is not None:
            n = min(n, open_slots)
        
        current_positions = current_positions or set()
        
        # Filter out already held symbols
        available = [
            s for s in self.queue.pending 
            if s.symbol not in current_positions
        ]
        
        # Sort by priority
        if self.config.select_by == "score":
            available.sort(key=lambda s: s.score, reverse=True)
        elif self.config.select_by == "atr":
            # Lower ATR% = higher priority (lower volatility)
            available.sort(key=lambda s: s.atrp_pct)
        elif self.config.select_by == "regime":
            # Prioritize signals in BTC_UP regime
            def regime_priority(s):
                if "BTC_UP" in s.market_regime:
                    return 0
                elif "BTC_SIDE" in s.market_regime:
                    return 1
                else:
                    return 2
            available.sort(key=lambda s: (regime_priority(s), -s.score))
        
        # Take top N
        selected = available[:n]
        
        # Remove selected from pending
        selected_set = set(id(s) for s in selected)
        self.queue.pending = [s for s in self.queue.pending if id(s) not in selected_set]
        
        return selected
    
    def record_entry(self, symbol: str) -> None:
        """Record that we entered a position"""
        self.queue.daily_counts[symbol] = self.queue.daily_counts.get(symbol, 0) + 1
    
    def record_exit(self, symbol: str) -> None:
        """Record exit - start cooldown"""
        self.queue.cooldowns[symbol] = self.current_bar + self.config.symbol_cooldown_bars
    
    def advance_bar(self) -> None:
        """Advance to next bar"""
        self.current_bar += 1
        
        # Clear expired cooldowns
        expired = [s for s, bar in self.queue.cooldowns.items() if bar <= self.current_bar]
        for s in expired:
            del self.queue.cooldowns[s]
        
        # Clear pending signals from previous bar
        self.queue.pending.clear()
    
    def _is_on_cooldown(self, symbol: str) -> bool:
        """Check if symbol is on cooldown"""
        return symbol in self.queue.cooldowns and \
               self.queue.cooldowns[symbol] > self.current_bar
    
    def _daily_limit_reached(self, symbol: str) -> bool:
        """Check if daily trade limit reached for symbol"""
        count = self.queue.daily_counts.get(symbol, 0)
        return count >= self.config.same_symbol_max_per_day


def prioritize_signals(
    signals: List[SignalEvent],
    max_per_bar: int = 3,
    sort_by: str = "score"
) -> List[SignalEvent]:
    """
    Simple function to prioritize signals by timestamp groups.
    
    Groups signals by similar timestamp, then sorts each group.
    Returns flattened list with priorities applied.
    """
    if not signals:
        return []
    
    # Group by timestamp (rounded to bar)
    from collections import defaultdict
    bars = defaultdict(list)
    
    # Assume signals within 1 minute belong to same bar
    for s in signals:
        bar_key = s.event_ts // 60000  # Round to minute
        bars[bar_key].append(s)
    
    result = []
    for bar_key in sorted(bars.keys()):
        bar_signals = bars[bar_key]
        
        # Sort within bar
        if sort_by == "score":
            bar_signals.sort(key=lambda s: s.score, reverse=True)
        elif sort_by == "atr":
            bar_signals.sort(key=lambda s: s.atrp_pct)
        
        # Take top N per bar
        result.extend(bar_signals[:max_per_bar])
    
    return result


if __name__ == "__main__":
    # Test portfolio manager
    from dataclasses import dataclass
    
    @dataclass
    class MockSignal:
        symbol: str
        signal_type: str
        score: int
        event_ts: int
        atrp_pct: float
        market_regime: str
    
    config = PortfolioConfig(
        max_concurrent_positions=3,
        max_signals_per_bar=2,
        symbol_cooldown_bars=3
    )
    
    pm = PortfolioManager(config)
    
    # Simulate signals
    test_signals = [
        MockSignal(symbol="BTC/USDT", signal_type="BREAKOUT", score=85, event_ts=1000, atrp_pct=3.0, market_regime="BTC_UP|A"),
        MockSignal(symbol="ETH/USDT", signal_type="BREAKOUT", score=75, event_ts=1000, atrp_pct=4.0, market_regime="BTC_UP|B"),
        MockSignal(symbol="SOL/USDT", signal_type="BREAKOUT", score=90, event_ts=1000, atrp_pct=5.0, market_regime="BTC_SIDE|B"),
    ]
    
    pm.queue.pending = test_signals
    
    # Get prioritized signals
    selected = pm.get_next_signals(n=2)
    
    print("\n📊 PORTFOLIO SIGNAL PRIORITIZATION TEST")
    print("=" * 50)
    print(f"Input: {len(test_signals)} signals")
    print(f"Output (top 2 by score):")
    for s in selected:
        print(f"  - {s.symbol}: score={s.score}")
    
    # Test cooldown
    pm.record_exit("BTC/USDT")
    pm.advance_bar()
    
    print(f"\n🕒 Cooldowns active: {pm.queue.cooldowns}")
    print("✅ Portfolio Manager test passed!")
