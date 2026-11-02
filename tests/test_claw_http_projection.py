"""Claw HTTP deadlines also bound blocking file/SQLite I/O without VM callbacks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

from flask import Flask, has_app_context, has_request_context

import app.auth.decorators as auth
from app.routes.kr_claw import kr_claw_bp
from marketflow_claw import observation, overview


def _application(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(kr_claw_bp, url_prefix='/api/kr/claw')
    monkeypatch.setattr(auth, '_get_current_user', lambda: SimpleNamespace(
        status='approved', is_admin=True, is_approved=True, tier='premium',
        is_pro_expired=False, is_aibain_active=True,
    ))
    return app


def test_blocking_overview_io_returns_warming_without_holding_http_thread(monkeypatch):
    app = _application(monkeypatch)
    release = threading.Event()
    entered = threading.Event()

    def blocked_io():
        entered.set()
        release.wait(1.0)  # No SQLite progress callback can interrupt this I/O.
        return {'generated_at': '2026-11-03T10:00:00', 'leaders': {'rows': []}}

    monkeypatch.setattr(overview, 'build_overview', blocked_io)
    started = time.monotonic()
    try:
        response = app.test_client().get('/api/kr/claw/overview')
        elapsed = time.monotonic() - started
        assert entered.is_set()
        assert elapsed < 0.5
        assert response.status_code == 503
        payload = response.get_json()
        assert payload['projection']['state'] == 'warming'
        assert payload['projection']['refreshing'] is True
        assert 'leaders' not in payload  # Never present unavailable I/O as zero stocks.
        assert response.headers['Retry-After'] == '5'
        assert response.headers['Cache-Control'] == 'no-cache, no-store, must-revalidate'
    finally:
        release.set()


def test_fast_projection_runs_without_flask_context_and_copies_payload(monkeypatch):
    app = _application(monkeypatch)
    original = {'generated_at': '2026-11-03T10:00:00', 'leaders': {'rows': [{'code': '005930'}]}}

    def fast_io():
        assert not has_request_context()
        assert not has_app_context()
        return original

    monkeypatch.setattr(overview, 'build_overview', fast_io)
    response = app.test_client().get('/api/kr/claw/overview')
    assert response.status_code == 200
    assert response.get_json()['projection']['state'] == 'fresh'
    assert response.get_json()['generated_at'] == '2026-11-03T10:00:00'
    assert 'projection' not in original
    response.get_json()['leaders']['rows'].clear()
    assert len(app.test_client().get('/api/kr/claw/overview').get_json()['leaders']['rows']) == 1


def test_concurrent_cold_requests_share_one_worker_and_do_not_retry_blocked_io(monkeypatch):
    app = _application(monkeypatch)
    release = threading.Event()
    calls = []

    def blocked_io():
        calls.append(threading.get_ident())
        release.wait(3)
        return {'generated_at': 'original'}

    monkeypatch.setattr(overview, 'build_overview', blocked_io)
    try:
        with ThreadPoolExecutor(max_workers=8) as clients:
            responses = list(clients.map(lambda _: app.test_client().get('/api/kr/claw/overview'), range(8)))
        assert {response.status_code for response in responses} == {503}
        assert len(calls) == 1
        assert app.test_client().get('/api/kr/claw/overview').status_code == 503
        assert len(calls) == 1
    finally:
        release.set()


def test_denied_requests_never_start_projection(monkeypatch):
    app = _application(monkeypatch)
    calls = []
    monkeypatch.setattr(overview, 'build_overview', lambda: calls.append(True))
    monkeypatch.setattr(auth, '_get_current_user', lambda: None)
    assert app.test_client().get('/api/kr/claw/overview').status_code == 401
    assert not calls


def test_explicit_diagnostics_blocking_io_are_also_bounded(monkeypatch):
    app = _application(monkeypatch)
    release = threading.Event()

    def blocked_io(**kwargs):
        release.wait(2)
        return {'status': 'ok'}

    monkeypatch.setattr(observation, 'build_quality', blocked_io)
    monkeypatch.setattr(observation, 'build_scorecards', blocked_io)
    try:
        started = time.monotonic()
        for endpoint in ('quality', 'scorecards?window_days=20'):
            response = app.test_client().get('/api/kr/claw/' + endpoint)
            assert response.status_code == 503
            assert response.get_json()['projection']['state'] == 'warming'
        assert time.monotonic() - started < 0.7
    finally:
        release.set()


def _settled(cache, key, builder):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        result = cache.read(key, builder)
        if not result.metadata['refreshing']:
            return result
        time.sleep(0.001)
    raise AssertionError('projection did not settle')


def test_stale_snapshot_survives_blocked_refresh_ttl_and_failed_refresh():
    from marketflow_claw.http_projection import BoundedProjectionCache

    clock = [0.0]
    cache = BoundedProjectionCache(ttl_seconds=1, clock=lambda: clock[0])
    original = {'generated_at': 'original', 'freshness': {'age_seconds': 7}, 'rows': [{'n': 3}]}
    assert cache.read('overview', lambda: original).payload == original
    clock[0] = 2
    release = threading.Event()
    entered = threading.Event()
    calls = []

    def blocked_refresh():
        calls.append(True)
        entered.set()
        release.wait(3)
        raise OSError('private-file-path-must-not-leak')

    try:
        stale = cache.read('overview', blocked_refresh)
        assert entered.wait(1)
        assert stale.payload == original
        assert stale.metadata['state'] == 'stale'
        stale.payload['rows'][0]['n'] = 999
        clock[0] = 100
        for _ in range(10):
            again = cache.read('overview', blocked_refresh)
            assert again.payload['rows'] == [{'n': 3}]
            assert again.payload['generated_at'] == 'original'
            assert again.payload['freshness']['age_seconds'] == 7
        assert len(calls) == 1
    finally:
        release.set()
    failed = _settled(cache, 'overview', blocked_refresh)
    assert failed.payload == original
    assert failed.metadata['state'] == 'stale'
    assert failed.metadata['last_error'] == 'OSError'
    assert 'private-file-path' not in str(failed.metadata)
    assert 'projection' not in original
    assert len(calls) == 1


def test_worker_and_key_capacity_never_queue_extra_builders_or_evict_blocked_key():
    from marketflow_claw.http_projection import BoundedProjectionCache

    cache = BoundedProjectionCache(max_workers=2, max_keys=2, wait_seconds=0.01)
    release = threading.Event()
    entered = threading.Barrier(3)
    calls = []

    def blocked_io():
        calls.append(True)
        entered.wait(1)
        release.wait(2)
        return {'ok': True}

    try:
        cache.read('first', blocked_io)
        cache.read('second', blocked_io)
        entered.wait(1)
        for n in range(30):
            result = cache.read(f'key-{n}', lambda: {'unexpected': True})
            assert result.payload is None
            assert result.metadata['state'] == 'unavailable'
        assert cache.read('first', blocked_io).metadata['refreshing'] is True
        assert len(calls) == 2
    finally:
        release.set()


def test_unavailable_diagnostic_does_not_replace_last_good_snapshot(monkeypatch):
    from marketflow_claw.http_projection import BoundedProjectionCache

    app = _application(monkeypatch)
    clock = [0.0]
    app.extensions['claw_http_projection'] = BoundedProjectionCache(ttl_seconds=1, clock=lambda: clock[0])
    monkeypatch.setattr(observation, 'build_quality', lambda: {
        'generated_at': 'original', 'status': 'ok', 'ledger': {'scans': 42},
    })
    client = app.test_client()
    assert client.get('/api/kr/claw/quality').get_json()['ledger']['scans'] == 42
    clock[0] = 2
    monkeypatch.setattr(observation, 'build_quality', lambda: {
        'status': 'unavailable', 'ledger': {'scans': 0},
    })
    client.get('/api/kr/claw/quality')
    settled = _settled(app.extensions['claw_http_projection'], 'quality', lambda: {})
    response = client.get('/api/kr/claw/quality')
    assert settled.metadata['last_error'] == 'ProjectionUnavailable'
    assert response.get_json()['ledger']['scans'] == 42
    assert response.get_json()['generated_at'] == 'original'
    assert response.get_json()['projection']['state'] == 'stale'


def test_worker_limit_refuses_new_work_without_creating_a_queue():
    from marketflow_claw.http_projection import BoundedProjectionCache

    cache = BoundedProjectionCache(max_workers=1, max_keys=3, wait_seconds=0.01)
    release = threading.Event()
    entered = threading.Event()
    extra_calls = []

    def blocked_io():
        entered.set()
        release.wait(2)
        return {'first': True}

    def extra_io():
        extra_calls.append(True)
        return {'second': True}

    try:
        cache.read('first', blocked_io)
        assert entered.wait(1)
        refused = cache.read('second', extra_io)
        assert refused.payload is None
        assert refused.metadata['state'] == 'unavailable'
        assert refused.metadata['refreshing'] is False
    finally:
        release.set()
    _settled(cache, 'first', blocked_io)
    assert not extra_calls  # Capacity returning must not start a queued job.
    assert cache.read('second', extra_io).payload == {'second': True}


def test_cold_failure_retries_after_backoff_and_recovers_to_fresh():
    from marketflow_claw.http_projection import BoundedProjectionCache

    clock = [0.0]
    cache = BoundedProjectionCache(clock=lambda: clock[0])
    calls = []

    def failing_io():
        calls.append(True)
        raise OSError('sensitive')

    failed = cache.read('quality', failing_io)
    assert failed.payload is None
    assert failed.metadata['state'] == 'unavailable'
    assert failed.metadata['last_error'] == 'OSError'
    assert cache.read('quality', failing_io).payload is None
    assert len(calls) == 1
    clock[0] = 6
    recovered = cache.read('quality', lambda: {'generated_at': 'recovered', 'status': 'ok'})
    assert recovered.payload == {'generated_at': 'recovered', 'status': 'ok'}
    assert recovered.metadata['state'] == 'fresh'
    assert recovered.metadata['last_error'] is None


def test_scorecard_cache_keys_preserve_window_parameters(monkeypatch):
    app = _application(monkeypatch)
    monkeypatch.setattr(observation, 'build_scorecards', lambda *, window_days: {'window_days': window_days})
    client = app.test_client()
    assert client.get('/api/kr/claw/scorecards?window_days=20').get_json()['window_days'] == 20
    assert client.get('/api/kr/claw/scorecards?window_days=40').get_json()['window_days'] == 40
    assert client.get('/api/kr/claw/scorecards?window_days=-8').get_json()['window_days'] == 1
    assert client.get('/api/kr/claw/scorecards?window_days=1000').get_json()['window_days'] == 365
    assert client.get('/api/kr/claw/scorecards?window_days=invalid').get_json()['window_days'] == 30
