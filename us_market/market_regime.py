#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Regime Detector v1.0
- Classifies market regime: Risk-On / Neutral / Risk-Off / Crisis
- Uses VIX level + trend, SPY trend, yield curve, breadth
- Outputs adaptive thresholds to output/regime_config.json
- All downstream scripts load these thresholds with sensible defaults
"""

import os
import json
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MarketRegimeDetector:
    """Detect current market regime and produce adaptive config for all scripts."""

    # Regime definitions (ordinal: lower = more risk-on)
    REGIMES = ['risk_on', 'neutral', 'risk_off', 'crisis']

    # --- VIX thresholds ---
    VIX_BOUNDARIES = {
        'risk_on': (0, 16),
        'neutral': (16, 22),
        'risk_off': (22, 30),
        'crisis': (30, 999),
    }

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'regime_config.json')

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------
    def _fetch_series(self, ticker: str, period: str = '6mo') -> Optional[pd.Series]:
        """Fetch Close series for a single ticker."""
        try:
            df = yf.download(ticker, period=period, progress=False)
            if df.empty:
                return None
            return df['Close'].squeeze()
        except Exception as e:
            logger.warning(f"Could not fetch {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # Signal components
    # ------------------------------------------------------------------
    def _vix_signal(self, vix: pd.Series) -> Dict:
        """VIX level + 20-day trend."""
        current = float(vix.iloc[-1])
        ma20 = float(vix.rolling(20).mean().iloc[-1]) if len(vix) >= 20 else current
        trend = 'falling' if current < ma20 else 'rising'

        regime = 'neutral'
        for name, (lo, hi) in self.VIX_BOUNDARIES.items():
            if lo <= current < hi:
                regime = name
                break

        return {
            'vix_current': round(current, 2),
            'vix_ma20': round(ma20, 2),
            'vix_trend': trend,
            'vix_regime': regime,
        }

    def _trend_signal(self, spy: pd.Series) -> Dict:
        """SPY trend: price vs 50/200 SMA + 200 SMA slope."""
        if spy is None or len(spy) < 200:
            return {'trend_regime': 'neutral', 'spy_above_50': True, 'spy_above_200': True, 'sma200_slope': 0}

        price = float(spy.iloc[-1])
        sma50 = float(spy.rolling(50).mean().iloc[-1])
        sma200 = float(spy.rolling(200).mean().iloc[-1])
        sma200_20d_ago = float(spy.rolling(200).mean().iloc[-20])
        slope = sma200 - sma200_20d_ago

        above_50 = price > sma50
        above_200 = price > sma200

        if above_50 and above_200 and slope > 0:
            regime = 'risk_on'
        elif above_200:
            regime = 'neutral'
        elif not above_200 and slope < 0:
            regime = 'risk_off'
        else:
            regime = 'neutral'

        return {
            'trend_regime': regime,
            'spy_above_50': above_50,
            'spy_above_200': above_200,
            'sma200_slope': round(slope, 4),
        }

    def _breadth_signal(self) -> Dict:
        """Market breadth via advance-decline (MMFI as proxy)."""
        # Use MMFI (% stocks above 50-day MA on NYSE) as breadth proxy
        try:
            mmfi = self._fetch_series('^MMFI', period='3mo')
            if mmfi is not None and len(mmfi) > 0:
                current = float(mmfi.iloc[-1])
                if current > 70:
                    regime = 'risk_on'
                elif current > 50:
                    regime = 'neutral'
                elif current > 30:
                    regime = 'risk_off'
                else:
                    regime = 'crisis'
                return {'breadth_pct': round(current, 1), 'breadth_regime': regime}
        except Exception:
            pass
        return {'breadth_pct': None, 'breadth_regime': 'neutral'}

    def _yield_curve_signal(self) -> Dict:
        """10Y-2Y spread: positive = normal, negative = inverted."""
        try:
            tnx = self._fetch_series('^TNX', period='3mo')  # 10Y
            twy = self._fetch_series('^IRX', period='3mo')  # 3mo T-bill (proxy for short end)
            if tnx is not None and twy is not None:
                spread = float(tnx.iloc[-1]) - float(twy.iloc[-1])
                if spread > 0.5:
                    regime = 'risk_on'
                elif spread > 0:
                    regime = 'neutral'
                else:
                    regime = 'risk_off'
                return {'yield_spread': round(spread, 2), 'yield_regime': regime}
        except Exception:
            pass
        return {'yield_spread': None, 'yield_regime': 'neutral'}

    # ------------------------------------------------------------------
    # Composite regime
    # ------------------------------------------------------------------
    def detect_regime(self) -> Dict:
        """Combine all signals into a single regime classification."""
        logger.info("🔍 Detecting market regime...")

        # Fetch data
        vix_data = self._fetch_series('^VIX', period='3mo')
        spy_data = self._fetch_series('SPY', period='1y')

        # Individual signals
        vix_sig = self._vix_signal(vix_data) if vix_data is not None else {'vix_regime': 'neutral', 'vix_current': 0}
        trend_sig = self._trend_signal(spy_data)
        breadth_sig = self._breadth_signal()
        yield_sig = self._yield_curve_signal()

        # Vote: map each regime to a score
        score_map = {'risk_on': 0, 'neutral': 1, 'risk_off': 2, 'crisis': 3}
        weights = {'vix': 0.35, 'trend': 0.30, 'breadth': 0.20, 'yield': 0.15}

        signals = {
            'vix': vix_sig.get('vix_regime', 'neutral'),
            'trend': trend_sig.get('trend_regime', 'neutral'),
            'breadth': breadth_sig.get('breadth_regime', 'neutral'),
            'yield': yield_sig.get('yield_regime', 'neutral'),
        }

        weighted_score = sum(
            score_map.get(regime, 1) * weights[name]
            for name, regime in signals.items()
        )

        # Map back to regime
        if weighted_score < 0.75:
            composite = 'risk_on'
        elif weighted_score < 1.5:
            composite = 'neutral'
        elif weighted_score < 2.25:
            composite = 'risk_off'
        else:
            composite = 'crisis'

        # Confidence: how aligned are the signals?
        regime_votes = list(signals.values())
        majority = max(set(regime_votes), key=regime_votes.count)
        agreement = regime_votes.count(majority) / len(regime_votes)
        confidence = round(agreement * 100, 0)

        return {
            'regime': composite,
            'confidence': confidence,
            'weighted_score': round(weighted_score, 2),
            'signals': {
                'vix': vix_sig,
                'trend': trend_sig,
                'breadth': breadth_sig,
                'yield_curve': yield_sig,
            },
        }

    # ------------------------------------------------------------------
    # Config generation
    # ------------------------------------------------------------------
    def _generate_config(self, regime: str) -> Dict:
        """Produce per-script adaptive thresholds based on current regime."""

        # Base configs per regime
        configs = {
            'risk_on': {
                'risk_alert': {
                    'max_drawdown_warning': -12.0,
                    'max_drawdown_critical': -25.0,
                    'stop_loss_default': -10.0,
                    'var_confidence': 0.95,
                },
                'index_predictor': {
                    'rsi_overbought': 75,
                    'rsi_oversold': 25,
                    'vix_high': 22,
                    'momentum_lookback': 20,
                },
                'backtest': {
                    'risk_free_rate': 0.04,
                },
                'smart_money': {
                    'min_composite_score': 55,
                    'volume_weight': 0.25,
                    'institutional_weight': 0.20,
                },
                'sector_rotation': {
                    'phase_weight_1w': 0.25,
                    'phase_weight_1m': 0.40,
                    'phase_weight_3m': 0.35,
                },
                'vcp_scanner': {
                    'min_trend_score': 5,
                    'min_rs_rating': 55,
                    'max_base_depth': 0.35,
                },
                'earnings_impact': {
                    'lookback_quarters': 4,
                    'min_beat_rate_bullish': 70,
                    'max_beat_rate_bearish': 40,
                },
            },
            'neutral': {
                'risk_alert': {
                    'max_drawdown_warning': -10.0,
                    'max_drawdown_critical': -20.0,
                    'stop_loss_default': -8.0,
                    'var_confidence': 0.95,
                },
                'index_predictor': {
                    'rsi_overbought': 70,
                    'rsi_oversold': 30,
                    'vix_high': 20,
                    'momentum_lookback': 20,
                },
                'backtest': {
                    'risk_free_rate': 0.04,
                },
                'smart_money': {
                    'min_composite_score': 60,
                    'volume_weight': 0.25,
                    'institutional_weight': 0.20,
                },
                'sector_rotation': {
                    'phase_weight_1w': 0.25,
                    'phase_weight_1m': 0.40,
                    'phase_weight_3m': 0.35,
                },
                'vcp_scanner': {
                    'min_trend_score': 6,
                    'min_rs_rating': 60,
                    'max_base_depth': 0.30,
                },
                'earnings_impact': {
                    'lookback_quarters': 4,
                    'min_beat_rate_bullish': 70,
                    'max_beat_rate_bearish': 40,
                },
            },
            'risk_off': {
                'risk_alert': {
                    'max_drawdown_warning': -7.0,
                    'max_drawdown_critical': -15.0,
                    'stop_loss_default': -5.0,
                    'var_confidence': 0.99,
                },
                'index_predictor': {
                    'rsi_overbought': 65,
                    'rsi_oversold': 35,
                    'vix_high': 18,
                    'momentum_lookback': 10,
                },
                'backtest': {
                    'risk_free_rate': 0.04,
                },
                'smart_money': {
                    'min_composite_score': 65,
                    'volume_weight': 0.20,
                    'institutional_weight': 0.25,
                },
                'sector_rotation': {
                    'phase_weight_1w': 0.35,
                    'phase_weight_1m': 0.40,
                    'phase_weight_3m': 0.25,
                },
                'vcp_scanner': {
                    'min_trend_score': 6,
                    'min_rs_rating': 65,
                    'max_base_depth': 0.25,
                },
                'earnings_impact': {
                    'lookback_quarters': 6,
                    'min_beat_rate_bullish': 75,
                    'max_beat_rate_bearish': 35,
                },
            },
            'crisis': {
                'risk_alert': {
                    'max_drawdown_warning': -5.0,
                    'max_drawdown_critical': -10.0,
                    'stop_loss_default': -3.0,
                    'var_confidence': 0.99,
                },
                'index_predictor': {
                    'rsi_overbought': 60,
                    'rsi_oversold': 40,
                    'vix_high': 15,
                    'momentum_lookback': 5,
                },
                'backtest': {
                    'risk_free_rate': 0.04,
                },
                'smart_money': {
                    'min_composite_score': 70,
                    'volume_weight': 0.15,
                    'institutional_weight': 0.30,
                },
                'sector_rotation': {
                    'phase_weight_1w': 0.40,
                    'phase_weight_1m': 0.35,
                    'phase_weight_3m': 0.25,
                },
                'vcp_scanner': {
                    'min_trend_score': 7,
                    'min_rs_rating': 70,
                    'max_base_depth': 0.20,
                },
                'earnings_impact': {
                    'lookback_quarters': 8,
                    'min_beat_rate_bullish': 80,
                    'max_beat_rate_bearish': 30,
                },
            },
        }

        return configs.get(regime, configs['neutral'])

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def run(self) -> Dict:
        """Detect regime and write adaptive config to output/regime_config.json."""
        logger.info("🌍 Starting market regime detection...")

        regime_info = self.detect_regime()
        regime = regime_info['regime']
        config = self._generate_config(regime)

        result = {
            'timestamp': datetime.now().isoformat(),
            'regime': regime,
            'confidence': regime_info['confidence'],
            'weighted_score': regime_info['weighted_score'],
            'signals': regime_info['signals'],
            **config,  # Flatten per-script configs at top level
        }

        # Save
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Regime: {regime.upper()} (confidence: {regime_info['confidence']}%)")
        logger.info(f"   Config saved to {self.output_file}")

        return result


def main():
    detector = MarketRegimeDetector()
    result = detector.run()

    print("\n" + "=" * 60)
    print("🌍 MARKET REGIME REPORT")
    print("=" * 60)

    print(f"\n📊 Current Regime: {result['regime'].upper()}")
    print(f"   Confidence: {result['confidence']}%")
    print(f"   Weighted Score: {result['weighted_score']} (0=RiskOn, 3=Crisis)")

    signals = result.get('signals', {})
    vix = signals.get('vix', {})
    trend = signals.get('trend', {})
    breadth = signals.get('breadth', {})
    yld = signals.get('yield_curve', {})

    print(f"\n📈 Signal Breakdown:")
    print(f"   VIX:     {vix.get('vix_current', '?')} ({vix.get('vix_regime', '?')}, {vix.get('vix_trend', '?')})")
    print(f"   Trend:   {'Above' if trend.get('spy_above_200') else 'Below'} 200SMA ({trend.get('trend_regime', '?')})")
    print(f"   Breadth: {breadth.get('breadth_pct', '?')}% ({breadth.get('breadth_regime', '?')})")
    print(f"   Yield:   {yld.get('yield_spread', '?')} ({yld.get('yield_regime', '?')})")

    print(f"\n📋 Adaptive Thresholds Applied:")
    for key in ['risk_alert', 'index_predictor', 'smart_money', 'vcp_scanner']:
        if key in result:
            print(f"   {key}: {json.dumps(result[key], indent=None)}")


if __name__ == "__main__":
    main()
