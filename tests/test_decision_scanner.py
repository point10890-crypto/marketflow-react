"""A slow scanner archive must never hold a decision request open."""
import json
from pathlib import Path
import threading
import time

import pytest

from app.services.mirofish import alpha_scanner


@pytest.fixture
def scanner(tmp_path, monkeypatch):
    from app.services.mirofish import decision_scanner
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    clock = [100.0]
    monkeypatch.setattr(decision_scanner, 'monotonic', lambda: clock[0])
    yield decision_scanner, clock
    worker = decision_scanner._worker
    if worker is not None:
        worker.join(timeout=2)
        assert not worker.is_alive(), 'test left a blocked scanner snapshot worker'


def _wait_snapshot(module):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            return module.read_snapshot()
        except module.SnapshotPending:
            threading.Event().wait(.005)
    pytest.fail('snapshot did not finish after the source was released')


def _payload(stamp='2026-11-12T07:00:00Z'):
    return {'run_id': 'mfas_20261112070000_test', 'status': 'completed',
            'generated_at': stamp, 'candidates': [{'symbol': '005930', 'rank': 1,
            'name': '삼성전자', 'action': 'BUY', 'alpha_score': 85, 'risk_score': 20}]}


def test_cold_request_returns_pending_before_blocked_archive_finishes(scanner, monkeypatch):
    module, _ = scanner
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    observations = []

    def blocked_reader(*, limit):
        observations.append((limit, threading.current_thread().daemon))
        entered.set()
        release.wait(2)
        return _payload()

    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', blocked_reader)
    response = []

    def request():
        try:
            response.append(module.read_snapshot())
        except Exception as error:
            response.append(error)
        finally:
            returned.set()

    request_thread = threading.Thread(target=request, daemon=True)
    request_thread.start()
    try:
        assert entered.wait(.5)
        assert returned.wait(.5), 'decision request waited for archive enumeration'
        assert isinstance(response[0], module.SnapshotPending)
        for _ in range(20):
            with pytest.raises(module.SnapshotPending):
                module.read_snapshot()
        assert observations == [(20, True)]
    finally:
        release.set()
        request_thread.join(2)
    result = _wait_snapshot(module)
    assert result['generated_at'] == '2026-11-12T07:00:00Z'
    assert result['candidates'][0]['symbol'] == '005930'


@pytest.mark.parametrize('value', [None, {'generated_at': '2026-11-12T07:00:00Z', 'candidates': []}])
def test_completed_empty_is_cached_and_distinct_from_pending(scanner, monkeypatch, value):
    module, clock = scanner
    calls = []

    def reader(*, limit):
        calls.append(limit)
        return value

    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', reader)
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    assert _wait_snapshot(module) == value
    clock[0] += 29
    assert module.read_snapshot() == value
    assert calls == [20]


def test_expired_snapshot_is_pending_during_single_refresh_and_keeps_source_time(scanner, monkeypatch):
    module, clock = scanner
    release, refreshing = threading.Event(), threading.Event()
    calls = []

    def reader(*, limit):
        calls.append(limit)
        if len(calls) == 1:
            return _payload('2026-11-11T07:00:00Z')
        refreshing.set()
        release.wait(2)
        return _payload('2026-11-12T07:00:00Z')

    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', reader)
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    assert _wait_snapshot(module)['generated_at'] == '2026-11-11T07:00:00Z'
    clock[0] = 129.999
    assert module.read_snapshot()['generated_at'] == '2026-11-11T07:00:00Z'
    clock[0] = 130
    try:
        for _ in range(20):
            with pytest.raises(module.SnapshotPending):
                module.read_snapshot()
        assert refreshing.wait(.5)
        assert calls == [20, 20]
    finally:
        release.set()
    assert _wait_snapshot(module)['generated_at'] == '2026-11-12T07:00:00Z'


def test_failure_is_safe_and_retry_is_rate_limited(scanner, monkeypatch):
    module, clock = scanner
    calls = []

    def reader(*, limit):
        calls.append(limit)
        if len(calls) == 1:
            raise OSError('C:/private/archive token=secret')
        return _payload()

    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', reader)
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    with pytest.raises(module.SnapshotUnavailable) as failure:
        _wait_snapshot(module)
    assert 'secret' not in str(failure.value) and 'private' not in str(failure.value)
    clock[0] = 129
    for _ in range(10):
        with pytest.raises(module.SnapshotUnavailable):
            module.read_snapshot()
    assert calls == [20]
    clock[0] = 130
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    assert _wait_snapshot(module)['candidates'][0]['rank'] == 1
    assert calls == [20, 20]


def test_refresh_failure_does_not_serve_last_success_as_current(scanner, monkeypatch):
    module, clock = scanner
    calls = []

    def reader(*, limit):
        calls.append(limit)
        if len(calls) > 1:
            raise RuntimeError('secret source failure')
        return _payload()

    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', reader)
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    assert _wait_snapshot(module)['generated_at'] == '2026-11-12T07:00:00Z'
    clock[0] = 130
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    with pytest.raises(module.SnapshotUnavailable):
        _wait_snapshot(module)


def test_root_change_discards_old_snapshot_and_keeps_only_one_worker(scanner, monkeypatch, tmp_path):
    module, _ = scanner
    entered, release = threading.Event(), threading.Event()
    roots = []
    first_root = alpha_scanner.SCANNER_RUNS_ROOT

    def reader(*, limit):
        root = alpha_scanner.SCANNER_RUNS_ROOT
        roots.append(root)
        if root == first_root:
            entered.set()
            release.wait(2)
        return _payload(root)

    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', reader)
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    try:
        assert entered.wait(.5)
        first_worker = module._worker
        next_root = str(tmp_path / 'another_archive')
        monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', next_root)
        for _ in range(10):
            with pytest.raises(module.SnapshotPending):
                module.read_snapshot()
        assert module._worker is first_worker and roots == [first_root]
    finally:
        release.set()
    first_worker.join(2)
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    assert _wait_snapshot(module)['generated_at'] == next_root
    assert roots == [first_root, next_root]


def test_returned_result_is_detached_from_the_cached_snapshot(scanner, monkeypatch):
    module, _ = scanner
    value = _payload()
    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', lambda **kwargs: value)
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    first = _wait_snapshot(module)
    first['candidates'][0]['alpha_score'] = -1
    value['candidates'][0]['alpha_score'] = -2
    assert module.read_snapshot()['candidates'][0]['alpha_score'] == 85


def test_existing_directory_lock_is_not_acquired_by_request_thread(scanner):
    module, _ = scanner
    returned = threading.Event()
    outcome = []

    def request():
        try:
            outcome.append(module.read_snapshot())
        except Exception as error:
            outcome.append(error)
        finally:
            returned.set()

    with alpha_scanner._RUN_PATHS_CACHE_LOCK:
        thread = threading.Thread(target=request, daemon=True)
        thread.start()
        assert returned.wait(.5), 'request waited for scanner directory lock'
        assert isinstance(outcome[0], module.SnapshotPending)
    thread.join(2)
    assert _wait_snapshot(module) is None
    assert not Path(alpha_scanner.SCANNER_RUNS_ROOT).exists()


def test_real_scanner_snapshot_preserves_compact_limit_and_does_not_write(scanner):
    module, _ = scanner
    root = Path(alpha_scanner.SCANNER_RUNS_ROOT)
    path = root / 'mfas_20261112070000_aaaaaaaaaaaa' / 'run.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'id': path.parent.name, 'status': 'completed',
        'generated_at': '2026-11-12T07:00:00Z',
        'candidates': [{'symbol': f'{index:06}', 'rank': index, 'action': 'HOLD'}
                       for index in range(1, 31)]}), encoding='utf8')
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    with pytest.raises(module.SnapshotPending):
        module.read_snapshot()
    result = _wait_snapshot(module)
    assert len(result['candidates']) == 20 and result['candidate_count'] == 30
    assert result['generated_at'] == '2026-11-12T07:00:00Z'
    after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    assert after == before
