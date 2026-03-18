#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Backtest - Fee Model
Realistic commission and slippage calculation.
"""
from .config import BacktestConfig


def calculate_entry_cost(entry_price: float, quantity: float, config: BacktestConfig) -> float:
    """
    Calculate total cost of entering a position.
    Returns the actual cost deducted from capital.
    """
    gross_cost = entry_price * quantity
    commission = gross_cost * (config.commission_pct / 100)
    slippage = gross_cost * (config.slippage_pct / 100)
    return commission + slippage


def calculate_exit_cost(exit_price: float, quantity: float, config: BacktestConfig) -> float:
    """
    Calculate total cost of exiting a position.
    Returns the fee deducted from proceeds.
    """
    gross_proceeds = exit_price * quantity
    commission = gross_proceeds * (config.commission_pct / 100)
    slippage = gross_proceeds * (config.slippage_pct / 100)
    return commission + slippage


def calculate_net_pnl(
    entry_price: float,
    exit_price: float,
    quantity: float,
    config: BacktestConfig
) -> tuple[float, float, float]:
    """
    Calculate net PnL after all fees.
    
    Returns:
        (gross_pnl, net_pnl, total_fees)
    """
    gross_pnl = (exit_price - entry_price) * quantity
    
    entry_fees = calculate_entry_cost(entry_price, quantity, config)
    exit_fees = calculate_exit_cost(exit_price, quantity, config)
    total_fees = entry_fees + exit_fees
    
    net_pnl = gross_pnl - total_fees
    
    return gross_pnl, net_pnl, total_fees


def apply_slippage_to_entry(price: float, config: BacktestConfig) -> float:
    """Apply slippage to entry price (buy higher)"""
    return price * (1 + config.slippage_pct / 100)


def apply_slippage_to_exit(price: float, is_stop_loss: bool, config: BacktestConfig) -> float:
    """
    Apply slippage to exit price.
    - Stop loss: Sell lower (slippage works against you)
    - Take profit: Sell lower (still works against you in volatile markets)
    """
    return price * (1 - config.slippage_pct / 100)


def estimate_breakeven_move_pct(config: BacktestConfig) -> float:
    """
    Calculate minimum price move needed to break even after fees.
    Useful for setting minimum take profit targets.
    """
    total_fee_pct = config.get_total_fee_pct()
    return total_fee_pct


def fee_summary(config: BacktestConfig) -> dict:
    """Generate fee structure summary for reporting"""
    return {
        "commission_per_side_pct": config.commission_pct,
        "slippage_per_side_pct": config.slippage_pct,
        "total_roundtrip_pct": config.get_total_fee_pct(),
        "breakeven_move_pct": estimate_breakeven_move_pct(config),
        "example_10k_trade_cost": 10000 * config.get_total_fee_pct() / 100
    }
