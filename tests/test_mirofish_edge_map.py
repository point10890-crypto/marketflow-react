"""Edge map mining tests — deterministic, no LLM, no network."""
import json

from app.services.mirofish import edge_map


def _item(symbol='005930', hit=True, ret=6.0, tags=('volume_surge',), alpha=78.0,
          action='BUY_CANDIDATE', status='evaluated'):
    return {
        'symbol': symbol,
        'status': status,
        'hit': hit,
        'forward_return_pct': ret,
        'feature_snapshot': {
            'alpha_score': alpha,
            'strategy_tags': list(tags),
            'scanner_action': action,
            'signal_quality': 'A',
        },
    }


def test_build_edge_map_aggregates_by_tag_and_band(tmp_path, monkeypatch):
    items = (
        [_item(hit=True, ret=8.0, tags=('volume_surge', 'foreign_buy'), alpha=82.0)] * 6
        + [_item(hit=False, ret=-4.0, tags=('volume_surge',), alpha=65.0)] * 4
    )
    monkeypatch.setattr(edge_map, '_evaluated_items', lambda limit_workflows: items)
    out_path = tmp_path / 'edge_map.json'
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(out_path))

    result = edge_map.build_edge_map(limit_workflows=50)

    assert result['schema_version'] == 'mirofish.edge_map.v1'
    assert result['lookahead_safe'] is True
    assert result['evaluated_count'] == 10
    surge = result['by_tag']['volume_surge']
    assert surge['n'] == 10
    assert surge['hit_rate'] == 0.6
    assert surge['expectancy_pct'] == round((8.0 * 6 - 4.0 * 4) / 10, 4)
    assert surge['insufficient'] is False
    assert result['by_tag']['foreign_buy']['n'] == 6
    assert result['by_alpha_band']['80+']['n'] == 6
    assert result['by_alpha_band']['60-70']['n'] == 4
    assert result['by_action']['BUY_CANDIDATE']['n'] == 10
    saved = json.loads(out_path.read_text(encoding='utf-8'))
    assert saved['evaluated_count'] == 10


def test_build_edge_map_marks_insufficient_buckets(monkeypatch, tmp_path):
    items = [_item(tags=('rare_tag',))] * 3  # MIN_BUCKET_SAMPLES(5) 미만
    monkeypatch.setattr(edge_map, '_evaluated_items', lambda limit_workflows: items)
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(tmp_path / 'edge_map.json'))

    result = edge_map.build_edge_map()

    assert result['by_tag']['rare_tag']['insufficient'] is True


def test_build_edge_map_skips_unevaluated_items(monkeypatch, tmp_path):
    items = [
        _item(status='evaluated'),
        _item(status='pending', hit=None, ret=None),
        _item(status='missing_entry', hit=None, ret=None),
    ]
    monkeypatch.setattr(
        edge_map, '_collect_raw_items', lambda limit_workflows: items
    )
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(tmp_path / 'edge_map.json'))

    result = edge_map.build_edge_map()

    assert result['evaluated_count'] == 1


def test_build_edge_map_empty_outcomes(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_map, '_collect_raw_items', lambda limit_workflows: [])
    monkeypatch.setattr(edge_map, 'EDGE_MAP_PATH', str(tmp_path / 'edge_map.json'))

    result = edge_map.build_edge_map()

    assert result['evaluated_count'] == 0
    assert result['by_tag'] == {}
