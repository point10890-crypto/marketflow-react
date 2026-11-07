import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.control_center import http_checks


@pytest.mark.parametrize('length,body', [(True, b'{"status":"ok"}'), (False, b'{"status":"ok"}')])
def test_complete_json_connection_close_is_not_unknown(monkeypatch, length, body):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Connection', 'close')
            if length:
                self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(http_checks, 'allowed_http_url', lambda *a, **k: True)
    try:
        result = http_checks.probe_contract(
            f'http://127.0.0.1:{server.server_port}',
            {'path': '/api/health', 'auth': 'public', 'expect_keys': ['status']}, None)
        assert result.status == 'ok', result
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
