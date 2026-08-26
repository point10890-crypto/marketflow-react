from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.services.alpha_core import (
    AlphaCoreConfigurationError,
    ContractValidationError,
    PaperFill,
    PaperLedger,
    canonical_hash,
    canonical_json,
    resolve_mode,
)

from .conftest import make_intent


def test_canonical_hash_is_order_independent_and_decimal_safe():
    left = {"한글": [1, Decimal("1.2300")], "a": {"z": True, "x": None}}
    right = {"a": {"x": None, "z": True}, "한글": [1, Decimal("1.23")]}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_hash(left) == canonical_hash(right)


def test_equivalent_timezone_values_make_same_intent_hash(alpha_now):
    utc = make_intent(alpha_now)
    kst = make_intent(
        alpha_now,
        created_at=(alpha_now - timedelta(seconds=10)).astimezone().isoformat(),
        expires_at=(alpha_now + timedelta(minutes=10)).astimezone().isoformat(),
    )

    assert utc.intent_hash == kst.intent_hash


def test_naive_timestamp_and_tampered_hash_are_rejected(alpha_now):
    with pytest.raises(ContractValidationError, match="timezone"):
        make_intent(alpha_now, created_at="2026-08-24T09:00:00")

    intent = make_intent(alpha_now)
    with pytest.raises(ContractValidationError, match="intent_hash"):
        replace(intent, quantity=11)


@pytest.mark.parametrize("value", ["live", "LIVE", "production", "", "paper-live"])
def test_runtime_mode_has_no_live_or_implicit_fallback(value):
    with pytest.raises(AlphaCoreConfigurationError):
        resolve_mode(value)


def test_default_mode_is_shadow(monkeypatch):
    monkeypatch.delenv("ALPHACLAW_MODE", raising=False)
    assert resolve_mode() == "shadow"


def test_ledger_constructor_and_missing_status_are_side_effect_free(tmp_path):
    path = tmp_path / "nested" / "paper.db"
    ledger = PaperLedger(path, read_only=True, mode="shadow")

    status = ledger.status()

    assert status["available"] is False
    assert status["mode"] == "shadow"
    assert status["environment"] == "paper"
    assert not path.exists()
    assert not path.parent.exists()


def test_fill_cash_delta_must_reconcile_exactly(alpha_now):
    intent = make_intent(alpha_now)
    with pytest.raises(ContractValidationError, match="net_cash_delta"):
        PaperFill(
            fill_id="fill-bad",
            intent_id=intent.intent_id,
            intent_hash=intent.intent_hash,
            side="buy",
            fill_model_version="fill-v1",
            cost_schedule_version="cost-v1",
            market_data_manifest_hash=canonical_hash({"bar": 1}),
            filled_at=alpha_now,
            quantity=10,
            gross_price_krw=10_000,
            slippage_krw=0,
            fee_krw=10,
            tax_krw=0,
            net_cash_delta_krw=-100_000,
            quality_status="complete",
        )
