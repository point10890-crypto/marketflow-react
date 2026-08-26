from datetime import timedelta

from app.services.alpha_core import (
    CostSchedule,
    FillModel,
    MarketBar,
    PaperLedger,
    PortfolioSnapshot,
    RiskKernel,
    parse_timestamp,
    reconcile_projection,
    simulate_fill,
)

from .conftest import make_intent, make_market


def _cost():
    return CostSchedule(
        version="cost-v1-test",
        effective_from="2026-01-01",
        market="KRX",
        buy_fee_bps=2,
        sell_fee_bps=2,
        buy_tax_bps=0,
        sell_tax_bps=18,
        source="test fixture; not an operational fee claim",
    )


def _model():
    return FillModel(version="fill-test-v1", adverse_slippage_bps=10, max_bar_participation_bps=1_000)


def _bar(intent, now, **changes):
    values = {
        "symbol_id": intent.symbol_id,
        "session_date": "2026-08-24",
        "available_at": now,
        "open_krw": 10_000,
        "high_krw": 10_200,
        "low_krw": 9_900,
        "close_krw": 10_100,
        "volume": 1_000,
        "market_data_manifest_hash": make_market(intent, now).market_data_manifest_hash,
        "vwap_krw": 10_050,
    }
    values.update(changes)
    return MarketBar(**values)


def test_shadow_simulation_never_generates_a_fill(alpha_now):
    intent = make_intent(alpha_now)
    result = simulate_fill(
        intent,
        _bar(intent, alpha_now),
        cost_schedule=_cost(),
        fill_model=_model(),
        filled_at=alpha_now,
        mode="shadow",
    )

    assert result.status == "BLOCKED"
    assert result.fill is None
    assert result.reason_codes == ("SHADOW_MODE_NO_FILL",)


def test_paper_fill_is_deterministic_adverse_and_capacity_bounded(alpha_now):
    intent = make_intent(alpha_now, quantity=200, notional_reservation_krw=2_020_000)
    bar = _bar(intent, alpha_now, volume=1_000)

    first = simulate_fill(
        intent,
        bar,
        cost_schedule=_cost(),
        fill_model=_model(),
        filled_at=alpha_now,
        mode="paper",
    )
    second = simulate_fill(
        intent,
        bar,
        cost_schedule=_cost(),
        fill_model=_model(),
        filled_at=alpha_now,
        mode="paper",
    )

    assert first.status == "PARTIAL"
    assert first.fill.quantity == 100
    assert first.fill.gross_price_krw == 10_010
    assert first.fill.net_cash_delta_krw < 0
    assert first.result_hash == second.result_hash
    assert first.fill.fill_hash == second.fill.fill_hash


def test_future_or_missing_vwap_is_not_fabricated(alpha_now):
    intent = make_intent(alpha_now, order_style="paper_vwap")
    future = simulate_fill(
        intent,
        _bar(intent, alpha_now + timedelta(seconds=1)),
        cost_schedule=_cost(),
        fill_model=_model(),
        filled_at=alpha_now,
        mode="paper",
    )
    missing = simulate_fill(
        intent,
        _bar(intent, alpha_now, vwap_krw=None),
        cost_schedule=_cost(),
        fill_model=_model(),
        filled_at=alpha_now,
        mode="paper",
    )

    assert future.reason_codes == ("PIT_FUTURE_BAR",)
    assert missing.reason_codes == ("VWAP_MISSING",)
    assert future.fill is None and missing.fill is None


def test_end_to_end_fill_replay_and_reconciliation(tmp_path, alpha_now, risk_policy):
    ledger = PaperLedger(tmp_path / "paper.db", mode="paper")
    ledger.initialize()
    ledger.initialize_capital(10_000_000, effective_at=alpha_now, idempotency_key="capital")
    intent = make_intent(alpha_now)
    ledger.propose_intent(intent, idempotency_key="propose")
    pre_risk_projection = ledger.portfolio()
    evaluated_at = parse_timestamp(pre_risk_projection["as_of"]) + timedelta(seconds=1)
    decision = RiskKernel(risk_policy).evaluate(
        intent,
        PortfolioSnapshot.from_projection(pre_risk_projection),
        make_market(intent, alpha_now),
        evaluated_at=evaluated_at,
        nonce="risk",
        mode="paper",
    )
    ledger.record_risk_decision(decision, idempotency_key="risk")
    ledger.submit_paper(
        intent.intent_id,
        intent_hash=intent.intent_hash,
        risk_decision_hash=decision.decision_hash,
        submitted_at=evaluated_at + timedelta(seconds=1),
        idempotency_key="submit",
    )
    simulation = simulate_fill(
        intent,
        _bar(intent, evaluated_at + timedelta(seconds=1)),
        cost_schedule=_cost(),
        fill_model=_model(),
        filled_at=evaluated_at + timedelta(seconds=2),
        mode="paper",
    )
    ledger.record_fill(simulation.fill, idempotency_key="fill")
    projection = ledger.portfolio()
    result = reconcile_projection(
        ledger,
        reconciled_at=evaluated_at + timedelta(seconds=3),
        expected_projection=projection,
        intent_id=intent.intent_id,
    )
    ledger.record_reconciliation(result, idempotency_key="reconcile")

    after = ledger.portfolio()
    assert result.status == "MATCHED"
    assert after["cash_krw"] == projection["cash_krw"]
    assert after["positions"][0]["symbol_id"] == "005930"
    assert after["positions"][0]["quantity"] == 10
    assert ledger.status()["intent_counts"] == {"RECONCILED": 1}
    assert ledger.status()["unreconciled_count"] == 0


def test_projection_mismatch_latches_manual_halt(tmp_path, alpha_now):
    ledger = PaperLedger(tmp_path / "paper.db", mode="paper")
    ledger.initialize()
    ledger.initialize_capital(1_000_000, effective_at=alpha_now, idempotency_key="capital")
    expected = {**ledger.portfolio(), "cash_krw": 999_999}
    expected.pop("snapshot_hash")
    result = reconcile_projection(
        ledger,
        reconciled_at=alpha_now,
        expected_projection=expected,
    )
    ledger.record_reconciliation(result, idempotency_key="reconcile-mismatch")

    assert result.status == "MISMATCH"
    assert ledger.status()["kill_state"] == "MANUAL_HALT"
