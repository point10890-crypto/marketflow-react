"""Bound HTTP latency independently of SQLite VM callbacks or blocked file I/O.

Builders run in daemon threads without Flask contexts. A blocked builder keeps
its slot and key until it actually exits: timeouts never spawn replacements.
There is no job queue, and inactive keys alone may be evicted at capacity.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable


class ProjectionUnavailable(RuntimeError):
    """A completed builder returned unavailable or incomplete source data."""


@dataclass(frozen=True)
class ProjectionRead:
    payload: dict[str, Any] | None
    metadata: dict[str, Any]


@dataclass
class _Entry:
    payload: dict[str, Any] | None = None
    completed_at: float | None = None
    cached_at: str | None = None
    last_attempt_at: str | None = None
    last_error: str | None = None
    retry_at: float = 0.0
    event: threading.Event | None = None


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class BoundedProjectionCache:
    def __init__(
        self, *, ttl_seconds: float = 5.0, wait_seconds: float = 0.15,
        retry_seconds: float = 5.0, max_workers: int = 3, max_keys: int = 16,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._wait = wait_seconds
        self._retry = retry_seconds
        self._max_workers = max_workers
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._active = 0

    def read(self, key: str, builder: Callable[[], dict[str, Any]]) -> ProjectionRead:
        worker = None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self._max_keys:
                    idle_key = next((k for k, e in self._entries.items() if e.event is None), None)
                    if idle_key is None:
                        return self._snapshot(_Entry(last_error='projection_capacity'))
                    del self._entries[idle_key]
                entry = _Entry()
                self._entries[key] = entry
            self._entries.move_to_end(key)
            now = self._clock()
            expired = entry.completed_at is None or now - entry.completed_at >= self._ttl
            if expired and entry.event is None and now >= entry.retry_at:
                if self._active < self._max_workers:
                    entry.event = threading.Event()
                    entry.last_attempt_at = _timestamp()
                    self._active += 1
                    worker = threading.Thread(
                        target=self._build, args=(entry, builder),
                        name='claw-http-projection', daemon=True,
                    )
                elif entry.payload is None:
                    entry.last_error = 'projection_capacity'
            event = entry.event
            cold = entry.payload is None

        # Starting/waiting and all builder I/O happen outside the cache lock.
        if worker is not None:
            try:
                worker.start()
            except Exception as exc:  # Thread allocation failures must release capacity.
                self._finish(entry, None, type(exc).__name__)
        if cold and event is not None:
            event.wait(self._wait)
        with self._lock:
            result = self._snapshot(entry)
        # Each response owns a copy; refresh metadata never mutates source data.
        return ProjectionRead(deepcopy(result.payload), result.metadata)

    def _build(self, entry: _Entry, builder: Callable[[], dict[str, Any]]) -> None:
        try:
            payload = builder()
            if not isinstance(payload, dict):
                raise ProjectionUnavailable()
            payload = deepcopy(payload)
        except Exception as exc:  # No exception text/path/credentials reach HTTP metadata.
            self._finish(entry, None, type(exc).__name__)
        else:
            self._finish(entry, payload, None)

    def _finish(self, entry: _Entry, payload: dict[str, Any] | None, error: str | None) -> None:
        with self._lock:
            now = self._clock()
            if payload is not None:
                entry.payload = payload
                entry.completed_at = now
                entry.cached_at = _timestamp()
            entry.last_error = error
            entry.retry_at = now + self._retry if error else now
            event, entry.event = entry.event, None
            self._active -= 1
            if event is not None:
                event.set()

    def _snapshot(self, entry: _Entry) -> ProjectionRead:
        age = None if entry.completed_at is None else max(0.0, self._clock() - entry.completed_at)
        stale = age is None or age >= self._ttl or entry.last_error is not None
        refreshing = entry.event is not None
        state = ('stale' if stale else 'fresh') if entry.payload is not None else (
            'warming' if refreshing else 'unavailable'
        )
        return ProjectionRead(entry.payload, {
            'state': state, 'stale': stale, 'refreshing': refreshing,
            'cached_at': entry.cached_at, 'age_seconds': round(age, 3) if age is not None else None,
            'last_attempt_at': entry.last_attempt_at, 'last_error': entry.last_error,
            'retry_after_seconds': max(1, int(self._retry)),
        })
