#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Backtest CLI Runner
Command-line interface for running backtests and walk-forward validation.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vcp_backtest import (
    BacktestConfig,
    generate_signals_for_backtest,
    run_backtest,
    run_walk_forward,
    fee_summary
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Default crypto universe for backtesting
DEFAULT_CRYPTO_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "MATIC/USDT",
    "LINK/USDT", "DOT/USDT", "ATOM/USDT", "UNI/USDT", "AAVE/USDT",
    "LTC/USDT", "BCH/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT",
    "NEAR/USDT", "FTM/USDT", "ALGO/USDT", "XLM/USDT", "VET/USDT",
]

# Default stock universe for yfinance backtesting
DEFAULT_STOCK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "JPM", "V", "MA", "HD", "PG", "JNJ", "UNH", "XOM"
]


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           VCP BACKTESTING ENGINE v1.0                        ║
║           ULTRATHINK Implementation                          ║
╚══════════════════════════════════════════════════════════════╝
    """)


def print_fee_summary(config: BacktestConfig):
    """Print fee structure summary"""
    fees = fee_summary(config)
    print("\n📊 FEE STRUCTURE:")
    print(f"   Commission per side: {fees['commission_per_side_pct']}%")
    print(f"   Slippage per side:   {fees['slippage_per_side_pct']}%")
    print(f"   Total roundtrip:     {fees['total_roundtrip_pct']}%")
    print(f"   Breakeven move:      {fees['breakeven_move_pct']:.3f}%")
    print(f"   Cost on $10K trade:  ${fees['example_10k_trade_cost']:.2f}")


def print_backtest_results(result):
    """Print formatted backtest results"""
    if hasattr(result, 'to_dict'):
        data = result.to_dict()
    else:
        data = result
    
    perf = data.get('performance', {})
    regime = data.get('regime_breakdown', {})
    
    print("\n" + "═" * 60)
    print("📈 BACKTEST RESULTS")
    print("═" * 60)
    
    print(f"\n💰 PERFORMANCE:")
    print(f"   Total Trades:        {perf.get('total_trades', 0)}")
    print(f"   Win Rate:            {perf.get('win_rate', 0):.1f}%")
    print(f"   Profit Factor:       {perf.get('profit_factor', 0):.2f}")
    print(f"   Avg R-Multiple:      {perf.get('avg_r_multiple', 0):.2f}R")
    print(f"   Max Consec. Losses:  {perf.get('max_consecutive_losses', 0)}")
    print(f"   Max Drawdown:        {perf.get('max_drawdown_pct', 0):.1f}%")
    print(f"   Sharpe Ratio:        {perf.get('sharpe_ratio', 0):.2f}")
    
    print(f"\n💵 PNL:")
    print(f"   Net PnL:             ${perf.get('total_pnl_net', 0):,.2f}")
    print(f"   Total Fees Paid:     ${perf.get('total_fees', 0):,.2f}")
    
    if regime:
        print(f"\n🌐 REGIME BREAKDOWN:")
        for reg, stats in regime.items():
            emoji = "🟢" if reg == "BTC_UP" else ("🟡" if reg == "BTC_SIDE" else "🔴")
            print(f"   {emoji} {reg}:")
            print(f"      Trades: {stats.get('trades', 0)}, "
                  f"Win Rate: {stats.get('win_rate', 0):.1f}%, "
                  f"Avg PnL: ${stats.get('avg_pnl', 0):.2f}")


def print_walk_forward_results(result):
    """Print walk-forward validation results"""
    data = result.to_dict() if hasattr(result, 'to_dict') else result
    summary = data.get('summary', {})
    windows = data.get('windows', [])
    
    print("\n" + "═" * 60)
    print("🔬 WALK-FORWARD VALIDATION RESULTS")
    print("═" * 60)
    
    print(f"\n📊 OUT-OF-SAMPLE AGGREGATE:")
    print(f"   Total OOS Trades:    {summary.get('total_oos_trades', 0)}")
    print(f"   Avg OOS Win Rate:    {summary.get('avg_oos_win_rate', 0):.1f}%")
    print(f"   Avg OOS Sharpe:      {summary.get('avg_oos_sharpe', 0):.2f}")
    print(f"   Avg OOS PF:          {summary.get('avg_oos_profit_factor', 0):.2f}")
    print(f"   Total OOS PnL:       ${summary.get('total_oos_pnl', 0):,.2f}")
    
    print(f"\n🎯 STABILITY METRICS:")
    print(f"   Avg Sharpe Degradation: {summary.get('avg_sharpe_degradation', 0):.1%}")
    print(f"   Consistency Score:      {summary.get('consistency_score', 0):.1f}%")
    
    if windows:
        print(f"\n📅 WINDOW DETAILS:")
        for i, w in enumerate(windows, 1):
            pnl_emoji = "✅" if w['oos_pnl'] > 0 else "❌"
            print(f"   {i}. {w['period']}")
            print(f"      IS Sharpe: {w['is_sharpe']:.2f} → OOS Sharpe: {w['oos_sharpe']:.2f} "
                  f"({pnl_emoji} ${w['oos_pnl']:.0f})")


def run_simple_backtest(args):
    """Run a simple backtest"""
    logger.info("Initializing simple backtest...")
    
    # Build config
    config = BacktestConfig(
        entry_trigger=args.entry_trigger,
        min_score=args.min_score,
        stop_loss_type=args.sl_type,
        stop_loss_value=args.sl_value,
        take_profit_pct=args.tp_pct,
        trailing_stop_pct=args.trailing_pct,
        commission_pct=args.commission,
        slippage_pct=args.slippage,
        max_concurrent_positions=args.max_positions,
        use_market_gate=args.use_gate,
        allow_btc_side=args.allow_side,
        allow_btc_down=args.allow_down
    )
    
    print_fee_summary(config)
    
    # Select universe
    if args.use_yfinance:
        symbols = args.symbols if args.symbols else DEFAULT_STOCK_UNIVERSE
    else:
        symbols = args.symbols if args.symbols else DEFAULT_CRYPTO_UNIVERSE
    
    logger.info(f"Universe: {len(symbols)} symbols")
    logger.info(f"Period: {args.start} to {args.end}")
    
    # Generate signals
    logger.info("Generating signal timeline...")
    signals, engine = generate_signals_for_backtest(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        timeframe=args.timeframe,
        use_yfinance=args.use_yfinance
    )
    
    logger.info(f"Generated {len(signals)} signals")
    
    if not signals:
        print("\n⚠️ No signals generated. Check your date range and symbols.")
        return
    
    # Run backtest
    logger.info("Running trade simulation...")
    result = run_backtest(
        signals=signals,
        candle_getter=lambda sym, ts: engine.get_candle_at_time(sym, ts),
        candles_after_getter=lambda sym, ts, n: engine.get_candles_after_time(sym, ts, n),
        config=config
    )
    
    print_backtest_results(result)
    
    # Save results
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"\n✅ Results saved to {args.output}")


def run_walk_forward_validation(args):
    """Run walk-forward validation"""
    logger.info("Initializing walk-forward validation...")
    
    config = BacktestConfig(
        entry_trigger=args.entry_trigger,
        min_score=args.min_score,
        stop_loss_type=args.sl_type,
        stop_loss_value=args.sl_value,
        use_market_gate=args.use_gate
    )
    
    # Select universe
    if args.use_yfinance:
        symbols = args.symbols if args.symbols else DEFAULT_STOCK_UNIVERSE
    else:
        symbols = args.symbols if args.symbols else DEFAULT_CRYPTO_UNIVERSE
    
    logger.info(f"Universe: {len(symbols)} symbols")
    logger.info(f"Full Period: {args.start} to {args.end}")
    logger.info(f"Train: {args.train_months} months, Test: {args.test_months} months")
    
    result = run_walk_forward(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        train_months=args.train_months,
        test_months=args.test_months,
        config=config,
        use_yfinance=args.use_yfinance
    )
    
    print_walk_forward_results(result)
    
    # Save results
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"\n✅ Results saved to {args.output}")


def main():
    print_banner()
    
    parser = argparse.ArgumentParser(description='VCP Backtest Engine')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Simple backtest command
    bt_parser = subparsers.add_parser('backtest', help='Run simple backtest')
    bt_parser.add_argument('--start', default='2023-01-01', help='Start date (YYYY-MM-DD)')
    bt_parser.add_argument('--end', default='2024-12-01', help='End date (YYYY-MM-DD)')
    bt_parser.add_argument('--timeframe', default='4h', choices=['4h', '1d'], help='Timeframe')
    bt_parser.add_argument('--symbols', nargs='+', help='Symbols to backtest')
    bt_parser.add_argument('--use-yfinance', action='store_true', help='Use yfinance (for stocks)')
    
    # Entry/Exit
    bt_parser.add_argument('--entry-trigger', default='BREAKOUT', choices=['BREAKOUT', 'RETEST', 'BOTH'])
    bt_parser.add_argument('--min-score', type=int, default=50, help='Min signal score')
    bt_parser.add_argument('--sl-type', default='PIVOT_BASED', choices=['PIVOT_BASED', 'FIXED_PCT', 'ATR_MULT'])
    bt_parser.add_argument('--sl-value', type=float, default=2.0, help='Stop loss value')
    bt_parser.add_argument('--tp-pct', type=float, default=10.0, help='Take profit %')
    bt_parser.add_argument('--trailing-pct', type=float, default=5.0, help='Trailing stop %')
    
    # Fees
    bt_parser.add_argument('--commission', type=float, default=0.1, help='Commission %')
    bt_parser.add_argument('--slippage', type=float, default=0.05, help='Slippage %')
    
    # Position management
    bt_parser.add_argument('--max-positions', type=int, default=5, help='Max concurrent positions')
    
    # Market gate
    bt_parser.add_argument('--use-gate', action='store_true', default=True, help='Use market regime gate')
    bt_parser.add_argument('--allow-side', action='store_true', default=True, help='Trade in BTC_SIDE')
    bt_parser.add_argument('--allow-down', action='store_true', default=False, help='Trade in BTC_DOWN')
    
    # Output
    bt_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Walk-forward command
    wf_parser = subparsers.add_parser('walkforward', help='Run walk-forward validation')
    wf_parser.add_argument('--start', default='2021-01-01', help='Start date')
    wf_parser.add_argument('--end', default='2025-01-01', help='End date')
    wf_parser.add_argument('--train-months', type=int, default=6, help='Training window months')
    wf_parser.add_argument('--test-months', type=int, default=1, help='Test window months')
    wf_parser.add_argument('--symbols', nargs='+', help='Symbols')
    wf_parser.add_argument('--use-yfinance', action='store_true')
    wf_parser.add_argument('--entry-trigger', default='BREAKOUT')
    wf_parser.add_argument('--min-score', type=int, default=50)
    wf_parser.add_argument('--sl-type', default='PIVOT_BASED')
    wf_parser.add_argument('--sl-value', type=float, default=2.0)
    wf_parser.add_argument('--use-gate', action='store_true', default=True)
    wf_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Regime comparison command
    rc_parser = subparsers.add_parser('regime-compare', help='Compare Gate vs No-Gate vs Regime-Aware')
    rc_parser.add_argument('--start', default='2023-01-01', help='Start date')
    rc_parser.add_argument('--end', default='2024-12-01', help='End date')
    rc_parser.add_argument('--timeframe', default='4h', choices=['4h', '1d'])
    rc_parser.add_argument('--symbols', nargs='+', help='Symbols')
    rc_parser.add_argument('--use-yfinance', action='store_true')
    rc_parser.add_argument('--min-score', type=int, default=50)
    
    args = parser.parse_args()
    
    if args.command == 'backtest':
        run_simple_backtest(args)
    elif args.command == 'walkforward':
        run_walk_forward_validation(args)
    elif args.command == 'regime-compare':
        run_regime_comparison(args)
    else:
        parser.print_help()


def run_regime_comparison(args):
    """
    Run backtest twice: with and without Market Gate.
    Compare performance and show regime-aware recommendation.
    """
    from vcp_backtest.regime_config import RegimeConfig, compare_gate_performance
    
    logger.info("Running regime comparison analysis...")
    
    # Select universe
    if args.use_yfinance:
        symbols = args.symbols if args.symbols else DEFAULT_STOCK_UNIVERSE
    else:
        symbols = args.symbols if args.symbols else DEFAULT_CRYPTO_UNIVERSE
    
    logger.info(f"Universe: {len(symbols)} symbols")
    logger.info(f"Period: {args.start} to {args.end}")
    
    # Generate signals once
    logger.info("Generating signal timeline...")
    signals, engine = generate_signals_for_backtest(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        timeframe=args.timeframe,
        use_yfinance=args.use_yfinance
    )
    
    if not signals:
        print("\n⚠️ No signals generated.")
        return
    
    logger.info(f"Generated {len(signals)} signals")
    
    # Run 1: WITHOUT Market Gate
    logger.info("Running backtest WITHOUT Market Gate...")
    config_no_gate = BacktestConfig(
        min_score=args.min_score,
        use_market_gate=False,
        allow_btc_side=True,
        allow_btc_down=True,
    )
    
    result_no_gate = run_backtest(
        signals=signals,
        candle_getter=lambda sym, ts: engine.get_candle_at_time(sym, ts),
        candles_after_getter=lambda sym, ts, n: engine.get_candles_after_time(sym, ts, n),
        config=config_no_gate
    )
    
    # Run 2: WITH Market Gate (default settings)
    logger.info("Running backtest WITH Market Gate...")
    config_gate = BacktestConfig(
        min_score=args.min_score,
        use_market_gate=True,
        allow_btc_side=True,
        allow_btc_down=False,
    )
    
    result_gate = run_backtest(
        signals=signals,
        candle_getter=lambda sym, ts: engine.get_candle_at_time(sym, ts),
        candles_after_getter=lambda sym, ts, n: engine.get_candles_after_time(sym, ts, n),
        config=config_gate
    )
    
    # Run 3: WITH Regime-Aware Config (adapts to regime)
    logger.info("Running backtest WITH Regime-Aware Config...")
    # Use conservative as a proxy for regime-awareness
    config_regime = BacktestConfig.conservative()
    
    result_regime = run_backtest(
        signals=signals,
        candle_getter=lambda sym, ts: engine.get_candle_at_time(sym, ts),
        candles_after_getter=lambda sym, ts, n: engine.get_candles_after_time(sym, ts, n),
        config=config_regime
    )
    
    # Print comparison
    print("\n" + "═" * 70)
    print("📊 REGIME-AWARE BACKTEST COMPARISON")
    print("═" * 70)
    
    def get_perf(r):
        d = r.to_dict() if hasattr(r, 'to_dict') else r
        p = d.get('performance', {})
        return {
            'total_trades': p.get('total_trades', 0),
            'win_rate': p.get('win_rate', 0),
            'profit_factor': p.get('profit_factor', 0),
            'max_dd': p.get('max_drawdown_pct', 0),
            'sharpe': p.get('sharpe_ratio', 0),
            'total_pnl': p.get('total_pnl_net', 0),
        }
    
    p1 = get_perf(result_no_gate)
    p2 = get_perf(result_gate)
    p3 = get_perf(result_regime)
    
    print(f"""
┌──────────────────┬────────────┬────────────┬────────────┐
│     지표         │ Gate 미적용 │  Gate 적용  │ Regime-Aware│
├──────────────────┼────────────┼────────────┼────────────┤
│ 총 트레이드      │ {p1['total_trades']:>8}개 │ {p2['total_trades']:>8}개 │ {p3['total_trades']:>8}개 │
│ 승률             │ {p1['win_rate']:>8.1f}% │ {p2['win_rate']:>8.1f}% │ {p3['win_rate']:>8.1f}% │
│ Profit Factor    │ {p1['profit_factor']:>8.2f} │ {p2['profit_factor']:>8.2f} │ {p3['profit_factor']:>8.2f} │
│ Max Drawdown     │ {p1['max_dd']:>8.1f}% │ {p2['max_dd']:>8.1f}% │ {p3['max_dd']:>8.1f}% │
│ Sharpe Ratio     │ {p1['sharpe']:>8.2f} │ {p2['sharpe']:>8.2f} │ {p3['sharpe']:>8.2f} │
│ 총 수익 ($)      │ {p1['total_pnl']:>8.0f} │ {p2['total_pnl']:>8.0f} │ {p3['total_pnl']:>8.0f} │
└──────────────────┴────────────┴────────────┴────────────┘
    """)
    
    # Find best approach
    sharpes = [('Gate 미적용', p1['sharpe']), ('Gate 적용', p2['sharpe']), ('Regime-Aware', p3['sharpe'])]
    best = max(sharpes, key=lambda x: x[1])
    
    print(f"\n🏆 최고 Sharpe: {best[0]} ({best[1]:.2f})")
    
    # Print regime configs
    print("\n📋 REGIME-AWARE 설정 (현재 적용 중):")
    for gate in ["GREEN", "YELLOW", "RED"]:
        rc = RegimeConfig.for_gate(gate)
        emoji = "🟢" if gate == "GREEN" else ("🟡" if gate == "YELLOW" else "🔴")
        print(f"\n   {emoji} {gate}: {rc.description}")
        print(f"      min_score={rc.min_score}, grade={rc.min_grade}, entry={rc.entry_trigger}")


if __name__ == "__main__":
    main()
