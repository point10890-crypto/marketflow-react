"""AlphaCore runtime boundary.

The package intentionally knows only two modes:

``shadow``
    Pure evaluation.  No paper-capital events may be persisted and no fills may
    be generated.

``paper``
    Internal deterministic paper ledger and fill simulation only.

There is deliberately no ``live`` enum value or fallback.  Adding one is a
separate design and authorization decision, not an environment toggle.
"""

from __future__ import annotations

import os
from pathlib import Path


ALLOWED_MODES = frozenset({"shadow", "paper"})
DEFAULT_MODE = "shadow"
MODE_ENV = "ALPHACLAW_MODE"
DB_PATH_ENV = "ALPHA_CORE_DB_PATH"


class AlphaCoreConfigurationError(ValueError):
    """Raised when a runtime setting crosses the AlphaCore safety boundary."""


def resolve_mode(value: str | None = None) -> str:
    """Return a validated mode, defaulting safely to ``shadow``.

    The explicit ``value`` is useful for deterministic tests and command-line
    tools.  When omitted, the environment is read exactly once per call.
    """

    raw = value if value is not None else os.getenv(MODE_ENV)
    if raw is None:
        raw = DEFAULT_MODE
    mode = str(raw).strip().lower()
    if mode not in ALLOWED_MODES:
        allowed = ", ".join(sorted(ALLOWED_MODES))
        raise AlphaCoreConfigurationError(
            f"unsupported {MODE_ENV}={raw!r}; allowed values: {allowed}"
        )
    return mode


def default_db_path() -> Path:
    """Return the isolated paper DB path without creating anything."""

    configured = str(os.getenv(DB_PATH_ENV, "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "alphaclaw" / "paper.db"
