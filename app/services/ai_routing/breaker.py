"""Persistent circuit breaker isolated by provider, modality, and model tier."""

from __future__ import annotations

import time
from collections.abc import Callable
from math import isfinite

from .contracts import ProviderErrorClass
from .providers import MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS
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
    DEFAULT_PROVIDER_DEADLINE_SECONDS = MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS
    DEFAULT_PROBE_MARGIN_SECONDS = 30.0
    DEFAULT_PROBE_LEASE_SECONDS = (
        DEFAULT_PROVIDER_DEADLINE_SECONDS + DEFAULT_PROBE_MARGIN_SECONDS
    )

    def __init__(
        self,
        store: RoutingStore | None = None,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        probe_lease_seconds: float = DEFAULT_PROBE_LEASE_SECONDS,
        max_provider_deadline_seconds: float = DEFAULT_PROVIDER_DEADLINE_SECONDS,
        probe_margin_seconds: float = DEFAULT_PROBE_MARGIN_SECONDS,
        failure_window_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        numeric_config = (
            float(cooldown_seconds),
            float(probe_lease_seconds),
            float(max_provider_deadline_seconds),
            float(probe_margin_seconds),
            float(failure_window_seconds),
        )
        if (
            failure_threshold <= 0
            or cooldown_seconds < 0
            or max_provider_deadline_seconds <= 0
            or probe_margin_seconds < 0
            or failure_window_seconds <= 0
            or not all(isfinite(value) for value in numeric_config)
        ):
            raise ValueError("invalid circuit breaker configuration")
        if probe_lease_seconds < max_provider_deadline_seconds + probe_margin_seconds:
            raise ValueError("probe lease must cover provider deadline plus margin")
        self.store = store or default_store()
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.probe_lease_seconds = probe_lease_seconds
        self.probe_margin_seconds = probe_margin_seconds
        self.failure_window_seconds = failure_window_seconds
        self.clock = clock

    def validate_adapter_deadlines(self, deadlines: list[float]) -> None:
        normalized = [float(deadline) for deadline in deadlines]
        if any(deadline <= 0 or not isfinite(deadline) for deadline in normalized):
            raise ValueError("provider deadlines must be positive and finite")
        if normalized and self.probe_lease_seconds < max(normalized) + self.probe_margin_seconds:
            raise ValueError("probe lease must cover provider deadline plus margin")

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
            # The transport completed successfully. Local validation still rejects
            # the response in the router, but it must not leave a probe occupied.
            self.record_success(provider, modality, model_tier)
            return
        now = self.clock()
        key = self._key(provider, modality, model_tier)
        with self.store.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT state, failure_count, updated_at FROM circuit_breakers "
                "WHERE provider = ? AND modality = ? AND model_tier = ?",
                key,
            ).fetchone()
            previous_count = int(row["failure_count"]) if row is not None else 0
            if (
                row is not None
                and error_class in _TRANSIENT
                and now - float(row["updated_at"]) >= self.failure_window_seconds
            ):
                previous_count = 0
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
