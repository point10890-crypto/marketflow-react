#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sector Rotation Tracker v1.0
- Tracks sector rotation over time using 11 SPDR sector ETFs
- Detects business cycle phase (Early/Mid/Late/Recession)
- Alerts on regime changes
- Provides rotation clock data for visualization
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


class SectorRotationTracker:
    """Track sector rotation and detect business cycle phases"""

    SECTOR_ETFS = {
        'XLK': 'Technology',
        'XLF': 'Financials',
        'XLV': 'Healthcare',
        'XLY': 'Consumer Disc.',
        'XLP': 'Consumer Staples',
        'XLE': 'Energy',
        'XLI': 'Industrials',
        'XLB': 'Materials',
        'XLRE': 'Real Estate',
        'XLU': 'Utilities',
        'XLC': 'Comm. Services',
    }

    CYCLE_MAP = {
        'Early Cycle': ['XLF', 'XLY', 'XLI'],
        'Mid Cycle': ['XLK', 'XLC', 'XLB'],
        'Late Cycle': ['XLE', 'XLRE'],
        'Recession': ['XLU', 'XLP', 'XLV'],
    }

    CYCLE_ANGLES = {
        'Early Cycle': 45,
        'Mid Cycle': 135,
        'Late Cycle': 225,
        'Recession': 315,
    }

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'sector_rotation.json')
        # Phase detection weights (overridden by regime config if available)
        self.phase_weight_1w = 0.25
        self.phase_weight_1m = 0.40
        self.phase_weight_3m = 0.35
        self._load_regime_config()

    def _load_regime_config(self):
        """Load adaptive weights from regime_config.json if available"""
        config_path = os.path.join(self.data_dir, 'output', 'regime_config.json')
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                sr_cfg = config.get('sector_rotation', {})
                if sr_cfg:
                    self.phase_weight_1w = sr_cfg.get('phase_weight_1w', self.phase_weight_1w)
                    self.phase_weight_1m = sr_cfg.get('phase_weight_1m', self.phase_weight_1m)
                    self.phase_weight_3m = sr_cfg.get('phase_weight_3m', self.phase_weight_3m)
                    logger.info("📋 Loaded regime config for sector_rotation")
        except Exception:
            pass

    def get_multi_period_performance(self) -> Dict:
        """Get 1w/1m/3m/6m/12m returns for all 11 sectors via yfinance"""
        logger.info("📊 Fetching multi-period sector performance...")

        tickers = list(self.SECTOR_ETFS.keys()) + ['SPY']
        periods = {'1w': 7, '1m': 30, '3m': 90, '6m': 180, '12m': 365}

        try:
            # Fetch 1 year of data to cover all periods
            data = yf.download(tickers, period='1y', progress=False)['Close']

            if data.empty:
                return {}

            performance = {}
            # Include SPY for relative strength calculations
            for ticker in list(self.SECTOR_ETFS.keys()) + ['SPY']:
                if ticker not in data.columns:
                    continue

                prices = data[ticker].dropna()
                if len(prices) < 5:
                    continue

                perf = {}
                current_price = prices.iloc[-1]

                for period_name, days in periods.items():
                    idx = max(0, len(prices) - days)
                    start_price = prices.iloc[idx]
                    if start_price > 0:
                        perf[period_name] = round(((current_price / start_price) - 1) * 100, 2)
                    else:
                        perf[period_name] = 0.0

                perf['current_price'] = round(float(current_price), 2)
                perf['name'] = self.SECTOR_ETFS.get(ticker, ticker)
                performance[ticker] = perf

            return performance

        except Exception as e:
            logger.error(f"Error fetching performance: {e}")
            return {}

    def calculate_relative_strength_history(self, weeks: int = 12) -> Dict:
        """Weekly RS vs SPY for each sector (for line chart)"""
        logger.info(f"📈 Calculating {weeks}-week relative strength history...")

        tickers = list(self.SECTOR_ETFS.keys()) + ['SPY']
        days_needed = weeks * 7 + 10

        try:
            data = yf.download(tickers, period=f'{days_needed}d', progress=False)['Close']

            if data.empty or 'SPY' not in data.columns:
                return {}

            # Resample to weekly
            weekly = data.resample('W-FRI').last().dropna(how='all')

            if len(weekly) < 2:
                return {}

            spy_weekly = weekly['SPY']
            rs_history = {}
            dates = [d.strftime('%Y-%m-%d') for d in weekly.index[-weeks:]]

            for ticker in self.SECTOR_ETFS:
                if ticker not in weekly.columns:
                    continue

                sector_weekly = weekly[ticker]
                # RS = sector return / SPY return (cumulative, rebased to 100)
                rs_values = []
                for i in range(-weeks, 0):
                    if i + len(weekly) >= 1:
                        idx = i + len(weekly)
                        base_idx = idx - 1

                        sector_ret = (sector_weekly.iloc[idx] / sector_weekly.iloc[base_idx] - 1) * 100
                        spy_ret = (spy_weekly.iloc[idx] / spy_weekly.iloc[base_idx] - 1) * 100
                        rs_values.append(round(sector_ret - spy_ret, 2))

                rs_history[ticker] = rs_values

            # Use min length across all sectors to align dates (avoid scope leak)
            min_len = min((len(v) for v in rs_history.values()), default=0)
            return {'dates': dates[-min_len:] if min_len > 0 else dates, 'sectors': rs_history}

        except Exception as e:
            logger.error(f"Error calculating RS history: {e}")
            return {}

    def detect_rotation_phase(self, performance: Dict) -> Dict:
        """Score each cycle phase by avg RS of its sectors"""
        logger.info("🔄 Detecting rotation phase...")

        if not performance:
            return {'current_phase': 'Unknown', 'phase_confidence': 0, 'phase_scores': {}}

        phase_scores = {}

        # SPY returns for relative strength calculation
        spy_perf = performance.get('SPY', {}) if isinstance(performance, dict) else {}

        for phase, phase_tickers in self.CYCLE_MAP.items():
            scores = []
            for ticker in phase_tickers:
                if ticker in performance:
                    # Use relative returns (vs SPY) instead of absolute
                    p = performance[ticker]
                    rel_1m = p.get('1m', 0) - spy_perf.get('1m', 0)
                    rel_3m = p.get('3m', 0) - spy_perf.get('3m', 0)
                    rel_1w = p.get('1w', 0) - spy_perf.get('1w', 0)
                    score = (
                        rel_1m * self.phase_weight_1m +
                        rel_3m * self.phase_weight_3m +
                        rel_1w * self.phase_weight_1w
                    )
                    scores.append(score)

            phase_scores[phase] = round(np.mean(scores), 2) if scores else 0

        # Sort phases by score
        sorted_phases = sorted(phase_scores.items(), key=lambda x: x[1], reverse=True)
        current_phase = sorted_phases[0][0]
        top_score = sorted_phases[0][1]
        second_score = sorted_phases[1][1] if len(sorted_phases) > 1 else 0

        # Confidence based on gap between 1st and 2nd place
        gap = abs(top_score - second_score)
        confidence = min(100, int(50 + gap * 5))

        # Leading and lagging sectors
        all_sectors_scored = []
        for ticker, perf in performance.items():
            weighted = perf.get('1m', 0) * 0.5 + perf.get('1w', 0) * 0.5
            all_sectors_scored.append((ticker, weighted))

        all_sectors_scored.sort(key=lambda x: x[1], reverse=True)
        leading = [t for t, _ in all_sectors_scored[:3]]
        lagging = [t for t, _ in all_sectors_scored[-3:]]

        # Rotation velocity: standard deviation of phase scores
        # High std → clear divergence between phases (fast rotation)
        # Low std → phases scoring similarly (slow/indecisive rotation)
        all_scores = list(phase_scores.values())
        velocity = round(float(np.std(all_scores)), 2) if len(all_scores) > 1 else 0

        return {
            'current_phase': current_phase,
            'phase_confidence': confidence,
            'phase_scores': phase_scores,
            'leading_sectors': leading,
            'lagging_sectors': lagging,
            'rotation_velocity': velocity,
        }

    def detect_money_flow(self, rs_history: Dict) -> Dict:
        """Compare RS changes: gaining sectors = inflow, losing = outflow"""
        logger.info("💰 Detecting money flow...")

        if not rs_history or 'sectors' not in rs_history:
            return {'inflows': [], 'outflows': []}

        inflows = []
        outflows = []

        for ticker, rs_values in rs_history.get('sectors', {}).items():
            if len(rs_values) < 4:
                continue

            recent_avg = np.mean(rs_values[-4:])  # Last 4 weeks
            earlier_avg = np.mean(rs_values[:4])   # First 4 weeks
            change = recent_avg - earlier_avg

            entry = {
                'ticker': ticker,
                'name': self.SECTOR_ETFS.get(ticker, ticker),
                'rs_change': round(change, 2),
                'recent_rs': round(recent_avg, 2),
            }

            if change > 0.5:
                inflows.append(entry)
            elif change < -0.5:
                outflows.append(entry)

        inflows.sort(key=lambda x: x['rs_change'], reverse=True)
        outflows.sort(key=lambda x: x['rs_change'])

        return {'inflows': inflows, 'outflows': outflows}

    def detect_regime_change(self, current_phase: str) -> Dict:
        """Load previous output, compare phase. Alert if changed."""
        regime_change_alert = False
        previous_phase = None

        try:
            if os.path.exists(self.output_file):
                with open(self.output_file, 'r', encoding='utf-8') as f:
                    prev_data = json.load(f)
                previous_phase = prev_data.get('rotation_signals', {}).get('current_phase')

                if previous_phase and previous_phase != current_phase:
                    regime_change_alert = True
                    logger.info(f"🚨 Regime change detected: {previous_phase} → {current_phase}")
        except Exception:
            pass

        return {
            'regime_change_alert': regime_change_alert,
            'previous_phase': previous_phase,
            'current_phase': current_phase,
        }

    def build_rotation_clock(self, performance: Dict, phase_info: Dict) -> Dict:
        """Clock position angles for each phase (0-360 degrees)"""
        phases = {}
        for phase_name, angle in self.CYCLE_ANGLES.items():
            phase_tickers = self.CYCLE_MAP[phase_name]
            sector_data = []
            for ticker in phase_tickers:
                if ticker in performance:
                    sector_data.append({
                        'ticker': ticker,
                        'name': self.SECTOR_ETFS.get(ticker, ticker),
                        'return_1m': performance[ticker].get('1m', 0),
                    })
            phases[phase_name] = {
                'angle': angle,
                'sectors': sector_data,
                'score': phase_info.get('phase_scores', {}).get(phase_name, 0),
            }

        current_angle = self.CYCLE_ANGLES.get(phase_info.get('current_phase', 'Mid Cycle'), 135)

        return {'phases': phases, 'current_angle': current_angle}

    def analyze(self) -> Dict:
        """Main entry point: run full analysis"""
        logger.info("🔄 Starting sector rotation analysis...")

        performance = self.get_multi_period_performance()
        rs_history = self.calculate_relative_strength_history(weeks=12)
        phase_info = self.detect_rotation_phase(performance)
        money_flow = self.detect_money_flow(rs_history)
        regime = self.detect_regime_change(phase_info['current_phase'])
        clock = self.build_rotation_clock(performance, phase_info)

        money_flow['regime_change_alert'] = regime['regime_change_alert']

        return {
            'timestamp': datetime.now().isoformat(),
            'performance_matrix': performance,
            'rotation_signals': phase_info,
            'relative_strength_history': rs_history,
            'money_flow': money_flow,
            'regime_change': regime,
            'rotation_clock': clock,
        }

    def save_data(self, output_dir: str = None):
        """Run analysis and save to output/sector_rotation.json"""
        data = self.analyze()

        output_path = self.output_file
        if output_dir:
            output_path = os.path.join(output_dir, 'sector_rotation.json')

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Saved sector rotation data to {output_path}")
        return data


def main():
    tracker = SectorRotationTracker()
    data = tracker.save_data()

    print("\n" + "=" * 60)
    print("🔄 SECTOR ROTATION ANALYSIS")
    print("=" * 60)

    signals = data.get('rotation_signals', {})
    print(f"\n📊 Current Phase: {signals.get('current_phase', 'Unknown')}")
    print(f"   Confidence: {signals.get('phase_confidence', 0)}%")
    print(f"   Velocity: {signals.get('rotation_velocity', 0)}")

    print(f"\n🟢 Leading Sectors: {', '.join(signals.get('leading_sectors', []))}")
    print(f"🔴 Lagging Sectors: {', '.join(signals.get('lagging_sectors', []))}")

    # Performance matrix
    perf = data.get('performance_matrix', {})
    if perf:
        print(f"\n📈 Performance Matrix:")
        print(f"{'Sector':18} {'1w':>8} {'1m':>8} {'3m':>8} {'6m':>8} {'12m':>8}")
        print("-" * 58)
        for ticker, p in sorted(perf.items(), key=lambda x: x[1].get('1m', 0), reverse=True):
            name = p.get('name', ticker)[:16]
            print(f"{name:18} {p.get('1w',0):>+7.1f}% {p.get('1m',0):>+7.1f}% {p.get('3m',0):>+7.1f}% {p.get('6m',0):>+7.1f}% {p.get('12m',0):>+7.1f}%")

    # Money flow
    mf = data.get('money_flow', {})
    if mf.get('inflows'):
        print(f"\n💰 Money Inflows:")
        for item in mf['inflows'][:5]:
            print(f"  ➡️  {item['name']:18} RS Change: {item['rs_change']:+.2f}")

    if mf.get('regime_change_alert'):
        regime = data.get('regime_change', {})
        print(f"\n🚨 REGIME CHANGE: {regime.get('previous_phase')} → {regime.get('current_phase')}")


if __name__ == "__main__":
    main()
