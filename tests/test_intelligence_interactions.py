"""Feature-interaction mining tests — deterministic, no LLM."""
from app.services.mirofish.intelligence import interactions


def _row(hit, ret, regime='RISK_ON', alpha=82.0, tags=('volume_surge', 'foreign_buy'),
         quality='high_conviction', action='BUY_CANDIDATE'):
    return {
        'features': {'alpha_score': alpha},
        'categoricals': {'regime': regime, 'signal_quality': quality, 'scanner_action': action},
        'tags': list(tags),
        'label': {'hit': hit, 'forward_return_pct': ret},
    }


def _dataset(rows):
    return {'schema_version': 'mirofish.training_dataset.v1', 'row_count': len(rows), 'rows': rows}


def test_row_conditions_includes_band_and_regime():
    conds = interactions._row_conditions(_row(True, 5.0))
    assert 'tag:volume_surge' in conds and 'tag:foreign_buy' in conds
    assert 'alpha:80+' in conds and 'regime:RISK_ON' in conds
    assert 'quality:high_conviction' in conds and 'action:BUY_CANDIDATE' in conds


def test_interaction_aggregates_and_marks_insufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(interactions, 'INTERACTION_MAP_PATH', str(tmp_path / 'im.json'))
    rows = [_row(True, 8.0)] * 6 + [_row(False, -4.0, tags=('volume_surge',))] * 4
    out = interactions.build_interaction_map(_dataset(rows), max_order=2)
    assert out['schema_version'] == 'mirofish.interaction_map.v1'
    assert out['evaluated_count'] == 10
    key = 'regime:RISK_ON & tag:volume_surge'
    assert out['by_combo'][key]['n'] == 10
    assert out['by_combo'][key]['insufficient'] is False
    fk = 'regime:RISK_ON & tag:foreign_buy'
    assert out['by_combo'][fk]['n'] == 6
    assert out['by_combo'][fk]['hit_rate'] == 1.0


def test_top_positive_sorted_desc(tmp_path, monkeypatch):
    monkeypatch.setattr(interactions, 'INTERACTION_MAP_PATH', str(tmp_path / 'im.json'))
    rows = ([_row(True, 9.0, tags=('a',))] * 6 + [_row(False, -2.0, tags=('b',), alpha=72.0)] * 6)
    out = interactions.build_interaction_map(_dataset(rows), max_order=2)
    assert out['top_positive'][0]['expectancy_pct'] >= out['top_positive'][-1]['expectancy_pct']
    assert out['top_negative'][0]['expectancy_pct'] <= out['top_negative'][-1]['expectancy_pct']


def test_empty_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(interactions, 'INTERACTION_MAP_PATH', str(tmp_path / 'im.json'))
    out = interactions.build_interaction_map(_dataset([]), max_order=3)
    assert out['evaluated_count'] == 0 and out['top_positive'] == []
