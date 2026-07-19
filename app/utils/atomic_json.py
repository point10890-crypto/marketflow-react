"""Atomic JSON file writes — crash-safe scheduler/worker/Flask outputs.

Problem:
    `open(path, 'w')` + `json.dump()` leaves a truncated file on crash,
    OOM, SIGKILL, or concurrent write. Any reader during the window sees
    corrupt JSON. Symptoms are rare, hard to reproduce, and easy to blame
    on the pipeline.

Solution:
    Write to a temp file in the same directory, fsync, then rename.
    `os.replace()` is atomic on both POSIX and Windows (NTFS).
    Reader either sees the old file or the new one — never a half-written
    one.

Usage:
    from app.utils.atomic_json import write_json_atomic

    write_json_atomic('/path/to/state.json', {'key': 'value'})

Combine with `app.utils.file_lock.safe_write` if you also need
multi-writer exclusion. Atomicity alone handles single-writer crash
safety.
"""

import json
import os
import tempfile
import time
from typing import Any

# Re-export for convenience
__all__ = ['write_json_atomic']

# Windows: os.replace(tmp, dst) raises PermissionError [WinError 5/32] when dst is
# transiently held open by a concurrent reader — the CRT default share mode lacks
# FILE_SHARE_DELETE. Readers (e.g. the live dashboard polling a run.json) open →
# read → close in milliseconds, so a short bounded retry almost always lands in a
# free window. On POSIX this branch never triggers (open files rename fine), so
# the retry is a harmless no-op there.
_REPLACE_MAX_ATTEMPTS = 10
_REPLACE_BACKOFF_STEP = 0.05  # seconds; escalates per attempt, ~2.25s worst case


def _replace_with_retry(src: str, dst: str) -> None:
    for attempt in range(_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_MAX_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_STEP * (attempt + 1))


def write_json_atomic(
    filepath: str,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> None:
    """Write `data` as JSON to `filepath` atomically.

    Raises:
        OSError: disk full, permission denied, or rename failure.
        TypeError: data is not JSON-serializable.
    """
    abs_path = os.path.abspath(filepath)
    directory = os.path.dirname(abs_path) or '.'
    os.makedirs(directory, exist_ok=True)

    # NamedTemporaryFile in the same dir so os.replace stays on one volume
    # (cross-device rename would fail on Windows).
    fd, tmp_path = tempfile.mkstemp(
        prefix='.tmp_', suffix='.json', dir=directory
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(
                data,
                f,
                indent=indent,
                ensure_ascii=ensure_ascii,
                sort_keys=sort_keys,
            )
            f.flush()
            os.fsync(f.fileno())
        # Atomic on POSIX and NTFS (Python 3.3+). Retried on Windows because a
        # concurrent reader holding `abs_path` open makes the replace fail with
        # PermissionError until the reader's handle closes.
        _replace_with_retry(tmp_path, abs_path)
    except Exception:
        # Clean up the temp file if anything went wrong before the rename.
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise
