"""The prospective sidecar cannot change successful production research."""
from copy import deepcopy

from app.services.mirofish.alpha_lab import service, store, monitor, evolution_store
from tests.test_alpha_lab_service import _context_scan


def test_evolution_receives_full_pool_after_original_publication(tmp_path, monkeypatch):
    inputs, discovery = _context_scan(tmp_path, monkeypatch)
    discovery['candidates'] *= 5
    calls = []
    published = store.publish

    def publish(*args, **kwargs):
        calls.append('publish')
        return published(*args, **kwargs)

    def refresh(root, data, report, full_pool):
        calls.append('evolution')
        assert root == tmp_path and data == inputs
        assert len(full_pool['candidates']) == 5
        assert len(report['buy_candidates']) == 3
        assert 'evolution' not in report
        return {'status': 'ready'}

    monkeypatch.setattr(store, 'publish', publish)
    monkeypatch.setattr(evolution_store, 'refresh', refresh)
    result = service.scan_once(tmp_path)
    assert result['state'] != 'failed'
    assert calls == ['publish', 'evolution']
    assert 'evolution' not in result['report']


def test_failed_optional_evolution_preserves_published_decision(tmp_path, monkeypatch, caplog):
    _context_scan(tmp_path, monkeypatch)
    registered = []
    monkeypatch.setattr(monitor, 'register_report', lambda *a, **k: registered.append(True))

    def fail(*args, **kwargs):
        raise ValueError('private key must not be exposed')

    monkeypatch.setattr(evolution_store, 'refresh', fail)
    result = service.scan_once(tmp_path)
    assert result['state'] != 'failed' and registered == [True]
    assert store.read_status(tmp_path)['report'] == result['report']
    assert 'private key' not in caplog.text
    assert 'evolution unavailable' in caplog.text


def test_evolution_get_reads_bound_saved_projection_without_writes(tmp_path, monkeypatch):
    _context_scan(tmp_path, monkeypatch)
    monkeypatch.setattr(evolution_store, 'refresh', lambda *a, **k: {'status': 'ready'})
    fixed = service.scan_once(tmp_path)['report']
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    snapshot = {'test_saved_projection': True}
    reads = []

    def read(root, board, **kwargs):
        assert root == tmp_path
        reads.append(deepcopy(board))
        return snapshot

    monkeypatch.setattr(evolution_store, 'read_status', read)
    monkeypatch.setattr(evolution_store, 'refresh', lambda *a, **k: (_ for _ in ()).throw(AssertionError('GET refreshed')))
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
    result = service.read_status(now='2026-10-04T03:00:00Z')
    assert result['evolution'] == snapshot
    assert reads == [result['opportunity_engine']]
    assert result['report'] == fixed
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}


def test_returned_evolution_hold_is_visible_in_logs_without_failure(tmp_path, monkeypatch, caplog):
    _context_scan(tmp_path, monkeypatch)
    monkeypatch.setattr(evolution_store, 'refresh', lambda *a, **k: {'status': 'held', 'error': 'private key'})
    assert service.scan_once(tmp_path)['state'] != 'failed'
    assert 'refresh_held' in caplog.text and 'private key' not in caplog.text
