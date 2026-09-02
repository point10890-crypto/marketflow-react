# -*- coding: utf-8 -*-
"""심층분석 백그라운드 잡 — Cloudflare 엣지 ~100초 응답 한계의 구조적 해소.

동기 POST 로 LLM 토론(실측 59초, 부하 시 그 이상)을 기다리면 엣지가 524 로 끊는
날이 반드시 온다. 그래서 시작(POST, 즉시 202)과 결과(GET 폴링)를 분리한다.

설계 원칙
- 잡은 프로세스 내 스레드 1개. 같은 종목의 중복 시작은 기존 잡에 합류한다.
- 동시 실행 상한(기본 2, DECISION_JOB_MAX_CONCURRENT) — 심층분석은 LLM 8~12콜이라
  폭주하면 비용·경합 둘 다 무너진다. 상한 초과는 429 로 정직하게 거절한다.
- 성공 결과는 기존 일간 캐시(decision_cache 'deep')에 그대로 들어간다 — 폴링 GET 과
  기존 동기 GET 캐시 적중 경로가 같은 산출물을 본다.
- 프로세스 재시작 시 진행 중 잡은 사라진다. 클라이언트 폴링은 'none' 을 받고
  재시작을 안내한다 — 잡 영속화는 이번 범위 밖(스펙 §3).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}   # key(symbol code) → job record

#: 완료/실패 잡을 메모리에 유지하는 시간(초) — 폴링 클라이언트가 결과를 집을 여유.
DONE_RETENTION_S = 600


def _max_concurrent() -> int:
    try:
        return max(1, int(os.environ.get('DECISION_JOB_MAX_CONCURRENT', '') or 2))
    except ValueError:
        return 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _prune_locked() -> None:
    cutoff = time.time() - DONE_RETENTION_S
    for key in [k for k, j in _JOBS.items()
                if j['state'] in ('done', 'error') and j['finished_ts'] < cutoff]:
        _JOBS.pop(key, None)


def running_count() -> int:
    with _LOCK:
        return sum(1 for j in _JOBS.values() if j['state'] == 'running')


def start(key: str, symbol: str) -> dict[str, Any]:
    """잡 시작. 반환 status: started | joined | busy.

    joined = 같은 종목 잡이 이미 도는 중(중복 시작 아님, 쿼터도 소모하지 않도록
    호출측이 이 상태를 먼저 확인한다). busy = 동시 상한 초과.
    """
    from app.services.mirofish import decision_brief, decision_cache

    with _LOCK:
        _prune_locked()
        existing = _JOBS.get(key)
        if existing and existing['state'] == 'running':
            return {'status': 'joined', 'job': _public(existing)}
        if sum(1 for j in _JOBS.values() if j['state'] == 'running') >= _max_concurrent():
            return {'status': 'busy', 'max_concurrent': _max_concurrent()}
        job: dict[str, Any] = {'key': key, 'symbol': symbol, 'state': 'running',
                               'started_at': _now(), 'finished_ts': 0.0,
                               'error': None}
        _JOBS[key] = job

    def _work() -> None:
        try:
            payload = decision_brief.run_deep_analysis_for(symbol)
            if not (payload or {}).get('error'):
                try:
                    decision_cache.cache_put('deep', key, payload)
                except Exception as exc:  # noqa: BLE001 — 캐시 실패가 결과를 잃게 하면 안 된다
                    logger.warning('deep job cache_put failed (%s): %s', key, exc)
            with _LOCK:
                job['state'] = 'error' if (payload or {}).get('error') else 'done'
                job['error'] = (payload or {}).get('error')
                job['payload'] = payload
                job['finished_ts'] = time.time()
        except Exception as exc:  # noqa: BLE001
            logger.exception('deep job failed: %s', key)
            with _LOCK:
                job['state'] = 'error'
                job['error'] = f'{type(exc).__name__}: {exc}'
                job['finished_ts'] = time.time()

    worker = threading.Thread(target=_work, daemon=True, name=f'DeepAnalysis-{key}')
    try:
        worker.start()
    except Exception as exc:  # noqa: BLE001 — 기동 실패가 유령 'running' 잡을 남기면 안 된다
        with _LOCK:
            job['state'] = 'error'
            job['error'] = f'{type(exc).__name__}: {exc}'
            job['finished_ts'] = time.time()
        raise
    return {'status': 'started', 'job': _public(job)}


def status(key: str) -> dict[str, Any]:
    """폴링용. state: running | done | error | none. done 이면 payload 를 포함한다."""
    with _LOCK:
        _prune_locked()
        job = _JOBS.get(key)
        if job is None:
            return {'state': 'none'}
        out = _public(job)
        if job['state'] == 'done':
            out['payload'] = job.get('payload')
        return out


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {'key': job['key'], 'symbol': job['symbol'], 'state': job['state'],
            'started_at': job['started_at'], 'error': job.get('error')}


def _reset_for_tests() -> None:
    with _LOCK:
        _JOBS.clear()
