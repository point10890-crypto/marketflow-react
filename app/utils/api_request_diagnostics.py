"""Small local evidence ring for slow Flask requests, without request contents.

Enabled by the production entry point only. The sampler stores route patterns,
elapsed time and Python function locations; never URLs, parameters, headers,
bodies, locals or exception text. Disk I/O runs only on its daemon thread and
outside the registry lock. Three atomic slots bound retained evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time


_install_lock = threading.Lock()


class RequestDiagnostics:
    def __init__(self, directory, *, clock=time.monotonic, frames=sys._current_frames):
        self.directory = Path(directory)
        self.clock = clock
        self.frames = frames
        self._lock = threading.Lock()
        self._active = {}
        self._next = 0
        self._slot = 0
        self._last_sample = float('-inf')
        self._stop = threading.Event()
        self.thread = None
        self.untracked = 0
        self.write_errors = 0

    def begin(self, thread_id, route):
        with self._lock:
            if len(self._active) >= 16:
                self.untracked += 1
                return None
            self._next += 1
            self._active[self._next] = (self.clock(), thread_id, route[:256])
            return self._next

    def finish(self, token):
        with self._lock:
            self._active.pop(token, None)

    def snapshot(self):
        with self._lock:
            return {'active': len(self._active), 'untracked': self.untracked, 'write_errors': self.write_errors}

    def sample(self):
        now = self.clock()
        with self._lock:
            if now - self._last_sample < 5:
                return False
            slow = [(started, thread_id, route) for started, thread_id, route
                    in self._active.values() if now - started >= 5]
            if not slow:
                return False
            self._last_sample = now
        try:
            frames = self.frames()
            requests = []
            for started, thread_id, route in slow:
                stack = []
                frame = frames.get(thread_id)
                for _ in range(12):
                    if frame is None:
                        break
                    stack.append({
                        'file': os.path.basename(frame.f_code.co_filename)[:128],
                        'function': frame.f_code.co_name[:128], 'line': frame.f_lineno,
                    })
                    frame = frame.f_back
                requests.append({
                    'route': route, 'thread_id': thread_id,
                    'elapsed_s': round(now - started, 3), 'frames': stack,
                })
            self._write_snapshot({
                'schema_version': 1, 'pid': os.getpid(),
                'captured_at': datetime.now(timezone.utc).isoformat(), 'requests': requests,
            })
            return True
        except Exception:
            # Diagnostics must not recurse into a blocked logger or fail HTTP.
            self.write_errors += 1
            return False

    def _write_snapshot(self, snapshot):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f'slow-requests-{self._slot}.json'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             prefix='.slow-requests-', suffix='.tmp', delete=False) as output:
                temporary = output.name
                json.dump(snapshot, output, ensure_ascii=True, separators=(',', ':'))
            os.replace(temporary, path)
            self._slot = (self._slot + 1) % 3
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='api-request-diagnostics', daemon=True)
            self.thread.start()

    def _run(self):
        while not self._stop.wait(5):
            self.sample()

    def stop(self):
        self._stop.set()  # Never join or wait on a potentially unavailable disk.


def install_request_diagnostics(app, directory, *, clock=time.monotonic, start_worker=True):
    """Install once per app before serving; test factories do not enable it implicitly."""
    from flask import g, request

    with _install_lock:
        existing = app.extensions.get('api_request_diagnostics')
        if existing is not None:
            return existing
        monitor = RequestDiagnostics(directory, clock=clock)

        def begin_request():
            rule = request.url_rule.rule if request.url_rule is not None else '<unmatched>'
            g._api_diagnostics_token = monitor.begin(threading.get_ident(), rule)

        def finish_request(error=None):
            monitor.finish(getattr(g, '_api_diagnostics_token', None))

        # Run before authorization/rate-limit hooks too: they can be the slow path.
        app.before_request_funcs.setdefault(None, []).insert(0, begin_request)
        # Teardown follows every after_request hook (compression/cache/CORS),
        # and also runs on unhandled exceptions. Cleaning up in after_request
        # would hide stalls in older hooks because Flask invokes them in reverse.
        app.teardown_request(finish_request)
        app.extensions['api_request_diagnostics'] = monitor
        if start_worker:
            monitor.start()
        return monitor
