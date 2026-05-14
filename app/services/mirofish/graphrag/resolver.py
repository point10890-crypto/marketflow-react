"""Entity resolver — 종목명 / ticker / corp_code / yahoo ticker → 표준 entity_id.

청사진 §5 entity resolve 설계의 핵심 구현.

매칭 우선순위 (높은 confidence 부터):
1. ticker direct (`005930`) — confidence 1.00
2. yahoo ticker (`005930.KS`) — confidence 0.99
3. corp_code 역방향 (`00126380`) — confidence 0.99
4. exact alias / chosung 정확 매치 — confidence 0.95
5. exact name (대소문자 무시) — confidence 0.97
6. prefix name — confidence 0.80–0.90
7. fuzzy match (difflib SequenceMatcher) — confidence 0.50–0.80
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import time
from difflib import SequenceMatcher
from typing import Any

from app.services.mirofish.graphrag.korean import (
    extract_chosung,
    is_chosung_only,
    normalize_query,
)
from app.services.mirofish.graphrag.storage import (
    ENTITIES_DB,
    ensure_dirs,
)
from app.utils.paths import BASE_DIR, DATA_DIR


# ── SQLite schema (Phase B) ──────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id     TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    name_ko       TEXT,
    name_en       TEXT,
    symbol        TEXT,
    market        TEXT,
    exchange      TEXT,
    country       TEXT,
    sector_id     TEXT,
    extra_json    TEXT NOT NULL DEFAULT '{}',
    chosung_ko    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name_ko ON entities(name_ko);
CREATE INDEX IF NOT EXISTS idx_entities_name_en ON entities(name_en);
CREATE INDEX IF NOT EXISTS idx_entities_symbol ON entities(symbol);
CREATE INDEX IF NOT EXISTS idx_entities_chosung ON entities(chosung_ko);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias         TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    lang          TEXT NOT NULL DEFAULT 'ko',
    source        TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (alias, entity_id),
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_aliases_alias ON entity_aliases(alias);

CREATE TABLE IF NOT EXISTS entity_external_ids (
    entity_id     TEXT NOT NULL,
    id_type       TEXT NOT NULL,
    id_value      TEXT NOT NULL,
    PRIMARY KEY (entity_id, id_type),
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_ext_ids ON entity_external_ids(id_type, id_value);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    """SQLite 스키마 생성 (idempotent)."""
    conn.executescript(_SCHEMA)
    conn.commit()


def _connect(read_only: bool = True) -> sqlite3.Connection:
    ensure_dirs()
    if read_only and os.path.exists(ENTITIES_DB):
        return sqlite3.connect(f"file:{ENTITIES_DB}?mode=ro", uri=True, timeout=2.0)
    return sqlite3.connect(ENTITIES_DB, timeout=5.0)


# ── yahoo_ticker ↔ entity_id 변환 (청사진 §4.2 / §5.2) ────────────────

def yahoo_to_entity_id(yahoo_ticker: str) -> str:
    """``005930.KS`` → ``kr:005930``, ``AAPL`` → ``us:AAPL``."""
    yt = (yahoo_ticker or '').strip().upper()
    if not yt:
        return ''
    if yt.endswith('.KS') or yt.endswith('.KQ'):
        return f"kr:{yt.rsplit('.', 1)[0]}"
    if yt.endswith('.US'):
        return f"us:{yt.rsplit('.', 1)[0]}"
    if '-' in yt and yt.endswith('USD'):
        return f"crypto:{yt.lower()}"
    return f"us:{yt}"


def entity_id_to_kr_ticker(entity_id: str) -> str | None:
    """``kr:005930`` → ``005930``. 한국 종목이 아니면 None."""
    if entity_id and entity_id.startswith('kr:'):
        return entity_id.split(':', 1)[1]
    return None


# ── 초기 적재 (청사진 §12 Phase B 완료 조건) ─────────────────────────

def _load_ticker_yahoo_map() -> list[dict[str, str]]:
    """``data/ticker_to_yahoo_map.csv`` 읽기.

    컬럼: ticker, market, yahoo_ticker, name
    """
    path = os.path.join(DATA_DIR, 'ticker_to_yahoo_map.csv')
    rows: list[dict[str, str]] = []
    if not os.path.isfile(path):
        return rows
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = (row.get('ticker') or '').strip().zfill(6)
                market = (row.get('market') or '').strip().upper()
                yahoo = (row.get('yahoo_ticker') or '').strip().upper()
                name = (row.get('name') or '').strip()
                if not ticker or not name:
                    continue
                rows.append({'ticker': ticker, 'market': market, 'yahoo_ticker': yahoo, 'name': name})
    except (OSError, csv.Error, UnicodeDecodeError):
        return []
    return rows


def _load_dart_corp_codes() -> dict[str, str]:
    """``data/dart_corp_codes.json`` 읽기. ``{ticker: corp_code}`` dict."""
    path = os.path.join(DATA_DIR, 'dart_corp_codes.json')
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k).strip().zfill(6): str(v).strip() for k, v in data.items() if v}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def populate_from_sources() -> dict[str, int]:
    """ticker_to_yahoo_map.csv + dart_corp_codes.json 으로 entities/aliases/external_ids 초기 적재.

    멱등. 같은 ticker 재호출 시 updated_at 만 갱신.
    """
    rows = _load_ticker_yahoo_map()
    corp_map = _load_dart_corp_codes()
    now = time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime())

    conn = _connect(read_only=False)
    init_schema(conn)

    inserted_entities = 0
    inserted_aliases = 0
    inserted_external = 0
    try:
        cur = conn.cursor()
        for row in rows:
            ticker = row['ticker']
            name = row['name']
            market = row['market']
            yahoo = row['yahoo_ticker']
            entity_id = f"kr:{ticker}"
            chosung = extract_chosung(name)

            cur.execute(
                """
                INSERT INTO entities (
                    entity_id, type, name_ko, name_en, symbol, market, exchange, country,
                    sector_id, extra_json, chosung_ko, created_at, updated_at
                ) VALUES (?, 'company', ?, NULL, ?, ?, ?, 'KR', NULL, '{}', ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    name_ko = excluded.name_ko,
                    symbol  = excluded.symbol,
                    market  = excluded.market,
                    exchange = excluded.exchange,
                    chosung_ko = excluded.chosung_ko,
                    updated_at = excluded.updated_at
                """,
                (entity_id, name, ticker, market, market, chosung, now, now),
            )
            inserted_entities += 1

            # alias: 정식 한글명
            cur.execute(
                """
                INSERT OR IGNORE INTO entity_aliases (alias, entity_id, lang, source, confidence)
                VALUES (?, ?, 'ko', 'ticker_map', 1.0)
                """,
                (name, entity_id),
            )
            inserted_aliases += cur.rowcount

            # alias: 초성 (검색 도움)
            if chosung and not is_chosung_only(name):
                cur.execute(
                    """
                    INSERT OR IGNORE INTO entity_aliases (alias, entity_id, lang, source, confidence)
                    VALUES (?, ?, 'chosung', 'derived', 0.7)
                    """,
                    (chosung, entity_id),
                )
                inserted_aliases += cur.rowcount

            # external_id: yahoo
            if yahoo:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO entity_external_ids (entity_id, id_type, id_value)
                    VALUES (?, 'yahoo_ticker', ?)
                    """,
                    (entity_id, yahoo),
                )
                inserted_external += 1

            # external_id: corp_code
            corp_code = corp_map.get(ticker)
            if corp_code:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO entity_external_ids (entity_id, id_type, id_value)
                    VALUES (?, 'corp_code', ?)
                    """,
                    (entity_id, corp_code),
                )
                inserted_external += 1

        # 수동 큐레이션 별칭
        from app.services.mirofish.graphrag.korean import iter_alias_records
        for alias, entity_id, source in iter_alias_records():
            cur.execute(
                """
                INSERT OR IGNORE INTO entity_aliases (alias, entity_id, lang, source, confidence)
                VALUES (?, ?, 'ko', ?, 0.9)
                """,
                (alias, entity_id, source),
            )
            inserted_aliases += cur.rowcount

        conn.commit()
    finally:
        conn.close()

    return {
        'entities_upserted': inserted_entities,
        'aliases_added': inserted_aliases,
        'external_ids_upserted': inserted_external,
        'source_ticker_rows': len(rows),
        'source_corp_codes': len(corp_map),
    }


# ── Resolve (Phase B 핵심) ───────────────────────────────────────────

def _row_to_match(row: sqlite3.Row, confidence: float, reason: str) -> dict[str, Any]:
    return {
        'entity_id': row['entity_id'],
        'type': row['type'],
        'name': row['name_ko'] or row['name_en'] or row['symbol'],
        'name_ko': row['name_ko'],
        'name_en': row['name_en'],
        'symbol': row['symbol'],
        'market': row['market'],
        'exchange': row['exchange'],
        'country': row['country'],
        'confidence': round(float(confidence), 4),
        'match_reason': reason,
    }


def _attach_external_ids(conn: sqlite3.Connection, matches: list[dict[str, Any]]) -> None:
    if not matches:
        return
    placeholders = ','.join('?' * len(matches))
    ids = [m['entity_id'] for m in matches]
    rows = conn.execute(
        f"SELECT entity_id, id_type, id_value FROM entity_external_ids WHERE entity_id IN ({placeholders})",
        ids,
    ).fetchall()
    by_entity: dict[str, dict[str, str]] = {}
    for r in rows:
        by_entity.setdefault(r['entity_id'], {})[r['id_type']] = r['id_value']
    for m in matches:
        ext = by_entity.get(m['entity_id'], {})
        m['ids'] = {
            'ticker_kr': m['symbol'] if m['country'] == 'KR' else None,
            'yahoo_ticker': ext.get('yahoo_ticker'),
            'corp_code': ext.get('corp_code'),
            'figi': ext.get('figi'),
            'isin': ext.get('isin'),
        }


def resolve(query: str, hint_market: str | None = None, limit: int = 5) -> dict[str, Any]:
    """입력을 표준 entity 로 변환.

    Returns::

        {
          "query": "두산",
          "matches": [{...}, ...],
          "asof": "...",
          "source": "ticker_map+dart_codes"
        }
    """
    asof = time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime())
    norm = normalize_query(query)
    response = {
        'query': query,
        'normalized': norm,
        'matches': [],
        'asof': asof,
        'source': 'sqlite:entities.db',
    }
    if not norm:
        return response

    if not os.path.exists(ENTITIES_DB):
        response['error'] = 'entities.db not initialized — run scripts/graphrag_init_entities.py'
        return response

    conn = _connect(read_only=True)
    conn.row_factory = sqlite3.Row
    try:
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(rows: list[sqlite3.Row], confidence: float, reason: str) -> None:
            for r in rows:
                if r['entity_id'] in seen:
                    continue
                seen.add(r['entity_id'])
                candidates.append(_row_to_match(r, confidence, reason))

        # 1) ticker direct (한국 6자리)
        if norm.isdigit() and len(norm) == 6:
            rows = conn.execute(
                "SELECT * FROM entities WHERE symbol = ? LIMIT ?",
                (norm, limit),
            ).fetchall()
            _add(rows, 1.0, 'ticker_direct')

        # 2) yahoo ticker (예: 005930.KS)
        if '.' in norm and len(candidates) < limit:
            eid = yahoo_to_entity_id(norm)
            if eid:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE entity_id = ?",
                    (eid,),
                ).fetchall()
                _add(rows, 0.99, 'yahoo_ticker')

        # 3) corp_code 역방향 (8자리 숫자)
        if norm.isdigit() and len(norm) == 8 and len(candidates) < limit:
            rows = conn.execute(
                """
                SELECT e.* FROM entities e
                JOIN entity_external_ids x ON x.entity_id = e.entity_id
                WHERE x.id_type = 'corp_code' AND x.id_value = ?
                LIMIT ?
                """,
                (norm, limit - len(candidates)),
            ).fetchall()
            _add(rows, 0.99, 'corp_code_reverse')

        # 4) exact alias 매치
        if len(candidates) < limit:
            rows = conn.execute(
                """
                SELECT e.*, a.confidence AS alias_confidence
                FROM entities e
                JOIN entity_aliases a ON a.entity_id = e.entity_id
                WHERE LOWER(a.alias) = LOWER(?)
                LIMIT ?
                """,
                (norm, limit - len(candidates)),
            ).fetchall()
            for r in rows:
                if r['entity_id'] in seen:
                    continue
                seen.add(r['entity_id'])
                candidates.append(_row_to_match(r, max(0.95, r['alias_confidence']), 'exact_alias'))

        # 5) exact name (대소문자 무시)
        if len(candidates) < limit:
            rows = conn.execute(
                "SELECT * FROM entities WHERE LOWER(name_ko) = LOWER(?) OR LOWER(name_en) = LOWER(?) LIMIT ?",
                (norm, norm, limit - len(candidates)),
            ).fetchall()
            _add(rows, 0.97, 'exact_name')

        # 6) 초성 매치 (입력이 초성-only 일 때만)
        if is_chosung_only(norm) and len(candidates) < limit:
            rows = conn.execute(
                "SELECT * FROM entities WHERE chosung_ko = ? LIMIT ?",
                (norm, limit - len(candidates)),
            ).fetchall()
            _add(rows, 0.85, 'chosung_exact')
            # 초성 prefix
            if len(candidates) < limit:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE chosung_ko LIKE ? AND chosung_ko != ? LIMIT ?",
                    (norm + '%', norm, limit - len(candidates)),
                ).fetchall()
                _add(rows, 0.75, 'chosung_prefix')

        # 7) prefix name
        if len(candidates) < limit:
            rows = conn.execute(
                "SELECT * FROM entities WHERE name_ko LIKE ? AND LOWER(name_ko) != LOWER(?) LIMIT ?",
                (norm + '%', norm, limit - len(candidates)),
            ).fetchall()
            _add(rows, 0.85, 'prefix_name')

        # 8) fuzzy match (남는 슬롯이 있고 후보가 적을 때)
        if len(candidates) < limit:
            remaining = limit - len(candidates)
            all_rows = conn.execute(
                "SELECT * FROM entities WHERE name_ko IS NOT NULL"
            ).fetchall()
            fuzzy_scored: list[tuple[float, sqlite3.Row]] = []
            for r in all_rows:
                if r['entity_id'] in seen:
                    continue
                ratio = SequenceMatcher(None, norm.lower(), (r['name_ko'] or '').lower()).ratio()
                if ratio >= 0.55:
                    fuzzy_scored.append((ratio, r))
            fuzzy_scored.sort(key=lambda x: x[0], reverse=True)
            for ratio, r in fuzzy_scored[:remaining]:
                if r['entity_id'] in seen:
                    continue
                seen.add(r['entity_id'])
                candidates.append(_row_to_match(r, round(0.5 + ratio * 0.3, 4), 'fuzzy'))

        # 시장 힌트 보너스 (정확도 보정 — 동일 점수일 때 우선)
        if hint_market:
            hm = hint_market.upper()
            for m in candidates:
                if (m.get('market') or '').upper() == hm or (m.get('country') or '').upper() == hm:
                    m['confidence'] = min(1.0, m['confidence'] + 0.01)

        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        _attach_external_ids(conn, candidates[:limit])
        response['matches'] = candidates[:limit]
    finally:
        conn.close()

    return response


def get_entity(entity_id: str) -> dict[str, Any] | None:
    """단일 entity 조회 + external_ids + aliases."""
    if not entity_id or not os.path.exists(ENTITIES_DB):
        return None
    conn = _connect(read_only=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            return None
        ext = conn.execute(
            "SELECT id_type, id_value FROM entity_external_ids WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()
        aliases = conn.execute(
            "SELECT alias, lang, source, confidence FROM entity_aliases WHERE entity_id = ? ORDER BY confidence DESC LIMIT 20",
            (entity_id,),
        ).fetchall()
        return {
            'entity_id': row['entity_id'],
            'type': row['type'],
            'name_ko': row['name_ko'],
            'name_en': row['name_en'],
            'symbol': row['symbol'],
            'market': row['market'],
            'exchange': row['exchange'],
            'country': row['country'],
            'sector_id': row['sector_id'],
            'chosung_ko': row['chosung_ko'],
            'ids': {r['id_type']: r['id_value'] for r in ext},
            'aliases': [
                {'alias': a['alias'], 'lang': a['lang'], 'source': a['source'], 'confidence': a['confidence']}
                for a in aliases
            ],
        }
    finally:
        conn.close()
