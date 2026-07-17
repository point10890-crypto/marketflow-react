"""Unit tests for the TradingAgents KR-native data hub.

Source failures must be isolated: one collector raising must not abort the
bundle, and the offending field must fall back to {} with an errors entry.
"""

import app.services.mirofish.tradingagents.data_hub as data_hub


def _fake_context():
    return {
        'resolved': {'symbol': '005930', 'market': 'KOSPI', 'display_name': '삼성전자'},
        'price': {'found': True, 'price': 70000, 'change_pct': 2.1, 'date': '2026-07-17'},
        'corpus': '삼성전자 수주 뉴스',
        'dart': {},
    }


def test_gather_bundle_isolates_source_failures(monkeypatch):
    monkeypatch.setattr(data_hub.live_data, 'build_context', lambda t: _fake_context())
    monkeypatch.setattr(
        data_hub.technical_analysis, 'analyze_target_with_levels',
        lambda t: (_ for _ in ()).throw(RuntimeError('boom')),
    )
    monkeypatch.setattr(data_hub, '_load_rs_entry', lambda symbol: {'rs_rating': 85})
    monkeypatch.setattr(data_hub, '_load_fundamentals', lambda symbol, market, ctx: {})

    b = data_hub.gather_bundle('삼성전자')

    assert b['symbol'] == '005930' and b['price']['found']
    assert b['technical'] == {} and 'technical' in b['errors']
    assert b['rs'] == {'rs_rating': 85}


def test_gather_bundle_happy_path_shape(monkeypatch):
    monkeypatch.setattr(data_hub.live_data, 'build_context', lambda t: _fake_context())
    monkeypatch.setattr(
        data_hub.technical_analysis, 'analyze_target_with_levels',
        lambda t: {'trend': 'bullish', 'indicators': {'sma5': 71000, 'sma20': 69000, 'sma60': 67000}},
    )
    monkeypatch.setattr(data_hub, '_load_rs_entry', lambda symbol: {'rs_rating': 90})
    monkeypatch.setattr(data_hub, '_load_fundamentals', lambda symbol, market, ctx: {'trailingPE': 12.0})

    b = data_hub.gather_bundle('삼성전자')

    expected_keys = {
        'target', 'symbol', 'market', 'display_name', 'price', 'corpus',
        'technical', 'rs', 'fundamentals', 'errors',
    }
    assert expected_keys <= set(b)
    assert b['errors'] == {}
    assert b['market'] == 'KOSPI'
    assert b['display_name'] == '삼성전자'
    assert b['technical']['trend'] == 'bullish'
    assert b['fundamentals'] == {'trailingPE': 12.0}


def test_gather_bundle_survives_live_data_failure(monkeypatch):
    monkeypatch.setattr(
        data_hub.live_data, 'build_context',
        lambda t: (_ for _ in ()).throw(RuntimeError('resolve exploded')),
    )
    monkeypatch.setattr(data_hub, '_load_rs_entry', lambda symbol: {})
    monkeypatch.setattr(data_hub, '_load_fundamentals', lambda symbol, market, ctx: {})

    b = data_hub.gather_bundle('없는종목')

    assert b['symbol'] is None
    assert b['price'] == {}
    assert 'live_data' in b['errors']


def test_technical_error_dict_becomes_empty(monkeypatch):
    monkeypatch.setattr(data_hub.live_data, 'build_context', lambda t: _fake_context())
    monkeypatch.setattr(
        data_hub.technical_analysis, 'analyze_target_with_levels',
        lambda t: {'error': '가격 데이터 부족', 'target': t},
    )
    monkeypatch.setattr(data_hub, '_load_rs_entry', lambda symbol: {})
    monkeypatch.setattr(data_hub, '_load_fundamentals', lambda symbol, market, ctx: {})

    b = data_hub.gather_bundle('삼성전자')

    assert b['technical'] == {}
    assert 'technical' in b['errors']
