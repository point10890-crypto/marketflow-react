"""JSON file cache with mtime-aware memory caching.

Use this when a route reads a scheduler-produced JSON file on every request.
Avoids repeated disk I/O when the file has not changed.

Usage:
    from app.utils.json_cache import load_json_cached

    data = load_json_cached('/path/to/file.json', ttl=300)
    # returns parsed dict/list or None on error (missing file, bad json)

Cache semantics:
    - Keyed by absolute path.
    - Returns cached value if (now - last_check) < ttl.
    - On TTL expiry, re-stat the file; if mtime unchanged, just refresh
      the check timestamp (no re-read). If mtime changed, re-read.
    - Thread-safe via a single lock (routes are I/O-bound; contention is fine).

IMPORTANT — mutation safety:
    The returned object is the SHARED cached instance. Do NOT mutate it.
    If your handler needs to enrich or modify the data, use copy.deepcopy
    before mutating, otherwise subsequent requests will see the poisoned
    version until the TTL expires or the file mtime changes.
"""

import json
import os
import threading
import time
from typing import Any, Optional

_cache: dict[str, tuple[float, float, Any]] = {}
# key -> (last_check_ts, file_mtime, parsed_data)
_lock = threading.Lock()


def load_json_cached(filepath: str, ttl: int = 300) -> Optional[Any]:
    """Load a JSON file with an mtime-aware memory cache.

    Args:
        filepath: Absolute path to a JSON file.
        ttl: Seconds to trust the cached value without re-statting the file.

    Returns:
        Parsed JSON (dict/list), or None if the file is missing or unreadable.
    """
    abs_path = os.path.abspath(filepath)
    now = time.time()

    with _lock:
        entry = _cache.get(abs_path)
        if entry is not None:
            last_check, cached_mtime, data = entry
            if now - last_check < ttl:
                return data

    # TTL expired (or first load) — re-stat outside the lock.
    try:
        stat = os.stat(abs_path)
    except FileNotFoundError:
        with _lock:
            _cache.pop(abs_path, None)
        return None
    except OSError:
        return None

    with _lock:
        entry = _cache.get(abs_path)
        if entry is not None and entry[1] == stat.st_mtime:
            # File unchanged — just refresh the check timestamp, skip re-read.
            _cache[abs_path] = (now, entry[1], entry[2])
            return entry[2]

    # mtime changed or first load — read from disk.
    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    with _lock:
        _cache[abs_path] = (now, stat.st_mtime, data)
    return data


def invalidate(filepath: Optional[str] = None) -> None:
    """Drop one path from the cache, or clear everything if filepath is None."""
    with _lock:
        if filepath is None:
            _cache.clear()
        else:
            _cache.pop(os.path.abspath(filepath), None)
