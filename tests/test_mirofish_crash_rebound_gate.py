import json
from pathlib import Path

from app.services.mirofish import crash_rebound_gate


def _indicator(value=None, *, change_pct=None, rsi=None, source='test'):
    row = {
        'value': value,
        'change_pct': change_pct,
        'source': source,
        'source_grade': 'test',
        'fetched_at': '2026-07-04T00:00:00+00:00',
    }
    if rsi is not None:
        row['rsi'] = rsi
    return row


def test_crash_rebound_gate_detects_rebound_confirmation_without_buy_signal():
    inputs = crash_rebound_gate.collect_crash_rebound_inputs(
        {
            'indicators': {
                'vix': _indicator(22, change_pct=-12.5),
                'fear_greed': _indicator(15),
                'ewy': _indicator(62, change_pct=2.1),
                'sp500': _indicator(5500, change_pct=1.2),
                'foreign_flow': _indicator(125_000_000_000),
                'usdkrw': _indicator(1360, change_pct=-0.8),
                'kospi': _indicator(2850, change_pct=1.4, rsi=37),
            },
        },
        live_fetch=False,
    )

    result = crash_rebound_gate.evaluate_crash_rebound_gate(inputs)

    assert result['schema_version'] == crash_rebound_gate.SCHEMA_VERSION
    assert result['status'] == 'rebound_confirmed'
    assert result['scanner_policy']['mode'] == 'rebound_confirmed'
    assert result['scanner_policy']['alpha_multiplier'] > 1.0
    assert 'not a buy signal' in result['non_goals']
    assert result['counts']['pass'] >= 7


def test_crash_rebound_gate_keeps_risk_off_when_vix_is_extreme():
    inputs = crash_rebound_gate.collect_crash_rebound_inputs(
        {'indicators': {'vix': _indicator(41), 'kospi': _indicator(2700, change_pct=-3.4)}},
        live_fetch=False,
    )

    result = crash_rebound_gate.evaluate_crash_rebound_gate(inputs)

    assert result['status'] == 'crash_risk'
    assert result['scanner_policy']['mode'] == 'risk_off'
    assert result['scanner_policy']['risk_multiplier'] > 1.0


def test_crash_rebound_gate_persists_latest_and_history(tmp_path, monkeypatch):
    latest_path = tmp_path / 'latest.json'
    history_root = tmp_path / 'history'
    monkeypatch.setattr(crash_rebound_gate, 'LATEST_PATH', latest_path)
    monkeypatch.setattr(crash_rebound_gate, 'HISTORY_ROOT', history_root)

    result = crash_rebound_gate.run_crash_rebound_gate(
        {
            'live': False,
            'indicators': {
                'vix': _indicator(20, change_pct=-11),
                'usdkrw': _indicator(1350, change_pct=-0.4),
                'sp500': _indicator(5500, change_pct=0.5),
            },
        }
    )

    assert latest_path.exists()
    saved = json.loads(latest_path.read_text(encoding='utf-8'))
    assert saved['schema_version'] == crash_rebound_gate.SCHEMA_VERSION
    assert saved['status'] == result['status']
    assert list(Path(history_root).glob('*.json'))


def test_crash_rebound_schema_is_read_only_and_source_aware():
    schema = crash_rebound_gate.get_crash_rebound_schema()

    assert schema['buy_signal'] is False
    assert len(schema['signals']) >= 10
    assert schema['rules']['missing_data_does_not_create_signal'] is True
