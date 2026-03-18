#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drawdown & Risk Alert System v1.0
- Real-time risk monitoring for smart money picks
- Configurable drawdown, stop-loss, concentration alerts
- VaR and CVaR (Expected Shortfall) calculation
"""

import os
import json
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RiskAlertSystem:
    """Portfolio risk monitoring and alerting"""

    DEFAULT_THRESHOLDS = {
        'max_drawdown_warning': -10.0,
        'max_drawdown_critical': -20.0,
        'stop_loss_default': -8.0,
        'concentration_threshold': 0.80,
        'var_confidence': 0.95,
    }

    SECTOR_MAP = {
        'XLK': 'Technology', 'XLF': 'Financials', 'XLV': 'Healthcare',
        'XLY': 'Consumer Disc.', 'XLP': 'Consumer Staples', 'XLE': 'Energy',
        'XLI': 'Industrials', 'XLB': 'Materials', 'XLRE': 'Real Estate',
        'XLU': 'Utilities', 'XLC': 'Comm. Services',
    }

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'risk_alerts.json')
        # Instance copy of thresholds — overridden by regime config if available
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        self._load_regime_config()

    def _load_regime_config(self):
        """Load adaptive thresholds from regime_config.json if available"""
        config_path = os.path.join(self.data_dir, 'output', 'regime_config.json')
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                ra_cfg = config.get('risk_alert', {})
                for key in self.thresholds:
                    if key in ra_cfg:
                        self.thresholds[key] = ra_cfg[key]
                if ra_cfg:
                    logger.info("📋 Loaded regime config for risk_alert")
        except Exception:
            pass  # Use defaults

    def load_picks(self) -> List[Dict]:
        """Read from output/smart_money_picks_v2.csv"""
        csv_path = os.path.join(self.data_dir, 'output', 'smart_money_picks_v2.csv')
        if not os.path.exists(csv_path):
            csv_path = os.path.join(self.data_dir, 'output', 'smart_money_picks.csv')

        if not os.path.exists(csv_path):
            logger.warning("No smart money picks found")
            return []

        try:
            df = pd.read_csv(csv_path)
            picks = []
            for _, row in df.head(15).iterrows():
                picks.append({
                    'ticker': row['ticker'],
                    'name': row.get('name', row['ticker']),
                    'entry_price': float(row.get('current_price', 0)),
                    'sector': str(row.get('sector', 'Unknown')),
                })
            return picks
        except Exception as e:
            logger.error(f"Error loading picks: {e}")
            return []

    def calculate_drawdowns(self, tickers: List[str], period: str = '3mo') -> Dict:
        """Current drawdown from peak for each ticker"""
        logger.info(f"📉 Calculating drawdowns for {len(tickers)} tickers...")

        if not tickers:
            return {}

        try:
            data = yf.download(tickers, period=period, progress=False)['Close']
            if isinstance(data, pd.Series):
                data = data.to_frame(name=tickers[0])

            drawdowns = {}
            for ticker in tickers:
                if ticker not in data.columns:
                    continue

                prices = data[ticker].dropna()
                if len(prices) < 2:
                    continue

                current_price = prices.iloc[-1]
                peak_price = prices.max()
                current_dd = ((current_price / peak_price) - 1) * 100

                # Rolling max drawdown
                rolling_max = prices.cummax()
                dd_series = (prices - rolling_max) / rolling_max * 100
                max_dd = dd_series.min()

                drawdowns[ticker] = {
                    'current_price': round(float(current_price), 2),
                    'peak_price': round(float(peak_price), 2),
                    'current_dd': round(float(current_dd), 2),
                    'max_dd': round(float(max_dd), 2),
                    'from_peak_days': int((prices.index[-1] - prices.idxmax()).days),
                }

            return drawdowns

        except Exception as e:
            logger.error(f"Error calculating drawdowns: {e}")
            return {}

    def calculate_portfolio_var(self, tickers: List[str], confidence: float = 0.95,
                                 horizon_days: int = 5, portfolio_value: float = 100000) -> Dict:
        """Historical VaR and CVaR (Expected Shortfall)"""
        logger.info(f"📊 Calculating VaR/CVaR (confidence={confidence}, horizon={horizon_days}d)...")

        if not tickers:
            return {}

        try:
            data = yf.download(tickers, period='6mo', progress=False)['Close']
            if isinstance(data, pd.Series):
                data = data.to_frame(name=tickers[0])

            # Equal weight portfolio returns
            returns = data.pct_change().dropna()
            available = [t for t in tickers if t in returns.columns]

            if not available:
                return {}

            portfolio_returns = returns[available].mean(axis=1)

            # Use rolling N-day returns for proper horizon scaling
            # (sqrt(T) applies to volatility, not individual returns)
            if horizon_days > 1 and len(portfolio_returns) > horizon_days:
                horizon_returns = portfolio_returns.rolling(horizon_days).sum().dropna()
            else:
                horizon_returns = portfolio_returns

            if len(horizon_returns) < 5:
                return {}

            # Historical VaR
            var_pct = np.percentile(horizon_returns, (1 - confidence) * 100)
            var_dollar = var_pct * portfolio_value

            # CVaR (Expected Shortfall) - average of losses beyond VaR
            tail_returns = horizon_returns[horizon_returns <= var_pct]
            cvar_pct = tail_returns.mean() if len(tail_returns) > 0 else var_pct
            cvar_dollar = cvar_pct * portfolio_value

            # Try Student-t fit for fat-tail accuracy
            degrees_of_freedom = None
            t_var_dollar = var_dollar
            try:
                from scipy.stats import t as t_dist
                params = t_dist.fit(horizon_returns.dropna())
                degrees_of_freedom = round(params[0], 2)
                # Student-t parametric VaR at same horizon
                t_var = t_dist.ppf(1 - confidence, *params)
                t_var_dollar = t_var * portfolio_value
            except ImportError:
                pass

            return {
                'var_pct': round(float(var_pct) * 100, 2),
                'var_dollar': round(float(var_dollar), 2),
                'cvar_pct': round(float(cvar_pct) * 100, 2),
                'cvar_dollar': round(float(cvar_dollar), 2),
                't_var_dollar': round(float(t_var_dollar), 2),
                'confidence': confidence,
                'horizon_days': horizon_days,
                'degrees_of_freedom': degrees_of_freedom,
            }

        except Exception as e:
            logger.error(f"Error calculating VaR: {e}")
            return {}

    def check_stop_losses(self, picks: List[Dict], threshold: float = None) -> List[Dict]:
        """Check if any pick breached stop-loss from recommendation price"""
        if threshold is None:
            threshold = self.thresholds['stop_loss_default']
        logger.info(f"🛑 Checking stop-losses (threshold={threshold}%)...")

        breached = []
        tickers = [p['ticker'] for p in picks if p.get('entry_price', 0) > 0]

        if not tickers:
            return []

        try:
            data = yf.download(tickers, period='1d', progress=False)['Close']
            if isinstance(data, pd.Series):
                data = data.to_frame(name=tickers[0])

            for pick in picks:
                ticker = pick['ticker']
                entry = pick.get('entry_price', 0)

                if entry <= 0 or ticker not in data.columns:
                    continue

                current = float(data[ticker].iloc[-1])
                change_pct = ((current / entry) - 1) * 100

                if change_pct <= threshold:
                    breached.append({
                        'ticker': ticker,
                        'name': pick.get('name', ticker),
                        'entry_price': round(entry, 2),
                        'current_price': round(current, 2),
                        'change_pct': round(change_pct, 2),
                        'threshold': threshold,
                    })

        except Exception as e:
            logger.error(f"Error checking stop-losses: {e}")

        return breached

    def analyze_concentration_risk(self, picks: List[Dict]) -> Dict:
        """Analyze sector concentration and correlation risk"""
        logger.info("⚖️  Analyzing concentration risk...")

        # Sector concentration
        sector_counts = {}
        for pick in picks:
            sector = pick.get('sector', 'Unknown')
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        total = len(picks) if picks else 1
        sector_concentration = {
            sector: {
                'count': count,
                'weight_pct': round(count / total * 100, 1),
            }
            for sector, count in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)
        }

        # Check for over-concentration (>40% in one sector)
        warnings = []
        for sector, info in sector_concentration.items():
            if info['weight_pct'] > 40:
                warnings.append(f"{sector} sector concentration at {info['weight_pct']}%")

        # Correlation check (reuse logic from portfolio_risk.py)
        tickers = [p['ticker'] for p in picks]
        high_correlation_pairs = []

        try:
            if len(tickers) >= 2:
                data = yf.download(tickers, period='3mo', progress=False)['Close']
                if not data.empty:
                    returns = data.pct_change().dropna()
                    corr = returns.corr()

                    cols = corr.columns
                    for i in range(len(cols)):
                        for j in range(i + 1, len(cols)):
                            val = corr.iloc[i, j]
                            if val > 0.80:
                                high_correlation_pairs.append({
                                    'pair': [cols[i], cols[j]],
                                    'correlation': round(float(val), 2),
                                })
        except Exception as e:
            logger.debug(f"Correlation check error: {e}")

        return {
            'sector_concentration': sector_concentration,
            'concentration_warnings': warnings,
            'high_correlation_pairs': high_correlation_pairs,
        }

    def generate_alerts(self, picks: List[Dict], drawdowns: Dict,
                        stop_losses: List[Dict], concentration: Dict,
                        var_info: Dict) -> List[Dict]:
        """Run all checks, return prioritized alerts by severity"""
        alerts = []

        # Drawdown alerts
        for ticker, dd in drawdowns.items():
            if dd['current_dd'] <= self.thresholds['max_drawdown_critical']:
                alerts.append({
                    'alert_type': 'drawdown',
                    'severity': 'critical',
                    'ticker': ticker,
                    'message': f"{ticker} is in critical drawdown: {dd['current_dd']:.1f}% from peak",
                    'value': dd['current_dd'],
                    'threshold': self.thresholds['max_drawdown_critical'],
                })
            elif dd['current_dd'] <= self.thresholds['max_drawdown_warning']:
                alerts.append({
                    'alert_type': 'drawdown',
                    'severity': 'warning',
                    'ticker': ticker,
                    'message': f"{ticker} drawdown warning: {dd['current_dd']:.1f}% from peak",
                    'value': dd['current_dd'],
                    'threshold': self.thresholds['max_drawdown_warning'],
                })

        # Stop-loss alerts
        for sl in stop_losses:
            alerts.append({
                'alert_type': 'stop_loss',
                'severity': 'critical',
                'ticker': sl['ticker'],
                'message': f"{sl['ticker']} breached stop-loss: {sl['change_pct']:.1f}% from entry",
                'value': sl['change_pct'],
                'threshold': sl['threshold'],
            })

        # Concentration alerts
        for warning in concentration.get('concentration_warnings', []):
            alerts.append({
                'alert_type': 'concentration',
                'severity': 'warning',
                'ticker': None,
                'message': warning,
                'value': None,
                'threshold': 40.0,
            })

        # High correlation alerts
        for pair in concentration.get('high_correlation_pairs', []):
            alerts.append({
                'alert_type': 'correlation',
                'severity': 'info',
                'ticker': f"{pair['pair'][0]}/{pair['pair'][1]}",
                'message': f"High correlation ({pair['correlation']}) between {pair['pair'][0]} and {pair['pair'][1]}",
                'value': pair['correlation'],
                'threshold': 0.80,
            })

        # Sort by severity
        severity_order = {'critical': 0, 'warning': 1, 'info': 2}
        alerts.sort(key=lambda x: severity_order.get(x['severity'], 3))

        return alerts

    def run_analysis(self) -> Dict:
        """Full pipeline, saves to output/risk_alerts.json"""
        logger.info("🚨 Starting risk alert analysis...")

        picks = self.load_picks()
        if not picks:
            logger.warning("No picks to analyze")
            result = {
                'timestamp': datetime.now().isoformat(),
                'portfolio_summary': {
                    'total_picks': 0,
                    'portfolio_var_95_5d': 0,
                    'portfolio_cvar_95_5d': 0,
                    'risk_level': 'No Data',
                    'var_details': {},
                },
                'drawdowns': {},
                'concentration': {'sector_concentration': {}, 'concentration_warnings': [], 'high_correlation_pairs': []},
                'alerts': [],
            }
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Saved empty risk alerts to {self.output_file}")
            return result

        tickers = [p['ticker'] for p in picks]

        drawdowns = self.calculate_drawdowns(tickers)
        var_info = self.calculate_portfolio_var(tickers)
        stop_losses = self.check_stop_losses(picks)
        concentration = self.analyze_concentration_risk(picks)
        alerts = self.generate_alerts(picks, drawdowns, stop_losses, concentration, var_info)

        # Determine overall risk level
        critical_count = len([a for a in alerts if a['severity'] == 'critical'])
        warning_count = len([a for a in alerts if a['severity'] == 'warning'])

        if critical_count >= 3:
            risk_level = 'High'
        elif critical_count >= 1 or warning_count >= 3:
            risk_level = 'Elevated'
        elif warning_count >= 1:
            risk_level = 'Moderate'
        else:
            risk_level = 'Low'

        result = {
            'timestamp': datetime.now().isoformat(),
            'portfolio_summary': {
                'total_picks': len(picks),
                'portfolio_var_95_5d': var_info.get('var_dollar', 0),
                'portfolio_cvar_95_5d': var_info.get('cvar_dollar', 0),
                'risk_level': risk_level,
                'var_details': var_info,
            },
            'drawdowns': drawdowns,
            'concentration': concentration,
            'alerts': alerts,
        }

        # Save
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Saved risk alerts to {self.output_file}")
        logger.info(f"   Risk Level: {risk_level} | Alerts: {len(alerts)} (Critical: {critical_count}, Warning: {warning_count})")

        return result


def main():
    system = RiskAlertSystem()
    result = system.run_analysis()

    print("\n" + "=" * 60)
    print("🚨 RISK ALERT REPORT")
    print("=" * 60)

    summary = result.get('portfolio_summary', {})
    print(f"\n📊 Portfolio Risk Level: {summary.get('risk_level', 'Unknown')}")
    print(f"   VaR (95%, 5d): ${summary.get('portfolio_var_95_5d', 0):,.2f}")
    print(f"   CVaR (95%, 5d): ${summary.get('portfolio_cvar_95_5d', 0):,.2f}")

    alerts = result.get('alerts', [])
    if alerts:
        print(f"\n⚠️  Active Alerts ({len(alerts)}):")
        for alert in alerts[:10]:
            icon = '🔴' if alert['severity'] == 'critical' else '🟡' if alert['severity'] == 'warning' else '🔵'
            print(f"  {icon} [{alert['severity'].upper()}] {alert['message']}")
    else:
        print(f"\n✅ No active risk alerts")


if __name__ == "__main__":
    main()
