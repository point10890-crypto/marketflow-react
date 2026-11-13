"""One read-only scanner snapshot worker, isolated from decision request latency."""
from copy import deepcopy
import os
import threading
from time import monotonic

from . import alpha_scanner


class SnapshotPending(RuntimeError):
    def __init__(self):
        super().__init__('scanner_snapshot_pending')


class SnapshotUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('scanner_snapshot_unavailable')


_TTL_SECONDS = 30
_lock = threading.Lock()
_worker = None
_root = None
_generation = 0
_completed_at = None
_snapshot = None
_failed = False


def _root_identity():
    # Path normalization does not inspect the archive or acquire its scan lock.
    return os.path.normcase(os.path.abspath(os.fspath(alpha_scanner.SCANNER_RUNS_ROOT)))


def _refresh(root, generation, reader):
    global _worker, _completed_at, _snapshot, _failed
    value, failed = None, True
    try:
        value = reader(limit=20)
        if value is not None and (not isinstance(value, dict)
                or not isinstance(value.get('candidates'), list)
                or len(value['candidates']) > 20):
            raise ValueError('invalid_scanner_snapshot')
        value = deepcopy(value)
        failed = False
    except Exception:
        # No paths, source payloads or exception details cross this boundary.
        pass
    finally:
        with _lock:
            if root == _root == _root_identity() and generation == _generation:
                _snapshot, _failed, _completed_at = value if not failed else None, failed, monotonic()
            _worker = None


def read_snapshot():
    """Read a fresh compact result or raise immediately while one worker loads it.

    Successful None is a completed empty snapshot. Expiry and root changes hide
    old results until refreshed; their original generated_at is never rewritten.
    Only this short in-memory lock is used on the request thread, never the
    scanner directory lock. A blocked worker cannot cause extra worker growth.
    """
    global _root, _generation, _completed_at, _snapshot, _failed, _worker
    root = _root_identity()
    with _lock:
        if root != _root:
            _root, _generation = root, _generation + 1
            _snapshot, _completed_at, _failed = None, None, False
        if _completed_at is not None and monotonic() - _completed_at < _TTL_SECONDS:
            if _failed:
                raise SnapshotUnavailable()
            return deepcopy(_snapshot)
        if _worker is None:
            _worker = threading.Thread(target=_refresh,
                args=(root, _generation, alpha_scanner.read_latest_scanner_candidates),
                name='decision-scanner-snapshot', daemon=True)
            try:
                _worker.start()
            except Exception:
                _worker, _snapshot, _failed, _completed_at = None, None, True, monotonic()
                raise SnapshotUnavailable() from None
        raise SnapshotPending()
