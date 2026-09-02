"""Persistent circuit breaker isolated by provider, modality, and model tier."""

from __future__ import annotations

import time
from collections.abc import Callable

from .contracts import ProviderErrorClass
from .store import RoutingStore, default_store


_IMMEDIATE_OPEN = {
    ProviderErrorClass.AUTHENTICATION,
    ProviderErrorClass.INSUFFICIENT_BALANCE,
    ProviderErrorClass.MODEL_UNAVAILABLE,
}
_TRANSIENT = {
    ProviderErrorClass.RATE_LIMIT,
    ProviderErrorClass.TIMEOUT,
    ProviderErrorClass.CONNECTION,
    ProviderErrorClass.SERVER_ERROR,
    ProviderErrorClass.UNKNOWN,
}
_NON_BREAKING = {
    ProviderErrorClass.INVALID_JSON,
    ProviderErrorClass.NUMERIC_MISMATCH,
    ProviderErrorClass.EMPTY,
    ProviderErrorClass.REFUSAL,
}


class CircuitBreaker:
    def __init__(
        self,
        store: RoutingStore | None = None,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        probe_lease_seconds: float = 120.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if failure_threshold <= 0 or cooldown_seconds < 0:
            raise ValueError("invalid circuit breaker configuration")
        self.store = store or default_store()
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.probe_lease_seconds = probe_lease_seconds
        self.clock = clock

    @staticmethod
    def _key(provider: str, modality: str, model_tier: str) -> tuple[str, str, str]:
        return provider.lower(), modality.lower(), model_tier.lower()

    def state(self, provider: str, modality: str, model_tier: str) -> str:
        key = self._key(provider, modality, model_tier)
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT state FROM circuit_breakers WHERE provider = ? AND modality = ? AND model_tier = ?",
                key,
            ).fetchone()
        return str(row["state"]) if row is not None else "closed"

    def allow(self, provider: str, modality: str, model_tier: str) -> bool:
        key = self._key(provider, modality, model_tier)
        now = self.clock()
        with self.store.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM circuit_breakers WHERE provider = ? AND modality = ? AND model_tier = ?",
                key,
            ).fetchone()
            if row is None or row["state"] == "closed":
                return True
            if row["state"] == "half_open":
                if now - float(row["updated_at"]) < self.probe_lease_seconds:
                    return False
                cursor = connection.execute(
                    """
                    UPDATE circuit_breakers SET updated_at = ?, probe_in_flight = 1
                    WHERE provider = ? AND modality = ? AND model_tier = ?
                      AND state = 'half_open' AND updated_at = ?
                    """,
                    (now, *key, row["updated_at"]),
                )
                return cursor.rowcount == 1
            if row["opened_at"] is None or now - float(row["opened_at"]) < self.cooldown_seconds:
                return False
            cursor = connection.execute(
                """
                UPDATE circuit_breakers
                SET state = 'half_open', probe_in_flight = 1, updated_at = ?
                WHERE provider = ? AND modality = ? AND model_tier = ? AND state = 'open'
                """,
                (now, *key),
            )
            return cursor.rowcount == 1

    is_call_allowed = allow

    def record_failure(
        self,
        provider: str,
        modality: str,
        model_tier: str,
        error_class: ProviderErrorClass | str,
    ) -> None:
        error_class = ProviderErrorClass(error_class)
        if error_class in _NON_BREAKING:
            return
        now = self.clock()
        key = self._key(provider, modality, model_tier)
        with self.store.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT state, failure_count FROM circuit_breakers "
                "WHERE provider = ? AND modality = ? AND model_tier = ?",
                key,
            ).fetchone()
            previous_count = int(row["failure_count"]) if row is not None else 0
            previous_state = str(row["state"]) if row is not None else "closed"
            count = previous_count + 1 if error_class in _TRANSIENT else previous_count
            should_open = (
                error_class in _IMMEDIATE_OPEN
                or previous_state == "half_open"
                or (error_class in _TRANSIENT and count >= self.failure_threshold)
            )
            state = "open" if should_open else "closed"
            opened_at = now if should_open else None
            connection.execute(
                """
                INSERT INTO circuit_breakers (
                    provider, modality, model_tier, state, failure_count, opened_at,
                    last_error_class, probe_in_flight, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(provider, modality, model_tier) DO UPDATE SET
                    state = excluded.state,
                    failure_count = excluded.failure_count,
                    opened_at = excluded.opened_at,
                    last_error_class = excluded.last_error_class,
                    probe_in_flight = 0,
                    updated_at = excluded.updated_at
                """,
                (*key, state, count, opened_at, error_class.value, now),
            )

    def record_success(self, provider: str, modality: str, model_tier: str) -> None:
        key = self._key(provider, modality, model_tier)
        now = self.clock()
        with self.store.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO circuit_breakers (
                    provider, modality, model_tier, state, failure_count, opened_at,
                    last_error_class, probe_in_flight, updated_at
                ) VALUES (?, ?, ?, 'closed', 0, NULL, NULL, 0, ?)
                ON CONFLICT(provider, modality, model_tier) DO UPDATE SET
                    state = 'closed', failure_count = 0, opened_at = NULL,
                    last_error_class = NULL, probe_in_flight = 0, updated_at = excluded.updated_at
                """,
                (*key, now),
            )
