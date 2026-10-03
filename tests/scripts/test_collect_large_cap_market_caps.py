import csv
import hashlib
import importlib.util
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

pa = pytest.importorskip('pyarrow')
pq = pytest.importorskip('pyarrow.parquet')
SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/collect_large_cap_market_caps.py'


def collector():
    assert SCRIPT.exists(), 'Historical market-cap collector is not implemented'
    spec = importlib.util.spec_from_file_location('market_cap_collector_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def report(path, codes):
    path.write_text(json.dumps({'ranking': {'as_of': '2026-10-01', 'ranked': [
        {'symbol': code} for code in codes]}}), encoding='utf-8')
    return path


def write_parquet(path, rows):
    fields = {'Date': [], 'Code': [], 'Name': [], 'Market': [], 'MarketId': [],
              'Marcap': [], 'Stocks': [], 'Rank': [], 'Close': [], 'Volume': []}
    for row in rows:
        merged = {'Date': datetime(2020, 1, 2), 'Code': '005930', 'Name': 'sample',
                  'Market': 'KOSPI', 'MarketId': 'STK', 'Marcap': 1000.,
                  'Stocks': 10, 'Rank': 999, 'Close': 100., 'Volume': 1.}
        merged.update(row)
        for field in fields:
            fields[field].append(merged[field])
    pq.write_table(pa.table(fields), path)


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def test_universe_enforces_one_to_one_hundred_unique_symbols(tmp_path):
    module = collector()
    assert module.load_universe(report(tmp_path / 'report.json', ['005930', '000660']))['symbols'] == {'005930', '000660'}
    for codes in ([], ['005930', '005930'], [f'{number:06}' for number in range(101)]):
        with pytest.raises(ValueError):
            module.load_universe(report(tmp_path / 'bad.json', codes))


def test_extract_scopes_rows_and_recomputes_market_ranking(tmp_path):
    module = collector()
    source = tmp_path / 'marcap-2020.parquet'
    write_parquet(source, [
        {'Code': '005930', 'Marcap': 1000., 'Rank': 999, 'Volume': 0.},
        {'Code': '000660', 'Marcap': 2000., 'Close': 200., 'Rank': 800},
        {'Code': '111110', 'Market': 'KONEX', 'Marcap': 3000., 'Close': 300., 'Rank': 1},
        {'Code': '222220', 'Market': 'KOSDAQ GLOBAL', 'Marcap': 1500., 'Close': 150., 'Rank': 500},
    ])
    result = module.extract_year(source, {'005930'}, tmp_path / 'out', year=2020, batch_size=2)
    selected = read_csv(Path(result['current_cohort_path']))
    membership = read_csv(Path(result['historical_membership_path']))
    assert len(selected) == 1 and selected[0]['symbol'] == '005930'
    assert selected[0]['market_cap'] == '1000' and selected[0]['tradable'] == 'false'
    assert [row['symbol'] for row in membership] == ['000660', '222220', '005930']
    assert [row['rank'] for row in membership] == ['1', '2', '3']
    assert membership[1]['market'] == 'KOSDAQ'
    assert result['unit_check']['verified_rows'] == 4
    assert result['unit_check']['mismatched_rows'] == 0
    assert result['current_cohort_missing_symbols'] == []


def test_bad_market_cap_unit_fails_before_any_scoped_output(tmp_path):
    module = collector()
    source = tmp_path / 'marcap-2020.parquet'
    write_parquet(source, [{'Marcap': 0.001}])
    with pytest.raises(ValueError, match='unit'):
        module.extract_year(source, {'005930'}, tmp_path / 'out', year=2020)
    assert not list((tmp_path / 'out').glob('*.csv'))


def test_zero_and_unknown_unit_rows_are_reported_separately(tmp_path):
    module = collector()
    source = tmp_path / 'marcap-2020.parquet'
    write_parquet(source, [
        {'Code': '005930', 'Marcap': 0., 'Close': 0.},
        {'Code': '000660', 'Marcap': None, 'Close': None},
    ])
    result = module.extract_year(source, {'005930', '000660'}, tmp_path / 'out', year=2020)
    assert result['unit_check']['zero_or_nonpositive_rows'] == 1
    assert result['unit_check']['unknown_rows'] == 1
    assert result['unit_check']['verified_rows'] == 0
    assert result['historical_membership_rows'] == 0


def test_conflicting_duplicate_symbol_day_fails_closed(tmp_path):
    module = collector()
    source = tmp_path / 'marcap-2020.parquet'
    write_parquet(source, [{'Close': 100., 'Marcap': 1000.}, {'Close': 200., 'Marcap': 2000.}])
    with pytest.raises(ValueError, match='duplicate'):
        module.extract_year(source, {'005930'}, tmp_path / 'out', year=2020, batch_size=1)


class Response(io.BytesIO):
    status = 200

    def __init__(self, content, declared=None):
        super().__init__(content)
        self.headers = {'Content-Length': str(len(content) if declared is None else declared),
                        'Content-Type': 'application/octet-stream', 'ETag': 'test-etag'}


def test_atomic_download_records_hash_and_resume_preserves_capture(tmp_path, monkeypatch):
    module = collector()
    content = b'PAR1original-parquet-bytesPAR1'
    monkeypatch.setattr(module, 'urlopen', lambda request, timeout: Response(content))
    record = module.download_year(2020, tmp_path, budget=module.ByteBudget(1000))
    assert Path(record['path']).read_bytes() == content
    assert record['sha256'] == hashlib.sha256(content).hexdigest()
    assert record['byte_count'] == len(content)
    assert not list(tmp_path.glob('*.part'))
    monkeypatch.setattr(module, 'urlopen', lambda *args, **kwargs: pytest.fail('Resume must not fetch again'))
    resumed = module.download_year(2020, tmp_path, budget=module.ByteBudget(1000), existing=record)
    assert resumed['sha256'] == record['sha256']
    assert resumed['capture_completed_utc'] == record['capture_completed_utc']
    assert resumed['reused'] is True


def test_corrupted_resume_and_oversize_download_fail_closed(tmp_path, monkeypatch):
    module = collector()
    content = b'PAR1originalPAR1'
    monkeypatch.setattr(module, 'urlopen', lambda request, timeout: Response(content))
    record = module.download_year(2020, tmp_path, budget=module.ByteBudget(1000))
    Path(record['path']).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='hash'):
        module.download_year(2020, tmp_path, budget=module.ByteBudget(1000), existing=record)
    monkeypatch.setattr(module, 'urlopen', lambda request, timeout: Response(content, declared=2000))
    with pytest.raises(ValueError, match='limit'):
        module.download_year(2021, tmp_path, budget=module.ByteBudget(1000), max_file_bytes=100)
    assert not (tmp_path / 'marcap-2021.parquet').exists()
    assert not list(tmp_path.glob('*.part'))


def test_resume_rejects_wrong_year_or_source_identity(tmp_path, monkeypatch):
    module = collector()
    content = b'PAR1originalPAR1'
    monkeypatch.setattr(module, 'urlopen', lambda request, timeout: Response(content))
    record = module.download_year(2020, tmp_path, budget=module.ByteBudget(1000))
    for changes in ({'year': 2021}, {'source_url': 'https://example.test/wrong.parquet'}):
        with pytest.raises(ValueError, match='identity'):
            module.download_year(2020, tmp_path, budget=module.ByteBudget(1000), existing=dict(record, **changes))


def test_cache_only_default_never_fetches_missing_year(tmp_path, monkeypatch, capsys):
    module = collector()
    monkeypatch.setattr(module, 'urlopen', lambda *args, **kwargs: pytest.fail('Network requires --fetch'))
    universe = report(tmp_path / 'report.json', ['005930'])
    assert module.main(['--universe-report', str(universe), '--years', '2020',
                        '--out', str(tmp_path / 'out')]) == 2
    assert '--fetch' in capsys.readouterr().err


def test_explicit_fetch_acquires_and_extracts_a_missing_year(tmp_path, monkeypatch):
    module = collector()
    parquet = tmp_path / 'fixture.parquet'
    write_parquet(parquet, [{'Code': '005930'}])
    content = parquet.read_bytes()
    monkeypatch.setattr(module, 'urlopen', lambda request, timeout: Response(content))
    universe = report(tmp_path / 'report.json', ['005930'])
    out = tmp_path / 'out'
    assert module.main(['--universe-report', str(universe), '--years', '2020',
                        '--out', str(out), '--fetch']) == 0
    evidence = json.loads((out / 'verification_summary.json').read_text(encoding='utf-8'))
    assert evidence['status'] == 'complete'
    assert evidence['requested_years'] == [2020]
    assert evidence['files'][0]['current_cohort_rows'] == 1


def test_main_reuses_manifest_and_emits_scoped_evidence(tmp_path):
    module = collector()
    out = tmp_path / 'out'
    out.mkdir()
    source = out / 'marcap-2020.parquet'
    write_parquet(source, [{'Code': '005930'}, {'Code': '000660', 'Close': 200., 'Marcap': 2000.}])
    old_capture = '2026-10-03T00:00:00+00:00'
    (out / 'download_manifest.json').write_text(json.dumps({'files': [{
        'year': 2020, 'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'byte_count': source.stat().st_size, 'capture_completed_utc': old_capture,
        'download_status': 'complete', 'source_url': 'https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-2020.parquet'}]}), encoding='utf-8')
    universe = report(tmp_path / 'report.json', ['005930'])
    assert module.main(['--universe-report', str(universe), '--years', '2020', '--out', str(out)]) == 0
    evidence = json.loads((out / 'verification_summary.json').read_text(encoding='utf-8'))
    manifest = json.loads((out / 'download_manifest.json').read_text(encoding='utf-8'))
    assert evidence['cohort_codes_count'] == 1
    assert evidence['files'][0]['current_cohort_rows'] == 1
    assert manifest['files'][0]['capture_completed_utc'] == old_capture
    assert manifest['files'][0]['reused'] is True
