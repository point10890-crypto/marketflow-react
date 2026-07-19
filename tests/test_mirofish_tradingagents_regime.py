import importlib
from app.services.mirofish.tradingagents import regime


def test_none_or_empty_brain_is_neutral_noop():
    rc = regime.regime_context(None)
    assert rc['direction'] == 'neutral'
    assert rc['adjustment'] == 0.0
    assert rc['line'] == ''            # 브레인 없으면 프롬프트 주입 금지
    assert regime.regime_context({})['line'] == ''


def test_bull_regime_with_high_alignment_boosts(monkeypatch):
    monkeypatch.delenv('MIROFISH_TA_REGIME_BOOST', raising=False)
    monkeypatch.delenv('MIROFISH_TA_REGIME_ALIGN_MIN', raising=False)
    rc = regime.regime_context({'regime': 'constructive_accumulation', 'alignment_score': 0.62})
    assert rc['direction'] == 'bull'
    assert rc['adjustment'] == 5.0     # 기본 boost
    assert '완만 강세' in rc['line'] and '0.62' in rc['line']


def test_bull_regime_below_alignment_min_no_boost():
    rc = regime.regime_context({'regime': 'constructive_bullish', 'alignment_score': 0.40})
    assert rc['direction'] == 'bull'
    assert rc['adjustment'] == 0.0     # 정렬 미달 → 무보정


def test_bear_regime_penalizes():
    rc = regime.regime_context({'regime': 'risk_off', 'alignment_score': 0.20})
    assert rc['direction'] == 'bear'
    assert rc['adjustment'] == -5.0


def test_neutral_and_unknown_noop():
    for label in ('neutral_balanced', 'unknown', 'data_unavailable'):
        rc = regime.regime_context({'regime': label, 'alignment_score': 0.9})
        assert rc['direction'] == 'neutral'
        assert rc['adjustment'] == 0.0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv('MIROFISH_TA_REGIME_BOOST', '8')
    monkeypatch.setenv('MIROFISH_TA_REGIME_PENALTY', '9')
    monkeypatch.setenv('MIROFISH_TA_REGIME_ALIGN_MIN', '0.50')
    importlib.reload(regime)
    assert regime.regime_context({'regime': 'constructive_bullish', 'alignment_score': 0.55})['adjustment'] == 8.0
    assert regime.regime_context({'regime': 'defensive_caution', 'alignment_score': 0.1})['adjustment'] == -9.0
    importlib.reload(regime)  # restore defaults for other tests
