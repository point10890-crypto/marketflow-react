"""Unit tests for app/services/mirofish/brain_loader."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish.brain_loader import (  # noqa: E402
    DIMENSIONS,
    load_brain_13d_snapshot,
    _dim_sector_momentum,
    _dim_macro_regime,
    _dim_options_flow,
    _dim_event_risk,
    _dim_ml_prediction,
    _dim_volatility,
    _high_level_regime,
)


def test_dimensions_count_is_13():
    assert len(DIMENSIONS) == 13


def test_load_snapshot_returns_required_keys():
    snap = load_brain_13d_snapshot('TestTarget')
    assert snap['name'] == 'MiroFish Brain 13D'
    assert snap['target'] == 'TestTarget'
    assert 'dimensions' in snap
    assert set(snap['dimensions'].keys()) == set(DIMENSIONS)
    assert 0.0 <= snap['alignment_score'] <= 1.0
    assert snap['regime'] in {'constructive_bullish', 'constructive_accumulation',
                              'neutral_balanced', 'defensive_caution', 'risk_off', 'unknown'}


def test_dim_sector_momentum_handles_missing():
    out = _dim_sector_momentum(None)
    assert out['score'] is None
    assert out['confidence'] == 0.0
    assert 'unavailable' in out['evidence']


def test_dim_sector_momentum_normalizes_score():
    fake = {
        'rotation_clock': {
            'phases': {
                'Early Cycle': {'score': 0.5},
                'Late Cycle': {'score': 4.0},
            }
        }
    }
    out = _dim_sector_momentum(fake)
    assert out['score'] is not None
    assert 0 <= out['score'] <= 100
    assert 'Late Cycle' in out['evidence']


def test_dim_macro_regime_combines_phase_and_vix():
    fake_sr = {'regime_change': {'current_phase': 'Mid Cycle'}}
    fake_md = {'volatility': {'^VIX': {'price': 18.0}}}
    out = _dim_macro_regime(fake_sr, fake_md)
    # Mid Cycle 기본 70 - vix penalty 0 (vix=18 → no penalty since base condition vix>20)
    assert out['score'] >= 60
    assert 'Mid Cycle' in out['evidence']


def test_dim_macro_regime_vix_penalty_applies_above_20():
    fake_sr = {'regime_change': {'current_phase': 'Late Cycle'}}
    fake_md = {'volatility': {'^VIX': {'price': 35.0}}}
    out = _dim_macro_regime(fake_sr, fake_md)
    # Late Cycle base 45 - vix(35-20)*0.5 = 45 - 7.5 = 37
    assert out['score'] is not None
    assert out['score'] < 45


def test_dim_options_flow_bullish_ratio():
    fake = {
        'total_analyzed': 10,
        'options_flow': [
            {'flow_signal': 'Bullish'},
            {'flow_signal': 'Bullish'},
            {'flow_signal': 'Bullish'},
            {'flow_signal': 'Bearish'},
        ]
    }
    out = _dim_options_flow(fake)
    assert out['score'] == 75  # 3/4 = 75


def test_dim_event_risk_high_severity_lowers_score():
    fake_ra = {
        'alerts': [
            {'severity': 'critical'},
            {'severity': 'critical'},
            {'severity': 'warning'},
        ]
    }
    fake_md = {'volatility': {'^VIX': {'price': 35.0}}}
    out = _dim_event_risk(fake_ra, fake_md)
    # 2*15 + 1*5 + (35-20)*2 = 30+5+30 = 65 risk → safety = 35
    assert out['score'] is not None
    assert out['score'] < 50


def test_dim_ml_prediction_uses_bullish_probability():
    fake = {'spy': {'bullish_probability': 87.5, 'direction': 'Bullish'}}
    out = _dim_ml_prediction(fake)
    assert out['score'] == 87
    assert 'Bullish' in out['evidence']


def test_dim_volatility_low_vix_high_score():
    fake = {'volatility': {'^VIX': {'price': 12.5}}}
    out = _dim_volatility(fake)
    assert out['score'] == 85


def test_dim_volatility_extreme_vix_low_score():
    fake = {'volatility': {'^VIX': {'price': 40.0}}}
    out = _dim_volatility(fake)
    assert out['score'] <= 20


def test_high_level_regime_bullish():
    dims = {f'd{i}': {'score': 75} for i in range(13)}
    assert _high_level_regime(dims) == 'constructive_bullish'


def test_high_level_regime_risk_off():
    dims = {f'd{i}': {'score': 20} for i in range(13)}
    assert _high_level_regime(dims) == 'risk_off'


def test_high_level_regime_unknown_on_all_none():
    dims = {f'd{i}': {'score': None} for i in range(13)}
    assert _high_level_regime(dims) == 'unknown'


def test_snapshot_includes_sources_metadata():
    snap = load_brain_13d_snapshot()
    assert 'sources' in snap
    assert isinstance(snap['sources'], list)
    # 모든 source는 file 필드 포함
    for src in snap['sources']:
        assert 'file' in src
