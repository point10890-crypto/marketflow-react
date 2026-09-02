# -*- coding: utf-8 -*-
"""사건 원장 — 깔때기를 통과한 뉴스 사건만 보관한다 (SQLite).

원문 본문 컬럼이 존재하지 않는다: 제목·요약(≤500자)·링크·해시만 남긴다.
저작권과 저장 비용 양쪽의 이유이며, 스키마 자체로 강제한다.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from app.services.omni.funnel import CORROBORATION_WEIGHT

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DB_PATH = os.path.join(REPO_ROOT, 'data', 'omni', 'omni.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_events (
  id INTEGER PRIMARY KEY,
  content_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  summary TEXT,
  link TEXT,
  source TEXT,
  sources TEXT,
  grade TEXT,
  published_ts TEXT,
  symbols TEXT,
  themes TEXT,
  score REAL,
  corroboration INTEGER DEFAULT 1,
  collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_news_collected ON news_events(collected_at DESC);
CREATE INDEX IF NOT EXISTS ix_news_score ON news_events(score DESC);
CREATE INDEX IF NOT EXISTS ix_news_published ON news_events(published_ts DESC, score DESC);
"""


@contextmanager
def connect(path: str | None = None) -> Iterator[sqlite3.Connection]:
    """호출 시점의 모듈 DB_PATH 를 쓴다 (테스트 격리를 위해 기본 인자 바인딩 금지)."""
    import app.services.omni.ledger as _self

    target = path or _self.DB_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    def _loads(value: Any) -> list[str]:
        try:
            out = json.loads(value or '[]')
            return out if isinstance(out, list) else []
        except (TypeError, ValueError):
            return []

    return {
        'content_hash': row['content_hash'], 'title': row['title'],
        'summary': row['summary'], 'link': row['link'], 'source': row['source'],
        'sources': _loads(row['sources']), 'grade': row['grade'],
        'published_ts': row['published_ts'], 'symbols': _loads(row['symbols']),
        'themes': _loads(row['themes']), 'score': row['score'],
        'corroboration': row['corroboration'], 'collected_at': row['collected_at'],
    }


def save_events(events: list[dict[str, Any]]) -> int:
    """신규 사건 수를 반환한다. 같은 content_hash 는 다시 넣지 않는다.

    다만 스윕을 넘어 같은 사건이 다른 매체에서 재관측되면 그냥 버리지 않고
    sources 를 합집합으로 병합하고 corroboration/score 를 올린다 (append-safe:
    기존 행의 제목·요약·수집시각 등은 절대 다시 쓰지 않는다). corroboration 은
    매 스윕마다 같은 피드가 같은 기사를 재서빙하므로 증분이 아니라
    '서로 다른 소스 수' 기준으로만 올린다.
    """
    if not events:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with connect() as con:
        for event in events:
            if not isinstance(event, dict) or not event.get('content_hash'):
                continue
            digest = str(event['content_hash'])
            cur = con.execute(
                'INSERT OR IGNORE INTO news_events'
                '(content_hash, title, summary, link, source, sources, grade,'
                ' published_ts, symbols, themes, score, corroboration, collected_at)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (digest, str(event.get('title') or ''),
                 str(event.get('summary') or ''), str(event.get('link') or ''),
                 str(event.get('source') or ''),
                 json.dumps(event.get('sources') or [], ensure_ascii=False),
                 str(event.get('grade') or 'C'), event.get('published_ts'),
                 json.dumps(event.get('symbols') or [], ensure_ascii=False),
                 json.dumps(event.get('themes') or [], ensure_ascii=False),
                 float(event.get('score') or 0.0),
                 int(event.get('corroboration') or 1), now))
            if cur.rowcount:
                inserted += cur.rowcount
            else:
                _merge_duplicate(con, digest, event)
    return inserted


def _merge_duplicate(con: sqlite3.Connection, digest: str, event: dict[str, Any]) -> None:
    """중복 사건(스윕 간 재관측)의 교차검증 정보만 기존 행에 병합한다."""
    row = con.execute(
        'SELECT sources, corroboration, score FROM news_events WHERE content_hash = ?',
        (digest,)).fetchone()
    if row is None:
        return
    try:
        existing = json.loads(row['sources'] or '[]')
    except (TypeError, ValueError):
        existing = []
    if not isinstance(existing, list):
        existing = []
    incoming = list(event.get('sources') or [])
    if not incoming and event.get('source'):
        incoming = [str(event['source'])]
    merged = [str(s) for s in existing if s]
    for src in incoming:
        src = str(src)
        if src and src not in merged:
            merged.append(src)
    old_corr = max(1, int(row['corroboration'] or 1))
    new_corr = max(old_corr, len(merged) or 1)
    if merged == existing and new_corr == old_corr:
        return
    old_score = float(row['score'] or 0.0)
    new_score = old_score
    if new_corr > old_corr and old_score > 0:
        # importance_score 의 corroboration 항과 동일한 증분 (funnel 과 일관 유지)
        new_score = round(old_score + (new_corr - old_corr) * CORROBORATION_WEIGHT, 3)
    con.execute(
        'UPDATE news_events SET sources = ?, corroboration = ?, score = ? '
        'WHERE content_hash = ?',
        (json.dumps(merged, ensure_ascii=False), new_corr, new_score, digest))


def recent_events(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            'SELECT * FROM news_events ORDER BY collected_at DESC, score DESC LIMIT ?',
            (max(1, int(limit)),)).fetchall()
    return [_row_to_event(r) for r in rows]


def events_for_symbol(symbol: str, limit: int = 10) -> list[dict[str, Any]]:
    """종목별 최근 사건 — decision_brief 의 근거 보강용(읽기전용)."""
    code = str(symbol or '').strip()
    if not code:
        return []
    like = f'%"{code}"%'
    with connect() as con:
        rows = con.execute(
            'SELECT * FROM news_events WHERE symbols LIKE ? '
            'ORDER BY published_ts DESC, score DESC LIMIT ?',
            (like, max(1, int(limit)))).fetchall()
    return [_row_to_event(r) for r in rows]


def stats() -> dict[str, Any]:
    # collected_at 은 ISO('T' 구분자) 저장인데 SQLite datetime() 은 공백 구분자를
    # 내놓아 사전식 비교가 24~48시간 창으로 넓어진다 → 파이썬에서 동일 포맷 경계 생성.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with connect() as con:
        total = con.execute('SELECT COUNT(*) FROM news_events').fetchone()[0]
        last = con.execute('SELECT MAX(collected_at) FROM news_events').fetchone()[0]
        top = con.execute(
            'SELECT COUNT(*) FROM news_events WHERE collected_at >= ?',
            (cutoff,)).fetchone()[0]
    return {'total': total, 'last_collected_at': last, 'last_24h': top}
