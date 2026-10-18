"""Bounded, nonblocking logging for the API process.

Werkzeug logs the request *before* writing response headers. A synchronous
StreamHandler can therefore stop otherwise healthy requests when its pipe or
file blocks. Only the daemon below may touch output handlers. Saturation drops
records (counted in snapshot()); it must never fall back to stderr.
"""
from __future__ import annotations

import copy
import atexit
import itertools
import logging
import queue
import re
import sys
import threading


_REDACTED = '[REDACTED]'
_MAX_TEXT = 8192
_SECRET_FIELD = re.compile(r'(?:authorization|api[_-]?key|secret|password|(?:access|bot|refresh)[_-]?token)', re.I)
_SECRET_VALUES = (
    re.compile(r'(/bot)[^/\s\'"?]+', re.I),
    re.compile(r'(authorization[\s\'"]*[:=]\s*[\'"]?)(?:Bearer\s+|Basic\s+)?[^,\s\'"}]+', re.I),
    re.compile(r'([\w-]{0,64}(?:api[_-]?key|secret|password|(?:access|bot|refresh)[_-]?token)[\w-]{0,64}[\'\"]?\s*[:=]\s*[\'\"]?)[^,\s\'\"}]+', re.I),
    re.compile(r'(Bearer\s+)[A-Za-z0-9._~+/=\-]+', re.I),
)
_runtime = None
_configure_lock = threading.Lock()


class _ShutdownStream:
    """Finalization-only stream: never flush an abandoned, blocked OS pipe."""
    encoding = 'utf-8'
    errors = 'replace'

    def write(self, value):
        return len(value)

    def flush(self):
        pass

    def isatty(self):
        return False


def _isolate_standard_stream_finalization(runtime):
    # CPython independently flushes sys.stdout/stderr after atexit. Removing
    # handlers from logging.shutdown is not enough when a real stderr pipe is
    # blocked. Keep old streams alive in the daemon's runtime (so replacement
    # cannot trigger their destructors), and explicitly sacrifice final buffered
    # lines instead of making service process exit wait for a stuck pipe.
    runtime.retired_streams = (sys.stdout, sys.stderr)
    sys.stdout = sys.stderr = _ShutdownStream()


def _redact_text(value: str) -> str:
    # Scrub before truncation, so a truncation boundary cannot expose a prefix.
    value = value[:65536]
    for pattern in _SECRET_VALUES:
        value = pattern.sub(lambda match: match.group(1) + _REDACTED, value)
    return value[:_MAX_TEXT]


def _redact_value(value, budget, depth=0):
    if budget['items'] <= 0 or budget['chars'] <= 0:
        return None
    budget['items'] -= 1  # Includes primitive leaves, not just containers/strings.
    if isinstance(value, str):
        text = _redact_text(value)[:budget['chars']]
        budget['chars'] -= len(text)
        return text
    if depth >= 5:
        return None
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if budget['items'] <= 0 or budget['chars'] <= 0:
                break
            key = str(key)[:128]
            safe_key = _redact_text(key)[:budget['chars']]
            budget['chars'] -= len(safe_key)
            result[safe_key] = _redact_value(_REDACTED if _SECRET_FIELD.search(key) else item, budget, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if budget['items'] <= 0 or budget['chars'] <= 0:
                break
            result.append(_redact_value(item, budget, depth + 1))
        return result
    if value is None or isinstance(value, (float, bool)):
        return value
    if isinstance(value, int):
        return value if value.bit_length() <= 64 else None
    return _redact_value(str(value), budget, depth + 1)


def _prepare(record):
    prepared = copy.copy(record)
    # Keep the small mandatory metadata independent of untrusted payload budget:
    # oversized extras must never turn levelno/created/etc. into an invalid type.
    metadata = ('name', 'levelno', 'levelname', 'pathname', 'filename', 'module',
                'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                'thread', 'threadName', 'processName', 'process', 'taskName')
    fields = {}
    for key in metadata:
        value = getattr(record, key, None)
        fields[key] = _redact_text(value)[:256] if isinstance(value, str) else value
    # All message/exception/extra nodes and key characters share one small budget.
    budget = {'chars': _MAX_TEXT, 'items': 128}
    fields.update(msg=_redact_value(record.getMessage(), budget), args=None, exc_info=None,
                  exc_text=None, stack_info=None)
    if record.exc_info:
        fields['exc_text'] = _redact_value(logging.Formatter().formatException(record.exc_info), budget)
    elif record.exc_text:
        fields['exc_text'] = _redact_value(record.exc_text, budget)
    if record.stack_info:
        fields['stack_info'] = _redact_value(record.stack_info, budget)
    # Do not retain traceback frames, arbitrary objects or unlimited extra keys.
    for key, value in itertools.islice(record.__dict__.items(), 64):
        if key not in fields:
            if budget['items'] <= 0 or budget['chars'] <= 0:
                break
            safe_key = _redact_text(key[:128])[:budget['chars']]
            budget['chars'] -= len(safe_key)
            fields[safe_key] = _redact_value(_REDACTED if _SECRET_FIELD.search(key) else value, budget)
    prepared.__dict__ = fields
    return prepared


def _detach_shutdown_flush(sink):
    # logging.shutdown() otherwise flushes retired real handlers synchronously,
    # which can hang process exit on the very same stopped pipe. These handlers
    # are owned by the daemon until OS process cleanup; the queue wrappers have
    # no-op flush/close. Isolate this stdlib-private compatibility boundary here.
    # _acquireLock/_releaseLock were removed in Python 3.13; the shared RLock
    # itself is present on every supported version (3.11+).
    with logging._lock:
        logging._handlerList[:] = [ref for ref in logging._handlerList if ref() is not sink]


class _QueueHandler(logging.Handler):
    def __init__(self, runtime, sink):
        super().__init__(sink.level)
        self.runtime = runtime
        self.sink = sink

    def createLock(self):
        self.lock = None  # queue.put_nowait is already thread safe; never acquire a sink lock.

    def handle(self, record):
        # Python 3.13's base Handler.handle uses ``with self.lock`` even when a
        # handler deliberately has no lock. Keep queue dispatch lock-free on
        # all supported versions, including filter record replacement (3.12+).
        accepted = self.filter(record)
        if isinstance(accepted, logging.LogRecord):
            record = accepted
        if accepted:
            self.emit(record)
        return accepted

    def emit(self, record):
        if threading.current_thread() is self.runtime.thread:
            # A custom sink/filter may itself log; do not feed its own writer.
            self.runtime.dropped += 1
            return
        try:
            prepared = _prepare(record)
            self.runtime.queue.put_nowait((self.sink, prepared))
        except Exception:
            # Includes queue.Full and bad __str__/formatting. Do not invoke the
            # standard Handler.handleError(), which writes to stderr itself.
            self.runtime.dropped += 1


class AsyncLoggingRuntime:
    def __init__(self, capacity):
        self.queue = queue.Queue(maxsize=capacity)
        self.dropped = 0
        self.sink_errors = 0
        self.retired_streams = ()
        self.thread = threading.Thread(target=self._listen, name='api-log-writer', daemon=True)
        self.thread.start()
        atexit.register(_isolate_standard_stream_finalization, self)

    def _listen(self):
        while True:
            sink, record = self.queue.get()
            try:
                sink.handle(record)  # Preserve the sink formatter, filters and routing.
            except Exception:
                self.sink_errors += 1
            finally:
                self.queue.task_done()

    def handle_sink_error(self, record):
        # StreamHandler.emit catches I/O errors itself and normally prints a
        # second, potentially secret-bearing traceback synchronously to stderr.
        # Captured handlers use this counter-only error policy instead.
        self.sink_errors += 1

    def snapshot(self):
        """Safe counters for diagnostics, without logging or reading the sink."""
        return {
            'capacity': self.queue.maxsize, 'queued': self.queue.qsize(),
            'dropped': self.dropped, 'sink_errors': self.sink_errors,
        }


def configure_async_logging(*, queue_size=1024):
    """Wrap existing logger outputs; repeat after factory setup to absorb new handlers.

    Logger levels, propagation and sink filtering/formatting remain unchanged.
    This is called only by flask_app.py; importing app or constructing test apps
    does not alter their logging or start this worker.
    """
    global _runtime
    with _configure_lock:
        if _runtime is None:
            if queue_size < 1:
                raise ValueError('queue_size must be positive')
            _runtime = AsyncLoggingRuntime(queue_size)
        root = logging.getLogger()
        if not root.handlers:
            root.addHandler(logging.StreamHandler())
        loggers = [root] + [
            logger for logger in list(logging.Logger.manager.loggerDict.values())
            if isinstance(logger, logging.Logger)
        ]
        for logger in loggers:
            for sink in list(logger.handlers):
                if isinstance(sink, _QueueHandler):
                    continue
                sink.handleError = _runtime.handle_sink_error
                wrapper = _QueueHandler(_runtime, sink)
                logger.handlers[logger.handlers.index(sink)] = wrapper
                _detach_shutdown_flush(sink)
        return _runtime
