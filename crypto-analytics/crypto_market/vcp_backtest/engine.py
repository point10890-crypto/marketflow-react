#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Backtest - Trade Execution Engine
Simulates trade entry, position tracking, and exit logic.
"""
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import numpy as np

from .config import BacktestConfig, Trade, BacktestResult
from .fee_model import calculate_net_pnl, apply_slippage_to_entry, apply_slippage_to_exit

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import SignalEvent, Candle

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PositionManager:
    """Manages open positions and capital allocation"""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.capital = config.initial_capital
        self.open_positions: Dict[str, Trade] = {}  # symbol -> Trade
        self.closed_trades: List[Trade] = []
        self.equity_curve: List[Tuple[int, float]] = []
        self.highest_equity = config.initial_capital
        self.max_drawdown = 0.0
    
    def can_open_position(self, symbol: str) -> bool:
        """Check if we can open a new position"""
        if symbol in self.open_positions:
            return False
        if len(self.open_positions) >= self.config.max_concurrent_positions:
            return False
        return True
    
    def calculate_position_size(self, entry_price: float, signal: SignalEvent) -> float:
        """Calculate position size based on config"""
        max_position_value = self.capital * (self.config.max_position_pct / 100)
        
        if self.config.position_sizing == "EQUAL":
            # Equal allocation across max positions
            position_value = min(
                self.capital / self.config.max_concurrent_positions,
                max_position_value
            )
        elif self.config.position_sizing == "SCORE_WEIGHTED":
            # Higher score = larger position
            score_factor = signal.score / 100.0
            base_value = self.capital / self.config.max_concurrent_positions
            position_value = min(base_value * (0.5 + score_factor), max_position_value)
        else:  # VOLATILITY - simplified
            # Lower ATR% = larger position
            atr_factor = max(0.3, 1.0 - (signal.atrp_pct / 10.0))
            base_value = self.capital / self.config.max_concurrent_positions
            position_value = min(base_value * atr_factor, max_position_value)
        
        return position_value / entry_price
    
    def open_position(self, signal: SignalEvent, entry_candle: Candle) -> Optional[Trade]:
        """Open a new position"""
        if not self.can_open_position(signal.symbol):
            return None
        
        # Determine entry price
        if self.config.entry_timing == "SIGNAL_CANDLE":
            entry_price = entry_candle.close
        else:  # NEXT_OPEN - but we use signal candle close as proxy
            entry_price = entry_candle.close
        
        # Apply slippage
        entry_price = apply_slippage_to_entry(entry_price, self.config)
        
        # Calculate position size
        quantity = self.calculate_position_size(entry_price, signal)
        
        # Calculate stop loss
        if self.config.stop_loss_type == "PIVOT_BASED":
            stop_loss = signal.pivot_high * (1 - self.config.stop_loss_value / 100)
        elif self.config.stop_loss_type == "ATR_MULT":
            atr_value = entry_price * (signal.atrp_pct / 100)
            stop_loss = entry_price - (atr_value * self.config.stop_loss_value)
        else:  # FIXED_PCT
            stop_loss = entry_price * (1 - self.config.stop_loss_value / 100)
        
        # Calculate take profit
        take_profit = None
        if self.config.take_profit_pct:
            take_profit = entry_price * (1 + self.config.take_profit_pct / 100)
        
        # Extract grade from market_regime (format: "BTC_UP|A")
        regime_parts = signal.market_regime.split("|")
        regime = regime_parts[0] if regime_parts else "BTC_SIDE"
        grade = regime_parts[1] if len(regime_parts) > 1 else "D"
        
        trade = Trade(
            symbol=signal.symbol,
            entry_time=signal.event_ts,
            entry_price=entry_price,
            entry_type=signal.signal_type,
            quantity=quantity,
            pivot_high=signal.pivot_high,
            stop_loss=stop_loss,
            take_profit=take_profit,
            score=signal.score,
            grade=grade,
            market_regime=regime,
            c1_range_pct=signal.c1_range_pct,
            c2_range_pct=signal.c2_range_pct,
            c3_range_pct=signal.c3_range_pct,
            vol_ratio=signal.vol_ratio,
            wick_ratio=signal.wick_ratio,
            ema_sep_pct=signal.ema_sep_pct,
            above_ema50_ratio=signal.above_ema50_ratio,
            atrp_pct=signal.atrp_pct,
            breakout_close_pct=signal.breakout_close_pct,
            liquidity_bucket=signal.liquidity_bucket,
        )
        
        self.open_positions[signal.symbol] = trade
        logger.debug(f"Opened {signal.symbol} @ {entry_price:.4f}, SL: {stop_loss:.4f}")
        return trade
    
    def check_exits(self, candle: Candle, symbol: str, bar_count: int) -> Optional[Trade]:
        """Check if position should be closed"""
        if symbol not in self.open_positions:
            return None
        
        trade = self.open_positions[symbol]
        exit_reason = None
        exit_price = None
        
        # Check stop loss (use low of candle)
        if candle.low <= trade.stop_loss:
            exit_reason = "SL"
            exit_price = apply_slippage_to_exit(trade.stop_loss, True, self.config)
        
        # Check take profit (use high of candle)
        elif trade.take_profit and candle.high >= trade.take_profit:
            exit_reason = "TP"
            exit_price = apply_slippage_to_exit(trade.take_profit, False, self.config)
        
        # Check trailing stop
        elif self.config.trailing_stop_pct:
            # Track highest high since entry
            trail_stop = candle.high * (1 - self.config.trailing_stop_pct / 100)
            if candle.close <= trail_stop and candle.close > trade.entry_price:
                exit_reason = "TRAILING"
                exit_price = apply_slippage_to_exit(candle.close, True, self.config)
        
        # Check time-based exit
        if not exit_reason and self.config.max_hold_bars:
            if bar_count >= self.config.max_hold_bars:
                exit_reason = "TIME"
                exit_price = apply_slippage_to_exit(candle.close, False, self.config)
        
        if exit_reason:
            return self.close_position(symbol, exit_price, candle.ts, exit_reason)
        
        return None
    
    def close_position(self, symbol: str, exit_price: float, exit_time: int, reason: str) -> Trade:
        """Close a position and calculate PnL"""
        trade = self.open_positions.pop(symbol)
        
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.exit_reason = reason
        
        # Calculate PnL
        gross_pnl, net_pnl, fees = calculate_net_pnl(
            trade.entry_price,
            exit_price,
            trade.quantity,
            self.config
        )
        
        trade.pnl_gross = gross_pnl
        trade.pnl_net = net_pnl
        trade.fees_paid = fees
        
        # Update capital
        self.capital += net_pnl
        
        # Track equity curve
        self.equity_curve.append((exit_time, self.capital))
        
        # Update max drawdown
        if self.capital > self.highest_equity:
            self.highest_equity = self.capital
        drawdown = (self.highest_equity - self.capital) / self.highest_equity * 100
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        self.closed_trades.append(trade)
        
        logger.debug(f"Closed {symbol} @ {exit_price:.4f} ({reason}), PnL: {net_pnl:.2f}")
        return trade


class TradeSimulator:
    """
    Main trade simulation engine.
    Processes signals chronologically and simulates trades.
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.position_manager = PositionManager(config)
    
    def should_take_signal(self, signal: SignalEvent) -> bool:
        """Check if signal passes all gates"""
        # Score gate
        if signal.score < self.config.min_score:
            return False
        
        # Entry type gate
        if self.config.entry_trigger == "BREAKOUT" and signal.signal_type != "BREAKOUT":
            return False
        if self.config.entry_trigger == "RETEST" and signal.signal_type != "RETEST_OK":
            return False
        
        # Grade gate
        regime_parts = signal.market_regime.split("|")
        grade = regime_parts[1] if len(regime_parts) > 1 else "D"
        if not self.config.grade_allowed(grade):
            return False
        
        # Market regime gate
        regime = regime_parts[0] if regime_parts else "BTC_SIDE"
        if not self.config.should_trade_in_regime(regime):
            return False
        
        return True
    
    def simulate(
        self,
        signals: List[SignalEvent],
        candle_getter,  # Function: (symbol, timestamp) -> Candle
        candles_after_getter  # Function: (symbol, timestamp, n) -> List[Candle]
    ) -> BacktestResult:
        """
        Run the full simulation.
        
        Args:
            signals: Chronological list of signals
            candle_getter: Function to get candle at specific time
            candles_after_getter: Function to get candles after a time
        """
        logger.info(f"Starting simulation with {len(signals)} signals...")
        
        # Sort signals by timestamp
        signals = sorted(signals, key=lambda s: s.event_ts)
        
        # Track position bar counts (for time-based exit)
        position_bar_counts: Dict[str, int] = {}
        
        for signal in signals:
            # Try to open position
            if self.should_take_signal(signal):
                entry_candle = candle_getter(signal.symbol, signal.event_ts)
                if entry_candle:
                    trade = self.position_manager.open_position(signal, entry_candle)
                    if trade:
                        position_bar_counts[signal.symbol] = 0
            
            # Check exits for all open positions
            for symbol in list(self.position_manager.open_positions.keys()):
                # Get next candles after entry
                trade = self.position_manager.open_positions[symbol]
                bar_count = position_bar_counts.get(symbol, 0)
                
                # Get candle at signal time
                candle = candle_getter(symbol, signal.event_ts)
                if candle and candle.ts > trade.entry_time:
                    position_bar_counts[symbol] = bar_count + 1
                    closed = self.position_manager.check_exits(
                        candle, symbol, position_bar_counts[symbol]
                    )
                    if closed:
                        del position_bar_counts[symbol]
        
        # Force close remaining positions at last available price
        for symbol in list(self.position_manager.open_positions.keys()):
            trade = self.position_manager.open_positions[symbol]
            self.position_manager.close_position(
                symbol,
                trade.entry_price,  # Use entry price as last resort
                signals[-1].event_ts if signals else 0,
                "END"
            )
        
        # Calculate final metrics
        return self._calculate_result()
    
    def _calculate_result(self) -> BacktestResult:
        """Calculate final backtest metrics"""
        trades = self.position_manager.closed_trades
        
        if not trades:
            return BacktestResult(config=self.config)
        
        winners = [t for t in trades if t.is_winner]
        losers = [t for t in trades if not t.is_winner]
        
        total_wins = sum(t.pnl_net for t in winners)
        total_losses = abs(sum(t.pnl_net for t in losers))
        
        # Profit factor
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
        
        # Average R-multiple
        r_multiples = [t.r_multiple for t in trades if t.r_multiple != 0]
        avg_r = np.mean(r_multiples) if r_multiples else 0.0
        
        # Max consecutive losses
        max_consec = 0
        current_consec = 0
        for t in trades:
            if not t.is_winner:
                current_consec += 1
                max_consec = max(max_consec, current_consec)
            else:
                current_consec = 0
        
        # Sharpe ratio (simplified - using returns)
        returns = [t.return_pct for t in trades]
        if len(returns) > 1:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 / len(returns))
        else:
            sharpe = 0.0
        
        # Regime breakdown
        regime_stats = {}
        for regime in ["BTC_UP", "BTC_SIDE", "BTC_DOWN"]:
            regime_trades = [t for t in trades if t.market_regime == regime]
            if regime_trades:
                regime_winners = [t for t in regime_trades if t.is_winner]
                regime_stats[regime] = {
                    "trades": len(regime_trades),
                    "win_rate": len(regime_winners) / len(regime_trades) * 100,
                    "avg_pnl": np.mean([t.pnl_net for t in regime_trades])
                }
        
        return BacktestResult(
            config=self.config,
            trades=trades,
            total_trades=len(trades),
            winners=len(winners),
            losers=len(losers),
            win_rate=len(winners) / len(trades) * 100 if trades else 0,
            total_pnl_gross=sum(t.pnl_gross for t in trades),
            total_pnl_net=sum(t.pnl_net for t in trades),
            total_fees=sum(t.fees_paid for t in trades),
            profit_factor=profit_factor,
            avg_r_multiple=avg_r,
            max_consecutive_losses=max_consec,
            max_drawdown_pct=self.position_manager.max_drawdown,
            sharpe_ratio=sharpe,
            regime_stats=regime_stats,
            equity_curve=self.position_manager.equity_curve
        )


def run_backtest(
    signals: List[SignalEvent],
    candle_getter,
    candles_after_getter,
    config: BacktestConfig = None
) -> BacktestResult:
    """
    Convenience function to run a complete backtest.
    """
    if config is None:
        config = BacktestConfig()
    
    simulator = TradeSimulator(config)
    return simulator.simulate(signals, candle_getter, candles_after_getter)
