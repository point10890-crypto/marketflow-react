"""Atomic per-run fallback budget reservation and settlement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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


def _utc_billing_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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

    @staticmethod
    def _daily_limit() -> tuple[Decimal | None, str | None]:
        raw = os.getenv("AI_OPENAI_DAILY_BUDGET_USD")
        if raw is None or not raw.strip():
            return None, None
        try:
            value = Decimal(raw.strip())
        except InvalidOperation:
            return None, "daily_budget_invalid"
        if not value.is_finite() or value <= 0:
            return None, "daily_budget_invalid"
        return value, None

    def _used_daily_cost(self, connection, billing_day_utc: str) -> Decimal:
        rows = connection.execute(
            """
            SELECT reserved_cost_usd, actual_cost_usd, status
            FROM budget_reservations
            WHERE provider = ? AND billing_day_utc = ? AND status != 'released'
            """,
            (self.provider, billing_day_utc),
        ).fetchall()
        total = Decimal("0")
        for row in rows:
            raw = (
                row["actual_cost_usd"]
                if row["status"] == "settled" and row["actual_cost_usd"] is not None
                else row["reserved_cost_usd"]
            )
            if raw is not None:
                total += Decimal(str(raw))
        return total

    def reserve(
        self,
        *,
        run_id: str,
        request_id: str,
        operation: Operation | str,
        input_tokens: int,
        output_tokens: int,
        calls: int = 1,
        estimated_cost_usd: Decimal | None = None,
        cost_pricing_version: str | None = None,
    ) -> BudgetReservation:
        if min(input_tokens, output_tokens, calls) < 0 or calls == 0:
            raise ValueError("reservation amounts must be non-negative and calls positive")
        operation = Operation(operation)
        if estimated_cost_usd is not None:
            estimated_cost_usd = Decimal(estimated_cost_usd)
            if not estimated_cost_usd.is_finite() or estimated_cost_usd < 0:
                raise ValueError("estimated cost must be a non-negative finite decimal")
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

            daily_limit, daily_error = (
                self._daily_limit()
                if self.provider.lower() == "openai"
                else (None, None)
            )
            if daily_error is not None:
                return BudgetReservation(False, reason=daily_error)
            billing_day_utc = _utc_billing_day()
            if daily_limit is not None:
                if estimated_cost_usd is None:
                    return BudgetReservation(False, reason="daily_cost_unknown")
                if (
                    self._used_daily_cost(connection, billing_day_utc)
                    + estimated_cost_usd
                    > daily_limit
                ):
                    return BudgetReservation(False, reason="daily_hard_cap")

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
                    billing_day_utc, reserved_cost_usd, cost_pricing_version,
                    status, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?)
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
                    billing_day_utc,
                    str(estimated_cost_usd) if estimated_cost_usd is not None else None,
                    cost_pricing_version,
                    _utc_now(),
                ),
            )
            return BudgetReservation(True, reservation_id=reservation_id, acquired_by_caller=True)

    def settle(
        self,
        reservation_id: str | None,
        usage: TokenUsage,
        *,
        calls: int = 1,
        actual_cost_usd: Decimal | None = None,
    ) -> None:
        if not reservation_id:
            return
        with self.store.transaction(write=True) as connection:
            if actual_cost_usd is not None:
                actual_cost_usd = Decimal(actual_cost_usd)
                if not actual_cost_usd.is_finite() or actual_cost_usd < 0:
                    raise ValueError("actual cost must be a non-negative finite decimal")
            connection.execute(
                """
                UPDATE budget_reservations
                SET actual_calls = ?, actual_input_tokens = COALESCE(?, reserved_input_tokens),
                    actual_output_tokens = COALESCE(?, reserved_output_tokens),
                    actual_cost_usd = COALESCE(?, reserved_cost_usd),
                    status = 'settled', settled_at_utc = ?
                WHERE reservation_id = ? AND status IN ('reserved', 'claimed')
                """,
                (
                    calls,
                    usage.input_tokens,
                    usage.output_tokens,
                    str(actual_cost_usd) if actual_cost_usd is not None else None,
                    _utc_now(),
                    reservation_id,
                ),
            )

    def release(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return
        with self.store.transaction(write=True) as connection:
            connection.execute(
                "UPDATE budget_reservations SET status = 'released', settled_at_utc = ? "
                "WHERE reservation_id = ? AND status IN ('reserved', 'claimed')",
                (_utc_now(), reservation_id),
            )

    def claim(
        self, reservation_id: str | None, *, run_id: str, request_id: str,
    ) -> BudgetReservation:
        """Atomically hand a preflight hold to the central router exactly once."""
        if not reservation_id:
            return BudgetReservation(False, reason="permit_missing")
        with self.store.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT status FROM budget_reservations "
                "WHERE reservation_id=? AND run_id=? AND request_id=? AND pool=? AND provider=?",
                (reservation_id, run_id, request_id, self.pool, self.provider),
            ).fetchone()
            if row is None:
                return BudgetReservation(False, reason="permit_mismatch")
            if row["status"] != "reserved":
                return BudgetReservation(False, reservation_id=reservation_id,
                                         reason="permit_already_claimed")
            updated = connection.execute(
                "UPDATE budget_reservations SET status='claimed' "
                "WHERE reservation_id=? AND status='reserved'", (reservation_id,),
            ).rowcount
            if updated != 1:
                return BudgetReservation(False, reservation_id=reservation_id,
                                         reason="permit_already_claimed")
        return BudgetReservation(True, reservation_id=reservation_id,
                                 already_reserved=True, acquired_by_caller=True)

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
