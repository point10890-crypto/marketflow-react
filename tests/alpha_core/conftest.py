from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.alpha_core import (
    MarketSnapshot,
    PaperOrderIntent,
    PortfolioSnapshot,
    RiskPolicy,
    canonical_hash,
)


@pytest.fixture
def alpha_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def risk_policy() -> RiskPolicy:
    return RiskPolicy(
        policy_version="risk-v1-test",
        cost_schedule_version="cost-v1-test",
        max_order_notional_krw=1_000_000,
        max_single_position_bps=2_000,
        max_gross_exposure_bps=10_000,
        max_sector_exposure_bps=5_000,
        min_cash_buffer_bps=1_000,
        max_adv_participation_bps=500,
        max_positions=20,
        max_data_age_seconds=300,
        max_daily_loss_bps=150,
        max_drawdown_bps=1_200,
        max_daily_turnover_bps=10_000,
        reservation_buffer_bps=100,
        allowed_strategy_versions=("strategy-v1",),
        allowed_model_versions=("model-v1",),
        allowed_hypothesis_ids=("hyp-1",),
        decision_ttl_seconds=60,
    )


def make_intent(now: datetime, **changes) -> PaperOrderIntent:
    values = {
        "intent_id": "poi-test-1",
        "strategy_id": "leader-follow",
        "strategy_version": "strategy-v1",
        "hypothesis_id": "hyp-1",
        "signal_instance_id": "signal-1",
        "decision_snapshot_hash": canonical_hash({"decision": 1}),
        "symbol_id": "005930",
        "side": "buy",
        "quantity": 10,
        "order_style": "next_open",
        "price_guard": {"max_price_krw": 10_500},
        "time_in_force": "paper_day",
        "notional_reservation_krw": 101_000,
        "created_at": now - timedelta(seconds=10),
        "expires_at": now + timedelta(minutes=10),
        "nonce": "intent-nonce-1",
        "model_version": "model-v1",
        "risk_policy_version": "risk-v1-test",
        "cost_schedule_version": "cost-v1-test",
        "fill_model_version": "fill-test-v1",
    }
    values.update(changes)
    return PaperOrderIntent(**values)


def make_projection(as_of: datetime, **changes) -> dict:
    material = {
        "cash_krw": 10_000_000,
        "reserved_cash_krw": 0,
        "positions": [],
        "gross_exposure_krw": 0,
        "net_exposure_krw": 0,
        "nav_krw": 10_000_000,
        "drawdown_pct": None,
        "as_of": as_of.isoformat(),
    }
    material.update(changes)
    return {**material, "snapshot_hash": canonical_hash(material)}


def make_portfolio(as_of: datetime, **changes) -> PortfolioSnapshot:
    projection_changes = {
        key: changes.pop(key)
        for key in list(changes)
        if key in {
            "cash_krw", "reserved_cash_krw", "positions", "gross_exposure_krw",
            "net_exposure_krw", "nav_krw", "drawdown_pct", "as_of",
        }
    }
    projection = make_projection(as_of, **projection_changes)
    return PortfolioSnapshot.from_projection(projection, **changes)


def make_market(intent: PaperOrderIntent, now: datetime, **changes) -> MarketSnapshot:
    values = {
        "decision_snapshot_hash": intent.decision_snapshot_hash,
        "market_data_manifest_hash": canonical_hash({"bar": 1}),
        "symbol_id": intent.symbol_id,
        "reference_price_krw": 10_000,
        "adv_value_krw": 10_000_000,
        "available_at": now,
        "quality_status": "PASS",
        "sector_id": "IT",
    }
    values.update(changes)
    return MarketSnapshot(**values)
