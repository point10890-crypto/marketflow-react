# -*- coding: utf-8 -*-
"""GraphRAG 엔티티 DB 부트스트랩 — `entities.db` 가 없으면/비었으면/오래됐으면 적재한다.

배경 (app_review §3.2 개선안 2): `resolver.populate_from_sources()` 는 있었지만
아무도 부팅 시 호출하지 않아 새 체크아웃·miniPC 재설치 환경에서는 `entities.db`
가 영영 생기지 않았다. 그러면 `decision_brief._graphrag_matches` 가 조용히 `[]`
를 돌려줘 초성·별칭·퍼지 검색 코드가 전부 죽은 코드였다.

불변조건
    - 절대 raise 하지 않는다. 결과 dict 의 `status` 로만 말한다.
    - 멱등. 신선한 DB 가 있으면 `skipped`.
    - 동시 호출(Flask 부팅 스레드 + 스케줄러)은 프로세스 내 락으로 직렬화.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 7
_lock = threading.Lock()


def _entities_db_path() -> str:
    # 테스트가 resolver.ENTITIES_DB 를 monkeypatch 하므로 호출 시점에 읽는다.
    from app.services.mirofish.graphrag import resolver
    return str(resolver.ENTITIES_DB)


def _count_entities(path: str) -> int:
    """entities 행 수. 파일 부재·스키마 부재·손상은 0 으로 본다."""
    if not os.path.isfile(path):
        return 0
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    try:
        row = conn.execute('SELECT COUNT(*) FROM entities').fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _age_days(path: str) -> float | None:
    try:
        return (time.time() - os.path.getmtime(path)) / 86400.0
    except OSError:
        return None


def ensure_entities_db(force: bool = False, *, max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> dict[str, Any]:
    """`entities.db` 를 필요할 때만 적재한다.

    Returns::

        {'status': 'ok' | 'skipped' | 'error',
         'entities': <적재 후 행 수>,
         'reason': 'missing' | 'empty' | 'stale' | 'forced' | 'fresh',
         'path': ..., 'age_days': ..., 'elapsed_ms': ..., 'populate': {...} | None,
         'error': <str, error 일 때만>}
    """
    started = time.time()
    path = ''
    try:
        path = _entities_db_path()
        with _lock:
            before = _count_entities(path)
            age = _age_days(path)
            if force:
                reason = 'forced'
            elif not os.path.isfile(path):
                reason = 'missing'
            elif before <= 0:
                reason = 'empty'
            elif age is not None and age > float(max_age_days):
                reason = 'stale'
            else:
                return {
                    'status': 'skipped', 'reason': 'fresh', 'entities': before,
                    'path': path, 'age_days': round(age, 2) if age is not None else None,
                    'elapsed_ms': round((time.time() - started) * 1000),
                    'populate': None,
                }

            from app.services.mirofish.graphrag import resolver
            populate = resolver.populate_from_sources()
            after = _count_entities(path)
            if after <= 0:
                # 원천 CSV 가 없어 0건 적재 — DB 파일은 생겼지만 검색은 여전히 죽어 있다.
                return {
                    'status': 'error', 'reason': reason, 'entities': after,
                    'path': path, 'age_days': round(age, 2) if age is not None else None,
                    'elapsed_ms': round((time.time() - started) * 1000),
                    'populate': populate,
                    'error': 'no entities loaded — data/ticker_to_yahoo_map.csv missing or empty',
                }
            logger.info('[graphrag] entities.db %s → %d entities (%s)', reason, after, path)
            return {
                'status': 'ok', 'reason': reason, 'entities': after,
                'path': path, 'age_days': round(age, 2) if age is not None else None,
                'elapsed_ms': round((time.time() - started) * 1000),
                'populate': populate,
            }
    except Exception as exc:  # noqa: BLE001 — 부팅/스케줄 경로에서 절대 raise 하지 않는다
        logger.warning('[graphrag] entities.db bootstrap failed: %s', exc)
        return {
            'status': 'error', 'reason': 'exception', 'entities': _count_entities(path) if path else 0,
            'path': path, 'age_days': None,
            'elapsed_ms': round((time.time() - started) * 1000),
            'populate': None, 'error': f'{type(exc).__name__}: {exc}',
        }


def start_background_bootstrap(*, name: str = 'GraphRAGEntitiesBootstrap') -> threading.Thread:
    """부팅을 막지 않도록 데몬 스레드에서 `ensure_entities_db()` 를 1회 실행한다."""
    thread = threading.Thread(target=ensure_entities_db, daemon=True, name=name)
    thread.start()
    return thread
