"""News context is a separate saved projection, never a ranking/approval input."""
from copy import deepcopy

from app.services.mirofish.alpha_lab import service, store, monitor, catalyst_store
from tests.test_alpha_lab_service import _context_scan


def hooks(monkeypatch, calls, *, fail=False):

    def refresh(root, **kwargs):
        calls.append(('refresh', root))
        if fail:
            raise ValueError('private key must not be logged')
        return {'status': 'ready'}

    monkeypatch.setattr(catalyst_store, 'refresh_context', refresh)
    monkeypatch.setattr(catalyst_store, 'read_context', lambda *args, **kwargs: None)
    def enroll(root, board, symbols, **kwargs):
        calls.append(('cohort', root, deepcopy(board), deepcopy(symbols)))
        return {'status': 'enrolled'}
    monkeypatch.setattr(catalyst_store, 'register_cohort', enroll)
    return catalyst_store


def test_research_hooks_run_after_publish_without_changing_fixed_decision(tmp_path, monkeypatch):
    data, _ = _context_scan(tmp_path, monkeypatch)
    calls = []
    hooks(monkeypatch, calls)
    published = store.publish

    def publish(*args, **kwargs):
        calls.append(('publish',))
        return published(*args, **kwargs)

    monkeypatch.setattr(store, 'publish', publish)
    result = service.scan_once(tmp_path)
    assert [row[0] for row in calls] == ['publish', 'cohort', 'refresh']
    assert calls[1][2] == result['report']['opportunity_board']
    assert calls[1][3] == data['names']
    assert 'catalyst_context' not in result['report']
    assert all('catalyst_context' not in row for row in result['report']['buy_candidates'])


def test_context_failure_does_not_undo_research_or_monitor_registration(tmp_path, monkeypatch, caplog):
    _context_scan(tmp_path, monkeypatch)
    calls = []
    hooks(monkeypatch, calls, fail=True)
    registration = []
    monkeypatch.setattr(monitor, 'register_report', lambda *args, **kwargs: registration.append(1))
    result = service.scan_once(tmp_path)
    assert result['state'] != 'failed'
    assert registration == [1]
    assert calls[-1][0] == 'refresh'
    assert 'private key' not in caplog.text


def test_get_attaches_saved_context_without_acquisition_or_mutation(tmp_path, monkeypatch):
    _context_scan(tmp_path, monkeypatch)
    calls = []
    context = hooks(monkeypatch, calls)
    service.scan_once(tmp_path)
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    fixed = store.read_status(tmp_path)['report']
    snapshot = {'test_saved_projection': True}
    reads = []

    def read(root, board, **kwargs):
        reads.append(deepcopy(board))
        return snapshot

    monkeypatch.setattr(context, 'read_context', read)
    calls.clear()
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
    status = service.read_status(now='2026-10-04T03:00:00Z')
    assert status['catalyst_context'] == snapshot
    assert reads == [status['opportunity_engine']]
    assert calls == []
    assert status['report'] == fixed
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}


def test_returned_context_failures_are_visible_without_undoing_research(tmp_path, monkeypatch, caplog):
    _context_scan(tmp_path, monkeypatch)
    monkeypatch.setattr(catalyst_store, 'register_cohort', lambda *a, **k: dict(status='failed', error='private credential'))
    monkeypatch.setattr(catalyst_store, 'refresh_context', lambda *a, **k: dict(status='failed', error='private credential'))
    result = service.scan_once(tmp_path)
    assert result['state'] != 'failed'
    assert 'cohort_failed' in caplog.text and 'refresh_failed' in caplog.text
    assert 'private credential' not in caplog.text


def test_real_saved_context_is_projected_through_service_get(tmp_path, monkeypatch):
    from tests.test_alpha_lab_catalyst_store import make_db
    _context_scan(tmp_path, monkeypatch)
    # Missing ledger is an optional-stage failure, not a failed research report.
    monkeypatch.setattr(catalyst_store, 'DEFAULT_DB_PATH', tmp_path/'absent.db')
    report = service.scan_once(tmp_path)['report']
    assert report.get('opportunity_board')
    db = make_db(tmp_path/'omni.db')
    result = catalyst_store.refresh_context(tmp_path, db_path=db)
    assert result['status'] == 'ready'
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    original = {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
    state = service.read_status()
    assert state['catalyst_context']['snapshot_id'] == result['snapshot_id']
    assert state['catalyst_context']['decision_id'] == state['opportunity_engine']['decision_id']
    assert state['catalyst_context']['used_in_selection'] is False
    assert state['report'] == report
    assert original == {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
