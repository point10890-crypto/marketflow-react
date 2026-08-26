"""Isolated append-only SQLite ledger for AlphaCore paper capital.

Construction is side-effect free.  Writers must explicitly call
:meth:`PaperLedger.initialize`; readers should use ``read_only=True`` which
opens SQLite with ``mode=ro`` and ``query_only`` enabled.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .config import default_db_path, resolve_mode
from .contracts import (
    PaperFill,
    PaperOrderIntent,
    ReconciliationResult,
    RiskDecision,
    canonical_hash,
    canonical_json,
    normalize_timestamp,
    parse_timestamp,
)


SCHEMA_VERSION = 1
ENVIRONMENT = "paper"

STATE_BY_EVENT = {
    "INTENT_PROPOSED": "PROPOSED",
    "INTENT_RESERVED": "RESERVED",
    "RISK_APPROVED": "RULE_APPROVED",
    "RISK_REJECTED": "REJECTED",
    "INTENT_EXPIRED": "EXPIRED",
    "PAPER_SUBMITTED": "PAPER_SUBMITTED",
    "PAPER_PARTIAL": "PARTIAL",
    "PAPER_FILLED": "FILLED",
    "PAPER_CANCELED": "CANCELED",
    "INTENT_RECONCILED": "RECONCILED",
}

ALLOWED_TRANSITIONS = {
    "PROPOSED": frozenset({"RESERVED", "REJECTED", "EXPIRED"}),
    "RESERVED": frozenset({"RULE_APPROVED", "REJECTED", "EXPIRED"}),
    "RULE_APPROVED": frozenset({"PAPER_SUBMITTED", "EXPIRED"}),
    "PAPER_SUBMITTED": frozenset({"PARTIAL", "FILLED", "CANCELED", "EXPIRED"}),
    "PARTIAL": frozenset({"PARTIAL", "FILLED", "CANCELED", "EXPIRED"}),
    "REJECTED": frozenset(),
    "EXPIRED": frozenset({"RECONCILED"}),
    "FILLED": frozenset({"RECONCILED"}),
    "CANCELED": frozenset({"RECONCILED"}),
    "RECONCILED": frozenset(),
}

KILL_STATES = ("NORMAL", "BLOCK_NEW", "CANCEL_PENDING", "REDUCE_ONLY", "MANUAL_HALT")
KILL_SEVERITY = {state: index for index, state in enumerate(KILL_STATES)}
TERMINAL_BEFORE_RECONCILE = frozenset({"FILLED", "CANCELED", "EXPIRED"})


class LedgerError(RuntimeError):
    """Base class for ledger safety failures."""


class LedgerNotInitialized(LedgerError):
    pass


class ReadOnlyLedgerError(LedgerError):
    pass


class InvalidTransition(LedgerError):
    pass


class IdempotencyConflict(LedgerError):
    pass


class LedgerIntegrityError(LedgerError):
    pass


class StaleApprovalError(LedgerError):
    pass


def _utc_now() -> str:
    return normalize_timestamp(datetime.now(timezone.utc))


class PaperLedger:
    """Append-only paper ledger with replay-derived read projections."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        read_only: bool = False,
        mode: str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.read_only = bool(read_only)
        self.mode = resolve_mode(mode)

    def initialize(self) -> None:
        """Explicitly create the isolated database and immutable schema."""

        if self.read_only:
            raise ReadOnlyLedgerError("read-only ledger cannot initialize schema")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS alpha_core_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ledger_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_uid TEXT NOT NULL UNIQUE,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    aggregate_seq INTEGER NOT NULL CHECK (aggregate_seq > 0),
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    event_schema_version INTEGER NOT NULL CHECK (event_schema_version > 0),
                    environment TEXT NOT NULL CHECK (environment = 'paper'),
                    effective_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    actor_principal TEXT NOT NULL,
                    intent_hash TEXT,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE,
                    UNIQUE (aggregate_type, aggregate_id, aggregate_seq)
                );

                CREATE INDEX IF NOT EXISTS idx_ledger_aggregate
                    ON ledger_events(aggregate_type, aggregate_id, event_id);
                CREATE INDEX IF NOT EXISTS idx_ledger_event_type
                    ON ledger_events(event_type, event_id);

                CREATE TABLE IF NOT EXISTS outbox (
                    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_uid TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_uid),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    dispatched_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );

                CREATE TRIGGER IF NOT EXISTS ledger_events_no_update
                BEFORE UPDATE ON ledger_events
                BEGIN
                    SELECT RAISE(ABORT, 'ledger_events is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS ledger_events_no_delete
                BEFORE DELETE ON ledger_events
                BEGIN
                    SELECT RAISE(ABORT, 'ledger_events is append-only');
                END;
                """
            )
            existing = con.execute(
                "SELECT value FROM alpha_core_meta WHERE key='schema_version'"
            ).fetchone()
            if existing and int(existing[0]) != SCHEMA_VERSION:
                raise LedgerError(
                    f"unsupported schema version {existing[0]}; expected {SCHEMA_VERSION}"
                )
            con.execute(
                "INSERT OR IGNORE INTO alpha_core_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            con.execute(
                "INSERT OR IGNORE INTO alpha_core_meta(key, value) VALUES('environment', 'paper')"
            )
            con.commit()
        finally:
            con.close()

    def exists(self) -> bool:
        return self.db_path.is_file()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if write and self.read_only:
            raise ReadOnlyLedgerError("read-only ledger cannot mutate")
        if not self.exists():
            raise LedgerNotInitialized(f"ledger does not exist: {self.db_path}")
        if self.read_only or not write:
            uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=5.0)
            con.execute("PRAGMA query_only=ON")
        else:
            con = sqlite3.connect(str(self.db_path), timeout=10.0)
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA busy_timeout=10000")
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def _require_paper_write(self) -> None:
        if self.read_only:
            raise ReadOnlyLedgerError("read-only ledger cannot mutate")
        if self.mode != "paper":
            raise ReadOnlyLedgerError(
                "shadow mode is evaluation-only; set ALPHACLAW_MODE=paper explicitly for paper writes"
            )
        if not self.exists():
            raise LedgerNotInitialized("call initialize() before writing ledger events")

    # -- bounded write API -------------------------------------------------

    def initialize_capital(
        self,
        cash_krw: int,
        *,
        effective_at: str,
        idempotency_key: str,
        actor_principal: str = "alpha_core.operator",
    ) -> dict[str, Any]:
        self._require_paper_write()
        if isinstance(cash_krw, bool) or not isinstance(cash_krw, int) or cash_krw <= 0:
            raise LedgerError("initial cash_krw must be a positive integer")
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            count = con.execute(
                "SELECT COUNT(*) FROM ledger_events WHERE event_type='CAPITAL_INITIALIZED'"
            ).fetchone()[0]
            if count:
                existing = self._event_by_idempotency_tx(con, idempotency_key)
                if existing:
                    con.commit()
                    return existing
                raise InvalidTransition("paper capital is already initialized")
            event = self._append_event_tx(
                con,
                aggregate_type="portfolio",
                aggregate_id="paper",
                event_type="CAPITAL_INITIALIZED",
                payload={"cash_krw": cash_krw},
                effective_at=effective_at,
                idempotency_key=idempotency_key,
                actor_principal=actor_principal,
                correlation_id="capital:paper",
            )
            con.commit()
            return event

    def propose_intent(
        self,
        intent: PaperOrderIntent,
        *,
        idempotency_key: str,
        actor_principal: str = "alpha_core.strategy",
    ) -> dict[str, Any]:
        self._require_paper_write()
        if not intent.verify_hash():
            raise LedgerIntegrityError("intent hash verification failed")
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = self._event_by_idempotency_tx(con, idempotency_key)
            if existing:
                self._assert_same_request(existing, "INTENT_PROPOSED", intent.to_dict())
                con.commit()
                return existing
            if self._current_state_tx(con, intent.intent_id) is not None:
                raise InvalidTransition(f"intent already exists: {intent.intent_id}")
            if self._current_kill_state_tx(con) != "NORMAL":
                raise InvalidTransition("kill state blocks new paper intents")
            event = self._append_event_tx(
                con,
                aggregate_type="paper_intent",
                aggregate_id=intent.intent_id,
                event_type="INTENT_PROPOSED",
                payload=intent.to_dict(),
                effective_at=intent.created_at,
                idempotency_key=idempotency_key,
                actor_principal=actor_principal,
                intent_hash=intent.intent_hash,
                correlation_id=intent.intent_id,
            )
            con.commit()
            return event

    def record_risk_decision(
        self,
        decision: RiskDecision,
        *,
        idempotency_key: str,
        actor_principal: str = "alpha_core.risk_kernel",
    ) -> dict[str, Any]:
        """Atomically reserve capital and append one deterministic decision."""

        self._require_paper_write()
        if decision.evaluation_mode != "paper":
            raise LedgerError("shadow risk decisions cannot be persisted as paper approvals")
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            final_key = f"{idempotency_key}:decision"
            existing = self._event_by_idempotency_tx(con, final_key)
            if existing:
                payload = existing["payload"]
                if payload.get("decision_hash") != decision.decision_hash:
                    raise IdempotencyConflict("risk idempotency key reused with another decision")
                con.commit()
                return existing

            intent = self._load_intent_tx(con, decision.intent_id)
            if intent.intent_hash != decision.intent_hash:
                raise StaleApprovalError("risk decision is bound to a different intent hash")
            current_state = self._current_state_tx(con, intent.intent_id)
            if current_state != "PROPOSED":
                raise InvalidTransition(f"cannot risk-evaluate intent in state {current_state}")
            if (
                decision.decision == "approved"
                and parse_timestamp(decision.expires_at) > parse_timestamp(intent.expires_at)
            ):
                raise StaleApprovalError("risk approval cannot outlive its intent")
            now = parse_timestamp(decision.evaluated_at)
            if now >= parse_timestamp(intent.expires_at):
                raise StaleApprovalError("intent expired before risk evaluation")

            if decision.decision == "rejected":
                self._assert_transition("PROPOSED", "REJECTED")
                event = self._append_event_tx(
                    con,
                    aggregate_type="paper_intent",
                    aggregate_id=intent.intent_id,
                    event_type="RISK_REJECTED",
                    payload=decision.to_dict(),
                    effective_at=decision.evaluated_at,
                    idempotency_key=final_key,
                    actor_principal=actor_principal,
                    intent_hash=intent.intent_hash,
                    correlation_id=intent.intent_id,
                )
                con.commit()
                return event

            if decision.reason_codes != ("ALL_CHECKS_PASSED",):
                raise StaleApprovalError("approved decision lacks the deterministic pass code")
            if decision.risk_policy_version != intent.risk_policy_version:
                raise StaleApprovalError("risk policy version is not bound to the intent")
            current_projection = self._portfolio_tx(con)
            if current_projection["snapshot_hash"] != decision.ledger_projection_hash:
                raise StaleApprovalError("portfolio changed after risk evaluation")
            if self._current_kill_state_tx(con) != "NORMAL":
                raise StaleApprovalError("kill state changed after risk evaluation")
            self._assert_transition("PROPOSED", "RESERVED")
            reserved = self._append_event_tx(
                con,
                aggregate_type="paper_intent",
                aggregate_id=intent.intent_id,
                event_type="INTENT_RESERVED",
                payload={
                    "reservation_id": decision.reservation_id,
                    "reserved_krw": intent.notional_reservation_krw,
                    "decision_hash": decision.decision_hash,
                },
                effective_at=decision.evaluated_at,
                idempotency_key=f"{idempotency_key}:reservation",
                actor_principal=actor_principal,
                intent_hash=intent.intent_hash,
                correlation_id=intent.intent_id,
            )
            self._assert_transition("RESERVED", "RULE_APPROVED")
            event = self._append_event_tx(
                con,
                aggregate_type="paper_intent",
                aggregate_id=intent.intent_id,
                event_type="RISK_APPROVED",
                payload=decision.to_dict(),
                effective_at=decision.evaluated_at,
                idempotency_key=final_key,
                actor_principal=actor_principal,
                intent_hash=intent.intent_hash,
                correlation_id=intent.intent_id,
                causation_id=reserved["event_uid"],
            )
            con.commit()
            return event

    def submit_paper(
        self,
        intent_id: str,
        *,
        intent_hash: str,
        risk_decision_hash: str,
        submitted_at: str,
        idempotency_key: str,
        actor_principal: str = "alpha_core.paper_simulator",
    ) -> dict[str, Any]:
        """Consume one exact, unexpired approval and mark paper submission."""

        self._require_paper_write()
        submitted_at = normalize_timestamp(submitted_at)
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = self._event_by_idempotency_tx(con, idempotency_key)
            if existing:
                con.commit()
                return existing
            intent = self._load_intent_tx(con, intent_id)
            if intent.intent_hash != intent_hash:
                raise StaleApprovalError("submitted intent hash mismatch")
            if self._current_state_tx(con, intent_id) != "RULE_APPROVED":
                raise InvalidTransition("only RULE_APPROVED intents can be submitted")
            approval = self._latest_event_tx(con, intent_id, event_type="RISK_APPROVED")
            if not approval or approval["payload"].get("decision_hash") != risk_decision_hash:
                raise StaleApprovalError("approval hash mismatch")
            if parse_timestamp(submitted_at) >= parse_timestamp(approval["payload"]["expires_at"]):
                raise StaleApprovalError("approval expired before submission")
            if parse_timestamp(submitted_at) >= parse_timestamp(intent.expires_at):
                raise StaleApprovalError("intent expired before submission")
            if self._current_kill_state_tx(con) != "NORMAL":
                raise StaleApprovalError("kill state blocks paper submission")
            self._assert_transition("RULE_APPROVED", "PAPER_SUBMITTED")
            event = self._append_event_tx(
                con,
                aggregate_type="paper_intent",
                aggregate_id=intent_id,
                event_type="PAPER_SUBMITTED",
                payload={
                    "intent_hash": intent_hash,
                    "risk_decision_hash": risk_decision_hash,
                    "approval_consumed_at": submitted_at,
                },
                effective_at=submitted_at,
                idempotency_key=idempotency_key,
                actor_principal=actor_principal,
                intent_hash=intent_hash,
                correlation_id=intent_id,
                causation_id=approval["event_uid"],
            )
            con.commit()
            return event

    def record_fill(
        self,
        fill: PaperFill,
        *,
        idempotency_key: str,
        actor_principal: str = "alpha_core.paper_simulator",
    ) -> dict[str, Any]:
        self._require_paper_write()
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = self._event_by_idempotency_tx(con, idempotency_key)
            if existing:
                if existing["payload"].get("fill_hash") != fill.fill_hash:
                    raise IdempotencyConflict("fill idempotency key reused with another fill")
                con.commit()
                return existing
            intent = self._load_intent_tx(con, fill.intent_id)
            if fill.intent_hash != intent.intent_hash or fill.side != intent.side:
                raise LedgerIntegrityError("fill is not bound to the exact approved intent")
            if fill.cost_schedule_version != intent.cost_schedule_version:
                raise LedgerIntegrityError("fill cost schedule differs from the approved intent")
            if fill.fill_model_version != intent.fill_model_version:
                raise LedgerIntegrityError("fill model differs from the approved intent")
            if fill.quality_status == "not_comparable":
                raise LedgerIntegrityError("not-comparable market data cannot create a fill")
            if parse_timestamp(fill.filled_at) >= parse_timestamp(intent.expires_at):
                raise InvalidTransition("cannot fill an expired intent")
            state = self._current_state_tx(con, fill.intent_id)
            if state not in {"PAPER_SUBMITTED", "PARTIAL"}:
                raise InvalidTransition(f"cannot fill intent in state {state}")
            prior_fills = self._fill_payloads_tx(con, fill.intent_id)
            if any(item.get("fill_id") == fill.fill_id for item in prior_fills):
                raise IdempotencyConflict(f"duplicate fill_id: {fill.fill_id}")
            cumulative = sum(int(item["quantity"]) for item in prior_fills) + fill.quantity
            if cumulative > intent.quantity:
                raise LedgerIntegrityError("cumulative fill exceeds intent quantity")
            guard_key = "max_price_krw" if intent.side == "buy" else "min_price_krw"
            guard = intent.price_guard.get(guard_key)
            if not isinstance(guard, int) or isinstance(guard, bool):
                raise LedgerIntegrityError("approved intent has no enforceable price guard")
            if intent.side == "buy" and fill.gross_price_krw > guard:
                raise LedgerIntegrityError("buy fill breaches approved price guard")
            if intent.side == "sell" and fill.gross_price_krw < guard:
                raise LedgerIntegrityError("sell fill breaches approved price guard")
            if intent.order_style == "paper_limit":
                limit_price = intent.price_guard.get("limit_price_krw")
                if not isinstance(limit_price, int) or isinstance(limit_price, bool):
                    raise LedgerIntegrityError("paper limit intent has no limit price")
                if intent.side == "buy" and fill.gross_price_krw > limit_price:
                    raise LedgerIntegrityError("buy fill breaches approved limit")
                if intent.side == "sell" and fill.gross_price_krw < limit_price:
                    raise LedgerIntegrityError("sell fill breaches approved limit")
            projection = self._portfolio_tx(con)
            if intent.side == "buy":
                if projection["cash_krw"] is None:
                    raise LedgerIntegrityError("paper capital is not initialized")
                if projection["cash_krw"] + fill.net_cash_delta_krw < 0:
                    raise LedgerIntegrityError("fill would create negative cash")
            else:
                position = next(
                    (
                        item for item in projection["positions"]
                        if item.get("symbol_id") == intent.symbol_id
                    ),
                    None,
                )
                if int((position or {}).get("quantity") or 0) < fill.quantity:
                    raise LedgerIntegrityError("sell fill would create a negative position")
            target = "FILLED" if cumulative == intent.quantity else "PARTIAL"
            self._assert_transition(state, target)
            event_type = "PAPER_FILLED" if target == "FILLED" else "PAPER_PARTIAL"
            event = self._append_event_tx(
                con,
                aggregate_type="paper_intent",
                aggregate_id=fill.intent_id,
                event_type=event_type,
                payload={**fill.to_dict(), "cumulative_quantity": cumulative},
                effective_at=fill.filled_at,
                idempotency_key=idempotency_key,
                actor_principal=actor_principal,
                intent_hash=intent.intent_hash,
                correlation_id=fill.intent_id,
            )
            con.commit()
            return event

    def cancel_intent(
        self,
        intent_id: str,
        *,
        canceled_at: str,
        reason_code: str,
        idempotency_key: str,
        actor_principal: str = "alpha_core.paper_simulator",
    ) -> dict[str, Any]:
        return self._terminal_transition(
            intent_id,
            target="CANCELED",
            event_type="PAPER_CANCELED",
            effective_at=canceled_at,
            payload={"reason_code": str(reason_code)},
            idempotency_key=idempotency_key,
            actor_principal=actor_principal,
        )

    def expire_intent(
        self,
        intent_id: str,
        *,
        expired_at: str,
        idempotency_key: str,
        actor_principal: str = "alpha_core.scheduler",
    ) -> dict[str, Any]:
        return self._terminal_transition(
            intent_id,
            target="EXPIRED",
            event_type="INTENT_EXPIRED",
            effective_at=expired_at,
            payload={"reason_code": "TTL_EXPIRED"},
            idempotency_key=idempotency_key,
            actor_principal=actor_principal,
        )

    def record_reconciliation(
        self,
        result: ReconciliationResult,
        *,
        idempotency_key: str,
        actor_principal: str = "alpha_core.reconciler",
    ) -> dict[str, Any]:
        self._require_paper_write()
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = self._event_by_idempotency_tx(con, idempotency_key)
            if existing:
                con.commit()
                return existing
            if result.status == "MATCHED" and result.intent_id:
                current_projection = self._portfolio_tx(con)
                if current_projection["snapshot_hash"] != result.replay_projection_hash:
                    raise LedgerIntegrityError("reconciliation result is stale")
                if result.expected_projection_hash != result.replay_projection_hash:
                    raise LedgerIntegrityError("matched reconciliation hashes differ")
                if not self._verify_integrity_events(self._all_events_tx(con))["ok"]:
                    raise LedgerIntegrityError("cannot record a match for a damaged ledger")
                state = self._current_state_tx(con, result.intent_id)
                if state not in TERMINAL_BEFORE_RECONCILE:
                    raise InvalidTransition(f"cannot reconcile intent in state {state}")
                self._assert_transition(state, "RECONCILED")
                intent = self._load_intent_tx(con, result.intent_id)
                event = self._append_event_tx(
                    con,
                    aggregate_type="paper_intent",
                    aggregate_id=result.intent_id,
                    event_type="INTENT_RECONCILED",
                    payload=result.to_dict(),
                    effective_at=result.reconciled_at,
                    idempotency_key=idempotency_key,
                    actor_principal=actor_principal,
                    intent_hash=intent.intent_hash,
                    correlation_id=result.intent_id,
                )
            else:
                event = self._append_event_tx(
                    con,
                    aggregate_type="reconciliation",
                    aggregate_id=result.reconciliation_id,
                    event_type="RECONCILIATION_MISMATCH",
                    payload=result.to_dict(),
                    effective_at=result.reconciled_at,
                    idempotency_key=idempotency_key,
                    actor_principal=actor_principal,
                    correlation_id=result.reconciliation_id,
                )
                self._escalate_kill_state_tx(
                    con,
                    "MANUAL_HALT",
                    reason_code="RECONCILIATION_MISMATCH",
                    effective_at=result.reconciled_at,
                    idempotency_key=f"{idempotency_key}:halt",
                    actor_principal=actor_principal,
                    causation_id=event["event_uid"],
                )
            con.commit()
            return event

    def escalate_kill_state(
        self,
        to_state: str,
        *,
        reason_code: str,
        effective_at: str,
        idempotency_key: str,
        actor_principal: str = "alpha_core.risk_kernel",
    ) -> dict[str, Any]:
        self._require_paper_write()
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            event = self._escalate_kill_state_tx(
                con,
                to_state,
                reason_code=reason_code,
                effective_at=effective_at,
                idempotency_key=idempotency_key,
                actor_principal=actor_principal,
            )
            con.commit()
            return event

    # -- side-effect-free read API ----------------------------------------

    def status(self) -> dict[str, Any]:
        if not self.exists():
            return {
                "available": False,
                "schema_version": None,
                "environment": ENVIRONMENT,
                "mode": self.mode,
                "kill_state": "NORMAL",
                "event_count": 0,
                "intent_counts": {},
                "risk_decision_counts": {},
                "fill_count": 0,
                "unreconciled_count": 0,
                "outbox_pending_count": 0,
                "last_event_at": None,
                "integrity": {"ok": None, "checked_events": 0, "errors": ["DB_NOT_INITIALIZED"]},
            }
        with self._connection() as con:
            schema_row = con.execute(
                "SELECT value FROM alpha_core_meta WHERE key='schema_version'"
            ).fetchone()
            events = self._all_events_tx(con)
            states = self._intent_states_from_events(events)
            risk_counts = Counter(
                "approved" if event["event_type"] == "RISK_APPROVED" else "rejected"
                for event in events
                if event["event_type"] in {"RISK_APPROVED", "RISK_REJECTED"}
            )
            reconciled = {
                event["aggregate_id"] for event in events if event["event_type"] == "INTENT_RECONCILED"
            }
            terminal = {
                intent_id for intent_id, state in states.items() if state in TERMINAL_BEFORE_RECONCILE
            }
            pending_outbox = con.execute(
                "SELECT COUNT(*) FROM outbox WHERE dispatched_at IS NULL"
            ).fetchone()[0]
            integrity = self._verify_integrity_events(events)
            projection = self._portfolio_tx(con)
            replay_errors = []
            if projection["cash_krw"] is not None and projection["cash_krw"] < 0:
                replay_errors.append("NEGATIVE_CASH")
            replay_errors.extend(
                f"NEGATIVE_POSITION:{item.get('symbol_id')}"
                for item in projection["positions"]
                if int(item.get("quantity") or 0) < 0
            )
            integrity["replay_ok"] = not replay_errors
            integrity["errors"].extend(replay_errors)
            integrity["ok"] = bool(integrity["ok"] and not replay_errors)
            return {
                "available": True,
                "schema_version": int(schema_row[0]) if schema_row else None,
                "environment": ENVIRONMENT,
                "mode": self.mode,
                "kill_state": self._kill_state_from_events(events),
                "event_count": len(events),
                "intent_counts": dict(sorted(Counter(states.values()).items())),
                "risk_decision_counts": dict(sorted(risk_counts.items())),
                "fill_count": sum(
                    1 for event in events if event["event_type"] in {"PAPER_PARTIAL", "PAPER_FILLED"}
                ),
                "unreconciled_count": len(terminal - reconciled),
                "outbox_pending_count": int(pending_outbox),
                "last_event_at": events[-1]["recorded_at"] if events else None,
                "integrity": integrity,
            }

    def list_events(
        self,
        limit: int = 100,
        after_id: int | None = None,
        aggregate_id: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        limit = max(1, min(int(limit), 1000))
        clauses: list[str] = []
        params: list[Any] = []
        if after_id is not None:
            clauses.append("event_id > ?")
            params.append(int(after_id))
        if aggregate_id:
            clauses.append("aggregate_id = ?")
            params.append(str(aggregate_id))
        if event_type:
            clauses.append("event_type = ?")
            params.append(str(event_type))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "ASC" if after_id is not None else "DESC"
        params.append(limit)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM ledger_events {where} ORDER BY event_id {order} LIMIT ?",
                params,
            ).fetchall()
        decoded = [self._decode_event(row) for row in rows]
        return decoded if order == "ASC" else decoded

    def list_intents(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        with self._connection() as con:
            events = self._all_events_tx(con)
        proposed: dict[str, dict[str, Any]] = {}
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            if event["event_type"] == "INTENT_PROPOSED":
                proposed[event["aggregate_id"]] = dict(event["payload"])
            state = STATE_BY_EVENT.get(event["event_type"])
            if state:
                latest[event["aggregate_id"]] = {
                    "status": state,
                    "updated_at": event["effective_at"],
                    "last_event_id": event["event_id"],
                }
        items = []
        wanted = str(status or "").upper()
        for intent_id, contract in proposed.items():
            state = latest.get(intent_id, {"status": "UNKNOWN", "updated_at": None, "last_event_id": 0})
            if wanted and state["status"] != wanted:
                continue
            items.append({**contract, **state})
        items.sort(key=lambda item: item["last_event_id"], reverse=True)
        return items[: max(1, min(int(limit), 1000))]

    def list_risk_decisions(
        self,
        limit: int = 100,
        decision: str | None = None,
        intent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        wanted = str(decision or "").lower()
        events = self.list_events(limit=1000, aggregate_id=intent_id)
        items: list[dict[str, Any]] = []
        for event in events:
            if event["event_type"] not in {"RISK_APPROVED", "RISK_REJECTED"}:
                continue
            payload = dict(event["payload"])
            if wanted and payload.get("decision") != wanted:
                continue
            payload.setdefault("intent_id", event["aggregate_id"])
            payload["created_at"] = event["recorded_at"]
            payload["event_id"] = event["event_id"]
            items.append(payload)
            if len(items) >= max(1, min(int(limit), 1000)):
                break
        return items

    def portfolio(self) -> dict[str, Any]:
        if not self.exists():
            empty = self._empty_portfolio()
            empty["snapshot_hash"] = canonical_hash(empty)
            return empty
        with self._connection() as con:
            return self._portfolio_tx(con)

    def verify_integrity(self) -> dict[str, Any]:
        if not self.exists():
            return {"ok": None, "checked_events": 0, "errors": ["DB_NOT_INITIALIZED"]}
        with self._connection() as con:
            return self._verify_integrity_events(self._all_events_tx(con))

    # -- replay and transactional helpers --------------------------------

    def _terminal_transition(
        self,
        intent_id: str,
        *,
        target: str,
        event_type: str,
        effective_at: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        actor_principal: str,
    ) -> dict[str, Any]:
        self._require_paper_write()
        with self._connection(write=True) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = self._event_by_idempotency_tx(con, idempotency_key)
            if existing:
                con.commit()
                return existing
            intent = self._load_intent_tx(con, intent_id)
            state = self._current_state_tx(con, intent_id)
            self._assert_transition(state, target)
            event = self._append_event_tx(
                con,
                aggregate_type="paper_intent",
                aggregate_id=intent_id,
                event_type=event_type,
                payload=dict(payload),
                effective_at=effective_at,
                idempotency_key=idempotency_key,
                actor_principal=actor_principal,
                intent_hash=intent.intent_hash,
                correlation_id=intent_id,
            )
            con.commit()
            return event

    def _append_event_tx(
        self,
        con: sqlite3.Connection,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        effective_at: str,
        idempotency_key: str,
        actor_principal: str,
        correlation_id: str,
        causation_id: str | None = None,
        intent_hash: str | None = None,
    ) -> dict[str, Any]:
        existing = self._event_by_idempotency_tx(con, idempotency_key)
        if existing:
            self._assert_same_request(existing, event_type, payload)
            return existing
        aggregate_id = str(aggregate_id or "").strip()
        if not aggregate_id or not str(idempotency_key or "").strip():
            raise LedgerError("aggregate_id and idempotency_key are required")
        now = _utc_now()
        effective = normalize_timestamp(effective_at)
        seq = con.execute(
            "SELECT COALESCE(MAX(aggregate_seq), 0) + 1 FROM ledger_events "
            "WHERE aggregate_type=? AND aggregate_id=?",
            (aggregate_type, aggregate_id),
        ).fetchone()[0]
        previous = con.execute(
            "SELECT event_hash FROM ledger_events ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
        prev_hash = previous[0] if previous else None
        payload_dict = json.loads(canonical_json(dict(payload)))
        envelope = {
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "aggregate_seq": int(seq),
            "correlation_id": str(correlation_id),
            "causation_id": causation_id,
            "idempotency_key": str(idempotency_key),
            "event_type": str(event_type),
            "event_schema_version": 1,
            "environment": ENVIRONMENT,
            "effective_at": effective,
            "received_at": now,
            "recorded_at": now,
            "actor_principal": str(actor_principal),
            "intent_hash": intent_hash,
            "payload": payload_dict,
            "prev_hash": prev_hash,
        }
        event_hash = canonical_hash(envelope)
        event_uid = f"evt_{event_hash.split(':', 1)[1]}"
        cursor = con.execute(
            """
            INSERT INTO ledger_events(
                event_uid, aggregate_type, aggregate_id, aggregate_seq,
                correlation_id, causation_id, idempotency_key, event_type,
                event_schema_version, environment, effective_at, received_at,
                recorded_at, actor_principal, intent_hash, payload_json,
                prev_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'paper', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_uid, aggregate_type, aggregate_id, int(seq), correlation_id,
                causation_id, idempotency_key, event_type, effective, now, now,
                actor_principal, intent_hash, canonical_json(payload_dict), prev_hash,
                event_hash,
            ),
        )
        con.execute(
            "INSERT INTO outbox(event_uid, idempotency_key, created_at) VALUES (?, ?, ?)",
            (event_uid, f"outbox:{idempotency_key}", now),
        )
        row = con.execute(
            "SELECT * FROM ledger_events WHERE event_id=?", (cursor.lastrowid,)
        ).fetchone()
        return self._decode_event(row)

    def _escalate_kill_state_tx(
        self,
        con: sqlite3.Connection,
        to_state: str,
        *,
        reason_code: str,
        effective_at: str,
        idempotency_key: str,
        actor_principal: str,
        causation_id: str | None = None,
    ) -> dict[str, Any]:
        target = str(to_state or "").upper()
        if target not in KILL_SEVERITY or target == "NORMAL":
            raise InvalidTransition("kill escalation target must be a non-NORMAL known state")
        current = self._current_kill_state_tx(con)
        existing = self._event_by_idempotency_tx(con, idempotency_key)
        if existing:
            return existing
        if KILL_SEVERITY[target] < KILL_SEVERITY[current]:
            raise InvalidTransition(f"kill state cannot weaken from {current} to {target}")
        return self._append_event_tx(
            con,
            aggregate_type="kill_state",
            aggregate_id="paper",
            event_type="KILL_STATE_CHANGED",
            payload={"from_state": current, "to_state": target, "reason_code": str(reason_code)},
            effective_at=effective_at,
            idempotency_key=idempotency_key,
            actor_principal=actor_principal,
            correlation_id="kill:paper",
            causation_id=causation_id,
        )

    @staticmethod
    def _assert_transition(current: str | None, target: str) -> None:
        if current is None or target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidTransition(f"invalid paper intent transition: {current} -> {target}")

    def _load_intent_tx(self, con: sqlite3.Connection, intent_id: str) -> PaperOrderIntent:
        row = con.execute(
            "SELECT payload_json FROM ledger_events WHERE aggregate_type='paper_intent' "
            "AND aggregate_id=? AND event_type='INTENT_PROPOSED' ORDER BY event_id LIMIT 1",
            (str(intent_id),),
        ).fetchone()
        if not row:
            raise InvalidTransition(f"unknown intent: {intent_id}")
        return PaperOrderIntent(**json.loads(row[0]))

    @staticmethod
    def _current_state_tx(con: sqlite3.Connection, intent_id: str) -> str | None:
        placeholders = ",".join("?" for _ in STATE_BY_EVENT)
        params = [str(intent_id), *STATE_BY_EVENT.keys()]
        row = con.execute(
            f"SELECT event_type FROM ledger_events WHERE aggregate_type='paper_intent' "
            f"AND aggregate_id=? AND event_type IN ({placeholders}) ORDER BY event_id DESC LIMIT 1",
            params,
        ).fetchone()
        return STATE_BY_EVENT.get(row[0]) if row else None

    def _current_kill_state_tx(self, con: sqlite3.Connection) -> str:
        row = con.execute(
            "SELECT payload_json FROM ledger_events WHERE event_type='KILL_STATE_CHANGED' "
            "ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
        return str(json.loads(row[0]).get("to_state") or "NORMAL") if row else "NORMAL"

    def _latest_event_tx(
        self, con: sqlite3.Connection, intent_id: str, *, event_type: str
    ) -> dict[str, Any] | None:
        row = con.execute(
            "SELECT * FROM ledger_events WHERE aggregate_type='paper_intent' "
            "AND aggregate_id=? AND event_type=? ORDER BY event_id DESC LIMIT 1",
            (intent_id, event_type),
        ).fetchone()
        return self._decode_event(row) if row else None

    def _event_by_idempotency_tx(
        self, con: sqlite3.Connection, idempotency_key: str
    ) -> dict[str, Any] | None:
        row = con.execute(
            "SELECT * FROM ledger_events WHERE idempotency_key=?", (str(idempotency_key),)
        ).fetchone()
        return self._decode_event(row) if row else None

    @staticmethod
    def _assert_same_request(
        existing: Mapping[str, Any], event_type: str, payload: Mapping[str, Any]
    ) -> None:
        if existing["event_type"] != event_type or canonical_hash(existing["payload"]) != canonical_hash(payload):
            raise IdempotencyConflict("idempotency key reused for different event material")

    @staticmethod
    def _decode_event(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def _all_events_tx(self, con: sqlite3.Connection) -> list[dict[str, Any]]:
        return [
            self._decode_event(row)
            for row in con.execute("SELECT * FROM ledger_events ORDER BY event_id ASC").fetchall()
        ]

    @staticmethod
    def _intent_states_from_events(events: list[dict[str, Any]]) -> dict[str, str]:
        states: dict[str, str] = {}
        for event in events:
            state = STATE_BY_EVENT.get(event["event_type"])
            if state:
                states[event["aggregate_id"]] = state
        return states

    @staticmethod
    def _kill_state_from_events(events: list[dict[str, Any]]) -> str:
        state = "NORMAL"
        for event in events:
            if event["event_type"] == "KILL_STATE_CHANGED":
                state = str(event["payload"].get("to_state") or state)
        return state

    def _fill_payloads_tx(self, con: sqlite3.Connection, intent_id: str) -> list[dict[str, Any]]:
        rows = con.execute(
            "SELECT payload_json FROM ledger_events WHERE aggregate_type='paper_intent' "
            "AND aggregate_id=? AND event_type IN ('PAPER_PARTIAL','PAPER_FILLED') "
            "ORDER BY event_id",
            (intent_id,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    @staticmethod
    def _empty_portfolio() -> dict[str, Any]:
        return {
            "cash_krw": None,
            "reserved_cash_krw": 0,
            "positions": [],
            "gross_exposure_krw": 0,
            "net_exposure_krw": 0,
            "nav_krw": None,
            "drawdown_pct": None,
            "as_of": None,
        }

    def _portfolio_tx(self, con: sqlite3.Connection) -> dict[str, Any]:
        events = self._all_events_tx(con)
        portfolio = self._empty_portfolio()
        cash: int | None = None
        intents: dict[str, dict[str, Any]] = {}
        states: dict[str, str] = {}
        positions: dict[str, dict[str, int]] = defaultdict(
            lambda: {"quantity": 0, "book_value_krw": 0}
        )
        last_at = None
        drawdown_pct = None
        for event in events:
            last_at = event["recorded_at"]
            kind = event["event_type"]
            payload = event["payload"]
            if kind == "CAPITAL_INITIALIZED":
                cash = int(payload["cash_krw"])
            if kind == "INTENT_PROPOSED":
                intents[event["aggregate_id"]] = payload
            state = STATE_BY_EVENT.get(kind)
            if state:
                states[event["aggregate_id"]] = state
            if kind in {"PAPER_PARTIAL", "PAPER_FILLED"}:
                if cash is not None:
                    cash += int(payload["net_cash_delta_krw"])
                symbol = intents[event["aggregate_id"]]["symbol_id"]
                qty = int(payload["quantity"])
                gross = int(payload["gross_price_krw"]) * qty
                if payload["side"] == "buy":
                    positions[symbol]["quantity"] += qty
                    positions[symbol]["book_value_krw"] += gross
                else:
                    previous_qty = positions[symbol]["quantity"]
                    if previous_qty > 0:
                        released = round(positions[symbol]["book_value_krw"] * qty / previous_qty)
                    else:
                        released = gross
                    positions[symbol]["quantity"] -= qty
                    positions[symbol]["book_value_krw"] -= released
            if kind == "NAV_MARKED":
                drawdown_pct = payload.get("drawdown_pct")

        active_reservations = sum(
            int(intents[intent_id].get("notional_reservation_krw") or 0)
            for intent_id, state in states.items()
            if state in {"RESERVED", "RULE_APPROVED", "PAPER_SUBMITTED", "PARTIAL"}
            and intents.get(intent_id, {}).get("side") == "buy"
        )
        position_items = [
            {
                "symbol_id": symbol,
                "quantity": values["quantity"],
                "book_value_krw": values["book_value_krw"],
            }
            for symbol, values in sorted(positions.items())
            if values["quantity"] != 0 or values["book_value_krw"] != 0
        ]
        gross = sum(abs(item["book_value_krw"]) for item in position_items)
        net = sum(item["book_value_krw"] for item in position_items)
        projection = {
            "cash_krw": cash,
            "reserved_cash_krw": active_reservations,
            "positions": position_items,
            "gross_exposure_krw": gross,
            "net_exposure_krw": net,
            "nav_krw": cash + net if cash is not None else None,
            "drawdown_pct": drawdown_pct,
            "as_of": last_at,
        }
        projection["snapshot_hash"] = canonical_hash(projection)
        return projection

    @staticmethod
    def _verify_integrity_events(events: list[dict[str, Any]]) -> dict[str, Any]:
        errors: list[str] = []
        expected_prev = None
        seq_by_aggregate: dict[tuple[str, str], int] = {}
        for event in events:
            aggregate_key = (event["aggregate_type"], event["aggregate_id"])
            expected_seq = seq_by_aggregate.get(aggregate_key, 0) + 1
            if event["aggregate_seq"] != expected_seq:
                errors.append(
                    f"AGGREGATE_SEQUENCE_GAP:{event['event_uid']}:{expected_seq}!={event['aggregate_seq']}"
                )
            seq_by_aggregate[aggregate_key] = int(event["aggregate_seq"])
            if event["prev_hash"] != expected_prev:
                errors.append(f"GLOBAL_HASH_CHAIN_GAP:{event['event_uid']}")
            envelope = {
                key: event[key]
                for key in (
                    "aggregate_type", "aggregate_id", "aggregate_seq", "correlation_id",
                    "causation_id", "idempotency_key", "event_type", "event_schema_version",
                    "environment", "effective_at", "received_at", "recorded_at",
                    "actor_principal", "intent_hash", "payload", "prev_hash",
                )
            }
            calculated = canonical_hash(envelope)
            if calculated != event["event_hash"]:
                errors.append(f"EVENT_HASH_MISMATCH:{event['event_uid']}")
            expected_uid = f"evt_{event['event_hash'].split(':', 1)[-1]}"
            if event["event_uid"] != expected_uid:
                errors.append(f"EVENT_UID_MISMATCH:{event['event_uid']}")
            expected_prev = event["event_hash"]
        return {"ok": not errors, "checked_events": len(events), "errors": errors}
