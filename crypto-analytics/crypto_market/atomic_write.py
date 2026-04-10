"""Atomic JSON file writes for crypto-analytics package.

Thin wrapper: delegates to app.utils.atomic_json if available (when run
from the main project), otherwise provides an equivalent local fallback.
"""

import json
import os
import tempfile

__all__ = ['write_json_atomic']

try:
    # When run from the main project root (scheduler, Flask)
    from app.utils.atomic_json import write_json_atomic
except ImportError:
    def write_json_atomic(
        filepath: str,
        data,
        *,
        indent: int = 2,
        ensure_ascii: bool = False,
        sort_keys: bool = False,
        default=None,
    ) -> None:
        """Crash-safe JSON write (standalone fallback)."""
        abs_path = os.path.abspath(filepath)
        directory = os.path.dirname(abs_path) or '.'
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix='.tmp_', suffix='.json', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(
                    data, f,
                    indent=indent,
                    ensure_ascii=ensure_ascii,
                    sort_keys=sort_keys,
                    default=default,
                )
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, abs_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise
