import csv
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/refresh_alpha_lab_inputs.py'
NOW = datetime(2026, 10, 4, 3, tzinfo=timezone.utc)
AS_OF = '2026-10-02'


def module():
    spec = importlib.util.spec_from_file_location('alpha_refresh_test', SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def fake_collectors(*, fail_stage=None, stale_price=False, changed_final_scope=False, future_capture=False,
                    strict_opens=False, local_financial_metadata=False, live_capture=False):
    calls = []
    ranked = [dict(symbol=f'{100000+i*10:06d}', rank=i+1, name=f'Stock{i}', market='KOSPI', market_cap=1e12-i)
              for i in range(100)]

    def run(command, **kwargs):
        calls.append(command)
        stage = 'prices' if Path(command[1]).name.startswith('collect_') else 'scope' if '--fetch-listing' in command else 'final_scope'
        if stage == fail_stage:
            return CompletedProcess(command, 2, '', 'Error: Source request failed: HTTP 403 https://x.invalid/?crtfc_key=topsecret123')
        arg = lambda key: Path(command[command.index(key)+1])
        captured = (datetime.now(timezone.utc).isoformat() if live_capture else
                    '2026-10-05T00:00:00+00:00' if future_capture else '2026-10-04T01:00:00+00:00')
        if stage in {'scope', 'final_scope'}:
            if strict_opens:
                with arg('--prices').open(encoding='utf-8-sig', newline='') as handle:
                    if any(float(row['open']) <= 0 for row in csv.DictReader(handle) if row.get('open')):
                        return CompletedProcess(command, 2, '', 'Error: open must be finite and positive')
            out = arg('--out')
            if stage == 'scope':
                listing, financials = out/'sources'/f'listing_{AS_OF}.csv', out/'sources'/'financials.json'
                listing.parent.mkdir(parents=True, exist_ok=True)
                listing.write_text('dated listing source', encoding='utf-8')
                write(financials, [])
            else:
                listing, financials = arg('--listing'), arg('--financials')
            own_ranked = [dict(row) for row in ranked]
            if changed_final_scope and stage == 'final_scope':
                own_ranked[-1]['symbol'] = '999990'
            quality = [dict(row, quality_pass=i < 3) for i, row in enumerate(own_ranked)]
            report = dict(as_of=AS_OF, ranking=dict(as_of=AS_OF, ranked=own_ranked),
                          quality=dict(as_of=AS_OF, results=quality, passed=quality[:3]),
                          input_evidence=dict(listing=dict(path=str(listing), sha256=digest(listing), as_of=AS_OF),
                          financials=dict(path=str(financials), sha256=digest(financials),
                                          fetched_at_by_batch=[captured], historical_vintage_verified=False),
                          prices=dict(path=str(arg('--prices')), sha256=digest(arg('--prices'))),
                          generated_at=captured, live_orders=False), historical_validation=dict(status='not_verified'))
            if local_financial_metadata and stage == 'final_scope':
                report['input_evidence']['financials'].pop('fetched_at_by_batch')
            write(out/'report.json', report)
        else:
            out = arg('--output-dir')
            out.mkdir(parents=True, exist_ok=True)
            source = arg('--universe-report')
            day = '2026-10-01' if stale_price else AS_OF
            fields = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'captured_at', 'source', 'price_basis', 'analysis_ready', 'quality_flags']
            with (out/'prices.csv').open('w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for row in ranked:
                    writer.writerow(dict(symbol=row['symbol'], date=day, open=100, high=101, low=99, close=100,
                                         volume=100, captured_at=captured, source='naver_sise_json_public',
                                         price_basis='provider_reported_unverified', analysis_ready='false', quality_flags=''))
            write(out/'manifest.json', dict(start='2005-01-01', end=AS_OF, universe_report_sha256=digest(source)))
            write(out/'report.json', dict(source='naver_sise_json_public', price_basis='provider_reported_unverified',
                selected_symbols=[row['symbol'] for row in ranked], status_counts=dict(collected=100), total_rows=100,
                prices_sha256=digest(out/'prices.csv'), analysis_ready=False, corporate_action_adjustment_verified=False,
                historical_vintage_verified=False, point_in_time_universe_verified=False,
                symbols=[dict(symbol=row['symbol'], status='collected', captured_at=captured,
                              coverage=dict(last_date=day, first_date=day, rows=1)) for row in ranked]))
        return CompletedProcess(command, 0, 'complete', '')
    return run, calls


def seed(tmp_path):
    path = tmp_path/'seed.csv'
    path.write_text('symbol,date,close\n100000,2026-10-01,100\n', encoding='utf-8')
    return path


def test_dry_run_launches_nothing_and_uses_last_closed_weekday(tmp_path):
    run, calls = fake_collectors()
    out = module().refresh_inputs(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=run, now=NOW, dry_run=True)
    assert out['as_of'] == AS_OF
    assert out['status'] == 'dry_run'
    assert not calls
    assert not (tmp_path/'inputs').exists()
    assert len(out['commands']) == 3


def test_atomic_pointer_joins_same_real_sources_and_reuses_completed_snapshot(tmp_path):
    mod = module()
    run, calls = fake_collectors()
    out = mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=run, now=NOW, fetch=True)
    pointer = json.loads((tmp_path/'inputs/current.json').read_text())
    assert out['status'] == 'complete'
    assert len(calls) == 3
    for key in ('prices', 'price_manifest', 'universe_report'):
        path = tmp_path/'inputs'/pointer[key]
        assert path.is_file()
        assert digest(path) == pointer['hashes'][key]
    assert pointer['source_metadata']['historical_vintage_verified'] is False
    assert pointer['source_metadata']['analysis_ready'] is False
    assert pointer['quality_count'] == 3
    mod.refresh_inputs(root=tmp_path/'inputs', runner=run, now=NOW, fetch=True)
    assert len(calls) == 3


@pytest.mark.parametrize('bad', ['stale_price', 'changed_final_scope', 'future_capture'])
def test_inconsistent_sources_never_publish_a_current_snapshot(tmp_path, bad):
    run, _ = fake_collectors(**{bad: True})
    mod = module()
    with pytest.raises(mod.RefreshError):
        mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=run, now=NOW, fetch=True)
    assert not (tmp_path/'inputs/current.json').exists()


def test_subprocess_failure_preserves_old_pointer_and_never_records_secret_output(tmp_path):
    mod = module()
    root = tmp_path/'inputs'
    root.mkdir()
    write(root/'current.json', dict(old='preserve'))
    before = (root/'current.json').read_bytes()
    run, _ = fake_collectors(fail_stage='scope')
    with pytest.raises(mod.RefreshError) as error:
        mod.refresh_inputs(root=root, seed_prices=seed(tmp_path), runner=run, now=NOW, fetch=True)
    assert (root/'current.json').read_bytes() == before
    audit = json.loads((root/'last_attempt.json').read_text())
    assert audit['stage'] == 'scope'
    assert audit['returncode'] == 2
    assert audit['http_status'] == 403
    assert audit['stderr_sha256']
    assert 'topsecret123' not in json.dumps(audit)
    assert 'topsecret123' not in str(error.value)


def test_unverified_offline_request_never_enables_network_implicitly(tmp_path):
    mod = module()
    run, calls = fake_collectors()
    with pytest.raises(mod.RefreshError, match='fetch_opt_in_required'):
        mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=run, now=NOW)
    assert not calls


def test_failed_partial_price_stage_resumes_without_refetching_completed_scope(tmp_path):
    mod = module()
    run, calls = fake_collectors()
    failed = False

    def partial_once(command, **kwargs):
        nonlocal failed
        result = run(command, **kwargs)
        if Path(command[1]).name.startswith('collect_') and not failed:
            failed = True
            directory = Path(command[command.index('--output-dir')+1])
            report = json.loads((directory/'report.json').read_text())
            report['status_counts'] = dict(collected=99, failed=1)
            write(directory/'report.json', report)
            return CompletedProcess(command, 2, '', 'partial collection')
        return result

    kwargs = dict(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=partial_once, now=NOW, fetch=True)
    with pytest.raises(mod.RefreshError):
        mod.refresh_inputs(**kwargs)
    out = mod.refresh_inputs(**kwargs)
    assert out['status'] == 'complete'
    assert len(calls) == 4
    assert sum('--fetch-listing' in command for command in calls) == 1


def test_sealed_completed_snapshot_recovers_interrupted_pointer_publication(tmp_path):
    mod = module()
    run, calls = fake_collectors()
    root, seed_path = tmp_path/'inputs', seed(tmp_path)
    mod.refresh_inputs(root=root, seed_prices=seed_path, runner=run, now=NOW, fetch=True)
    expected = (root/'current.json').read_bytes()
    (root/'current.json').unlink()
    out = mod.refresh_inputs(root=root, seed_prices=seed_path, runner=run, now=NOW, fetch=True)
    assert out['status'] == 'complete'
    assert len(calls) == 3
    assert (root/'current.json').read_bytes() == expected


def test_period_before_annual_deadline_uses_prior_third_quarter():
    assert module()._period('2026-03-02', None, None) == (2025, '11014')
    assert module()._period('2026-04-01', None, None) == (2025, '11011')


def test_source_capture_files_cannot_escape_the_snapshot_directory(tmp_path):
    mod = module()
    run, _ = fake_collectors()
    outside = tmp_path/'unrelated.json'
    write(outside, [])

    def redirect_source(command, **kwargs):
        result = run(command, **kwargs)
        if '--fetch-listing' in command:
            scope = Path(command[command.index('--out')+1])/'report.json'
            report = json.loads(scope.read_text())
            report['input_evidence']['financials'].update(path=str(outside), sha256=digest(outside))
            write(scope, report)
        return result

    with pytest.raises(mod.RefreshError, match='scope_source_path_outside_snapshot'):
        mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=redirect_source, now=NOW, fetch=True)


def test_halted_zero_open_is_projected_for_screen_without_modifying_raw_ohlcv(tmp_path):
    mod = module()
    seed_path = seed(tmp_path)
    seed_path.write_text('symbol,date,open,high,low,close,volume\n100000,2026-10-01,0,0,0,100,0\n')
    before = seed_path.read_bytes()
    run, calls = fake_collectors(strict_opens=True)
    out = mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed_path, runner=run, now=NOW, fetch=True)
    assert out['status'] == 'complete'
    assert seed_path.read_bytes() == before
    for command in (calls[0], calls[2]):
        projected = Path(command[command.index('--prices')+1])
        with projected.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            assert not {'open', 'high', 'low'} & set(reader.fieldnames)
    scope = json.loads((tmp_path/'inputs'/out['universe_report']).read_text())
    source = scope['input_evidence']['prices']['source_price_input']
    assert source['sha256'] == digest(tmp_path/'inputs'/out['prices'])
    assert source['transformation'] == 'close_volume_projection_no_ohlc_inference'


def test_local_final_screen_inherits_only_verified_same_file_financial_capture(tmp_path):
    mod = module()
    run, _ = fake_collectors(local_financial_metadata=True)
    out = mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=run, now=NOW, fetch=True)
    scope = json.loads((tmp_path/'inputs'/out['universe_report']).read_text())
    assert scope['input_evidence']['financials']['fetched_at_by_batch'] == ['2026-10-04T01:00:00+00:00']


def test_real_time_capture_after_refresh_start_is_validated_at_publication_time(tmp_path):
    mod = module()
    run, _ = fake_collectors(live_capture=True)
    out = mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed(tmp_path), runner=run, as_of=AS_OF, fetch=True)
    assert out['status'] == 'complete'
    assert datetime.fromisoformat(out['published_at']) >= datetime.fromisoformat(out['source_metadata']['captured_at'])
