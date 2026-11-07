"""Current chart universe follows verified corporate ticker changes."""
import ast
from pathlib import Path

from app.utils import cache


def test_chart_universe_uses_current_marsh_symbol_without_adding_a_stock():
    # Read configuration without importing the chart/paid-provider CLI startup.
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'main_us.py').read_text(encoding='utf-8'))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'STOCKS' for target in node.targets))
    stocks = ast.literal_eval(assignment.value)
    assert len(stocks) == 100
    assert stocks.get('MRSH') == ('Marsh', 'Financial')
    assert 'MMC' not in stocks


def test_current_and_historical_marsh_sector_need_no_live_fallback(monkeypatch, tmp_path):
    def unexpected_fetch(*args, **kwargs):
        raise AssertionError('Known Marsh symbols must use the central sector map')

    monkeypatch.setattr(cache.yf, 'Ticker', unexpected_fetch)
    monkeypatch.setattr(cache, 'SECTOR_CACHE_FILE', str(tmp_path / 'sector.json'))
    monkeypatch.setattr(cache, '_sector_cache', {})
    assert cache.get_sector('MRSH') == 'Fin'
    assert cache.get_sector('MMC') == 'Fin'
