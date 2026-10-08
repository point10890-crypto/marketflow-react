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
                    strict_opens=False, local_financial_metadata=False, live_capture=False, captured_at=None):
    calls = []
    ranked = [dict(symbol=f'{100000+i*10:06d}', rank=i+1, name=f'Stock{i}', market='KOSPI', market_cap=1e12-i)
              for i in range(100)]

    def run(command, **kwargs):
        calls.append(command)
        stage = 'prices' if Path(command[1]).name.startswith('collect_') else 'scope' if '--fetch-listing' in command else 'final_scope'
        if stage == fail_stage:
            return CompletedProcess(command, 2, '', 'Error: Source request failed: HTTP 403 https://x.invalid/?crtfc_key=topsecret123')
        arg = lambda key: Path(command[command.index(key)+1])
        as_of = command[command.index('--end' if stage == 'prices' else '--as-of')+1]
        captured = (captured_at if captured_at is not None else datetime.now(timezone.utc).isoformat() if live_capture else
                    '2026-10-05T00:00:00+00:00' if future_capture else '2026-10-04T01:00:00+00:00')
        if stage in {'scope', 'final_scope'}:
            if strict_opens:
                with arg('--prices').open(encoding='utf-8-sig', newline='') as handle:
                    if any(float(row['open']) <= 0 for row in csv.DictReader(handle) if row.get('open')):
                        return CompletedProcess(command, 2, '', 'Error: open must be finite and positive')
            out = arg('--out')
            if stage == 'scope':
                listing, financials = out/'sources'/f'listing_{as_of}.csv', out/'sources'/'financials.json'
                listing.parent.mkdir(parents=True, exist_ok=True)
                listing.write_text('dated listing source', encoding='utf-8')
                write(financials, [])
            else:
                listing, financials = arg('--listing'), arg('--financials')
            own_ranked = [dict(row) for row in ranked]
            if changed_final_scope and stage == 'final_scope':
                own_ranked[-1]['symbol'] = '999990'
            quality = [dict(row, quality_pass=i < 3) for i, row in enumerate(own_ranked)]
            report = dict(as_of=as_of, ranking=dict(as_of=as_of, ranked=own_ranked),
                          quality=dict(as_of=as_of, results=quality, passed=quality[:3]),
                          input_evidence=dict(listing=dict(path=str(listing), sha256=digest(listing), as_of=as_of),
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
            day = '2026-10-01' if stale_price else as_of
            fields = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'captured_at', 'source', 'price_basis', 'analysis_ready', 'quality_flags']
            with (out/'prices.csv').open('w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for row in ranked:
                    writer.writerow(dict(symbol=row['symbol'], date=day, open=100, high=101, low=99, close=100,
                                         volume=100, captured_at=captured, source='naver_sise_json_public',
                                         price_basis='provider_reported_unverified', analysis_ready='false', quality_flags=''))
            write(out/'manifest.json', dict(start='2005-01-01', end=as_of, universe_report_sha256=digest(source)))
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


@pytest.mark.parametrize('clock', ['2026-10-08T15:30:00+09:00', '2026-10-08T18:45:00+09:00',
                                  '2026-10-08T20:29:59+09:00'])
def test_same_day_before_acquisition_cutoff_rejected_before_network_or_write(tmp_path, clock):
    mod = module()
    run, calls = fake_collectors(captured_at=clock)
    root = tmp_path/'inputs'
    with pytest.raises(mod.RefreshError, match='requested_session_not_closed'):
        mod.refresh_inputs(root=root, seed_prices=seed(tmp_path), runner=run, now=datetime.fromisoformat(clock),
                           as_of='2026-10-08', fetch=True)
    assert not calls
    assert not root.exists()


@pytest.mark.parametrize(('clock', 'expected'), [
    ('2026-10-08T20:29:59+09:00', '2026-10-07'),
    ('2026-10-08T20:30:00+09:00', '2026-10-08'),
    ('2026-10-12T18:45:00+09:00', '2026-10-09'),
])
def test_default_session_waits_for_acquisition_cutoff(tmp_path, clock, expected):
    run, calls = fake_collectors()
    root = tmp_path/'inputs'
    result = module().refresh_inputs(root=root, seed_prices=seed(tmp_path), runner=run,
                                    now=datetime.fromisoformat(clock), dry_run=True)
    assert result['as_of'] == expected
    assert not calls
    assert not root.exists()


def alter_one_price_capture(directory, location, capture='2026-10-08T18:45:00+09:00'):
    report = json.loads((directory/'report.json').read_text())
    if location == 'metadata':
        report['symbols'][0]['captured_at'] = capture
    else:
        with (directory/'prices.csv').open(encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        if location == 'historical_csv':
            rows.append(dict(rows[0], date='2026-10-07', captured_at=capture))
            report['total_rows'] += 1
            report['symbols'][0]['coverage'].update(rows=2, first_date='2026-10-07')
        else:
            rows[0]['captured_at'] = capture
        with (directory/'prices.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        report['prices_sha256'] = digest(directory/'prices.csv')
    write(directory/'report.json', report)


@pytest.mark.parametrize('location', ['metadata', 'csv', 'historical_csv'])
def test_every_price_capture_must_follow_requested_session_cutoff(tmp_path, location):
    mod = module()
    run, calls = fake_collectors(captured_at='2026-10-08T20:30:00+09:00')
    root = tmp_path/'inputs'

    def retained_provisional_capture(command, **kwargs):
        result = run(command, **kwargs)
        if Path(command[1]).name.startswith('collect_'):
            alter_one_price_capture(Path(command[command.index('--output-dir')+1]), location)
        return result

    with pytest.raises(mod.RefreshError, match='price_capture_before_acquisition_cutoff'):
        mod.refresh_inputs(root=root, seed_prices=seed(tmp_path), runner=retained_provisional_capture,
                           as_of='2026-10-08', now=datetime.fromisoformat('2026-10-08T20:40:00+09:00'), fetch=True)
    assert len(calls) == 2
    assert not (root/'current.json').exists()


def test_cutoff_capture_is_accepted_without_certifying_finality(tmp_path):
    mod = module()
    clock = datetime.fromisoformat('2026-10-08T20:30:00+09:00')
    run, _ = fake_collectors(captured_at=clock.isoformat())
    seed_path = seed(tmp_path)
    out = mod.refresh_inputs(root=tmp_path/'inputs', seed_prices=seed_path, runner=run, now=clock,
                             as_of='2026-10-08', fetch=True)
    assert out['settings'].get('acquisition_policy_version') == 'postmarket_2030_kst_v1'
    assert out['source_metadata']['calendar_verified'] is False
    assert out['source_metadata']['corporate_action_adjustment_verified'] is False


@pytest.mark.parametrize('location', ['metadata', 'csv'])
def test_retry_after_cutoff_never_promotes_retained_pre_cutoff_capture(tmp_path, location):
    mod = module()
    run, calls = fake_collectors(captured_at='2026-10-08T20:30:00+09:00')
    price_attempts = 0
    root = tmp_path/'inputs'

    def partial_then_retained_cache(command, **kwargs):
        nonlocal price_attempts
        if Path(command[1]).name.startswith('collect_'):
            price_attempts += 1
            directory = Path(command[command.index('--output-dir')+1])
            if price_attempts == 2:
                calls.append(command)
                report = json.loads((directory/'report.json').read_text())
                report['status_counts'] = dict(collected=100)
                write(directory/'report.json', report)
                return CompletedProcess(command, 0, 'resumed cached bars', '')
        result = run(command, **kwargs)
        if Path(command[1]).name.startswith('collect_'):
            alter_one_price_capture(directory, location)
            report = json.loads((directory/'report.json').read_text())
            report['status_counts'] = dict(collected=99, failed=1)
            write(directory/'report.json', report)
            return CompletedProcess(command, 2, '', 'partial collection')
        return result

    kwargs = dict(root=root, seed_prices=seed(tmp_path), runner=partial_then_retained_cache,
                  as_of='2026-10-08', now=datetime.fromisoformat('2026-10-08T20:40:00+09:00'), fetch=True)
    with pytest.raises(mod.RefreshError, match='collector_failed:prices'):
        mod.refresh_inputs(**kwargs)
    scope = next((root/'snapshots').glob('*/scope/report.json'))
    before = scope.read_bytes()
    kwargs['now'] = datetime.fromisoformat('2026-10-08T21:10:00+09:00')
    with pytest.raises(mod.RefreshError, match='price_capture_before_acquisition_cutoff'):
        mod.refresh_inputs(**kwargs)
    assert scope.read_bytes() == before
    assert sum('--fetch-listing' in command for command in calls) == 1
    assert price_attempts == 2
    assert not (root/'current.json').exists()


@pytest.mark.parametrize('location', ['metadata', 'csv'])
@pytest.mark.parametrize('current_exists', [True, False])
def test_reuse_and_sealed_recovery_recheck_every_capture_without_changing_sources(tmp_path, location, current_exists):
    mod = module()
    clock = datetime.fromisoformat('2026-10-08T20:40:00+09:00')
    run, calls = fake_collectors(captured_at='2026-10-08T20:30:00+09:00')
    root, seed_path = tmp_path/'inputs', seed(tmp_path)
    out = mod.refresh_inputs(root=root, seed_prices=seed_path, runner=run, now=clock,
                             as_of='2026-10-08', fetch=True)
    directory = (root/out['prices']).parent
    alter_one_price_capture(directory, location)
    pointer = json.loads((root/'current.json').read_text())
    for key in ('prices', 'price_manifest'):
        pointer['hashes'][key] = digest(root/pointer[key])
    sealed = directory.parent/'sealed.json'
    write(sealed, pointer)
    write(root/'current.json', pointer)
    if not current_exists:
        (root/'current.json').unlink()
    original = {path: path.read_bytes() for path in (sealed, directory/'report.json', directory/'prices.csv')}
    with pytest.raises(mod.RefreshError, match='price_capture_before_acquisition_cutoff'):
        mod.refresh_inputs(root=root, seed_prices=seed_path, runner=run, now=clock,
                           as_of='2026-10-08', fetch=True)
    assert len(calls) == 3
    assert all(path.read_bytes() == content for path, content in original.items())
    if not current_exists:
        assert not (root/'current.json').exists()


def legacy_provisional_snapshot(mod, root, seed_path):
    """Pre-policy 18:45 fixture with the original request identity and artifacts."""
    as_of, captured = '2026-10-08', '2026-10-08T18:45:00+09:00'
    settings = dict(start='2005-01-01', year=2026, report_code='11012', top_n=100)
    request = dict(as_of=as_of, **settings, seed_prices_sha256=digest(seed_path), capture_day=as_of)
    legacy_id = as_of+'-'+hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:20]
    destination = root/'snapshots'/legacy_id
    scope, prices, final = destination/'scope', destination/'prices', destination/'universe'
    run, _ = fake_collectors(captured_at=captured)
    projection = mod._screen_projection(seed_path, scope/'technical_prices.csv')
    run(['python', 'screen_large_cap_kelly.py', '--as-of', as_of, '--fetch-listing',
         '--prices', str(scope/'technical_prices.csv'), '--out', str(scope)])
    mod._link_screen_evidence(scope/'report.json', projection)
    run(['python', 'collect_large_cap_price_history.py', '--end', as_of,
         '--universe-report', str(scope/'report.json'), '--output-dir', str(prices)])
    projection = mod._screen_projection(prices/'prices.csv', final/'technical_prices.csv')
    run(['python', 'screen_large_cap_kelly.py', '--as-of', as_of, '--prices', str(final/'technical_prices.csv'),
         '--listing', str(scope/'sources'/f'listing_{as_of}.csv'),
         '--financials', str(scope/'sources'/'financials.json'), '--out', str(final)])
    mod._link_screen_evidence(final/'report.json', projection, json.loads((scope/'report.json').read_text()))
    artifacts = dict(prices=prices/'prices.csv', price_manifest=prices/'report.json', universe_report=final/'report.json')
    pointer = dict(schema_version=1, snapshot_id=legacy_id, as_of=as_of, latest_session=as_of,
                   published_at=captured, settings=settings, ranked_count=100, quality_count=3,
                   hashes={key: digest(path) for key, path in artifacts.items()},
                   source_metadata=dict(price_source=mod.SOURCE, price_basis=mod.BASIS, captured_at=captured,
                       financial_captures=[captured], screen_price_input=projection, analysis_ready=False,
                       corporate_action_adjustment_verified=False, historical_vintage_verified=False,
                       point_in_time_universe_verified=False, current_cohort_bias=True, calendar_verified=False,
                       financial_period_policy='conservative_standard_deadline_not_latest_filing_search'),
                   **{key: path.relative_to(root).as_posix() for key, path in artifacts.items()})
    write(destination/'sealed.json', pointer)
    write(root/'current.json', pointer)
    return pointer, destination


def test_real_legacy_policy_migration_creates_fresh_snapshot_and_preserves_all_sources(tmp_path):
    mod = module()
    clock = datetime.fromisoformat('2026-10-08T20:40:00+09:00')
    run, calls = fake_collectors(captured_at='2026-10-08T20:30:00+09:00')
    root, seed_path = tmp_path/'inputs', seed(tmp_path)
    legacy, destination = legacy_provisional_snapshot(mod, root, seed_path)
    original = {path: path.read_bytes() for path in destination.rglob('*') if path.is_file()}
    out = mod.refresh_inputs(root=root, seed_prices=seed_path, runner=run, now=clock,
                             as_of='2026-10-08', fetch=True)
    assert out['reused'] is False
    assert out['snapshot_id'] != legacy['snapshot_id']
    assert out['settings']['acquisition_policy_version'] == 'postmarket_2030_kst_v1'
    assert all(path.read_bytes() == content for path, content in original.items())
    assert json.loads((destination/'sealed.json').read_text()) == legacy
    assert json.loads((root/'current.json').read_text())['snapshot_id'] == out['snapshot_id']
    assert len(calls) == 3
    again = mod.refresh_inputs(root=root, seed_prices=seed_path, runner=run, now=clock,
                               as_of='2026-10-08', fetch=True)
    assert again['reused'] is True
    assert again['snapshot_id'] == out['snapshot_id']
    assert len(calls) == 3
