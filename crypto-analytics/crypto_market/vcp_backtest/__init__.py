#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Backtest Package
"""
from .config import BacktestConfig, Trade, BacktestResult
from .engine import TradeSimulator, PositionManager, run_backtest
from .fee_model import calculate_net_pnl, fee_summary
from .signal_replay import SignalReplayEngine, generate_signals_for_backtest
from .walk_forward import WalkForwardValidator, run_walk_forward, WalkForwardResult

__all__ = [
    # Config
    "BacktestConfig",
    "Trade",
    "BacktestResult",
    
    # Engine
    "TradeSimulator",
    "PositionManager",
    "run_backtest",
    
    # Fees
    "calculate_net_pnl",
    "fee_summary",
    
    # Signal Replay
    "SignalReplayEngine",
    "generate_signals_for_backtest",
    
    # Walk-Forward
    "WalkForwardValidator",
    "run_walk_forward",
    "WalkForwardResult",
]
