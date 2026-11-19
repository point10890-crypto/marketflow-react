"""CLI owns candidate attempt lifecycle across the preceding legacy scan."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import time

from filelock import FileLock, Timeout
import pytest

from scripts import run_alpha_lab as cli
from app.services.mirofish.alpha_lab import candidate_service as service, candidate_store
from app.services.mirofish.alpha_lab import regular_inputs
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
    monkeypatch.setattr(time, 'sleep', lambda *a: pytest.fail('busy CLI retried'))
    with FileLock(str(tmp_path/'candidate-compose.lock')).acquire(timeout=0):
        assert cli.main(['--root', str(tmp_path), '--candidate-attempts', '3']) == 2
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


def test_transient_candidate_failure_retries_without_legacy_replay(tmp_path, monkeypatch):
    directory, first, immutable = setup_cli(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: calls.append('legacy') or dict(state='held', error=None, report=None))

    def refresh(*a):
        calls.append('candidate')
        if calls.count('candidate') == 1:
            candidate_store.set_attempt(directory, 'failed', error='source_unavailable')
            return dict(first, state='failed')
        candidate_store.set_attempt(directory, 'complete')
        return deepcopy(first)

    def pause(seconds):
        calls.append(('sleep', seconds))
        with pytest.raises(Timeout):
            FileLock(str(tmp_path/'candidate-compose.lock')).acquire(timeout=0)
        with pytest.raises(Timeout):
            FileLock(str(tmp_path/'regular-compose.lock')).acquire(timeout=0)

    monkeypatch.setattr(service, 'refresh_desk', refresh)
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', lambda *a: calls.append('regular') or deepcopy(first))
    monkeypatch.setattr(time, 'sleep', pause)
    assert cli.main(['--root', str(tmp_path), '--candidate-attempts', '3']) == 0
    assert calls == ['legacy', 'candidate', ('sleep', 15), 'candidate', 'regular']
    assert all(path.read_bytes() == value for path, value in immutable.items())


@pytest.mark.parametrize('regular_only', [False, True])
def test_regular_retry_preserves_completed_candidate_and_legacy(tmp_path, monkeypatch, regular_only):
    directory, first, immutable = setup_cli(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service.store, 'read_status', lambda *a: dict(state='held', error=None, report=None))
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: calls.append('legacy') or dict(state='held', error=None, report=None))

    def candidate(*a):
        calls.append('candidate')
        candidate_store.set_attempt(directory, 'complete')
        return deepcopy(first)

    def regular(*a):
        calls.append('regular')
        assert candidate_store._load(directory/'attempt.json')['state'] == 'complete'
        if calls.count('regular') == 1:
            candidate_store.set_attempt(tmp_path/'candidate-regular-v1', 'failed', error='source_unavailable')
            return dict(first, state='failed')
        candidate_store.set_attempt(tmp_path/'candidate-regular-v1', 'complete')
        return deepcopy(first)

    monkeypatch.setattr(service, 'refresh_desk', candidate)
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', regular)
    monkeypatch.setattr(time, 'sleep', lambda seconds: calls.append(('sleep', seconds)))
    argv = ['--root', str(tmp_path), '--candidate-attempts', '3']
    assert cli.main([*argv, *(['--regular-only'] if regular_only else [])]) == 0
    assert calls == ([] if regular_only else ['legacy', 'candidate']) + ['regular', ('sleep', 15), 'regular']
    assert all(path.read_bytes() == value for path, value in immutable.items())


def test_candidate_exhaustion_keeps_failed_public_state_and_exit(tmp_path, monkeypatch):
    directory, first, immutable = setup_cli(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: calls.append('legacy') or dict(state='held', error=None, report=None))

    def refresh(*a):
        calls.append('candidate')
        candidate_store.set_attempt(directory, 'failed', error='source_unavailable')
        return dict(first, state='failed')

    monkeypatch.setattr(service, 'refresh_desk', refresh)
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', lambda *a: pytest.fail('daily failure reached regular collection'))
    monkeypatch.setattr(time, 'sleep', lambda seconds: calls.append(('sleep', seconds)))
    assert cli.main(['--root', str(tmp_path), '--candidate-attempts', '3']) == 1
    assert calls == ['legacy', 'candidate', ('sleep', 15), 'candidate', ('sleep', 15), 'candidate']
    assert candidate_store.read_public(directory)['state'] == 'failed'
    assert candidate_store._load(tmp_path/'candidate-regular-v1'/'attempt.json')['state'] == 'failed'
    assert all(path.read_bytes() == value for path, value in immutable.items())


def test_legacy_failure_never_uses_candidate_retry_budget(tmp_path, monkeypatch):
    setup_cli(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: calls.append('legacy') or dict(state='failed', error='scan_unavailable', report=None))
    monkeypatch.setattr(time, 'sleep', lambda *a: pytest.fail('legacy failure was retried'))
    assert cli.main(['--root', str(tmp_path), '--candidate-attempts', '3']) == 1
    assert calls == ['legacy']


def test_regular_exhaustion_returns_failure_with_successful_daily_preserved(tmp_path, monkeypatch):
    directory, first, immutable = setup_cli(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: calls.append('legacy') or dict(state='held', error=None, report=None))

    def candidate(*a):
        calls.append('candidate')
        candidate_store.set_attempt(directory, 'complete')
        return deepcopy(first)

    def regular(*a):
        calls.append('regular')
        candidate_store.set_attempt(tmp_path/'candidate-regular-v1', 'failed', error='source_unavailable')
        return dict(first, state='failed')

    monkeypatch.setattr(service, 'refresh_desk', candidate)
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', regular)
    monkeypatch.setattr(time, 'sleep', lambda seconds: calls.append(('sleep', seconds)))
    assert cli.main(['--root', str(tmp_path), '--candidate-attempts', '2']) == 1
    assert calls == ['legacy', 'candidate', 'regular', ('sleep', 15), 'regular']
    assert candidate_store._load(directory/'attempt.json')['state'] == 'complete'
    assert candidate_store._load(tmp_path/'candidate-regular-v1'/'attempt.json')['state'] == 'failed'
    assert all(path.read_bytes() == value for path, value in immutable.items())


@pytest.mark.parametrize('busy_stage', ['candidate', 'regular'])
def test_running_stage_exits_busy_without_retry(tmp_path, monkeypatch, busy_stage):
    directory, first, immutable = setup_cli(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service.legacy, 'scan_once', lambda *a: calls.append('legacy') or dict(state='held', error=None, report=None))

    def candidate(*a):
        calls.append('candidate')
        candidate_store.set_attempt(directory, 'running' if busy_stage == 'candidate' else 'complete')
        return dict(first, state='running') if busy_stage == 'candidate' else deepcopy(first)

    monkeypatch.setattr(service, 'refresh_desk', candidate)
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', lambda *a: calls.append('regular') or dict(first, state='running'))
    monkeypatch.setattr(time, 'sleep', lambda *a: pytest.fail('running stage retried'))
    assert cli.main(['--root', str(tmp_path), '--candidate-attempts', '3']) == 2
    assert calls == ['legacy', 'candidate'] + (['regular'] if busy_stage == 'regular' else [])
    assert all(path.read_bytes() == value for path, value in immutable.items())


@pytest.mark.parametrize('corrupt', [False, True])
def test_structural_or_corrupt_current_regular_receipt_stops_retry(tmp_path, monkeypatch, corrupt):
    _, first, immutable = setup_cli(tmp_path, monkeypatch)
    monkeypatch.setattr(service.store, 'read_status', lambda *a: dict(state='held', error=None, report=None))
    service.store._write(tmp_path/'inputs'/'current.json', dict(latest_session='2026-10-21'))
    contract = service.store._hash(regular_inputs.source_contract())
    path = tmp_path/'candidate-regular-v1'/'inputs'/'epochs'/contract/'2026-10-21'/'attempt.json'
    regular_inputs.daily._write(path, dict(objects={'005930': 'a'*64}, failures={'000660': 'regular_page_size'}))
    if corrupt:
        path.write_text('{"data": {}, "sha256": "invalid"}', encoding='utf-8')
    receipt = path.read_bytes()
    calls = []
    monkeypatch.setattr(cli.regular_service, 'refresh_desk', lambda *a: calls.append('regular') or dict(first, state='failed'))
    monkeypatch.setattr(time, 'sleep', lambda *a: pytest.fail('structural validation was retried'))
    assert cli.main(['--root', str(tmp_path), '--regular-only', '--candidate-attempts', '3']) == 1
    assert calls == ['regular']
    assert path.read_bytes() == receipt
    assert all(p.read_bytes() == value for p, value in immutable.items())


def test_only_transient_current_regular_receipt_retries_preserving_saved_objects(tmp_path, monkeypatch):
    _, first, immutable = setup_cli(tmp_path, monkeypatch)
    monkeypatch.setattr(service.store, 'read_status', lambda *a: dict(state='held', error=None, report=None))
    service.store._write(tmp_path/'inputs'/'current.json', dict(latest_session='2026-10-21'))
    contract = service.store._hash(regular_inputs.source_contract())
    epochs = tmp_path/'candidate-regular-v1'/'inputs'/'epochs'
    current = epochs/contract/'2026-10-21'/'attempt.json'
    regular_inputs.daily._write(current, dict(objects={'005930': 'a'*64}, failures={'000660': 'kis_http_failure'}))
    old = epochs/contract/'2026-10-20'/'attempt.json'
    wrong_contract = epochs/('b'*64)/'2026-10-21'/'attempt.json'
    for path in (old, wrong_contract):
        regular_inputs.daily._write(path, dict(objects={}, failures={'000660': 'regular_page_size'}))
    sealed = {path: path.read_bytes() for path in (current, old, wrong_contract)}
    calls = []

    def refresh(*a):
        calls.append('regular')
        assert regular_inputs._read(current)['objects'] == {'005930': 'a'*64}
        return dict(first, state='failed') if len(calls) == 1 else deepcopy(first)

    monkeypatch.setattr(cli.regular_service, 'refresh_desk', refresh)
    monkeypatch.setattr(time, 'sleep', lambda seconds: calls.append(('sleep', seconds)))
    assert cli.main(['--root', str(tmp_path), '--regular-only', '--candidate-attempts', '3']) == 0
    assert calls == ['regular', ('sleep', 15), 'regular']
    assert all(p.read_bytes() == value for p, value in {**immutable, **sealed}.items())
