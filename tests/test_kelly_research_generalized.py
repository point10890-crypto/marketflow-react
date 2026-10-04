"""Generalized stock Kelly and point-in-time market risk research contracts."""
import copy
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest


def engine():
    path = Path(__file__).resolve().parents[1] / "app/services/mirofish/kelly_research.py"
    spec = importlib.util.spec_from_file_location("kelly_generalized_test_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(*, winning=.035, losing=-.02, flat=False):
    days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(211)]
    rows, close = [], 100.
    rows.append({"symbol": "AAA", "name": "Alpha", "date": days[0],
                 "close": close, "open": close, "volume": 1000.})
    for cycle in range(30):
        outcome = losing if cycle % 5 == 4 else 0. if flat and cycle % 5 == 3 else winning
        for offset, change in enumerate([.01, .012, .008, -.06, 0., outcome, 0.], 1):
            close *= 1 + change
            rows.append({"symbol": "AAA", "name": "Alpha", "date": days[cycle*7+offset],
                         "close": close, "open": close, "volume": 1000.})
    funds = [{"symbol": "AAA", "available_date": days[0], "market_cap": 1e12,
              "debt_ratio": 30., "tradable": True}]
    return rows, funds, days


def run(*, rows=None, funds=None, risk=None, winning=.035, losing=-.02, flat=False, **changes):
    source_rows, source_funds, days = fixture(winning=winning, losing=losing, flat=flat)
    config = dict({"lookback": 3, "horizon": 2, "min_samples": 5, "min_win_lower": .3,
                   "fundamental_max_age_days": 1000, "volatility_threshold": .99,
                   "cost_bps": 0., "slippage_bps": 0.}, **changes)
    return engine().run_research(rows if rows is not None else source_rows,
                                 funds if funds is not None else source_funds,
                                 train_end=days[70], validation_end=days[140], test_end=days[-1],
                                 config=config, market_volatility=risk)


def frozen(report):
    return [{key: value for key, value in row.items() if key != "test"}
            for row in report["qualification"]]


def test_default_empirical_weights_keep_two_point_diagnostic_and_missing_vix_explicit():
    report = run()
    row = report["qualification"][0]
    calculation = row["kelly_calculation"]
    assert report["config"]["kelly_model"] == "empirical"
    assert row["estimated_kelly"] == pytest.approx(1.)
    assert row["target_weight"] == pytest.approx(.2)
    assert calculation["model"] == "empirical"
    assert calculation["two_point"]["raw_fraction"] == pytest.approx(34.285714285714285)
    assert calculation["vix_index"] is None
    assert calculation["vix_available_date"] is None
    assert calculation["vix_source_id"] is None
    assert calculation["vix_status"] == "missing"
    assert calculation["approval_status"] == "held"
    json.dumps(report, allow_nan=False)


def test_generalized_sizing_uses_actual_net_gain_loss_fractions_not_payoff_ratio():
    report = run(kelly_model="generalized", cost_bps=5., slippage_bps=10.)
    row = report["qualification"][0]
    calculation = row["kelly_calculation"]
    gain = 1.035*.9985/1.0015-1
    loss = 1-.98*.9985/1.0015
    expected = .8/loss-.2/gain
    assert row["eligible"]
    assert row["estimated_kelly"] == pytest.approx(expected)
    assert calculation["two_point"]["p"] == pytest.approx(.8)
    assert calculation["two_point"]["gain_fraction"] == pytest.approx(gain)
    assert calculation["two_point"]["loss_fraction"] == pytest.approx(loss)
    assert calculation["fractional_fraction"] == pytest.approx(expected*.5)
    assert calculation["capped_fraction"] == pytest.approx(.2)
    assert row["target_weight"] == pytest.approx(.2)
    assert expected > 1.


def test_two_point_flat_outcomes_are_conditional_without_inflating_gate_win_rate():
    row = run(flat=True, kelly_model="generalized")["qualification"][0]
    diagnostic = row["kelly_calculation"]["two_point"]
    assert row["eligible"]
    assert row["validation"]["win_rate"] == pytest.approx(.6)
    assert diagnostic["sample_count"] == 10
    assert diagnostic["wins"] == 6
    assert diagnostic["losses"] == 2
    assert diagnostic["zeros"] == 2
    assert diagnostic["p"] == pytest.approx(.75)
    assert diagnostic["raw_fraction"] == pytest.approx(30.357142857142858)


@pytest.mark.parametrize("model", ["empirical", "generalized"])
def test_no_loss_evidence_stays_held_and_finite_in_both_models(model):
    report = run(winning=.035, losing=.035, kelly_model=model)
    row = report["qualification"][0]
    assert not row["eligible"]
    assert row["estimated_kelly"] == 0.
    assert row["target_weight"] == 0.
    assert row["kelly_calculation"]["two_point"]["raw_fraction"] is None
    assert row["kelly_calculation"]["two_point"]["status"] == "held"
    assert report["selected_symbols"] == []
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("vix,fraction,target", [(29.99,.5,.2), (30.,.25,.19324454346729955)])
def test_vix_boundary_applies_fraction_before_the_position_cap(vix, fraction, target):
    _, _, days = fixture()
    risk = [{"available_date": days[140], "vix_index": vix, "source_id": "official-vix-cache"}]
    row = run(risk=risk, winning=1.5, losing=-.9, kelly_model="generalized")["qualification"][0]
    calculation = row["kelly_calculation"]
    assert row["estimated_kelly"] == pytest.approx(.7729781738691982)
    assert calculation["kelly_fraction"] == fraction
    assert calculation["vix_high"] is (vix >= 30)
    assert calculation["vix_available_date"] == days[140]
    assert calculation["vix_source_id"] == "official-vix-cache"
    assert calculation["vix_status"] == "available"
    assert row["target_weight"] == pytest.approx(target)


def test_stock_volatility_half_remains_separate_from_market_vix_quarter():
    _, _, days = fixture()
    risk = [{"available_date": days[140], "vix_index": 30., "source_id": "vix-cache"}]
    row = run(risk=risk, winning=1.5, losing=-.9, kelly_model="generalized",
              volatility_threshold=.0001)["qualification"][0]
    calculation = row["kelly_calculation"]
    assert calculation["kelly_fraction"] == .25
    assert calculation["stock_volatility_guard"] is True
    assert row["base_target_weight"] == pytest.approx(.19324454346729955)
    assert row["target_weight"] == pytest.approx(.09662227173364978)


def test_future_vix_and_holdout_prices_cannot_rewrite_frozen_qualification():
    rows, funds, days = fixture(winning=1.5, losing=-.9)
    historical = [{"available_date": days[140], "vix_index": 20., "source_id": "vix-cache"}]
    original = run(rows=rows, funds=funds, risk=historical, kelly_model="generalized")
    future = historical + [{"available_date": days[170], "vix_index": 99., "source_id": "future-cache"}]
    changed_rows = copy.deepcopy(rows)
    for row in changed_rows:
        if row["date"] > days[140]:
            row["close"] *= .9
            row["open"] *= .9
    changed = run(rows=changed_rows, funds=funds, risk=future, kelly_model="generalized")
    assert frozen(original) == frozen(changed)
    assert original["selected_symbols"] == changed["selected_symbols"]


def test_future_only_vix_is_missing_at_qualification_not_zero():
    _, _, days = fixture()
    risk = [{"available_date": days[150], "vix_index": 31., "source_id": "future"}]
    row = run(risk=risk)["qualification"][0]
    assert row["kelly_calculation"]["vix_index"] is None
    assert row["kelly_calculation"]["vix_status"] == "missing"
    assert row["kelly_calculation"]["vix_source_id"] is None
    assert row["target_weight"] == pytest.approx(.2)


def test_vix_available_on_execution_day_cannot_size_that_days_entry():
    _, _, days = fixture()
    risk = [{"available_date": days[140], "vix_index": 20., "source_id": "prior"},
            {"available_date": days[145], "vix_index": 30., "source_id": "new-day"}]
    report = run(risk=risk, winning=1.5, losing=-.9, kelly_model="generalized")
    entry = next(fill for fill in report["portfolio"]["fills"] if fill["side"] == "buy")
    assert entry["date"] == days[145]
    point = next(point for point in report["portfolio"]["equity_curve"] if point["date"] == days[145])
    assert point["weights"]["AAA"] == pytest.approx(.2)
    trims = [fill for fill in report["portfolio"]["fills"] if fill["reason"] == "vix_risk_trim"]
    assert trims[0]["date"] == days[146]
    point = next(point for point in report["portfolio"]["equity_curve"] if point["date"] == days[146])
    assert point["weights"]["AAA"] == pytest.approx(.19324454346729955)


def test_persistent_high_vix_reduces_new_entries_but_never_changes_frozen_targets():
    _, _, days = fixture()
    risk = [{"available_date": days[140], "vix_index": 20., "source_id": "prior"},
            {"available_date": days[142], "vix_index": 30., "source_id": "later-risk"}]
    report = run(risk=risk, winning=1.5, losing=-.9, kelly_model="generalized")
    row = report["qualification"][0]
    assert row["target_weight"] == pytest.approx(.2)
    first = next(point for point in report["portfolio"]["equity_curve"] if "AAA" in point["weights"])
    assert first["weights"]["AAA"] == pytest.approx(.19324454346729955)


def test_vix_risk_trim_uses_post_fee_equity_when_rebalance_is_disabled():
    _, _, days = fixture()
    risk = [{"available_date": days[140], "vix_index": 20., "source_id": "prior"},
            {"available_date": days[145], "vix_index": 30., "source_id": "later-risk"}]
    report = run(risk=risk, winning=1.5, losing=-.9, kelly_model="generalized",
                 cost_bps=5., slippage_bps=10.)
    # Completed validation labels: eight +150%, one +2.212%, two -90%.
    # The small gain follows a separate post-loss shock; it must not be erased.
    gain = (8*(2.5*.9985/1.0015-1)+(1.02212*.9985/1.0015-1))/9
    loss = 1-.1*.9985/1.0015
    target = ((9/11)/loss-(2/11)/gain)*.25
    trim = next(fill for fill in report["portfolio"]["fills"] if fill["reason"] == "vix_risk_trim")
    point = next(point for point in report["portfolio"]["equity_curve"] if point["date"] == trim["date"])
    assert point["weights"]["AAA"] == pytest.approx(target, abs=1e-12)
    assert trim["cost"] > 0.


@pytest.mark.parametrize("bad", [True, -1., float("nan"), float("inf"), "30"])
def test_invalid_vix_values_cannot_become_a_normal_risk_regime(bad):
    with pytest.raises(ValueError, match="vix"):
        run(risk=[{"available_date": "2024-01-01", "vix_index": bad, "source_id": "source"}])


@pytest.mark.parametrize("risk", [
    {}, [True], [{"available_date": "2024-1-1", "vix_index": 30., "source_id": "x"}],
    [{"available_date": "2024-01-01", "vix_index": 30.}],
    [{"available_date": "2024-01-01", "vix_index": 30., "source_id": " "}],
    [{"available_date": "2024-01-01", "vix_index": 20., "source_id": "x"},
     {"available_date": "2024-01-01", "vix_index": 30., "source_id": "y"}],
])
def test_malformed_or_duplicate_market_risk_rows_fail_closed(risk):
    with pytest.raises(ValueError, match="volatility|VIX|vix|source|available_date|duplicate"):
        run(risk=risk)


@pytest.mark.parametrize("model", [None, True, "unknown"])
def test_unknown_sizing_model_is_rejected_instead_of_falling_back(model):
    with pytest.raises(ValueError, match="kelly_model"):
        run(kelly_model=model)


def test_normalized_market_observations_are_preserved_for_replay_without_mutable_input_aliases():
    _, _, days = fixture()
    risk = [{"available_date": days[170], "vix_index": 31, "source_id": " newer "},
            {"available_date": days[140], "vix_index": 20, "source_id": " prior "}]
    report = run(risk=risk)
    assert report["market_volatility"] == [
        {"available_date": days[140], "vix_index": 20., "source_id": "prior"},
        {"available_date": days[170], "vix_index": 31., "source_id": "newer"}]
    risk[0]["vix_index"] = 999.
    assert report["market_volatility"][1]["vix_index"] == 31.
