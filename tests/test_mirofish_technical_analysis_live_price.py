from __future__ import annotations

from datetime import date, timedelta

from app.services.mirofish import chat_agent, live_data, technical_analysis


def _history_rows(days: int = 80, start_price: int = 100_000) -> list[dict]:
    start = date.today() - timedelta(days=days)
    rows = []
    for idx in range(days):
        price = start_price + idx * 100
        rows.append({
            'date': (start + timedelta(days=idx)).strftime('%Y-%m-%d'),
            'open': float(price - 50),
            'high': float(price + 200),
            'low': float(price - 300),
            'close': float(price),
            'volume': 100_000 + idx,
        })
    return rows


def test_analyze_levels_overlays_kis_live_current_price(monkeypatch):
    monkeypatch.setattr(
        live_data,
        'resolve_target',
        lambda target: {
            'symbol': '123456',
            'display_name': '테스트전자',
            'name': '테스트전자',
            'market': 'KOSPI',
        },
    )
    monkeypatch.setattr(technical_analysis, '_load_price_history', lambda symbol: _history_rows())
    monkeypatch.setattr(
        live_data,
        'load_kis_snapshot',
        lambda resolved: {
            'source': 'KIS API',
            'enabled': True,
            'found': True,
            'symbol': '123456',
            'quote': {
                'symbol': '123456',
                'price': 123_450,
                'open': 121_000,
                'high': 124_000,
                'low': 120_500,
                'volume': 777_000,
            },
            'sources': ['KIS API: inquire-price'],
            'fetched_at': '2026-06-10T00:00:00+00:00',
        },
    )

    result = technical_analysis.analyze_target_with_levels('테스트전자')

    assert result['price']['current'] == 123_450
    assert result['price']['source'] == 'KIS API: inquire-price'
    assert result['price']['is_live'] is True
    assert result['data_quality']['is_live_price'] is True
    assert result['data_quality']['live_price'] == 123_450
    assert '123,450원' in result['grounded_summary']
    assert 'LLM이 임의 생성한 값이 아닙니다' in result['grounded_summary']


def test_analyze_levels_marks_csv_price_when_kis_unavailable(monkeypatch):
    rows = _history_rows()
    monkeypatch.setattr(
        live_data,
        'resolve_target',
        lambda target: {
            'symbol': '123456',
            'display_name': '테스트전자',
            'name': '테스트전자',
            'market': 'KOSPI',
        },
    )
    monkeypatch.setattr(technical_analysis, '_load_price_history', lambda symbol: rows)
    monkeypatch.setattr(
        live_data,
        'load_kis_snapshot',
        lambda resolved: {
            'source': 'KIS API',
            'enabled': True,
            'found': False,
            'error': 'token_unavailable',
            'sources': [],
        },
    )
    monkeypatch.setattr(technical_analysis, '_fetch_external_quote_snapshot', lambda resolved: None)

    result = technical_analysis.analyze_target_with_levels('테스트전자')

    assert result['price']['current'] == rows[-1]['close']
    assert result['price']['source'] == 'daily_prices.csv'
    assert result['price']['is_live'] is False
    assert result['data_quality']['kis_error'] == 'token_unavailable'
    assert 'CSV 종가 기준' in result['grounded_summary']


def test_analyze_levels_uses_market_fallback_when_kis_price_missing(monkeypatch):
    rows = _history_rows()
    monkeypatch.setattr(
        live_data,
        'resolve_target',
        lambda target: {
            'symbol': '123456',
            'display_name': '테스트전자',
            'name': '테스트전자',
            'market': 'KOSPI',
            'yahoo_ticker': '123456.KS',
        },
    )
    monkeypatch.setattr(technical_analysis, '_load_price_history', lambda symbol: rows)
    monkeypatch.setattr(
        live_data,
        'load_kis_snapshot',
        lambda resolved: {
            'source': 'KIS API',
            'enabled': True,
            'found': False,
            'error': 'token_unavailable',
            'sources': [],
        },
    )
    monkeypatch.setattr(
        technical_analysis,
        '_fetch_external_quote_snapshot',
        lambda resolved: {
            'source': 'KR OHLCV fallback',
            'sources': ['FinanceDataReader/pykrx OHLCV'],
            'fetched_at': '2026-06-10T09:05:00',
            'quote': {
                'symbol': '123456',
                'price': 125_000,
                'open': 124_000,
                'high': 126_000,
                'low': 123_500,
                'volume': 555_000,
                'date': date.today().strftime('%Y-%m-%d'),
            },
        },
    )

    result = technical_analysis.analyze_target_with_levels('테스트전자')

    assert result['price']['current'] == 125_000
    assert result['price']['source'] == 'KR OHLCV fallback'
    assert result['data_quality']['fallback_from_kis_error'] == 'token_unavailable'
    assert '시장 가격 폴백' in result['grounded_summary']


def test_chat_agent_appends_grounded_summary_for_analyze_levels():
    tool_result = {
        'target': '테스트전자',
        'symbol': '123456',
        'name': '테스트전자',
        'price': {
            'current': 123_450,
            'date': '2026-06-10',
            'source': 'KIS API: inquire-price',
            'is_live': True,
        },
        'levels': {
            'entry': 123_450,
            'target1': 130_000,
            'target2': 135_000,
            'stop': 118_000,
        },
        'indicators': {
            'sma5': 122_000,
            'sma20': 120_000,
            'sma60': 115_000,
            'atr14': 2_000,
        },
        'data_quality': {
            'price_source': 'KIS API: inquire-price',
            'is_live_price': True,
            'stale_days': 0,
        },
    }

    reply = chat_agent._append_grounded_tool_summary(
        '모델 본문에는 다른 숫자가 있을 수 있습니다.',
        [{'name': 'analyze_levels', 'args': {'target': '테스트전자'}, 'result': tool_result}],
    )

    assert '### MCP 가격 기준' in reply
    assert '123,450원' in reply
    assert 'KIS API: inquire-price' in reply
