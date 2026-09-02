"""Process-safe cache claims for immutable TradingAgents run artifacts."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4


@dataclass(frozen=True)
class CacheClaim:
    owner: bool
    status: str
    source_run_id: str | None = None
    artifact_path: str | None = None


class RunCache:
    def __init__(self, db_path: str, *, lease_seconds: float = 120.0, wait_seconds: float = 30.0) -> None:
        self.db_path = os.path.abspath(db_path)
        self.lease_seconds = max(1.0, float(lease_seconds))
        self.wait_seconds = max(0.1, float(wait_seconds))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS run_cache (
                    cache_key TEXT PRIMARY KEY, status TEXT NOT NULL,
                    owner_id TEXT NOT NULL, lease_until REAL NOT NULL,
                    source_run_id TEXT, artifact_path TEXT, completed_at TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS candidate_admissions (
                    run_id TEXT NOT NULL, symbol TEXT NOT NULL, admission_id TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, symbol)
                )
            """)

    def claim(self, cache_key: str, owner_id: str) -> CacheClaim:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM run_cache WHERE cache_key=?", (cache_key,)).fetchone()
            if row and row["status"] == "completed" and row["artifact_path"] and os.path.isfile(row["artifact_path"]):
                connection.commit()
                return CacheClaim(False, "completed", row["source_run_id"], row["artifact_path"])
            if row is None:
                connection.execute(
                    "INSERT INTO run_cache(cache_key,status,owner_id,lease_until) VALUES(?, 'running', ?, ?)",
                    (cache_key, owner_id, now + self.lease_seconds),
                )
                connection.commit()
                return CacheClaim(True, "running")
            if float(row["lease_until"] or 0) <= now:
                connection.execute(
                    "UPDATE run_cache SET status='running',owner_id=?,lease_until=?,source_run_id=NULL,artifact_path=NULL WHERE cache_key=?",
                    (owner_id, now + self.lease_seconds, cache_key),
                )
                connection.commit()
                return CacheClaim(True, "recovered")
            connection.commit()
            return CacheClaim(False, "running")

    def publish(self, cache_key: str, owner_id: str, source_run_id: str, artifact_path: str) -> None:
        if not os.path.isfile(artifact_path):
            raise FileNotFoundError(artifact_path)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE run_cache SET status='completed',source_run_id=?,artifact_path=?,completed_at=?,lease_until=0 "
                "WHERE cache_key=? AND owner_id=? AND status='running'",
                (source_run_id, os.path.abspath(artifact_path), datetime.now(timezone.utc).isoformat(), cache_key, owner_id),
            )
            connection.commit()

    def abandon(self, cache_key: str, owner_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM run_cache WHERE cache_key=? AND owner_id=? AND status='running'", (cache_key, owner_id))

    @staticmethod
    def load(claim: CacheClaim) -> dict[str, Any] | None:
        if not claim.artifact_path:
            return None
        try:
            with open(claim.artifact_path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return copy.deepcopy(value) if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def wait(self, cache_key: str, owner_id: str) -> CacheClaim:
        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            claim = self.claim(cache_key, owner_id)
            if claim.owner or claim.status == "completed":
                return claim
            time.sleep(0.05)
        return CacheClaim(False, "in_progress")


def execute_cached(
    cache: RunCache, cache_key: str, owner_id: str,
    producer: Callable[[], dict[str, Any]], artifact_path: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    claim = cache.claim(cache_key, owner_id)
    if not claim.owner and claim.status == "running":
        claim = cache.wait(cache_key, owner_id)
    if not claim.owner:
        cached = cache.load(claim)
        if cached is not None:
            cached["cache_hit"] = True
            cached["source_run_id"] = claim.source_run_id
            return cached
        return {"analysis_status": "IN_PROGRESS", "cache_hit": False, "source_run_id": claim.source_run_id}
    try:
        result = producer()
        status = str(result.get("analysis_status") or "")
        if status in {"SUCCESS_PRIMARY", "SUCCESS_FALLBACK"}:
            cache.publish(cache_key, owner_id, str(result.get("id")), artifact_path(result))
        else:
            cache.abandon(cache_key, owner_id)
        return result
    except Exception:
        cache.abandon(cache_key, owner_id)
        raise


class AdmissionManager:
    """Atomic candidate-count admission; it never owns provider token/cost debit."""

    def __init__(self, db_path: str) -> None:
        self.cache = RunCache(db_path)

    def admit(
        self, run_id: str, candidates: list[dict[str, Any]], *, limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        admitted: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        limit = max(0, int(limit))
        with self.cache._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_count = int(connection.execute(
                "SELECT COUNT(*) FROM candidate_admissions WHERE run_id=? AND status='admitted'",
                (run_id,),
            ).fetchone()[0])
            for candidate in candidates:
                symbol = str(candidate.get("symbol") or "").strip()
                row = connection.execute(
                    "SELECT * FROM candidate_admissions WHERE run_id=? AND symbol=?", (run_id, symbol)
                ).fetchone()
                if row is not None:
                    status, admission_id, reason = row["status"], row["admission_id"], row["reason"]
                else:
                    status = "admitted" if symbol and existing_count < limit else "deferred"
                    reason = None if status == "admitted" else ("missing_symbol" if not symbol else "candidate_limit")
                    admission_id = str(uuid4())
                    connection.execute(
                        "INSERT INTO candidate_admissions VALUES(?,?,?,?,?,?)",
                        (run_id, symbol, admission_id, status, reason, datetime.now(timezone.utc).isoformat()),
                    )
                    if status == "admitted":
                        existing_count += 1
                record = {"symbol": symbol, "admission_id": admission_id, "status": status, "reason": reason}
                records.append(record)
                if status == "admitted":
                    admitted.append({**candidate, "admission_id": admission_id})
            connection.commit()
        return admitted, {
            "scope": "candidate_admission", "provider_budget_owner": "central_router",
            "admitted": len(admitted), "deferred": sum(r["status"] == "deferred" for r in records),
            "rejected": sum(r["status"] == "rejected" for r in records), "records": records,
        }
