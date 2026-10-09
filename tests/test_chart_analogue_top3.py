"""Whole-index TOP3 selection must be replayable, bounded and risk-aware."""
import copy
import importlib
import json
import threading
from pathlib import Path

import numpy as np
import pytest
from filelock import FileLock

from app.services.mirofish import chart_analogue as engine


AS_OF = '2026-10-02T01:00:00Z'
SOURCE = {'name': 'fixture closed prices', 'source_id': 'fixture_closed',
          'price_basis': 'provider_adjusted', 'latest_session': '2026-10-01',
          'built_at': '2026-10-01T12:00:00Z', 'captured_at': '2026-10-01T08:00:00Z',
          'rows': 10000, 'symbols': 5}


def service():
    return importlib.import_module('app.services.mirofish.chart_analogue_top3')


def prediction(symbol, median=8, low=-6, frequency=70):
    return {'symbol': symbol, 'target': 'Stock ' + symbol, 'status': 'ready',
            'mode': 'shadow', 'as_of': AS_OF, 'sample_count': 20,
            'source': {**SOURCE, 'query_collection_status': 'fresh',
                       'query_captured_at': '2026-10-01T08:00:00Z'},
            'history': [{'date': '2026-10-01', 'close': 1000}],
            'horizons': [{'sessions': 20, 'median_return_pct': median,
                          'p10_return_pct': low, 'p90_return_pct': max(median, 20),
                          'up_frequency_pct': frequency}],
            'neighbors': [{'symbol': f'{i + 20:06d}', 'similarity': .9,
                           'end_date': '2025-01-01', 'outcome_end_date': '2025-03-01',
                           'captured_at': '2025-03-01T08:00:00Z'} for i in range(20)]}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    svc = service()
    data = {'metadata': {'source': copy.deepcopy(SOURCE)},
            'symbols': np.array([f'{i + 1:06d}' for i in range(5)])}
    state = {'data': data, 'loads': [], 'calls': [], 'rows': {s: prediction(s) for s in data['symbols']},
             'now': AS_OF}
    original_cutoff = engine._cutoff
    monkeypatch.setattr(engine, '_cutoff',
        lambda value=None: original_cutoff(state['now'] if value is None else value))
    def load(**kwargs):
        state['loads'].append(kwargs)
        return (data if kwargs.get('full') else data['metadata']), None
    def predict(symbol, **kwargs):
        state['calls'].append((symbol, kwargs))
        return copy.deepcopy(state['rows'][symbol])
    monkeypatch.setattr(engine, '_load', load)
    monkeypatch.setattr(engine, 'predict', predict)
    state.update(svc=svc, root=tmp_path / 'results')
    return state


def test_risk_adjusted_three_are_sorted_deterministically_and_use_one_vintage(harness):
    h = harness
    h['rows']['000001'] = prediction('000001', median=40, low=-25)  # reject tail risk
    h['rows']['000002'] = prediction('000002', median=9, low=-10)  # score 3.67
    h['rows']['000003'] = prediction('000003', median=8, low=-2)   # score 6.67
    h['rows']['000004'] = prediction('000004', median=8, low=-2)   # tie: code
    result = h['svc'].scan(as_of=AS_OF)
    assert result['status'] == 'ready'
    assert [r['symbol'] for r in result['candidates']] == ['000003', '000004', '000005']
    assert result['candidates'][0]['score'] == pytest.approx(6.67)
    assert result['criteria']['cost_bps'] == 33
    assert result['universe'] == {'indexed': 5, 'processed': 5, 'eligible': 4,
                                  'rejected': {'tail_risk': 1}}
    assert len(h['loads']) == 1 and h['loads'][0]['full'] is True
    assert len(h['calls']) == 5
    assert all(kw['_loaded_index'][0] is h['data'] and kw['as_of'] == AS_OF
               and kw['horizons'] == (20,) for _, kw in h['calls'])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('change,reason', [
    ({'sample_count': 19}, 'too_few_samples'),
    ({'source': {**SOURCE, 'query_collection_status': 'cache_preserved', 'query_captured_at': '2026-10-01T08:00:00Z'}}, 'cached_target'),
    ({'source': {**SOURCE, 'latest_session': '2026-09-30', 'query_captured_at': '2026-10-01T08:00:00Z'}}, 'old_target_session'),
    ({'source': {**SOURCE, 'query_captured_at': '2027-01-01T08:00:00Z'}}, 'future_capture'),
    ({'status': 'insufficient_history'}, 'insufficient_history'),
    ({'neighbors': [{'symbol': '000099', 'similarity': .9}] * 20}, 'insufficient_diversity'),
])
def test_bad_evidence_is_excluded_without_padding(harness, change, reason):
    h = harness
    for symbol in ['000001', '000002', '000003', '000004']:
        h['rows'][symbol].update(copy.deepcopy(change))
    result = h['svc'].scan(as_of=AS_OF)
    assert result['status'] == 'insufficient_candidates'
    assert [r['symbol'] for r in result['candidates']] == ['000005']
    assert result['universe']['rejected'][reason] == 4


@pytest.mark.parametrize('field,value,reason', [
    ('median_return_pct', float('nan'), 'invalid_statistics'),
    ('up_frequency_pct', 59.9, 'low_up_frequency'),
    ('median_return_pct', -1, 'nonpositive_score'),
    ('median_return_pct', 3.3300001, 'nonpositive_score'),
    ('p10_return_pct', -12.1, 'tail_risk'),
])
def test_statistical_quality_gates(harness, field, value, reason):
    h = harness
    h['rows']['000001']['horizons'][0][field] = value
    result = h['svc'].scan(as_of=AS_OF)
    assert result['universe']['rejected'][reason] == 1
    assert '000001' not in [r['symbol'] for r in result['candidates']]


def test_missing_stale_and_raw_index_never_produce_picks(harness, monkeypatch):
    h = harness
    h['data']['metadata']['source']['latest_session'] = '2026-09-01'
    assert h['svc'].scan(as_of=AS_OF)['status'] == 'stale_data'
    assert not h['calls']
    h['data']['metadata']['source'].update(SOURCE, price_basis='unadjusted')
    assert h['svc'].scan(as_of=AS_OF)['status'] == 'invalid_index'
    monkeypatch.setattr(engine, '_load', lambda **kw: (None, 'missing_index'))
    assert h['svc'].scan(as_of=AS_OF)['candidates'] == []


def test_status_reads_are_cheap_and_result_becomes_outdated_on_index_change(harness, monkeypatch):
    h = harness
    h['svc'].run_scan(root=h['root'], as_of=AS_OF)
    monkeypatch.setattr(engine, 'predict', lambda *a, **kw: pytest.fail('GET must never predict'))
    h['loads'].clear()
    status = h['svc'].read_status(root=h['root'])
    assert status['state'] == 'done' and status['freshness'] == 'current'
    assert all(not row['full'] for row in h['loads'])
    h['data']['metadata']['source']['built_at'] = '2026-10-02T12:00:00Z'
    assert h['svc'].read_status(root=h['root'])['freshness'] == 'outdated'


def test_saved_cache_expires_after_source_freshness_window(harness, monkeypatch):
    h = harness
    h['svc'].run_scan(root=h['root'], as_of=AS_OF)
    monkeypatch.setattr(engine, 'predict', lambda *a, **kw: pytest.fail('GET must never predict'))
    h['now'] = '2026-10-08T01:00:00Z'  # Latest Oct 1 session is still within seven days.
    assert h['svc'].read_status(root=h['root'])['freshness'] == 'current'
    h['now'] = '2026-10-09T01:00:00Z'
    assert h['svc'].read_status(root=h['root'])['freshness'] == 'outdated'


def test_no_artifact_get_does_not_create_directories(tmp_path):
    root = tmp_path / 'not-created'
    assert service().read_status(root=root)['state'] == 'none'
    assert not root.exists()


def test_persisted_progress_after_worker_restart_is_not_permanently_running(harness):
    h = harness
    h['root'].mkdir()
    (h['root'] / 'job.json').write_text(json.dumps({'state': 'running', 'processed': 2,
        'total': 5, 'started_at': AS_OF, 'error': None}))
    state = h['svc'].read_status(root=h['root'])
    assert state['state'] == 'error' and state['error'] == 'scan_interrupted'


def test_worker_finishing_during_get_is_not_misreported_as_interrupted(harness, monkeypatch):
    h = harness
    h['root'].mkdir()
    job_path = h['root'] / 'job.json'
    job = {'state': 'running', 'processed': 2, 'total': 5, 'started_at': AS_OF, 'error': None}
    job_path.write_text(json.dumps(job))
    report = h['svc'].scan(as_of=AS_OF)
    report.pop('_audit')
    def finish_before_lock_observation(root):
        (root / 'report.json').write_text(json.dumps(report))
        job_path.write_text(json.dumps({**job, 'state': 'done', 'processed': 5}))
        return False
    monkeypatch.setattr(h['svc'], '_active', finish_before_lock_observation)
    state = h['svc'].read_status(root=h['root'])
    assert state['state'] == 'done' and state['error'] is None
    assert state['freshness'] == 'current' and len(state['report']['candidates']) == 3


def test_api_and_nightly_duplicate_scan_join_same_file_lock(harness):
    h = harness
    h['root'].mkdir()
    lock = FileLock(str(h['root'] / 'scan.lock'))
    with lock:
        state = h['svc'].start_scan(root=h['root'])
        assert state['state'] == 'running'
        assert not h['calls']


def test_completed_cache_is_rechecked_after_lock_acquisition(harness, monkeypatch):
    h = harness
    h['svc'].run_scan(root=h['root'], as_of=AS_OF)
    report = json.loads((h['root'] / 'report.json').read_text())
    job = json.loads((h['root'] / 'job.json').read_text())
    (h['root'] / 'report.json').unlink()
    (h['root'] / 'job.json').unlink()
    original_lock = h['svc']._lock
    class CompletingLock:
        def __init__(self, root):
            self.lock = original_lock(root)
        def acquire(self, **kwargs):
            token = self.lock.acquire(**kwargs)
            # Another completed worker published just before this acquisition.
            (h['root'] / 'report.json').write_text(json.dumps(report))
            (h['root'] / 'job.json').write_text(json.dumps(job))
            return token
        def release(self):
            self.lock.release()
    starts = []
    class Thread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            starts.append(True)
    monkeypatch.setattr(h['svc'], '_active', lambda root: False)
    monkeypatch.setattr(h['svc'], '_lock', CompletingLock)
    monkeypatch.setattr(h['svc'].threading, 'Thread', Thread)
    result = h['svc'].start_scan(root=h['root'])
    assert result['state'] == 'done' and result['freshness'] == 'current'
    assert starts == []


def test_nightly_waits_for_active_scan_and_reuses_its_current_result(harness, monkeypatch):
    h = harness
    h['svc'].run_scan(root=h['root'], as_of=AS_OF)
    report = json.loads((h['root'] / 'report.json').read_text())
    job = json.loads((h['root'] / 'job.json').read_text())
    (h['root'] / 'report.json').unlink()
    (h['root'] / 'job.json').unlink()
    original_lock = h['svc']._lock
    class CompletingLock:
        def __init__(self, root):
            self.lock = original_lock(root)
        def acquire(self, *, timeout):
            assert timeout > 0  # Offline scheduler must wait, not exit before completion.
            token = self.lock.acquire(timeout=timeout)
            (h['root'] / 'report.json').write_text(json.dumps(report))
            (h['root'] / 'job.json').write_text(json.dumps(job))
            return token
        def release(self):
            self.lock.release()
    monkeypatch.setattr(h['svc'], '_lock', CompletingLock)
    monkeypatch.setattr(engine, 'predict', lambda *a, **kw: pytest.fail('Same source must be reused'))
    assert h['svc'].run_scan(root=h['root'])['run_id'] == report['run_id']


def test_explicit_offline_cutoff_does_not_reuse_another_decision(harness):
    h = harness
    previous = h['svc'].run_scan(root=h['root'], as_of=AS_OF)
    h['calls'].clear()
    replay = h['svc'].run_scan(root=h['root'], as_of=AS_OF)
    assert replay['run_id'] != previous['run_id'] and len(h['calls']) == 5


def test_background_scan_failure_is_safe_and_can_retry(harness, monkeypatch):
    h = harness
    event = threading.Event()
    def fail(*args, **kwargs):
        event.set()
        raise RuntimeError('private filesystem path or provider secret')
    monkeypatch.setattr(h['svc'], 'scan', fail)
    assert h['svc'].start_scan(root=h['root'])['state'] in {'running', 'error'}
    assert event.wait(2)
    for _ in range(100):
        state = h['svc'].read_status(root=h['root'])
        if state['state'] == 'error':
            break
        threading.Event().wait(.01)
    assert state['error'] == 'scan_failed'
    assert 'private' not in json.dumps(state)


def test_pinned_predict_survives_index_replacement(tmp_path, monkeypatch):
    from tests.test_chart_analogue import install, cutoff
    module, _, days, _ = install(tmp_path, monkeypatch)
    loaded = module._load(full=True)
    baseline = module.predict('000001', as_of=cutoff(days[-1]))
    monkeypatch.setattr(module, '_load', lambda **kw: (None, 'missing_index'))
    assert module.predict('000001', as_of=cutoff(days[-1]), _loaded_index=loaded) == baseline


def test_real_engine_whole_universe_records_actual_knowable_evidence(tmp_path, monkeypatch):
    from tests.test_chart_analogue import install, cutoff
    module, csv_path, days, _ = install(tmp_path, monkeypatch, symbols=16)
    module.build_index(csv_path, tmp_path / 'index', price_basis='provider_adjusted')
    result = service().scan(as_of=cutoff(days[-1]), index_root=tmp_path / 'index')
    assert result['status'] == 'ready'
    assert result['universe']['processed'] == result['universe']['indexed'] == 16
    assert [r['symbol'] for r in result['candidates']] == ['000001', '000002', '000003']
    for row in result['candidates']:
        assert row['horizon']['median_return_pct'] == pytest.approx(2.019114)
        assert row['score'] == pytest.approx(1.689114)
        assert row['horizon']['up_frequency_pct'] == 100
    for prediction in result['_audit']['selected_forecasts']:
        assert prediction['as_of'] == result['as_of']
        assert all(n['outcome_end_date'] <= days[-1].isoformat() for n in prediction['neighbors'])
        assert all(engine._cutoff(n['captured_at']) <= engine._cutoff(result['as_of']) for n in prediction['neighbors'])
    service().run_scan(as_of=cutoff(days[-1]), index_root=tmp_path / 'index', root=tmp_path / 'saved')
    saved = service().read_status(index_root=tmp_path / 'index', root=tmp_path / 'saved')
    assert saved['state'] == 'done' and len(saved['report']['candidates']) == 3


def test_weak_patterns_and_partial_scans_do_not_return_three(harness, monkeypatch):
    h = harness
    for row in h['rows'].values():
        for neighbor in row['neighbors']:
            neighbor['similarity'] = .79
    result = h['svc'].scan(as_of=AS_OF)
    assert result['candidates'] == []
    assert result['universe']['rejected'] == {'weak_similarity': 5}
    times = iter([0, 0, 3000])
    monkeypatch.setattr(h['svc'].time, 'monotonic', lambda: next(times))
    result = h['svc'].scan(as_of=AS_OF)
    assert result['status'] == 'failed' and result['candidates'] == []
    assert result['universe']['processed'] == 1 < result['universe']['indexed']
