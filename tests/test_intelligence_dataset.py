"""Training dataset builder tests — deterministic, no LLM."""
from app.services.mirofish.intelligence import dataset


def _item(symbol='005930', hit=True, ret=6.0, entry='2026-02-10',
          tags=('volume_surge',), alpha=78.0, status='evaluated'):
    return {
        'symbol': symbol, 'status': status, 'hit': hit, 'forward_return_pct': ret,
        'entry_date': entry,
        'feature_snapshot': {
            'alpha_score': alpha, 'risk_score': 30.0, 'ranking_score': 60.0,
            'goal_fit_score': 70.0, 'source_count': 4, 'trend_20d_pct': 12.0,
            'volume_ratio': 1.8, 'cio_confidence_pct': 65.0,
            'signal_quality': 'high_conviction', 'scanner_action': 'BUY_CANDIDATE',
            'strategy_tags': list(tags),
        },
    }


_TL = {'by_date': {'2026-02-10': {'breadth': 0.7, 'regime': 'RISK_ON', 'above': 7, 'total': 10}}}


def test_build_dataset_maps_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    out = dataset.build_training_dataset(items=[_item()], timeline=_TL)
    assert out['schema_version'] == 'mirofish.training_dataset.v1'
    assert out['lookahead_safe'] is True
    assert out['row_count'] == 1
    row = out['rows'][0]
    assert row['features']['alpha_score'] == 78.0
    assert row['categoricals']['regime'] == 'RISK_ON'
    assert row['categoricals']['market'] == 'KR'
    assert row['label']['hit'] is True
    assert 'volume_surge' in row['tags']
    assert out['regime_distribution']['RISK_ON'] == 1


def test_missing_numeric_defaults_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    it = _item()
    del it['feature_snapshot']['volume_ratio']
    out = dataset.build_training_dataset(items=[it], timeline=_TL)
    assert out['rows'][0]['features']['volume_ratio'] == 0.0


def test_empty_items(monkeypatch, tmp_path):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    out = dataset.build_training_dataset(items=[], timeline=_TL)
    assert out['row_count'] == 0 and out['rows'] == []


def test_summary_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(dataset, 'TRAINING_DATASET_PATH', str(tmp_path / 'ds.json'))
    items = [_item(hit=True), _item(hit=False, ret=-3.0)]
    dataset.build_training_dataset(items=items, timeline=_TL)
    s = dataset.dataset_summary()
    assert s['row_count'] == 2 and s['hit_count'] == 1 and s['hit_rate'] == 0.5
