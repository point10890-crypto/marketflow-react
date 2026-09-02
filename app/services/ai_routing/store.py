"""Single SQLite schema and transaction boundary for AI routing state."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.utils.paths import DATA_DIR


DEFAULT_DB_PATH = Path(DATA_DIR) / "ai_routing" / "usage.sqlite3"
_SCHEMA_LOCK = threading.Lock()


class RoutingStore:
    """Own the shared usage, budget, and breaker SQLite database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        if self._initialized:
            return
        with _SCHEMA_LOCK:
            if self._initialized:
                return
            connection = self._connect()
            try:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS provider_attempts (
                        event_ts_utc TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        run_id TEXT,
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        attempt_number INTEGER NOT NULL,
                        selected INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        latency_ms REAL NOT NULL,
                        max_output_tokens INTEGER NOT NULL,
                        input_tokens INTEGER,
                        cached_input_tokens INTEGER,
                        uncached_input_tokens INTEGER,
                        output_tokens INTEGER,
                        reasoning_tokens INTEGER,
                        total_tokens INTEGER,
                        raw_total_tokens INTEGER,
                        usage_mapping_version TEXT NOT NULL,
                        usage_mapping_status TEXT NOT NULL,
                        estimated_cost_usd TEXT,
                        pricing_version TEXT,
                        usage_estimated INTEGER NOT NULL,
                        error_class TEXT,
                        fallback_from TEXT,
                        breaker_state TEXT NOT NULL,
                        cache_hit INTEGER NOT NULL,
                        symbol TEXT,
                        market TEXT,
                        caller_endpoint TEXT,
                        PRIMARY KEY (request_id, attempt_number)
                    );
                    CREATE INDEX IF NOT EXISTS idx_provider_attempts_event
                        ON provider_attempts(event_ts_utc);
                    CREATE INDEX IF NOT EXISTS idx_provider_attempts_summary
                        ON provider_attempts(provider, model, caller_endpoint, operation, event_ts_utc);

                    CREATE TABLE IF NOT EXISTS budget_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        pool TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        reserved_calls INTEGER NOT NULL,
                        reserved_input_tokens INTEGER NOT NULL,
                        reserved_output_tokens INTEGER NOT NULL,
                        actual_calls INTEGER,
                        actual_input_tokens INTEGER,
                        actual_output_tokens INTEGER,
                        status TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        settled_at_utc TEXT,
                        UNIQUE (run_id, request_id, pool, provider)
                    );
                    CREATE INDEX IF NOT EXISTS idx_budget_reservations_run
                        ON budget_reservations(run_id, pool, provider, status);

                    CREATE TABLE IF NOT EXISTS circuit_breakers (
                        provider TEXT NOT NULL,
                        modality TEXT NOT NULL,
                        model_tier TEXT NOT NULL,
                        state TEXT NOT NULL,
                        failure_count INTEGER NOT NULL,
                        opened_at REAL,
                        last_error_class TEXT,
                        probe_in_flight INTEGER NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (provider, modality, model_tier)
                    );
                    """
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(provider_attempts)").fetchall()
                }
                migrations = {
                    "raw_total_tokens": "INTEGER",
                    "usage_mapping_version": "TEXT NOT NULL DEFAULT 'legacy-unknown'",
                    "usage_mapping_status": "TEXT NOT NULL DEFAULT 'unverified'",
                }
                for name, declaration in migrations.items():
                    if name not in columns:
                        connection.execute(
                            f"ALTER TABLE provider_attempts ADD COLUMN {name} {declaration}"
                        )
                self._initialized = True
            finally:
                connection.close()

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def default_store() -> RoutingStore:
    """Resolve the default path at call time so tests can monkeypatch it."""
    return RoutingStore(DEFAULT_DB_PATH)
