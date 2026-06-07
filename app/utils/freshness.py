"""Helpers for attaching source freshness metadata to JSON API payloads."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterable


_CANDIDATE_PATHS: tuple[tuple[str, ...], ...] = (
    ("metadata", "generated_at"),
    ("metadata", "updated_at"),
    ("metadata", "timestamp"),
    ("summary", "generated_at"),
    ("summary", "updated_at"),
    ("summary", "timestamp"),
    ("generated_at",),
    ("updated_at",),
    ("timestamp",),
    ("scan_at",),
    ("date",),
)


def parse_datetime_value(value: Any) -> datetime | None:
    """Parse common JSON timestamp/date values without raising."""
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts)
        except (OSError, OverflowError, ValueError):
            return None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass

    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    return None


def _get_nested(data: Any, path: Iterable[str]) -> Any:
    cur = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def find_content_datetime(data: Any) -> datetime | None:
    """Return the best content timestamp embedded in a JSON object."""
    for path in _CANDIDATE_PATHS:
        dt = parse_datetime_value(_get_nested(data, path))
        if dt is not None:
            return dt
    return None


def _to_epoch(dt: datetime) -> float:
    return dt.timestamp()


def build_freshness(
    source_path: str,
    data: Any | None = None,
    *,
    max_age_hours: float = 72.0,
) -> dict[str, Any]:
    """Build a compact freshness object for API responses and verification."""
    exists = os.path.exists(source_path)
    file_dt = datetime.fromtimestamp(os.path.getmtime(source_path)) if exists else None
    content_dt = find_content_datetime(data) if data is not None else None
    basis_dt = content_dt or file_dt

    now_epoch = datetime.now().timestamp()
    age_seconds = None
    if basis_dt is not None:
        age_seconds = max(0, int(now_epoch - _to_epoch(basis_dt)))

    max_age_seconds = int(max_age_hours * 3600)
    stale_reasons: list[str] = []
    if not exists:
        stale_reasons.append("missing_file")
    if basis_dt is None:
        stale_reasons.append("missing_timestamp")
    if age_seconds is not None and age_seconds > max_age_seconds:
        stale_reasons.append("expired")

    return {
        "source_file": os.path.relpath(source_path).replace("\\", "/") if exists else source_path,
        "exists": exists,
        "basis": "content_timestamp" if content_dt is not None else "file_mtime",
        "content_timestamp": content_dt.isoformat() if content_dt else None,
        "file_mtime": file_dt.isoformat() if file_dt else None,
        "age_seconds": age_seconds,
        "max_age_hours": max_age_hours,
        "is_stale": bool(stale_reasons),
        "stale_reasons": stale_reasons,
    }


def attach_freshness(
    data: Any,
    source_path: str,
    *,
    max_age_hours: float = 72.0,
) -> Any:
    """Attach freshness under metadata.freshness while preserving payload shape."""
    if not isinstance(data, dict):
        return data
    payload = dict(data)
    metadata = dict(payload.get("metadata") or {})
    metadata["freshness"] = build_freshness(source_path, payload, max_age_hours=max_age_hours)
    payload["metadata"] = metadata
    return payload
