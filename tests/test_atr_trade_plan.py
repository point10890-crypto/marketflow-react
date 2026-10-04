"""Deterministic OHLCV, ATR and causal Bollinger trade-plan contracts."""
import copy
import importlib.util
import json
import math
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean, stdev

import pytest


@pytest.fixture(scope="module")
def engine():
    path = Path(__file__).resolve().parents[1] / "app/services/mirofish/atr_trade_plan.py"
    assert path.exists(), "ATR/Bollinger trade-plan module is not implemented"
    spec = importlib.util.spec_from_file_location("atr_trade_plan_test_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prices(closes, *, symbol="005930", spread=1.):
    start = date(2024, 1, 1)
    return [dict(date=(start + timedelta(days=i)).isoformat(), symbol=symbol,
                 name="삼성전자", open=float(close), high=float(close) + spread,
                 low=float(close) - spread, close=float(close), volume=1000.)
            for i, close in enumerate(closes)]


def test_normalization_sorts_dates_preserves_extras_and_does_not_mutate_input(engine):
    rows = prices([100, 101, 102])
    rows[0].update(code="005930", extra={"source": "fixture"}, volume=0)
    rows.reverse()
    original = copy.deepcopy(rows)
    normalized = engine.validate_ohlcv(rows)
    assert rows == original
    assert [row["date"] for row in normalized] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert normalized[0]["code"] == "005930" and normalized[0]["name"] == "삼성전자"
    assert normalized[0]["extra"] == {"source": "fixture"}
    assert normalized[0]["volume"] == 0.
    assert all(isinstance(row[field], float) for row in normalized for field in ("open", "high", "low", "close", "volume"))
    assert all(row is not source for row in normalized for source in rows)


def test_symbol_scope_uniqueness_and_single_symbol_plan_boundary(engine):
    first = prices([100, 101], symbol="005930")
    second = prices([200, 201], symbol="000660")
    mixed = first + second
    assert len(engine.validate_ohlcv(mixed)) == 4
    assert [row["date"] for row in engine.validate_ohlcv(mixed)] == sorted(row["date"] for row in mixed)
    with pytest.raises(ValueError, match="single|symbol"):
        engine.build_trade_plan(mixed, atr_period=2, band_period=2)
    with pytest.raises(ValueError, match="duplicate|unique"):
        engine.validate_ohlcv(first + [dict(first[0])])


def test_code_only_and_no_symbol_sequences_are_supported(engine):
    rows = prices([100, 99])
    for row in rows:
        row["code"] = row.pop("symbol")
    assert engine.build_trade_plan(rows, atr_period=2, band_period=2)["status"] == "ready"
    for row in rows:
        row.pop("code")
    assert engine.build_trade_plan(rows, atr_period=2, band_period=2)["status"] == "ready"


@pytest.mark.parametrize("field", ["date", "open", "high", "low", "close", "volume"])
def test_missing_required_fields_fail(engine, field):
    rows = prices([100])
    rows[0].pop(field)
    with pytest.raises(ValueError):
        engine.validate_ohlcv(rows)


@pytest.mark.parametrize("field,value", [("open", True), ("close", False), ("high", math.inf),
    ("low", math.nan), ("close", -math.inf), ("volume", True), ("volume", math.nan),
    ("volume", -1.), ("open", 0.), ("high", -1.), ("low", 0.), ("close", "100"),
    ("open", 10**400), ("volume", math.inf), ("high", None)])
def test_rejects_nonfinite_nonpositive_or_non_numeric_ohlcv(engine, field, value):
    rows = prices([100])
    rows[0][field] = value
    with pytest.raises(ValueError):
        engine.validate_ohlcv(rows)


@pytest.mark.parametrize("changes", [{"low": 101.}, {"high": 99.}, {"open": 102.},
    {"open": 98.}, {"close": 102.}, {"close": 98.}, {"low": 102., "high": 101.}])
def test_rejects_inconsistent_ohlc_extrema(engine, changes):
    rows = prices([100])
    rows[0].update(changes)
    with pytest.raises(ValueError, match="OHLC|low|high|range"):
        engine.validate_ohlcv(rows)


@pytest.mark.parametrize("value", ["2024-1-1", "2024-02-30", "2024-01-01T00:00:00", "", True, None])
def test_dates_must_be_real_canonical_calendar_dates(engine, value):
    rows = prices([100])
    rows[0]["date"] = value
    with pytest.raises(ValueError, match="date|YYYY"):
        engine.validate_ohlcv(rows)


@pytest.mark.parametrize("value", [None, "ohlcv", {"date": "2024-01-01"}, [100]])
def test_container_and_rows_must_be_structured_records(engine, value):
    with pytest.raises(ValueError):
        engine.validate_ohlcv(value)


def test_true_ranges_include_both_up_and_down_gaps(engine):
    rows = prices([100, 120, 80])
    plan = engine.build_trade_plan(rows, atr_period=3, band_period=3)
    assert plan["status"] == "ready"
    assert plan["atr"] == pytest.approx((2 + 21 + 41) / 3)
    assert plan["band_mean"] == 100.
    assert plan["band_std"] == 20.  # sample variance, not population variance
    assert plan["lower_band"] == 60.
    assert plan["signal"] is False
    assert plan["entry_price"] == 60.


def test_atr_uses_simple_last_window_not_wilder_smoothing(engine):
    plan = engine.build_trade_plan(prices([100, 120, 80, 90]), atr_period=2, band_period=3)
    assert plan["atr"] == 26.  # final true ranges 41 and 11 only
    assert plan["band_mean"] == pytest.approx(fmean([120, 80, 90]))
    assert plan["band_std"] == pytest.approx(stdev([120, 80, 90]))


def test_first_true_range_is_high_minus_low_without_fabricated_previous_close(engine):
    plan = engine.build_trade_plan(prices([100]), atr_period=1, band_period=2)
    assert plan["status"] == "warmup"
    assert plan["atr"] == 2.
    assert plan["band_mean"] is None and plan["band_std"] is None


def test_band_uses_current_inclusive_sample_standard_deviation_oracle(engine):
    rows = prices([100.] * 19 + [85.])
    plan = engine.build_trade_plan(rows)
    mean, standard = fmean([100.] * 19 + [85.]), stdev([100.] * 19 + [85.])
    assert plan["band_mean"] == mean
    assert plan["band_std"] == pytest.approx(standard)
    assert plan["lower_band"] == pytest.approx(mean - 2 * standard)
    assert plan["signal"] is True
    assert plan["signal_date"] == rows[-1]["date"]
    assert plan["current_close"] == 85.
    assert plan["atr"] == 3.
    assert plan["entry_price"] == 85.
    assert plan["stop_price"] == 79.
    assert plan["target_price"] == 97.
    assert plan["loss_fraction"] == pytest.approx(6 / 85)
    assert plan["gain_fraction"] == pytest.approx(12 / 85)
    assert plan["gain_fraction"] / plan["loss_fraction"] == pytest.approx(2.)
    assert set(plan) == {"status", "signal", "signal_date", "current_close", "atr", "band_mean",
        "band_std", "lower_band", "entry_price", "stop_price", "target_price", "loss_fraction",
        "gain_fraction", "reward_risk"}
    assert not {"p", "win_rate", "kelly", "weight"} & set(plan)
    json.dumps(plan, allow_nan=False)


def test_stop_is_capped_at_eight_percent_then_target_uses_actual_capped_risk(engine):
    plan = engine.build_trade_plan(prices([100.] * 19 + [50.]))
    assert plan["signal"] is True
    assert plan["atr"] == 5.5
    assert plan["entry_price"] == 50.
    assert plan["stop_price"] == 46.
    assert plan["target_price"] == 58.
    assert plan["loss_fraction"] <= .08
    assert plan["gain_fraction"] == .16


def test_positive_band_and_inclusive_signal_threshold(engine):
    rows = prices([100., 90.])
    exact_sigma = (95. - 90.) / stdev([100., 90.])
    plan = engine.build_trade_plan(rows, atr_period=2, band_period=2, sigma=exact_sigma)
    assert plan["lower_band"] == 90.
    assert plan["signal"] is True
    assert plan["entry_price"] == 90.
    negative = engine.build_trade_plan(rows, atr_period=2, band_period=2, sigma=100.)
    assert negative["lower_band"] < 0
    assert negative["signal"] is False
    assert negative["entry_price"] == 90.


def test_warmup_does_not_invent_trade_prices_or_missing_indicators(engine):
    plan = engine.build_trade_plan([])
    assert plan["status"] == "warmup" and plan["signal"] is False
    assert plan["reward_risk"] == 2.
    assert all(value is None for field, value in plan.items() if field not in {"status", "signal", "reward_risk"})
    plan = engine.build_trade_plan(prices([100.] * 19))
    assert plan["status"] == "warmup" and plan["signal"] is False
    assert plan["atr"] == 2.
    assert plan["current_close"] == 100.
    for field in ("entry_price", "stop_price", "target_price", "loss_fraction", "gain_fraction"):
        assert plan[field] is None


def test_zero_atr_holds_even_if_price_equals_constant_lower_band(engine):
    plan = engine.build_trade_plan(prices([100.] * 20, spread=0.))
    assert plan["atr"] == 0.
    assert plan["band_std"] == 0.
    assert plan["lower_band"] == 100.
    assert plan["status"] == "held" and plan["signal"] is False
    assert all(plan[key] is None for key in ("entry_price", "stop_price", "target_price", "loss_fraction", "gain_fraction"))


def test_prefix_causality_and_input_order_independence(engine):
    rows = prices([100. + i % 5 for i in range(29)] + [90.] + [9999., 1., 5000.])
    initial = copy.deepcopy(rows)
    for index in range(20, 31):
        prefix = rows[:index]
        planned = engine.build_trade_plan(prefix)
        assert engine.build_trade_plan(list(reversed(prefix))) == planned
        changed = copy.deepcopy(rows)
        for item in changed[index:]:
            item.update(open=100_000., high=100_001., low=99_999., close=100_000.)
        assert engine.build_trade_plan(changed[:index]) == planned
    assert rows == initial


@pytest.mark.parametrize("field,value", [("atr_period", 0), ("atr_period", True), ("atr_period", 14.),
    ("band_period", 1), ("band_period", False), ("band_period", 20.), ("sigma", 0.),
    ("sigma", -1.), ("sigma", math.inf), ("sigma", True), ("atr_multiplier", 0.),
    ("atr_multiplier", math.nan), ("max_stop_fraction", 0.), ("max_stop_fraction", 1.001),
    ("max_stop_fraction", True), ("reward_risk", 0.), ("reward_risk", "2"),
    ("reward_risk", math.inf)])
def test_configuration_rejects_invalid_periods_nonfinite_or_nonpositive_parameters(engine, field, value):
    with pytest.raises(ValueError):
        engine.build_trade_plan(prices([100.] * 20), **{field: value})


def test_custom_parameters_use_unrounded_absolute_price_distances(engine):
    plan = engine.build_trade_plan(prices([100.] * 19 + [85.]), atr_multiplier=1.5,
        max_stop_fraction=.19999, reward_risk=3.)
    assert plan["stop_price"] == 80.5
    assert plan["target_price"] == 98.5
    assert plan["loss_fraction"] == pytest.approx(4.5 / 85)
    assert plan["gain_fraction"] == pytest.approx(13.5 / 85)
    assert plan["reward_risk"] == 3.


def test_target_and_band_overflow_fail_closed_instead_of_nonfinite_json(engine):
    rows = prices([100.] * 19 + [85.])
    with pytest.raises(ValueError, match="finite|overflow"):
        engine.build_trade_plan(rows, sigma=1e308)
    with pytest.raises(ValueError, match="finite|overflow"):
        engine.build_trade_plan(rows, reward_risk=1e308)
