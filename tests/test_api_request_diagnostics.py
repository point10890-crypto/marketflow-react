"""Bounded, credential-free evidence for the next slow API request."""
import json
import sys

from flask import Flask


def test_five_second_sampling_is_bounded_and_file_io_is_outside_request_lock(tmp_path, monkeypatch):
    from app.utils.api_request_diagnostics import RequestDiagnostics
    clock = [0.0]
    monitor = RequestDiagnostics(tmp_path, clock=lambda: clock[0], frames=lambda: {42: sys._getframe()})
    for number in range(20):
        monitor.begin(42, '/api/example/<int:item>')
    assert monitor.snapshot()['active'] == 16
    assert monitor.snapshot()['untracked'] == 4
    original = monitor._write_snapshot
    def write(snapshot):
        assert not monitor._lock.locked(), 'disk I/O holds the request registry lock'
        original(snapshot)
    monkeypatch.setattr(monitor, '_write_snapshot', write)
    clock[0] = 4.99
    assert not monitor.sample()
    for moment in (5, 10, 15, 20):
        clock[0] = moment
        assert monitor.sample()
        assert not monitor.sample(), 'same five-second slot sampled twice'
    files = sorted(tmp_path.glob('slow-requests-*.json'))
    assert len(files) == 3
    for path in files:
        content = json.loads(path.read_text(encoding='utf-8'))
        assert len(content['requests']) == 16
        assert all(len(item['frames']) <= 12 for item in content['requests'])
        assert all('/' not in frame['file'] and '\\' not in frame['file']
                   for item in content['requests'] for frame in item['frames'])


def test_flask_hooks_record_route_pattern_only_and_cleanup_after_success_and_exception(tmp_path):
    from app.utils.api_request_diagnostics import install_request_diagnostics
    app = Flask('request-diagnostics-test')
    clock = [0.0]
    monitor = install_request_diagnostics(app, tmp_path, clock=lambda: clock[0], start_worker=False)
    @app.route('/api/example/<int:item>')
    def example(item):
        return {'ok': True}
    @app.route('/api/error')
    def error():
        raise ValueError('not recorded')
    with app.test_request_context('/api/example/987654?api_key=SYNTHETIC_QUERY',
                                  headers={'Authorization': 'Bearer SYNTHETIC_AUTH'},
                                  data='SYNTHETIC_BODY'):
        app.preprocess_request()
        clock[0] = 5
        assert monitor.sample()
        app.process_response(app.response_class('ok'))
        assert monitor.snapshot()['active'] == 1  # Retain until every after_request hook finishes.
    assert monitor.snapshot()['active'] == 0
    text = next(tmp_path.glob('slow-requests-*.json')).read_text(encoding='utf-8')
    assert '/api/example/<int:item>' in text
    assert all(secret not in text for secret in ('987654', 'SYNTHETIC_QUERY', 'SYNTHETIC_AUTH', 'SYNTHETIC_BODY'))
    assert app.test_client().get('/api/error').status_code == 500
    assert monitor.snapshot()['active'] == 0


def test_preexisting_slow_after_request_hook_is_sampled_before_teardown(tmp_path):
    from app.utils.api_request_diagnostics import install_request_diagnostics
    app = Flask('slow-after-request')
    clock = [0.0]
    samples = []
    @app.after_request
    def slow_after(response):
        clock[0] = 6
        samples.append(monitor.sample())
        return response
    monitor = install_request_diagnostics(app, tmp_path, clock=lambda: clock[0], start_worker=False)
    app.add_url_rule('/example', view_func=lambda: 'ok')
    assert app.test_client().get('/example').status_code == 200
    assert samples == [True]
    assert monitor.snapshot()['active'] == 0


def test_failed_snapshot_write_never_propagates_or_logs_and_cleanup_still_works(tmp_path, monkeypatch):
    import logging
    from app.utils import api_request_diagnostics as diagnostics
    clock = [0.0]
    monitor = diagnostics.RequestDiagnostics(tmp_path, clock=lambda: clock[0])
    token = monitor.begin(42, '/api/test')
    clock[0] = 5
    def fail(*args, **kwargs):
        raise OSError('synthetic disk unavailable')
    monkeypatch.setattr(diagnostics.os, 'replace', fail)
    monkeypatch.setattr(logging.Logger, '_log', lambda *a, **k: (_ for _ in ()).throw(AssertionError('log fallback')))
    assert not monitor.sample()
    assert monitor.snapshot()['write_errors'] == 1
    monitor.finish(token)
    assert monitor.snapshot()['active'] == 0
    assert not list(tmp_path.glob('*.tmp'))


def test_install_is_idempotent_and_monitor_thread_is_daemon_and_stoppable(tmp_path):
    from app.utils.api_request_diagnostics import install_request_diagnostics
    app = Flask('request-diagnostics-idempotent')
    monitor = install_request_diagnostics(app, tmp_path)
    before = len(app.before_request_funcs[None])
    assert install_request_diagnostics(app, tmp_path) is monitor
    assert len(app.before_request_funcs[None]) == before
    assert monitor.thread.daemon and monitor.thread.is_alive()
    monitor.stop()
    monitor.thread.join(timeout=1)
    assert not monitor.thread.is_alive()
