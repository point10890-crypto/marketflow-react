#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtesting System for Smart Money Strategy v3.0
- Tests the stock picking strategy on historical data
- Calculates returns, Sharpe ratio, Sortino ratio, max drawdown
- Compares against benchmarks (SPY, QQQ)
- Monte Carlo simulation with Student-t distribution
- Walk-forward optimization
- Rolling Sharpe ratio
- Transaction cost modeling

Note on Short Interest Data:
- Finnhub free tier does NOT include short interest data
- Short interest scoring will return neutral (0) if data unavailable
- For production, consider upgrading to paid tier or using FINRA data
"""

import os
import json
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BacktestEngine:
    """Backtesting engine for stock picking strategies"""

    def __init__(self, initial_capital: float = 100000, transaction_cost: float = 0.001):
        self.initial_capital = initial_capital
        self.transaction_cost = transaction_cost  # 0.1% per trade (buy + sell)
        self.benchmark_tickers = ['SPY', 'QQQ']

    def get_historical_prices(self, tickers: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch historical price data"""
        logger.info(f"📊 Fetching data for {len(tickers)} tickers...")

        try:
            data = yf.download(tickers, start=start_date, end=end_date, progress=False)
            if 'Close' in data.columns:
                return data['Close']
            return data
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return pd.DataFrame()

    def calculate_returns(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Calculate daily returns"""
        return prices.pct_change().dropna()

    def calculate_rolling_sharpe(self, returns: pd.Series, window: int = 63,
                                  risk_free_rate: float = 0.04) -> pd.Series:
        """Calculate rolling Sharpe ratio over a window (default 63 trading days = ~3 months)"""
        daily_rf = risk_free_rate / 252
        excess_returns = returns - daily_rf
        rolling_mean = excess_returns.rolling(window=window).mean()
        rolling_std = returns.rolling(window=window).std()
        rolling_sharpe = (rolling_mean * 252) / (rolling_std * np.sqrt(252))
        return rolling_sharpe

    def run_equal_weight_backtest(
        self,
        picks: List[str],
        start_date: str,
        end_date: str,
        rebalance_days: int = 30
    ) -> Dict:
        """
        Run equal-weight portfolio backtest with transaction costs and rebalancing

        Args:
            picks: List of stock tickers
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            rebalance_days: Days between rebalancing

        Returns:
            Backtest results dictionary
        """
        logger.info(f"🚀 Running backtest: {start_date} to {end_date}")
        logger.info(f"📈 Stocks: {picks}")

        # Get all tickers including benchmarks
        all_tickers = list(set(picks + self.benchmark_tickers))

        # Fetch prices
        prices = self.get_historical_prices(all_tickers, start_date, end_date)

        if prices.empty:
            return {'error': 'No price data available'}

        # Filter to available tickers
        available_picks = [t for t in picks if t in prices.columns]

        if not available_picks:
            return {'error': 'No valid tickers found'}

        logger.info(f"✅ Available tickers: {len(available_picks)}/{len(picks)}")

        # Calculate portfolio returns (equal weight)
        pick_prices = prices[available_picks]
        pick_returns = self.calculate_returns(pick_prices)

        # Equal weight portfolio daily returns
        portfolio_returns = pick_returns.mean(axis=1)

        # Apply transaction costs at rebalance points
        # Estimate actual turnover instead of assuming 100% turnover
        # Equal-weight drift over rebalance_days typically causes ~20-40% turnover
        num_positions = len(available_picks)
        estimated_turnover = 0.30  # Conservative 30% turnover per rebalance
        rebalance_cost_per_event = self.transaction_cost * 2 * num_positions * estimated_turnover
        cumulative_transaction_costs = 0
        rebalance_count = 0

        if rebalance_days > 0 and len(portfolio_returns) > rebalance_days:
            rebalance_indices = list(range(rebalance_days, len(portfolio_returns), rebalance_days))
            rebalance_count = len(rebalance_indices)
            # Deduct cost at each rebalance by reducing return on that day
            for idx in rebalance_indices:
                if idx < len(portfolio_returns):
                    portfolio_returns.iloc[idx] -= rebalance_cost_per_event
                    cumulative_transaction_costs += rebalance_cost_per_event

        # Also add initial entry cost (full portfolio buy)
        if len(portfolio_returns) > 0:
            entry_cost = self.transaction_cost * num_positions
            portfolio_returns.iloc[0] -= entry_cost
            cumulative_transaction_costs += entry_cost

        # Benchmark returns
        benchmark_returns = {}
        for bench in self.benchmark_tickers:
            if bench in prices.columns:
                bench_prices = prices[bench]
                benchmark_returns[bench] = self.calculate_returns(bench_prices.to_frame())[bench]

        # Calculate cumulative returns
        portfolio_cumulative = (1 + portfolio_returns).cumprod()

        benchmark_cumulative = {}
        for bench, rets in benchmark_returns.items():
            benchmark_cumulative[bench] = (1 + rets).cumprod()

        # Calculate metrics
        total_days = len(portfolio_returns)
        total_return = (portfolio_cumulative.iloc[-1] - 1) * 100

        # Annualized return (assuming 252 trading days)
        years = total_days / 252
        annualized_return = ((1 + total_return/100) ** (1/years) - 1) * 100 if years > 0 else 0

        # Volatility (annualized)
        daily_vol = portfolio_returns.std()
        annualized_vol = daily_vol * np.sqrt(252) * 100

        # Sharpe Ratio (assuming 4% risk-free rate)
        risk_free_rate = 0.04
        sharpe_ratio = (annualized_return/100 - risk_free_rate) / (annualized_vol/100) if annualized_vol > 0 else 0

        # Sortino Ratio
        sortino = self.calculate_sortino_ratio(portfolio_returns, risk_free_rate)

        # Max Drawdown
        rolling_max = portfolio_cumulative.cummax()
        drawdown = (portfolio_cumulative - rolling_max) / rolling_max
        max_drawdown = drawdown.min() * 100

        # Win rate
        winning_days = (portfolio_returns > 0).sum()
        win_rate = (winning_days / total_days) * 100 if total_days > 0 else 0

        # Best and worst days
        best_day = portfolio_returns.max() * 100
        worst_day = portfolio_returns.min() * 100

        # Rolling Sharpe
        rolling_sharpe = self.calculate_rolling_sharpe(portfolio_returns)
        rolling_sharpe_values = rolling_sharpe.dropna()

        # Benchmark comparison
        benchmark_metrics = {}
        for bench, cum_ret in benchmark_cumulative.items():
            bench_total = (cum_ret.iloc[-1] - 1) * 100
            benchmark_metrics[bench] = {
                'total_return': round(bench_total, 2),
                'alpha': round(total_return - bench_total, 2)
            }

        results = {
            'period': {
                'start': start_date,
                'end': end_date,
                'trading_days': total_days,
                'years': round(years, 2)
            },
            'portfolio': {
                'stocks': available_picks,
                'num_stocks': len(available_picks),
                'strategy': 'Equal Weight',
                'rebalance_days': rebalance_days,
            },
            'returns': {
                'total_return': round(total_return, 2),
                'annualized_return': round(annualized_return, 2),
                'volatility': round(annualized_vol, 2),
                'sharpe_ratio': round(sharpe_ratio, 2),
                'sortino_ratio': round(sortino, 2),
                'max_drawdown': round(max_drawdown, 2),
                'win_rate': round(win_rate, 2),
                'best_day': round(best_day, 2),
                'worst_day': round(worst_day, 2)
            },
            'transaction_costs': {
                'cost_per_trade': self.transaction_cost,
                'rebalance_count': rebalance_count,
                'total_costs_pct': round(cumulative_transaction_costs * 100, 4),
                'total_costs_dollar': round(cumulative_transaction_costs * self.initial_capital, 2),
            },
            'rolling_metrics': {
                'rolling_sharpe_latest': round(float(rolling_sharpe_values.iloc[-1]), 2) if len(rolling_sharpe_values) > 0 else None,
                'rolling_sharpe_mean': round(float(rolling_sharpe_values.mean()), 2) if len(rolling_sharpe_values) > 0 else None,
                'rolling_sharpe_min': round(float(rolling_sharpe_values.min()), 2) if len(rolling_sharpe_values) > 0 else None,
                'rolling_sharpe_dates': [d.strftime('%Y-%m-%d') for d in rolling_sharpe_values.index[-60:]],
                'rolling_sharpe_values': [round(float(v), 2) for v in rolling_sharpe_values.values[-60:]],
            },
            'benchmarks': benchmark_metrics,
            'equity_curve': {
                'dates': [d.strftime('%Y-%m-%d') for d in portfolio_cumulative.index],
                'portfolio': [round(v * self.initial_capital, 2) for v in portfolio_cumulative.values],
                'benchmarks': {
                    bench: [round(v * self.initial_capital, 2) for v in cum.values]
                    for bench, cum in benchmark_cumulative.items()
                }
            }
        }

        return results

    def calculate_sortino_ratio(self, returns: pd.Series, risk_free_rate: float = 0.04) -> float:
        """Calculate Sortino ratio using proper downside deviation.

        Downside deviation = sqrt(mean(min(excess_return, 0)^2))
        NOT std() of negative returns (which drops zero/positive days and
        underestimates downside risk).
        """
        daily_rf = risk_free_rate / 252
        excess_returns = returns - daily_rf

        # Downside deviation: sqrt of mean of squared negative deviations
        downside = np.minimum(excess_returns, 0)
        downside_var = (downside ** 2).mean()
        if downside_var <= 0:
            return 0.0

        downside_dev = np.sqrt(downside_var) * np.sqrt(252)
        annualized_return = returns.mean() * 252

        return (annualized_return - risk_free_rate) / downside_dev

    def monte_carlo_simulation(
        self,
        returns: pd.Series,
        num_simulations: int = 1000,
        num_days: int = 252,
        initial_value: float = 100000,
        distribution: str = 'student_t'
    ) -> Dict:
        """
        Monte Carlo simulation for portfolio projection

        Args:
            returns: Historical daily returns
            num_simulations: Number of simulation paths
            num_days: Days to simulate (252 = 1 year)
            initial_value: Starting portfolio value
            distribution: 'normal' or 'student_t' (fat-tail)
        """
        if len(returns) < 20:
            return {'error': 'Insufficient return data'}

        mean_return = returns.mean()
        std_return = returns.std()

        np.random.seed(42)

        degrees_of_freedom = None

        if distribution == 'student_t':
            try:
                from scipy.stats import t as t_dist
                df_t, loc_t, scale_t = t_dist.fit(returns.dropna())
                degrees_of_freedom = round(df_t, 2)

                # Generate random walks using Student-t
                simulated_paths = []
                for _ in range(num_simulations):
                    daily_returns = t_dist.rvs(df_t, loc=loc_t, scale=scale_t, size=num_days)
                    price_path = initial_value * np.cumprod(1 + daily_returns)
                    simulated_paths.append(price_path)
            except ImportError:
                logger.warning("scipy not available, falling back to normal distribution")
                distribution = 'normal'

        if distribution == 'normal':
            simulated_paths = []
            for _ in range(num_simulations):
                daily_returns = np.random.normal(mean_return, std_return, num_days)
                price_path = initial_value * np.cumprod(1 + daily_returns)
                simulated_paths.append(price_path)

        simulated_paths = np.array(simulated_paths)
        final_values = simulated_paths[:, -1]

        return {
            'simulations': num_simulations,
            'days': num_days,
            'initial_value': initial_value,
            'distribution': distribution,
            'degrees_of_freedom': degrees_of_freedom,
            'median_final': round(np.median(final_values), 2),
            'mean_final': round(np.mean(final_values), 2),
            'percentile_5': round(np.percentile(final_values, 5), 2),
            'percentile_25': round(np.percentile(final_values, 25), 2),
            'percentile_75': round(np.percentile(final_values, 75), 2),
            'percentile_95': round(np.percentile(final_values, 95), 2),
            'prob_profit': round(np.mean(final_values > initial_value) * 100, 1),
            'prob_double': round(np.mean(final_values > initial_value * 2) * 100, 1),
            'prob_loss_20pct': round(np.mean(final_values < initial_value * 0.8) * 100, 1),
            'var_95': round(np.percentile(final_values, 5) - initial_value, 2)  # Value at Risk
        }

    def walk_forward_analysis(self, picks: List[str], start_date: str, end_date: str,
                               in_sample_days: int = 252, out_sample_days: int = 63) -> Dict:
        """
        Walk-forward optimization: train on in-sample, test on out-of-sample

        Args:
            picks: List of stock tickers
            start_date: Start date
            end_date: End date
            in_sample_days: In-sample window size (trading days)
            out_sample_days: Out-of-sample window size (trading days)

        Returns:
            Walk-forward results with robustness score
        """
        logger.info(f"📊 Running walk-forward analysis (IS={in_sample_days}, OOS={out_sample_days})...")

        all_tickers = list(set(picks + self.benchmark_tickers))
        prices = self.get_historical_prices(all_tickers, start_date, end_date)

        if prices.empty:
            return {'error': 'No price data'}

        available = [t for t in picks if t in prices.columns]
        if not available:
            return {'error': 'No valid tickers'}

        returns = prices[available].pct_change().dropna().mean(axis=1)

        window_size = in_sample_days + out_sample_days
        if len(returns) < window_size:
            return {'error': f'Insufficient data ({len(returns)} days < {window_size} needed)'}

        # Slide window
        is_sharpes = []
        oos_sharpes = []
        oos_returns_list = []

        step = out_sample_days
        for start_idx in range(0, len(returns) - window_size + 1, step):
            is_end = start_idx + in_sample_days
            oos_end = is_end + out_sample_days

            is_returns = returns.iloc[start_idx:is_end]
            oos_returns = returns.iloc[is_end:oos_end]

            # In-sample Sharpe
            is_sharpe = (is_returns.mean() * 252 - 0.04) / (is_returns.std() * np.sqrt(252)) if is_returns.std() > 0 else 0
            is_sharpes.append(is_sharpe)

            # Out-of-sample Sharpe
            oos_sharpe = (oos_returns.mean() * 252 - 0.04) / (oos_returns.std() * np.sqrt(252)) if oos_returns.std() > 0 else 0
            oos_sharpes.append(oos_sharpe)

            oos_total = (1 + oos_returns).prod() - 1
            oos_returns_list.append(oos_total * 100)

        if not is_sharpes:
            return {'error': 'No complete windows'}

        # Robustness: correlation between IS and OOS performance
        correlation = np.corrcoef(is_sharpes, oos_sharpes)[0, 1] if len(is_sharpes) > 1 else 0

        return {
            'windows': len(is_sharpes),
            'in_sample_days': in_sample_days,
            'out_sample_days': out_sample_days,
            'avg_is_sharpe': round(float(np.mean(is_sharpes)), 2),
            'avg_oos_sharpe': round(float(np.mean(oos_sharpes)), 2),
            'avg_oos_return': round(float(np.mean(oos_returns_list)), 2),
            'oos_win_rate': round(len([r for r in oos_returns_list if r > 0]) / len(oos_returns_list) * 100, 1),
            'robustness_score': round(float(correlation) * 100, 1),
            'degradation': round(float(np.mean(is_sharpes) - np.mean(oos_sharpes)), 2),
        }

    def print_results(self, results: Dict):
        """Print formatted backtest results"""
        if 'error' in results:
            print(f"❌ Error: {results['error']}")
            return

        print("\n" + "="*70)
        print("📊 BACKTEST RESULTS")
        print("="*70)

        # Period
        p = results['period']
        print(f"\n📅 Period: {p['start']} to {p['end']} ({p['trading_days']} days, {p['years']} years)")

        # Portfolio
        port = results['portfolio']
        print(f"\n📈 Portfolio: {port['num_stocks']} stocks ({port['strategy']})")
        print(f"   Stocks: {', '.join(port['stocks'][:5])}{'...' if len(port['stocks']) > 5 else ''}")

        # Returns
        r = results['returns']
        print(f"\n💰 Performance:")
        print(f"   Total Return:      {r['total_return']:+.2f}%")
        print(f"   Annualized Return: {r['annualized_return']:+.2f}%")
        print(f"   Volatility:        {r['volatility']:.2f}%")
        print(f"   Sharpe Ratio:      {r['sharpe_ratio']:.2f}")
        print(f"   Sortino Ratio:     {r['sortino_ratio']:.2f}")
        print(f"   Max Drawdown:      {r['max_drawdown']:.2f}%")
        print(f"   Win Rate:          {r['win_rate']:.1f}%")
        print(f"   Best Day:          {r['best_day']:+.2f}%")
        print(f"   Worst Day:         {r['worst_day']:+.2f}%")

        # Transaction costs
        tc = results.get('transaction_costs', {})
        if tc:
            print(f"\n💸 Transaction Costs:")
            print(f"   Cost per trade:    {tc.get('cost_per_trade', 0)*100:.2f}%")
            print(f"   Rebalance count:   {tc.get('rebalance_count', 0)}")
            print(f"   Total costs:       {tc.get('total_costs_pct', 0):.4f}% (${tc.get('total_costs_dollar', 0):,.2f})")

        # Rolling metrics
        rm = results.get('rolling_metrics', {})
        if rm and rm.get('rolling_sharpe_latest') is not None:
            print(f"\n📈 Rolling Sharpe (63d):")
            print(f"   Latest:            {rm['rolling_sharpe_latest']:.2f}")
            print(f"   Average:           {rm['rolling_sharpe_mean']:.2f}")
            print(f"   Minimum:           {rm['rolling_sharpe_min']:.2f}")

        # vs Benchmarks
        print(f"\n📊 vs Benchmarks:")
        for bench, metrics in results['benchmarks'].items():
            alpha_emoji = "🟢" if metrics['alpha'] > 0 else "🔴"
            print(f"   {bench}: {metrics['total_return']:+.2f}% | Alpha: {alpha_emoji} {metrics['alpha']:+.2f}%")

        # Final values
        eq = results['equity_curve']
        final_portfolio = eq['portfolio'][-1]
        print(f"\n💵 Final Value: ${final_portfolio:,.2f} (started: ${self.initial_capital:,.2f})")


class HistoricalPicksSimulator:
    """Simulate picking stocks based on our criteria at historical points"""

    def __init__(self):
        self.engine = BacktestEngine()

    def simulate_strategy(
        self,
        universe: List[str],  # Stock universe to pick from
        start_date: str,
        end_date: str,
        holding_period: int = 30,  # Days to hold each pick
        top_n: int = 10  # Number of stocks to pick
    ) -> Dict:
        """
        Simulate our stock picking strategy on historical data
        Using momentum + volume as proxy for smart money signals
        """
        logger.info("🔬 Running historical simulation...")

        # Get 1 year of data before start for indicators
        lookback_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=365)).strftime('%Y-%m-%d')

        prices = self.engine.get_historical_prices(universe, lookback_start, end_date)
        if prices.empty:
            return {'error': 'No price data'}

        # Get volume data
        try:
            volume_data = yf.download(universe, start=lookback_start, end=end_date, progress=False)['Volume']
        except:
            volume_data = None

        # Simulation period
        sim_start = datetime.strptime(start_date, '%Y-%m-%d')
        sim_end = datetime.strptime(end_date, '%Y-%m-%d')

        all_picks_returns = []
        all_benchmark_returns = []

        current_date = sim_start

        while current_date < sim_end:
            # Get historical data up to current date for stock selection
            hist_prices = prices[prices.index <= current_date].tail(60)  # Last 60 days

            if len(hist_prices) < 20:
                current_date += timedelta(days=holding_period)
                continue

            # Calculate signals for each stock
            scores = {}
            for ticker in universe:
                if ticker not in hist_prices.columns:
                    continue

                ticker_prices = hist_prices[ticker].dropna()
                if len(ticker_prices) < 20:
                    continue

                # Momentum (20-day return)
                momentum = (ticker_prices.iloc[-1] / ticker_prices.iloc[-20] - 1) * 100

                # Relative strength (vs mean)
                rs = (ticker_prices.iloc[-1] / ticker_prices.mean() - 1) * 100

                # Volume spike (if available)
                vol_score = 0
                if volume_data is not None and ticker in volume_data.columns:
                    vol = volume_data[ticker]
                    recent_vol = vol[vol.index <= current_date].tail(5).mean()
                    avg_vol = vol[vol.index <= current_date].tail(20).mean()
                    if avg_vol > 0:
                        vol_score = (recent_vol / avg_vol - 1) * 100

                # Combined score (similar to our smart money logic)
                score = momentum * 0.4 + rs * 0.3 + vol_score * 0.3
                scores[ticker] = score

            # Pick top N stocks
            sorted_picks = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
            picks = [t[0] for t in sorted_picks]

            if not picks:
                current_date += timedelta(days=holding_period)
                continue

            # Calculate returns for holding period
            hold_end = min(current_date + timedelta(days=holding_period), sim_end)

            period_prices = prices[(prices.index > current_date) & (prices.index <= hold_end)]

            if len(period_prices) > 0:
                for pick in picks:
                    if pick in period_prices.columns:
                        start_price = prices[pick][prices.index <= current_date].iloc[-1]
                        end_price = period_prices[pick].iloc[-1]
                        ret = (end_price / start_price - 1) * 100
                        all_picks_returns.append(ret)

                # Benchmark (SPY)
                if 'SPY' in period_prices.columns:
                    start_spy = prices['SPY'][prices.index <= current_date].iloc[-1]
                    end_spy = period_prices['SPY'].iloc[-1]
                    spy_ret = (end_spy / start_spy - 1) * 100
                    all_benchmark_returns.append(spy_ret)

            current_date += timedelta(days=holding_period)

        # Aggregate results
        if not all_picks_returns:
            return {'error': 'No trades executed'}

        avg_return = np.mean(all_picks_returns)
        # Use average per-period return compounded across periods (not across
        # individual overlapping trades, which double-counts concurrent positions)
        num_periods = len(all_benchmark_returns) if all_benchmark_returns else max(1, len(all_picks_returns) // top_n)
        period_returns = []
        for i in range(0, len(all_picks_returns), max(1, top_n)):
            chunk = all_picks_returns[i:i + top_n]
            period_returns.append(np.mean(chunk))
        total_return = np.prod([1 + r / 100 for r in period_returns]) - 1
        win_count = len([r for r in all_picks_returns if r > 0])
        win_rate = win_count / len(all_picks_returns) * 100

        avg_benchmark = np.mean(all_benchmark_returns) if all_benchmark_returns else 0

        return {
            'simulation': {
                'start': start_date,
                'end': end_date,
                'holding_period': holding_period,
                'top_n': top_n,
                'total_trades': len(all_picks_returns)
            },
            'performance': {
                'avg_trade_return': round(avg_return, 2),
                'total_return': round(total_return * 100, 2),
                'win_rate': round(win_rate, 1),
                'best_trade': round(max(all_picks_returns), 2),
                'worst_trade': round(min(all_picks_returns), 2)
            },
            'vs_benchmark': {
                'SPY_avg_return': round(avg_benchmark, 2),
                'alpha': round(avg_return - avg_benchmark, 2)
            }
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Backtest Trading Strategy')
    parser.add_argument('--mode', choices=['simple', 'simulate', 'walkforward'], default='simple')
    parser.add_argument('--start', default='2023-01-01', help='Start date')
    parser.add_argument('--end', default='2024-12-01', help='End date')
    parser.add_argument('--stocks', nargs='+', default=['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'AMZN'])
    parser.add_argument('--cost', type=float, default=0.001, help='Transaction cost (0.001 = 0.1%)')
    args = parser.parse_args()

    if args.mode == 'simple':
        # Simple backtest with given stocks
        engine = BacktestEngine(initial_capital=100000, transaction_cost=args.cost)
        results = engine.run_equal_weight_backtest(
            picks=args.stocks,
            start_date=args.start,
            end_date=args.end
        )
        engine.print_results(results)

        # Monte Carlo
        if 'error' not in results:
            all_tickers = list(set(args.stocks + ['SPY', 'QQQ']))
            prices = engine.get_historical_prices(all_tickers, args.start, args.end)
            if not prices.empty:
                available = [t for t in args.stocks if t in prices.columns]
                returns = prices[available].pct_change().dropna().mean(axis=1)
                mc_results = engine.monte_carlo_simulation(returns, distribution='student_t')
                if 'error' not in mc_results:
                    print(f"\n🎲 Monte Carlo ({mc_results['distribution']}, df={mc_results.get('degrees_of_freedom', 'N/A')}):")
                    print(f"   Median: ${mc_results['median_final']:,.2f}")
                    print(f"   5th percentile: ${mc_results['percentile_5']:,.2f}")
                    print(f"   95th percentile: ${mc_results['percentile_95']:,.2f}")
                    print(f"   P(Profit): {mc_results['prob_profit']}%")
                    print(f"   P(Loss >20%): {mc_results['prob_loss_20pct']}%")

        # Save results
        with open('backtest_results.json', 'w') as f:
            results_save = {k: v for k, v in results.items() if k != 'equity_curve'}
            json.dump(results_save, f, indent=2)
        print("\n✅ Results saved to backtest_results.json")

    elif args.mode == 'walkforward':
        engine = BacktestEngine(initial_capital=100000, transaction_cost=args.cost)
        wf_results = engine.walk_forward_analysis(
            picks=args.stocks,
            start_date=args.start,
            end_date=args.end
        )
        print("\n" + "=" * 70)
        print("📊 WALK-FORWARD ANALYSIS")
        print("=" * 70)
        if 'error' in wf_results:
            print(f"❌ {wf_results['error']}")
        else:
            print(f"   Windows: {wf_results['windows']}")
            print(f"   IS Sharpe (avg): {wf_results['avg_is_sharpe']:.2f}")
            print(f"   OOS Sharpe (avg): {wf_results['avg_oos_sharpe']:.2f}")
            print(f"   OOS Return (avg): {wf_results['avg_oos_return']:+.2f}%")
            print(f"   OOS Win Rate: {wf_results['oos_win_rate']}%")
            print(f"   Robustness Score: {wf_results['robustness_score']:.1f}%")
            print(f"   IS→OOS Degradation: {wf_results['degradation']:.2f}")

    else:
        # Simulate strategy
        universe = [
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'UNH', 'JNJ',
            'JPM', 'V', 'PG', 'MA', 'HD', 'CVX', 'MRK', 'ABBV', 'PEP', 'KO',
            'COST', 'AVGO', 'LLY', 'WMT', 'MCD', 'CSCO', 'ACN', 'TMO', 'ABT', 'DHR',
            'SPY'  # Include SPY for benchmark
        ]

        simulator = HistoricalPicksSimulator()
        results = simulator.simulate_strategy(
            universe=universe,
            start_date=args.start,
            end_date=args.end,
            holding_period=30,
            top_n=10
        )

        print("\n" + "="*70)
        print("🔬 STRATEGY SIMULATION RESULTS")
        print("="*70)

        if 'error' in results:
            print(f"❌ Error: {results['error']}")
        else:
            sim = results['simulation']
            perf = results['performance']
            bench = results['vs_benchmark']

            print(f"\n📅 Period: {sim['start']} to {sim['end']}")
            print(f"📊 Strategy: Top {sim['top_n']} momentum stocks, {sim['holding_period']}-day holding")
            print(f"🔄 Total trades: {sim['total_trades']}")

            print(f"\n💰 Performance:")
            print(f"   Avg Trade Return: {perf['avg_trade_return']:+.2f}%")
            print(f"   Total Return:     {perf['total_return']:+.2f}%")
            print(f"   Win Rate:         {perf['win_rate']:.1f}%")
            print(f"   Best Trade:       {perf['best_trade']:+.2f}%")
            print(f"   Worst Trade:      {perf['worst_trade']:+.2f}%")

            alpha_emoji = "🟢" if bench['alpha'] > 0 else "🔴"
            print(f"\n📊 vs SPY:")
            print(f"   SPY Avg Return:   {bench['SPY_avg_return']:+.2f}%")
            print(f"   Alpha:            {alpha_emoji} {bench['alpha']:+.2f}%")


if __name__ == "__main__":
    main()
