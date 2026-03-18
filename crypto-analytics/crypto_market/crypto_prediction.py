#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto Price Direction Predictor v2.0

Improvements over v1.0:
- Threshold-based label: forward_5d_return > median + 0.5*std (noise filtering)
- 18 features (added VIX, VIX percentile, TLT, alt strength, funding rate, fear&greed)
- 3-model ensemble (seeds 42, 123, 456) with averaged probabilities
- Tuned hyperparameters (depth=3, lr=0.05, leaf=10, n=150)
- Prediction history tracking (btc_prediction_history.json, max 90 entries)
- Better driver direction logic for RSI, BB, VIX

Features:
- GradientBoosting ML ensemble for BTC 5-day direction prediction
- 18 technical, cross-asset & sentiment features
- TimeSeriesSplit cross-validation (no data leakage)
- Automatic retraining when model is stale (>7 days)
- Key driver analysis with feature importances

Usage:
    python3 crypto_prediction.py
"""

import os
import json
import logging
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_TIMEOUT = 5


class CryptoPredictor:
    """Probabilistic BTC direction prediction using ML ensemble"""

    FEATURE_NAMES = [
        'btc_return_5d',
        'btc_return_20d',
        'btc_rsi_14',
        'btc_macd_signal',
        'btc_bb_position',
        'btc_above_ma50',
        'btc_above_ma200',
        'eth_btc_relative_5d',
        'spy_return_5d',
        'gold_return_5d',
        'dxy_return_5d',
        'btc_volume_zscore',
        'vix_level',
        'vix_percentile_60d',
        'tlt_return_5d',
        'alt_strength_5d',
        'funding_rate',
        'fear_greed_index',
    ]

    # Features where higher value tends to be bearish
    INVERSE_FEATURES = {
        'dxy_return_5d',   # strong dollar = headwind for crypto
        'vix_level',       # high VIX = risk-off, bearish for crypto
        'vix_percentile_60d',  # high VIX percentile = elevated fear
    }

    TICKERS = ['BTC-USD', 'ETH-USD', 'SPY', 'GLD', '^VIX', 'TLT', 'UUP']
    TICKER_LABELS = {
        'BTC-USD': 'BTC', 'ETH-USD': 'ETH', 'SPY': 'SPY',
        'GLD': 'GLD', '^VIX': 'VIX', 'TLT': 'TLT', 'UUP': 'DXY',
    }

    ENSEMBLE_SEEDS = [42, 123, 456]
    RETRAIN_INTERVAL_DAYS = 7
    PREDICTION_HORIZON = 5  # 5 trading days forward
    HISTORY_MAX_ENTRIES = 90

    FEAR_GREED_URL = 'https://api.alternative.me/fng/'
    BINANCE_FUTURES_BASE = 'https://fapi.binance.com/fapi/v1'

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_dir = os.path.join(data_dir, 'output')
        self.output_file = os.path.join(self.output_dir, 'btc_prediction.json')
        self.model_path = os.path.join(self.output_dir, 'btc_model.joblib')
        self.history_file = os.path.join(self.output_dir, 'btc_prediction_history.json')

    # ------------------------------------------------------------------
    # External Data Fetchers (point-in-time features)
    # ------------------------------------------------------------------

    def _fetch_funding_rate(self) -> Optional[float]:
        """Fetch BTC perpetual funding rate from Binance fapi"""
        try:
            resp = requests.get(
                f'{self.BINANCE_FUTURES_BASE}/premiumIndex',
                params={'symbol': 'BTCUSDT'},
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            rate = float(data.get('lastFundingRate', 0))
            return rate
        except Exception as e:
            logger.warning(f"Failed to fetch funding rate: {e}")
            return None

    def _fetch_fear_greed(self) -> Optional[float]:
        """Fetch current Crypto Fear & Greed Index from alternative.me"""
        try:
            resp = requests.get(
                self.FEAR_GREED_URL,
                params={'limit': 1},
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get('data', [])
            if data:
                return float(data[0].get('value', 50))
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch Fear & Greed Index: {e}")
            return None

    # ------------------------------------------------------------------
    # Technical Indicators
    # ------------------------------------------------------------------

    def _calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Standard 14-period RSI using Wilder's smoothing"""
        delta = series.diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1 / period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / period, adjust=False).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def _calculate_macd_signal(self, series: pd.Series) -> pd.Series:
        """MACD signal: +1 bullish (MACD > signal), -1 bearish, 0 neutral"""
        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return (macd > signal).astype(int) - (macd < signal).astype(int)

    def _calculate_bb_position(self, series: pd.Series, window: int = 20) -> pd.Series:
        """Bollinger Band position: (close - lower) / (upper - lower), clipped 0-1"""
        ma = series.rolling(window).mean()
        std = series.rolling(window).std()
        upper = ma + 2 * std
        lower = ma - 2 * std
        band_width = upper - lower
        position = (series - lower) / band_width.replace(0, np.nan)
        return position.clip(0, 1).fillna(0.5)

    # ------------------------------------------------------------------
    # Feature Engineering
    # ------------------------------------------------------------------

    def _fetch_price_data(self, years: int = 3) -> pd.DataFrame:
        """Download price data for all required tickers"""
        start_date = (datetime.now() - timedelta(days=years * 365 + 300)).strftime('%Y-%m-%d')

        try:
            data = yf.download(self.TICKERS, start=start_date, progress=False)
            if data.empty:
                logger.error("No data returned from yfinance")
                return pd.DataFrame()

            close = data['Close'].rename(columns=self.TICKER_LABELS)
            volume = data['Volume'].rename(columns=self.TICKER_LABELS)

            # Combine close and BTC volume into one frame
            result = close.copy()
            if 'BTC' in volume.columns:
                result['BTC_VOLUME'] = volume['BTC']

            return result
        except Exception as e:
            logger.error(f"Error downloading price data: {e}")
            return pd.DataFrame()

    def build_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Build 18 feature columns from price data"""
        features = pd.DataFrame(index=data.index)

        if 'BTC' not in data.columns:
            logger.error("BTC price data not available")
            return pd.DataFrame()

        btc = data['BTC']

        # BTC momentum features
        features['btc_return_5d'] = btc.pct_change(5, fill_method=None) * 100
        features['btc_return_20d'] = btc.pct_change(20, fill_method=None) * 100

        # BTC technical features
        features['btc_rsi_14'] = self._calculate_rsi(btc, period=14)
        features['btc_macd_signal'] = self._calculate_macd_signal(btc)
        features['btc_bb_position'] = self._calculate_bb_position(btc)

        # BTC trend features
        features['btc_above_ma50'] = (btc > btc.rolling(50).mean()).astype(int)
        features['btc_above_ma200'] = (btc > btc.rolling(200).mean()).astype(int)

        # ETH/BTC relative strength
        if 'ETH' in data.columns:
            eth_ret_5d = data['ETH'].pct_change(5, fill_method=None)
            btc_ret_5d = btc.pct_change(5, fill_method=None)
            features['eth_btc_relative_5d'] = (eth_ret_5d - btc_ret_5d) * 100
        else:
            features['eth_btc_relative_5d'] = 0

        # Cross-asset features
        if 'SPY' in data.columns:
            features['spy_return_5d'] = data['SPY'].pct_change(5, fill_method=None) * 100
        else:
            features['spy_return_5d'] = 0

        if 'GLD' in data.columns:
            features['gold_return_5d'] = data['GLD'].pct_change(5, fill_method=None) * 100
        else:
            features['gold_return_5d'] = 0

        if 'DXY' in data.columns:
            features['dxy_return_5d'] = data['DXY'].pct_change(5, fill_method=None) * 100
        else:
            features['dxy_return_5d'] = 0

        # Volume z-score
        if 'BTC_VOLUME' in data.columns:
            vol = data['BTC_VOLUME']
            vol_mean = vol.rolling(20).mean()
            vol_std = vol.rolling(20).std()
            features['btc_volume_zscore'] = ((vol - vol_mean) / vol_std.replace(0, np.nan)).fillna(0)
        else:
            features['btc_volume_zscore'] = 0

        # --- New features (v2.0) ---

        # VIX level
        if 'VIX' in data.columns:
            features['vix_level'] = data['VIX']
        else:
            features['vix_level'] = np.nan

        # VIX 60-day rolling percentile rank
        if 'VIX' in data.columns:
            vix = data['VIX']
            features['vix_percentile_60d'] = vix.rolling(60).apply(
                lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False,
            )
        else:
            features['vix_percentile_60d'] = np.nan

        # TLT 5-day return (Treasury bonds)
        if 'TLT' in data.columns:
            features['tlt_return_5d'] = data['TLT'].pct_change(5, fill_method=None) * 100
        else:
            features['tlt_return_5d'] = np.nan

        # Alt strength: ETH/BTC ratio 5-day change
        if 'ETH' in data.columns and 'BTC' in data.columns:
            eth_btc_ratio = data['ETH'] / data['BTC'].replace(0, np.nan)
            features['alt_strength_5d'] = eth_btc_ratio.pct_change(5, fill_method=None) * 100
        else:
            features['alt_strength_5d'] = np.nan

        # Funding rate and Fear & Greed are point-in-time; set NaN for historical rows.
        # They will be filled for the latest row in _build_latest_features.
        features['funding_rate'] = np.nan
        features['fear_greed_index'] = np.nan

        return features

    def _build_training_dataset(self) -> pd.DataFrame:
        """Build features + target for training with threshold-based label"""
        logger.info("Building training dataset...")

        data = self._fetch_price_data(years=3)
        if data.empty:
            return pd.DataFrame()

        features = self.build_features(data)

        # Target: threshold-based label
        # forward_5d_return > median + 0.5*std -> bullish (1), else 0
        btc = data['BTC']
        forward_return = btc.pct_change(self.PREDICTION_HORIZON, fill_method=None).shift(-self.PREDICTION_HORIZON) * 100
        features['btc_forward_5d_return'] = forward_return

        # Calculate threshold from historical returns (exclude NaN)
        valid_returns = forward_return.dropna()
        ret_median = valid_returns.median()
        ret_std = valid_returns.std()
        threshold = ret_median + 0.5 * ret_std
        logger.info(f"Label threshold: median={ret_median:.2f}% + 0.5*std={0.5*ret_std:.2f}% = {threshold:.2f}%")

        features['target'] = (features['btc_forward_5d_return'] > threshold).astype(int)

        # Fill NaN in point-in-time features with column median for training
        for col in self.FEATURE_NAMES:
            if col in features.columns:
                col_median = features[col].median()
                if pd.isna(col_median):
                    col_median = 0
                features[col] = features[col].fillna(col_median)

        # Drop initial NaN rows from lookback calculations
        features = features.dropna(subset=self.FEATURE_NAMES + ['target'])

        logger.info(f"Built {len(features)} training samples with {len(self.FEATURE_NAMES)} features")
        class_dist = features['target'].value_counts()
        logger.info(f"Class distribution: {dict(class_dist)}")
        return features

    def _build_latest_features(self) -> Optional[pd.Series]:
        """Build today's feature vector for live prediction"""
        data = self._fetch_price_data(years=1)
        if data.empty:
            return None

        features = self.build_features(data)

        # Fill point-in-time features for the latest row
        funding_rate = self._fetch_funding_rate()
        fear_greed = self._fetch_fear_greed()

        if funding_rate is not None:
            features.loc[features.index[-1], 'funding_rate'] = funding_rate
        if fear_greed is not None:
            features.loc[features.index[-1], 'fear_greed_index'] = fear_greed

        available = [f for f in self.FEATURE_NAMES if f in features.columns]
        latest = features[available].iloc[-1]

        if latest.isna().sum() > len(available) // 2:
            logger.warning("Too many NaN in latest features")
            return None

        # Fill remaining NaN with column median
        for col in available:
            if pd.isna(latest[col]):
                col_median = features[col].median()
                latest[col] = col_median if not pd.isna(col_median) else 0

        return latest

    # ------------------------------------------------------------------
    # Model Training
    # ------------------------------------------------------------------

    def train_model(self, df: pd.DataFrame) -> Dict:
        """Train multi-algorithm ensemble with TimeSeriesSplit CV

        Algorithms: GradientBoosting (x3 seeds), RandomForest,
                    HistGradientBoosting, LogisticRegression
        """
        logger.info("Training BTC prediction multi-model ensemble...")

        try:
            from sklearn.ensemble import (
                GradientBoostingClassifier,
                RandomForestClassifier,
                HistGradientBoostingClassifier,
            )
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import TimeSeriesSplit
            from sklearn.preprocessing import StandardScaler
            from sklearn.metrics import accuracy_score
            import joblib
        except ImportError:
            logger.error("scikit-learn or joblib not installed")
            return {'error': 'scikit-learn not installed'}

        model_configs = [
            {
                'name': 'GradientBoosting',
                'create': lambda seed: GradientBoostingClassifier(
                    n_estimators=150, max_depth=3, learning_rate=0.05,
                    subsample=0.8, min_samples_leaf=10, random_state=seed,
                ),
                'seeds': self.ENSEMBLE_SEEDS,
            },
            {
                'name': 'RandomForest',
                'create': lambda seed: RandomForestClassifier(
                    n_estimators=200, max_depth=6, min_samples_leaf=10,
                    max_features='sqrt', random_state=seed,
                ),
                'seeds': [42],
            },
            {
                'name': 'HistGradientBoosting',
                'create': lambda seed: HistGradientBoostingClassifier(
                    max_iter=150, max_depth=4, learning_rate=0.05,
                    min_samples_leaf=10, random_state=seed,
                ),
                'seeds': [42],
            },
            {
                'name': 'LogisticRegression',
                'create': lambda seed: LogisticRegression(
                    C=1.0, max_iter=1000, solver='lbfgs', random_state=seed,
                ),
                'seeds': [42],
            },
        ]

        available_features = [f for f in self.FEATURE_NAMES if f in df.columns]
        if len(available_features) < 5:
            return {'error': f'Insufficient features: {len(available_features)}'}

        train_df = df.dropna(subset=['target'])
        if len(train_df) < 100:
            return {'error': f'Insufficient training samples: {len(train_df)}'}

        X = train_df[available_features].fillna(0).values
        y = train_df['target'].values

        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            return {'error': f'Only one class in training data: {unique_classes}'}

        # TimeSeriesSplit CV — per-model + ensemble accuracy
        tscv = TimeSeriesSplit(n_splits=5)
        model_cv_results = {cfg['name']: [] for cfg in model_configs}
        ensemble_cv_results = []

        for train_idx, test_idx in tscv.split(X):
            X_train_raw, X_test_raw = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            fold_scaler = StandardScaler()
            X_train = fold_scaler.fit_transform(X_train_raw)
            X_test = fold_scaler.transform(X_test_raw)

            if len(np.unique(y_train)) < 2:
                continue

            all_fold_probas = []

            for cfg in model_configs:
                model_probas = []
                for seed in cfg['seeds']:
                    clf = cfg['create'](seed)
                    clf.fit(X_train, y_train)
                    proba = clf.predict_proba(X_test)
                    model_probas.append(proba)

                avg_model_proba = np.mean(model_probas, axis=0)
                all_fold_probas.append(avg_model_proba)

                y_pred = (avg_model_proba[:, 1] >= 0.5).astype(int)
                model_cv_results[cfg['name']].append(accuracy_score(y_test, y_pred))

            # Ensemble: average across all model types
            ensemble_proba = np.mean(all_fold_probas, axis=0)
            y_ensemble = (ensemble_proba[:, 1] >= 0.5).astype(int)
            ensemble_cv_results.append(accuracy_score(y_test, y_ensemble))

        if not ensemble_cv_results:
            return {'error': 'No valid CV folds'}

        mean_ensemble_accuracy = round(np.mean(ensemble_cv_results) * 100, 1)

        for name, accs in model_cv_results.items():
            if accs:
                logger.info(f"  {name} CV accuracy: {round(np.mean(accs) * 100, 1)}%")
        logger.info(f"  Ensemble CV accuracy: {mean_ensemble_accuracy}%")

        # Final training on all data
        final_scaler = StandardScaler()
        X_scaled = final_scaler.fit_transform(X)

        all_classifiers = {}
        all_importances = np.zeros(len(available_features))
        importance_count = 0

        for cfg in model_configs:
            classifiers = []
            for seed in cfg['seeds']:
                clf = cfg['create'](seed)
                clf.fit(X_scaled, y)
                classifiers.append(clf)

                if hasattr(clf, 'feature_importances_'):
                    all_importances += clf.feature_importances_
                    importance_count += 1
                elif hasattr(clf, 'coef_'):
                    all_importances += np.abs(clf.coef_[0])
                    importance_count += 1

            all_classifiers[cfg['name']] = classifiers

        avg_importances = all_importances / importance_count if importance_count > 0 else all_importances
        importances = dict(zip(available_features, avg_importances))
        top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]

        # Model details
        model_details = {}
        for name, accs in model_cv_results.items():
            if accs:
                model_details[name] = {
                    'accuracy': round(np.mean(accs) * 100, 1),
                    'models_count': len(all_classifiers.get(name, [])),
                }

        # Save model
        model_data = {
            'all_classifiers': all_classifiers,
            'classifiers': all_classifiers.get('GradientBoosting', []),
            'scaler': final_scaler,
            'features': available_features,
            'trained_at': datetime.now().isoformat(),
            'training_samples': len(X),
            'cv_accuracy': mean_ensemble_accuracy,
            'avg_importances': avg_importances.tolist(),
            'model_details': model_details,
        }

        os.makedirs(self.output_dir, exist_ok=True)
        joblib.dump(model_data, self.model_path)

        total_models = sum(len(clfs) for clfs in all_classifiers.values())
        logger.info(f"Saved {total_models} models ({len(model_configs)} algorithms) to {self.model_path}")

        return {
            'accuracy': mean_ensemble_accuracy,
            'training_samples': len(X),
            'features_used': len(available_features),
            'top_features': [{'feature': f, 'importance': round(i, 4)} for f, i in top_features],
            'model_details': model_details,
        }

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def _get_driver_direction(self, feature_name: str, value: float) -> str:
        """Determine bullish/bearish direction based on feature value"""
        # VIX features are inverse (high VIX = bearish for crypto)
        if feature_name in self.INVERSE_FEATURES:
            if 'vix_level' == feature_name:
                if value > 25:
                    return 'bearish'
                elif value < 15:
                    return 'bullish'
                return 'bearish' if value > 20 else 'bullish'
            if 'vix_percentile_60d' == feature_name:
                return 'bearish' if value > 0.7 else 'bullish'
            # dxy_return_5d
            return 'bearish' if value > 0 else 'bullish'

        if 'rsi' in feature_name:
            if value > 70:
                return 'bearish'
            elif value < 30:
                return 'bullish'
            return 'bullish' if value > 50 else 'bearish'

        if 'bb_position' in feature_name:
            if value > 0.8:
                return 'bearish'
            elif value < 0.2:
                return 'bullish'
            return 'bullish' if value > 0.5 else 'bearish'

        if 'macd_signal' in feature_name:
            return 'bullish' if value > 0 else 'bearish'

        if 'above_ma' in feature_name:
            return 'bullish' if value > 0.5 else 'bearish'

        if 'fear_greed' in feature_name:
            # Contrarian: extreme greed -> bearish, extreme fear -> bullish
            if value > 75:
                return 'bearish'
            elif value < 25:
                return 'bullish'
            return 'bullish' if value > 50 else 'bearish'

        if 'funding_rate' in feature_name:
            # High positive funding = over-leveraged longs -> bearish signal
            if value > 0.0005:
                return 'bearish'
            elif value < -0.0003:
                return 'bullish'
            return 'neutral'

        if 'tlt_return' in feature_name:
            # TLT up = risk-off, mildly bearish for crypto
            return 'bearish' if value > 0 else 'bullish'

        return 'bullish' if value > 0 else 'bearish'

    def _update_prediction_history(self, bullish_prob: float, btc_price: float) -> None:
        """Append prediction to history file. Keep max 90 entries."""
        entry = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'bullish_probability': bullish_prob,
            'btc_price': round(btc_price, 2),
        }

        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                if not isinstance(history, list):
                    history = []
            except Exception:
                history = []

        # Avoid duplicate entries for the same date
        today_str = entry['date']
        history = [h for h in history if h.get('date') != today_str]

        history.append(entry)

        # Keep only the most recent entries
        if len(history) > self.HISTORY_MAX_ENTRIES:
            history = history[-self.HISTORY_MAX_ENTRIES:]

        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        logger.info(f"Updated prediction history ({len(history)} entries)")

    def predict(self) -> Dict:
        """Generate prediction using trained ensemble model"""
        logger.info("Generating BTC prediction...")

        try:
            import joblib
        except ImportError:
            return {'error': 'joblib not installed'}

        # Check if model needs retraining
        need_retrain = True
        model_data = None

        if os.path.exists(self.model_path):
            try:
                model_data = joblib.load(self.model_path)
                trained_at = datetime.fromisoformat(model_data['trained_at'])
                if (datetime.now() - trained_at).days <= self.RETRAIN_INTERVAL_DAYS:
                    need_retrain = False
                    logger.info(f"Using existing model (trained {(datetime.now() - trained_at).days}d ago)")
            except Exception:
                pass

        train_info = {}
        if need_retrain:
            train_df = self._build_training_dataset()
            if train_df.empty:
                return {'error': 'Could not build training dataset'}

            train_info = self.train_model(train_df)
            if 'error' in train_info:
                return train_info

            try:
                model_data = joblib.load(self.model_path)
            except Exception as e:
                return {'error': f'Model load failed: {e}'}

        # Build latest feature vector
        latest_features = self._build_latest_features()
        if latest_features is None:
            return {'error': 'Could not build latest features'}

        model_features = model_data['features']
        feature_vector = np.array([
            float(latest_features.get(f, 0)) if f in latest_features.index else 0.0
            for f in model_features
        ])

        X_latest = feature_vector.reshape(1, -1)
        scaler = model_data['scaler']
        X_scaled = scaler.transform(X_latest)

        # Load all model types (backward compat with old single-algorithm format)
        all_classifiers = model_data.get('all_classifiers', {})
        if not all_classifiers:
            gb_clfs = model_data.get('classifiers', [])
            if not gb_clfs and 'classifier' in model_data:
                gb_clfs = [model_data['classifier']]
            all_classifiers = {'GradientBoosting': gb_clfs}

        # Ensemble prediction across all model types
        per_model_predictions = {}
        try:
            all_probas = []

            for model_name, classifiers in all_classifiers.items():
                model_probas = []
                for clf in classifiers:
                    proba = clf.predict_proba(X_scaled)[0]
                    if len(proba) == 2:
                        model_probas.append(proba)

                if model_probas:
                    avg_proba = np.mean(model_probas, axis=0)
                    all_probas.append(avg_proba)
                    per_model_predictions[model_name] = {
                        'bullish': round(float(avg_proba[1]) * 100, 1),
                        'bearish': round(float(avg_proba[0]) * 100, 1),
                    }

            if all_probas:
                ensemble_proba = np.mean(all_probas, axis=0)
                bearish_prob = round(float(ensemble_proba[0]) * 100, 1)
                bullish_prob = round(float(ensemble_proba[1]) * 100, 1)
            else:
                bullish_prob, bearish_prob = 50.0, 50.0
        except Exception:
            bullish_prob, bearish_prob = 50.0, 50.0

        # Current BTC price
        try:
            btc = yf.Ticker('BTC-USD')
            hist = btc.history(period='5d')
            current_price = float(hist['Close'].iloc[-1]) if not hist.empty else 0
        except Exception:
            current_price = 0

        # Confidence level
        max_prob = max(bullish_prob, bearish_prob)
        if max_prob >= 70:
            confidence = 'High'
        elif max_prob >= 60:
            confidence = 'Moderate'
        else:
            confidence = 'Low'

        # Key drivers from averaged importances
        avg_importances = model_data.get('avg_importances', None)
        if avg_importances is not None:
            importances = dict(zip(model_features, avg_importances))
        else:
            # Fallback: use first classifier's importances
            importances = dict(zip(model_features, classifiers[0].feature_importances_))

        key_drivers = []
        for feat, imp in sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]:
            val = float(latest_features.get(feat, 0)) if feat in latest_features.index else 0.0
            direction = self._get_driver_direction(feat, val)
            key_drivers.append({
                'feature': feat,
                'impact': round(float(imp), 4),
                'value': round(val, 2),
                'direction': direction,
            })

        cv_accuracy = train_info.get('accuracy', model_data.get('cv_accuracy', None))

        # Update prediction history
        self._update_prediction_history(bullish_prob, current_price)

        # Build per-model details for output
        model_details = model_data.get('model_details', {})
        ensemble_models = []
        for name, details in model_details.items():
            entry = {
                'name': name,
                'accuracy': details.get('accuracy'),
            }
            if name in per_model_predictions:
                entry['bullish'] = per_model_predictions[name]['bullish']
            ensemble_models.append(entry)

        return {
            'predictions': {
                'BTC': {
                    'current_price': round(current_price, 2),
                    'bullish_probability': bullish_prob,
                    'bearish_probability': bearish_prob,
                    'confidence_level': confidence,
                    'key_drivers': key_drivers,
                },
            },
            'model_info': {
                'algorithm': 'Multi-Model Ensemble',
                'ensemble_models': ensemble_models,
                'training_accuracy': cv_accuracy,
                'training_samples': model_data.get('training_samples', 0),
                'last_trained': model_data.get('trained_at', ''),
            },
        }

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> Dict:
        """Main entry: build features -> train if stale -> predict -> save"""
        logger.info("Starting BTC prediction pipeline...")

        prediction = self.predict()

        if 'error' in prediction:
            logger.error(f"Prediction failed: {prediction['error']}")
            result = {
                'timestamp': datetime.now().isoformat(),
                'predictions': {},
                'model_info': {},
                'disclaimer': 'Statistical model prediction. Not investment advice.',
            }
        else:
            result = {
                'timestamp': datetime.now().isoformat(),
                **prediction,
                'disclaimer': 'Statistical model prediction. Not investment advice. Investment decisions are your own responsibility.',
            }

        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved prediction to {self.output_file}")
        return result


if __name__ == '__main__':
    predictor = CryptoPredictor(
        data_dir=os.path.dirname(os.path.abspath(__file__))
    )
    result = predictor.run()

    print("\n" + "=" * 60)
    print("BTC DIRECTION PREDICTION (v2.0 Ensemble)")
    print("=" * 60)

    for coin, pred in result.get('predictions', {}).items():
        print(f"\n {coin}:")
        print(f"   Current Price:  ${pred['current_price']:,.2f}")
        print(f"   Bullish:        {pred['bullish_probability']}%")
        print(f"   Bearish:        {pred['bearish_probability']}%")
        print(f"   Confidence:     {pred['confidence_level']}")

        print(f"\n   Key Drivers:")
        for d in pred.get('key_drivers', []):
            icon = '+' if d['direction'] == 'bullish' else '-'
            print(f"     {icon} {d['feature']:25} = {d['value']:>8.2f} (impact: {d['impact']:.4f})")

    model = result.get('model_info', {})
    if model:
        print(f"\n Model: {model.get('algorithm', 'N/A')}")
        if model.get('ensemble_models'):
            for m in model['ensemble_models']:
                bull = m.get('bullish', '-')
                print(f"   - {m['name']:25} Acc: {m.get('accuracy', 'N/A')}%  Bull: {bull}%")
        print(f"   Ensemble Accuracy: {model.get('training_accuracy', 'N/A')}%")
        print(f"   Samples:   {model.get('training_samples', 0)}")
        print(f"   Trained:   {model.get('last_trained', 'N/A')}")

    print(f"\n {result.get('disclaimer', '')}")
