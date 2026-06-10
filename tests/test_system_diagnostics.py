import json
import os
import time
from datetime import datetime, timedelta

from app.utils import diagnostics


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {'ok': True}
        self.elapsed = timedelta(milliseconds=7)

    def json(self):
        return self._payload

    def __bool__(self):
        return self.status_code < 400


def test_endpoint_diagnostics_treats_pro_gate_as_liveness_ok(monkeypatch):
    def fake_get(url, timeout):
        if url.endswith('/api/health'):
            return _FakeResponse(200, {'status': 'ok'})
        return _FakeResponse(401, {'error': 'Authentication required'})

    import requests

    monkeypatch.setattr(requests, 'get', fake_get)

    result = diagnostics._check_endpoints(port=5001)

    assert result['status'] == 'OK'
    protected = [item for item in result['details'] if item['endpoint'] != '/api/health']
    assert protected
    assert all(item['http_code'] == 401 for item in protected)
    assert all(item['note'] == 'protected_endpoint_auth_gate' for item in protected)


def test_endpoint_diagnostics_still_flags_real_route_failures(monkeypatch):
    def fake_get(url, timeout):
        if url.endswith('/api/health'):
            return _FakeResponse(200, {'status': 'ok'})
        return _FakeResponse(404, {'error': 'not found'})

    import requests

    monkeypatch.setattr(requests, 'get', fake_get)

    result = diagnostics._check_endpoints(port=5001)

    assert result['status'] == 'CRITICAL'
    assert any(item['http_code'] == 404 for item in result['details'])


def test_scheduler_diagnostics_accepts_external_daemon(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    log_dir = tmp_path / 'logs'
    data_dir.mkdir()
    log_dir.mkdir()
    pid = 1234
    (data_dir / 'scheduler_heartbeat.json').write_text(
        json.dumps({'pid': pid, 'ts': datetime.now().isoformat(timespec='seconds')}),
        encoding='utf-8',
    )
    (log_dir / 'scheduler.pid').write_text(str(pid), encoding='utf-8')

    import app.utils.scheduler as cloud_scheduler

    monkeypatch.setattr(cloud_scheduler, 'get_scheduler_status', lambda: {
        'running': False,
        'jobs_count': 0,
        'environment': 'local',
    })
    monkeypatch.setattr(diagnostics, '_BASE_DIR', str(tmp_path))
    monkeypatch.setattr(diagnostics, '_DATA_DIR', str(data_dir))
    monkeypatch.setattr(diagnostics, '_is_pid_alive', lambda value: int(value or 0) == pid)
    monkeypatch.setattr(diagnostics, '_scheduler_daemon_processes', lambda: [pid])

    result = diagnostics._check_scheduler()

    assert result['status'] == 'OK'
    assert result['details']['running'] is True
    assert result['details']['mode'] == 'external_daemon'
    assert result['details']['external']['heartbeat_pid'] == pid


def test_scheduler_diagnostics_warns_on_duplicate_external_daemons(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    log_dir = tmp_path / 'logs'
    data_dir.mkdir()
    log_dir.mkdir()
    pid = 1234
    (data_dir / 'scheduler_heartbeat.json').write_text(
        json.dumps({'pid': pid, 'ts': datetime.now().isoformat(timespec='seconds')}),
        encoding='utf-8',
    )
    (log_dir / 'scheduler.pid').write_text(str(pid), encoding='utf-8')

    import app.utils.scheduler as cloud_scheduler

    monkeypatch.setattr(cloud_scheduler, 'get_scheduler_status', lambda: {
        'running': False,
        'jobs_count': 0,
        'environment': 'local',
    })
    monkeypatch.setattr(diagnostics, '_BASE_DIR', str(tmp_path))
    monkeypatch.setattr(diagnostics, '_DATA_DIR', str(data_dir))
    monkeypatch.setattr(diagnostics, '_is_pid_alive', lambda value: int(value or 0) == pid)
    monkeypatch.setattr(diagnostics, '_scheduler_daemon_processes', lambda: [pid, 5678])

    result = diagnostics._check_scheduler()

    assert result['status'] == 'WARNING'
    assert result['details']['external']['duplicate_processes'] == 1


def test_crypto_overview_stale_is_warning_because_live_endpoint_refreshes(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    crypto_dir = tmp_path / 'crypto'
    data_dir.mkdir()
    crypto_dir.mkdir()
    for filename in [
        'overview_snapshot.json',
        'market_gate.json',
        'crypto_briefing.json',
        'btc_prediction.json',
        'crypto_risk.json',
    ]:
        (crypto_dir / filename).write_text('{}', encoding='utf-8')

    stale = time.time() - (12 * 3600)
    os.utime(crypto_dir / 'overview_snapshot.json', (stale, stale))

    monkeypatch.setenv('RENDER', '1')
    monkeypatch.setattr(diagnostics, '_BASE_DIR', str(tmp_path))
    monkeypatch.setattr(diagnostics, '_DATA_DIR', str(data_dir))
    monkeypatch.setattr(diagnostics, '_CRYPTO_OUTPUT', str(crypto_dir))

    result = diagnostics._check_data_freshness()
    details = {item['name']: item for item in result['details']}

    assert details['crypto_overview']['status'] == 'WARNING'
    assert details['crypto_overview']['note'] == 'live_endpoint_refreshes_on_demand'
    assert details['crypto_market_gate']['status'] == 'OK'
    assert result['status'] == 'WARNING'
