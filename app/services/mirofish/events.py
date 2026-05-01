"""Run events — JSONL append-only log per run + tail reader for SSE/polling."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Iterator

from app.services.mirofish.store import _safe_run_id, _run_dir

_lock = threading.Lock()


def append_event(run_id: str, level: str, phase: str, message: str,
                 *, payload: dict | None = None) -> dict[str, Any]:
    """Append event to events.jsonl. Atomic per-line append (file lock)."""
    safe_id = _safe_run_id(run_id)
    run_dir = _run_dir(safe_id)
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, 'events.jsonl')

    event = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'level': str(level),
        'phase': str(phase),
        'message': str(message),
    }
    if payload is not None and isinstance(payload, dict):
        event['payload'] = payload

    line = json.dumps(event, ensure_ascii=False) + '\n'
    with _lock:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line)
    return event


def read_events(run_id: str, *, since_index: int = 0,
                max_count: int = 200) -> dict[str, Any]:
    """Tail read events from index onward. Used for polling-based SSE."""
    safe_id = _safe_run_id(run_id)
    path = os.path.join(_run_dir(safe_id), 'events.jsonl')
    if not os.path.isfile(path):
        return {'run_id': safe_id, 'events': [], 'next_index': 0, 'total': 0}

    with _lock:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
        except OSError:
            return {'run_id': safe_id, 'events': [], 'next_index': since_index, 'total': 0}

    total = len(all_lines)
    since_index = max(0, min(since_index, total))
    slice_lines = all_lines[since_index:since_index + max_count]
    events = []
    for ln in slice_lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    next_idx = since_index + len(slice_lines)
    return {
        'run_id': safe_id,
        'events': events,
        'next_index': next_idx,
        'total': total,
        'has_more': next_idx < total,
    }


def stream_events_sse(run_id: str, *, since_index: int = 0) -> Iterator[str]:
    """Generator yielding SSE-formatted strings.

    Usage in Flask route:
        return Response(stream_events_sse(run_id), mimetype='text/event-stream')

    Polls disk every 1s for new events. Stops after 30s idle (client must reconnect).
    """
    import time
    idle_seconds = 0
    max_idle = 30
    poll_interval = 1.0
    cursor = since_index

    while idle_seconds < max_idle:
        snap = read_events(run_id, since_index=cursor, max_count=200)
        new_events = snap['events']
        if new_events:
            for ev in new_events:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            cursor = snap['next_index']
            idle_seconds = 0
        else:
            yield ': keep-alive\n\n'
            idle_seconds += poll_interval
        time.sleep(poll_interval)

    yield 'event: end\ndata: {"reason": "idle_timeout"}\n\n'
