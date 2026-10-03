import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/collect_large_cap_dart_history.py'
NOW = datetime(2026, 10, 3, 3, tzinfo=timezone.utc)
TOKEN = 'private-test-token'


def collector():
    assert SCRIPT.exists(), 'Bounded historical collector has not been implemented'
    spec = importlib.util.spec_from_file_location('dart_history_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def inputs(tmp_path, symbols=('005930',)):
    report = tmp_path / 'cohort.json'
    report.write_text(json.dumps(dict(as_of='2026-10-01', ranking=dict(ranked=[
        dict(symbol=s, rank=i + 1, name=f'Company {s}') for i, s in enumerate(symbols)]))), encoding='utf-8')
    mapping = tmp_path / 'codes.json'
    mapping.write_text(json.dumps({s: f'{i + 1:08d}' for i, s in enumerate(sorted(symbols))}), encoding='utf-8')
    env = tmp_path / '.env'
    env.write_text(f'DART_API_KEY={TOKEN}\n', encoding='utf-8')
    return dict(cohort_report=report, mapping_path=mapping, env_file=env,
                out=tmp_path / 'out', start_year=2025, through_year=2025,
                through_report='11013', now=NOW)


def account(name, amount, *, symbol='005930', fs='CFS', year=2025, report='11013',
            receipt='20250515000123', period='2025.03.31 현재', added=None, currency='KRW'):
    row = dict(stock_code=symbol, corp_code='00000001', bsns_year=str(year), reprt_code=report,
               fs_div=fs, rcept_no=receipt, currency=currency, account_nm=name,
               sj_div='BS' if name in ('자본총계', '부채총계') else 'IS',
               thstrm_amount=str(amount), thstrm_dt=period, ord='1')
    if added is not None:
        row['thstrm_add_amount'] = str(added)
    return row


def complete_rows(**kwargs):
    return [account('자본총계', 1000, **kwargs), account('부채총계', 500, **kwargs),
            account('영업이익', 10, added=80, **kwargs), account('당기순이익', 5, added=60, **kwargs)]


def response(rows=None, status='000'):
    return json.dumps(dict(status=status, message='OK', list=rows or []), ensure_ascii=False).encode()


def missing(*args, **kwargs):
    return response(status='013')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def zip_bytes(name='report.xml', value=b'<document/>'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, value)
    return buffer.getvalue()


def test_plan_is_46_completed_reporting_periods_not_2026_future_reports():
    module = collector()
    periods = module.reporting_periods(2015, 2026, '11012')
    assert len(periods) == 46
    assert periods[0] == dict(year=2015, report_code='11013', period_end='2015-03-31')
    assert periods[-1] == dict(year=2026, report_code='11012', period_end='2026-06-30')
    assert {(p['year'], p['report_code']) for p in periods if p['year'] == 2026} == {(2026, '11013'), (2026, '11012')}


def test_all_scopes_preserved_without_mixing_and_vintage_never_certified(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    rows = complete_rows() + complete_rows(fs='OFS')
    report = module.collect_history(**args, fetch=True, transport=lambda *a, **k: response(rows))
    values = read_json(args['out'] / 'financials.json')
    assert report['status'] == 'complete'
    assert len(values) == 2 and {row['fs_div'] for row in values} == {'CFS', 'OFS'}
    assert all(row['net_income'] == 60 and row['operating_profit'] == 80 for row in values)
    assert all(row['period_end'] == '2025-03-31' and row['period_verified'] for row in values)
    assert all(row['available_date'] == '2025-05-16' for row in values)
    assert all(row['historical_vintage_verified'] is False for row in values)
    assert report['historical_universe_verified'] is False


def test_incomplete_cfs_never_borrows_ofs_income(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    rows = complete_rows()[:2] + complete_rows(fs='OFS')
    module.collect_history(**args, fetch=True, transport=lambda *a, **k: response(rows))
    values = read_json(args['out'] / 'financials.json')
    cfs = next(row for row in values if row['fs_div'] == 'CFS')
    assert cfs['net_income'] is None and cfs['operating_profit'] is None
    assert 'missing_net_income' in cfs['completeness_reasons']


@pytest.mark.parametrize('period,reason', [('', 'missing_period_date'), ('2024.12.31 현재', 'period_end_mismatch'),
                                         ('2025.99.99 현재', 'invalid_period_date')])
def test_ambiguous_or_wrong_period_is_held_without_claiming_requested_date(tmp_path, period, reason):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=lambda *a, **k: response(complete_rows(period=period)))
    row = read_json(args['out'] / 'financials.json')[0]
    assert row['period_verified'] is False
    assert row['period_end'] is None
    assert row['requested_period_end'] == '2025-03-31'
    assert reason in row['completeness_reasons']


def test_missing_ytd_and_nonkrw_are_not_promoted(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    rows = [account('영업이익', 80), account('자본총계', 1000),
            account('당기순이익', 123, currency='USD')]
    module.collect_history(**args, fetch=True, transport=lambda *a, **k: response(rows))
    row = read_json(args['out'] / 'financials.json')[0]
    assert row['operating_profit'] is None and row['net_income'] is None
    assert 'non_KRW_account' in row['completeness_reasons']


def test_status_013_is_durable_missing_and_no_fetch_on_resume(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    first = module.collect_history(**args, fetch=True, transport=missing)
    assert first['coverage'][0]['missing_symbols'] == ['005930']
    assert first['coverage'][0]['symbol_reasons']['005930'] == ['DART_status_013']
    assert first['budget']['calls_total'] == 1
    def forbidden(*args, **kwargs):
        pytest.fail('Completed missing-data receipt must not be downloaded again')
    second = module.collect_history(**args, fetch=True, transport=forbidden)
    assert second['budget']['calls_this_run'] == 0
    assert second['budget']['calls_total'] == 1


def test_later_failure_preserves_prior_completed_call_and_safe_errors(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    args['through_report'] = '11012'
    def first_attempt(url, params, **kwargs):
        if params['reprt_code'] == '11012':
            raise RuntimeError(f'https://example.test/?crtfc_key={TOKEN}')
        return missing()
    first = module.collect_history(**args, fetch=True, transport=first_attempt)
    assert first['status'] == 'partial'
    assert first['budget']['calls_total'] == 2
    second = module.collect_history(**args, fetch=True, transport=missing)
    assert second['status'] == 'complete'
    assert second['budget']['calls_total'] == 3 and second['budget']['calls_this_run'] == 1
    assert TOKEN not in '\n'.join(p.read_text(encoding='utf-8') for p in args['out'].rglob('*.json'))


def test_persistent_budget_stops_before_another_request(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    args['through_report'] = '11012'
    first = module.collect_history(**args, fetch=True, max_calls=1, transport=missing)
    assert first['status'] == 'partial' and first['budget']['calls_total'] == 1
    second = module.collect_history(**args, fetch=True, max_calls=1, transport=lambda *a, **k: pytest.fail('Budget exceeded'))
    assert second['budget']['calls_this_run'] == 0
    assert second['error'] == 'financial_request_budget_exhausted'


def test_fifty_company_batch_limit_is_observable_in_request_params(tmp_path):
    module = collector()
    args = inputs(tmp_path, tuple(f'{i:06d}' for i in range(1, 52)))
    batches = []
    def transport(url, params, **kwargs):
        batches.append(params['corp_code'].split(','))
        return missing()
    report = module.collect_history(**args, fetch=True, transport=transport)
    assert [len(batch) for batch in batches] == [50, 1]
    assert report['budget']['planned_batches'] == 2


def test_existing_fresh_capture_import_keeps_time_and_file_hash(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    cache_dir = tmp_path / 'existing'
    cache_dir.mkdir()
    identity = hashlib.sha256(b'00000001').hexdigest()[:16]
    source = cache_dir / f'dart_2025_11013_{identity}.json'
    source.write_text(json.dumps(dict(source=module.DART_API, fetched_at='2026-10-03T02:00:00+00:00',
        payload=dict(status='000', list=complete_rows()))), encoding='utf-8')
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    report = module.collect_history(**args, fetch=True, reuse_cache_dirs=[cache_dir],
        transport=lambda *a, **k: pytest.fail('Fresh capture should be imported'))
    assert report['budget']['calls_total'] == 0
    assert report['captures'][0]['fetched_at'] == '2026-10-03T02:00:00+00:00'
    assert report['captures'][0]['imported_source_sha256'] == expected_hash
    assert read_json(args['out'] / 'financials.json')[0]['fetched_at'] == '2026-10-03T02:00:00+00:00'


def test_expired_external_cache_is_not_silently_current_capture(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    cache_dir = tmp_path / 'existing'
    cache_dir.mkdir()
    identity = hashlib.sha256(b'00000001').hexdigest()[:16]
    source = cache_dir / f'dart_2025_11013_{identity}.json'
    source.write_text(json.dumps(dict(source=module.DART_API, fetched_at='2026-09-01T02:00:00+00:00',
        payload=dict(status='013'))), encoding='utf-8')
    report = module.collect_history(**args, fetch=True, reuse_cache_dirs=[cache_dir], transport=missing)
    assert report['budget']['calls_this_run'] == 1


def test_key_in_source_payload_is_redacted_before_snapshot(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    payload = dict(status='013', message=f'url?crtfc_key={TOKEN}', crtfc_key=TOKEN)
    report = module.collect_history(**args, fetch=True,
        transport=lambda *a, **k: json.dumps(payload).encode())
    text = '\n'.join(p.read_text(encoding='utf-8') for p in args['out'].rglob('*.json'))
    assert report['status'] == 'complete'
    assert TOKEN not in text and '[REDACTED]' in text


def test_other_cohort_does_not_reuse_completed_output(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    report = read_json(args['cohort_report'])
    report['ranking']['ranked'][0]['symbol'] = '000660'
    args['cohort_report'].write_text(json.dumps(report), encoding='utf-8')
    args['mapping_path'].write_text(json.dumps({'000660': '00000001'}), encoding='utf-8')
    with pytest.raises(ValueError, match='identity'):
        module.collect_history(**args, fetch=True, transport=missing)


def test_no_fetch_does_not_read_key_or_call_provider(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    args['env_file'] = tmp_path / 'nonexistent.env'
    report = module.collect_history(**args, fetch=False,
        transport=lambda *a, **k: pytest.fail('No fetch permission'))
    assert report['status'] == 'partial' and report['error'] == 'fetch_required'
    assert report['budget']['calls_total'] == 0


def test_receipt_before_period_or_after_capture_is_not_usable(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    rows = complete_rows(receipt='20250301000123') + complete_rows(fs='OFS', receipt='20271003000123')
    module.collect_history(**args, fetch=True, transport=lambda *a, **k: response(rows))
    values = read_json(args['out'] / 'financials.json')
    assert all(row['research_usable'] is False for row in values)
    reasons = {reason for row in values for reason in row['completeness_reasons']}
    assert {'receipt_before_period_end', 'receipt_after_capture'} <= reasons


def test_snapshot_tampering_fails_closed_without_redownload(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    path = next((args['out'] / 'sources').glob('dart_*.json'))
    envelope = read_json(path)
    envelope['payload']['status'] = '000'
    path.write_text(json.dumps(envelope), encoding='utf-8')
    report = module.collect_history(**args, fetch=True,
        transport=lambda *a, **k: pytest.fail('Corrupt snapshot must not trigger unbounded retry'))
    assert report['status'] == 'partial' and report['error'] == 'invalid_completed_snapshot'


def test_original_sample_retrieval_is_bounded_and_does_not_claim_contents_verified(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    calls = []
    body = zip_bytes()
    def transport(url, params, **kwargs):
        calls.append((url.rsplit('/', 1)[-1], params['rcept_no']))
        return body
    first = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True, now=NOW, transport=transport)
    assert len(calls) == 4
    assert {receipt for _, receipt in calls} == {'20160330003536', '20160516001867'}
    assert first['calls_total'] == 4 and first['historical_vintage_verified'] is False
    assert all(row['content_validated'] is False and row['zip_structure_verified'] for row in first['captures'])
    assert len(list((args['out'] / 'originals').glob('*.zip'))) == 4
    second = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True, now=NOW,
        transport=lambda *a, **k: pytest.fail('Original captures must be reused'))
    assert second['calls_this_run'] == 0 and second['calls_total'] == 4


@pytest.mark.parametrize('body', [b'<result><status>014</status></result>', zip_bytes('../escape.xml')])
def test_invalid_or_traversal_original_archive_is_held_and_never_extracted(tmp_path, body):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    result = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True,
        now=NOW, max_calls=1, transport=lambda *a, **k: body)
    assert result['status'] == 'partial' and not result['captures']
    assert not list((args['out'] / 'originals').glob('*.zip'))
    assert not (tmp_path / 'escape.xml').exists()


def test_original_storage_total_bytes_limit_is_not_per_file(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    body = zip_bytes()
    result = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True,
        now=NOW, max_total_bytes=len(body), transport=lambda *a, **k: body)
    assert result['status'] == 'partial' and result['stored_bytes'] == len(body)
    assert result['calls_total'] == 1


@pytest.mark.parametrize('field,value', [('corp_code', '99999999'), ('stock_code', '000660'),
                                        ('bsns_year', '2024'), ('reprt_code', '11011')])
def test_remote_response_cannot_substitute_another_company_or_period(tmp_path, field, value):
    module = collector()
    args = inputs(tmp_path)
    rows = complete_rows()
    rows[0][field] = value
    report = module.collect_history(**args, fetch=True, transport=lambda *a, **k: response(rows))
    assert report['status'] == 'partial' and report['error'] == 'invalid_source_identity'
    assert read_json(args['out'] / 'financials.json') == []


def test_future_calendar_period_is_rejected_before_any_network_call(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    args.update(through_year=2026, through_report='11011')
    with pytest.raises(ValueError, match='future'):
        module.collect_history(**args, fetch=True, transport=lambda *a, **k: pytest.fail('Future period requested'))


def test_original_missing_xbrl_does_not_prevent_other_receipt_archive_proof(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    def transport(url, params, **kwargs):
        if url.endswith('fnlttXbrl.xml') and params['rcept_no'] == '20160330003536':
            return b'<result><status>014</status><message>Not found</message></result>'
        return zip_bytes()
    report = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True,
        now=NOW, transport=transport)
    assert report['status'] == 'partial' and report['calls_total'] == 4
    assert len(report['captures']) == 3
    assert any(item.get('source_status') == '014' for item in report['failures'])


def test_orphan_original_bytes_are_not_downloaded_again(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    originals = args['out'] / 'originals'
    originals.mkdir()
    (originals / '005930_20160330003536_document.zip').write_bytes(zip_bytes())
    report = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True,
        now=NOW, max_calls=0, transport=lambda *a, **k: pytest.fail('Orphan original must be held'))
    assert 'incomplete_original_snapshot' in [item['error'] for item in report['failures']]


def test_raw_response_digest_and_sanitized_payload_digest_are_both_recorded(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    body = response(complete_rows())
    report = module.collect_history(**args, fetch=True, transport=lambda *a, **k: body)
    assert report['captures'][0]['raw_response_sha256'] == hashlib.sha256(body).hexdigest()
    assert len(report['captures'][0]['payload_sha256']) == 64


def test_cli_without_fetch_leaves_explicit_partial_report(tmp_path, monkeypatch, capsys):
    module = collector()
    args = inputs(tmp_path)
    monkeypatch.setattr(module, '_get_bytes', lambda *a, **k: pytest.fail('Implicit live call'))
    code = module.main(['--cohort-report', str(args['cohort_report']), '--corp-codes', str(args['mapping_path']),
                        '--env-file', str(tmp_path / 'absent.env'), '--out', str(args['out']),
                        '--start-year', '2025', '--through-year', '2025', '--through-report', '11013'])
    assert code == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary['budget']['calls_total'] == 0 and summary['historical_vintage_verified'] is False


def test_failed_original_retains_safe_response_diagnostics(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    body = b'<result><status>014</status></result>'
    report = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True,
        now=NOW, max_calls=1, transport=lambda *a, **k: body)
    failure = report['failures'][0]
    assert failure['source_status'] == '014' and failure['body_bytes'] == len(body)
    assert failure['response_sha256'] == hashlib.sha256(body).hexdigest()
    assert failure['archive_error_reason'] == 'archive_format_or_crc_error'
    assert failure['content_type'] is None and failure['diagnostics_available'] is True


def test_consumed_original_failure_is_reported_without_reinventing_diagnostics(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    ledger_path = args['out'] / 'request_ledger.json'
    ledger = read_json(ledger_path)
    ledger['original_attempts'] = [dict(source='https://opendart.fss.or.kr/api/document.xml',
        rcept_no='20160330003536', kind='document', requested_at=NOW.isoformat(), state='source_error',
        error='original_retrieval_or_archive_validation_failed', response_sha256='a' * 64)]
    ledger_path.write_text(json.dumps(ledger), encoding='utf-8')
    report = module.collect_original_samples(out=args['out'], env_file=tmp_path / 'absent.env', fetch=False, now=NOW)
    first = report['failures'][0]
    assert first['error'] == 'original_retrieval_or_archive_validation_failed'
    assert first['response_sha256'] == 'a' * 64
    assert first['body_bytes'] is None and first['archive_error_reason'] is None
    assert first['diagnostics_available'] is False and report['calls_this_run'] == 0


def test_unsafe_zip_has_specific_local_reason_not_arbitrary_exception_text(tmp_path):
    module = collector()
    args = inputs(tmp_path)
    module.collect_history(**args, fetch=True, transport=missing)
    report = module.collect_original_samples(out=args['out'], env_file=args['env_file'], fetch=True,
        now=NOW, max_calls=1, transport=lambda *a, **k: zip_bytes('../escape.xml'))
    assert report['failures'][0]['archive_error_reason'] == 'unsafe_archive_member_path'


@pytest.mark.parametrize('captured,should_hold', [('2025-05-14T23:30:00+00:00', False),
                                               ('2025-05-14T14:59:00+00:00', True)])
def test_receipt_day_is_compared_to_korean_capture_day_not_utc_day(captured, should_hold):
    module = collector()
    values, _ = module._normalize(complete_rows(), dict(year=2025, report_code='11013', period_end='2025-03-31'),
                                  captured, ['005930'])
    assert ('receipt_after_capture' in values[0]['completeness_reasons']) is should_hold
    assert values[0]['research_usable'] is (not should_hold)
