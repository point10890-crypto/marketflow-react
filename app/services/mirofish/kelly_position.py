"""Pure Kelly diagnostics and long-only sizing; no data, account, or order access.

The generalized solution assumes two outcomes: a gain ``b`` and a loss ``a``,
both expressed as return fractions. It is an approximation when positive and
negative observations have different magnitudes. Actual-return empirical Kelly
remains a separate estimator; these helpers do not approve allocations.
"""
import math
from collections.abc import Mapping
from statistics import fmean


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def generalized_kelly(p, gain_fraction, loss_fraction):
    """Return the signed two-outcome optimum ``p/a - (1-p)/b``.

    ``a`` is the absolute loss fraction (0 < a <= 1); ``b`` is the positive
    gain fraction. Unlike the binary stake formula, b is not a payoff ratio.
    The mathematical result can be negative or above one. No cap, rounding,
    leverage permission, or investment approval is implied by this diagnostic.
    """
    probability = _number(p, "p")
    gain = _number(gain_fraction, "gain_fraction")
    loss = _number(loss_fraction, "loss_fraction")
    if not 0 <= probability <= 1:
        raise ValueError("p must be between zero and one")
    if gain <= 0:
        raise ValueError("gain_fraction must be positive")
    if not 0 < loss <= 1:
        raise ValueError("loss_fraction must be positive and at most one")
    result = probability / loss - (1 - probability) / gain
    return _number(result, "Kelly calculation result")


def fractional_kelly(estimated_fraction, *, kelly_fraction=.5, vix_index=None,
                     cap_limit=.20):
    """Apply a configured fraction, optional VIX quarter guard, and 20% cap.

    VIX >= 30 limits the configured coefficient to .25 of the full estimator,
    not .25 of an already halved allocation. Missing VIX stays None, explicitly
    retaining the configured coefficient. A caller's separate realized-volatility
    guard and portfolio exposure limit must be applied after this result.
    """
    raw = _number(estimated_fraction, "estimated_fraction")
    fraction = _number(kelly_fraction, "kelly_fraction")
    cap = _number(cap_limit, "cap_limit")
    if not 0 < fraction <= 1:
        raise ValueError("kelly_fraction must be positive and at most one")
    if not 0 <= cap <= .20:
        raise ValueError("cap_limit must be between zero and .20")

    vix = None if vix_index is None else _number(vix_index, "vix_index")
    if vix is not None and vix < 0:
        raise ValueError("vix_index cannot be negative")
    high = vix is not None and vix >= 30
    if high:
        fraction = min(fraction, .25)
        regime = "vix_high_quarter_kelly"
    elif vix is None:
        regime = "vix_missing_default_fraction"
    else:
        regime = "normal_fractional_kelly"
    partial = _number(max(0., raw) * fraction, "fractional Kelly result")
    return {
        "raw_fraction": raw,
        "fractional_fraction": partial,
        "capped_fraction": min(cap, partial),
        "kelly_fraction": fraction,
        "vix_index": vix,
        "vix_high": high,
        "risk_regime": regime,
    }


def _mean(values, label):
    if not values:
        return None
    try:
        result = fmean(values)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} calculation overflow: results must remain finite") from exc
    return _number(result, label)


def two_point_kelly(returns):
    """Summarize observed net returns into an explicit two-point approximation.

    Zero returns add zero log growth for every position, so they do not change
    the optimum's positive/negative probability; they remain in sample_count
    and zeros. Both signs are required to estimate the gain/loss diagnostic.
    'ready' means calculable, not statistically qualified or approved.
    """
    if isinstance(returns, (str, bytes, bytearray, Mapping)):
        raise ValueError("returns must be an iterable of finite numbers")
    try:
        iterator = iter(returns)
    except TypeError as exc:
        raise ValueError("returns must be an iterable of finite numbers") from exc
    values = [_number(value, "net return") for value in iterator]
    if any(value < -1 for value in values):
        raise ValueError("net returns cannot be below -100%")
    positive = [value for value in values if value > 0]
    negative = [-value for value in values if value < 0]
    directional_count = len(positive) + len(negative)
    probability = len(positive) / directional_count if directional_count else None
    gain = _mean(positive, "gain_fraction")
    loss = _mean(negative, "loss_fraction")
    calculable = bool(positive and negative)
    raw = generalized_kelly(probability, gain, loss) if calculable else None
    return {
        "raw_fraction": raw,
        "p": probability,
        "gain_fraction": gain,
        "loss_fraction": loss,
        "sample_count": len(values),
        "wins": len(positive),
        "losses": len(negative),
        "zeros": len(values) - directional_count,
        "model": "two_point_net_return_approximation",
        "status": "ready" if calculable else "held",
    }


def calculate_kelly_position(p, b, a, vix_index, cap_limit=.20):
    """Return capped half/quarter Kelly with gain b and loss a; no rounding."""
    raw = generalized_kelly(p, b, a)
    return fractional_kelly(raw, vix_index=vix_index, cap_limit=cap_limit)["capped_fraction"]
