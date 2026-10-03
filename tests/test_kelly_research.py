"""Offline contracts for point-in-time signals, qualification and actual turnover."""
import copy
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest


def engine():
    path = Path(__file__).resolve().parents[1] / "app/services/mirofish/kelly_research.py"
    assert path.exists(), "Offline Kelly research engine has not been implemented"
    spec = importlib.util.spec_from_file_location("kelly_research_test_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(symbols=("AAA",), *, winning=.035, losing=-.02, cycles=30):
    rows, fundamentals = [], []
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(cycles * 7 + 1)]
    for symbol in symbols:
        close = 100.
        rows.append({"symbol": symbol, "name": symbol, "date": dates[0], "close": close, "open": close, "volume": 1000.})
        for cycle in range(cycles):
            outcome = losing if cycle % 5 == 4 else winning
            for offset, change in enumerate([.01, .012, .008, -.06, 0., outcome, 0.], 1):
                close *= 1 + change
                rows.append({"symbol": symbol, "name": symbol, "date": dates[cycle * 7 + offset], "close": close, "open": close, "volume": 1000.})
        fundamentals.append({"symbol": symbol, "available_date": dates[0], "market_cap": 1e12, "debt_ratio": 30., "tradable": True})
    return rows, fundamentals, dates


def config(**changes):
    return dict({"lookback": 3, "horizon": 2, "min_samples": 5, "min_win_lower": .3,
                 "fundamental_max_age_days": 1000, "volatility_threshold": .99,
                 "cost_bps": 0., "slippage_bps": 0.}, **changes)


def research(rows=None, fundamentals=None, **cfg):
    base_rows, base_fund, days = fixture()
    return engine().run_research(rows if rows is not None else base_rows,
                                 fundamentals if fundamentals is not None else base_fund,
                                 train_end=days[70], validation_end=days[140], test_end=days[-1], config=config(**cfg))


def frozen_qualification(report):
    return [{key: value for key, value in row.items() if key != "test"} for row in report["qualification"]]


def test_after_cost_samples_qualify_using_independent_train_and_validation():
    report = research()
    qualification = report["qualification"][0]
    assert qualification["eligible"]
    assert qualification["train"]["samples"] == 10
    assert qualification["validation"]["samples"] == 10
    assert qualification["validation"]["win_rate"] == pytest.approx(.8)
    assert qualification["validation"]["payoff"] == pytest.approx(1.75)
    assert report["selected_symbols"] == ["AAA"]
    assert 0 < qualification["target_weight"] <= .2
    assert report["gambling_formula_example"] == pytest.approx(.2)
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("mutation", ["nan", "negative", "duplicate", "unknown_config", "unordered_split"])
def test_invalid_inputs_fail_clearly(mutation):
    rows, funds, days = fixture()
    cfg = config()
    if mutation == "nan": rows[0]["close"] = float("nan")
    if mutation == "negative": rows[0]["close"] = 0
    if mutation == "duplicate": rows.append(dict(rows[0]))
    if mutation == "unknown_config": cfg["magic_return"] = .9
    with pytest.raises(ValueError):
        engine().run_research(rows, funds, train_end=days[140] if mutation == "unordered_split" else days[70],
                              validation_end=days[140], test_end=days[-1], config=cfg)


def test_future_test_prices_cannot_change_qualification_or_frozen_weights():
    rows, funds, days = fixture()
    original = research(rows, funds)
    changed = copy.deepcopy(rows)
    for row in changed:
        if row["date"] > days[140]:
            row["close"] *= 2 if int(row["date"][-2:]) % 2 else .4
            row["open"] = row["close"]
    modified = research(changed, funds)
    assert frozen_qualification(original) == frozen_qualification(modified)
    assert original["selected_symbols"] == modified["selected_symbols"]
    assert original["qualification"][0]["test"] != modified["qualification"][0]["test"]
    assert original["portfolio"]["metrics"] != modified["portfolio"]["metrics"]


def test_current_return_is_excluded_from_its_standardization_baseline():
    report = research()
    first = next(signal for signal in report["signal_history"] if signal["symbol"] == "AAA")
    assert first["z"] == pytest.approx((-.06 - .01) / ((.000004 + .000004) / 3) ** .5)


def test_missing_fundamental_blocks_qualification_instead_of_assuming_a_safe_company():
    report = research(fundamentals=[])
    assert report["selected_symbols"] == []
    assert "fundamental" in report["qualification"][0]["reason"]


def test_future_fundamental_cannot_qualify_earlier_signals():
    rows, funds, days = fixture()
    funds[0]["available_date"] = days[145]
    report = research(rows, funds)
    assert report["selected_symbols"] == []
    assert report["qualification"][0]["train"]["samples"] == 0


def test_high_win_rate_with_bad_payoff_is_rejected():
    rows, funds, _ = fixture(winning=.005, losing=-.20)
    report = research(rows, funds)
    assert report["qualification"][0]["validation"]["win_rate"] >= .6
    assert not report["qualification"][0]["eligible"]


@pytest.mark.parametrize("cfg", [{"min_samples": 11}, {"min_win_lower": .7}])
def test_sample_count_and_wilson_lower_guard_cannot_be_replaced_by_point_win_rate(cfg):
    report = research(**cfg)
    assert not report["qualification"][0]["eligible"]


def test_no_losses_do_not_provide_payoff_evidence():
    rows, funds, _ = fixture(losing=.035)
    report = research(rows, funds)
    assert report["qualification"][0]["validation"]["payoff"] is None
    assert report["selected_symbols"] == []


def test_costs_are_in_sample_returns_and_every_real_buy_and_sell():
    zero = research()
    paid = research(cost_bps=5, slippage_bps=10, sell_tax_bps=20)
    assert paid["qualification"][0]["validation"]["expected_net_return"] < zero["qualification"][0]["validation"]["expected_net_return"]
    fills = paid["portfolio"]["fills"]
    assert fills and all(fill["cost"] > 0 for fill in fills)
    assert paid["portfolio"]["metrics"]["total_return"] < zero["portfolio"]["metrics"]["total_return"]


def test_daily_execution_is_next_calendar_session_and_expiry_is_fixed_horizon():
    rows, _, days = fixture()
    report = research()
    fills = report["portfolio"]["fills"]
    buy = next(fill for fill in fills if fill["side"] == "buy")
    sell = next(fill for fill in fills if fill["side"] == "sell" and fill["reason"] == "horizon_expiry")
    assert days.index(buy["date"]) == days.index(buy["signal_date"]) + 1
    assert days.index(sell["date"]) == days.index(buy["date"]) + 2
    prices = {row["date"]: row["close"] for row in rows}
    assert buy["price"] == prices[buy["date"]]
    assert buy["quantity"] == sell["quantity"]
    assert len(report["portfolio"]["equity_curve"]) == 70


def test_missing_held_session_price_raises_instead_of_forward_filling_or_erasing_position():
    report = research()
    buy = next(fill for fill in report["portfolio"]["fills"] if fill["side"] == "buy")
    rows, funds, days = fixture(symbols=("AAA", "ZZZ"))
    missing = days[days.index(buy["date"]) + 1]
    rows = [row for row in rows if not (row["symbol"] == "AAA" and row["date"] == missing)]
    with pytest.raises(ValueError, match="missing"):
        research(rows, funds)


def test_union_calendar_gap_does_not_create_a_false_multiday_return_signal():
    rows, funds, days = fixture(symbols=("AAA", "ZZZ"))
    rows = [row for row in rows if not (row["symbol"] == "AAA" and row["date"] == days[10])]
    report = research(rows, funds)
    invalid = {days[index] for index in range(10, 15)}
    assert not any(signal["symbol"] == "AAA" and signal["date"] in invalid for signal in report["signal_history"])


def test_open_execution_requires_real_open_prices():
    rows, funds, _ = fixture()
    for row in rows: row.pop("open")
    with pytest.raises(ValueError, match="open"):
        research(rows, funds, execution_price="open")


def test_top_three_are_deterministic_and_actual_entry_caps_preserve_cash():
    rows, funds, _ = fixture(symbols=("DDD", "CCC", "BBB", "AAA"))
    report = research(rows, funds, cost_bps=5, slippage_bps=10)
    assert report["selected_symbols"] == ["AAA", "BBB", "CCC"]
    curve = report["portfolio"]["equity_curve"]
    assert all(point["cash"] >= 0 for point in curve)
    first_active = next(point for point in curve if point["exposure"] > 0)
    assert first_active["exposure"] <= .6 + 1e-9
    assert first_active["cash"] / first_active["equity"] >= .4 - 1e-9
    assert max(first_active["weights"].values()) <= .2 + 1e-9


def test_high_prior_volatility_halves_the_validation_frozen_weight():
    normal = research()
    cautious = research(volatility_threshold=.0001)
    assert cautious["qualification"][0]["target_weight"] == pytest.approx(normal["qualification"][0]["target_weight"] / 2)
    assert cautious["qualification"][0]["target_weight"] <= .1


def test_empirical_stock_kelly_is_not_the_gambling_formula():
    module = engine()
    assert module.empirical_kelly([.01] * 6 + [-.01] * 4) == pytest.approx(1.)
    assert module.empirical_kelly([1.] * 6 + [-1.] * 4) == pytest.approx(.2)
    assert module.empirical_kelly([.01] + [-.10] * 9) == 0


def test_rebalance_topups_have_turnover_cost_and_declared_calibration_mismatch():
    fixed = research(cost_bps=5, slippage_bps=10)
    rebalanced = research(rebalance=True, cost_bps=5, slippage_bps=10)
    assert any(fill["reason"] == "rebalance" for fill in rebalanced["portfolio"]["fills"])
    assert rebalanced["portfolio"]["fills"] != fixed["portfolio"]["fills"]
    assert any("calibration" in warning for warning in rebalanced["warnings"])


def test_labels_crossing_train_boundary_are_not_counted_in_either_phase():
    rows, funds, days = fixture()
    report = engine().run_research(rows, funds, train_end=days[6], validation_end=days[14], test_end=days[21], config=config(min_samples=1, min_win_lower=0))
    assert report["qualification"][0]["train"]["samples"] == 0  # first exit is session seven
    assert report["qualification"][0]["validation"]["samples"] == 1  # entry twelve, exit fourteen


def test_flat_forward_outcomes_become_losses_after_costs():
    rows, funds, _ = fixture(winning=0, losing=0)
    report = research(rows, funds, cost_bps=5, slippage_bps=10)
    metrics = report["qualification"][0]["validation"]
    assert metrics["samples"] > 0
    assert metrics["win_rate"] == 0
    assert metrics["expected_net_return"] < 0
    assert not report["qualification"][0]["eligible"]


def test_zero_historical_sigma_never_creates_a_signal():
    rows, funds, _ = fixture()
    for row in rows:
        row["close"] = row["open"] = 100.
    report = research(rows, funds)
    assert report["signal_history"] == []
    assert report["selected_symbols"] == []


def test_drawdown_halt_exits_at_the_following_execution_session_and_stays_in_cash():
    base = research()
    first_buy = next(fill for fill in base["portfolio"]["fills"] if fill["side"] == "buy")
    rows, funds, days = fixture()
    loss_day = days[days.index(first_buy["date"])+1]
    for row in rows:
        if row["date"] >= loss_day:
            row["close"] *= .4
            row["open"] = row["close"]
    report = research(rows, funds, drawdown_halt=.05)
    halt_sell = next(fill for fill in report["portfolio"]["fills"] if fill["reason"] == "drawdown_halt")
    assert days.index(halt_sell["date"]) == days.index(loss_day)+1
    assert not any(fill["side"] == "buy" and fill["date"] >= halt_sell["date"] for fill in report["portfolio"]["fills"])
    assert report["portfolio"]["equity_curve"][-1]["cash"] == report["portfolio"]["equity_curve"][-1]["equity"]


def test_test_period_tradability_change_exits_without_changing_frozen_qualification():
    original = research()
    buy = next(fill for fill in original["portfolio"]["fills"] if fill["side"] == "buy")
    rows, funds, days = fixture()
    known_day = days[days.index(buy["date"])+1]
    funds.append(dict(funds[0], available_date=known_day, tradable=False))
    report = research(rows, funds)
    assert frozen_qualification(report) == frozen_qualification(original)
    sell = next(fill for fill in report["portfolio"]["fills"] if fill["reason"] == "fundamental_not_tradable")
    assert days.index(sell["date"]) == days.index(known_day)+1


def test_stale_fundamentals_liquidate_existing_holdings():
    rows, initial_fund, days = fixture(losing=-.06)
    funds = [dict(initial_fund[0], available_date=day) for day in days[:141]]
    report = research(rows, funds, horizon=5, fundamental_max_age_days=6)
    assert report["selected_symbols"]
    assert any(fill["reason"] == "fundamental_stale_fundamental" for fill in report["portfolio"]["fills"])


def test_open_prices_are_used_when_requested_and_final_liquidation_is_charged():
    rows, funds, days = fixture()
    for row in rows: row["open"] = row["close"]*.98
    report = research(rows, funds, execution_price="open", cost_bps=5, slippage_bps=10)
    fills = report["portfolio"]["fills"]
    for fill in fills:
        actual = next(row for row in rows if row["date"] == fill["date"])
        assert fill["price"] == actual["open"]
    assert fills[-1]["date"] == days[-1]
    assert fills[-1]["reason"] == "end_of_test"
    assert fills[-1]["cost"] > 0
    assert report["portfolio"]["equity_curve"][-1]["exposure"] == 0


def test_benchmark_has_the_same_test_period_execution_and_cost_assumptions():
    rows, funds, days = fixture(symbols=("AAA", "BENCH"))
    report = engine().run_research(rows, funds, train_end=days[70], validation_end=days[140], test_end=days[-1], benchmark_symbol="BENCH", config=config(cost_bps=5, slippage_bps=10))
    assert "BENCH" not in report["selected_symbols"]
    benchmark = report["benchmark"]
    assert benchmark["fills"][0]["date"] == days[141]
    assert benchmark["fills"][-1]["date"] == days[-1]
    assert all(fill["cost"] > 0 for fill in benchmark["fills"])
    expected = rows[-1]["close"]*(1-.0015)/(next(row["close"] for row in rows if row["symbol"] == "BENCH" and row["date"] == days[141])*(1+.0015))-1
    assert benchmark["metrics"]["total_return"] == pytest.approx(expected)


def test_finite_but_overflowing_price_ratios_fail_with_a_clear_error():
    rows, funds, _ = fixture()
    rows[3]["close"] = 1e-308
    rows[4]["close"] = 1e308
    with pytest.raises(ValueError, match="finite|overflow"):
        research(rows, funds)


def test_zero_volume_entry_session_does_not_execute_a_prior_signal():
    first_buy = next(fill for fill in research()["portfolio"]["fills"] if fill["side"] == "buy")
    rows, funds, _ = fixture()
    next(row for row in rows if row["date"] == first_buy["date"])["volume"] = 0
    report = research(rows, funds)
    assert not any(fill["side"] == "buy" and fill["date"] == first_buy["date"] for fill in report["portfolio"]["fills"])


def test_zero_volume_training_exit_is_incomplete_evidence_not_an_omitted_loss():
    rows, funds, days = fixture()
    next(row for row in rows if row["date"] == days[35])["volume"] = 0  # losing sample
    with pytest.raises(ValueError, match="incomplete execution outcome"):
        research(rows, funds)


def test_held_zero_volume_exit_cannot_be_reported_as_an_actual_fill():
    first_sell = next(fill for fill in research()["portfolio"]["fills"] if fill["side"] == "sell")
    rows, funds, _ = fixture()
    next(row for row in rows if row["date"] == first_sell["date"])["volume"] = 0
    with pytest.raises(ValueError, match="volume|executable"):
        research(rows, funds)


def test_current_signals_do_not_recycle_an_older_event_after_a_tradability_change():
    rows, funds, days = fixture()
    funds.append(dict(funds[0], available_date=days[-1], tradable=False))
    report = research(rows, funds)
    assert all(signal["date"] == days[-1] and signal["as_of"] == days[-1] for signal in report["signals"])
    assert not any(signal["eligible"] for signal in report["signals"])
    assert report["signal_history"]


def test_missing_volume_is_an_explicit_execution_assumption():
    rows, funds, _ = fixture()
    for row in rows: row.pop("volume")
    report = research(rows, funds)
    assert any("volume" in warning for warning in report["warnings"])


def test_holdout_confusion_counts_cover_selected_and_unselected_completed_opportunities():
    rows, funds, _ = fixture(symbols=("AAA", "BBB", "CCC", "DDD"))
    report = research(rows, funds)
    assert all(item["test"]["samples"] == 10 for item in report["qualification"])
    evaluation = report["evaluation"]
    assert evaluation["true_positive"] == 24
    assert evaluation["false_positive"] == 6
    assert evaluation["false_negative"] == 8
    assert evaluation["true_negative"] == 2
    assert evaluation["scope"] == "fixed-horizon completed signal opportunities in supplied universe"
    assert any("false negatives" in warning for warning in report["warnings"])


def test_high_volatility_trim_targets_post_fee_equity():
    report = research(volatility_threshold=.03, cost_bps=5, slippage_bps=10)
    trim = next(fill for fill in report["portfolio"]["fills"] if fill["reason"] == "volatility_risk_trim")
    point = next(point for point in report["portfolio"]["equity_curve"] if point["date"] == trim["date"])
    assert point["weights"]["AAA"] == pytest.approx(.1, abs=1e-12)


def test_zero_volume_sample_entry_is_an_unfilled_opportunity():
    rows, funds, days = fixture()
    next(row for row in rows if row["date"] == days[5])["volume"] = 0
    report = research(rows, funds)
    assert report["qualification"][0]["train"]["samples"] == 9
    assert report["qualification"][0]["validation"]["samples"] == 10


def test_missing_price_inside_a_completed_sample_is_not_silently_censored():
    rows, funds, days = fixture(symbols=("AAA", "ZZZ"))
    rows = [row for row in rows if not (row["symbol"] == "AAA" and row["date"] == days[6])]
    with pytest.raises(ValueError, match="incomplete execution outcome"):
        research(rows, funds)


def test_current_signal_ineligible_when_current_fundamentals_are_untradable():
    rows, funds, days = fixture()
    rows[-1]["close"] *= .75
    rows[-1]["open"] = rows[-1]["close"]
    funds.append(dict(funds[0], available_date=days[-1], tradable=False))
    report = research(rows, funds)
    assert len(report["signals"]) == 1
    current = report["signals"][0]
    assert current["date"] == current["as_of"] == days[-1]
    assert not current["eligible"] and current["fundamental_reason"] == "not_tradable"
