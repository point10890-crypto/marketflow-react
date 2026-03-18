#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto Risk Analysis System v1.0

Features:
- Historical VaR(95%) and CVaR(95%) for top 15 crypto assets
- Correlation matrix across coins
- Market concentration analysis (BTC dominance, top-3 weight)
- Alert generation for drawdowns, volatility spikes, high correlation
- Equal-weight portfolio risk metrics

Usage:
    python3 crypto_risk.py
"""

import os
import json
import logging
import numpy as np
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CryptoRiskAnalyzer:
    """Portfolio risk monitoring and alerting for crypto assets"""

    COIN_TICKERS = [
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD',
        'ADA-USD', 'DOGE-USD', 'AVAX-USD', 'DOT-USD', 'LINK-USD',
        'POL-USD', 'ATOM-USD', 'LTC-USD', 'NEAR-USD', 'SUI-USD',
    ]

    COIN_LABELS = {
        'BTC-USD': 'BTC', 'ETH-USD': 'ETH', 'SOL-USD': 'SOL',
        'BNB-USD': 'BNB', 'XRP-USD': 'XRP', 'ADA-USD': 'ADA',
        'DOGE-USD': 'DOGE', 'AVAX-USD': 'AVAX', 'DOT-USD': 'DOT',
        'LINK-USD': 'LINK', 'POL-USD': 'POL',
        'ATOM-USD': 'ATOM', 'LTC-USD': 'LTC', 'NEAR-USD': 'NEAR',
        'SUI-USD': 'SUI',
    }

    # Alert thresholds
    DRAWDOWN_WARNING_PCT = -10.0
    VOLATILITY_WARNING_ANNUALIZED = 80.0
    CORRELATION_HIGH_THRESHOLD = 0.90

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_dir = os.path.join(data_dir, 'output')
        self.output_file = os.path.join(self.output_dir, 'crypto_risk.json')

    # ------------------------------------------------------------------
    # Data Fetching
    # ------------------------------------------------------------------

    def fetch_price_data(self, period_days: int = 90) -> pd.DataFrame:
        """Download 90d daily close prices for top 15 coins via yfinance"""
        logger.info(f"Fetching {period_days}d price data for {len(self.COIN_TICKERS)} coins...")

        start_date = (datetime.now() - timedelta(days=period_days + 10)).strftime('%Y-%m-%d')

        try:
            data = yf.download(
                self.COIN_TICKERS,
                start=start_date,
                progress=False,
            )['Close']

            if data.empty:
                logger.error("No data returned from yfinance")
                return pd.DataFrame()

            # Rename columns to short labels
            data = data.rename(columns=self.COIN_LABELS)
            # Drop columns that are all NaN (delisted coins)
            data = data.dropna(axis=1, how='all')
            logger.info(f"Fetched data: {len(data)} rows, {len(data.columns)} coins")
            return data

        except Exception as e:
            logger.error(f"Error fetching price data: {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # VaR / CVaR Calculation
    # ------------------------------------------------------------------

    def calculate_var(self, data: pd.DataFrame, confidence: float = 0.95) -> Dict:
        """Historical VaR(95%) and CVaR(95%) for each coin and equal-weight portfolio"""
        logger.info(f"Calculating VaR/CVaR at {confidence*100:.0f}% confidence...")

        returns = data.pct_change(fill_method=None)
        # Drop only rows where ALL values are NaN (not ANY)
        returns = returns.dropna(how='all')
        if returns.empty or len(returns) < 5:
            return {}

        individual_risk = {}
        available_coins = [c for c in returns.columns if returns[c].notna().sum() > 10]

        for coin in available_coins:
            coin_returns = returns[coin].dropna()
            if len(coin_returns) < 5:
                continue

            var_pct = float(np.percentile(coin_returns, (1 - confidence) * 100))
            tail = coin_returns[coin_returns <= var_pct]
            cvar_pct = float(tail.mean()) if len(tail) > 0 else var_pct

            # Max drawdown over last 30 days
            prices_30d = data[coin].dropna().iloc[-30:]
            if len(prices_30d) > 1:
                rolling_max = prices_30d.cummax()
                dd_series = (prices_30d - rolling_max) / rolling_max * 100
                max_dd_30d = float(dd_series.min())
            else:
                max_dd_30d = 0.0

            # 30-day annualized volatility
            recent_returns = coin_returns.iloc[-30:] if len(coin_returns) >= 30 else coin_returns
            vol_30d = float(recent_returns.std() * np.sqrt(365) * 100)  # crypto trades 365d

            individual_risk[coin] = {
                'var_95_1d': round(var_pct * 100, 2),
                'cvar_95_1d': round(cvar_pct * 100, 2),
                'max_dd_30d': round(max_dd_30d, 2),
                'volatility_30d': round(vol_30d, 2),
            }

        # Equal-weight portfolio
        portfolio_returns = returns[available_coins].mean(axis=1)
        if len(portfolio_returns) > 5:
            port_var = float(np.percentile(portfolio_returns, (1 - confidence) * 100))
            port_tail = portfolio_returns[portfolio_returns <= port_var]
            port_cvar = float(port_tail.mean()) if len(port_tail) > 0 else port_var
        else:
            port_var = 0
            port_cvar = 0

        return {
            'individual_risk': individual_risk,
            'portfolio_var_95_1d': round(port_var * 100, 2),
            'portfolio_cvar_95_1d': round(port_cvar * 100, 2),
        }

    # ------------------------------------------------------------------
    # Correlation Matrix
    # ------------------------------------------------------------------

    def calculate_correlation_matrix(self, data: pd.DataFrame) -> Dict:
        """Pairwise correlation matrix from daily returns"""
        logger.info("Calculating correlation matrix...")

        returns = data.pct_change(fill_method=None).dropna(how='all')
        available = [c for c in returns.columns if returns[c].notna().sum() > 10]

        if len(available) < 2:
            return {'coins': [], 'values': []}

        returns_clean = returns[available].dropna(how='any')
        if len(returns_clean) < 10:
            return {'coins': [], 'values': []}

        corr_matrix = np.corrcoef(returns_clean.values, rowvar=False)

        return {
            'coins': available,
            'values': [[round(float(v), 4) for v in row] for row in corr_matrix],
        }

    # ------------------------------------------------------------------
    # Concentration Analysis
    # ------------------------------------------------------------------

    def calculate_concentration(self) -> Dict:
        """BTC market cap / total market cap, top-3 weight via CoinGecko"""
        logger.info("Calculating market concentration...")

        try:
            resp = requests.get(
                'https://api.coingecko.com/api/v3/global',
                timeout=5,
            )
            resp.raise_for_status()
            global_data = resp.json().get('data', {})

            total_market_cap = global_data.get('total_market_cap', {}).get('usd', 0)
            market_cap_pcts = global_data.get('market_cap_percentage', {})

            btc_weight = market_cap_pcts.get('btc', 0)
            eth_weight = market_cap_pcts.get('eth', 0)

            # Top-3: BTC + ETH + next largest
            sorted_caps = sorted(market_cap_pcts.items(), key=lambda x: x[1], reverse=True)
            top3_weight = sum(v for _, v in sorted_caps[:3])
            top3_coins = [k.upper() for k, _ in sorted_caps[:3]]

            warnings = []
            if btc_weight > 50:
                warnings.append(f"BTC dominance very high at {btc_weight:.1f}% - market heavily concentrated")
            if top3_weight > 75:
                warnings.append(f"Top 3 coins ({', '.join(top3_coins)}) hold {top3_weight:.1f}% of total market cap")

            return {
                'btc_weight_pct': round(btc_weight, 2),
                'eth_weight_pct': round(eth_weight, 2),
                'top3_weight_pct': round(top3_weight, 2),
                'top3_coins': top3_coins,
                'total_market_cap_usd': round(total_market_cap, 0),
                'warnings': warnings,
            }
        except Exception as e:
            logger.error(f"Failed to calculate concentration: {e}")
            return {
                'btc_weight_pct': 0,
                'eth_weight_pct': 0,
                'top3_weight_pct': 0,
                'top3_coins': [],
                'total_market_cap_usd': 0,
                'warnings': ['Could not fetch market cap data from CoinGecko'],
            }

    # ------------------------------------------------------------------
    # Alert Generation
    # ------------------------------------------------------------------

    def generate_alerts(self, var_data: Dict, corr_data: Dict, data: pd.DataFrame) -> List[Dict]:
        """Check for drawdowns >-10%, volatility >80% ann., high correlation warnings"""
        logger.info("Generating risk alerts...")
        alerts = []

        individual = var_data.get('individual_risk', {})

        for coin, metrics in individual.items():
            # Drawdown alerts
            dd = metrics.get('max_dd_30d', 0)
            if dd <= self.DRAWDOWN_WARNING_PCT:
                severity = 'critical' if dd <= self.DRAWDOWN_WARNING_PCT * 2 else 'warning'
                alerts.append({
                    'severity': severity,
                    'alert_type': 'drawdown',
                    'coin': coin,
                    'message': f"{coin} 30d max drawdown: {dd:.1f}%",
                    'value': dd,
                })

            # Volatility alerts
            vol = metrics.get('volatility_30d', 0)
            if vol > self.VOLATILITY_WARNING_ANNUALIZED:
                severity = 'critical' if vol > self.VOLATILITY_WARNING_ANNUALIZED * 1.5 else 'warning'
                alerts.append({
                    'severity': severity,
                    'alert_type': 'volatility',
                    'coin': coin,
                    'message': f"{coin} annualized volatility: {vol:.1f}% (threshold: {self.VOLATILITY_WARNING_ANNUALIZED}%)",
                    'value': vol,
                })

        # High correlation warnings
        coins = corr_data.get('coins', [])
        values = corr_data.get('values', [])

        for i in range(len(coins)):
            for j in range(i + 1, len(coins)):
                if i < len(values) and j < len(values[i]):
                    corr_val = values[i][j]
                    if corr_val > self.CORRELATION_HIGH_THRESHOLD:
                        alerts.append({
                            'severity': 'info',
                            'alert_type': 'correlation',
                            'coin': f"{coins[i]}/{coins[j]}",
                            'message': f"High correlation ({corr_val:.2f}) between {coins[i]} and {coins[j]} - limited diversification",
                            'value': corr_val,
                        })

        # Portfolio-level VaR alert
        port_var = var_data.get('portfolio_var_95_1d', 0)
        if port_var < -5:  # More than 5% daily VaR
            alerts.append({
                'severity': 'warning',
                'alert_type': 'portfolio_var',
                'coin': 'PORTFOLIO',
                'message': f"Portfolio 1-day VaR(95%): {port_var:.1f}% - elevated risk",
                'value': port_var,
            })

        # Sort by severity
        severity_order = {'critical': 0, 'warning': 1, 'info': 2}
        alerts.sort(key=lambda x: severity_order.get(x['severity'], 3))

        return alerts

    # ------------------------------------------------------------------
    # Risk Level Assessment
    # ------------------------------------------------------------------

    def _determine_risk_level(self, alerts: List[Dict], var_data: Dict) -> str:
        """Determine overall risk level from alerts and portfolio VaR"""
        critical_count = sum(1 for a in alerts if a['severity'] == 'critical')
        warning_count = sum(1 for a in alerts if a['severity'] == 'warning')
        port_var = abs(var_data.get('portfolio_var_95_1d', 0))

        if critical_count >= 3 or port_var > 8:
            return 'CRITICAL'
        elif critical_count >= 1 or warning_count >= 3 or port_var > 5:
            return 'HIGH'
        elif warning_count >= 1 or port_var > 3:
            return 'MODERATE'
        else:
            return 'LOW'

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self) -> Dict:
        """Full pipeline: fetch data -> calculate metrics -> generate alerts -> save"""
        logger.info("Starting crypto risk analysis...")

        # 1. Fetch price data
        data = self.fetch_price_data(period_days=90)

        if data.empty:
            logger.warning("No price data available")
            result = {
                'timestamp': datetime.now().isoformat(),
                'portfolio_summary': {
                    'total_coins': 0,
                    'portfolio_var_95_1d': 0,
                    'portfolio_cvar_95_1d': 0,
                    'risk_level': 'NO_DATA',
                },
                'correlation_matrix': {'coins': [], 'values': []},
                'individual_risk': {},
                'concentration': {},
                'alerts': [],
            }
            os.makedirs(self.output_dir, exist_ok=True)
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            return result

        # 2. Calculate VaR / CVaR
        var_data = self.calculate_var(data)

        # 3. Correlation matrix
        corr_data = self.calculate_correlation_matrix(data)

        # 4. Concentration
        concentration = self.calculate_concentration()

        # 5. Generate alerts
        alerts = self.generate_alerts(var_data, corr_data, data)

        # 6. Determine risk level
        risk_level = self._determine_risk_level(alerts, var_data)

        available_coins = list(var_data.get('individual_risk', {}).keys())

        result = {
            'timestamp': datetime.now().isoformat(),
            'portfolio_summary': {
                'total_coins': len(available_coins),
                'portfolio_var_95_1d': var_data.get('portfolio_var_95_1d', 0),
                'portfolio_cvar_95_1d': var_data.get('portfolio_cvar_95_1d', 0),
                'risk_level': risk_level,
            },
            'correlation_matrix': corr_data,
            'individual_risk': var_data.get('individual_risk', {}),
            'concentration': concentration,
            'alerts': alerts,
        }

        # Save
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved crypto risk analysis to {self.output_file}")
        logger.info(f"Risk Level: {risk_level} | Alerts: {len(alerts)} "
                     f"(Critical: {sum(1 for a in alerts if a['severity'] == 'critical')}, "
                     f"Warning: {sum(1 for a in alerts if a['severity'] == 'warning')})")

        return result


if __name__ == '__main__':
    analyzer = CryptoRiskAnalyzer(
        data_dir=os.path.dirname(os.path.abspath(__file__))
    )
    result = analyzer.run()

    print("\n" + "=" * 60)
    print("CRYPTO RISK ANALYSIS REPORT")
    print("=" * 60)

    summary = result.get('portfolio_summary', {})
    print(f"\nPortfolio Risk Level: {summary.get('risk_level', 'Unknown')}")
    print(f"Total Coins Analyzed: {summary.get('total_coins', 0)}")
    print(f"Portfolio VaR(95%, 1d):  {summary.get('portfolio_var_95_1d', 0):.2f}%")
    print(f"Portfolio CVaR(95%, 1d): {summary.get('portfolio_cvar_95_1d', 0):.2f}%")

    # Individual risk
    individual = result.get('individual_risk', {})
    if individual:
        print(f"\nIndividual Coin Risk:")
        print(f"  {'Coin':6} {'VaR(95%)':>10} {'CVaR':>10} {'MaxDD30d':>10} {'Vol30d':>10}")
        print(f"  {'-'*46}")
        for coin, m in sorted(individual.items(), key=lambda x: x[1].get('var_95_1d', 0)):
            print(f"  {coin:6} {m['var_95_1d']:>9.2f}% {m['cvar_95_1d']:>9.2f}% {m['max_dd_30d']:>9.2f}% {m['volatility_30d']:>9.1f}%")

    # Concentration
    conc = result.get('concentration', {})
    if conc:
        print(f"\nMarket Concentration:")
        print(f"  BTC Weight:  {conc.get('btc_weight_pct', 0):.1f}%")
        print(f"  Top-3 Weight: {conc.get('top3_weight_pct', 0):.1f}% ({', '.join(conc.get('top3_coins', []))})")

    # Alerts
    alerts = result.get('alerts', [])
    if alerts:
        print(f"\nActive Alerts ({len(alerts)}):")
        for alert in alerts[:15]:
            icon = '[CRITICAL]' if alert['severity'] == 'critical' else '[WARNING]' if alert['severity'] == 'warning' else '[INFO]'
            print(f"  {icon:12} {alert['message']}")
    else:
        print(f"\nNo active risk alerts")
