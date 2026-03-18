#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Risk Manager
Centralized risk management for live trading and backtesting.

Features:
1. Daily/Weekly loss limits
2. Position concentration limits
3. Volatility-based position sizing
4. Trading halt conditions
"""
import os
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk management limits configuration"""
    
    # Loss limits (percentage of capital)
    max_daily_loss_pct: float = 3.0      # 1일 최대 3% 손실
    max_weekly_loss_pct: float = 7.0     # 주간 최대 7% 손실
    max_monthly_loss_pct: float = 15.0   # 월간 최대 15% 손실
    
    # Position limits
    max_positions: int = 5
    max_single_position_pct: float = 20.0  # 단일 포지션 최대 20%
    max_sector_concentration_pct: float = 40.0  # 섹터 집중 40%
    
    # Volatility limits (ATR multiples)
    reduce_position_atr_mult: float = 2.0   # ATR 2배 → 포지션 축소
    halt_trading_atr_mult: float = 3.0      # ATR 3배 → 트레이딩 중지
    
    # Drawdown limits
    max_drawdown_pct: float = 20.0  # 최대 허용 드로우다운
    
    # Cooldown
    loss_streak_cooldown: int = 3  # 연속 손실 N회 후 쿨다운


@dataclass
class RiskState:
    """Current risk state tracking"""
    
    # P&L tracking
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    
    # Position tracking
    current_positions: int = 0
    sector_exposure: Dict[str, float] = field(default_factory=dict)
    
    # Drawdown tracking
    peak_equity: float = 0.0
    current_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    
    # Loss streak
    consecutive_losses: int = 0
    
    # Timestamps
    last_reset_daily: str = ""
    last_reset_weekly: str = ""
    
    # Status
    is_halted: bool = False
    halt_reason: str = ""


@dataclass
class RiskCheckResult:
    """Result of a risk check"""
    allowed: bool
    reason: str
    suggested_size_pct: float = 100.0  # Percentage of normal position size allowed
    warnings: List[str] = field(default_factory=list)


class RiskManager:
    """
    Centralized risk management.
    """
    
    def __init__(self, limits: RiskLimits = None, initial_capital: float = 10000):
        self.limits = limits or RiskLimits()
        self.initial_capital = initial_capital
        self.state = RiskState(
            peak_equity=initial_capital,
            current_equity=initial_capital
        )
        self._trade_history: List[Dict] = []
    
    def check_can_open_position(
        self,
        position_value: float,
        atr_ratio: float = 1.0,
        sector: str = None
    ) -> RiskCheckResult:
        """
        Check if opening a new position is allowed.
        
        Args:
            position_value: Value of proposed position
            atr_ratio: Current ATR / Historical ATR (1.0 = normal)
            sector: Optional sector/category of the asset
        
        Returns:
            RiskCheckResult with allowed status and reasons
        """
        warnings = []
        suggested_size = 100.0
        
        # Check if trading is halted
        if self.state.is_halted:
            return RiskCheckResult(
                allowed=False,
                reason=f"Trading halted: {self.state.halt_reason}",
                suggested_size_pct=0
            )
        
        # Check daily loss limit
        if abs(self.state.daily_pnl) >= self.limits.max_daily_loss_pct * self.initial_capital / 100:
            return RiskCheckResult(
                allowed=False,
                reason=f"Daily loss limit reached ({self.state.daily_pnl:.2f})",
                suggested_size_pct=0
            )
        
        # Check weekly loss limit
        if abs(self.state.weekly_pnl) >= self.limits.max_weekly_loss_pct * self.initial_capital / 100:
            return RiskCheckResult(
                allowed=False,
                reason=f"Weekly loss limit reached ({self.state.weekly_pnl:.2f})",
                suggested_size_pct=0
            )
        
        # Check max positions
        if self.state.current_positions >= self.limits.max_positions:
            return RiskCheckResult(
                allowed=False,
                reason=f"Max positions reached ({self.state.current_positions})",
                suggested_size_pct=0
            )
        
        # Check single position size
        position_pct = (position_value / self.state.current_equity) * 100
        if position_pct > self.limits.max_single_position_pct:
            suggested_size = (self.limits.max_single_position_pct / position_pct) * 100
            warnings.append(f"Position size reduced to {suggested_size:.0f}%")
        
        # Check sector concentration
        if sector and sector in self.state.sector_exposure:
            sector_pct = self.state.sector_exposure[sector]
            if sector_pct >= self.limits.max_sector_concentration_pct:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Sector concentration limit ({sector}: {sector_pct:.1f}%)",
                    suggested_size_pct=0
                )
        
        # Check volatility
        if atr_ratio >= self.limits.halt_trading_atr_mult:
            return RiskCheckResult(
                allowed=False,
                reason=f"Volatility too high (ATR {atr_ratio:.1f}x normal)",
                suggested_size_pct=0
            )
        elif atr_ratio >= self.limits.reduce_position_atr_mult:
            vol_reduction = (self.limits.halt_trading_atr_mult - atr_ratio) / \
                           (self.limits.halt_trading_atr_mult - self.limits.reduce_position_atr_mult)
            suggested_size = min(suggested_size, vol_reduction * 100)
            warnings.append(f"High volatility - size reduced to {suggested_size:.0f}%")
        
        # Check drawdown
        if self.state.current_drawdown_pct >= self.limits.max_drawdown_pct:
            return RiskCheckResult(
                allowed=False,
                reason=f"Max drawdown reached ({self.state.current_drawdown_pct:.1f}%)",
                suggested_size_pct=0
            )
        
        # Check loss streak cooldown
        if self.state.consecutive_losses >= self.limits.loss_streak_cooldown:
            warnings.append(f"Loss streak ({self.state.consecutive_losses}) - caution advised")
            suggested_size = min(suggested_size, 50.0)  # Reduce by 50%
        
        return RiskCheckResult(
            allowed=True,
            reason="All risk checks passed",
            suggested_size_pct=suggested_size,
            warnings=warnings
        )
    
    def record_trade_result(
        self,
        pnl: float,
        is_win: bool,
        symbol: str = None,
        sector: str = None
    ) -> None:
        """Record a trade result and update state"""
        # Update P&L
        self.state.daily_pnl += pnl
        self.state.weekly_pnl += pnl
        self.state.monthly_pnl += pnl
        
        # Update equity
        self.state.current_equity += pnl
        
        # Update peak equity
        if self.state.current_equity > self.state.peak_equity:
            self.state.peak_equity = self.state.current_equity
        
        # Update drawdown
        if self.state.peak_equity > 0:
            self.state.current_drawdown_pct = \
                (1 - self.state.current_equity / self.state.peak_equity) * 100
        
        # Update loss streak
        if is_win:
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1
        
        # Store in history
        self._trade_history.append({
            'pnl': pnl,
            'is_win': is_win,
            'symbol': symbol,
            'sector': sector,
            'timestamp': datetime.now().isoformat()
        })
        
        # Check if we need to halt
        self._check_halt_conditions()
    
    def _check_halt_conditions(self) -> None:
        """Check if trading should be halted"""
        if self.state.current_drawdown_pct >= self.limits.max_drawdown_pct:
            self.state.is_halted = True
            self.state.halt_reason = f"Max drawdown {self.state.current_drawdown_pct:.1f}%"
        
        if abs(self.state.daily_pnl) >= self.limits.max_daily_loss_pct * self.initial_capital / 100:
            self.state.is_halted = True
            self.state.halt_reason = "Daily loss limit"
    
    def open_position(self, symbol: str, sector: str = None, value_pct: float = 0) -> None:
        """Record opening a position"""
        self.state.current_positions += 1
        
        if sector:
            self.state.sector_exposure[sector] = \
                self.state.sector_exposure.get(sector, 0) + value_pct
    
    def close_position(self, symbol: str, sector: str = None, value_pct: float = 0) -> None:
        """Record closing a position"""
        self.state.current_positions = max(0, self.state.current_positions - 1)
        
        if sector and sector in self.state.sector_exposure:
            self.state.sector_exposure[sector] = \
                max(0, self.state.sector_exposure[sector] - value_pct)
    
    def reset_daily(self) -> None:
        """Reset daily tracking (call at day change)"""
        self.state.daily_pnl = 0.0
        self.state.last_reset_daily = datetime.now().isoformat()
        
        # Unhalt if halted due to daily limit
        if self.state.halt_reason == "Daily loss limit":
            self.state.is_halted = False
            self.state.halt_reason = ""
    
    def reset_weekly(self) -> None:
        """Reset weekly tracking"""
        self.state.weekly_pnl = 0.0
        self.state.last_reset_weekly = datetime.now().isoformat()
    
    def get_status(self) -> Dict:
        """Get current risk status"""
        return {
            'halted': self.state.is_halted,
            'halt_reason': self.state.halt_reason,
            'daily_pnl': self.state.daily_pnl,
            'weekly_pnl': self.state.weekly_pnl,
            'drawdown_pct': self.state.current_drawdown_pct,
            'positions': self.state.current_positions,
            'max_positions': self.limits.max_positions,
            'consecutive_losses': self.state.consecutive_losses,
            'equity': self.state.current_equity,
        }
    
    def print_status(self) -> None:
        """Print risk status"""
        status = self.get_status()
        
        print(f"""
╔══════════════════════════════════════════════════════════╗
║                  RISK MANAGER STATUS                     ║
╠══════════════════════════════════════════════════════════╣
║ Halted:    {str(status['halted']):>6}  │  Reason: {status['halt_reason'][:20]:<20} ║
║ Equity:    ${status['equity']:>10,.2f}                              ║
║ Drawdown:  {status['drawdown_pct']:>6.2f}%  │  Max: {self.limits.max_drawdown_pct}%                ║
╠══════════════════════════════════════════════════════════╣
║ Daily P&L:   ${status['daily_pnl']:>10,.2f}  (Limit: {self.limits.max_daily_loss_pct}%)      ║
║ Weekly P&L:  ${status['weekly_pnl']:>10,.2f}  (Limit: {self.limits.max_weekly_loss_pct}%)     ║
║ Positions:   {status['positions']:>3}/{status['max_positions']}                                     ║
║ Loss Streak: {status['consecutive_losses']:>3}                                          ║
╚══════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    print("\n🛡️ RISK MANAGER TEST")
    print("=" * 50)
    
    # Initialize
    rm = RiskManager(initial_capital=10000)
    
    # Check if we can open a position
    result = rm.check_can_open_position(position_value=2000, atr_ratio=1.0)
    print(f"\n✅ Can open position: {result.allowed}")
    print(f"   Reason: {result.reason}")
    print(f"   Suggested size: {result.suggested_size_pct}%")
    
    # Simulate some trades
    rm.open_position("BTC/USDT", sector="L1", value_pct=20)
    rm.record_trade_result(pnl=150, is_win=True, symbol="BTC/USDT")
    
    rm.open_position("ETH/USDT", sector="L1", value_pct=15)
    rm.record_trade_result(pnl=-80, is_win=False, symbol="ETH/USDT")
    rm.close_position("ETH/USDT", sector="L1", value_pct=15)
    
    # Print status
    rm.print_status()
    
    # Test high volatility
    result = rm.check_can_open_position(position_value=2000, atr_ratio=2.5)
    print(f"\n⚠️ High volatility check: {result.allowed}")
    print(f"   Warnings: {result.warnings}")
    
    print("\n✅ Risk Manager test complete!")
