"""Atomic per-run fallback budget reservation and settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .contracts import Operation, TokenUsage
from .store import RoutingStore, default_store


@dataclass(frozen=True)
class BudgetLimits:
    max_calls: int = 5
    max_input_tokens: int = 30_000
    max_output_tokens: int = 6_000
    low_priority_cutoff: float = 0.8


@dataclass(frozen=True)
class BudgetReservation:
    approved: bool
    reservation_id: str | None = None
    reason: str | None = None
    already_reserved: bool = False
    acquired_by_caller: bool = False


@dataclass(frozen=True)
class BudgetSnapshot:
    used_calls: int
    used_input_tokens: int
    used_output_tokens: int
    remaining_calls: int
    remaining_input_tokens: int
    remaining_output_tokens: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BudgetManager:
    """Reserve an approved OpenAI fallback before any logical provider call."""

    _LOW_PRIORITY = {Operation.BULK_TEXT, Operation.COMPACT_DEBATE, Operation.VISION}

    def __init__(
        self,
        store: RoutingStore | None = None,
        *,
        limits: BudgetLimits | None = None,
        pool: str = "automatic",
        provider: str = "openai",
    ) -> None:
        self.store = store or default_store()
        self.limits = limits or BudgetLimits()
        self.pool = pool
        self.provider = provider

    def _used(self, connection, run_id: str) -> tuple[int, int, int]:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status = 'settled'
                    THEN COALESCE(actual_calls, reserved_calls) ELSE reserved_calls END), 0),
                COALESCE(SUM(CASE WHEN status = 'settled'
                    THEN COALESCE(actual_input_tokens, reserved_input_tokens)
                    ELSE reserved_input_tokens END), 0),
                COALESCE(SUM(CASE WHEN status = 'settled'
                    THEN COALESCE(actual_output_tokens, reserved_output_tokens)
                    ELSE reserved_output_tokens END), 0)
            FROM budget_reservations
            WHERE run_id = ? AND pool = ? AND provider = ? AND status != 'released'
            """,
            (run_id, self.pool, self.provider),
        ).fetchone()
        return int(row[0]), int(row[1]), int(row[2])

    def reserve(
        self,
        *,
        run_id: str,
        request_id: str,
        operation: Operation | str,
        input_tokens: int,
        output_tokens: int,
        calls: int = 1,
    ) -> BudgetReservation:
        if min(input_tokens, output_tokens, calls) < 0 or calls == 0:
            raise ValueError("reservation amounts must be non-negative and calls positive")
        operation = Operation(operation)
        with self.store.transaction(write=True) as connection:
            existing = connection.execute(
                """
                SELECT reservation_id, status FROM budget_reservations
                WHERE run_id = ? AND request_id = ? AND pool = ? AND provider = ?
                """,
                (run_id, request_id, self.pool, self.provider),
            ).fetchone()
            if existing is not None:
                return BudgetReservation(
                    approved=existing["status"] != "released",
                    reservation_id=existing["reservation_id"],
                    already_reserved=True,
                    acquired_by_caller=False,
                )

            used_calls, used_input, used_output = self._used(connection, run_id)
            ratios = (
                used_calls / self.limits.max_calls if self.limits.max_calls else 1.0,
                used_input / self.limits.max_input_tokens if self.limits.max_input_tokens else 1.0,
                used_output / self.limits.max_output_tokens if self.limits.max_output_tokens else 1.0,
            )
            if operation in self._LOW_PRIORITY and max(ratios) >= self.limits.low_priority_cutoff:
                return BudgetReservation(False, reason="priority_reserve")
            if (
                used_calls + calls > self.limits.max_calls
                or used_input + input_tokens > self.limits.max_input_tokens
                or used_output + output_tokens > self.limits.max_output_tokens
            ):
                return BudgetReservation(False, reason="hard_cap")

            reservation_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO budget_reservations (
                    reservation_id, run_id, request_id, pool, provider, operation,
                    reserved_calls, reserved_input_tokens, reserved_output_tokens,
                    status, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?)
                """,
                (
                    reservation_id,
                    run_id,
                    request_id,
                    self.pool,
                    self.provider,
                    operation.value,
                    calls,
                    input_tokens,
                    output_tokens,
                    _utc_now(),
                ),
            )
            return BudgetReservation(True, reservation_id=reservation_id, acquired_by_caller=True)

    def settle(self, reservation_id: str | None, usage: TokenUsage, *, calls: int = 1) -> None:
        if not reservation_id:
            return
        with self.store.transaction(write=True) as connection:
            connection.execute(
                """
                UPDATE budget_reservations
                SET actual_calls = ?, actual_input_tokens = COALESCE(?, reserved_input_tokens),
                    actual_output_tokens = COALESCE(?, reserved_output_tokens),
                    status = 'settled', settled_at_utc = ?
                WHERE reservation_id = ? AND status = 'reserved'
                """,
                (calls, usage.input_tokens, usage.output_tokens, _utc_now(), reservation_id),
            )

    def release(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return
        with self.store.transaction(write=True) as connection:
            connection.execute(
                "UPDATE budget_reservations SET status = 'released', settled_at_utc = ? "
                "WHERE reservation_id = ? AND status = 'reserved'",
                (_utc_now(), reservation_id),
            )

    def snapshot(self, run_id: str) -> BudgetSnapshot:
        with self.store.transaction() as connection:
            calls, input_tokens, output_tokens = self._used(connection, run_id)
        return BudgetSnapshot(
            used_calls=calls,
            used_input_tokens=input_tokens,
            used_output_tokens=output_tokens,
            remaining_calls=max(0, self.limits.max_calls - calls),
            remaining_input_tokens=max(0, self.limits.max_input_tokens - input_tokens),
            remaining_output_tokens=max(0, self.limits.max_output_tokens - output_tokens),
        )
