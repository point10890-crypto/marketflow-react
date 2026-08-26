from dataclasses import replace
from datetime import timedelta

from app.services.alpha_core import RiskKernel

from .conftest import make_intent, make_market, make_portfolio


def test_deterministic_risk_kernel_approves_same_material(alpha_now, risk_policy):
    intent = make_intent(alpha_now)
    portfolio = make_portfolio(alpha_now)
    market = make_market(intent, alpha_now)
    kernel = RiskKernel(risk_policy)

    first = kernel.evaluate(
        intent, portfolio, market, evaluated_at=alpha_now, nonce="risk-1", mode="shadow"
    )
    second = kernel.evaluate(
        intent, portfolio, market, evaluated_at=alpha_now, nonce="risk-1", mode="shadow"
    )

    assert first.decision == "approved"
    assert first.reason_codes == ("ALL_CHECKS_PASSED",)
    assert first.decision_hash == second.decision_hash
    assert first.evaluation_mode == "shadow"


def test_stale_future_and_degraded_data_fail_closed(alpha_now, risk_policy):
    intent = make_intent(alpha_now)
    portfolio = make_portfolio(alpha_now)
    kernel = RiskKernel(risk_policy)

    stale = kernel.evaluate(
        intent,
        portfolio,
        make_market(intent, alpha_now - timedelta(seconds=301)),
        evaluated_at=alpha_now,
        nonce="stale",
        mode="shadow",
    )
    future = kernel.evaluate(
        intent,
        portfolio,
        make_market(intent, alpha_now + timedelta(seconds=1)),
        evaluated_at=alpha_now,
        nonce="future",
        mode="shadow",
    )
    degraded = kernel.evaluate(
        intent,
        portfolio,
        make_market(intent, alpha_now, quality_status="DEGRADED"),
        evaluated_at=alpha_now,
        nonce="degraded",
        mode="shadow",
    )

    assert "DATA_STALE" in stale.reason_codes
    assert "PIT_FUTURE_DATA" in future.reason_codes
    assert "DATA_QUALITY_NOT_PASS" in degraded.reason_codes
    assert {stale.decision, future.decision, degraded.decision} == {"rejected"}


def test_cash_kill_and_position_limits_are_hard_vetoes(alpha_now, risk_policy):
    intent = make_intent(alpha_now)
    market = make_market(intent, alpha_now)
    kernel = RiskKernel(risk_policy)
    constrained = make_portfolio(
        alpha_now,
        cash_krw=110_000,
        nav_krw=110_000,
        kill_state="BLOCK_NEW",
        ledger_consistent=False,
    )

    decision = kernel.evaluate(
        intent, constrained, market, evaluated_at=alpha_now, nonce="hard-veto", mode="paper"
    )

    assert decision.decision == "rejected"
    assert "KILL_STATE_BLOCK_NEW" in decision.reason_codes
    assert "LEDGER_INCONSISTENT" in decision.reason_codes
    assert "CASH_BUFFER_LIMIT" in decision.reason_codes
    assert decision.reservation_id is None


def test_reduce_only_accepts_only_bounded_sell(alpha_now, risk_policy):
    intent = make_intent(
        alpha_now,
        side="sell",
        quantity=5,
        price_guard={"min_price_krw": 9_500},
        notional_reservation_krw=0,
    )
    portfolio = make_portfolio(
        alpha_now,
        positions=({"symbol_id": "005930", "quantity": 10, "book_value_krw": 100_000},),
        gross_exposure_krw=100_000,
        net_exposure_krw=100_000,
        nav_krw=10_100_000,
        kill_state="REDUCE_ONLY",
    )
    decision = RiskKernel(risk_policy).evaluate(
        intent,
        portfolio,
        make_market(intent, alpha_now),
        evaluated_at=alpha_now,
        nonce="reduce",
        mode="shadow",
    )

    assert decision.decision == "approved"

