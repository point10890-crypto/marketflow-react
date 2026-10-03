"""Recoverable offline publication, immutable decisions and cheap reads."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.mirofish import chart_analogue_kelly_store as store


SOURCE = {'source_id': 'fixture_prices', 'price_basis': 'provider_adjusted',
          'latest_session': '2026-10-01', 'captured_at': '2026-10-01T08:00:00Z',
          'built_at': '2026-10-01T09:00:00Z', 'rows': 10000, 'symbols': 2}
UNIVERSE = {'as_of': '2026-10-01', 'ranking': {'ranked': []}, 'quality': {'passed': []}}
CUTOFF = '2026-10-03T01:00:00Z'


def report(symbol='005930', cutoff=CUTOFF):
    return {'schema_version': 1, 'policy_id': 'chart-analogue-kelly-v1', 'mode': 'research',
            'status': 'ready', 'as_of': cutoff, 'generated_at': cutoff, 'source': SOURCE,
            'universe': {'processed': 2, 'quality_passed': 2},
            'candidates': [{'symbol': symbol, 'target': 'fixture', 'reference_session': '2026-10-01',
                            'current_close': 100., 'kelly': {'approved_weight': None}}],
            'approval': {'status': 'held', 'approved_exposure': 0},
            '_audit': {'raw_returns': [.1, -.1]}}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(store, '_now', lambda: CUTOFF)
    calls = []
    def scan(universe, **kwargs):
        calls.append(deepcopy(universe))
        if kwargs.get('progress'):
            kwargs['progress'](2, 2)
        return report(cutoff=kwargs.get('as_of') or CUTOFF)
    monkeypatch.setattr(store, '_engine', lambda: SimpleNamespace(scan=scan))
    monkeypatch.setattr(store.chart, '_load', lambda **kwargs: ({'source': SOURCE}, None))
    monkeypatch.setattr(store.chart, '_freshness', lambda source, cutoff: 2)
    monkeypatch.setattr(store.chart, 'observed_outcomes', lambda *a, **kw: {
        'trade_horizons': [{'sessions': 20, 'status': 'pending', 'gross_return_pct': None}]})
    return calls


def write_universe(tmp_path, value=None):
    path = tmp_path / 'input.json'
    store._write(path, value or UNIVERSE)
    return path


def test_get_is_cheap_and_never_starts_scan(tmp_path, provider):
    state = store.read_status(root=tmp_path / 'saved')
    assert state['state'] == 'none'
    assert state['report'] is None
    assert provider == []


def test_blocked_empty_source_report_remains_visible(tmp_path, provider, monkeypatch):
    blocked = {**report(), 'status': 'blocked', 'source': {}, 'candidates': []}
    monkeypatch.setattr(store, '_engine', lambda: SimpleNamespace(scan=lambda *a, **kw: blocked))
    root = tmp_path / 'saved'
    store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of=CUTOFF)
    state = store.read_status(root=root)
    assert state['state'] == 'done'
    assert state['report']['status'] == 'blocked'
    assert state['freshness'] == 'stale'


def test_completed_input_is_reused_and_audit_is_not_public(tmp_path, provider):
    scope = write_universe(tmp_path)
    root = tmp_path / 'saved'
    first = store.run_scan(root=root, universe_path=scope, as_of=CUTOFF)
    second = store.run_scan(root=root, as_of=CUTOFF)
    assert first == second
    assert len(provider) == 1
    assert '_audit' not in first
    assert store._read(root / 'runs' / (first['run_id'] + '.json'))['audit']
    assert store.read_status(root=root)['state'] == 'done'
    assert store.read_status(root=root)['freshness'] == 'current'


def test_changed_scope_does_not_reuse_old_result(tmp_path, provider):
    scope = write_universe(tmp_path)
    root = tmp_path / 'saved'
    store.run_scan(root=root, universe_path=scope, as_of=CUTOFF)
    store._write(scope, {**UNIVERSE, 'as_of': '2026-10-02'})
    store.run_scan(root=root, universe_path=scope, as_of=CUTOFF)
    assert len(provider) == 2


def test_expired_universe_is_stale_even_if_price_vintage_is_fresh(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of=CUTOFF)
    monkeypatch.setattr(store, '_now', lambda: '2026-10-09T01:00:00Z')
    assert store.read_status(root=root)['freshness'] == 'stale'


def test_historical_scan_is_not_backdated_into_forward_journal(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    monkeypatch.setattr(store, '_now', lambda: '2026-10-04T01:00:00Z')
    saved = store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of=CUTOFF)
    assert saved['forward']['decision_days'] == 0
    assert saved['forward']['pending_trades'] == 0
    assert not (root / 'decisions.json').exists()


def test_changed_index_vintage_is_marked_stale(tmp_path, provider, monkeypatch):
    store.run_scan(root=tmp_path / 'saved', universe_path=write_universe(tmp_path), as_of=CUTOFF)
    monkeypatch.setattr(store.chart, '_load', lambda **kw: ({'source': {**SOURCE, 'built_at': '2026-10-02T09:00:00Z'}}, None))
    assert store.read_status(root=tmp_path / 'saved')['freshness'] == 'stale'


def test_interrupted_job_is_retryable_and_error_is_generic(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    store._write(root / 'job.json', {'state': 'running', 'processed': 1, 'total': 2, 'started_at': CUTOFF, 'error': None})
    assert store.read_status(root=root)['error'] == 'scan_interrupted'
    def fail(*args, **kwargs):
        raise ValueError('secret provider path')
    monkeypatch.setattr(store, '_engine', lambda: SimpleNamespace(scan=fail))
    with pytest.raises(ValueError):
        store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of=CUTOFF)
    state = store.read_status(root=root)
    assert state['state'] == 'error'
    assert state['error'] == 'scan_failed'
    assert 'secret' not in str(state)


def test_first_daily_decision_is_immutable_and_pending_is_not_zero_loss(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    scope = write_universe(tmp_path)
    store.run_scan(root=root, universe_path=scope, as_of=CUTOFF)
    frozen = deepcopy(store._read(root / 'decisions.json')['items'][0])
    monkeypatch.setattr(store, '_engine', lambda: SimpleNamespace(scan=lambda *a, **kw: report('000660', '2026-10-03T02:00:00Z')))
    monkeypatch.setattr(store, '_now', lambda: '2026-10-03T03:00:00Z')
    monkeypatch.setattr(store.chart, 'observed_outcomes', lambda *a, **kw: {'trade_horizons': [{'sessions': 20, 'status': 'pending', 'gross_return_pct': None}]})
    latest = store.run_scan(root=root, as_of='2026-10-03T02:00:00Z')
    assert store._read(root / 'decisions.json')['items'][0] == frozen
    assert latest['forward']['decision_days'] == 1
    assert latest['forward']['pending_trades'] == 1
    assert latest['forward']['matured_trades'] == 0
    assert latest['forward']['net_win_rate_pct'] is None
    assert latest['approval']['status'] == 'held'


def test_matured_forward_trade_uses_cost_and_next_close_contract(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of=CUTOFF)
    kwargs_seen = []
    def outcomes(symbol, **kwargs):
        kwargs_seen.append(kwargs)
        if kwargs['decision_at'].startswith('2026-11'):
            return {'trade_horizons': [{'sessions': 20, 'status': 'pending', 'gross_return_pct': None}]}
        return {'trade_horizons': [{'sessions': 20, 'status': 'matured', 'gross_return_pct': 1., 'entry_date': '2026-10-05', 'exit_date': '2026-11-02'}]}
    monkeypatch.setattr(store.chart, 'observed_outcomes', outcomes)
    monkeypatch.setattr(store, '_now', lambda: '2026-11-03T01:00:00Z')
    result = store.run_scan(root=root, as_of='2026-11-03T01:00:00Z')
    assert result['forward']['expectancy_pct'] == pytest.approx(.67)
    assert result['forward']['matured_trades'] == 1
    assert result['forward']['independent'] is False
    assert kwargs_seen[0]['horizons'] == (20,)
    assert kwargs_seen[0]['expected_source_id'] == SOURCE['source_id']


def test_nonfinite_and_oversized_json_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        store._write(tmp_path / 'bad.json', {'x': float('nan')})
    path = tmp_path / 'huge.json'
    path.write_text(' ' * (store.MAX_JSON_BYTES + 1))
    with pytest.raises(ValueError):
        store._read(path)


def test_future_decision_cannot_publish_or_freeze(tmp_path, provider):
    root = tmp_path / 'saved'
    with pytest.raises(ValueError, match='future_decision_cutoff'):
        store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of='2026-11-05T01:00:00Z')
    assert provider == []
    assert not (root / 'decisions.json').exists()


def test_scanner_cannot_substitute_a_different_cutoff(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    monkeypatch.setattr(store, '_engine', lambda: SimpleNamespace(scan=lambda *a, **kw: report(cutoff='2026-10-03T02:00:00Z')))
    with pytest.raises(ValueError, match='scan_cutoff_mismatch'):
        store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of=CUTOFF)
    assert not (root / 'decisions.json').exists()


def test_daily_freeze_recovers_after_latest_report_publication_failure(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    real_write = store._write
    def fail_publish(path, value):
        if path.name == 'report.json':
            raise OSError('disk publication failed')
        real_write(path, value)
    monkeypatch.setattr(store, '_write', fail_publish)
    with pytest.raises(OSError):
        store.run_scan(root=root, universe_path=write_universe(tmp_path), as_of=CUTOFF)
    first = store._read(root / 'decisions.json')['items'][0]
    monkeypatch.setattr(store, '_write', real_write)
    store.run_scan(root=root, as_of=CUTOFF)
    assert store._read(root / 'decisions.json')['items'] == [first]


def test_one_background_worker_and_saved_result_reuse(tmp_path, provider, monkeypatch):
    root = tmp_path / 'saved'
    store._write(root / 'universe.json', UNIVERSE)
    captured = []
    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            captured.append(self.target)
    monkeypatch.setattr(store.threading, 'Thread', Thread)
    assert store.start_scan(root=root)['state'] == 'running'
    assert store.start_scan(root=root)['state'] == 'running'
    assert len(captured) == 1
    captured[0]()
    assert store.start_scan(root=root)['state'] == 'done'
    assert len(provider) == 1
