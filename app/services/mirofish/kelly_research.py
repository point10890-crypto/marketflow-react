"""Offline point-in-time mean-reversion research; no API, account, or order access.

Qualification is frozen at validation end. Returns and allocation are research
diagnostics, not calibrated future probabilities or production trading signals.
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date
import math
from statistics import fmean, pstdev

if __package__:
    from .kelly_position import fractional_kelly, two_point_kelly
else:
    # The offline CLI and tests also load this module without the Flask package.
    import importlib.util
    from pathlib import Path
    _position_spec = importlib.util.spec_from_file_location(
        "marketflow_offline_kelly_position", Path(__file__).with_name("kelly_position.py"))
    _position_module = importlib.util.module_from_spec(_position_spec)
    _position_spec.loader.exec_module(_position_module)
    fractional_kelly, two_point_kelly = _position_module.fractional_kelly, _position_module.two_point_kelly


DEFAULT_CONFIG = {
    "lookback": 60, "horizon": 5, "z_threshold": -2., "min_samples": 30,
    "min_win_rate": .60, "min_payoff": 1., "min_win_lower": .60,
    "confidence_z": 1.96, "max_weight": .20, "kelly_fraction": .5, "kelly_model": "empirical",
    "max_exposure": .60, "max_positions": 3, "min_market_cap": 300e9,
    "max_debt_ratio": 150., "fundamental_max_age_days": 180,
    "cost_bps": 5., "slippage_bps": 10., "sell_tax_bps": 0.,
    "execution_price": "close", "rebalance": False,
    "volatility_threshold": .03, "drawdown_halt": .20,
}


def _number(value, label, *, minimum=None, positive=False):
    try:
        finite = math.isfinite(value) if isinstance(value, (int, float)) else False
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite:
        raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise ValueError(f"{label} is outside the allowed range")
    return value


def _finite_report(value):
    """Reject numerical overflow rather than emitting nonstandard JSON numbers."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("research calculation overflow: results must remain finite")
    if isinstance(value, dict):
        for item in value.values(): _finite_report(item)
    elif isinstance(value, list):
        for item in value: _finite_report(item)


def _day(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return parsed


def _configuration(overrides):
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError("config must be a dictionary")
    unknown = set(overrides or {}) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown config fields: {', '.join(sorted(unknown))}")
    cfg = dict(DEFAULT_CONFIG, **(overrides or {}))
    integer_fields = {"lookback", "horizon", "min_samples", "max_positions", "fundamental_max_age_days"}
    for key, value in cfg.items():
        if key in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int) or value < (2 if key == "lookback" else 1):
                raise ValueError(f"{key} must be a positive integer")
        elif key == "rebalance":
            if not isinstance(value, bool):
                raise ValueError("rebalance must be a boolean")
        elif key == "execution_price":
            if value not in {"close", "open"}:
                raise ValueError("execution_price must be close or open")
        elif key == "kelly_model":
            if not isinstance(value, str) or value not in {"empirical", "generalized"}:
                raise ValueError("kelly_model must be empirical or generalized")
        else:
            cfg[key] = _number(value, key)
    if cfg["z_threshold"] >= 0:
        raise ValueError("z_threshold must be negative")
    if not 0 < cfg["max_weight"] <= .2 or not 0 < cfg["max_exposure"] <= .6 or cfg["max_positions"] > 3:
        raise ValueError("entry caps cannot exceed 20% per symbol, 60% total, or three positions")
    if not 0 < cfg["kelly_fraction"] <= 1 or not 0 < cfg["drawdown_halt"] < 1:
        raise ValueError("kelly_fraction and drawdown_halt are outside their allowed ranges")
    for key in ("min_win_rate", "min_win_lower"):
        if not 0 <= cfg[key] <= 1:
            raise ValueError(f"{key} must be between zero and one")
    for key in ("min_market_cap", "max_debt_ratio", "min_payoff", "cost_bps", "slippage_bps", "sell_tax_bps"):
        if cfg[key] < 0:
            raise ValueError(f"{key} cannot be negative")
    if cfg["confidence_z"] <= 0 or cfg["volatility_threshold"] <= 0:
        raise ValueError("confidence_z and volatility_threshold must be positive")
    if cfg["cost_bps"] + cfg["slippage_bps"] + cfg["sell_tax_bps"] >= 10000:
        raise ValueError("combined exit cost must be below 10000 basis points")
    return cfg


def empirical_kelly(returns):
    """Maximize mean log(1 + fR) for the actual stock net returns, 0 <= f <= 1."""
    values = [_number(value, "net return") for value in returns]
    if not values or any(value < -1 for value in values):
        if values:
            raise ValueError("net returns cannot be below -100%")
        return 0.
    def derivative(fraction):
        terms = []
        for value in values:
            denominator = 1 + fraction * value
            if denominator <= 0:
                return -math.inf
            terms.append(value / denominator)
        return fmean(terms)
    if derivative(0.) <= 0:
        return 0.
    if derivative(1.) >= 0:
        return 1.
    lower, upper = 0., 1.
    for _ in range(80):
        middle = (lower + upper) / 2
        if derivative(middle) > 0:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2


def _metrics(returns, cfg):
    n = len(returns)
    positives = [value for value in returns if value > 0]
    negatives = [value for value in returns if value < 0]
    p = len(positives) / n if n else 0.
    z2 = cfg["confidence_z"] ** 2
    lower = ((p + z2 / (2*n) - cfg["confidence_z"] * math.sqrt(p*(1-p)/n + z2/(4*n*n))) / (1+z2/n)) if n else 0.
    avg_win = fmean(positives) if positives else None
    avg_loss = abs(fmean(negatives)) if negatives else None
    return {"samples": n, "win_rate": p, "win_lower": max(0., lower),
            "avg_win": avg_win, "avg_loss": avg_loss,
            "payoff": avg_win / avg_loss if avg_win is not None and avg_loss else None,
            "expected_net_return": fmean(returns) if n else None}


def _failed_metrics(metrics, cfg):
    if metrics["samples"] < cfg["min_samples"]: return "insufficient_samples"
    if metrics["payoff"] is None: return "insufficient_payoff_evidence"
    if metrics["win_rate"] < cfg["min_win_rate"]: return "low_win_rate"
    if metrics["payoff"] < cfg["min_payoff"]: return "low_payoff"
    if metrics["expected_net_return"] <= 0: return "nonpositive_net_expectancy"
    if metrics["win_lower"] < cfg["min_win_lower"]: return "low_wilson_lower_bound"
    return None


def _curve_metrics(curve, fills):
    peak, drawdown = 1., 0.
    previous, returns = 1., []
    for point in curve:
        value = point["equity"]
        peak = max(peak, value)
        drawdown = max(drawdown, 1-value/peak)
        returns.append(_number(value/previous-1, "daily return"))
        previous = value
    return {"total_return": curve[-1]["equity"]-1 if curve else 0., "max_drawdown": drawdown,
            "daily_volatility": pstdev(returns) if returns else 0.,
            "total_cost": sum(fill["cost"] for fill in fills), "turnover": sum(fill["quantity"]*fill["price"] for fill in fills),
            "fill_count": len(fills)}


def _market_volatility_series(rows):
    """Index optional, explicitly available market observations without fabrication."""
    if rows is None:
        return [], []
    if not isinstance(rows, list):
        raise ValueError("market_volatility must be a list of VIX observations")
    by_date = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("market_volatility rows must be dictionaries")
        available = _day(row.get("available_date"), "VIX available_date")
        if available in by_date:
            raise ValueError("duplicate VIX available_date")
        vix = _number(row.get("vix_index"), "vix_index", minimum=0.)
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("VIX source_id is required")
        by_date[available] = {"available_date": available.isoformat(), "vix_index": vix,
                              "source_id": source_id.strip()}
    dates = sorted(by_date)
    return dates, [by_date[day] for day in dates]


def run_research(prices: list[dict], fundamentals: list[dict], *, train_end: str, validation_end: str,
                 test_end: str | None = None, benchmark_symbol: str | None = None, config: dict | None = None,
                 market_volatility: list[dict] | None = None) -> dict:
    cfg = _configuration(config)
    market_dates, market_rows = _market_volatility_series(market_volatility)
    def market_at(day):
        index = bisect_right(market_dates, day)-1
        return market_rows[index] if index >= 0 else None
    train_date, validation_date = _day(train_end, "train_end"), _day(validation_end, "validation_end")
    if train_date >= validation_date:
        raise ValueError("splits must satisfy train_end < validation_end < test_end")
    if not isinstance(prices, list) or not prices or not isinstance(fundamentals, list):
        raise ValueError("nonempty prices and a fundamentals list are required")
    series, names, calendar_set = defaultdict(dict), {}, set()
    for raw in prices:
        if not isinstance(raw, dict): raise ValueError("price rows must be dictionaries")
        symbol = raw.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip(): raise ValueError("price symbol is required")
        symbol = symbol.strip()
        day = _day(raw.get("date"), "price date")
        if day in series[symbol]: raise ValueError(f"duplicate price: {symbol} {day}")
        row = {"close": _number(raw.get("close"), "close", positive=True)}
        for field in ("open", "volume"):
            if raw.get(field) is not None:
                row[field] = _number(raw[field], field, minimum=0, positive=field == "open")
        if cfg["execution_price"] == "open" and "open" not in row:
            raise ValueError(f"open execution requires actual open: {symbol} {day}")
        series[symbol][day] = row
        names.setdefault(symbol, str(raw.get("name") or symbol))
        calendar_set.add(day)
    calendar = sorted(calendar_set)
    end_date = _day(test_end, "test_end") if test_end is not None else calendar[-1]
    if not train_date < validation_date < end_date or end_date > calendar[-1] or len(calendar) < 3:
        raise ValueError("splits must have train, validation, and test dates within the price calendar")
    if not any(day <= train_date for day in calendar) or not any(train_date < day <= validation_date for day in calendar) or not any(validation_date < day <= end_date for day in calendar):
        raise ValueError("each split requires at least one calendar session")
    calendar = [day for day in calendar if day <= end_date]
    fundamental_map = defaultdict(dict)
    for raw in fundamentals:
        if not isinstance(raw, dict): raise ValueError("fundamental rows must be dictionaries")
        symbol = raw.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip(): raise ValueError("fundamental symbol is required")
        symbol = symbol.strip()
        available = _day(raw.get("available_date"), "available_date")
        if available in fundamental_map[symbol]: raise ValueError(f"duplicate fundamental: {symbol} {available}")
        if not isinstance(raw.get("tradable"), bool): raise ValueError("tradable must be a boolean")
        fundamental_map[symbol][available] = {"market_cap": _number(raw.get("market_cap"), "market_cap", positive=True),
            "debt_ratio": _number(raw.get("debt_ratio"), "debt_ratio", minimum=0), "tradable": raw["tradable"]}
    fundamental_dates = {symbol: sorted(data) for symbol, data in fundamental_map.items()}
    def fundamental_check(symbol, day):
        dates = fundamental_dates.get(symbol, [])
        index = bisect_right(dates, day)-1
        if index < 0: return False, "missing_fundamental"
        available = dates[index]
        data = fundamental_map[symbol][available]
        if (day-available).days > cfg["fundamental_max_age_days"]: return False, "stale_fundamental"
        if not data["tradable"]: return False, "not_tradable"
        if data["market_cap"] < cfg["min_market_cap"]: return False, "market_cap_filter"
        if data["debt_ratio"] > cfg["max_debt_ratio"]: return False, "debt_ratio_filter"
        return True, None
    observations, signals = defaultdict(dict), defaultdict(dict)
    signal_history = []
    for symbol in sorted(series):
        data = series[symbol]
        for index in range(cfg["lookback"]+1, len(calendar)):
            window_days = calendar[index-cfg["lookback"]-1:index+1]
            if any(day not in data for day in window_days): continue
            values = [data[day]["close"] for day in window_days]
            returns = [_number(current/previous-1, "derived return") for previous, current in zip(values, values[1:])]
            baseline = returns[:-1]
            sigma = pstdev(baseline)
            observations[symbol][index] = sigma
            if sigma <= 1e-12: continue
            z_score = _number((returns[-1]-fmean(baseline))/sigma, "signal z score")
            if z_score > cfg["z_threshold"]: continue
            day = calendar[index]
            okay, reason = fundamental_check(symbol, day)
            if "volume" in data[day] and data[day]["volume"] <= 0:
                okay, reason = False, "zero_volume"
            signal = {"symbol": symbol, "name": names[symbol], "date": day.isoformat(), "z": z_score,
                      "prior_volatility": sigma, "fundamental_ok": okay, "fundamental_reason": reason}
            signals[symbol][index] = signal
            signal_history.append(signal)
    entry_cost = (cfg["cost_bps"]+cfg["slippage_bps"])/10000
    exit_cost = entry_cost+cfg["sell_tax_bps"]/10000
    def samples(symbol, lower, upper):
        result, previous_exit = [], -1
        for index, signal in sorted(signals[symbol].items()):
            entry, exit_index = index+1, index+1+cfg["horizon"]
            if not signal["fundamental_ok"] or exit_index >= len(calendar): continue
            if lower is not None and calendar[entry] <= lower: continue
            if calendar[exit_index] > upper or entry < previous_exit: continue
            entry_row = series[symbol].get(calendar[entry])
            if entry_row is None or entry_row.get("volume", 1.) <= 0: continue
            if any(day not in series[symbol] for day in calendar[entry:exit_index+1]):
                raise ValueError(f"incomplete execution outcome: missing held sample price for {symbol}")
            if series[symbol][calendar[exit_index]].get("volume", 1.) <= 0:
                raise ValueError(f"incomplete execution outcome: zero exit volume for {symbol} {calendar[exit_index]}")
            buy, sell = (series[symbol][calendar[i]][cfg["execution_price"]] for i in (entry, exit_index))
            result.append(_number(sell*(1-exit_cost)/(buy*(1+entry_cost))-1, "sample net return"))
            previous_exit = exit_index
        return result
    qualifications = []
    last_validation_index = bisect_right(calendar, validation_date)-1
    for symbol in sorted(series):
        train_returns, validation_returns = samples(symbol, None, train_date), samples(symbol, train_date, validation_date)
        train_metrics, validation_metrics = _metrics(train_returns, cfg), _metrics(validation_returns, cfg)
        okay, reason = fundamental_check(symbol, validation_date)
        if symbol == benchmark_symbol: okay, reason = False, "benchmark_only"
        prior_vol = observations[symbol].get(last_validation_index)
        if okay and prior_vol is None: okay, reason = False, "validation_price_gap_or_insufficient_lookback"
        if okay:
            failed = _failed_metrics(train_metrics, cfg)
            if failed: okay, reason = False, "train_"+failed
        if okay:
            failed = _failed_metrics(validation_metrics, cfg)
            if failed: okay, reason = False, "validation_"+failed
        empirical_fraction = empirical_kelly(validation_returns) if validation_returns else None
        two_point = two_point_kelly(validation_returns)
        raw_fraction = empirical_fraction if cfg["kelly_model"] == "empirical" else two_point["raw_fraction"]
        market = market_at(validation_date)
        vix_index = market["vix_index"] if market else None
        calculation = fractional_kelly(estimated_fraction=raw_fraction if raw_fraction is not None else 0.,
            kelly_fraction=cfg["kelly_fraction"], vix_index=vix_index, cap_limit=cfg["max_weight"])
        if raw_fraction is None:
            for key in ("raw_fraction", "fractional_fraction", "capped_fraction"):
                calculation[key] = None
        if okay and raw_fraction is None:
            okay, reason = False, "insufficient_kelly_evidence"
        estimated = raw_fraction if okay else 0.
        base_weight = calculation["capped_fraction"] if okay else 0.
        stock_guard = prior_vol is not None and prior_vol > cfg["volatility_threshold"]
        weight = base_weight*.5 if stock_guard else base_weight
        calculation.update({"model": cfg["kelly_model"], "two_point": two_point,
            "empirical_fraction": empirical_fraction, "applied": okay,
            "held_reason": None if okay else reason, "approval_status": "held",
            "input_basis": "validation_realized_net_returns",
            "vix_status": "available" if market else "missing",
            "vix_available_date": market["available_date"] if market else None,
            "vix_source_id": market["source_id"] if market else None,
            "stock_volatility_guard": stock_guard, "target_weight": weight})
        qualifications.append({"symbol": symbol, "name": names[symbol], "eligible": okay, "reason": reason or "qualified",
            "train": train_metrics, "validation": validation_metrics, "estimated_kelly": estimated,
            "base_target_weight": base_weight, "target_weight": weight, "prior_volatility": prior_vol,
            "kelly_calculation": calculation})
    selected = sorted((item for item in qualifications if item["eligible"] and item["target_weight"] > 0),
                      key=lambda item: (-item["validation"]["expected_net_return"], item["symbol"]))[:cfg["max_positions"]]
    selected_symbols = [item["symbol"] for item in selected]
    weights = {item["symbol"]: item["target_weight"] for item in selected}
    estimated_fractions = {item["symbol"]: item["estimated_kelly"] for item in selected}
    def execution_target(symbol, prior_day, stock_guard):
        # Qualification and its return estimates stay frozen. Newly available
        # market risk can only lower the configured, frozen execution ceiling.
        market = market_at(prior_day)
        stage = fractional_kelly(estimated_fraction=estimated_fractions[symbol],
            kelly_fraction=cfg["kelly_fraction"], vix_index=market["vix_index"] if market else None,
            cap_limit=cfg["max_weight"])
        target = stage["capped_fraction"]*(.5 if stock_guard else 1.)
        return min(weights[symbol], target), stage["vix_high"]
    # Holdout labels are diagnostics only: eligibility, ranking and weights are
    # already frozen above and never read these test returns.
    evaluation = {"true_positive": 0, "false_positive": 0, "false_negative": 0, "true_negative": 0,
                  "scope": "fixed-horizon completed signal opportunities in supplied universe"}
    for item in qualifications:
        test_returns = samples(item["symbol"], validation_date, end_date)
        item["test"] = _metrics(test_returns, cfg)
        if item["symbol"] == benchmark_symbol: continue
        predicted = item["symbol"] in selected_symbols
        for net_return in test_returns:
            key = ("true_positive" if net_return > 0 else "false_positive") if predicted else ("false_negative" if net_return > 0 else "true_negative")
            evaluation[key] += 1
    test_indices = [index for index, day in enumerate(calendar) if validation_date < day <= end_date]
    cash, holdings, fills, curve = 1., {}, [], []
    peak, halted, pending_halt = 1., False, False
    def execution(symbol, index):
        row = series[symbol].get(calendar[index])
        if row is None: raise ValueError(f"missing held/execution price: {symbol} {calendar[index]}")
        if row.get("volume", 1.) <= 0: raise ValueError(f"zero volume is not executable: {symbol} {calendar[index]}")
        return row[cfg["execution_price"]]
    def value(index, field):
        total = 0.
        for symbol, holding in holdings.items():
            row = series[symbol].get(calendar[index])
            if row is None: raise ValueError(f"missing held price: {symbol} {calendar[index]}")
            total += holding["quantity"]*row[field]
        return total
    def sell(symbol, index, quantity, reason):
        nonlocal cash
        price = execution(symbol, index)
        holding = holdings[symbol]
        quantity = min(quantity, holding["quantity"])
        gross = quantity*price
        cost = gross*exit_cost
        cash += gross-cost
        fills.append({"date": calendar[index].isoformat(), "symbol": symbol, "side": "sell", "quantity": quantity,
                      "price": price, "cost": cost, "reason": reason, "signal_date": holding["signal_date"]})
        holding["quantity"] -= quantity
        if holding["quantity"] <= 0: holdings.pop(symbol)
    def buy(symbol, index, target_weight, reason, signal_date):
        nonlocal cash
        if series[symbol].get(calendar[index], {}).get("volume", 1.) <= 0: return
        price = execution(symbol, index)
        held_value = value(index, cfg["execution_price"])
        equity = cash+held_value
        own_value = holdings.get(symbol, {}).get("quantity", 0.)*price
        # Reserve the maximum same-session aggregate fee before sizing an early
        # order, so later buys cannot push that order over its 20% entry cap.
        desired = max(0., target_weight*equity-own_value)/(1+cfg["max_exposure"]*entry_cost)
        capacity = max(0., cfg["max_exposure"]*equity-held_value)/(1+cfg["max_exposure"]*entry_cost)
        gross = min(desired, capacity, cash/(1+entry_cost))
        if gross <= 1e-12: return
        quantity, cost = _number(gross/price, "executed quantity", positive=True), gross*entry_cost
        cash -= gross+cost
        if cash < -1e-10: raise ValueError("cash overspend")
        cash = max(0., cash)
        if symbol not in holdings:
            holdings[symbol] = {"quantity": 0., "expiry": index+cfg["horizon"], "signal_date": signal_date}
        holdings[symbol]["quantity"] += quantity
        fills.append({"date": calendar[index].isoformat(), "symbol": symbol, "side": "buy", "quantity": quantity,
                      "price": price, "cost": cost, "reason": reason, "signal_date": signal_date})
    for index in test_indices:
        day = calendar[index]
        previous_day = calendar[index-1]
        value(index, cfg["execution_price"])
        if pending_halt: halted = True
        last_day = index == test_indices[-1]
        for symbol in list(holdings):
            okay, reason = fundamental_check(symbol, previous_day)
            exit_reason = "drawdown_halt" if halted else "end_of_test" if last_day else "fundamental_"+reason if not okay else "horizon_expiry" if index >= holdings[symbol]["expiry"] else None
            if exit_reason:
                sell(symbol, index, holdings[symbol]["quantity"], exit_reason)
        if not halted and not last_day:
            for symbol in list(holdings):
                prior_vol = observations[symbol].get(index-1)
                high_vol = prior_vol is not None and prior_vol > cfg["volatility_threshold"]
                equity = cash+value(index, cfg["execution_price"])
                price = series[symbol][day][cfg["execution_price"]]
                own = holdings[symbol]["quantity"]*price
                target, high_vix = execution_target(symbol, previous_day, high_vol)
                if cfg["rebalance"] or high_vol or high_vix:
                    excess = own-target*equity
                    if excess > 1e-12:
                        quantity = excess/(price*(1-target*exit_cost))
                        trim_reason = "rebalance" if cfg["rebalance"] else "vix_risk_trim" if high_vix else "volatility_risk_trim"
                        sell(symbol, index, quantity, trim_reason)
                    if cfg["rebalance"] and symbol in holdings:
                        buy(symbol, index, target, "rebalance", holdings[symbol]["signal_date"])
            for symbol in selected_symbols:
                signal = signals[symbol].get(index-1)
                if symbol in holdings or signal is None or not signal["fundamental_ok"]: continue
                okay, _ = fundamental_check(symbol, previous_day)
                if not okay: continue
                target, _ = execution_target(symbol, previous_day,
                    signal["prior_volatility"] > cfg["volatility_threshold"])
                buy(symbol, index, target, "kelly_signal", signal["date"])
        held_value = value(index, "close")
        equity = _number(cash+held_value, "portfolio equity", positive=True)
        current_weights = {symbol: holding["quantity"]*series[symbol][day]["close"]/equity for symbol, holding in holdings.items()}
        peak = max(peak, equity)
        drawdown = 1-equity/peak
        if drawdown >= cfg["drawdown_halt"]: pending_halt = True
        curve.append({"date": day.isoformat(), "equity": equity, "cash": cash, "exposure": held_value/equity,
                      "weights": current_weights, "drawdown": drawdown, "halted": halted,
                      "weight_drift": {symbol: actual-weights[symbol] for symbol, actual in current_weights.items()}})
    portfolio = {"equity_curve": curve, "fills": fills, "metrics": _curve_metrics(curve, fills)}
    benchmark = None
    if benchmark_symbol is not None:
        if benchmark_symbol not in series: raise ValueError("benchmark symbol has no prices")
        for index in test_indices:
            if calendar[index] not in series[benchmark_symbol]: raise ValueError("missing benchmark session price")
        first_index, last_index = test_indices[0], test_indices[-1]
        first_price, last_price = execution(benchmark_symbol, first_index), execution(benchmark_symbol, last_index)
        quantity = 1/(first_price*(1+entry_cost))
        benchmark_fills = [
            {"date": calendar[first_index].isoformat(), "symbol": benchmark_symbol, "side": "buy", "quantity": quantity, "price": first_price, "cost": quantity*first_price*entry_cost, "reason": "benchmark", "signal_date": None},
            {"date": calendar[last_index].isoformat(), "symbol": benchmark_symbol, "side": "sell", "quantity": quantity, "price": last_price, "cost": quantity*last_price*exit_cost, "reason": "end_of_test", "signal_date": None},
        ]
        benchmark_curve = [{"date": calendar[index].isoformat(), "equity": quantity*series[benchmark_symbol][calendar[index]]["close"]} for index in test_indices]
        benchmark_curve[-1]["equity"] = quantity*last_price*(1-exit_cost)
        benchmark = {"symbol": benchmark_symbol, "equity_curve": benchmark_curve, "fills": benchmark_fills,
                     "metrics": _curve_metrics(benchmark_curve, benchmark_fills)}
    latest = []
    for symbol in sorted(signals):
        if len(calendar)-1 in signals[symbol]:
            signal = dict(signals[symbol][len(calendar)-1])
            okay, reason = fundamental_check(symbol, calendar[-1])
            if series[symbol][calendar[-1]].get("volume", 1.) <= 0:
                okay, reason = False, "zero_volume"
            signal["fundamental_ok"], signal["fundamental_reason"] = okay, reason
            signal["as_of"] = calendar[-1].isoformat()
            signal["eligible"] = symbol in selected_symbols and okay
            latest.append(signal)
    warnings = ["Wilson lower bound is a model diagnostic, not a future win guarantee.",
                "Multiple testing and universe survivorship bias are not resolved by this engine.",
                "Fixed-horizon samples use actual next-session execution and completed labels only.",
                "Entry weight/exposure caps apply at execution; fixed-quantity holding drift is reported separately.",
                "False positives/false negatives cover completed signal opportunities in the supplied universe, not missed stocks across the full market; the benchmark is excluded."]
    warnings.extend([
        "Generalized Kelly uses a two-outcome approximation of mean realized net gains and losses, not the full return distribution or target take-profit rates.",
        "Zero net outcomes remain in qualification win rates; the two-point diagnostic conditions its probability on nonzero outcomes.",
        "VIX availability dates are supplied research assumptions; missing VIX is null, not a zero or a normal-market certification.",
        "Fractional Kelly is applied before the position cap; high VIX need not reduce an already capped weight.",
        "All position weights are research calculations; production investment approval remains held.",
    ])
    if cfg["execution_price"] == "close": warnings.append("Close-only execution uses the next calendar session close, not signal-day close.")
    if cfg["rebalance"]: warnings.append("Daily rebalance introduces a calibration mismatch with fixed-horizon qualification samples.")
    if any("volume" not in row for data in series.values() for day, row in data.items() if day <= end_date):
        warnings.append("Missing volume assumes executable sessions; zero supplied volume always prevents fills.")
    report = {"schema_version": 1, "config": cfg,
            "market_volatility": [dict(row) for row in market_rows],
            "splits": {"train_end": train_end, "validation_end": validation_end, "test_start": calendar[test_indices[0]].isoformat(), "test_end": end_date.isoformat(), "qualification_frozen_at": validation_end},
            "qualification": qualifications, "selected_symbols": selected_symbols, "signals": latest,
            "evaluation": evaluation,
            "signal_history": sorted(signal_history, key=lambda row: (row["date"], row["symbol"])),
            "portfolio": portfolio, "benchmark": benchmark, "gambling_formula_example": .2, "warnings": warnings}
    _finite_report(report)
    return report
