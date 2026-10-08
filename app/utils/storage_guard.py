"""Read-only disk-space checks; never create, remove, or publish artifacts."""
import errno
import os
from pathlib import Path
import shutil


DEFAULT_MIN_FREE_BYTES = 1_073_741_824
MIN_FREE_BYTES_ENV = 'MARKETFLOW_SCHEDULER_MIN_FREE_BYTES'


def check_storage(paths, *, min_free_bytes=None):
    """Check each output volume, including parents of not-yet-created paths.

    An unavailable check is distinct from measured low space and fails closed.
    Exception bodies and malformed environment values are never returned.
    """
    result = {'status': 'invalid_config', 'min_free_bytes': None, 'checks': []}
    try:
        minimum = min_free_bytes
        if minimum is None:
            minimum = int(os.environ.get(MIN_FREE_BYTES_ENV, str(DEFAULT_MIN_FREE_BYTES)))
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum <= 0:
            return result
        if not isinstance(paths, (list, tuple)) or not paths:
            return result
    except (ValueError, TypeError, OverflowError):
        return result
    result['min_free_bytes'] = minimum
    for raw_path in paths:
        try:
            path = Path(raw_path).resolve()
            while not path.exists() and path.parent != path:
                path = path.parent
            free = shutil.disk_usage(path).free
            if isinstance(free, bool) or not isinstance(free, int) or free < 0:
                raise ValueError('invalid disk usage')
            result['checks'].append({'path': str(path), 'free_bytes': free})
            if free < minimum:
                result['status'] = 'low_space'
                return result
        except Exception as exc:
            result.update(status='unavailable', error_type=type(exc).__name__)
            return result
    result['status'] = 'healthy'
    return result


def is_disk_full(error):
    """Recognize OS/SQLite disk-full codes without inspecting error messages."""
    return (getattr(error, 'errno', None) == errno.ENOSPC
            or getattr(error, 'winerror', None) in {39, 112}
            or getattr(error, 'sqlite_errorcode', None) == 13)
