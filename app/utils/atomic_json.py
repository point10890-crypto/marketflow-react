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
from typing import Any

# Re-export for convenience
__all__ = ['write_json_atomic']


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
        # Atomic on POSIX and NTFS (Python 3.3+).
        os.replace(tmp_path, abs_path)
    except Exception:
        # Clean up the temp file if anything went wrong before the rename.
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise
