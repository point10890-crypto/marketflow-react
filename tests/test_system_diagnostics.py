from datetime import timedelta

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
