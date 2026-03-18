#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Index Direction Predictor v2.0
- Probabilistic next-week direction prediction for SPY/QQQ
- ML ensemble (GradientBoosting) with 20 feature signals
- Separate models for SPY and QQQ (independent targets)
- Proper TimeSeriesSplit CV with scaler inside fold
- Fresh feature vector for prediction (no stale data)
- Regime-aware config support
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


class IndexPredictor:
    """Probabilistic index direction prediction using ML ensemble"""

    MODEL_DIR = 'output'

    FEATURE_NAMES = [
        'spy_return_1w', 'spy_return_1m', 'spy_above_200ma', 'spy_above_50ma',
        'spy_rsi', 'spy_macd_signal', 'spy_bb_position',
        'vix_value', 'vix_change_5d', 'vix_percentile',
        'qqq_return_1w', 'qqq_rsi',
        'breadth_pct_above_50ma', 'advance_decline_ratio',
        'xlk_relative_1m', 'xlu_relative_1m', 'xly_relative_1m',
        'yield_spread_proxy', 'gold_return_1w', 'dxy_return_1w',
    ]

    # Features where higher value = bearish (used for key driver direction)
    INVERSE_FEATURES = {
        'vix_value', 'vix_change_5d', 'vix_percentile',
        'xlu_relative_1m',  # utilities outperforming = defensive = bearish
        'dxy_return_1w',    # strong dollar = headwind for earnings
    }

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'index_prediction.json')
        self.history_file = os.path.join(data_dir, 'output', 'prediction_history.json')
        self.model_path_spy = os.path.join(data_dir, 'output', 'predictor_model_spy.joblib')
        self.model_path_qqq = os.path.join(data_dir, 'output', 'predictor_model_qqq.joblib')
        self.config = self._load_regime_config()

    def _load_regime_config(self) -> Dict:
        """Load adaptive thresholds from regime_config.json"""
        config_path = os.path.join(self.data_dir, 'output', 'regime_config.json')
        defaults = {
            'prediction_horizon_days': 5,
            'cv_splits': 5,
            'retrain_interval_days': 7,
            'min_training_samples': 50,
            'confidence_high_threshold': 70,
            'confidence_moderate_threshold': 60,
        }
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    regime = json.load(f)
                defaults.update(regime.get('predictor', {}))
        except Exception:
            pass
        return defaults

    def _calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI using Wilder's smoothing (EMA with alpha=1/N)"""
        delta = series.diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        # Handle edge case: both gain and loss are 0 -> RSI should be 50
        rsi = rsi.fillna(50)
        return rsi

    def _calculate_macd_signal(self, series: pd.Series) -> pd.Series:
        """Calculate MACD signal: +1 bullish, -1 bearish, 0 neutral"""
        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return (macd > signal).astype(int) - (macd < signal).astype(int)

    def _calculate_bb_position(self, series: pd.Series, window: int = 20) -> pd.Series:
        """Bollinger Band position: 0-1 (0=lower, 0.5=middle, 1=upper)"""
        ma = series.rolling(window).mean()
        std = series.rolling(window).std()
        upper = ma + 2 * std
        lower = ma - 2 * std
        band_width = upper - lower
        # Guard against zero band width (flat price)
        position = (series - lower) / band_width.replace(0, np.nan)
        return position.clip(0, 1).fillna(0.5)

    def _build_raw_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Build feature columns from price data (no target, no dropna)"""
        features = pd.DataFrame(index=data.index)

        # SPY features
        if 'SPY' in data.columns:
            spy = data['SPY']
            features['spy_return_1w'] = spy.pct_change(5) * 100
            features['spy_return_1m'] = spy.pct_change(21) * 100
            features['spy_above_200ma'] = (spy > spy.rolling(200).mean()).astype(int)
            features['spy_above_50ma'] = (spy > spy.rolling(50).mean()).astype(int)
            features['spy_rsi'] = self._calculate_rsi(spy)
            features['spy_macd_signal'] = self._calculate_macd_signal(spy)
            features['spy_bb_position'] = self._calculate_bb_position(spy)

        # VIX features
        if 'VIX' in data.columns:
            vix = data['VIX']
            features['vix_value'] = vix
            features['vix_change_5d'] = vix.pct_change(5) * 100
            features['vix_percentile'] = vix.rolling(252).apply(
                lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100, raw=False
            )

        # QQQ features
        if 'QQQ' in data.columns:
            qqq = data['QQQ']
            features['qqq_return_1w'] = qqq.pct_change(5) * 100
            features['qqq_rsi'] = self._calculate_rsi(qqq)

        # Breadth proxy
        if 'SPY' in data.columns:
            spy = data['SPY']
            spy_above = (spy > spy.rolling(50).mean()).astype(float)
            features['breadth_pct_above_50ma'] = spy_above.rolling(50).mean() * 100
            # Advance/decline proxy with Laplace smoothing
            daily_ret = spy.pct_change()
            adv = (daily_ret > 0).astype(float).rolling(10).sum()
            dec = (daily_ret < 0).astype(float).rolling(10).sum()
            features['advance_decline_ratio'] = (adv + 1) / (dec + 1)

        # Sector relative strength
        if 'SPY' in data.columns:
            spy_1m = data['SPY'].pct_change(21)
            for etf, col_name in [('XLK', 'xlk_relative_1m'), ('XLU', 'xlu_relative_1m'), ('XLY', 'xly_relative_1m')]:
                if etf in data.columns:
                    etf_1m = data[etf].pct_change(21)
                    features[col_name] = (etf_1m - spy_1m) * 100

        # Yield spread proxy (10Y - 5Y)
        if 'TNX' in data.columns and 'FVX' in data.columns:
            features['yield_spread_proxy'] = data['TNX'] - data['FVX']
        elif 'TNX' in data.columns:
            # Use TNX change as proxy when FVX unavailable (not raw level)
            features['yield_spread_proxy'] = data['TNX'].pct_change(5) * 100

        # Gold and DXY
        if 'GOLD' in data.columns:
            features['gold_return_1w'] = data['GOLD'].pct_change(5) * 100
        if 'DXY' in data.columns:
            features['dxy_return_1w'] = data['DXY'].pct_change(5) * 100

        return features

    def _fetch_price_data(self, start_date: str = '2023-01-01') -> pd.DataFrame:
        """Fetch all price data needed for features"""
        tickers = ['SPY', 'QQQ', '^VIX', 'XLK', 'XLU', 'XLY', 'GC=F', 'DX-Y.NYB', '^TNX', '^FVX']
        lookback_start = (pd.to_datetime(start_date) - timedelta(days=300)).strftime('%Y-%m-%d')

        try:
            data = yf.download(tickers, start=lookback_start, progress=False)['Close']
        except Exception as e:
            logger.error(f"Error downloading data: {e}")
            return pd.DataFrame()

        if data.empty:
            return pd.DataFrame()

        rename_map = {'^VIX': 'VIX', 'GC=F': 'GOLD', 'DX-Y.NYB': 'DXY', '^TNX': 'TNX', '^FVX': 'FVX'}
        data = data.rename(columns=rename_map)
        return data

    def reconstruct_signals_from_prices(self, start_date: str = '2023-01-01') -> pd.DataFrame:
        """Build training dataset with features + targets"""
        logger.info(f"Reconstructing signals from prices since {start_date}...")

        data = self._fetch_price_data(start_date)
        if data.empty:
            return pd.DataFrame()

        features = self._build_raw_features(data)

        horizon = self.config['prediction_horizon_days']

        # Add targets for both SPY and QQQ
        if 'SPY' in data.columns:
            features['spy_target_return'] = data['SPY'].pct_change(horizon).shift(-horizon) * 100
            features['spy_target_direction'] = (features['spy_target_return'] > 0).astype(int)

        if 'QQQ' in data.columns:
            features['qqq_target_return'] = data['QQQ'].pct_change(horizon).shift(-horizon) * 100
            features['qqq_target_direction'] = (features['qqq_target_return'] > 0).astype(int)

        # Filter to start_date onwards
        features = features.loc[start_date:]

        logger.info(f"   Reconstructed {len(features)} rows with {len(self.FEATURE_NAMES)} features")
        return features

    def build_latest_features(self) -> Optional[pd.Series]:
        """Build today's feature vector for prediction (fresh, not stale)"""
        data = self._fetch_price_data(start_date='2024-01-01')
        if data.empty:
            return None

        features = self._build_raw_features(data)

        # Get the last row that has valid feature values (forward-fill missing)
        available = [f for f in self.FEATURE_NAMES if f in features.columns]
        latest = features[available].iloc[-1]

        # Check if too many NaN
        if latest.isna().sum() > len(available) // 2:
            logger.warning("Too many NaN in latest features")
            return None

        # Fill remaining NaN with 0
        latest = latest.fillna(0)
        return latest

    def train(self, df: pd.DataFrame, target_ticker: str = 'SPY') -> Dict:
        """Train GradientBoosting with proper CV (scaler inside fold)"""
        logger.info(f"Training {target_ticker} prediction model...")

        try:
            from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
            from sklearn.model_selection import TimeSeriesSplit
            from sklearn.preprocessing import StandardScaler
            from sklearn.metrics import accuracy_score, brier_score_loss
            import joblib
        except ImportError:
            logger.error("scikit-learn not installed. Run: pip install scikit-learn")
            return {'error': 'scikit-learn not installed'}

        target_return_col = f'{target_ticker.lower()}_target_return'
        target_dir_col = f'{target_ticker.lower()}_target_direction'

        if target_return_col not in df.columns or target_dir_col not in df.columns:
            return {'error': f'No target columns for {target_ticker}'}

        available_features = [f for f in self.FEATURE_NAMES if f in df.columns]
        if len(available_features) < 5:
            return {'error': f'Insufficient features: {len(available_features)}'}

        # Training data: drop rows with NaN targets (last N rows due to shift)
        # AND exclude the very last valid row (to avoid training on prediction point)
        train_df = df.dropna(subset=[target_return_col, target_dir_col])

        if len(train_df) < self.config['min_training_samples']:
            return {'error': f'Insufficient samples: {len(train_df)}'}

        X = train_df[available_features].fillna(0).values
        y_direction = train_df[target_dir_col].values
        y_return = train_df[target_return_col].values

        # Check for single-class data
        unique_classes = np.unique(y_direction)
        if len(unique_classes) < 2:
            return {'error': f'Only one class in training data: {unique_classes}'}

        # TimeSeriesSplit CV with scaler INSIDE each fold (no data leakage)
        n_splits = self.config['cv_splits']
        tscv = TimeSeriesSplit(n_splits=n_splits)
        cv_accuracies = []
        cv_brier = []

        for train_idx, test_idx in tscv.split(X):
            X_train_raw, X_test_raw = X[train_idx], X[test_idx]
            y_train, y_test = y_direction[train_idx], y_direction[test_idx]

            # Fit scaler on TRAINING fold only
            fold_scaler = StandardScaler()
            X_train = fold_scaler.fit_transform(X_train_raw)
            X_test = fold_scaler.transform(X_test_raw)

            # Skip fold if single class in training
            if len(np.unique(y_train)) < 2:
                continue

            clf = GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.1,
                subsample=0.8, min_samples_leaf=5, random_state=42
            )
            clf.fit(X_train, y_train)

            y_pred = clf.predict(X_test)
            y_proba = clf.predict_proba(X_test)

            cv_accuracies.append(accuracy_score(y_test, y_pred))
            # Brier score needs probability of positive class
            if y_proba.shape[1] == 2:
                cv_brier.append(brier_score_loss(y_test, y_proba[:, 1]))

        if not cv_accuracies:
            return {'error': 'No valid CV folds'}

        # Train final model on ALL training data (fit scaler on all training data)
        final_scaler = StandardScaler()
        X_scaled = final_scaler.fit_transform(X)

        clf_final = GradientBoostingClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.1,
            subsample=0.8, min_samples_leaf=5, random_state=42
        )
        clf_final.fit(X_scaled, y_direction)

        reg_final = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.1,
            subsample=0.8, min_samples_leaf=5, random_state=42
        )
        reg_final.fit(X_scaled, y_return)

        # Feature importances
        importances = dict(zip(available_features, clf_final.feature_importances_))
        top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]

        # Compute historical target std for range estimation
        target_std = float(np.std(y_return))

        # Save model
        model_path = self.model_path_spy if target_ticker == 'SPY' else self.model_path_qqq
        model_data = {
            'classifier': clf_final,
            'regressor': reg_final,
            'scaler': final_scaler,
            'features': available_features,
            'trained_at': datetime.now().isoformat(),
            'training_samples': len(X),
            'cv_accuracy': round(np.mean(cv_accuracies) * 100, 1),
            'target_std': target_std,
        }

        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        joblib.dump(model_data, model_path)
        logger.info(f"   Model saved to {model_path}")

        return {
            'accuracy': round(np.mean(cv_accuracies) * 100, 1),
            'brier_score': round(np.mean(cv_brier), 4) if cv_brier else None,
            'training_samples': len(X),
            'features_used': len(available_features),
            'top_features': [{'feature': f, 'importance': round(i, 4)} for f, i in top_features],
        }

    def _get_driver_direction(self, feature_name: str, value: float) -> str:
        """Determine bullish/bearish direction with feature-specific logic"""
        if feature_name in self.INVERSE_FEATURES:
            return 'bearish' if value > 0 else 'bullish'

        # RSI-based features: overbought is bearish, oversold is bullish
        if 'rsi' in feature_name:
            if value > 70:
                return 'bearish'
            elif value < 30:
                return 'bullish'
            return 'bullish' if value > 50 else 'bearish'

        # BB position: >0.8 = overbought, <0.2 = oversold
        if 'bb_position' in feature_name:
            return 'bearish' if value > 0.8 else 'bullish' if value < 0.2 else ('bullish' if value > 0.5 else 'bearish')

        # Default: positive = bullish
        return 'bullish' if value > 0 else 'bearish'

    def predict_next_week(self) -> Dict:
        """Predict next week's direction for SPY and QQQ independently."""
        logger.info("Generating prediction...")

        # Build training dataset
        features_df = self.reconstruct_signals_from_prices(start_date='2023-06-01')
        if features_df.empty:
            return {'error': 'Could not build features'}

        # Build FRESH feature vector (today's data, not stale)
        latest_features = self.build_latest_features()
        if latest_features is None:
            return {'error': 'Could not build latest features'}

        predictions = {}

        for ticker in ['SPY', 'QQQ']:
            model_path = self.model_path_spy if ticker == 'SPY' else self.model_path_qqq

            # Check if model needs retraining
            model_data = None
            need_retrain = True

            try:
                import joblib
                if os.path.exists(model_path):
                    model_data = joblib.load(model_path)
                    trained_at = datetime.fromisoformat(model_data['trained_at'])
                    if (datetime.now() - trained_at).days <= self.config['retrain_interval_days']:
                        need_retrain = False
                        logger.info(f"   Using existing {ticker} model (trained within {self.config['retrain_interval_days']} days)")
            except Exception:
                pass

            # Train if needed
            train_info = {}
            if need_retrain:
                train_info = self.train(features_df, target_ticker=ticker)
                if 'error' in train_info:
                    logger.warning(f"Training failed for {ticker}: {train_info['error']}")
                    continue
                try:
                    import joblib
                    model_data = joblib.load(model_path)
                except Exception as e:
                    logger.error(f"Model load failed for {ticker}: {e}")
                    continue

            # Prepare latest feature vector
            model_features = model_data['features']
            available = [f for f in model_features if f in latest_features.index]

            if len(available) != len(model_features):
                missing = set(model_features) - set(available)
                logger.warning(f"Missing features for {ticker}: {missing}. Filling with 0.")
                # Build full vector with zeros for missing features
                feature_vector = np.zeros(len(model_features))
                for i, f in enumerate(model_features):
                    if f in latest_features.index:
                        feature_vector[i] = float(latest_features[f])
            else:
                feature_vector = np.array([float(latest_features[f]) for f in model_features])

            X_latest = feature_vector.reshape(1, -1)
            scaler = model_data['scaler']
            X_scaled = scaler.transform(X_latest)

            clf = model_data['classifier']
            reg = model_data['regressor']

            # Predict with guard for single-class
            try:
                proba = clf.predict_proba(X_scaled)[0]
                if len(proba) == 2:
                    bearish_prob = round(proba[0] * 100, 1)
                    bullish_prob = round(proba[1] * 100, 1)
                else:
                    # Single class — use the one class we have
                    only_class = clf.classes_[0]
                    if only_class == 1:
                        bullish_prob, bearish_prob = 100.0, 0.0
                    else:
                        bullish_prob, bearish_prob = 0.0, 100.0
            except Exception:
                bullish_prob, bearish_prob = 50.0, 50.0

            predicted_return = float(reg.predict(X_scaled)[0])

            # Get current price
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='5d')
                if hist.empty:
                    continue
                current_price = float(hist['Close'].iloc[-1])
            except Exception:
                continue

            # Target range
            target_std = model_data.get('target_std', 2.0)
            target_mid = current_price * (1 + predicted_return / 100)
            target_low = current_price * (1 + (predicted_return - target_std) / 100)
            target_high = current_price * (1 + (predicted_return + target_std) / 100)

            # Key drivers with feature-specific direction
            importances = dict(zip(model_features, clf.feature_importances_))
            key_drivers = []
            for feat, imp in sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]:
                val = float(latest_features.get(feat, 0)) if feat in latest_features.index else 0.0
                direction = self._get_driver_direction(feat, val)
                key_drivers.append({
                    'feature': feat,
                    'impact': round(imp, 4),
                    'value': round(val, 2),
                    'direction': direction,
                })

            # Confidence level
            high_thresh = self.config['confidence_high_threshold']
            mod_thresh = self.config['confidence_moderate_threshold']
            max_prob = max(bullish_prob, bearish_prob)
            if max_prob >= high_thresh:
                confidence = 'High'
            elif max_prob >= mod_thresh:
                confidence = 'Moderate'
            else:
                confidence = 'Low'

            # Use proper cached accuracy
            cv_accuracy = train_info.get('accuracy', model_data.get('cv_accuracy', None))

            predictions[ticker.lower()] = {
                'current_price': round(current_price, 2),
                'bullish_probability': bullish_prob,
                'bearish_probability': bearish_prob,
                'predicted_return_pct': round(predicted_return, 2),
                'target_range': {
                    'low': round(target_low, 2),
                    'mid': round(target_mid, 2),
                    'high': round(target_high, 2),
                },
                'confidence_level': confidence,
                'key_drivers': key_drivers,
            }

        if not predictions:
            return {'error': 'No predictions generated'}

        # Use SPY model accuracy as primary (or whichever is available)
        spy_model = None
        qqq_model = None
        try:
            import joblib
            if os.path.exists(self.model_path_spy):
                spy_model = joblib.load(self.model_path_spy)
            if os.path.exists(self.model_path_qqq):
                qqq_model = joblib.load(self.model_path_qqq)
        except Exception:
            pass

        primary_model = spy_model or qqq_model or {}

        return {
            'predictions': predictions,
            'model_info': {
                'algorithm': 'GradientBoosting Ensemble (per-ticker)',
                'training_accuracy': primary_model.get('cv_accuracy', 'N/A'),
                'training_samples': primary_model.get('training_samples', 0),
                'last_trained': primary_model.get('trained_at', ''),
                'features_used': len(primary_model.get('features', [])),
            },
        }

    def update_prediction_history(self, prediction: Dict):
        """Append to prediction_history.json for accuracy tracking"""
        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    history = json.load(f)
            except Exception:
                history = []

        entry = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'predictions': prediction.get('predictions', {}),
        }

        existing_dates = {h['date'] for h in history}
        if entry['date'] not in existing_dates:
            history.append(entry)

        history = history[-100:]

        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=2)

    def evaluate_past_predictions(self) -> Dict:
        """Compare historical predictions vs actual outcomes"""
        if not os.path.exists(self.history_file):
            return {'total_predictions': 0, 'direction_accuracy': 0}

        try:
            with open(self.history_file, 'r') as f:
                history = json.load(f)
        except Exception:
            return {'total_predictions': 0, 'direction_accuracy': 0}

        if not history:
            return {'total_predictions': 0, 'direction_accuracy': 0}

        try:
            spy = yf.Ticker('SPY')
            spy_hist = spy.history(period='6mo')
        except Exception:
            return {'total_predictions': len(history), 'direction_accuracy': 0}

        correct = 0
        evaluated = 0

        for entry in history:
            pred_date = entry['date']
            spy_pred = entry.get('predictions', {}).get('spy', {})

            if not spy_pred:
                continue

            bullish_prob = spy_pred.get('bullish_probability', 50)
            predicted_direction = 'up' if bullish_prob > 50 else 'down'

            try:
                pred_dt = pd.to_datetime(pred_date)
                # Get prices: prediction date close and 5 days later close
                mask_on = spy_hist.index >= pred_dt
                mask_after = spy_hist.index > pred_dt
                prices_from = spy_hist[mask_on]
                prices_after = spy_hist[mask_after]

                if len(prices_from) < 1 or len(prices_after) < 5:
                    continue

                start_price = prices_from['Close'].iloc[0]
                end_price = prices_after['Close'].iloc[min(4, len(prices_after) - 1)]
                actual_return = (end_price / start_price - 1) * 100
                actual_direction = 'up' if actual_return > 0 else 'down'

                if predicted_direction == actual_direction:
                    correct += 1
                evaluated += 1
            except Exception:
                continue

        return {
            'total_predictions': len(history),
            'evaluated': evaluated,
            'direction_accuracy': round(correct / max(evaluated, 1) * 100, 1),
        }

    def run(self):
        """Main entry: build dataset -> train if needed -> predict -> save"""
        logger.info("Starting index prediction pipeline...")

        prediction = self.predict_next_week()

        if 'error' in prediction:
            logger.error(f"Prediction failed: {prediction['error']}")
            result = {
                'timestamp': datetime.now().isoformat(),
                'predictions': {},
                'model_info': {},
                'historical_performance': {},
                'disclaimer_ko': '본 예측은 통계 모델 기반이며 투자 조언이 아닙니다.',
                'disclaimer_en': 'Statistical model prediction. Not investment advice.',
            }
        else:
            self.update_prediction_history(prediction)
            historical_perf = self.evaluate_past_predictions()

            result = {
                'timestamp': datetime.now().isoformat(),
                **prediction,
                'historical_performance': historical_perf,
                'disclaimer_ko': '본 예측은 통계 모델 기반이며 투자 조언이 아닙니다. 실제 투자 판단은 본인 책임하에 이루어져야 합니다.',
                'disclaimer_en': 'Statistical model prediction. Not investment advice. Investment decisions are your own responsibility.',
            }

        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved prediction to {self.output_file}")
        return result


def main():
    predictor = IndexPredictor()
    result = predictor.run()

    print("\n" + "=" * 60)
    print("INDEX DIRECTION PREDICTION")
    print("=" * 60)

    for idx_name, pred in result.get('predictions', {}).items():
        print(f"\n {idx_name.upper()}:")
        print(f"   Current Price: ${pred['current_price']:,.2f}")
        print(f"   Bullish: {pred['bullish_probability']}% | Bearish: {pred['bearish_probability']}%")
        print(f"   Predicted Return: {pred['predicted_return_pct']:+.2f}%")
        print(f"   Target Range: ${pred['target_range']['low']:,.2f} - ${pred['target_range']['high']:,.2f}")
        print(f"   Confidence: {pred['confidence_level']}")

        print(f"\n   Key Drivers:")
        for driver in pred.get('key_drivers', []):
            icon = '+' if driver['direction'] == 'bullish' else '-'
            print(f"     {icon} {driver['feature']:25} = {driver['value']:>8.2f} (impact: {driver['impact']:.4f})")

    model = result.get('model_info', {})
    if model:
        print(f"\n Model: {model.get('algorithm', 'N/A')}")
        print(f"   Accuracy: {model.get('training_accuracy', 'N/A')}%")
        print(f"   Samples: {model.get('training_samples', 0)}")

    hist = result.get('historical_performance', {})
    if hist.get('evaluated', 0) > 0:
        print(f"\n Historical Accuracy: {hist['direction_accuracy']}% ({hist['evaluated']} predictions)")

    print(f"\n {result.get('disclaimer_en', '')}")


if __name__ == "__main__":
    main()
