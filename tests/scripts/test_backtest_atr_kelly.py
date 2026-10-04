import csv
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/backtest_atr_kelly.py'


def cli_module():
    spec = importlib.util.spec_from_file_location('atr_cli_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def prices(count=110):
    result = []
    for index in range(count):
        close = 90 if index % 25 in (20, 21) else 100
        result.append(dict(ticker='000001', name='실제 입력 <종목>',
                           date=(date(2024, 1, 1) + timedelta(days=index)).isoformat(),
                           open=close, high=close + 2, low=close - 2,
                           current_price=close, volume=1000, update_time='2026-10-04 08:00:00'))
    return result


def test_alias_loader_preserves_actual_ohlcv_and_honest_provenance(tmp_path):
    cli = cli_module()
    path = make_csv(tmp_path / 'prices.csv', prices(2))
    rows, evidence = cli.load_ohlcv_csv(path, {'000001'})
    assert rows[0]['code'] == '000001'
    assert rows[0]['high'] == 102 and rows[0]['low'] == 98
    assert rows[0]['open'] == 100 and rows[0]['close'] == 100
    assert evidence['rows_selected'] == 2
    assert len(evidence['sha256']) == 64
    assert evidence['historical_vintage_verified'] is False
    assert evidence['historical_universe_verified'] is False
    assert evidence['captured_after_price_date'] is True


@pytest.mark.parametrize('fault', ['missing_high', 'duplicate', 'bad_low', 'nan', 'missing_symbol'])
def test_loader_rejects_unknown_or_inconsistent_market_data(tmp_path, fault):
    cli = cli_module()
    rows = prices(2)
    selected = {'000001'}
    if fault == 'missing_high':
        for row in rows:
            row.pop('high')
    elif fault == 'duplicate':
        rows.append(dict(rows[0]))
    elif fault == 'bad_low':
        rows[0]['low'] = 105
    elif fault == 'nan':
        rows[0]['volume'] = 'nan'
    else:
        selected = {'005930'}
    path = make_csv(tmp_path / 'bad.csv', rows)
    with pytest.raises(ValueError):
        cli.load_ohlcv_csv(path, selected)


def test_cli_actual_input_exports_pngs_ledgers_and_escaped_report(tmp_path):
    cli = cli_module()
    path = make_csv(tmp_path / 'prices.csv', prices())
    output = tmp_path / 'report'
    assert cli.main(['--prices', str(path), '--symbols', '000001',
                     '--train-end', '2024-02-15', '--validation-end', '2024-03-15',
                     '--out', str(output)]) == 0
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    assert report['input_evidence']['kind'] == 'provided_price_csv'
    assert report['input_evidence']['live_orders'] is False
    assert report['symbols'][0]['production_eligible'] is False
    assert (output / 'trades.csv').is_file() and (output / 'signals.csv').is_file()
    for filename in ('price_000001.png', 'equity.png', 'summary.png'):
        content = (output / filename).read_bytes()
        assert content.startswith(b'\x89PNG\r\n\x1a\n') and len(content) > 1000
    page = (output / 'report.html').read_text(encoding='utf-8')
    assert '실제 입력 &lt;종목&gt;' in page
    assert '실제 입력 <종목>' not in page
    assert '63.5%' not in page
    assert '연구용' in page and 'VIX' in page and '보류' in page


def test_invalid_input_does_not_export_a_success_report(tmp_path, capsys):
    cli = cli_module()
    rows = prices(2)
    rows[0]['high'] = 'nan'
    path = make_csv(tmp_path / 'bad.csv', rows)
    output = tmp_path / 'report'
    assert cli.main(['--prices', str(path), '--train-end', '2024-02-15',
                     '--validation-end', '2024-03-15', '--out', str(output)]) == 2
    assert not (output / 'report.json').exists()
    assert 'error' in capsys.readouterr().err.lower()


def test_same_day_intraday_capture_cannot_be_used_as_completed_daily(tmp_path):
    cli = cli_module()
    rows = prices(2)
    rows[0]['update_time'] = rows[0]['date'] + ' 12:00:00'
    path = make_csv(tmp_path / 'intraday.csv', rows)
    with pytest.raises(ValueError, match='intraday'):
        cli.load_ohlcv_csv(path)


def test_capture_date_provenance_uses_korean_session_timezone(tmp_path):
    cli = cli_module()
    rows = prices(1)
    rows[0]['update_time'] = '2024-01-01T17:00:00Z'
    _, evidence = cli.load_ohlcv_csv(make_csv(tmp_path / 'utc.csv', rows))
    assert evidence['captured_after_price_date'] is True


def test_win_caption_counts_directional_trades_separately_from_zeros():
    cli = cli_module()
    assert cli.win_caption({'completed_count': 4, 'wins': 2, 'losses': 1, 'zeros': 1, 'p': 2/3}) == 'n=3 · 0수익=1 · 승률 66.67%'


def test_explicit_mixed_price_basis_is_not_combined_into_atr(tmp_path):
    cli = cli_module()
    rows = prices(2)
    rows[0]['price_basis'] = 'raw'
    rows[1]['price_basis'] = 'split_adjusted'
    with pytest.raises(ValueError, match='basis'):
        cli.load_ohlcv_csv(make_csv(tmp_path / 'mixed.csv', rows))


def test_conflicting_symbol_aliases_are_ambiguous(tmp_path):
    cli = cli_module()
    rows = prices(1)
    rows[0]['code'] = '000002'
    with pytest.raises(ValueError, match='identifier'):
        cli.load_ohlcv_csv(make_csv(tmp_path / 'mixed-id.csv', rows))


def test_lineage_audit_cannot_override_verified_flags(tmp_path):
    cli = cli_module()
    path = make_csv(tmp_path / 'prices.csv', prices())
    audit = tmp_path / 'audit.json'
    audit.write_text(json.dumps({'historical_vintage_verified': True,
                                 'point_in_time_fundamentals': True}), encoding='utf-8')
    output = tmp_path / 'report'
    assert cli.main(['--prices', str(path), '--train-end', '2024-02-15',
                     '--validation-end', '2024-03-15', '--input-audit', str(audit),
                     '--out', str(output)]) == 0
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    evidence = report['input_evidence']
    assert evidence['historical_vintage_verified'] is False
    assert evidence['lineage_audit']['declared']['historical_vintage_verified'] is True
    assert report['symbols'][0]['production_eligible'] is False
