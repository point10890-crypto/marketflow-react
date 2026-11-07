"""A failed quick refresh must not re-stamp cached US market data."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from us_market import us_market_briefing as briefing


def _instance(tmp_path, monkeypatch, snapshot):
    output = tmp_path / 'output'
    output.mkdir()
    path = output / 'market_briefing.json'
    previous = {'timestamp': '2026-11-06T04:12:53',
                'market_data': {'indices': {'SPY': {'price': 1}}},
                'ai_analysis': {'content': 'preserved analysis'}}
    path.write_text(json.dumps(previous), encoding='utf-8')
    monkeypatch.setattr(briefing, '__file__', str(tmp_path / 'us_market_briefing.py'))
    instance = briefing.USMarketBriefing.__new__(briefing.USMarketBriefing)
    instance.data_fetcher = SimpleNamespace(
        get_market_snapshot=lambda: snapshot,
        get_vix=lambda: {'value': 20},
        calculate_fear_greed_index=lambda *_: {'score': 50},
    )
    instance.smart_money = SimpleNamespace(get_top_picks_summary=lambda: {}, get_performance_summary=lambda: {})
    instance._load_quant_signals = lambda: {}
    return instance, path, previous


def test_failed_quick_fetch_preserves_file_and_content_timestamp(tmp_path, monkeypatch):
    instance, path, previous = _instance(tmp_path, monkeypatch, {'indices': {}})
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='market data'):
        asyncio.run(instance.generate_quick_briefing())
    assert path.read_bytes() == before
    assert json.loads(path.read_text())['timestamp'] == previous['timestamp']


def test_quick_refresh_uses_source_collection_time_and_keeps_ai_age(tmp_path, monkeypatch):
    snapshot = {'timestamp': '2026-11-07T07:12:00', 'indices': {'SPY': {'price': 2}}}
    instance, path, previous = _instance(tmp_path, monkeypatch, snapshot)
    result = asyncio.run(instance.generate_quick_briefing())
    assert result['timestamp'] == snapshot['timestamp']
    assert result['ai_analysis_timestamp'] == previous['timestamp']
    assert json.loads(path.read_text()) == result


@pytest.mark.parametrize('snapshot', [
    None, [], {}, {'indices': {}},
    {'timestamp': '2026-11-07T07:12:00', 'indices': []},
    {'indices': {'SPY': {'price': 2}}},
    {'timestamp': 'invalid', 'indices': {'SPY': {'price': 2}}},
])
@pytest.mark.parametrize('method', ['generate_full_briefing', 'generate_quick_briefing'])
def test_invalid_snapshot_preserves_artifact_before_any_paid_call(tmp_path, monkeypatch, snapshot, method):
    instance, path, _ = _instance(tmp_path, monkeypatch, snapshot)
    before = path.read_bytes()
    paid_calls = []

    async def paid(*args):
        paid_calls.append(True)
        return {'content': 'must not be generated', 'citations': []}

    instance.analyzer = SimpleNamespace(get_market_analysis=paid, get_sector_rotation=paid)
    with pytest.raises(RuntimeError, match='market data'):
        asyncio.run(getattr(instance, method)())
    assert path.read_bytes() == before
    assert paid_calls == []


def test_valid_full_refresh_uses_snapshot_collection_time(tmp_path, monkeypatch):
    snapshot = {'timestamp': '2026-11-07T07:12:00', 'indices': {'SPY': {'price': 2}}}
    instance, path, _ = _instance(tmp_path, monkeypatch, snapshot)

    async def paid(*args):
        return {'content': 'analysis', 'citations': []}

    instance.analyzer = SimpleNamespace(get_market_analysis=paid, get_sector_rotation=paid)
    result = asyncio.run(instance.generate_full_briefing())
    assert result['timestamp'] == snapshot['timestamp']
    assert json.loads(path.read_text()) == result
