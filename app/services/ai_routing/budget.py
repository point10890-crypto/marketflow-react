"""Atomic per-run fallback budget reservation and settlement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    owner_token: str | None = None


@dataclass(frozen=True)
class BudgetSnapshot:
    used_calls: int
    used_input_tokens: int
    used_output_tokens: int
    remaining_calls: int
    remaining_input_tokens: int
    remaining_output_tokens: int


def _utc_now_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now() -> str:
    return _utc_now_datetime().isoformat()


def _utc_billing_day() -> str:
    return _utc_now_datetime().date().isoformat()


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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

    @staticmethod
    def _lease_seconds() -> int:
        try:
            configured = int(os.getenv("AI_OPENAI_PERMIT_LEASE_SECONDS", "900"))
        except (TypeError, ValueError):
            configured = 900
        return max(1, min(configured, 86_400))

    def _lease_expiry(self) -> str:
        return (_utc_now_datetime() + timedelta(seconds=self._lease_seconds())).isoformat()

    @staticmethod
    def _lease_expired(row) -> bool:
        expires_at = _parse_utc(row["lease_expires_at_utc"])
        return expires_at is not None and expires_at <= _utc_now_datetime()

    def _used(self, connection, run_id: str) -> tuple[int, int, int]:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status IN ('settled', 'breached')
                    THEN COALESCE(actual_calls, reserved_calls) ELSE reserved_calls END), 0),
                COALESCE(SUM(CASE WHEN status IN ('settled', 'breached')
                    THEN COALESCE(actual_input_tokens, reserved_input_tokens)
                    ELSE reserved_input_tokens END), 0),
                COALESCE(SUM(CASE WHEN status IN ('settled', 'breached')
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
                if row["status"] in {"settled", "breached"} and row["actual_cost_usd"] is not None
                else row["reserved_cost_usd"]
            )
            if raw is not None:
                total += Decimal(str(raw))
        return total

    def _active_limit_failure(
        self, connection, *, run_id: str, billing_day_utc: str,
    ) -> str | None:
        """Fail closed when a settled overage has invalidated active holds."""
        daily_limit, daily_error = (
            self._daily_limit()
            if self.provider.lower() == "openai"
            else (None, None)
        )
        if daily_error is not None:
            return daily_error
        if (
            daily_limit is not None
            and self._used_daily_cost(connection, billing_day_utc) > daily_limit
        ):
            return "daily_hard_cap"
        used_calls, used_input, used_output = self._used(connection, run_id)
        if (
            used_calls > self.limits.max_calls
            or used_input > self.limits.max_input_tokens
            or used_output > self.limits.max_output_tokens
        ):
            return "hard_cap"
        return None

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
        owner_token: str | None = None,
    ) -> BudgetReservation:
        if min(input_tokens, output_tokens, calls) < 0 or calls == 0:
            raise ValueError("reservation amounts must be non-negative and calls positive")
        operation = Operation(operation)
        if estimated_cost_usd is not None:
            estimated_cost_usd = Decimal(estimated_cost_usd)
            if not estimated_cost_usd.is_finite() or estimated_cost_usd < 0:
                raise ValueError("estimated cost must be a non-negative finite decimal")
        acquisition_token = str(owner_token or uuid4())
        with self.store.transaction(write=True) as connection:
            released_reservation_id: str | None = None
            existing = connection.execute(
                """
                SELECT reservation_id, status, owner_token, operation,
                       lease_expires_at_utc, reserved_calls, reserved_input_tokens,
                       reserved_output_tokens, reserved_cost_usd
                FROM budget_reservations
                WHERE run_id = ? AND request_id = ? AND pool = ? AND provider = ?
                """,
                (run_id, request_id, self.pool, self.provider),
            ).fetchone()
            if existing is not None:
                if existing["status"] == "settled":
                    return BudgetReservation(False, existing["reservation_id"], "already_settled", True)
                if existing["status"] == "claimed" and self._lease_expired(existing):
                    connection.execute(
                        """UPDATE budget_reservations
                        SET actual_calls=reserved_calls,
                            actual_input_tokens=reserved_input_tokens,
                            actual_output_tokens=reserved_output_tokens,
                            actual_cost_usd=reserved_cost_usd,
                            status='breached', settled_at_utc=?, lease_expires_at_utc=NULL
                        WHERE reservation_id=? AND status='claimed'""",
                        (_utc_now(), existing["reservation_id"]),
                    )
                    return BudgetReservation(
                        False, existing["reservation_id"],
                        "expired_claim_reconciled", True,
                    )
                if existing["status"] in {"claimed", "breached"}:
                    return BudgetReservation(False, existing["reservation_id"], "permit_in_use", True)
                if existing["status"] == "reserved":
                    if self._lease_expired(existing):
                        if existing["operation"] != operation.value:
                            return BudgetReservation(
                                False, existing["reservation_id"], "permit_mismatch", True,
                            )
                        updated = connection.execute(
                            "UPDATE budget_reservations SET status='released', "
                            "settled_at_utc=?, lease_expires_at_utc=NULL "
                            "WHERE reservation_id=? AND status='reserved'",
                            (_utc_now(), existing["reservation_id"]),
                        ).rowcount
                        if updated != 1:
                            return BudgetReservation(
                                False, existing["reservation_id"], "permit_in_use", True,
                            )
                        released_reservation_id = existing["reservation_id"]
                    else:
                        same_owner = bool(owner_token) and existing["owner_token"] == acquisition_token
                        return BudgetReservation(
                            same_owner, existing["reservation_id"],
                            None if same_owner else "permit_in_use", True, same_owner,
                            acquisition_token if same_owner else None,
                        )
                if existing["status"] == "released":
                    if existing["operation"] != operation.value:
                        return BudgetReservation(
                            False, existing["reservation_id"], "permit_mismatch", True,
                        )
                    released_reservation_id = existing["reservation_id"]
                elif released_reservation_id is None:
                    return BudgetReservation(
                        False, existing["reservation_id"], "permit_unavailable", True,
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

            if released_reservation_id is not None:
                updated = connection.execute(
                    """UPDATE budget_reservations SET reserved_calls=?,
                    reserved_input_tokens=?, reserved_output_tokens=?, billing_day_utc=?,
                    reserved_cost_usd=?, cost_pricing_version=?, actual_calls=NULL,
                    actual_input_tokens=NULL, actual_output_tokens=NULL, actual_cost_usd=NULL,
                    status='reserved', owner_token=?, lease_expires_at_utc=?,
                    created_at_utc=?, settled_at_utc=NULL
                    WHERE reservation_id=? AND status='released'""",
                    (calls, input_tokens, output_tokens, billing_day_utc,
                     str(estimated_cost_usd) if estimated_cost_usd is not None else None,
                     cost_pricing_version, acquisition_token, self._lease_expiry(),
                     _utc_now(), released_reservation_id),
                ).rowcount
                if updated != 1:
                    return BudgetReservation(
                        False, released_reservation_id, "permit_in_use", True,
                    )
                return BudgetReservation(
                    True, released_reservation_id, already_reserved=True,
                    acquired_by_caller=True, owner_token=acquisition_token,
                )

            reservation_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO budget_reservations (
                    reservation_id, run_id, request_id, pool, provider, operation,
                    reserved_calls, reserved_input_tokens, reserved_output_tokens,
                    billing_day_utc, reserved_cost_usd, cost_pricing_version,
                    status, owner_token, lease_expires_at_utc, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?)
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
                    acquisition_token,
                    self._lease_expiry(),
                    _utc_now(),
                ),
            )
            return BudgetReservation(True, reservation_id=reservation_id, acquired_by_caller=True,
                                     owner_token=acquisition_token)

    def settle(
        self,
        reservation_id: str | None,
        usage: TokenUsage,
        *,
        calls: int = 1,
        actual_cost_usd: Decimal | None = None,
    ) -> bool:
        if not reservation_id:
            return False
        if calls < 0:
            raise ValueError("actual calls must be non-negative")
        with self.store.transaction(write=True) as connection:
            if actual_cost_usd is not None:
                actual_cost_usd = Decimal(actual_cost_usd)
                if not actual_cost_usd.is_finite() or actual_cost_usd < 0:
                    raise ValueError("actual cost must be a non-negative finite decimal")
            row = connection.execute(
                "SELECT reserved_calls,reserved_input_tokens,reserved_output_tokens,reserved_cost_usd,status "
                "FROM budget_reservations WHERE reservation_id=?", (reservation_id,),
            ).fetchone()
            if row is None or row["status"] not in {"reserved", "claimed"}:
                return False
            breached = (
                calls > row["reserved_calls"]
                or (usage.input_tokens is not None and usage.input_tokens > row["reserved_input_tokens"])
                or (usage.output_tokens is not None and usage.output_tokens > row["reserved_output_tokens"])
                or (actual_cost_usd is not None and row["reserved_cost_usd"] is not None
                    and actual_cost_usd > Decimal(str(row["reserved_cost_usd"])))
            )
            status = "breached" if breached else "settled"
            updated = connection.execute(
                """
                UPDATE budget_reservations
                SET actual_calls = ?, actual_input_tokens = COALESCE(?, reserved_input_tokens),
                    actual_output_tokens = COALESCE(?, reserved_output_tokens),
                    actual_cost_usd = COALESCE(?, reserved_cost_usd),
                    status = ?, settled_at_utc = ?, lease_expires_at_utc=NULL
                WHERE reservation_id = ? AND status IN ('reserved', 'claimed')
                """,
                (
                    calls,
                    usage.input_tokens,
                    usage.output_tokens,
                    str(actual_cost_usd) if actual_cost_usd is not None else None,
                    status,
                    _utc_now(),
                    reservation_id,
                ),
            ).rowcount
        return updated == 1 and not breached

    def finalize_uncertain_claim(
        self,
        reservation_id: str | None,
        *,
        owner_token: str | None,
        usage: TokenUsage,
        calls: int = 1,
        actual_cost_usd: Decimal | None = None,
    ) -> bool:
        """Terminalize owned post-dispatch work when normal settlement is uncertain.

        A provider may have accepted billable work even when persisting its exact
        settlement fails.  In that case the safe accounting value is the larger
        of the reservation and the observed usage/cost, never an open claim and
        never a release.  The owner check prevents one caller from finalizing a
        different caller's permit.
        """
        if not reservation_id or not owner_token:
            return False
        if calls < 0:
            raise ValueError("actual calls must be non-negative")
        if actual_cost_usd is not None:
            actual_cost_usd = Decimal(actual_cost_usd)
            if not actual_cost_usd.is_finite() or actual_cost_usd < 0:
                raise ValueError("actual cost must be a non-negative finite decimal")

        with self.store.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT status,owner_token,reserved_calls,reserved_input_tokens,"
                "reserved_output_tokens,reserved_cost_usd FROM budget_reservations "
                "WHERE reservation_id=? AND pool=? AND provider=?",
                (reservation_id, self.pool, self.provider),
            ).fetchone()
            if row is None or row["owner_token"] != owner_token:
                return False
            if row["status"] in {"settled", "breached"}:
                return True
            if row["status"] != "claimed":
                return False

            actual_input = usage.input_tokens if usage.input_tokens is not None else 0
            actual_output = usage.output_tokens if usage.output_tokens is not None else 0
            conservative_calls = max(int(row["reserved_calls"]), calls)
            conservative_input = max(int(row["reserved_input_tokens"]), actual_input)
            conservative_output = max(int(row["reserved_output_tokens"]), actual_output)
            reserved_cost = (
                Decimal(str(row["reserved_cost_usd"]))
                if row["reserved_cost_usd"] is not None
                else None
            )
            if reserved_cost is None:
                conservative_cost = actual_cost_usd
            elif actual_cost_usd is None:
                conservative_cost = reserved_cost
            else:
                conservative_cost = max(reserved_cost, actual_cost_usd)

            updated = connection.execute(
                """
                UPDATE budget_reservations
                SET actual_calls=?, actual_input_tokens=?, actual_output_tokens=?,
                    actual_cost_usd=?, status='breached', settled_at_utc=?,
                    lease_expires_at_utc=NULL
                WHERE reservation_id=? AND pool=? AND provider=? AND owner_token=?
                  AND status='claimed'
                """,
                (
                    conservative_calls,
                    conservative_input,
                    conservative_output,
                    str(conservative_cost) if conservative_cost is not None else None,
                    _utc_now(),
                    reservation_id,
                    self.pool,
                    self.provider,
                    owner_token,
                ),
            ).rowcount
        return updated == 1

    def release(self, reservation_id: str | None, *, owner_token: str | None = None) -> bool:
        """Release only an unclaimed hold owned by this acquisition token."""
        if not reservation_id or not owner_token:
            return False
        with self.store.transaction(write=True) as connection:
            updated = connection.execute(
                "UPDATE budget_reservations SET status = 'released', settled_at_utc = ?, "
                "lease_expires_at_utc=NULL "
                "WHERE reservation_id = ? AND status = 'reserved' AND owner_token=?",
                (_utc_now(), reservation_id, owner_token),
            ).rowcount
        return updated == 1

    def release_before_dispatch(
        self,
        reservation_id: str | None,
        *,
        owner_token: str | None,
    ) -> bool:
        """Release an owned hold or claim only while no provider was dispatched."""
        if not reservation_id or not owner_token:
            return False
        with self.store.transaction(write=True) as connection:
            updated = connection.execute(
                "UPDATE budget_reservations SET status='released', settled_at_utc=?, "
                "lease_expires_at_utc=NULL WHERE reservation_id=? AND pool=? "
                "AND provider=? AND owner_token=? AND status IN ('reserved','claimed')",
                (
                    _utc_now(),
                    reservation_id,
                    self.pool,
                    self.provider,
                    owner_token,
                ),
            ).rowcount
            if updated == 1:
                return True
            row = connection.execute(
                "SELECT status,owner_token FROM budget_reservations "
                "WHERE reservation_id=? AND pool=? AND provider=?",
                (reservation_id, self.pool, self.provider),
            ).fetchone()
        return bool(
            row is not None
            and row["owner_token"] == owner_token
            and row["status"] == "released"
        )

    def release_claimed(self, reservation_id: str | None) -> bool:
        """Central-router-only release after claim; terminal rows are already safe."""
        if not reservation_id:
            return False
        with self.store.transaction(write=True) as connection:
            updated = connection.execute(
                "UPDATE budget_reservations SET status='released', settled_at_utc=?, "
                "lease_expires_at_utc=NULL "
                "WHERE reservation_id=? AND status='claimed'",
                (_utc_now(), reservation_id),
            ).rowcount
            if updated == 1:
                return True
            row = connection.execute(
                "SELECT status FROM budget_reservations WHERE reservation_id=? "
                "AND pool=? AND provider=?",
                (reservation_id, self.pool, self.provider),
            ).fetchone()
        return row is not None and row["status"] in {"released", "settled", "breached"}

    def renew(
        self, reservation_id: str | None, *, owner_token: str | None = None,
    ) -> bool:
        """Extend one owned active permit without reviving an expired lease."""
        if not reservation_id or not owner_token:
            return False
        return self.renew_many([(reservation_id, owner_token)], terminal_ok=False)

    def renew_many(
        self, reservations: list[tuple[str, str]], *, terminal_ok: bool = False,
    ) -> bool:
        """Atomically extend owned active permits, optionally ignoring terminal rows."""
        requested = list(reservations)
        if any(not reservation_id or not owner_token for reservation_id, owner_token in requested):
            return False
        owned = list(dict.fromkeys(
            (str(reservation_id), str(owner_token))
            for reservation_id, owner_token in requested
        ))
        if not owned:
            return True
        with self.store.transaction(write=True) as connection:
            active: list[tuple[str, str, str, str]] = []
            billing_day_utc = _utc_billing_day()
            for reservation_id, owner_token in owned:
                row = connection.execute(
                    "SELECT status,owner_token,lease_expires_at_utc,billing_day_utc,run_id "
                    "FROM budget_reservations WHERE reservation_id=? AND pool=? AND provider=?",
                    (reservation_id, self.pool, self.provider),
                ).fetchone()
                if row is None or row["owner_token"] != owner_token:
                    return False
                if row["status"] == "breached":
                    return False
                if row["status"] in {"settled", "released"}:
                    if terminal_ok:
                        continue
                    return False
                if row["billing_day_utc"] != billing_day_utc:
                    return False
                expires_at = _parse_utc(row["lease_expires_at_utc"])
                if (
                    row["status"] not in {"reserved", "claimed"}
                    or expires_at is None
                    or expires_at <= _utc_now_datetime()
                ):
                    return False
                active.append((
                    reservation_id,
                    owner_token,
                    str(row["run_id"]),
                    str(row["billing_day_utc"]),
                ))

            for run_id, active_billing_day in {
                (run_id, active_billing_day)
                for _, _, run_id, active_billing_day in active
            }:
                if self._active_limit_failure(
                    connection,
                    run_id=run_id,
                    billing_day_utc=active_billing_day,
                ) is not None:
                    return False

            expiry = self._lease_expiry()
            for reservation_id, owner_token, _, _ in active:
                updated = connection.execute(
                    "UPDATE budget_reservations SET lease_expires_at_utc=? "
                    "WHERE reservation_id=? AND owner_token=? "
                    "AND status IN ('reserved','claimed')",
                    (expiry, reservation_id, owner_token),
                ).rowcount
                if updated != 1:
                    raise RuntimeError("permit renewal lost ownership")
        return True

    def claim(
        self, reservation_id: str | None, *, run_id: str, request_id: str,
        owner_token: str | None = None, input_tokens: int = 0, output_tokens: int = 0,
    ) -> BudgetReservation:
        """Atomically hand a preflight hold to the central router exactly once."""
        if not reservation_id:
            return BudgetReservation(False, reason="permit_missing")
        with self.store.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT status,owner_token,reserved_input_tokens,reserved_output_tokens,"
                "lease_expires_at_utc,billing_day_utc FROM budget_reservations "
                "WHERE reservation_id=? AND run_id=? AND request_id=? AND pool=? AND provider=?",
                (reservation_id, run_id, request_id, self.pool, self.provider),
            ).fetchone()
            if row is None:
                return BudgetReservation(False, reason="permit_mismatch")
            if not owner_token or row["owner_token"] != owner_token:
                return BudgetReservation(False, reservation_id=reservation_id, reason="permit_owner_mismatch")
            if row["status"] != "reserved":
                return BudgetReservation(False, reservation_id=reservation_id,
                                         reason="permit_already_claimed")
            if row["billing_day_utc"] != _utc_billing_day():
                connection.execute(
                    "UPDATE budget_reservations SET status='released', settled_at_utc=?, "
                    "lease_expires_at_utc=NULL WHERE reservation_id=? AND status='reserved'",
                    (_utc_now(), reservation_id),
                )
                return BudgetReservation(
                    False, reservation_id=reservation_id,
                    reason="permit_billing_day_expired",
                )
            expires_at = _parse_utc(row["lease_expires_at_utc"])
            if expires_at is None:
                connection.execute(
                    "UPDATE budget_reservations SET status='released', settled_at_utc=?, "
                    "lease_expires_at_utc=NULL WHERE reservation_id=? AND status='reserved'",
                    (_utc_now(), reservation_id),
                )
                return BudgetReservation(
                    False, reservation_id=reservation_id,
                    reason="permit_lease_invalid",
                )
            if expires_at <= _utc_now_datetime():
                connection.execute(
                    "UPDATE budget_reservations SET status='released', settled_at_utc=?, "
                    "lease_expires_at_utc=NULL WHERE reservation_id=? AND status='reserved'",
                    (_utc_now(), reservation_id),
                )
                return BudgetReservation(False, reservation_id=reservation_id,
                                         reason="permit_expired")
            limit_failure = self._active_limit_failure(
                connection,
                run_id=run_id,
                billing_day_utc=str(row["billing_day_utc"]),
            )
            if limit_failure is not None:
                connection.execute(
                    "UPDATE budget_reservations SET status='released', settled_at_utc=?, "
                    "lease_expires_at_utc=NULL WHERE reservation_id=? AND status='reserved'",
                    (_utc_now(), reservation_id),
                )
                return BudgetReservation(
                    False,
                    reservation_id=reservation_id,
                    reason=limit_failure,
                )
            if input_tokens > row["reserved_input_tokens"] or output_tokens > row["reserved_output_tokens"]:
                connection.execute(
                    "UPDATE budget_reservations SET status='breached',settled_at_utc=? "
                    "WHERE reservation_id=? AND status='reserved'",
                    (_utc_now(), reservation_id),
                )
                return BudgetReservation(False, reservation_id=reservation_id,
                                         reason="permit_bound_exceeded")
            updated = connection.execute(
                "UPDATE budget_reservations SET status='claimed', lease_expires_at_utc=? "
                "WHERE reservation_id=? AND status='reserved'",
                (self._lease_expiry(), reservation_id),
            ).rowcount
            if updated != 1:
                return BudgetReservation(False, reservation_id=reservation_id,
                                         reason="permit_already_claimed")
        return BudgetReservation(True, reservation_id=reservation_id,
                                 already_reserved=True, acquired_by_caller=True,
                                 owner_token=owner_token)

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
