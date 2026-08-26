from datetime import timedelta
import sqlite3

import pytest

from app.services.alpha_core import (
    InvalidTransition,
    PaperLedger,
    PortfolioSnapshot,
    ReadOnlyLedgerError,
    RiskKernel,
    StaleApprovalError,
    parse_timestamp,
)

from .conftest import make_intent, make_market


def _ready_ledger(tmp_path, alpha_now):
    ledger = PaperLedger(tmp_path / "paper.db", mode="paper")
    ledger.initialize()
    ledger.initialize_capital(
        10_000_000,
        effective_at=alpha_now,
        idempotency_key="capital-v1",
    )
    return ledger


def test_schema_bootstrap_is_explicit_and_read_only_open_does_not_write(tmp_path):
    path = tmp_path / "paper.db"
    writer = PaperLedger(path, mode="shadow")
    assert not path.exists()
    writer.initialize()
    before = path.stat().st_mtime_ns

    reader = PaperLedger(path, read_only=True, mode="shadow")
    status = reader.status()

    assert status["available"] is True
    assert status["event_count"] == 0
    assert path.stat().st_mtime_ns == before
    with pytest.raises(ReadOnlyLedgerError):
        reader.initialize()


def test_intent_append_is_idempotent_and_sqlite_events_are_immutable(tmp_path, alpha_now):
    ledger = _ready_ledger(tmp_path, alpha_now)
    intent = make_intent(alpha_now)

    first = ledger.propose_intent(intent, idempotency_key="propose-1")
    second = ledger.propose_intent(intent, idempotency_key="propose-1")

    assert first["event_uid"] == second["event_uid"]
    assert ledger.status()["intent_counts"] == {"PROPOSED": 1}
    with sqlite3.connect(str(ledger.db_path)) as con:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute("UPDATE ledger_events SET event_type='X' WHERE event_id=?", (first["event_id"],))
    assert ledger.verify_integrity()["ok"] is True


def test_approval_is_hash_bound_atomic_and_single_use(tmp_path, alpha_now, risk_policy):
    ledger = _ready_ledger(tmp_path, alpha_now)
    intent = make_intent(alpha_now)
    ledger.propose_intent(intent, idempotency_key="propose-1")
    projection = ledger.portfolio()
    portfolio = PortfolioSnapshot.from_projection(projection)
    evaluated_at = parse_timestamp(projection["as_of"]) + timedelta(seconds=1)
    decision = RiskKernel(risk_policy).evaluate(
        intent,
        portfolio,
        make_market(intent, alpha_now),
        evaluated_at=evaluated_at,
        nonce="risk-1",
        mode="paper",
    )
    assert decision.decision == "approved"

    ledger.record_risk_decision(decision, idempotency_key="risk-record-1")
    submitted = ledger.submit_paper(
        intent.intent_id,
        intent_hash=intent.intent_hash,
        risk_decision_hash=decision.decision_hash,
        submitted_at=evaluated_at + timedelta(seconds=1),
        idempotency_key="submit-1",
    )

    assert submitted["event_type"] == "PAPER_SUBMITTED"
    assert ledger.status()["intent_counts"] == {"PAPER_SUBMITTED": 1}
    with pytest.raises(InvalidTransition):
        ledger.submit_paper(
            intent.intent_id,
            intent_hash=intent.intent_hash,
            risk_decision_hash=decision.decision_hash,
            submitted_at=evaluated_at + timedelta(seconds=2),
            idempotency_key="submit-2",
        )


def test_changed_portfolio_invalidates_precomputed_approval(tmp_path, alpha_now, risk_policy):
    ledger = _ready_ledger(tmp_path, alpha_now)
    intent = make_intent(alpha_now)
    ledger.propose_intent(intent, idempotency_key="propose-1")
    projection = ledger.portfolio()
    evaluated_at = parse_timestamp(projection["as_of"]) + timedelta(seconds=1)
    decision = RiskKernel(risk_policy).evaluate(
        intent,
        PortfolioSnapshot.from_projection(projection),
        make_market(intent, alpha_now),
        evaluated_at=evaluated_at,
        nonce="risk-1",
        mode="paper",
    )
    ledger.escalate_kill_state(
        "BLOCK_NEW",
        reason_code="TEST_INTERLOCK",
        effective_at=alpha_now,
        idempotency_key="kill-1",
    )

    with pytest.raises(StaleApprovalError):
        ledger.record_risk_decision(decision, idempotency_key="risk-record-1")


def test_competing_reservations_cannot_reuse_one_portfolio_snapshot(
    tmp_path, alpha_now, risk_policy
):
    ledger = _ready_ledger(tmp_path, alpha_now)
    first_intent = make_intent(alpha_now)
    second_intent = make_intent(
        alpha_now,
        intent_id="poi-test-2",
        signal_instance_id="signal-2",
        nonce="intent-nonce-2",
    )
    ledger.propose_intent(first_intent, idempotency_key="propose-1")
    ledger.propose_intent(second_intent, idempotency_key="propose-2")
    projection = ledger.portfolio()
    evaluated_at = parse_timestamp(projection["as_of"]) + timedelta(seconds=1)
    portfolio = PortfolioSnapshot.from_projection(projection)
    kernel = RiskKernel(risk_policy)
    first_decision = kernel.evaluate(
        first_intent,
        portfolio,
        make_market(first_intent, alpha_now),
        evaluated_at=evaluated_at,
        nonce="risk-1",
        mode="paper",
    )
    second_decision = kernel.evaluate(
        second_intent,
        portfolio,
        make_market(second_intent, alpha_now),
        evaluated_at=evaluated_at,
        nonce="risk-2",
        mode="paper",
    )

    ledger.record_risk_decision(first_decision, idempotency_key="risk-record-1")
    with pytest.raises(StaleApprovalError, match="portfolio changed"):
        ledger.record_risk_decision(second_decision, idempotency_key="risk-record-2")


def test_shadow_mode_cannot_append_capital_events(tmp_path, alpha_now):
    ledger = PaperLedger(tmp_path / "paper.db", mode="shadow")
    ledger.initialize()

    with pytest.raises(ReadOnlyLedgerError, match="shadow mode"):
        ledger.initialize_capital(
            1_000_000,
            effective_at=alpha_now,
            idempotency_key="capital",
        )
