"""근거 캡슐 — 예측 시점에 본 자료. 내용의 SHA-256 이 키다."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from typing import Any

from app.services.forecast_league import clock


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def put_capsule(conn: sqlite3.Connection, payload: Any) -> str:
    body = _canonical(payload)
    digest = hashlib.sha256(body).hexdigest()
    conn.execute('INSERT OR IGNORE INTO capsules (capsule_hash, payload, created_at) VALUES (?, ?, ?)',
                 (digest, zlib.compress(body), clock.iso(clock.now_utc())))
    return digest


def get_capsule(conn: sqlite3.Connection, capsule_hash: str) -> Any | None:
    row = conn.execute('SELECT payload FROM capsules WHERE capsule_hash = ?', (capsule_hash,)).fetchone()
    if row is None:
        return None
    body = zlib.decompress(row['payload'])
    if hashlib.sha256(body).hexdigest() != capsule_hash:
        raise ValueError('capsule_integrity')
    return json.loads(body.decode('utf-8'))
