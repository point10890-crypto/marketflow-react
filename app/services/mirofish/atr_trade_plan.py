"""Offline OHLCV validation and causal ATR/Bollinger price-plan arithmetic.

Prices describe a plan frozen at the last observed session, not an order or a
fill. No probability, Kelly allocation, future observation or external service
is used. ATR is a simple rolling true-range mean; bands use sample deviation.
"""
from collections.abc import Mapping
import copy
from datetime import date
import math
from statistics import fmean, stdev


def _number(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    if positive and result <= 0 or nonnegative and result < 0:
        raise ValueError(f"{label} is outside the allowed range")
    return result


def _identity(row):
    field = "symbol" if "symbol" in row else "code" if "code" in row else None
    if field is None:
        return None
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Provided symbol/code must be a nonempty string")
    return value


def _day(value):
    if not isinstance(value, str):
        raise ValueError("date must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must use a real YYYY-MM-DD calendar date") from exc
    if parsed.isoformat() != value:
        raise ValueError("date must use canonical YYYY-MM-DD")
    return value


def validate_ohlcv(rows):
    """Copy and normalize chronological rows, unique per provided symbol/date.

    Symbol (or code if no symbol is supplied) identifies each sequence. A mixed
    universe can be validated here before a caller groups it into single-symbol
    plans. Without either identity field, all rows form one unnamed sequence.
    Zero volume is valid; positive prices and consistent OHLC extrema are not
    relaxed. Non-price metadata is preserved without mutating the source.
    """
    if isinstance(rows, (str, bytes, bytearray, Mapping)):
        raise ValueError("OHLCV rows must be an iterable of objects")
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError("OHLCV rows must be an iterable of objects") from exc
    normalized, seen = [], set()
    for source in iterator:
        if not isinstance(source, dict):
            raise ValueError("OHLCV rows require objects")
        try:
            row = copy.deepcopy(source)
            row["date"] = _day(row["date"])
            for field in ("open", "high", "low", "close"):
                row[field] = _number(row[field], field, positive=True)
            row["volume"] = _number(row["volume"], "volume", nonnegative=True)
        except KeyError as exc:
            raise ValueError(f"Missing required OHLCV field: {exc.args[0]}") from exc
        if not (row["low"] <= row["open"] <= row["high"]
                and row["low"] <= row["close"] <= row["high"]):
            raise ValueError("OHLC open/close must lie between low and high")
        identity = (_identity(row), row["date"])
        if identity in seen:
            raise ValueError("OHLCV dates must be unique per symbol; duplicate observation")
        seen.add(identity)
        normalized.append(row)
    normalized.sort(key=lambda row: (row["date"], _identity(row) or ""))
    return normalized


def _period(value, label, minimum):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    return value


def _statistic(function, values, label):
    try:
        result = function(values)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} calculation overflow: results must remain finite") from exc
    return _number(result, label)


def build_trade_plan(rows, *, atr_period=14, band_period=20, sigma=2.0,
                     atr_multiplier=2.0, max_stop_fraction=.08, reward_risk=2.0):
    """Return a last-session price plan from one symbol's observed prefix.

    A close at/below a positive lower band is a signal. The planned entry uses
    min(lower band, close); execution is the caller's next-session task. Stop
    distance is bounded by the ATR multiple and maximum loss fraction. Target
    uses that actual price distance, not an assumed future win rate.
    """
    atr_period = _period(atr_period, "atr_period", 1)
    band_period = _period(band_period, "band_period", 2)
    sigma = _number(sigma, "sigma", positive=True)
    multiplier = _number(atr_multiplier, "atr_multiplier", positive=True)
    max_stop = _number(max_stop_fraction, "max_stop_fraction", positive=True)
    reward = _number(reward_risk, "reward_risk", positive=True)
    if max_stop > 1:
        raise ValueError("max_stop_fraction must be at most one")
    observations = validate_ohlcv(rows)
    if len({_identity(row) for row in observations}) > 1:
        raise ValueError("A trade plan requires a single symbol sequence")
    plan = {
        "status": "warmup", "signal": False,
        "signal_date": observations[-1]["date"] if observations else None,
        "current_close": observations[-1]["close"] if observations else None,
        "atr": None, "band_mean": None, "band_std": None, "lower_band": None,
        "entry_price": None, "stop_price": None, "target_price": None,
        "loss_fraction": None, "gain_fraction": None, "reward_risk": reward,
    }
    if len(observations) >= atr_period:
        true_ranges = []
        previous = None
        for row in observations:
            current = row["high"] - row["low"]
            if previous is not None:
                current = max(current, abs(row["high"] - previous), abs(row["low"] - previous))
            true_ranges.append(current)
            previous = row["close"]
        plan["atr"] = _statistic(fmean, true_ranges[-atr_period:], "ATR")
    if len(observations) >= band_period:
        closes = [row["close"] for row in observations[-band_period:]]
        mean = _statistic(fmean, closes, "band mean")
        standard = _statistic(stdev, closes, "band sample deviation")
        lower = _number(mean - sigma * standard, "lower band")
        plan.update(band_mean=mean, band_std=standard, lower_band=lower)
    if plan["atr"] is None or plan["lower_band"] is None:
        return plan
    plan["status"] = "held"
    if plan["atr"] <= 0:
        return plan
    close, lower = plan["current_close"], plan["lower_band"]
    entry = min(lower, close) if lower > 0 else close
    atr_distance = _number(multiplier * plan["atr"], "ATR stop distance", positive=True)
    stop = max(entry - atr_distance, entry * (1 - max_stop))
    distance = entry - stop
    if distance <= 0:
        return plan
    target = _number(entry + reward * distance, "target price", positive=True)
    loss = min(1., max_stop, _number(distance / entry, "loss fraction", positive=True))
    gain = _number((target - entry) / entry, "gain fraction", positive=True)
    plan.update(status="ready", signal=lower > 0 and close <= lower,
                entry_price=entry, stop_price=stop, target_price=target,
                loss_fraction=loss, gain_fraction=gain)
    return plan
