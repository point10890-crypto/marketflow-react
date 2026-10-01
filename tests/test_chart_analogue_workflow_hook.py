"""Use the real workflow completion pipeline with deterministic analysis inputs."""

import copy
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
