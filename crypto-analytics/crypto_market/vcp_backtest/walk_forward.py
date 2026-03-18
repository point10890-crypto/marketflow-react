#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Backtest - Walk-Forward Validation
Rolling window out-of-sample testing for robust parameter selection.
"""
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import json

from .config import BacktestConfig, BacktestResult
from .engine import TradeSimulator
from .signal_replay import SignalReplayEngine, generate_signals_for_backtest

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    """Single walk-forward window result"""
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    
    # In-sample metrics
    is_trades: int = 0
    is_win_rate: float = 0.0
    is_sharpe: float = 0.0
    is_profit_factor: float = 0.0
    
    # Out-of-sample metrics
    oos_trades: int = 0
    oos_win_rate: float = 0.0
    oos_sharpe: float = 0.0
    oos_profit_factor: float = 0.0
    oos_pnl: float = 0.0
    
    # Stability metrics
    sharpe_degradation: float = 0.0  # (IS - OOS) / IS
    win_rate_degradation: float = 0.0


@dataclass
class WalkForwardResult:
    """Complete walk-forward analysis result"""
    config: BacktestConfig
    windows: List[WalkForwardWindow] = field(default_factory=list)
    
    # Aggregate OOS metrics
    total_oos_trades: int = 0
    avg_oos_win_rate: float = 0.0
    avg_oos_sharpe: float = 0.0
    avg_oos_profit_factor: float = 0.0
    total_oos_pnl: float = 0.0
    
    # Stability
    avg_sharpe_degradation: float = 0.0
    consistency_score: float = 0.0  # % of windows where OOS was profitable
    
    def to_dict(self) -> dict:
        return {
            "summary": {
                "total_oos_trades": self.total_oos_trades,
                "avg_oos_win_rate": round(self.avg_oos_win_rate, 2),
                "avg_oos_sharpe": round(self.avg_oos_sharpe, 2),
                "avg_oos_profit_factor": round(self.avg_oos_profit_factor, 2),
                "total_oos_pnl": round(self.total_oos_pnl, 2),
                "avg_sharpe_degradation": round(self.avg_sharpe_degradation, 2),
                "consistency_score": round(self.consistency_score, 2)
            },
            "windows": [
                {
                    "period": f"{w.train_start} to {w.test_end}",
                    "is_sharpe": round(w.is_sharpe, 2),
                    "oos_sharpe": round(w.oos_sharpe, 2),
                    "oos_pnl": round(w.oos_pnl, 2),
                    "degradation": round(w.sharpe_degradation, 2)
                }
                for w in self.windows
            ]
        }


class WalkForwardValidator:
    """
    Walk-Forward Validation Engine
    
    Rolling window approach:
    1. Train on [t, t+train_months]: Run backtest, record metrics
    2. Test on [t+train_months, t+train_months+test_months]: OOS performance
    3. Shift window by test_months
    4. Repeat until end of period
    """
    
    def __init__(
        self,
        symbols: List[str],
        full_start: str,
        full_end: str,
        train_months: int = 6,
        test_months: int = 1,
        config: BacktestConfig = None,
        use_yfinance: bool = False
    ):
        self.symbols = symbols
        self.full_start = full_start
        self.full_end = full_end
        self.train_months = train_months
        self.test_months = test_months
        self.config = config or BacktestConfig()
        self.use_yfinance = use_yfinance
    
    def run(self) -> WalkForwardResult:
        """Execute walk-forward validation"""
        logger.info(f"Starting walk-forward validation: {self.full_start} to {self.full_end}")
        logger.info(f"Train: {self.train_months} months, Test: {self.test_months} months")
        
        windows: List[WalkForwardWindow] = []
        
        current_start = datetime.strptime(self.full_start, "%Y-%m-%d")
        end_date = datetime.strptime(self.full_end, "%Y-%m-%d")
        
        window_num = 0
        
        while True:
            train_end = current_start + relativedelta(months=self.train_months)
            test_end = train_end + relativedelta(months=self.test_months)
            
            if test_end > end_date:
                break
            
            window_num += 1
            logger.info(f"Window {window_num}: Train {current_start.date()} - {train_end.date()}, "
                       f"Test {train_end.date()} - {test_end.date()}")
            
            # Run in-sample (training period)
            is_result = self._run_period(
                current_start.strftime("%Y-%m-%d"),
                train_end.strftime("%Y-%m-%d")
            )
            
            # Run out-of-sample (test period)
            oos_result = self._run_period(
                train_end.strftime("%Y-%m-%d"),
                test_end.strftime("%Y-%m-%d")
            )
            
            # Calculate degradation
            sharpe_deg = 0.0
            if is_result.sharpe_ratio != 0:
                sharpe_deg = (is_result.sharpe_ratio - oos_result.sharpe_ratio) / abs(is_result.sharpe_ratio)
            
            win_rate_deg = 0.0
            if is_result.win_rate != 0:
                win_rate_deg = (is_result.win_rate - oos_result.win_rate) / is_result.win_rate
            
            window = WalkForwardWindow(
                train_start=current_start.strftime("%Y-%m-%d"),
                train_end=train_end.strftime("%Y-%m-%d"),
                test_start=train_end.strftime("%Y-%m-%d"),
                test_end=test_end.strftime("%Y-%m-%d"),
                is_trades=is_result.total_trades,
                is_win_rate=is_result.win_rate,
                is_sharpe=is_result.sharpe_ratio,
                is_profit_factor=is_result.profit_factor,
                oos_trades=oos_result.total_trades,
                oos_win_rate=oos_result.win_rate,
                oos_sharpe=oos_result.sharpe_ratio,
                oos_profit_factor=oos_result.profit_factor,
                oos_pnl=oos_result.total_pnl_net,
                sharpe_degradation=sharpe_deg,
                win_rate_degradation=win_rate_deg
            )
            
            windows.append(window)
            
            # Shift window
            current_start += relativedelta(months=self.test_months)
        
        # Calculate aggregate metrics
        return self._aggregate_results(windows)
    
    def _run_period(self, start: str, end: str) -> BacktestResult:
        """Run backtest for a specific period"""
        try:
            # Generate signals for this period
            signals, engine = generate_signals_for_backtest(
                symbols=self.symbols,
                start_date=start,
                end_date=end,
                timeframe="4h",
                use_yfinance=self.use_yfinance
            )
            
            if not signals:
                return BacktestResult(config=self.config)
            
            # Run simulation
            simulator = TradeSimulator(self.config)
            result = simulator.simulate(
                signals,
                lambda sym, ts: engine.get_candle_at_time(sym, ts),
                lambda sym, ts, n: engine.get_candles_after_time(sym, ts, n)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error in period {start} to {end}: {e}")
            return BacktestResult(config=self.config)
    
    def _aggregate_results(self, windows: List[WalkForwardWindow]) -> WalkForwardResult:
        """Aggregate all window results"""
        if not windows:
            return WalkForwardResult(config=self.config)
        
        total_oos_trades = sum(w.oos_trades for w in windows)
        
        # Weighted averages by trade count
        if total_oos_trades > 0:
            avg_win_rate = sum(w.oos_win_rate * w.oos_trades for w in windows) / total_oos_trades
            avg_sharpe = sum(w.oos_sharpe * w.oos_trades for w in windows) / total_oos_trades
            avg_pf = sum(w.oos_profit_factor * w.oos_trades for w in windows) / total_oos_trades
        else:
            avg_win_rate = 0.0
            avg_sharpe = 0.0
            avg_pf = 0.0
        
        total_pnl = sum(w.oos_pnl for w in windows)
        
        # Stability metrics
        avg_degradation = sum(w.sharpe_degradation for w in windows) / len(windows)
        profitable_windows = sum(1 for w in windows if w.oos_pnl > 0)
        consistency = profitable_windows / len(windows) * 100
        
        return WalkForwardResult(
            config=self.config,
            windows=windows,
            total_oos_trades=total_oos_trades,
            avg_oos_win_rate=avg_win_rate,
            avg_oos_sharpe=avg_sharpe,
            avg_oos_profit_factor=avg_pf,
            total_oos_pnl=total_pnl,
            avg_sharpe_degradation=avg_degradation,
            consistency_score=consistency
        )


def run_walk_forward(
    symbols: List[str],
    start_date: str = "2021-01-01",
    end_date: str = "2025-01-01",
    train_months: int = 6,
    test_months: int = 1,
    config: BacktestConfig = None,
    use_yfinance: bool = False
) -> WalkForwardResult:
    """
    Convenience function to run walk-forward validation.
    """
    validator = WalkForwardValidator(
        symbols=symbols,
        full_start=start_date,
        full_end=end_date,
        train_months=train_months,
        test_months=test_months,
        config=config,
        use_yfinance=use_yfinance
    )
    
    return validator.run()
