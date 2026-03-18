# PART10: VCP 백테스팅 엔진

## 1. `crypto_market/vcp_backtest/config.py`

```python
#!/usr/bin/env python3
"""VCP Backtest Configuration"""
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple, List


@dataclass
class BacktestConfig:
    """ULTRATHINK Backtest Configuration"""
    
    # ===== ENTRY RULES =====
    entry_trigger: Literal["BREAKOUT", "RETEST", "BOTH"] = "BREAKOUT"
    entry_timing: Literal["SIGNAL_CANDLE", "NEXT_OPEN"] = "NEXT_OPEN"
    min_score: int = 50
    min_grade: str = "C"
    
    # ===== EXIT RULES =====
    stop_loss_type: Literal["FIXED_PCT", "PIVOT_BASED", "ATR_MULT"] = "PIVOT_BASED"
    stop_loss_value: float = 2.0
    take_profit_pct: Optional[float] = 10.0
    trailing_stop_pct: Optional[float] = 5.0
    max_hold_bars: Optional[int] = 20
    
    # ===== FEES & SLIPPAGE =====
    commission_pct: float = 0.1
    slippage_pct: float = 0.05
    
    # ===== POSITION MANAGEMENT =====
    initial_capital: float = 100000.0
    max_concurrent_positions: int = 5
    position_sizing: Literal["EQUAL", "VOLATILITY", "SCORE_WEIGHTED"] = "EQUAL"
    max_position_pct: float = 20.0
    
    # ===== MARKET GATE =====
    use_market_gate: bool = True
    allow_btc_side: bool = True
    allow_btc_down: bool = False
    
    def get_total_fee_pct(self) -> float:
        return 2 * (self.commission_pct + self.slippage_pct)
    
    def should_trade_in_regime(self, regime: str) -> bool:
        if not self.use_market_gate:
            return True
        if regime == "BTC_UP":
            return True
        if regime == "BTC_SIDE":
            return self.allow_btc_side
        if regime == "BTC_DOWN":
            return self.allow_btc_down
        return self.allow_btc_side
    
    def grade_allowed(self, grade: str) -> bool:
        grade_order = {"A": 0, "B": 1, "C": 2, "D": 3}
        min_order = grade_order.get(self.min_grade, 2)
        current_order = grade_order.get(grade, 3)
        return current_order <= min_order
```

---

## 2. `crypto_market/vcp_backtest/fee_model.py`

```python
def calculate_net_pnl(entry_price, exit_price, quantity, config) -> tuple:
    entry_value = entry_price * quantity
    entry_commission = entry_value * (config.commission_pct / 100)
    exit_value = exit_price * quantity
    exit_commission = exit_value * (config.commission_pct / 100)
    gross_pnl = exit_value - entry_value
    total_fees = entry_commission + exit_commission
    net_pnl = gross_pnl - total_fees
    return gross_pnl, net_pnl, total_fees

def apply_slippage_to_entry(price, config):
    return price * (1 + config.slippage_pct / 100)

def apply_slippage_to_exit(price, is_stop, config):
    if is_stop:
        return price * (1 - config.slippage_pct / 100)
    return price * (1 - config.slippage_pct / 200)
```

> 전체 백테스트 엔진(engine.py 376줄)은 실제 파일 참조:
> `/Users/seoheun/Documents/국내주식/crypto_market/vcp_backtest/engine.py`
