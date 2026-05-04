import json

from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import alpha_scanner


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _seed_artifacts(data_dir):
    (data_dir / 'ticker_to_yahoo_map.csv').write_text(
        '\n'.join([
            'ticker,market,yahoo_ticker,name',
            '000001,KOSPI,000001.KS,Alpha One',
            '000002,KOSDAQ,000002.KQ,Beta Two',
        ]),
        encoding='utf-8',
    )
    (data_dir / 'daily_prices.csv').write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000001,2026-05-02,Alpha One,100,0,1.0,101,98,99,100000,2026-05-02 16:00:00',
            '000001,2026-05-03,Alpha One,108,0,8.0,110,100,101,600000000,2026-05-03 16:00:00',
            '000002,2026-05-03,Beta Two,50,0,22.0,59,47,48,1000000,2026-05-03 16:00:00',
        ]),
        encoding='utf-8',
    )
    _write_json(data_dir / 'screener_leading_latest.json', {
        'timestamp': '2026-05-04T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
            {'code': '000002', 'name': 'Beta Two', 'score': {'total_enriched': 30}},
        ],
    })
    _write_json(data_dir / 'vcp_kr_latest.json', {
        'metadata': {'generated_at': '2026-05-04T00:00:00+00:00'},
        'signals': [
            {
                'symbol': '000001',
                'name': 'Alpha One',
                'market': 'KR',
                'composite': {'composite_score': 90, 'entry_ready': 'True'},
            },
        ],
    })
    _write_json(data_dir / 'jongga_v2_latest.json', {
        'date': '2026-05-04',
        'signals': [
            {
                'stock_code': '000001',
                'stock_name': 'Alpha One',
                'market': 'KOSPI',
                'score': {'total': 12},
                'checklist': {'negative_news': False, 'upper_wick_long': False},
            },
            {
                'stock_code': '000002',
                'stock_name': 'Beta Two',
                'market': 'KOSDAQ',
                'score': {'total': 6},
                'checklist': {'negative_news': True, 'upper_wick_long': True},
            },
        ],
    })


def test_alpha_scanner_creates_ranked_deterministic_run(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})

    assert run['status'] == 'completed'
    assert run['source'] == 'local_marketflow_artifacts'
    assert run['candidate_count'] == 2
    assert run['scoring_schema']['ranking'] == 'rank by alpha_score - 0.45 * risk_score, descending.'
    assert run['candidates'][0]['symbol'] == '000001'
    assert run['candidates'][0]['rank'] == 1
    assert run['candidates'][0]['action'] == 'BUY_CANDIDATE'
    assert run['candidates'][0]['alpha_score'] > run['candidates'][1]['alpha_score']
    assert run['candidates'][1]['risk_score'] > run['candidates'][0]['risk_score']
    assert {'rank', 'symbol', 'display_name', 'market', 'alpha_score', 'risk_score'} <= set(run['candidates'][0])
    assert run['candidates'][0]['evidence']

    saved = alpha_scanner.read_scanner_run(run['id'])
    candidate_payload = alpha_scanner.read_scanner_candidates(run['id'])

    assert saved['id'] == run['id']
    assert candidate_payload['candidate_count'] == 2
    assert candidate_payload['candidates'][0]['symbol'] == '000001'


def test_alpha_scanner_handles_missing_optional_artifacts(tmp_path, monkeypatch):
    (tmp_path / 'daily_prices.csv').write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000003,2026-05-03,Fallback Three,20,0,5.0,21,19,20,3000000,2026-05-03 16:00:00',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 3})

    assert run['candidate_count'] == 1
    assert run['freshness']['missing_files'] >= 3
    assert run['candidates'][0]['symbol'] == '000003'
    assert run['candidates'][0]['source'] == 'local_marketflow_artifacts'


def test_alpha_scanner_can_filter_requested_symbols(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000002'], 'limit': 5})

    assert run['candidate_count'] == 1
    assert run['requested_symbols'] == ['000002']
    assert run['candidates'][0]['symbol'] == '000002'


def test_alpha_scanner_rejects_unsafe_run_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    try:
        alpha_scanner.read_scanner_run('../escape')
    except ValueError as exc:
        assert 'invalid scanner run_id' in str(exc)
    else:
        raise AssertionError('unsafe scanner run id should be rejected')


def test_admin_mirofish_scanner_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/scanner/runs' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/candidates' in rules
