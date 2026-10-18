"""API logging must never put a slow output sink on the HTTP response path."""
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _isolated(source, *, timeout=10):
    result = subprocess.run(
        [sys.executable, '-c', textwrap.dedent(source)], cwd=ROOT,
        capture_output=True, text=True, timeout=timeout,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_blocked_sink_cannot_block_real_werkzeug_response_headers():
    _isolated(r'''
        import logging, socket, threading
        from flask import Flask
        from werkzeug.serving import make_server
        gate, entered = threading.Event(), threading.Event()
        class BlockedStream:
            def write(self, value):
                entered.set()
                gate.wait(8)
            def flush(self):
                pass
        root = logging.getLogger()
        root.handlers[:] = [logging.StreamHandler(BlockedStream())]
        root.setLevel(logging.INFO)
        try:
            from app.utils.api_logging import configure_async_logging
        except ImportError:
            pass  # RED control: reproduce the current synchronous handler path.
        else:
            configure_async_logging(queue_size=4)
        app = Flask('logging-isolation')
        app.add_url_rule('/healthz', view_func=lambda: {'status': 'ok'})
        server = make_server('127.0.0.1', 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        threading.Thread(target=lambda: root.warning('block sink'), daemon=True).start()
        assert entered.wait(2), 'blocked sink was not reached'
        headers = b''
        try:
            with socket.create_connection(server.server_address, timeout=1) as client:
                client.sendall(b'GET /healthz HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                try:
                    headers = client.recv(1024)
                except socket.timeout:
                    pass
        finally:
            gate.set()
            server.shutdown()
            server.server_close()
        assert b'200 OK' in headers, 'response headers waited for the logging sink'
    ''')


def test_queue_overflow_drops_without_fallback_and_process_exit_does_not_flush_blocked_sink():
    _isolated('''
        import logging, threading
        from app.utils.api_logging import configure_async_logging
        entered, forever = threading.Event(), threading.Event()
        class BlockedStream:
            def write(self, value):
                entered.set()
                forever.wait()
            def flush(self):
                forever.wait()
        sink = logging.StreamHandler(BlockedStream())
        root = logging.getLogger()
        root.handlers[:] = [sink]
        root.setLevel(logging.INFO)
        runtime = configure_async_logging(queue_size=2)
        root.warning('blocked')
        assert entered.wait(2)
        for number in range(100):
            root.warning('overflow %s', number)
        stats = runtime.snapshot()
        assert stats['capacity'] == 2
        assert stats['queued'] == 2
        assert stats['dropped'] >= 98
        assert runtime.thread.daemon
        # Interpreter shutdown must not flush or acquire the real blocked handler.
    ''', timeout=5)


def test_normal_logs_preserve_levels_formatters_filters_and_idempotent_routing():
    _isolated('''
        import io, logging, time
        from app.utils.api_logging import configure_async_logging
        stream = io.StringIO()
        sink = logging.StreamHandler(stream)
        sink.setLevel(logging.WARNING)
        sink.setFormatter(logging.Formatter('%(name)s|%(levelname)s|%(message)s'))
        sink.addFilter(lambda record: 'skip-me' not in record.getMessage())
        root = logging.getLogger()
        root.handlers[:] = [sink]
        root.setLevel(logging.DEBUG)
        custom = logging.getLogger('isolated-route')
        custom.propagate = False
        own = logging.StreamHandler(stream)
        own.setFormatter(logging.Formatter('OWN %(message)s'))
        custom.handlers[:] = [own]
        runtime = configure_async_logging(queue_size=8)
        assert configure_async_logging(queue_size=99) is runtime
        root.info('too-low')
        root.warning('skip-me')
        root.error('normal %s', 7)
        custom.warning('own-route')
        deadline = time.monotonic() + 2
        while 'own-route' not in stream.getvalue() and time.monotonic() < deadline:
            time.sleep(.01)
        assert stream.getvalue().splitlines() == ['root|ERROR|normal 7', 'OWN own-route']
        assert root.level == logging.DEBUG
        assert custom.propagate is False
    ''')


def test_queued_records_redact_synthetic_credentials_in_message_exception_and_extra():
    _isolated('''
        import io, logging, time
        from app.utils.api_logging import configure_async_logging
        captured = []
        class Capture(logging.Handler):
            def emit(self, record):
                captured.append(record)
        root = logging.getLogger()
        root.handlers[:] = [Capture()]
        configure_async_logging(queue_size=4)
        try:
            raise RuntimeError('https://api.telegram.org/bot12345:FAKE_TOKEN/sendMessage appsecret=FAKE_APPSECRET')
        except RuntimeError:
            root.exception('Authorization: Bearer FAKE_AUTH api_key=FAKE_KEY refresh_token=FAKE_REFRESH client_secret=FAKE_CLIENT secret=FAKE_SECRET',
                           extra={'context': {'api_key': 'FAKE_EXTRA', 'api_key=FAKE_FIELD_KEY': 'safe'}})
        deadline = time.monotonic() + 2
        while not captured and time.monotonic() < deadline:
            time.sleep(.01)
        assert len(captured) == 1
        record = captured[0]
        output = logging.Formatter().format(record) + str(record.context)
        assert all(secret not in output for secret in ['12345:FAKE_TOKEN', 'FAKE_AUTH', 'FAKE_KEY', 'FAKE_EXTRA', 'FAKE_APPSECRET', 'FAKE_REFRESH', 'FAKE_CLIENT', 'FAKE_SECRET', 'FAKE_FIELD_KEY'])
        assert '[REDACTED]' in output
        assert record.exc_info is None
        assert 'RuntimeError' in output
        assert '/sendMessage' in output
    ''')


def test_broken_sink_counts_error_without_standard_stderr_fallback():
    _isolated('''
        import io, logging, sys, time
        from app.utils.api_logging import configure_async_logging
        class BrokenStream:
            def write(self, value):
                raise OSError('SYNTHETIC_WRITE_FAILURE')
            def flush(self):
                pass
        errors = io.StringIO()
        sys.stderr = errors
        logging.getLogger().handlers[:] = [logging.StreamHandler(BrokenStream())]
        runtime = configure_async_logging(queue_size=4)
        logging.warning('ordinary-message')
        deadline = time.monotonic() + 2
        while runtime.queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(.01)
        assert errors.getvalue() == '', 'sink.handleError wrote synchronously to stderr'
        assert runtime.snapshot()['sink_errors'] == 1
    ''')


def test_sink_that_logs_again_does_not_recursively_fill_queue():
    _isolated('''
        import logging, threading, time
        from app.utils.api_logging import configure_async_logging
        seen = []
        class ReentrantSink(logging.Handler):
            def emit(self, record):
                seen.append(record.getMessage())
                logging.warning('sink-internal-warning')
        logging.getLogger().handlers[:] = [ReentrantSink()]
        runtime = configure_async_logging(queue_size=4)
        logging.warning('original')
        deadline = time.monotonic() + 2
        while not seen and time.monotonic() < deadline:
            time.sleep(.01)
        time.sleep(.02)
        assert seen == ['original'], 'sink reentered its own async pipeline'
        assert runtime.snapshot()['dropped'] == 1
    ''')


def test_entrypoint_preserves_factory_basicconfig_without_starting_live_workers():
    _isolated('''
        import io, logging, runpy, sys, time, types
        from flask import Flask
        import app
        from app.utils import api_logging
        stream = io.StringIO()
        logging.getLogger().handlers[:] = []
        logging.getLogger().setLevel(logging.WARNING)
        def factory():
            logging.basicConfig(level=logging.INFO, format='FACTORY %(message)s', stream=stream)
            return Flask('factory-fixture')
        app.create_app = factory
        sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)
        sys.platform = 'linux'  # No real environment loading or Windows certificate setup.
        scope = runpy.run_path('flask_app.py', run_name='entrypoint-fixture')
        logging.info('factory-policy-kept')
        deadline = time.monotonic() + 2
        while 'factory-policy-kept' not in stream.getvalue() and time.monotonic() < deadline:
            time.sleep(.01)
        assert logging.getLogger().level == logging.INFO
        assert stream.getvalue() == 'FACTORY factory-policy-kept\\n'
        assert scope['api_logging'].thread.is_alive()
    ''')


def test_adversarial_nested_numeric_extras_have_a_shared_size_budget_and_keep_metadata():
    import json
    import logging
    from app.utils.api_logging import _prepare
    record = logging.LogRecord('bounded-test', logging.WARNING, 'example.py', 25, 'ordinary', (), None)
    record.context = {
        f'child-{child}': {f'{number:03d}' + ('x' * 125): number for number in range(128)}
        for child in range(128)
    }
    prepared = _prepare(record)
    assert len(json.dumps(prepared.__dict__)) < 65536
    assert prepared.levelno == logging.WARNING
    assert prepared.name == 'bounded-test'
    assert prepared.pathname == 'example.py'
    assert prepared.lineno == 25


def test_real_os_pipe_on_stderr_cannot_hang_interpreter_final_flush():
    _isolated('''
        import logging, os, sys, threading, time
        from app.utils.api_logging import configure_async_logging
        read_fd, write_fd = os.pipe()
        pipe = os.fdopen(write_fd, 'w', buffering=1, encoding='utf-8')
        sys.stderr = pipe
        state_lock = threading.Lock()
        state = {'started': 0, 'finished': 0}
        class MarkWrite:
            def write(self, text):
                with state_lock:
                    state['started'] += 1
                result = pipe.write(text)
                with state_lock:
                    state['finished'] += 1
                return result
            def flush(self):
                return pipe.flush()
        logging.getLogger().handlers[:] = [logging.StreamHandler(MarkWrite())]
        runtime = configure_async_logging(queue_size=4)
        # Windows and Linux have different pipe capacities. Fill the real pipe
        # until a native write actually stays unfinished, instead of assuming
        # that a single (bounded/redacted) record exceeds the kernel buffer.
        blocked = False
        deadline = time.monotonic() + 3
        for number in range(128):
            logging.warning('x' * 32768)
            while time.monotonic() < deadline:
                with state_lock:
                    started, finished = state['started'], state['finished']
                if started > number:
                    break
                time.sleep(.001)
            if started <= number:
                print({'pipe_started': started, 'pipe_finished': finished, 'attempt': number}, flush=True)
                raise AssertionError('log writer did not reach the OS pipe')
            if started > finished:
                time.sleep(.05)
                with state_lock:
                    if state['started'] > state['finished']:
                        blocked = True
                        break
            assert time.monotonic() < deadline, 'pipe fill deadline exceeded'
        print({'pipe_started': state['started'], 'pipe_finished': state['finished'], 'blocked': blocked}, flush=True)
        assert blocked and runtime.queue.unfinished_tasks > 0, 'fixture did not fill the unconsumed OS pipe'
        print('main-returned', flush=True)
        # read_fd intentionally stays open and unread: interpreter must not flush pipe.
    ''', timeout=5)
