"""Use the real workflow completion pipeline with deterministic analysis inputs."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import venv
from datetime import datetime, timedelta, timezone

import pytest

from app.services.mirofish import chart_analogue, chart_analogue_evaluation as evaluation, semantic_ranking, workflow
from tests.test_admin_mirofish_workflow import _analysis_run, _candidate, _scanner_result


@pytest.fixture
def completion(monkeypatch, tmp_path):
    candidates = [_candidate(f'{n:06d}', f'Stock {n}', 90 - n, 20, n) for n in range(1, 6)]
    monkeypatch.setenv('MIROFISH_TRADINGAGENTS_DISABLED', 'true')
    monkeypatch.setattr(evaluation, 'ROOT', tmp_path / 'evaluation')
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'state'))
    monkeypatch.setattr(semantic_ranking, 'apply', lambda rows, **kwargs: (rows, {'status': 'disabled'}))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *a, **k: _scanner_result(candidates))
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode:
                        _analysis_run(candidate, action='HOLD' if candidate['symbol'] == '000001' else 'BUY'))
    monkeypatch.setattr(workflow.outcome_tracker, 'refresh_workflow_outcomes', lambda *a, **kw: {'status': 'pending', 'items': []})
    monkeypatch.setattr(workflow.ta_learning, 'persist_workflow_learning', lambda *a, **kw: ({'status': 'pending'}, {}))
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    reference_day = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    artifact = {'run_id': 'mfas_test', 'generated_at': cutoff, 'as_of': cutoff,
                'items': [{'symbol': c['symbol'], 'status': 'ready', 'mode': 'shadow',
                           'as_of': cutoff, 'model_version': 'chart_v1', 'sample_count': 20,
                           'source': {'source_id': 'test_daily_prices', 'price_basis': 'unadjusted',
                                      'latest_session': reference_day, 'captured_at': cutoff},
                           'history': [{'date': reference_day, 'close': 100 + n}],
                           'horizons': [{'sessions': h, 'median_return_pct': n,
                                         'p10_return_pct': -10, 'p90_return_pct': 30,
                                         'up_frequency_pct': 60} for h in (5, 20, 40)]}
                          for n, c in enumerate(candidates, start=1)]}
    read_calls = []

    def original_forecasts(run_id, filename):
        read_calls.append((run_id, filename))
        return copy.deepcopy(artifact)

    monkeypatch.setattr(workflow.alpha_scanner, 'read_scanner_run_artifact', original_forecasts)
    monkeypatch.setattr(chart_analogue, 'predict', lambda *a, **kw: pytest.fail('Completion must not re-predict'))
    writes = []
    real_write = workflow._write_workflow

    def capture_write(record):
        if record.get('status') == 'completed':
            writes.append(copy.deepcopy(record))
        return real_write(record)

    monkeypatch.setattr(workflow, '_write_workflow', capture_write)
    return {'candidates': candidates, 'reads': read_calls, 'writes': writes}


def test_completion_freezes_all_buy_eligible_results_before_final_workflow_write(completion):
    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 5, 'top_n': 3, 'require_buy': True}, async_mode=False, commit_event_state=False)
    assert result['status'] == 'completed'
    assert 'chart_analogue_evaluation' in completion['writes'][-1]
    assert completion['reads'] == [('mfas_test', 'chart_analogue.json')]
    report = evaluation.read_report()
    row = report['recent'][0]
    assert row['baseline'] == [{key: pick[key] for key in ('symbol', 'target')} for pick in result['top3']]
    assert [r['symbol'] for r in row['challenger']] == ['000005', '000004', '000003']
    assert '000001' not in {r['symbol'] for r in row['challenger']}
    assert report['counts']['eligible_days'] == 1
    assert result['chart_analogue_evaluation']['recorded_at'] >= result['completed_at']


def test_evaluation_failure_is_visible_and_does_not_change_top3_or_completion(completion, monkeypatch):
    def failed_record(*args, **kwargs):
        raise OSError('local evaluation storage unavailable')

    monkeypatch.setattr(evaluation, 'record_workflow', failed_record)
    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 5, 'top_n': 3, 'require_buy': True}, async_mode=False, commit_event_state=False)
    assert result['status'] == 'completed'
    assert len(result['top3']) == 3
    assert all(pick['verdict']['action'] == 'BUY' for pick in result['top3'])
    assert result['chart_analogue_evaluation'] == {'status': 'unavailable', 'reason': 'record_failed:OSError'}
    assert completion['writes'][-1]['chart_analogue_evaluation']['status'] == 'unavailable'


@pytest.fixture(scope='module')
def nightly_harness(tmp_path_factory):
    """Execute the real PowerShell stage coordinator, with offline stage spies."""
    shell = shutil.which('powershell') or shutil.which('pwsh')
    if not shell or os.name != 'nt':
        pytest.skip('Windows PowerShell refresh contract')
    root = tmp_path_factory.mktemp('chart-nightly')
    venv.EnvBuilder(with_pip=False, symlinks=False).create(root / '.venv')
    scripts = root / 'scripts'
    scripts.mkdir()
    index = root / 'data' / 'chart_analogue'
    index.mkdir(parents=True)
    (root / 'data' / 'daily_prices.csv').write_text('ticker,date\n', encoding='utf-8')
    stub = '''import json, os, pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
with (root / 'stage_calls.jsonl').open('a', encoding='utf-8') as handle:
    handle.write(json.dumps({'stage': pathlib.Path(__file__).stem, 'args': sys.argv[1:]})+'\\n')
if pathlib.Path(__file__).stem == 'scan_chart_analogue_kelly':
    raise SystemExit(int(os.environ.get('CHART_KELLY_TEST_EXIT', '0')))
'''
    for name in ('refresh_chart_analogue_prices', 'build_chart_analogue_index',
                 'evaluate_chart_analogue_shadow', 'scan_chart_analogue_top3', 'scan_chart_analogue_kelly'):
        (scripts / (name+'.py')).write_text(stub, encoding='utf-8')
    real_script = Path(__file__).resolve().parents[1] / 'scripts' / 'refresh_chart_analogue_index.ps1'
    return root, shell, real_script


def run_nightly(harness, *, prepared=True, exit_code=0, universe_override=None):
    root, shell, script = harness
    calls = root / 'stage_calls.jsonl'
    calls.unlink(missing_ok=True)
    prepared_path = root / 'data' / 'chart_analogue' / 'kelly' / 'universe.json'
    if prepared:
        prepared_path.parent.mkdir(exist_ok=True)
        prepared_path.write_text('{}', encoding='utf-8')
    else:
        prepared_path.unlink(missing_ok=True)
        # An unrelated scope elsewhere must not satisfy canonical readiness.
        (root / 'data' / 'universe.json').write_text('{}', encoding='utf-8')
    environment = dict(os.environ, CHART_KELLY_TEST_EXIT=str(exit_code))
    if universe_override is not None:
        environment['MIROFISH_CHART_KELLY_UNIVERSE'] = str(universe_override)
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(script), '-Root', str(root)],
                            text=True, capture_output=True, timeout=30, env=environment)
    recorded = [json.loads(line) for line in calls.read_text(encoding='utf-8').splitlines()]
    return result, recorded


def test_nightly_kelly_runs_after_prepared_index_evaluation_top3(nightly_harness):
    root, _, _ = nightly_harness
    result, calls = run_nightly(nightly_harness)
    assert result.returncode == 0, result.stderr
    assert [row['stage'] for row in calls] == ['refresh_chart_analogue_prices', 'build_chart_analogue_index',
           'evaluate_chart_analogue_shadow', 'scan_chart_analogue_top3', 'scan_chart_analogue_kelly']
    arguments = calls[-1]['args']
    assert arguments == ['--root', str(root / 'data' / 'chart_analogue' / 'kelly'),
                         '--index-root', str(root / 'data' / 'chart_analogue'),
                         '--universe', str(root / 'data' / 'chart_analogue' / 'kelly' / 'universe.json')]


def test_nightly_skips_without_canonical_dated_scope(nightly_harness):
    result, calls = run_nightly(nightly_harness, prepared=False)
    assert result.returncode == 0
    assert len(calls) == 4
    assert 'Kelly research scan skipped' in result.stdout


def test_nightly_blocked_scope_is_visible_warning_with_prepared_index_retained(nightly_harness):
    result, calls = run_nightly(nightly_harness, exit_code=2)
    assert result.returncode == 0, result.stderr
    assert calls[-1]['stage'] == 'scan_chart_analogue_kelly'
    assert 'Kelly research scan held' in result.stdout
    assert 'prepared price index retained' in ' '.join(result.stdout.split())


@pytest.mark.parametrize('exit_code', [1, 3])
def test_nightly_research_failure_is_not_reported_as_success(nightly_harness, exit_code):
    result, calls = run_nightly(nightly_harness, exit_code=exit_code)
    assert result.returncode != 0
    assert calls[-1]['stage'] == 'scan_chart_analogue_kelly'
    assert 'Kelly research scan failed' in result.stderr
    assert 'prepared price index retained' in result.stderr


def test_nightly_kelly_is_optional_when_scanner_not_installed(nightly_harness):
    root, _, _ = nightly_harness
    scanner = root / 'scripts' / 'scan_chart_analogue_kelly.py'
    content = scanner.read_text(encoding='utf-8')
    scanner.unlink()
    try:
        result, calls = run_nightly(nightly_harness)
    finally:
        scanner.write_text(content, encoding='utf-8')
    assert result.returncode == 0
    assert len(calls) == 4
    assert 'Kelly research scan skipped' in result.stdout


def test_nightly_pins_canonical_scope_even_with_environment_override(nightly_harness):
    root, _, _ = nightly_harness
    unrelated = root / 'data' / 'unrelated_quality_scope.json'
    unrelated.write_text('{"as_of":"2099-01-01"}', encoding='utf-8')
    result, calls = run_nightly(nightly_harness, universe_override=unrelated)
    assert result.returncode == 0, result.stderr
    arguments = calls[-1]['args']
    assert arguments[arguments.index('--universe')+1] == str(root / 'data' / 'chart_analogue' / 'kelly' / 'universe.json')
    assert str(unrelated) not in arguments
