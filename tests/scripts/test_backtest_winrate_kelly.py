import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/backtest_winrate_kelly.py'


def load_cli():
    spec = importlib.util.spec_from_file_location('kelly_cli_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def csv_file(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_existing_close_cache_aliases_keep_codes_and_provenance(tmp_path):
    cli = load_cli()
    path = csv_file(tmp_path / 'prices.csv',
                    ['ticker', 'date', 'name', 'current_price', 'update_time', 'price_basis'],
                    [dict(ticker='003690', date='2025-01-02', name='코리안리', current_price='100',
                          update_time='2026-10-01T13:00:00Z', price_basis='provider_adjusted'),
                     dict(ticker='000020', date='2025-01-02', name='다른 종목', current_price='80')])
    prices, evidence = cli.load_price_csv(path, symbols={'003690'})
    assert prices == [{'symbol': '003690', 'name': '코리안리', 'date': '2025-01-02', 'close': 100.0}]
    assert evidence['rows_read'] == 2 and evidence['rows_selected'] == 1
    assert evidence['price_basis'] == ['provider_adjusted']
    assert evidence['captured_after_price_date'] is True
    assert evidence['historical_vintage_verified'] is False


@pytest.mark.parametrize('value', ['nan', 'inf', '-1', '0', 'garbage'])
def test_bad_prices_cannot_be_silently_dropped(tmp_path, value):
    cli = load_cli()
    path = csv_file(tmp_path / 'prices.csv', ['symbol', 'date', 'close'],
                    [{'symbol': '003690', 'date': '2025-01-02', 'close': value}])
    with pytest.raises(ValueError):
        cli.load_price_csv(path)


def test_fundamental_available_date_and_tradable_are_explicit(tmp_path):
    cli = load_cli()
    path = csv_file(tmp_path / 'fundamentals.csv',
                    ['symbol', 'available_date', 'market_cap', 'debt_ratio', 'tradable'],
                    [dict(symbol='003690', available_date='2025-01-02', market_cap='1000000000000',
                          debt_ratio='45.2', tradable='false')])
    assert cli.load_fundamental_csv(path) == [
        {'symbol': '003690', 'available_date': '2025-01-02', 'market_cap': 1e12,
         'debt_ratio': 45.2, 'tradable': False}]


def test_truncated_fundamental_row_is_a_validation_error(tmp_path):
    cli = load_cli()
    path = tmp_path / 'fundamentals.csv'
    path.write_text('symbol,available_date,market_cap,debt_ratio,tradable\nAAA,2024-01-01,1000000000000,30\n', encoding='utf-8')
    with pytest.raises(ValueError, match='required'):
        cli.load_fundamental_csv(path)


def test_demo_export_is_labelled_and_emits_real_ledgers(tmp_path):
    cli = load_cli()
    assert cli.main(['--demo', '--out', str(tmp_path)]) == 0
    report = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert report['input_evidence']['kind'] == 'synthetic_demo'
    assert report['input_evidence']['live_orders'] is False
    assert report['portfolio']['equity_curve']
    assert (tmp_path / 'equity_curve.csv').stat().st_size > 50
    assert (tmp_path / 'fills.csv').exists()
    assert (tmp_path / 'qualification.csv').exists()
    html = (tmp_path / 'report.html').read_text(encoding='utf-8')
    assert '합성 데이터' in html and '파산' in html


def test_html_exposes_actual_execution_and_cost_assumptions(tmp_path):
    cli = load_cli()
    assert cli.main(['--demo', '--execution-price', 'open', '--cost-bps', '15',
                     '--sell-tax-bps', '20', '--out', str(tmp_path)]) == 0
    page = (tmp_path / 'report.html').read_text(encoding='utf-8')
    assert '체결 기준: open' in page
    assert '보유기간: 5시장일' in page
    assert '수수료: 15' in page and '매도세: 20' in page


def test_bad_input_returns_error_without_a_success_report(tmp_path, capsys):
    cli = load_cli()
    path = csv_file(tmp_path / 'bad.csv', ['symbol', 'date', 'close'],
                    [{'symbol': '003690', 'date': '2025-01-02', 'close': 'nan'}])
    out = tmp_path / 'out'
    assert cli.main(['--prices', str(path), '--out', str(out)]) == 2
    assert not (out / 'report.json').exists()
    assert 'error' in capsys.readouterr().err.lower()


def test_vix_csv_requires_availability_and_source_and_records_hash(tmp_path):
    cli = load_cli()
    path = csv_file(tmp_path / 'vix.csv', ['available_date', 'vix_index', 'source_id'],
                    [{'available_date': '2024-01-02', 'vix_index': '30', 'source_id': 'fixture-vix'}])
    rows, evidence = cli.load_market_volatility_csv(path)
    assert rows == [{'available_date': '2024-01-02', 'vix_index': 30., 'source_id': 'fixture-vix'}]
    assert evidence['rows'] == 1 and len(evidence['sha256']) == 64
    assert evidence['source_ids'] == ['fixture-vix']
    assert evidence['availability_verified'] is False


@pytest.mark.parametrize('value', ['nan', 'inf', '-1', 'garbage'])
def test_invalid_vix_csv_is_rejected(tmp_path, value):
    cli = load_cli()
    path = csv_file(tmp_path / 'vix.csv', ['available_date', 'vix_index', 'source_id'],
                    [{'available_date': '2024-01-02', 'vix_index': value, 'source_id': 'fixture'}])
    with pytest.raises(ValueError):
        cli.load_market_volatility_csv(path)


@pytest.mark.parametrize('rows', [
    [{'available_date': '2024-01-02', 'vix_index': '30', 'source_id': ''}],
    [{'available_date': '2024-01-02', 'vix_index': '30', 'source_id': 'one'},
     {'available_date': '2024-01-02', 'vix_index': '20', 'source_id': 'two'}],
    [],
])
def test_vix_csv_missing_evidence_or_ambiguous_date_is_rejected(tmp_path, rows):
    cli = load_cli()
    path = csv_file(tmp_path / 'vix.csv', ['available_date', 'vix_index', 'source_id'], rows)
    with pytest.raises(ValueError):
        cli.load_market_volatility_csv(path)


def test_generalized_cli_exports_sizing_trace_and_dated_vix(tmp_path):
    cli = load_cli()
    prices, _ = cli.demo_data()
    days = sorted({row['date'] for row in prices})
    vix = csv_file(tmp_path / 'vix.csv', ['available_date', 'vix_index', 'source_id'],
                   [{'available_date': days[0], 'vix_index': '35', 'source_id': 'synthetic-fixture'},
                    {'available_date': days[-1], 'vix_index': '10', 'source_id': 'synthetic-fixture'}])
    out = tmp_path / 'generalized'
    assert cli.main(['--demo', '--kelly-model', 'generalized', '--vix-csv', str(vix),
                     '--min-win-lower', '0', '--min-samples', '5', '--out', str(out)]) == 0
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['config']['kelly_model'] == 'generalized'
    assert report['input_evidence']['market_volatility']['sha256'] == cli._hash(vix)
    assert report['input_evidence']['live_orders'] is False
    calculations = [row['kelly_calculation'] for row in report['qualification']]
    assert calculations
    for calculation in calculations:
        assert calculation['model'] == 'generalized'
        assert calculation['vix_index'] == 35
        assert calculation['vix_available_date'] == days[0]
        assert calculation['kelly_fraction'] == .25
    with (out / 'kelly_calculations.csv').open(encoding='utf-8-sig', newline='') as handle:
        records = list(csv.DictReader(handle))
    assert records and {'p', 'gain_fraction', 'loss_fraction', 'raw_fraction',
                        'fractional_fraction', 'capped_fraction', 'target_weight'} <= records[0].keys()
    page = (out / 'report.html').read_text(encoding='utf-8')
    assert 'p/a' in page and '쿼터' in page and 'kelly_calculations.csv' in page
    assert '순손익 0' in page and '파산' in page


def test_generalized_cli_runs_from_outside_repository(tmp_path):
    import subprocess
    result = subprocess.run([sys.executable, str(SCRIPT), '--demo', '--kelly-model', 'generalized',
                             '--out', str(tmp_path / 'portable')], cwd=tmp_path, capture_output=True,
                            text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / 'portable/report.json').read_text(encoding='utf-8'))
    assert report['config']['kelly_model'] == 'generalized'
    assert report['input_evidence']['market_volatility']['status'] == 'missing'
    assert all(row['kelly_calculation']['vix_index'] is None for row in report['qualification'])


def test_vix_csv_truncated_or_undated_input_is_rejected(tmp_path):
    cli = load_cli()
    for contents in ('vix_index,source_id\n30,fixture\n',
                     'available_date,vix_index,source_id\n2024-01-02,30\n'):
        path = tmp_path / 'vix.csv'
        path.write_text(contents, encoding='utf-8')
        with pytest.raises(ValueError):
            cli.load_market_volatility_csv(path)
