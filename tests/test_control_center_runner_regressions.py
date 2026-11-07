from datetime import timedelta
import os

from app.services.control_center import incidents, runner, store
from app.services.control_center.model import CheckResult, iso, now_kst


def _result(check_id, family, status, detail=''):
    return CheckResult(check_id, family, check_id.split(':', 1)[1], status, detail)


def test_lock_cannot_be_stolen_from_live_owner(tmp_path):
    with runner.TierLock('fast', str(tmp_path)) as lock:
        os.utime(lock.path, (1, 1))
        with runner.TierLock('fast', str(tmp_path)) as rival:
            assert not rival.acquired


def test_fresh_fast_cannot_hide_stale_standard(tmp_path):
    now = now_kst()
    last_runs = {
        'fast': {'finished_at': iso(now)},
        'standard': {'finished_at': iso(now - timedelta(hours=1))},
        'deep': {'finished_at': iso(now)},
    }
    store.write_json_atomic(str(tmp_path / 'latest.json'), {'overall': 'ok', 'last_runs': last_runs})
    store.write_json_atomic(str(tmp_path / 'heartbeat.json'), {'ts': iso(now), 'tier': 'fast'})
    snapshot = runner.read_snapshot(str(tmp_path))
    assert snapshot['monitor']['status'] == 'fail'
    assert snapshot['monitor']['tiers']['standard']['status'] == 'fail'
    assert snapshot['overall'] == 'fail'


def test_snapshot_shows_partial_page_coverage_and_security_failure(tmp_path):
    contract = {'pages': [{'path': '/x', 'label': 'X', 'endpoints': ['/a', '/b']}], 'data': []}
    with store.connect(str(tmp_path)) as conn:
        incidents.apply(conn, _result('endpoint:/a', 'endpoint', 'ok'), 'standard')
        snapshot = runner.build_snapshot(conn, contract)
        assert snapshot['pages'][0]['status'] == 'unknown'
        incidents.apply(conn, _result('endpoint:/b', 'endpoint', 'skipped'), 'standard')
        assert runner.build_snapshot(conn, contract)['pages'][0]['status'] == 'unknown'
        incidents.apply(conn, _result('security:/a', 'security', 'fail'), 'standard')
        assert runner.build_snapshot(conn, contract)['pages'][0]['status'] == 'fail'


def test_security_incident_requires_two_protected_observations(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'run_checks', lambda *a: [_result('security:/x', 'security', 'fail')])
    runner.run('standard', str(tmp_path), send_alerts=False)
    monkeypatch.setattr(runner, 'run_checks', lambda *a: [_result('gate:/x', 'endpoint', 'ok')])
    runner.run('standard', str(tmp_path), send_alerts=False)
    assert runner.read_snapshot(str(tmp_path))['open_incidents']
    runner.run('standard', str(tmp_path), send_alerts=False)
    assert not runner.read_snapshot(str(tmp_path))['open_incidents']


def test_skipped_results_cannot_resolve_incident(tmp_path):
    with store.connect(str(tmp_path)) as conn:
        for status in ('fail', 'skipped', 'skipped'):
            incidents.apply(conn, _result('job:x', 'job', status), 'standard')
        assert store.open_incidents(conn)


def test_read_only_api_validates_params_and_does_not_initialize_storage(tmp_path, monkeypatch):
    from flask import Flask
    from app.routes.control_center import control_center_bp

    monkeypatch.setenv('CONTROL_CENTER_DIR', str(tmp_path / 'absent'))
    app = Flask(__name__)
    app.register_blueprint(control_center_bp)
    for endpoint, view in tuple(app.view_functions.items()):
        if endpoint.startswith('control_center.'):
            app.view_functions[endpoint] = view.__wrapped__
    client = app.test_client()

    for path in ('/incidents?state=invalid', '/incidents?limit=bad', '/checks/x/history?hours=nan'):
        response = client.get(path)
        assert response.status_code == 400
        assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/incidents').get_json()['incidents'] == []
    assert client.get('/checks/x/history').get_json()['state'] is None
    assert not (tmp_path / 'absent').exists()


def test_runner_does_not_persist_raw_exception_text(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError('secret=do-not-persist')

    monkeypatch.setattr(runner, 'run_checks', fail)
    runner.run('fast', str(tmp_path), send_alerts=False)
    detail = runner.read_snapshot(str(tmp_path))['failing'][0]['detail']
    assert 'RuntimeError' in detail
    assert 'do-not-persist' not in detail


def test_inventory_does_not_initialize_database(monkeypatch):
    from app.models import db

    def fail(*args):
        raise AssertionError('inventory must not initialize the database')

    monkeypatch.setattr(db, 'init_app', fail)
    rows = runner.build_inventory_payload()['routes']
    assert len(rows) > 300
    assert any(r['rule'] == '/api/system/diagnostics' and r['auth'] == 'admin' for r in rows)


def test_prune_expires_resolved_incidents_and_audit_events(tmp_path):
    with store.connect(str(tmp_path)) as conn:
        conn.execute("INSERT INTO events (at, kind) VALUES ('2000-01-01', 'test')")
        conn.execute("INSERT INTO incidents (check_id, opened_at, resolved_at) VALUES ('old', '2000-01-01', '2000-01-02')")
        conn.execute("INSERT INTO incidents (check_id, opened_at) VALUES ('open', '2000-01-01')")
        store.prune(conn)
        assert not conn.execute('SELECT * FROM events').fetchall()
        assert [item['check_id'] for item in store.recent_incidents(conn)] == ['open']


def test_standard_probes_only_reviewed_gate_paths(tmp_path, monkeypatch):
    from app.services.control_center import http_checks, local_checks

    contract = {'endpoints': {'auth_probe_safe': ['/safe']}, 'data': [], 'jobs': [], 'windows_tasks': {}}
    inventory = {'routes': [
        {'rule': path, 'readable': True, 'auth': 'admin'} for path in ('/safe', '/unsafe')
    ]}
    monkeypatch.setattr(runner, 'load_inventory', lambda *a: inventory)
    monkeypatch.setattr(http_checks, 'http_get', lambda *a, **k: {'status': 200})
    monkeypatch.setattr(http_checks, 'mint_service_token', lambda: None)
    monkeypatch.setattr(http_checks, 'auth_gate_sweep', lambda base, rows: [
        _result('gate:' + row['rule'], 'endpoint', 'ok') for row in rows
    ])
    for name in ('check_data', 'check_jobs', 'check_windows_tasks', 'check_disk', 'check_memory'):
        monkeypatch.setattr(local_checks, name, lambda *a: [])
    by_id = {r.id: r for r in runner.run_checks('standard', contract, {}, str(tmp_path))}
    assert 'gate:/safe' in by_id and 'gate:/unsafe' not in by_id
    assert by_id['gate:/safe'].status == 'ok'
    assert by_id['monitor:gate_sweep'].status == 'unknown'
    assert by_id['monitor:gate_sweep'].data == {'observed': 1, 'candidates': 2, 'skipped': 1}


def test_cli_succeeds_when_monitor_observed_service_failure(tmp_path, monkeypatch):
    from app.services.control_center import __main__ as cli

    monkeypatch.setenv('CONTROL_CENTER_DIR', str(tmp_path))
    monkeypatch.setattr(cli, '_load_env', lambda: None)
    monkeypatch.setattr(runner, 'run_checks', lambda *args: [
        CheckResult('process:x', 'process', 'x', 'fail', severity='critical')
    ])
    assert cli.main(['run', '--tier', 'fast', '--no-alerts']) == 0
    assert runner.read_snapshot()['overall'] == 'fail'


def test_cli_fails_when_monitor_itself_crashes(tmp_path, monkeypatch):
    from app.services.control_center import __main__ as cli

    def fail(*args):
        raise RuntimeError('unexpected internal failure')

    monkeypatch.setenv('CONTROL_CENTER_DIR', str(tmp_path))
    monkeypatch.setattr(cli, '_load_env', lambda: None)
    monkeypatch.setattr(runner, 'run_checks', fail)
    assert cli.main(['run', '--tier', 'fast', '--no-alerts']) != 0


def test_protected_probes_require_confirmed_admin_identity(monkeypatch):
    from app.services.control_center import http_checks

    requests = []

    def get(url, **kwargs):
        requests.append(url)
        return {'status': 403, 'json': None}

    monkeypatch.setattr(http_checks, 'mint_service_token', lambda: 'mock-token')
    monkeypatch.setattr(http_checks, 'http_get', get)
    contract = {'endpoints': {'auth_probe_safe': ['/api/kr/claw/overview'],
                              'deep': [{'path': '/api/kr/claw/overview', 'tier': 'standard'}]}}
    monkeypatch.delenv('CONTROL_CENTER_AUTH_PROBES_ENABLED', raising=False)
    disabled = runner._probe_endpoints('http://localhost', contract, 'standard', now_kst())
    assert not requests
    assert all(result.status == 'skipped' for result in disabled)
    monkeypatch.setenv('CONTROL_CENTER_AUTH_PROBES_ENABLED', '1')
    results = runner._probe_endpoints('http://localhost', contract, 'standard', now_kst())
    assert requests == ['http://localhost/api/admin/control-center/summary']
    assert {r.status for r in results} == {'skipped', 'unknown'}


def test_tiers_publish_in_commit_order(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    fast_reached_publish = Event()
    release_fast_publish = Event()
    deep_finished_probes = Event()
    original = store.write_json_atomic

    def probe(tier, *args):
        if tier == 'deep':
            deep_finished_probes.set()
        return [_result('process:' + tier, 'process', 'ok')]

    def write(path, payload):
        if path.endswith('latest.json') and set(payload['last_runs']) == {'fast'}:
            fast_reached_publish.set()
            assert release_fast_publish.wait(5)
        return original(path, payload)

    monkeypatch.setattr(runner, 'run_checks', probe)
    monkeypatch.setattr(store, 'write_json_atomic', write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fast = pool.submit(runner.run, 'fast', str(tmp_path), False)
        assert fast_reached_publish.wait(5)
        deep = pool.submit(runner.run, 'deep', str(tmp_path), False)
        assert deep_finished_probes.wait(5)
        try:
            with store.connect(str(tmp_path), read_only=True) as conn:
                assert [row['tier'] for row in conn.execute('SELECT tier FROM runs')] == ['fast']
        finally:
            release_fast_publish.set()
        fast.result(timeout=5)
        deep.result(timeout=5)
    assert set(runner.read_snapshot(str(tmp_path))['last_runs']) == {'fast', 'deep'}



def test_snapshot_never_reports_all_clear_for_skipped_only_checks(tmp_path):
    contract = {'pages': [], 'data': []}
    with store.connect(str(tmp_path)) as conn:
        incidents.apply(conn, _result('provider:x', 'provider', 'skipped'), 'deep')
        snapshot = runner.build_snapshot(conn, contract)
    assert snapshot['families']['provider']['status'] == 'unknown'
    assert snapshot['overall'] == 'unknown'
