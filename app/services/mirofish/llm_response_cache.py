"""LLM 응답 캐시 (SQLite, TTL) — 같은 프롬프트에 두 번 지불하지 않는다.

리뷰(2026-09-02 §3.5 ⑥): 프롬프트 캐싱이 0 이라 스캐너 rerank·주도주 뉴스 사유처럼
같은 입력이 반복되는 경로가 매번 provider 에 재과금됐다. 이 모듈은 provider 와
무관한 얇은 저장소만 제공한다 — 키 생성/TTL 판단은 호출부(llm_client 등)가 한다.

설계:
    - 파일: data/llm_response_cache.db (app.utils.paths.DATA_DIR 기준)
    - 테이블 llm_response_cache(key PK, provider, model, text, usage_json, created_at, expires_at)
    - 호출마다 새 connection (스레드 간 공유 없음 → check_same_thread 불필요)
    - 실패는 절대 전파하지 않는다: 캐시가 깨져도 LLM 호출은 그대로 진행
    - 킬스위치: MIROFISH_LLM_CACHE_DISABLED=1
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from typing import Any

from app.utils.paths import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(DATA_DIR, 'llm_response_cache.db')
_TABLE = 'llm_response_cache'
_SCHEMA = f'''
CREATE TABLE IF NOT EXISTS {_TABLE} (
    key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT,
    text TEXT NOT NULL,
    usage_json TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
)
'''


def is_disabled() -> bool:
    return os.getenv('MIROFISH_LLM_CACHE_DISABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


def make_key(*parts: Any) -> str:
    """sha256 of the '|'-joined parts. dict/list parts are canonical JSON."""
    encoded: list[str] = []
    for part in parts:
        if isinstance(part, (dict, list, tuple)):
            encoded.append(json.dumps(part, ensure_ascii=False, sort_keys=True, default=str))
        elif part is None:
            encoded.append('')
        else:
            encoded.append(str(part))
    return hashlib.sha256('|'.join(encoded).encode('utf-8')).hexdigest()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)) or '.', exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute(_SCHEMA)
    return conn


def get(key: str) -> dict[str, Any] | None:
    """만료되지 않은 항목을 돌려준다. 없거나 캐시 장애면 None."""
    if is_disabled() or not key:
        return None
    try:
        conn = _connect()
        try:
            row = conn.execute(
                f'SELECT provider, model, text, usage_json, created_at, expires_at FROM {_TABLE} WHERE key = ?',
                (key,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — 캐시 장애는 조용히 miss 처리
        logger.warning('[llm_cache] read failed: %s', type(exc).__name__)
        return None
    if row is None:
        return None
    provider, model, text, usage_json, created_at, expires_at = row
    if float(expires_at) <= time.time():
        return None
    usage = None
    if usage_json:
        try:
            usage = json.loads(usage_json)
        except ValueError:
            usage = None
    return {
        'provider': provider,
        'model': model,
        'text': text,
        'usage': usage,
        'created_at': created_at,
        'expires_at': expires_at,
    }


def put(key: str, *, provider: str, model: str | None, text: str,
        usage: dict[str, Any] | None, ttl: int) -> bool:
    """항목 저장(덮어쓰기). ttl<=0 이면 저장하지 않는다."""
    if is_disabled() or not key or not text or ttl is None or int(ttl) <= 0:
        return False
    now = time.time()
    try:
        conn = _connect()
        try:
            conn.execute(
                f'INSERT OR REPLACE INTO {_TABLE} (key, provider, model, text, usage_json, created_at, expires_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (
                    key, str(provider), model,
                    text,
                    json.dumps(usage, ensure_ascii=False) if usage else None,
                    now, now + int(ttl),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning('[llm_cache] write failed: %s', type(exc).__name__)
        return False


def purge_expired(now: float | None = None) -> int:
    """만료 항목 삭제 후 삭제 건수 반환. 캐시 장애면 0."""
    cutoff = time.time() if now is None else float(now)
    try:
        conn = _connect()
        try:
            cur = conn.execute(f'DELETE FROM {_TABLE} WHERE expires_at <= ?', (cutoff,))
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning('[llm_cache] purge failed: %s', type(exc).__name__)
        return 0


def stats() -> dict[str, Any]:
    """운영 가시성용 요약 (항목 수/만료 수). 프롬프트·응답 본문은 노출하지 않는다."""
    try:
        conn = _connect()
        try:
            total = conn.execute(f'SELECT COUNT(*) FROM {_TABLE}').fetchone()[0]
            expired = conn.execute(
                f'SELECT COUNT(*) FROM {_TABLE} WHERE expires_at <= ?', (time.time(),)
            ).fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {'disabled': is_disabled(), 'error': type(exc).__name__}
    return {'disabled': is_disabled(), 'entries': int(total), 'expired': int(expired)}
