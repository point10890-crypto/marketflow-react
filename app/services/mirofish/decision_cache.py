# -*- coding: utf-8 -*-
"""종목 판단 결과의 일간 캐시.

같은 종목을 하루에 여러 번 눌러도 같은 계산을 반복하지 않는다. 브리프는 7개 소스를
팬아웃해 모으고(실측 ~15초), 심층 분석은 LLM 토론까지 돌린다(~2분, 유료).

만료 규칙을 종류별로 나눈 이유
    - ``deep``  : 에이전트 토론 결과다. 장중에 흔들릴 성질이 아니므로 그날 하루 재사용한다.
    - ``brief`` : 주도주 전이 같은 **장중 실시간 근거**를 포함한다. 장중에는 짧은 TTL
                  로만 재사용하고, 장이 끝난 뒤에는 그날 하루 유지한다.

캐시는 절대 요청을 막지 않는다. 읽기·쓰기의 어떤 실패도 '미스'로 흘러 정상 계산으로
이어진다 — 캐시 장애가 기능 장애가 되어선 안 된다.

킬스위치
    DECISION_CACHE_DISABLED=1   읽기·쓰기 모두 무효화 (항상 재계산)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DB_PATH = os.path.join(REPO_ROOT, 'data', 'decision_cache.db')

KST = timezone(timedelta(hours=9))

#: 장중 브리프를 재사용해도 되는 한도(초). 실시간 근거가 섞여 있어 짧게 잡는다.
MARKET_TTL = 300

#: 장 운영 시간(KST, 분 단위). 정규장 + 마감 직후 정산 여유.
MARKET_OPEN_MIN = 9 * 60
MARKET_CLOSE_MIN = 15 * 60 + 40


def _disabled() -> bool:
    return str(os.environ.get('DECISION_CACHE_DISABLED', '')).strip().lower() in {
        '1', 'true', 'yes', 'on'}


def _now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def _in_market_hours(when: datetime) -> bool:
    if when.weekday() >= 5:  # 토·일
        return False
    minutes = when.hour * 60 + when.minute
    return MARKET_OPEN_MIN <= minutes <= MARKET_CLOSE_MIN


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.execute("""
        CREATE TABLE IF NOT EXISTS decision_cache (
            kind        TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            payload     TEXT NOT NULL,
            created_ts  TEXT NOT NULL,
            PRIMARY KEY (kind, symbol)
        )
    """)
    return con


def _is_fresh(kind: str, created: datetime, when: datetime) -> bool:
    """같은 날 안에서 이 항목을 그대로 써도 되는가."""
    if created.date() != when.date():
        return False
    if kind != 'brief':
        return True
    # 브리프는 장중에만 신선도를 따진다. 장이 닫혀 있으면 근거가 더 바뀌지 않는다.
    if not _in_market_hours(when):
        return True
    return (when - created).total_seconds() <= MARKET_TTL


def cache_get(kind: str, symbol: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """캐시 적중이면 ``cached``/``cached_at`` 을 붙여 돌려준다. 아니면 None."""
    if _disabled():
        return None
    when = now or _now_kst()
    try:
        con = _connect()
        try:
            row = con.execute(
                'SELECT payload, created_ts FROM decision_cache WHERE kind=? AND symbol=?',
                (str(kind), str(symbol)),
            ).fetchone()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 — 캐시 장애가 기능 장애가 되면 안 된다
        logger.debug('[decision_cache] read failed: %s', exc)
        return None

    if not row:
        return None

    try:
        created = datetime.fromisoformat(row[1])
        payload = json.loads(row[0])
    except (TypeError, ValueError) as exc:
        logger.debug('[decision_cache] corrupt entry %s/%s: %s', kind, symbol, exc)
        return None

    if not isinstance(payload, dict) or not _is_fresh(str(kind), created, when):
        return None

    payload['cached'] = True
    payload['cached_at'] = created.isoformat()
    return payload


def cache_put(kind: str, symbol: Any, payload: Any, *,
              now: datetime | None = None) -> None:
    """계산 결과를 저장한다. 원본 payload 는 건드리지 않는다."""
    if _disabled() or not isinstance(payload, dict):
        return
    when = now or _now_kst()
    body = {k: v for k, v in payload.items() if k not in {'cached', 'cached_at'}}
    try:
        con = _connect()
        try:
            con.execute(
                'INSERT OR REPLACE INTO decision_cache'
                ' (kind, symbol, trade_date, payload, created_ts) VALUES (?,?,?,?,?)',
                (str(kind), str(symbol), when.date().isoformat(),
                 json.dumps(body, ensure_ascii=False), when.isoformat()),
            )
            con.commit()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug('[decision_cache] write failed: %s', exc)


def cache_clear(*, kind: str | None = None, symbol: Any = None) -> int:
    """캐시를 비운다. 인자를 좁힐수록 지우는 범위가 준다. 지운 행 수를 돌려준다."""
    clauses, args = [], []
    if kind:
        clauses.append('kind=?')
        args.append(str(kind))
    if symbol:
        clauses.append('symbol=?')
        args.append(str(symbol))
    sql = 'DELETE FROM decision_cache'
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    try:
        con = _connect()
        try:
            cur = con.execute(sql, args)
            con.commit()
            return cur.rowcount or 0
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug('[decision_cache] clear failed: %s', exc)
        return 0


# ─── 심층분석 일일 쿼터 (유료 서비스 남용 차단) ─────────────────
#
# 심층분석 1회 = LLM 8~12콜. 캐시 적중은 차감하지 않는다(재조회는 무료).
# 쿼터 저장소 장애는 fail-open — 가용성이 우선이며, 사유는 로그로 남긴다.

DEEP_QUOTA_ENV = 'DECISION_DEEP_DAILY_QUOTA'
DEEP_QUOTA_DEFAULT = 20


def deep_quota_limit() -> int:
    try:
        return int(os.environ.get(DEEP_QUOTA_ENV, '') or DEEP_QUOTA_DEFAULT)
    except ValueError:
        return DEEP_QUOTA_DEFAULT


def consume_deep_quota(user_id: int) -> tuple[bool, int, int]:
    """(허용 여부, 남은 횟수, 한도). 한도 0 이하 = 무제한."""
    limit = deep_quota_limit()
    if limit <= 0:
        return True, -1, 0
    day = _now_kst().strftime('%Y%m%d')
    try:
        con = _connect()
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS deep_quota (
                    day     TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    count   INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, user_id)
                )
            """)
            row = con.execute('SELECT count FROM deep_quota WHERE day=? AND user_id=?',
                              (day, int(user_id))).fetchone()
            used = int(row[0]) if row else 0
            if used >= limit:
                return False, 0, limit
            con.execute('INSERT INTO deep_quota(day, user_id, count) VALUES (?,?,1) '
                        'ON CONFLICT(day, user_id) DO UPDATE SET count = count + 1',
                        (day, int(user_id)))
            con.commit()
            return True, limit - used - 1, limit
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 — 쿼터 인프라 장애가 기능 장애가 되면 안 된다
        logger.warning('deep quota check failed (fail-open): %s', exc)
        return True, -1, limit
