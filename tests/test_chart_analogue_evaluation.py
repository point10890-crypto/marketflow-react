"""Prospective comparisons select cohorts before any outcomes are observable."""

import copy
import concurrent.futures
import importlib
import json
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from app.services.mirofish import alpha_scanner, chart_analogue


NOW = datetime(2026, 10, 2, 6, tzinfo=timezone.utc)
HORIZONS = (5, 20, 40)
EVALUATION_SOURCE = {'source_id': 'vendor_a', 'price_basis': 'unadjusted',
                     'built_at': '2027-01-01T08:00:00+00:00', 'rows': 10000, 'symbols': 5}


@pytest.fixture
def service(monkeypatch):
    # Outcomes are mocked below; their shared saved-index seam remains explicit.
    monkeypatch.setattr(chart_analogue, '_load', lambda full=False, index_root=None:
                        ({'metadata': {'source': copy.deepcopy(EVALUATION_SOURCE)}}, None))
    try:
        return importlib.import_module('app.services.mirofish.chart_analogue_evaluation')
    except ModuleNotFoundError as exc:
        if exc.name != 'app.services.mirofish.chart_analogue_evaluation':
            raise
        def missing(*args, **kwargs):
            pytest.fail('The prospective chart evaluation service is not implemented')
        return SimpleNamespace(record_workflow=missing, evaluate=missing, read_report=missing)


def _item(number, score=None, action='BUY'):
    return {'symbol': f'{number:06d}', 'target': f'Stock {number}',
            'final_score': score if score is not None else 100 - number,
            'status': 'completed', 'analysis_status': 'SUCCESS_PRIMARY',
            'verdict': {'action': action},
            'candidate': {'symbol': f'{number:06d}', 'display_name': f'Stock {number}', 'market': 'KR'}}


def _workflow(workflow_id='workflow_test_1', decision=NOW - timedelta(minutes=1), count=5):
    rows = [_item(n) for n in range(1, count + 1)]
    return {'id': workflow_id, 'scanner_run_id': 'scanner_test_1', 'status': 'completed',
            'completed_at': decision.isoformat(), 'analysis_runs': rows, 'top3': rows[:3],
            'filters': {'require_buy': True}}


def _forecasts(workflow, medians=None):
    cutoff = (datetime.fromisoformat(workflow['completed_at']) - timedelta(minutes=5)).isoformat()
    medians = medians or {1: 1, 2: 2, 3: 3, 4: 20, 5: 30}
    return {'run_id': workflow['scanner_run_id'], 'as_of': cutoff, 'generated_at': cutoff,
            'items': [{'symbol': f'{n:06d}', 'target': f'Stock {n}', 'status': 'ready', 'mode': 'shadow',
                       'as_of': cutoff, 'model_version': 'chart_v1', 'sample_count': 20,
                       'source': {'source_id': 'vendor_a', 'price_basis': 'unadjusted',
                                  'captured_at': (datetime.fromisoformat(cutoff) - timedelta(minutes=1)).isoformat(),
                                  'latest_session': '2026-10-01'},
                       'history': [{'date': '2026-10-01', 'close': 100 + n}],
                       'horizons': [{'sessions': h, 'median_return_pct': medians.get(n, 0),
                                     'p10_return_pct': -10, 'p90_return_pct': 50,
                                     'up_frequency_pct': 60} for h in HORIZONS]}
                      for n in range(1, len(workflow['analysis_runs']) + 1)]}


def _outcomes(symbol, *, decision_at, reference_session, frozen_reference_close, as_of,
              expected_source_id, expected_price_basis, index_root=None, _loaded_index=None):
    number = int(symbol)
    gross = number * 2.0
    rows = [{'sessions': h, 'status': 'matured', 'reason': None, 'observed_sessions': 50,
             'entry_date': '2026-10-05', 'entry_close': 100,
             'exit_date': '2026-12-02', 'exit_close': 100 + gross,
             'captured_at': '2026-12-02T07:30:00+00:00', 'gross_return_pct': gross} for h in HORIZONS]
    return {'source': copy.deepcopy(EVALUATION_SOURCE),
            'reference': {'session': reference_session, 'frozen_close': frozen_reference_close,
                          'evaluated_close': frozen_reference_close, 'rebased': False},
            'forecast_horizons': copy.deepcopy(rows), 'trade_horizons': rows}


def _json_files(root):
    return sorted((root / 'snapshots').glob('*.json'))


def test_record_freezes_actual_top3_and_challenger_with_no_new_predictions(service, tmp_path, monkeypatch):
    workflow = _workflow()
    artifact = _forecasts(workflow)
    monkeypatch.setattr(alpha_scanner, 'read_scanner_run_artifact', lambda rid, name: artifact)
    monkeypatch.setattr(chart_analogue, 'predict', lambda *a, **kw: pytest.fail('Freeze must read the original artifact'))
    snapshot = service.record_workflow(workflow, now=NOW, root=tmp_path)
    assert snapshot['recorded_at'] == NOW.isoformat()
    assert snapshot['decision_at'] == workflow['completed_at']
    assert snapshot['aggregate_eligible'] is True
    assert [r['symbol'] for r in snapshot['baseline']] == ['000001', '000002', '000003']
    assert [r['symbol'] for r in snapshot['challenger']] == ['000005', '000004', '000003']
    assert snapshot['forecasts']['000005']['reference_close'] == 105
    assert snapshot['forecasts']['000005']['reference_session'] == '2026-10-01'
    assert len(snapshot['forecasts']) == 5
    artifact['items'][0]['horizons'][1]['median_return_pct'] = 999
    assert json.loads(_json_files(tmp_path)[0].read_text(encoding='utf-8'))['forecasts']['000001']['horizons'][1]['median_return_pct'] == 1
    report = service.read_report(root=tmp_path)
    assert report['status'] == 'collecting'
    assert report['counts'] == {'recorded': 1, 'eligible_days': 1, 'pending': 1, 'blocked': 0, 'intraday_excluded': 0}
    assert report['recent'][0]['workflow_id'] == workflow['id']
    assert all(h['baseline_net_return_pct'] is None for h in report['horizons'])


def test_snapshot_is_write_once_even_if_forecasts_or_completion_time_change(service, tmp_path):
    workflow = _workflow()
    first = service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW, root=tmp_path)
    saved = _json_files(tmp_path)[0].read_bytes()
    workflow['completed_at'] = (NOW + timedelta(days=4)).isoformat()
    second = service.record_workflow(workflow, forecasts={}, now=NOW + timedelta(days=4), root=tmp_path)
    assert second == first
    assert _json_files(tmp_path)[0].read_bytes() == saved
    assert service.read_report(root=tmp_path)['counts']['recorded'] == 1


def test_only_first_valid_kst_day_cohort_is_paired_even_when_it_is_pending(service, tmp_path, monkeypatch):
    first = _workflow('workflow_first', decision=NOW - timedelta(minutes=3))
    second = _workflow('workflow_later', decision=NOW - timedelta(minutes=1))
    a = service.record_workflow(first, forecasts=_forecasts(first), now=NOW, root=tmp_path)
    b = service.record_workflow(second, forecasts=_forecasts(second), now=NOW + timedelta(minutes=1), root=tmp_path)
    assert a['aggregate_eligible'] is True and b['aggregate_eligible'] is False

    def pending(*args, **kwargs):
        result = _outcomes(*args, **kwargs)
        for row in result['trade_horizons']:
            row.update(status='pending', observed_sessions=2, gross_return_pct=None)
        return result

    monkeypatch.setattr(chart_analogue, 'observed_outcomes', pending, raising=False)
    report = service.evaluate(root=tmp_path, as_of=NOW + timedelta(days=1))
    assert report['status'] == 'collecting'
    assert report['counts']['eligible_days'] == 1
    assert report['counts']['intraday_excluded'] == 1
    assert report['counts']['pending'] == 1
    assert all(h['paired_days'] == 0 and h['pending_days'] == 1 for h in report['horizons'])


@pytest.mark.parametrize('failure', ['partial_baseline', 'missing_forecast', 'future_forecast', 'future_capture', 'nan_horizon', 'missing_basis', 'wrong_scanner'])
def test_incomplete_or_unobservable_cohorts_are_blocked_explicitly(service, tmp_path, failure):
    workflow = _workflow()
    artifact = _forecasts(workflow)
    if failure == 'partial_baseline':
        workflow['top3'] = workflow['top3'][:2]
    elif failure == 'missing_forecast':
        artifact['items'] = artifact['items'][:-1]
    elif failure == 'future_forecast':
        artifact['items'][0]['as_of'] = (NOW + timedelta(days=1)).isoformat()
    elif failure == 'future_capture':
        artifact['items'][0]['source']['captured_at'] = (NOW + timedelta(days=1)).isoformat()
    elif failure == 'nan_horizon':
        artifact['items'][0]['horizons'][1]['median_return_pct'] = float('nan')
    elif failure == 'missing_basis':
        artifact['items'][0]['source'].pop('price_basis')
    else:
        artifact['run_id'] = 'other_scanner'
    snapshot = service.record_workflow(workflow, forecasts=artifact, now=NOW, root=tmp_path)
    assert snapshot['status'] == 'blocked' and snapshot['reason']
    assert snapshot['aggregate_eligible'] is False
    report = service.read_report(root=tmp_path)
    assert report['counts']['eligible_days'] == 0 and report['counts']['blocked'] == 1
    assert report['recent'][0]['status'] == 'blocked'
    json.dumps(snapshot, allow_nan=False)
    json.dumps(report, allow_nan=False)


def test_invalid_cohort_does_not_consume_the_daily_slot(service, tmp_path):
    incomplete = _workflow('workflow_partial')
    incomplete['top3'] = incomplete['top3'][:1]
    service.record_workflow(incomplete, forecasts=_forecasts(incomplete), now=NOW, root=tmp_path)
    complete = _workflow('workflow_valid')
    valid = service.record_workflow(complete, forecasts=_forecasts(complete), now=NOW, root=tmp_path)
    assert valid['aggregate_eligible'] is True


def test_historical_freeze_is_blocked_without_backdating_recorded_time(service, tmp_path):
    workflow = _workflow(decision=NOW - timedelta(days=1))
    snapshot = service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW, root=tmp_path)
    assert snapshot['status'] == 'blocked'
    assert snapshot['reason'] == 'historical_freeze_not_allowed'
    assert snapshot['recorded_at'] == NOW.isoformat()


def test_eligibility_gates_and_median_score_symbol_ties_are_shared(service, tmp_path):
    workflow = _workflow(count=7)
    workflow['analysis_runs'][5]['verdict']['action'] = 'HOLD'
    workflow['analysis_runs'][6]['ta_excluded'] = True
    artifact = _forecasts(workflow, {1: 1, 2: 2, 3: 3, 4: 20, 5: 20, 6: 999, 7: 999})
    workflow['analysis_runs'][3]['final_score'] = 75
    workflow['analysis_runs'][4]['final_score'] = 75
    snapshot = service.record_workflow(workflow, forecasts=artifact, now=NOW, root=tmp_path)
    assert [r['symbol'] for r in snapshot['challenger']] == ['000004', '000005', '000003']
    assert set(snapshot['forecasts']) == {'000001', '000002', '000003', '000004', '000005'}


def test_complete_paired_baskets_deduct_roundtrip_costs_from_each_equal_weight_basket(service, tmp_path, monkeypatch):
    workflow = _workflow()
    service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW, root=tmp_path)
    calls = []

    def observed(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return _outcomes(symbol, **kwargs)

    monkeypatch.setattr(chart_analogue, 'observed_outcomes', observed, raising=False)
    report = service.evaluate(root=tmp_path, as_of=NOW + timedelta(days=90), index_root=tmp_path / 'index')
    assert report['status'] == 'ready'
    assert report['cost_bps'] == 23 and report['slippage_bps'] == 10
    assert [h['sessions'] for h in report['horizons']] == [5, 20, 40]
    assert all(h['paired_days'] == 1 for h in report['horizons'])
    assert report['horizons'][1]['baseline_net_return_pct'] == pytest.approx(3.67)
    assert report['horizons'][1]['challenger_net_return_pct'] == pytest.approx(7.67)
    assert report['horizons'][1]['excess_return_pct'] == pytest.approx(4)
    assert len(calls) == 5
    assert all(kw['decision_at'] == workflow['completed_at'] and kw['expected_source_id'] == 'vendor_a'
               and kw['expected_price_basis'] == 'unadjusted' and kw['reference_session'] == '2026-10-01'
               for _, kw in calls)
    assert calls[0][1]['frozen_reference_close'] == 101
    assert 'market_etf_benchmark_unavailable' in report['warnings']
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('state', ['pending', 'blocked', 'nan'])
def test_a_single_unmatured_or_invalid_leg_never_creates_a_partial_basket(service, tmp_path, monkeypatch, state):
    workflow = _workflow()
    service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW, root=tmp_path)

    def observed(symbol, **kwargs):
        result = _outcomes(symbol, **kwargs)
        if symbol == '000005':
            for row in result['trade_horizons']:
                row.update(status='matured' if state == 'nan' else state, observed_sessions=3,
                           gross_return_pct=float('nan') if state == 'nan' else None, reason=state)
        return result

    monkeypatch.setattr(chart_analogue, 'observed_outcomes', observed, raising=False)
    report = service.evaluate(root=tmp_path, as_of=NOW + timedelta(days=90))
    assert report['status'] == 'collecting'
    assert all(h['paired_days'] == 0 and h['baseline_net_return_pct'] is None
               and h['challenger_net_return_pct'] is None and h['excess_return_pct'] is None for h in report['horizons'])
    assert all(h['status'] == ('pending' if state == 'pending' else 'blocked') for h in report['recent'][0]['horizons'])


def test_new_record_updates_cached_counts_without_discarding_completed_pairs(service, tmp_path, monkeypatch):
    first = _workflow('workflow_day_one')
    service.record_workflow(first, forecasts=_forecasts(first), now=NOW, root=tmp_path)
    monkeypatch.setattr(chart_analogue, 'observed_outcomes', _outcomes, raising=False)
    service.evaluate(root=tmp_path, as_of=NOW + timedelta(days=90))
    second = _workflow('workflow_day_two', decision=NOW + timedelta(days=91))
    monkeypatch.setattr(chart_analogue, 'observed_outcomes', lambda *a, **kw: pytest.fail('Record refresh must stay cheap'))
    service.record_workflow(second, forecasts=_forecasts(second), now=NOW + timedelta(days=91, minutes=1), root=tmp_path)
    report = service.read_report(root=tmp_path)
    assert report['counts']['recorded'] == 2
    assert report['counts']['eligible_days'] == 2
    assert report['counts']['pending'] == 1
    assert report['horizons'][0]['paired_days'] == 1
    assert report['horizons'][0]['pending_days'] == 1
    assert report['horizons'][0]['baseline_net_return_pct'] == pytest.approx(3.67)


def test_cached_reader_has_exact_public_shape_and_never_queries_engine(service, tmp_path, monkeypatch):
    monkeypatch.setattr(chart_analogue, 'observed_outcomes', lambda *a, **kw: pytest.fail('Public report must be cached JSON'), raising=False)
    report = service.read_report(root=tmp_path)
    assert set(report) == {'schema_version', 'status', 'evaluated_at', 'protocol', 'ranking_effect', 'cost_bps',
                           'slippage_bps', 'counts', 'horizons', 'recent', 'warnings'}
    assert report['status'] == 'collecting' and report['evaluated_at'] is None
    assert report['ranking_effect'] == 'none' and report['protocol'] == 'chart_median20_v1'


@pytest.mark.parametrize('invalid', [None, 'not-a-time', '2026-10-02T12:00:00'])
def test_invalid_decision_times_remain_counted_but_do_not_poison_recent_contract(service, tmp_path, invalid):
    workflow = _workflow()
    workflow['completed_at'] = invalid
    snapshot = service.record_workflow(workflow, forecasts={}, now=NOW, root=tmp_path)
    assert snapshot['status'] == 'blocked'
    report = service.read_report(root=tmp_path)
    assert report['counts']['blocked'] == 1
    assert report['recent'] == []


def test_first_valid_kst_day_uses_local_day_across_utc_midnight(service, tmp_path):
    workflow = _workflow(decision=datetime(2026, 10, 1, 20, tzinfo=timezone.utc))
    snapshot = service.record_workflow(workflow, forecasts=_forecasts(workflow),
                                       now=datetime(2026, 10, 2, 1, tzinfo=timezone.utc), root=tmp_path)
    assert snapshot['aggregate_eligible'] is True
    assert snapshot['decision_day'] == '2026-10-02'


def test_malformed_observation_is_blocked_and_keeps_the_original_cohort(service, tmp_path, monkeypatch):
    workflow = _workflow()
    service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW, root=tmp_path)
    monkeypatch.setattr(chart_analogue, 'observed_outcomes', lambda *a, **kw: ['malformed'], raising=False)
    report = service.evaluate(root=tmp_path, as_of=NOW + timedelta(days=90))
    assert report['counts']['blocked'] == 1
    assert all(h['blocked_days'] == 1 and h['paired_days'] == 0 for h in report['horizons'])
    assert [r['symbol'] for r in report['recent'][0]['baseline']] == ['000001', '000002', '000003']


def test_concurrent_records_publish_one_immutable_snapshot_and_one_daily_cohort(service, tmp_path):
    workflow = _workflow()
    artifact = _forecasts(workflow)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        calls = [executor.submit(service.record_workflow, workflow, forecasts=artifact, now=NOW, root=tmp_path)
                 for _ in range(2)]
        snapshots = [call.result() for call in calls]
    assert snapshots[0] == snapshots[1]
    assert len(_json_files(tmp_path)) == 1
    assert service.read_report(root=tmp_path)['counts']['recorded'] == 1


def test_recent_rows_are_bounded_without_truncating_daily_counts(service, tmp_path):
    for n in range(12):
        workflow = _workflow(f'workflow_intraday_{n}')
        service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW + timedelta(minutes=n), root=tmp_path)
    report = service.read_report(root=tmp_path)
    assert len(report['recent']) == 10
    assert report['counts']['recorded'] == 12
    assert report['counts']['intraday_excluded'] == 11


def test_missing_artifact_publication_time_is_blocked(service, tmp_path):
    decision = datetime.now(timezone.utc) + timedelta(days=1)
    workflow = _workflow(decision=decision)
    artifact = _forecasts(workflow)
    artifact.pop('generated_at')
    snapshot = service.record_workflow(workflow, forecasts=artifact, now=decision + timedelta(minutes=1), root=tmp_path)
    assert snapshot['status'] == 'blocked'


def test_evaluation_freezes_one_index_object_despite_a_publisher_switching_vintage(service, tmp_path, monkeypatch):
    workflow = _workflow()
    service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW, root=tmp_path)
    first = ({'metadata': {'source': copy.deepcopy(EVALUATION_SOURCE)}}, None)
    second = ({'metadata': {'source': {**EVALUATION_SOURCE, 'built_at': '2027-01-02T08:00:00+00:00'}}}, None)
    load_calls = []
    observations = []

    def saved_index(full=False, index_root=None):
        load_calls.append(index_root)
        return first if len(load_calls) == 1 else second

    def observed(symbol, **kwargs):
        observations.append(kwargs.get('_loaded_index'))
        return _outcomes(symbol, **kwargs)

    monkeypatch.setattr(chart_analogue, '_load', saved_index)
    monkeypatch.setattr(chart_analogue, 'observed_outcomes', observed)
    report = service.evaluate(root=tmp_path, as_of=NOW + timedelta(days=90))
    assert report['status'] == 'ready'
    assert len(load_calls) == 1
    assert all(index is first for index in observations)


def test_mixed_vintage_observation_payload_blocks_the_entire_pair(service, tmp_path, monkeypatch):
    workflow = _workflow()
    service.record_workflow(workflow, forecasts=_forecasts(workflow), now=NOW, root=tmp_path)

    def observed(symbol, **kwargs):
        result = _outcomes(symbol, **kwargs)
        if symbol == '000005':
            result['source']['built_at'] = '2027-01-02T08:00:00+00:00'
        return result

    monkeypatch.setattr(chart_analogue, 'observed_outcomes', observed)
    report = service.evaluate(root=tmp_path, as_of=NOW + timedelta(days=90))
    assert report['counts']['blocked'] == 1
    assert all(h['paired_days'] == 0 and h['blocked_days'] == 1
               and h['baseline_net_return_pct'] is None and h['challenger_net_return_pct'] is None
               for h in report['horizons'])
