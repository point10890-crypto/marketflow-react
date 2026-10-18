"""Health deadlines use loopback sockets and isolated children, never production."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'scripts' / 'health_probe.py'
SUPERVISOR = ROOT / 'scripts' / 'health_probe.ps1'
PS51 = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')


@pytest.fixture
def endpoint():
    servers = []

    def start(mode='ok'):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(8)
        stop = threading.Event()

        def serve():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(4)
                    connection.recv(4096)
                    if mode == 'headers_stall':
                        stop.wait(8)
                    elif mode in ('body_stall', 'trickle'):
                        connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\nx')
                        while not stop.wait(0.15):
                            if mode == 'trickle':
                                connection.sendall(b'x')
                    elif mode == 'large':
                        body = b'x' * 8192
                        connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 8192\r\nConnection: close\r\n\r\n' + body)
                    else:
                        status = b'200 OK' if mode == 'ok' else b'503 Unavailable'
                        connection.sendall(b'HTTP/1.1 ' + status + b'\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}')
            except (OSError, TimeoutError):
                pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        servers.append((listener, stop, thread))
        return f'http://127.0.0.1:{listener.getsockname()[1]}/healthz'

    yield start
    for listener, stop, thread in servers:
        stop.set()
        listener.close()
        thread.join(timeout=2)


def run_cli(url, timeout=0.5):
    assert PROBE.exists(), 'bounded health probe is missing'
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(PROBE), '--url', url, '--timeout', str(timeout)],
                            capture_output=True, text=True, timeout=4)
    return result, time.monotonic() - started


@pytest.mark.parametrize('mode', ['headers_stall', 'body_stall', 'trickle'])
def test_probe_has_total_deadline_even_when_individual_reads_keep_progressing(endpoint, mode):
    result, elapsed = run_cli(endpoint(mode))
    assert result.returncode != 0
    assert elapsed < 2.5


@pytest.mark.parametrize('mode,healthy,reason', [('ok', True, 'healthy'), ('unavailable', False, 'http_status'), ('large', False, 'response_too_large')])
def test_probe_requires_successful_bounded_response(endpoint, mode, healthy, reason):
    result, _ = run_cli(endpoint(mode), timeout=2)
    body = json.loads(result.stdout)
    assert body['healthy'] is healthy
    assert body['reason'] == reason
    assert (result.returncode == 0) is healthy
    assert result.stderr == ''


def test_probe_preserves_requests_tls_verification_and_redacts_transport_errors(monkeypatch):
    assert PROBE.exists(), 'bounded health probe is missing'
    spec = importlib.util.spec_from_file_location('watchdog_probe_test', PROBE)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    options = []

    def reject(url, **kwargs):
        options.append(kwargs)
        raise probe.requests.exceptions.SSLError('private transport detail /botPRIVATE/sendMessage')

    monkeypatch.setattr(probe.requests, 'get', reject)
    result = probe.check_health('https://example.invalid/healthz', 1)
    assert options[0].get('verify', True) is True
    assert result['healthy'] is False and result['reason'] == 'tls_error'
    assert 'private' not in json.dumps(result)
    assert 'PRIVATE' not in json.dumps(result)


def ps_json(script):
    assert PS51.exists(), 'Windows PowerShell 5.1 is required'
    result = subprocess.run([str(PS51), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr[:300]
    return json.loads(result.stdout)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(not PS51.exists(), reason='Windows PowerShell 5.1 runtime')
@pytest.mark.parametrize('mode', ['headers_stall', 'body_stall', 'trickle', 'ok'])
def test_ps51_supervisor_bounds_whole_request_and_reaps_exact_child(endpoint, mode):
    assert SUPERVISOR.exists(), 'wallclock probe supervisor is missing'
    budget = 3 if mode == 'ok' else 1
    body = ps_json(f"""
        . {quote(SUPERVISOR)}
        $r = Invoke-BoundedHealthProbe -Uri {quote(endpoint(mode))} -TimeoutSeconds {budget} -PythonPath {quote(sys.executable)}
        $r | Add-Member -NotePropertyName child_alive -NotePropertyValue ([bool](Get-Process -Id $r.child_pid -ErrorAction SilentlyContinue))
        $r | ConvertTo-Json -Compress
    """)
    assert body['healthy'] is (mode == 'ok')
    assert body['elapsed_ms'] < budget * 1000 + 1600
    assert body['child_alive'] is False


@pytest.mark.skipif(not PS51.exists(), reason='Windows PowerShell 5.1 runtime')
def test_supervisor_kills_hung_or_lying_child_without_stopping_other_process(tmp_path):
    assert SUPERVISOR.exists(), 'wallclock probe supervisor is missing'
    fake = tmp_path / 'stalled_probe.py'
    worker_pid = tmp_path / 'actual_worker.pid'
    worker_code = f'import os,pathlib,time;pathlib.Path({str(worker_pid)!r}).write_text(str(os.getpid()));time.sleep(30)'
    # Model the MiniPC venv forwarding launcher, including a child that hangs
    # before importing the real probe or starting its own deadline timer.
    fake.write_text('import subprocess,sys\n'
                    f'child=subprocess.Popen([sys.executable,"-c",{worker_code!r}])\n'
                    'print(\'{"healthy":true,"status":200,"reason":"healthy"}\',flush=True)\nchild.wait()\n', encoding='utf-8')
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        body = ps_json(f"""
            . {quote(SUPERVISOR)}
            $r = Invoke-BoundedHealthProbe -Uri 'http://127.0.0.1:1/healthz' -TimeoutSeconds 1.5 -PythonPath {quote(sys.executable)} -ProbeScript {quote(fake)}
            $r | Add-Member -NotePropertyName child_alive -NotePropertyValue ([bool](Get-Process -Id $r.child_pid -ErrorAction SilentlyContinue))
            $r | ConvertTo-Json -Compress
        """)
        assert body['healthy'] is False and body['reason'] == 'deadline_exceeded'
        assert body['elapsed_ms'] < 3500
        assert body['child_alive'] is False
        assert worker_pid.exists()
        actual_pid = int(worker_pid.read_text())
        actual_alive = ps_json(f"[bool](Get-Process -Id {actual_pid} -ErrorAction SilentlyContinue) | ConvertTo-Json")
        assert actual_alive is False, 'venv forwarding worker survived supervisor cleanup'
        assert unrelated.poll() is None
    finally:
        if worker_pid.exists():
            subprocess.run(['taskkill.exe', '/PID', worker_pid.read_text().strip(), '/T', '/F'], capture_output=True, timeout=3)
        unrelated.kill()
        unrelated.wait(timeout=3)
