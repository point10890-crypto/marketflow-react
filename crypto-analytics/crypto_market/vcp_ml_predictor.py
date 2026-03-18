#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Signal ML Predictor

Trains ML models on historical backtest trade data to predict
which VCP signals are likely to be winners.

Features: c1/c2/c3 contraction ranges, vol_ratio, wick_ratio,
          ema_sep, above_ema50, atrp, breakout_close_pct,
          score, grade (encoded), market_regime (encoded),
          entry_type (encoded), liquidity_bucket (encoded)

Target: is_winner (binary: 1=WIN, 0=LOSS)

Usage:
    python3 vcp_ml_predictor.py                    # Train + evaluate
    python3 vcp_ml_predictor.py --predict score.json  # Predict on new signals
"""

import os
import json
import logging
import numpy as np
import joblib
from datetime import datetime
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
MODEL_PATH = os.path.join(OUTPUT_DIR, 'vcp_ml_model.joblib')
BACKTEST_PATH = os.path.join(OUTPUT_DIR, 'backtest_result.json')


# ===== Feature definitions =====

NUMERIC_FEATURES = [
    'score',
    'c1_range_pct',
    'c2_range_pct',
    'c3_range_pct',
    'vol_ratio',
    'wick_ratio',
    'ema_sep_pct',
    'above_ema50_ratio',
    'atrp_pct',
    'breakout_close_pct',
]

# Derived features computed from raw data
DERIVED_FEATURES = [
    'decay_r12',        # c1 / c2 ratio (contraction quality)
    'decay_r23',        # c2 / c3 ratio
    'c3_tightness',     # inverse of c3 (tighter = better)
    'vol_atr_ratio',    # vol_ratio / atrp (volume relative to volatility)
]

CATEGORICAL_FEATURES = [
    'entry_type',       # BREAKOUT, RETEST_OK, APPROACHING
    'grade',            # A, B, C, D
    'market_regime',    # BTC_UP, BTC_SIDE, BTC_DOWN
    'liquidity_bucket', # A, B, C
]


class VCPMLPredictor:
    """ML-based VCP signal win probability predictor"""

    def __init__(self):
        self.models = None
        self.scaler = None
        self.feature_names = None
        self.model_details = None

    # ===== Data loading =====

    def load_backtest_trades(self, path: str = None) -> list:
        """Load trade data from backtest result JSON"""
        path = path or BACKTEST_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"Backtest result not found: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        trades = data.get('trades', [])
        if not trades:
            raise ValueError("No individual trades found in backtest result. Re-run backtest.")

        logger.info(f"Loaded {len(trades)} trades from backtest")
        return trades

    # ===== Feature engineering =====

    def _build_features(self, trades: list) -> tuple:
        """Build feature matrix X and target vector y from trades"""
        import pandas as pd

        df = pd.DataFrame(trades)

        # Target
        y = df['is_winner'].astype(int).values

        # Numeric features
        X_num = df[NUMERIC_FEATURES].fillna(0).values

        # Derived features
        c1 = df['c1_range_pct'].values
        c2 = df['c2_range_pct'].values
        c3 = df['c3_range_pct'].values
        vol = df['vol_ratio'].values
        atrp = df['atrp_pct'].values

        decay_r12 = np.where(c2 > 0, c1 / c2, 1.0)
        decay_r23 = np.where(c3 > 0, c2 / c3, 1.0)
        c3_tightness = np.where(c3 > 0, 1.0 / c3, 0.0)
        vol_atr_ratio = np.where(atrp > 0, vol / atrp, 0.0)

        X_derived = np.column_stack([decay_r12, decay_r23, c3_tightness, vol_atr_ratio])

        # Categorical features (one-hot encode)
        cat_columns = []
        cat_names = []
        for feat in CATEGORICAL_FEATURES:
            col = df[feat].fillna('UNKNOWN')
            dummies = pd.get_dummies(col, prefix=feat, dtype=float)
            cat_columns.append(dummies.values)
            cat_names.extend(dummies.columns.tolist())

        X_cat = np.hstack(cat_columns) if cat_columns else np.empty((len(df), 0))

        # Combine all features
        X = np.hstack([X_num, X_derived, X_cat])
        feature_names = NUMERIC_FEATURES + DERIVED_FEATURES + cat_names

        logger.info(f"Feature matrix: {X.shape[0]} samples x {X.shape[1]} features")

        return X, y, feature_names

    def _build_single_features(self, signal_data: dict) -> np.ndarray:
        """Build features for a single signal (for prediction)"""
        if self.feature_names is None:
            raise ValueError("Model not trained yet")

        row = {}

        # Numeric
        for feat in NUMERIC_FEATURES:
            row[feat] = signal_data.get(feat, 0.0)

        # Derived
        c1 = row.get('c1_range_pct', 0)
        c2 = row.get('c2_range_pct', 0)
        c3 = row.get('c3_range_pct', 0)
        row['decay_r12'] = c1 / c2 if c2 > 0 else 1.0
        row['decay_r23'] = c2 / c3 if c3 > 0 else 1.0
        row['c3_tightness'] = 1.0 / c3 if c3 > 0 else 0.0
        row['vol_atr_ratio'] = row['vol_ratio'] / row['atrp_pct'] if row['atrp_pct'] > 0 else 0.0

        # Categorical (one-hot)
        for feat in CATEGORICAL_FEATURES:
            val = signal_data.get(feat, 'UNKNOWN')
            for fname in self.feature_names:
                if fname.startswith(f"{feat}_"):
                    row[fname] = 1.0 if fname == f"{feat}_{val}" else 0.0

        # Build vector in correct order
        vec = np.array([row.get(f, 0.0) for f in self.feature_names], dtype=float).reshape(1, -1)

        # Scale
        if self.scaler:
            vec = self.scaler.transform(vec)

        return vec

    # ===== Training =====

    def train(self, backtest_path: str = None) -> dict:
        """Train ML models on backtest trade data"""
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import TimeSeriesSplit

        trades = self.load_backtest_trades(backtest_path)
        X, y, feature_names = self._build_features(trades)

        self.feature_names = feature_names

        # Scale
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Model configs
        model_configs = [
            {
                'name': 'RandomForest',
                'create': lambda: RandomForestClassifier(
                    n_estimators=200, max_depth=6, min_samples_leaf=10,
                    max_features='sqrt', random_state=42, class_weight='balanced',
                ),
            },
            {
                'name': 'GradientBoosting',
                'create': lambda: GradientBoostingClassifier(
                    n_estimators=150, max_depth=3, learning_rate=0.05,
                    subsample=0.8, min_samples_leaf=10, random_state=42,
                ),
            },
            {
                'name': 'HistGradientBoosting',
                'create': lambda: HistGradientBoostingClassifier(
                    max_iter=150, max_depth=4, learning_rate=0.05,
                    min_samples_leaf=10, random_state=42,
                    class_weight='balanced',
                ),
            },
            {
                'name': 'LogisticRegression',
                'create': lambda: LogisticRegression(
                    C=1.0, max_iter=1000, solver='lbfgs',
                    random_state=42, class_weight='balanced',
                ),
            },
        ]

        # Cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        model_results = {}

        for mc in model_configs:
            name = mc['name']
            fold_accuracies = []

            for train_idx, val_idx in tscv.split(X_scaled):
                clf = mc['create']()
                clf.fit(X_scaled[train_idx], y[train_idx])
                acc = clf.score(X_scaled[val_idx], y[val_idx])
                fold_accuracies.append(acc)

            mean_acc = np.mean(fold_accuracies) * 100
            model_results[name] = {'accuracy': mean_acc, 'folds': fold_accuracies}
            logger.info(f"  {name}: CV Accuracy = {mean_acc:.1f}%")

        # Train final models on full data
        self.models = {}
        self.model_details = {}

        for mc in model_configs:
            name = mc['name']
            clf = mc['create']()
            clf.fit(X_scaled, y)
            self.models[name] = clf
            self.model_details[name] = {
                'accuracy': model_results[name]['accuracy'],
            }

        # Feature importance (from RandomForest)
        rf = self.models['RandomForest']
        importances = rf.feature_importances_
        importance_pairs = sorted(
            zip(feature_names, importances), key=lambda x: x[1], reverse=True
        )

        # Ensemble CV accuracy
        ensemble_accs = []
        for train_idx, val_idx in tscv.split(X_scaled):
            fold_probs = []
            for mc in model_configs:
                clf = mc['create']()
                clf.fit(X_scaled[train_idx], y[train_idx])
                proba = clf.predict_proba(X_scaled[val_idx])[:, 1]
                fold_probs.append(proba)
            ensemble_prob = np.mean(fold_probs, axis=0)
            ensemble_pred = (ensemble_prob >= 0.5).astype(int)
            ensemble_acc = np.mean(ensemble_pred == y[val_idx])
            ensemble_accs.append(ensemble_acc)

        ensemble_accuracy = np.mean(ensemble_accs) * 100

        # Save model
        model_data = {
            'models': self.models,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'model_details': self.model_details,
            'ensemble_accuracy': ensemble_accuracy,
            'trained_at': datetime.now().isoformat(),
            'training_samples': len(X),
            'win_rate_baseline': float(np.mean(y) * 100),
            'top_features': [(f, float(imp)) for f, imp in importance_pairs[:10]],
        }

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        joblib.dump(model_data, MODEL_PATH)
        logger.info(f"Model saved to {MODEL_PATH}")

        return {
            'ensemble_accuracy': ensemble_accuracy,
            'models': {k: v['accuracy'] for k, v in self.model_details.items()},
            'training_samples': len(X),
            'win_rate_baseline': float(np.mean(y) * 100),
            'feature_count': len(feature_names),
            'top_features': importance_pairs[:10],
        }

    # ===== Loading =====

    def load_model(self) -> bool:
        """Load trained model from disk"""
        if not os.path.exists(MODEL_PATH):
            return False

        data = joblib.load(MODEL_PATH)
        self.models = data['models']
        self.scaler = data['scaler']
        self.feature_names = data['feature_names']
        self.model_details = data.get('model_details', {})
        return True

    # ===== Prediction =====

    def predict(self, signal_data: dict) -> dict:
        """Predict win probability for a single VCP signal"""
        if self.models is None:
            if not self.load_model():
                raise ValueError("No trained model found. Run train() first.")

        X = self._build_single_features(signal_data)

        # Per-model predictions
        per_model = {}
        probs = []

        for name, clf in self.models.items():
            prob = clf.predict_proba(X)[0][1]  # P(WIN)
            probs.append(prob)
            per_model[name] = {
                'win_prob': round(prob * 100, 1),
                'accuracy': round(self.model_details.get(name, {}).get('accuracy', 0), 1),
            }

        # Ensemble
        ensemble_prob = np.mean(probs) * 100

        return {
            'win_probability': round(ensemble_prob, 1),
            'confidence': 'High' if abs(ensemble_prob - 50) > 15 else 'Moderate' if abs(ensemble_prob - 50) > 5 else 'Low',
            'prediction': 'WIN' if ensemble_prob >= 50 else 'LOSS',
            'per_model': per_model,
        }

    def predict_batch(self, signals: list) -> list:
        """Predict win probability for multiple signals"""
        return [self.predict(s) for s in signals]


# ===== CLI =====

def main():
    import argparse

    parser = argparse.ArgumentParser(description='VCP Signal ML Predictor')
    parser.add_argument('--backtest', default=None, help='Path to backtest_result.json')
    parser.add_argument('--predict', default=None, help='Path to signal JSON for prediction')
    args = parser.parse_args()

    predictor = VCPMLPredictor()

    print("\n" + "=" * 60)
    print("  VCP SIGNAL ML PREDICTOR")
    print("=" * 60)

    # Train
    print("\n[1/2] Training models on backtest data...")
    result = predictor.train(args.backtest)

    print(f"\n  Training Samples:     {result['training_samples']}")
    print(f"  Baseline Win Rate:    {result['win_rate_baseline']:.1f}%")
    print(f"  Feature Count:        {result['feature_count']}")
    print(f"\n  --- Model CV Accuracy ---")
    for name, acc in result['models'].items():
        print(f"  {name:25s} {acc:.1f}%")
    print(f"  {'Ensemble':25s} {result['ensemble_accuracy']:.1f}%")

    print(f"\n  --- Top 10 Features ---")
    for feat, imp in result['top_features']:
        bar = '#' * int(imp * 200)
        print(f"  {feat:30s} {imp:.4f}  {bar}")

    # Predict on sample if available
    if args.predict:
        print(f"\n[2/2] Predicting from {args.predict}...")
        with open(args.predict, 'r', encoding='utf-8') as f:
            signal = json.load(f)
        pred = predictor.predict(signal)
        print(f"\n  Prediction:    {pred['prediction']}")
        print(f"  Win Prob:      {pred['win_probability']}%")
        print(f"  Confidence:    {pred['confidence']}")
        for name, info in pred['per_model'].items():
            print(f"  {name:25s} Win: {info['win_prob']}%  (Acc: {info['accuracy']}%)")
    else:
        # Quick validation: predict on first few training trades
        print(f"\n[2/2] Validation: predicting on sample trades...")
        trades = predictor.load_backtest_trades(args.backtest)
        correct = 0
        total = min(100, len(trades))
        for t in trades[-total:]:
            pred = predictor.predict(t)
            actual = t['is_winner']
            predicted = pred['prediction'] == 'WIN'
            if actual == predicted:
                correct += 1
        print(f"  Sample accuracy (last {total} trades): {correct/total*100:.1f}%")

    print(f"\n  Model saved to: {MODEL_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
