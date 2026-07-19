"""Regression tests for write_json_atomic under Windows-style replace contention.

Root cause (2026-07-19): on Windows, `os.replace(tmp, dst)` raises
PermissionError [WinError 5] when `dst` is transiently held open by a concurrent
reader (the CRT default share mode lacks FILE_SHARE_DELETE). The MiroFish live
dashboard polls a run's run.json every ~1s while the background pipeline rewrites
it at each phase, so the replace collided and aborted the run around
brain_snapshot/graph_build. The fix retries the replace with a short backoff.
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from app.utils import atomic_json
from app.utils.atomic_json import write_json_atomic


def _read(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_replace_retries_through_transient_permission_error(tmp_path, monkeypatch):
    """A few transient PermissionErrors on os.replace must be retried, not fatal."""
    target = str(tmp_path / 'run.json')
    write_json_atomic(target, {'v': 0})

    real_replace = os.replace
    calls = {'n': 0}

    def flaky_replace(src, dst):
        calls['n'] += 1
        if calls['n'] <= 3:  # first 3 attempts hit the sharing violation
            raise PermissionError(5, 'Access is denied')
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_json.os, 'replace', flaky_replace)
    # Keep the test fast: no real sleeping between retries.
    monkeypatch.setattr(atomic_json.time, 'sleep', lambda _s: None)

    write_json_atomic(target, {'v': 1})

    assert calls['n'] == 4                 # 3 failures + 1 success
    assert _read(target) == {'v': 1}       # new content committed
    # No leaked temp files in the directory after a successful commit.
    assert not [p for p in os.listdir(tmp_path) if p.startswith('.tmp_')]


def test_replace_gives_up_and_raises_when_error_persists(tmp_path, monkeypatch):
    """If the destination stays locked forever, the error still surfaces (no silent loss)."""
    target = str(tmp_path / 'run.json')

    def always_denied(src, dst):
        raise PermissionError(5, 'Access is denied')

    monkeypatch.setattr(atomic_json.os, 'replace', always_denied)
    monkeypatch.setattr(atomic_json.time, 'sleep', lambda _s: None)

    with pytest.raises(PermissionError):
        write_json_atomic(target, {'v': 1})

    # The temp file is cleaned up even when every retry fails.
    assert not [p for p in os.listdir(tmp_path) if p.startswith('.tmp_')]


def test_survives_a_real_concurrent_reader(tmp_path):
    """End-to-end: a reader that briefly holds the file open must not abort the write.

    Mirrors the live dashboard poller opening run.json while the pipeline rewrites
    it. On Windows this reproduces WinError 5 without the retry fix; on POSIX it is
    a no-op that must still pass.
    """
    target = str(tmp_path / 'run.json')
    write_json_atomic(target, {'v': 0})

    stop = threading.Event()

    def poller():
        # Continuously open/read/close, like the frontend polling the run status.
        while not stop.is_set():
            try:
                with open(target, 'r', encoding='utf-8') as f:
                    f.read()
            except (OSError, ValueError):
                pass

    t = threading.Thread(target=poller, daemon=True)
    t.start()
    try:
        for i in range(1, 25):  # many phase writes, as a full pipeline would do
            write_json_atomic(target, {'v': i})
    finally:
        stop.set()
        t.join(timeout=2)

    assert _read(target) == {'v': 24}
