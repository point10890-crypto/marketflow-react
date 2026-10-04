"""Pure offline tests for generalized Kelly math and conservative sizing."""
import importlib.util
import json
import math
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def engine():
    path = Path(__file__).resolve().parents[1] / "app/services/mirofish/kelly_position.py"
    assert path.exists(), "Shared Kelly position helper has not been implemented"
    spec = importlib.util.spec_from_file_location("kelly_position_test_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unit_stakes_match_reference_and_preserve_negative_edge(engine):
    assert engine.generalized_kelly(.6, 1., 1.) == pytest.approx(.2)
    assert engine.generalized_kelly(.4, 1., 1.) == pytest.approx(-.2)
    assert engine.generalized_kelly(0., 1., 1.) == -1.
    assert engine.generalized_kelly(1., 1., 1.) == 1.


def test_gain_and_loss_use_absolute_fraction_units_not_payoff_ratio(engine):
    assert engine.generalized_kelly(.5, .6, .4) == pytest.approx(5 / 12)
    assert engine.generalized_kelly(.6, .1, .1) == pytest.approx(2.)
    assert engine.calculate_kelly_position(.5, .6, .4, 30.) == pytest.approx(5 / 48)


@pytest.mark.parametrize("p,gain,loss", [(.6, 1., 1.), (.5, .6, .4), (.55, .7, .5)])
def test_generalized_solution_maximizes_expected_log_growth(engine, p, gain, loss):
    raw = engine.generalized_kelly(p, gain, loss)
    derivative = p * gain / (1 + raw * gain) - (1 - p) * loss / (1 - raw * loss)
    assert derivative == pytest.approx(0., abs=1e-14)

    def growth(fraction):
        return p * math.log1p(fraction * gain) + (1 - p) * math.log1p(-fraction * loss)

    grid = [i / 10000 for i in range(10000)]
    assert growth(raw) >= max(growth(fraction) for fraction in grid) - 1e-13
    assert growth(raw - .001) < growth(raw)
    assert growth(raw + .001) < growth(raw)


@pytest.mark.parametrize("value", [True, False, None, "0.6", math.nan, math.inf, -math.inf, 10**400])
@pytest.mark.parametrize("field", ["p", "gain_fraction", "loss_fraction"])
def test_formula_rejects_nonfinite_or_non_number_inputs(engine, field, value):
    inputs = dict(p=.6, gain_fraction=.1, loss_fraction=.1)
    inputs[field] = value
    with pytest.raises(ValueError):
        engine.generalized_kelly(**inputs)


@pytest.mark.parametrize("p,gain,loss", [(-.001, .1, .1), (1.001, .1, .1),
    (.6, 0., .1), (.6, -.1, .1), (.6, .1, 0.), (.6, .1, -.1), (.6, .1, 1.001)])
def test_formula_rejects_bad_probability_or_denominators(engine, p, gain, loss):
    with pytest.raises(ValueError):
        engine.generalized_kelly(p, gain, loss)


@pytest.mark.parametrize("p,gain,loss", [(.6, .1, 5e-324), (.4, 5e-324, .1)])
def test_formula_rejects_finite_input_calculation_overflow(engine, p, gain, loss):
    with pytest.raises(ValueError, match="finite|overflow"):
        engine.generalized_kelly(p, gain, loss)


def test_vix_boundary_quarters_full_kelly_and_records_selected_regime(engine):
    raw = engine.generalized_kelly(.6, 1., 1.)
    normal = engine.fractional_kelly(raw, vix_index=29.999)
    high = engine.fractional_kelly(raw, vix_index=30.)
    assert set(high) == {"raw_fraction", "fractional_fraction", "capped_fraction",
                         "kelly_fraction", "vix_index", "vix_high", "risk_regime"}
    assert normal["capped_fraction"] == pytest.approx(.1)
    assert normal["kelly_fraction"] == .5
    assert normal["vix_high"] is False
    assert normal["risk_regime"] == "normal_fractional_kelly"
    assert high["raw_fraction"] == pytest.approx(.2)
    assert high["fractional_fraction"] == pytest.approx(.05)
    assert high["capped_fraction"] == pytest.approx(.05)
    assert high["kelly_fraction"] == .25
    assert high["vix_high"] is True
    assert high["risk_regime"] == "vix_high_quarter_kelly"


def test_missing_vix_preserves_unknown_evidence_and_default_fraction(engine):
    result = engine.fractional_kelly(.2)
    assert result["vix_index"] is None
    assert result["vix_high"] is False
    assert result["risk_regime"] == "vix_missing_default_fraction"
    assert result["kelly_fraction"] == .5
    assert result["capped_fraction"] == .1
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_high_vix_does_not_loosen_existing_stricter_fraction(engine):
    assert engine.fractional_kelly(.8, kelly_fraction=.1, vix_index=35)["capped_fraction"] == pytest.approx(.08)
    assert engine.fractional_kelly(.8, cap_limit=0.)["capped_fraction"] == 0.


def test_explicit_full_kelly_configuration_is_preserved_until_vix_guard(engine):
    normal = engine.fractional_kelly(.1, kelly_fraction=1., vix_index=29.999)
    high = engine.fractional_kelly(.1, kelly_fraction=1., vix_index=30.)
    assert normal["kelly_fraction"] == 1.
    assert normal["fractional_fraction"] == .1
    assert high["kelly_fraction"] == .25
    assert high["fractional_fraction"] == .025


def test_long_only_sizing_preserves_raw_negative_without_creating_short_position(engine):
    result = engine.fractional_kelly(-.2, vix_index=10.)
    assert result["raw_fraction"] == -.2
    assert result["fractional_fraction"] == 0.
    assert result["capped_fraction"] == 0.


def test_raw_levered_optimum_remains_visible_but_final_position_capped(engine):
    raw = engine.generalized_kelly(.6, .1, .1)
    for vix in (None, 29.999, 30., 70.):
        result = engine.fractional_kelly(raw, vix_index=vix)
        assert result["raw_fraction"] == pytest.approx(2.)
        assert result["capped_fraction"] == .2
        assert engine.calculate_kelly_position(.6, .1, .1, vix) == .2


def test_tight_cap_is_not_rounded_above_limit(engine):
    limit = .19999
    result = engine.fractional_kelly(.9, cap_limit=limit)
    assert result["capped_fraction"] == limit
    assert engine.calculate_kelly_position(.6, .1, .1, 30., limit) == limit
    just_below = math.nextafter(limit, 0.)
    assert engine.fractional_kelly(just_below / .5, cap_limit=limit)["capped_fraction"] == just_below


@pytest.mark.parametrize("field,value", [("estimated_fraction", True), ("estimated_fraction", math.inf),
    ("estimated_fraction", 10**400), ("kelly_fraction", -.001), ("kelly_fraction", 0.), ("kelly_fraction", 1.00001),
    ("kelly_fraction", True), ("kelly_fraction", math.nan), ("cap_limit", -.001),
    ("cap_limit", .20001), ("cap_limit", True), ("cap_limit", math.inf),
    ("vix_index", -1.), ("vix_index", True), ("vix_index", "30"), ("vix_index", math.nan),
    ("vix_index", math.inf)])
def test_fractional_sizing_rejects_malformed_risk_inputs(engine, field, value):
    inputs = dict(estimated_fraction=.2, kelly_fraction=.5, cap_limit=.2, vix_index=20.)
    inputs[field] = value
    with pytest.raises(ValueError):
        engine.fractional_kelly(**inputs)


def test_two_point_summary_excludes_flat_log_contributions_but_keeps_counts(engine):
    returns = [.6, .6, -.4, -.4, 0., 0.]
    before = list(returns)
    result = engine.two_point_kelly(returns)
    assert returns == before
    assert result == pytest.approx(dict(raw_fraction=5 / 12, p=.5, gain_fraction=.6,
        loss_fraction=.4, sample_count=6, wins=2, losses=2, zeros=2,
        model="two_point_net_return_approximation", status="ready"))


def test_two_point_summary_is_an_explicit_approximation_of_actual_return_distribution(engine):
    result = engine.two_point_kelly(iter([.2, .4, -.1, -.3]))
    assert result["p"] == .5
    assert result["gain_fraction"] == pytest.approx(.3)
    assert result["loss_fraction"] == pytest.approx(.2)
    assert result["raw_fraction"] == pytest.approx(5 / 6)
    assert result["model"] == "two_point_net_return_approximation"


@pytest.mark.parametrize("values,p,gain,loss,wins,losses,zeros", [([], None, None, None, 0, 0, 0),
    ([0., 0.], None, None, None, 0, 0, 2), ([.1, .2, 0.], 1., .15, None, 2, 0, 1),
    ([-.1, -.2, 0.], 0., None, .15, 0, 2, 1)])
def test_missing_positive_or_negative_evidence_is_held_not_fabricated(engine, values, p, gain, loss, wins, losses, zeros):
    result = engine.two_point_kelly(values)
    assert result["raw_fraction"] is None
    assert result["status"] == "held"
    assert result["p"] == p
    assert result["gain_fraction"] == pytest.approx(gain) if gain is not None else result["gain_fraction"] is None
    assert result["loss_fraction"] == pytest.approx(loss) if loss is not None else result["loss_fraction"] is None
    assert (result["sample_count"], result["wins"], result["losses"], result["zeros"]) == (len(values), wins, losses, zeros)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("values", [None, "0.1", {"return": .1}, [.1, True], [.1, math.nan],
    [.1, math.inf], [.1, 10**400], [.1, -1.001]])
def test_two_point_summary_rejects_malformed_returns(engine, values):
    with pytest.raises(ValueError):
        engine.two_point_kelly(values)


def test_two_point_summary_rejects_mean_or_formula_overflow(engine):
    with pytest.raises(ValueError, match="finite|overflow"):
        engine.two_point_kelly([1e308, 1e308, -1.])
    with pytest.raises(ValueError, match="finite|overflow"):
        engine.two_point_kelly([5e-324, -1.])
