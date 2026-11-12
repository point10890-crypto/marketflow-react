"""league.db 스키마와 연결. forecasts 와 capsules 는 트리거로 수정·삭제를 막는다."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.services.forecast_league import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasters (
  forecaster_id TEXT NOT NULL, version TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('engine','agent','baseline')),
  probability_source TEXT NOT NULL CHECK (probability_source IN ('native','derived')),
  registered_at TEXT NOT NULL,
  PRIMARY KEY (forecaster_id, version)
);
CREATE TABLE IF NOT EXISTS capsules (
  capsule_hash TEXT PRIMARY KEY, payload BLOB NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
  forecast_id TEXT PRIMARY KEY, forecaster_id TEXT NOT NULL, version TEXT NOT NULL,
  stock_code TEXT NOT NULL, asof_ts TEXT NOT NULL, event_id TEXT NOT NULL,
  probability REAL NOT NULL CHECK (probability >= 0.02 AND probability <= 0.98), raw_score REAL, capsule_hash TEXT NOT NULL,
  source_ref TEXT NOT NULL DEFAULT '', official INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE (forecaster_id, version, stock_code, asof_ts, event_id),
  FOREIGN KEY (forecaster_id, version) REFERENCES forecasters (forecaster_id, version),
  FOREIGN KEY (capsule_hash) REFERENCES capsules (capsule_hash)
);
CREATE INDEX IF NOT EXISTS ix_forecasts_asof ON forecasts (asof_ts);
CREATE TABLE IF NOT EXISTS abstentions (
  forecaster_id TEXT NOT NULL, version TEXT NOT NULL, stock_code TEXT NOT NULL,
  asof_ts TEXT NOT NULL, event_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (forecaster_id, version, stock_code, asof_ts, event_id)
);
CREATE TABLE IF NOT EXISTS resolutions (
  forecast_id TEXT PRIMARY KEY REFERENCES forecasts (forecast_id),
  status TEXT NOT NULL CHECK (status IN ('resolved','void')),
  outcome INTEGER, resolved_at TEXT NOT NULL,
  entry_date TEXT, entry_price REAL, exit_date TEXT, exit_price REAL,
  exit_reason TEXT, net_return REAL, price_source_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scorecards (
  forecaster_id TEXT NOT NULL, version TEXT NOT NULL, event_id TEXT NOT NULL,
  window_id TEXT NOT NULL, status TEXT NOT NULL, n_resolved INTEGER NOT NULL,
  metrics_json TEXT NOT NULL, computed_at TEXT NOT NULL,
  PRIMARY KEY (forecaster_id, version, event_id, window_id)
);
CREATE TABLE IF NOT EXISTS bars (
  stock_code TEXT NOT NULL, session_date TEXT NOT NULL, basis TEXT NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  captured_at TEXT NOT NULL, evidence_hash TEXT,
  PRIMARY KEY (stock_code, session_date, basis)
);
CREATE INDEX IF NOT EXISTS ix_bars_basis_date ON bars (basis, session_date);
CREATE TABLE IF NOT EXISTS jobs (
  job_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, args TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  not_before TEXT NOT NULL, result TEXT, last_error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS forecasts_no_update BEFORE UPDATE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_no_delete BEFORE DELETE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS capsules_no_update BEFORE UPDATE ON capsules
BEGIN SELECT RAISE(ABORT, 'capsules are append-only'); END;
CREATE TRIGGER IF NOT EXISTS capsules_no_delete BEFORE DELETE ON capsules
BEGIN SELECT RAISE(ABORT, 'capsules are append-only'); END;
"""


@contextmanager
def connect(path: str | None = None) -> Iterator[sqlite3.Connection]:
    """정상 종료 시 커밋, 예외 시 롤백."""
    target = path or paths.db_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA foreign_keys=ON')
        # REPLACE 충돌 해소가 지우는 행에도 DELETE 트리거가 걸리게 한다 (INSERT OR REPLACE 우회 차단).
        conn.execute('PRAGMA recursive_triggers=ON')
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
