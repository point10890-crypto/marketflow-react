from __future__ import annotations

from app.services.mirofish import k_analyst_engine


def _rows(count: int, *, start: float = 10000.0, step: float = 22.0) -> list[dict]:
    rows = []
    for idx in range(count):
        close = start + idx * step
        wave = ((idx % 9) - 4) * 3
        close += wave
        rows.append({
            'date': f'2026-01-{(idx % 28) + 1:02d}',
            'open': close - 12,
            'high': close + 28,
            'low': close - 35,
            'close': close,
            'volume': 100000 + idx * 1200,
        })
    return rows


def test_tech_engine_partial_data_outputs_indicators_strategy_and_probabilities():
    packet = k_analyst_engine.analyze_technical_packet({
        'target': {'symbol': '005930', 'name': 'Samsung Electronics', 'market': 'KOSPI'},
        'rows': _rows(90),
        'flow': {'foreign_cash_net': 120000, 'foreign_futures_net': 3300, 'source_grade': 'A'},
        'evidence': [{'cluster': 'scanner_alpha', 'direction': 'Bull', 'strength': 0.7, 'source_grade': 'B'}],
    })

    assert packet['readiness']['status'] == 'PARTIAL'
    assert packet['technical']['sample_days'] == 90
    assert packet['technical']['sma']['20'] is not None
    assert packet['price_strategy']['status'] == 'conditional'
    assert packet['bayesian_verdict']['probability_total'] == 100
    assert packet['contracts']['no_fabricated_prices'] is True


def test_insufficient_price_data_withholds_price_strategy():
    packet = k_analyst_engine.analyze_technical_packet({
        'target': {'symbol': '005930', 'name': 'Samsung Electronics', 'market': 'KOSPI'},
        'rows': _rows(10),
    })

    assert packet['readiness']['status'] == 'INSUFFICIENT'
    assert packet['price_strategy']['status'] == 'withheld'
    assert packet['bayesian_verdict']['action'] in {'DATA_HOLD', 'HOLD_REVIEW'}
    assert packet['bayesian_verdict']['probability_total'] == 100


def test_halt_gate_overrides_bullish_inputs():
    packet = k_analyst_engine.analyze_technical_packet({
        'target': {'symbol': '005930', 'name': 'Samsung Electronics', 'market': 'KOSPI'},
        'rows': _rows(150),
        'flow': {'foreign_cash_net': 999999, 'foreign_futures_net': 9999, 'source_grade': 'A'},
        'fundamental': {'source_grade': 'B', 'latest': 'normal'},
        'dart_event': {'headline': 'trading halt risk and delisting review'},
        'evidence': [{'cluster': 'scanner_alpha', 'direction': 'Bull', 'strength': 0.9, 'source_grade': 'A'}],
    })

    assert packet['readiness']['status'] == 'FULL'
    assert packet['halt_gate']['halt'] is True
    assert packet['price_strategy']['status'] == 'withheld'
    assert packet['bayesian_verdict']['action'] == 'HOLD_REVIEW'
    assert packet['bayesian_verdict']['posterior_pct']['Bull'] <= 45


def test_bayesian_verdict_sums_to_100_and_caps_partial_confidence():
    verdict = k_analyst_engine.build_bayesian_verdict({
        'readiness': {'status': 'PARTIAL'},
        'confidence_cap': 0.65,
        'evidence': [
            {'cluster': 'capital_flow', 'direction': 'Bull', 'strength': 1.0, 'source_grade': 'A', 'freshness': 'fresh'},
            {'cluster': 'currency', 'direction': 'Bear', 'strength': 0.7, 'source_grade': 'B', 'freshness': 'recent'},
        ],
    })

    assert verdict['probability_total'] == 100
    assert max(verdict['posterior_pct'].values()) <= 65
    assert verdict['conflict_flags']['has_directional_conflict'] is True
