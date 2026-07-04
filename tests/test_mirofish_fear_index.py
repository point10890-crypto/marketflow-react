import json
from pathlib import Path

from app.services.mirofish import fear_index


def _indicator(value=None, *, change_pct=None, source='test'):
    return {
        'value': value,
        'change_pct': change_pct,
        'source': source,
        'source_grade': 'test',
        'fetched_at': '2026-07-04T00:00:00+00:00',
        'freshness': 'fresh',
    }


def test_fear_index_scores_high_fear_from_volatility_and_drawdown():
    result = fear_index.evaluate_fear_index(
        {
            'indicators': {
                'fear_greed': _indicator(12),
                'vix': _indicator(34, change_pct=18.0),
                'usdkrw': _indicator(1390, change_pct=1.2),
                'kospi': _indicator(2700, change_pct=-2.5),
                'sp500': _indicator(5400, change_pct=-1.1),
            },
        }
    )

    assert result['schema_version'] == fear_index.SCHEMA_VERSION
    assert result['score'] >= 70
    assert result['level'] in {'fear', 'extreme_fear'}
    assert result['confidence'] == 'high'
    assert 'not a standalone buy or sell signal' in result['non_goals']


def test_fear_index_scores_low_fear_from_risk_appetite():
    result = fear_index.evaluate_fear_index(
        {
            'indicators': {
                'fear_greed': _indicator(82),
                'vix': _indicator(13, change_pct=-4.0),
                'usdkrw': _indicator(1320, change_pct=-0.3),
                'kospi': _indicator(2850, change_pct=1.5),
                'sp500': _indicator(5600, change_pct=1.0),
            },
        }
    )

    assert result['score'] < 35
    assert result['level'] in {'low_fear', 'complacent'}
    assert result['dashboard']['display_score'] == str(int(round(result['score'])))


def test_fear_index_persists_latest_and_history(tmp_path, monkeypatch):
    latest_path = tmp_path / 'latest.json'
    history_root = tmp_path / 'history'
    monkeypatch.setattr(fear_index, 'LATEST_PATH', latest_path)
    monkeypatch.setattr(fear_index, 'HISTORY_ROOT', history_root)

    result = fear_index.run_fear_index(
        {
            'live': False,
            'indicators': {
                'fear_greed': _indicator(20),
                'vix': _indicator(31),
            },
        }
    )

    assert latest_path.exists()
    saved = json.loads(latest_path.read_text(encoding='utf-8'))
    assert saved['schema_version'] == fear_index.SCHEMA_VERSION
    assert saved['score'] == result['score']
    assert list(Path(history_root).glob('*.json'))


def test_fear_index_schema_is_read_only_source_context():
    schema = fear_index.get_fear_index_schema()

    assert schema['buy_signal'] is False
    assert schema['score_direction'] == '0=low fear, 100=extreme fear'
    assert len(schema['components']) == 5
    assert schema['rules']['llm_may_explain_not_invent'] is True
