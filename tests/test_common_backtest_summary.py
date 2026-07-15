import json

from flask import Flask

from app.routes import common


def test_closing_bet_summary_does_not_fabricate_forward_returns(monkeypatch, tmp_path):
    first = tmp_path / 'jongga_v2_results_20260710.json'
    second = tmp_path / 'jongga_v2_results_20260711.json'
    payload = {
        'date': '2026-07-10',
        'signals': [
            {'ticker': '005930', 'entry_price': 70000, 'change_pct': 3.2},
            {'ticker': '000660', 'entry_price': 200000, 'change_pct': -1.1},
        ],
    }
    first.write_text(json.dumps(payload), encoding='utf-8')
    second.write_text(json.dumps({**payload, 'date': '2026-07-11'}), encoding='utf-8')
    monkeypatch.setattr(common, 'DATA_DIR', str(tmp_path))

    app = Flask(__name__)
    with app.test_request_context('/api/kr/backtest-summary'):
        response = common.get_backtest_summary()
        data = response.get_json()

    assert data['closing_bet']['status'] == 'Unavailable'
    assert data['closing_bet']['count'] == 4
    assert data['closing_bet']['win_rate'] is None
    assert data['closing_bet']['avg_return'] is None
    assert data['closing_bet']['lookahead_safe'] is False
