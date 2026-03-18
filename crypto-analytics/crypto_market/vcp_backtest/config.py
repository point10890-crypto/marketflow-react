#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Backtest Configuration
All tunable parameters for the backtesting engine.
"""
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple, List


@dataclass
class BacktestConfig:
    """
    ULTRATHINK Backtest Configuration
    All parameters for entry, exit, fees, and position management.
    """
    
    # ===== ENTRY RULES =====
    entry_trigger: Literal["BREAKOUT", "RETEST", "BOTH"] = "BREAKOUT"
    entry_timing: Literal["SIGNAL_CANDLE", "NEXT_OPEN"] = "NEXT_OPEN"
    min_score: int = 50  # Minimum signal score to enter
    min_grade: str = "C"  # Minimum VCP grade (A, B, C, D)
    
    # ===== EXIT RULES =====
    stop_loss_type: Literal["FIXED_PCT", "PIVOT_BASED", "ATR_MULT"] = "PIVOT_BASED"
    stop_loss_value: float = 2.0  # % below pivot, or fixed %, or ATR multiplier
    take_profit_pct: Optional[float] = 10.0  # None = no fixed TP
    trailing_stop_pct: Optional[float] = 5.0  # None = disabled
    max_hold_bars: Optional[int] = 20  # Time-based exit, None = disabled
    
    # ===== FEES & SLIPPAGE =====
    commission_pct: float = 0.1  # Per side (0.1% = Binance VIP0)
    slippage_pct: float = 0.05  # Conservative estimate
    
    # ===== POSITION MANAGEMENT =====
    initial_capital: float = 100000.0
    max_concurrent_positions: int = 5
    position_sizing: Literal["EQUAL", "VOLATILITY", "SCORE_WEIGHTED"] = "EQUAL"
    max_position_pct: float = 20.0  # Max % of capital per position
    
    # ===== MARKET GATE =====
    use_market_gate: bool = True
    require_btc_up: bool = False  # Only trade when BTC_UP
    allow_btc_side: bool = True  # Allow trading in BTC_SIDE
    allow_btc_down: bool = False  # Allow trading in BTC_DOWN
    
    # ===== TIME PERIODS =====
    train_start: str = "2021-01-01"
    train_end: str = "2024-01-01"
    test_start: str = "2024-01-01"
    test_end: str = "2025-01-01"
    
    # ===== VCP PARAMETERS (for tuning) =====
    # These override config.py defaults during parameter search
    min_r12: Optional[float] = None
    min_r23: Optional[float] = None
    swing_k: Optional[int] = None
    breakout_min_pct: Optional[float] = None
    retest_tol_pct: Optional[float] = None
    
    def get_total_fee_pct(self) -> float:
        """Total roundtrip cost (commission + slippage on both sides)"""
        return 2 * (self.commission_pct + self.slippage_pct)
    
    def should_trade_in_regime(self, regime: str) -> bool:
        """Check if trading is allowed in given market regime"""
        if not self.use_market_gate:
            return True
        
        if regime == "BTC_UP":
            return True
        if regime == "BTC_SIDE":
            return self.allow_btc_side
        if regime == "BTC_DOWN":
            return self.allow_btc_down
        
        return self.allow_btc_side  # Default for unknown
    
    def grade_allowed(self, grade: str) -> bool:
        """Check if VCP grade meets minimum requirement"""
        grade_order = {"A": 0, "B": 1, "C": 2, "D": 3}
        min_order = grade_order.get(self.min_grade, 2)
        current_order = grade_order.get(grade, 3)
        return current_order <= min_order
    
    @classmethod
    def default(cls) -> "BacktestConfig":
        """Default configuration"""
        return cls()
    
    @classmethod
    def conservative(cls) -> "BacktestConfig":
        """
        CONSERVATIVE preset based on Walk-Forward analysis (2025-12-26).
        Designed to reduce overfitting and improve OOS consistency.
        
        Changes from default:
        - min_score: 50 → 60 (higher quality signals only)
        - min_grade: C → B (top grades only)
        - max_hold_bars: 20 → 15 (faster timeouts)
        - allow_btc_side: True → False (trend-only trading)
        - trailing_stop_pct: 5.0 → 4.0 (tighter trailing)
        """
        return cls(
            # Entry - more selective
            entry_trigger="BREAKOUT",
            min_score=60,
            min_grade="B",
            
            # Exit - tighter risk management
            stop_loss_type="PIVOT_BASED",
            stop_loss_value=2.0,
            take_profit_pct=8.0,  # Reduced from 10%
            trailing_stop_pct=4.0,  # Tighter trailing
            max_hold_bars=15,  # Faster exit
            
            # Fees
            commission_pct=0.1,
            slippage_pct=0.05,
            
            # Position sizing - more conservative
            max_concurrent_positions=3,  # Reduced from 5
            max_position_pct=15.0,  # Reduced from 20%
            
            # Market Gate - stricter
            use_market_gate=True,
            require_btc_up=False,
            allow_btc_side=False,  # Only trade in uptrend
            allow_btc_down=False,
        )
    
    @classmethod
    def aggressive(cls) -> "BacktestConfig":
        """
        AGGRESSIVE preset for strong bull markets.
        Higher risk, higher potential reward.
        """
        return cls(
            entry_trigger="BOTH",
            min_score=45,
            min_grade="C",
            take_profit_pct=15.0,
            trailing_stop_pct=6.0,
            max_hold_bars=25,
            max_concurrent_positions=8,
            allow_btc_side=True,
            allow_btc_down=False,
        )


@dataclass
class Trade:
    """Single trade record"""
    symbol: str
    entry_time: int  # Unix timestamp
    entry_price: float
    entry_type: str  # BREAKOUT or RETEST
    
    exit_time: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # SL, TP, TRAILING, TIME, MANUAL
    
    quantity: float = 0.0
    pnl_gross: float = 0.0
    pnl_net: float = 0.0
    fees_paid: float = 0.0
    
    # Context
    pivot_high: float = 0.0
    stop_loss: float = 0.0
    take_profit: Optional[float] = None
    score: int = 0
    grade: str = ""
    market_regime: str = ""

    # Signal features (for ML training)
    c1_range_pct: float = 0.0
    c2_range_pct: float = 0.0
    c3_range_pct: float = 0.0
    vol_ratio: float = 0.0
    wick_ratio: float = 0.0
    ema_sep_pct: float = 0.0
    above_ema50_ratio: float = 0.0
    atrp_pct: float = 0.0
    breakout_close_pct: float = 0.0
    liquidity_bucket: str = ""
    
    @property
    def is_closed(self) -> bool:
        return self.exit_time is not None
    
    @property
    def return_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.pnl_net / (self.entry_price * self.quantity)) * 100
    
    @property
    def r_multiple(self) -> float:
        """Risk-adjusted return (R-multiple)"""
        if self.entry_price == 0 or self.stop_loss == 0:
            return 0.0
        risk_per_unit = self.entry_price - self.stop_loss
        if risk_per_unit <= 0:
            return 0.0
        return self.pnl_net / (risk_per_unit * self.quantity)
    
    @property
    def is_winner(self) -> bool:
        return self.pnl_net > 0


@dataclass
class BacktestResult:
    """Complete backtest result"""
    config: BacktestConfig
    trades: List[Trade] = field(default_factory=list)
    
    # Performance metrics
    total_trades: int = 0
    winners: int = 0
    losers: int = 0
    win_rate: float = 0.0
    
    total_pnl_gross: float = 0.0
    total_pnl_net: float = 0.0
    total_fees: float = 0.0
    
    profit_factor: float = 0.0
    avg_r_multiple: float = 0.0
    max_consecutive_losses: int = 0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    
    # Regime breakdown
    regime_stats: dict = field(default_factory=dict)
    
    # Equity curve
    equity_curve: List[Tuple[int, float]] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        return {
            "config": {
                "entry_trigger": self.config.entry_trigger,
                "stop_loss_type": self.config.stop_loss_type,
                "stop_loss_value": self.config.stop_loss_value,
                "take_profit_pct": self.config.take_profit_pct,
                "trailing_stop_pct": self.config.trailing_stop_pct,
                "commission_pct": self.config.commission_pct,
                "slippage_pct": self.config.slippage_pct,
            },
            "performance": {
                "total_trades": self.total_trades,
                "win_rate": round(self.win_rate, 2),
                "profit_factor": round(self.profit_factor, 2),
                "avg_r_multiple": round(self.avg_r_multiple, 2),
                "max_consecutive_losses": self.max_consecutive_losses,
                "max_drawdown_pct": round(self.max_drawdown_pct, 2),
                "sharpe_ratio": round(self.sharpe_ratio, 2),
                "total_pnl_net": round(self.total_pnl_net, 2),
                "total_fees": round(self.total_fees, 2),
            },
            "regime_breakdown": self.regime_stats,
            "trades_summary": {
                "winners": self.winners,
                "losers": self.losers,
                "gross_pnl": round(self.total_pnl_gross, 2),
            },
            "trades": [
                {
                    "symbol": t.symbol,
                    "entry_time": t.entry_time,
                    "entry_price": round(t.entry_price, 6),
                    "entry_type": t.entry_type,
                    "exit_price": round(t.exit_price, 6) if t.exit_price else None,
                    "exit_reason": t.exit_reason,
                    "return_pct": round(t.return_pct, 4),
                    "r_multiple": round(t.r_multiple, 4),
                    "is_winner": t.is_winner,
                    "score": t.score,
                    "grade": t.grade,
                    "market_regime": t.market_regime,
                    "c1_range_pct": round(t.c1_range_pct, 4),
                    "c2_range_pct": round(t.c2_range_pct, 4),
                    "c3_range_pct": round(t.c3_range_pct, 4),
                    "vol_ratio": round(t.vol_ratio, 4),
                    "wick_ratio": round(t.wick_ratio, 4),
                    "ema_sep_pct": round(t.ema_sep_pct, 4),
                    "above_ema50_ratio": round(t.above_ema50_ratio, 4),
                    "atrp_pct": round(t.atrp_pct, 4),
                    "breakout_close_pct": round(t.breakout_close_pct, 4),
                    "liquidity_bucket": t.liquidity_bucket,
                }
                for t in self.trades
            ]
        }
