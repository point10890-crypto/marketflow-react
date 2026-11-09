"""CLI owns candidate attempt lifecycle across the preceding legacy scan."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from filelock import FileLock, Timeout
import pytest

from scripts import run_alpha_lab as cli
from app.services.mirofish.alpha_lab import candidate_service as service, candidate_store
from tests.test_alpha_lab_candidate_store import data, desk


def setup_cli(tmp_path, monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **k: False)
    directory = tmp_path/'candidate-desk'
    first = candidate_store.publish(directory, desk(), data(), now='2026-10-22T00:02:00Z')
    candidate_store.set_attempt(directory, 'complete', now='2026-10-22T00:02:00Z')
    old = tmp_path/'detection-v2'/'terminal.json'
    old.parent.mkdir(); old.write_text('sealed original')
    immutable = {p:p.read_bytes() for p in tmp_path.rglob('*.json') if p.name != 'attempt.json'}
    monkeypatch.setattr(service, 'refresh_desk', lambda *a, **k: pytest.fail('failed legacy reached candidate source'))
    return directory, first, immutable


@pytest.mark.parametrize('raises', [False, True])
def test_legacy_failure_downgrades_attempt_before_unlock_without_mutating_first(tmp_path, monkeypatch, capsys, raises):
    directory, first, immutable = setup_cli(tmp_path, monkeypatch)

    def fail(*a, **k):
        if raises:
            raise RuntimeError('private credential and internal path')
        return dict(state='failed', error='scan_unavailable', report=None)

    monkeypatch.setattr(service.legacy, 'scan_once', fail)
    assert cli.main(['--root', str(tmp_path)]) == 1
    attempt = candidate_store._load(directory/'attempt.json')
    assert attempt['state'] == 'failed'
    assert attempt['error'] == 'analysis_unavailable'
    view = candidate_store.read_public(directory, now='2026-10-22T00:05:00Z')
    assert view['decision_id'] == first['decision_id']
    assert view['state'] == 'failed'
    assert all(path.read_bytes() == value for path, value in immutable.items())
    assert 'private' not in capsys.readouterr().out
    with FileLock(str(tmp_path/'candidate-compose.lock')).acquire(timeout=0):
        pass


def test_cli_marks_running_and_owns_compose_lock_during_legacy_scan(tmp_path, monkeypatch):
    directory, _, _ = setup_cli(tmp_path, monkeypatch)

    def scan(*a, **k):
        assert candidate_store._load(directory/'attempt.json')['state'] == 'running'
        with pytest.raises(Timeout):
            FileLock(str(tmp_path/'candidate-compose.lock')).acquire(timeout=0)
        return dict(state='failed', error='scan_unavailable', report=None)

    monkeypatch.setattr(service.legacy, 'scan_once', scan)
    assert cli.main(['--root', str(tmp_path)]) == 1


@pytest.mark.parametrize('active_state', ['complete', 'running'])
def test_busy_composition_preserves_attempt_and_all_saved_files(tmp_path, monkeypatch, active_state):
    directory, _, _ = setup_cli(tmp_path, monkeypatch)
    candidate_store.set_attempt(directory, active_state)
    before = {p:p.read_bytes() for p in tmp_path.rglob('*.json')}
    monkeypatch.setattr(service.store, 'read_status', lambda *a: dict(state='held', error=None, report=None))
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: pytest.fail('busy CLI scanned'))
    with FileLock(str(tmp_path/'candidate-compose.lock')).acquire(timeout=0):
        assert cli.main(['--root', str(tmp_path)]) == 2
    assert {p:p.read_bytes() for p in tmp_path.rglob('*.json')} == before
    assert candidate_store._load(directory/'attempt.json')['state'] == active_state


@pytest.mark.parametrize('new_state', ['running', 'complete'])
def test_failure_does_not_clobber_a_newer_attempt(tmp_path, monkeypatch, new_state):
    directory, _, _ = setup_cli(tmp_path, monkeypatch)
    newer = (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat().replace('+00:00','Z')

    def scan(*a, **k):
        candidate_store.set_attempt(directory, new_state, now=newer)
        return dict(state='failed', error='scan_unavailable', report=None)

    monkeypatch.setattr(service.legacy, 'scan_once', scan)
    assert cli.main(['--root', str(tmp_path)]) == 1
    assert candidate_store._load(directory/'attempt.json') == dict(state=new_state, at=newer, error=None)


def test_legacy_running_does_not_leave_this_finished_cli_attempt_running(tmp_path, monkeypatch):
    directory, _, _ = setup_cli(tmp_path, monkeypatch)
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: dict(state='running',error=None,report=None))
    assert cli.main(['--root', str(tmp_path)]) == 2
    assert candidate_store._load(directory/'attempt.json')['state'] == 'failed'


@pytest.mark.parametrize('desk_only', [False, True])
def test_success_composes_once_and_desk_only_never_reruns_legacy(tmp_path, monkeypatch, desk_only):
    directory, first, immutable = setup_cli(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service.store, 'read_status', lambda *a: dict(state='held', error=None, report=None))
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: calls.append('legacy') or dict(state='held',error=None,report=None))

    def refresh(*a):
        calls.append('candidate')
        candidate_store.set_attempt(directory, 'complete')
        return deepcopy(first)

    monkeypatch.setattr(service, 'refresh_desk', refresh)
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', lambda *a: calls.append('regular') or deepcopy(first))
    assert cli.main(['--root', str(tmp_path), *(['--desk-only'] if desk_only else [])]) == 0
    assert calls == (['candidate','regular'] if desk_only else ['legacy','candidate','regular'])
    assert candidate_store._load(directory/'attempt.json')['state'] == 'complete'
    assert all(path.read_bytes() == value for path, value in immutable.items())


def test_regular_only_recovers_failed_stage_without_touching_completed_upstream(tmp_path, monkeypatch):
    _, first, immutable = setup_cli(tmp_path, monkeypatch)
    monkeypatch.setattr(service.store, 'read_status', lambda *a: dict(state='held', error=None, report=None))
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: pytest.fail('reran completed legacy'))
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', lambda *a: deepcopy(first))
    assert cli.main(['--root', str(tmp_path), '--regular-only']) == 0
    assert all(path.read_bytes() == value for path, value in immutable.items())


def test_regular_failure_exits_nonzero_even_when_upstream_succeeded(tmp_path, monkeypatch):
    setup_cli(tmp_path, monkeypatch)
    monkeypatch.setattr(service.store, 'read_status', lambda *a: dict(state='held', error=None, report=None))
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', lambda *a: None)
    assert cli.main(['--root', str(tmp_path), '--regular-only']) == 1
