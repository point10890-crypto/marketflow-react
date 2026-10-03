"""Bounded current-cohort research gates. Pure stdlib; no API or order access.

The supplied listing fixes the cohort before financial or price quality gates.
Current published fundamentals must never be backfilled into historical dates.
"""
from collections import defaultdict
from datetime import date, datetime
import math
from statistics import fmean, pstdev


def _day(value, label):
    if not isinstance(value, str): raise ValueError(f"{label} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value: raise ValueError(f"{label} must use YYYY-MM-DD")
    return parsed


def _text(value, label):
    if not isinstance(value, str) or not value.strip(): raise ValueError(f"{label} is required")
    return value.strip()


def _number(value, label, *, minimum=None, positive=False):
    try:
        finite = math.isfinite(value) if isinstance(value, (int, float)) else False
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite: raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise ValueError(f"{label} is outside the allowed range")
    return value


def _metadata():
    return {"cohort_type": "current_large_cap", "historical_point_in_time": False,
            "win_rate_certified": False, "research_only": True,
            "refill_after_quality": False}


def _listing_rows(rows, as_of):
    if not isinstance(rows, list): raise ValueError("listing rows must be a list")
    result, seen = [], set()
    for raw in rows:
        if not isinstance(raw, dict): raise ValueError("listing rows must be dictionaries")
        row = dict(raw)
        row["symbol"] = _text(raw.get("symbol"), "symbol")
        row["name"] = _text(raw.get("name"), "name")
        if row["symbol"] in seen: raise ValueError(f"duplicate listing symbol: {row['symbol']}")
        seen.add(row["symbol"])
        if _day(raw.get("date"), "listing date") != as_of:
            raise ValueError("every listing row must use the same as_of snapshot date")
        row["market"] = _text(raw.get("market"), "market").upper()
        # The provider exposes the KOSDAQ segment as a separate label. It
        # belongs in the combined KOSPI/KOSDAQ ranking, not an excluded market.
        if row["market"] == "KOSDAQ GLOBAL":
            row["source_market"] = row["market"]
            row["market"] = "KOSDAQ"
        row["source"] = _text(raw.get("source"), "listing source")
        row["market_cap"] = _number(raw.get("market_cap"), "market_cap", positive=True)
        row["volume"] = _number(raw.get("volume"), "volume", minimum=0)
        if raw.get("share_type") not in ("common", "preferred", "fund", "spac", "unknown"):
            raise ValueError("share_type must be an explicit normalized security type")
        result.append(row)
    return result


def select_large_caps(rows: list[dict], as_of: str, top_n: int = 100) -> dict:
    """Rank common KOSPI/KOSDAQ shares once; later gates cannot refill ranks."""
    day = _day(as_of, "as_of")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 100:
        raise ValueError("top_n must be an integer between 1 and 100")
    listing = _listing_rows(rows, day)
    eligible, excluded = [], []
    for row in listing:
        reason = "not_common_stock" if row["share_type"] != "common" else "unsupported_market" if row["market"] not in {"KOSPI", "KOSDAQ"} else None
        if reason: excluded.append(dict(row, reason=reason))
        else: eligible.append(row)
    eligible.sort(key=lambda row: (-row["market_cap"], row["symbol"]))
    ranked = [dict(row, rank=index+1) for index, row in enumerate(eligible[:top_n])]
    metadata = dict(_metadata(), supplied_count=len(listing), common_stock_count=len(eligible), ranked_count=len(ranked))
    return {"as_of": as_of, "top_n": top_n, "ranked": ranked,
            "excluded": sorted(excluded, key=lambda row: row["symbol"]), "metadata": metadata}


def _financial_rows(rows):
    if not isinstance(rows, list): raise ValueError("financials must be a list")
    data, seen = defaultdict(list), set()
    for raw in rows:
        if not isinstance(raw, dict): raise ValueError("financial rows must be dictionaries")
        row = dict(raw)
        symbol = _text(raw.get("symbol"), "financial symbol")
        row["symbol"] = symbol
        for field in ("available_date", "period_end"):
            if raw.get(field) is not None: _day(raw[field], field)
        for field in ("equity", "liabilities", "net_income", "operating_profit"):
            if raw.get(field) is not None: row[field] = _number(raw[field], field)
        if raw.get("fs_div") not in (None, "", "CFS", "OFS"):
            raise ValueError("fs_div must be CFS or OFS")
        if raw.get("source") is not None and not isinstance(raw["source"], str):
            raise ValueError("financial source must be text")
        if raw.get("fetched_at") is not None:
            if not isinstance(raw["fetched_at"], str): raise ValueError("fetched_at must be an ISO timestamp")
            stamp = raw["fetched_at"].strip()
            row["fetched_at"] = stamp or None
        else:
            stamp = None
        if stamp:
            try: datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError as exc: raise ValueError("fetched_at must be an ISO timestamp") from exc
        key = (symbol, raw.get("available_date"), raw.get("period_end"), raw.get("fs_div"))
        if key in seen: raise ValueError(f"duplicate financial record: {symbol}")
        seen.add(key)
        data[symbol].append(row)
    return data


def evaluate_quality(ranked: list[dict], financials: list[dict], as_of: str,
                     max_age_days: int = 180, max_debt_ratio: float = 150.) -> dict:
    """Check current publication evidence; use one entire latest financial record."""
    day = _day(as_of, "as_of")
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 0:
        raise ValueError("max_age_days must be a nonnegative integer")
    debt_limit = _number(max_debt_ratio, "max_debt_ratio", minimum=0)
    listings = _listing_rows(ranked, day)
    if len(listings) > 100: raise ValueError("quality cohort cannot exceed 100 stocks")
    data = _financial_rows(financials)
    results = []
    for listing in listings:
        known = [row for row in data.get(listing["symbol"], [])
                 if row.get("available_date") is not None and _day(row["available_date"], "available_date") <= day]
        # CFS is preferred only when publication date and reporting period tie.
        known.sort(key=lambda row: (row["available_date"], row.get("period_end") or "", row.get("fs_div") == "CFS"))
        record = known[-1] if known else None
        reason, debt_ratio = None, None
        if listing["share_type"] != "common": reason = "not_common_stock"
        elif listing["market"] not in {"KOSPI", "KOSDAQ"}: reason = "unsupported_market"
        elif listing["volume"] <= 0: reason = "zero_volume"
        elif record is None: reason = "missing_financials"
        elif not record.get("source") or not record["source"].strip(): reason = "missing_financial_source"
        elif not record.get("fs_div"): reason = "missing_financial_fs_div"
        elif not record.get("fetched_at"): reason = "missing_financial_fetched_at"
        elif not record.get("period_end"): reason = "missing_financial_period_end"
        elif _day(record["period_end"], "period_end") > day: reason = "future_financial_period"
        elif record["period_end"] > record["available_date"]: reason = "financial_period_after_publication"
        elif (day-_day(record["available_date"], "available_date")).days > max_age_days: reason = "stale_financials"
        else:
            for field in ("equity", "liabilities", "net_income", "operating_profit"):
                if record.get(field) is None:
                    reason = "missing_financial_"+field
                    break
            if reason is None:
                if record["equity"] <= 0: reason = "nonpositive_equity"
                elif record["net_income"] <= 0: reason = "nonpositive_net_income"
                elif record["operating_profit"] <= 0: reason = "nonpositive_operating_profit"
                elif record["liabilities"] < 0: reason = "negative_liabilities"
                else:
                    debt_ratio = _number(record["liabilities"]/record["equity"]*100, "debt ratio")
                    if debt_ratio > debt_limit: reason = "high_debt_ratio"
        results.append(dict(listing, quality_pass=reason is None, reason=reason or "quality_passed",
                            debt_ratio=debt_ratio, financial=record))
    return {"as_of": as_of, "passed": [row for row in results if row["quality_pass"]],
            "held": [row for row in results if not row["quality_pass"]], "results": results,
            "metadata": dict(_metadata(), max_age_days=max_age_days, max_debt_ratio=debt_limit,
                             fundamentals_basis="latest available current filing; no historical backfill")}


def current_technical(prices: list[dict], symbols: list, as_of: str,
                      lookback: int = 60, z_threshold: float = -2.) -> dict:
    """Current return surprise against previous returns only; not a BUY verdict."""
    day = _day(as_of, "as_of")
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
        raise ValueError("lookback must be an integer of at least two")
    threshold = _number(z_threshold, "z_threshold")
    if threshold >= 0: raise ValueError("z_threshold must be negative")
    if not isinstance(prices, list) or not isinstance(symbols, list):
        raise ValueError("prices and symbols must be lists")
    cohort, names = [], {}
    for item in symbols:
        symbol = _text(item.get("symbol") if isinstance(item, dict) else item, "cohort symbol")
        if symbol in cohort: raise ValueError(f"duplicate cohort symbol: {symbol}")
        cohort.append(symbol)
        if isinstance(item, dict) and item.get("name") is not None:
            names[symbol] = _text(item["name"], "cohort name")
    if len(cohort) > 100: raise ValueError("technical cohort cannot exceed 100 stocks")
    data, calendar_set, seen = defaultdict(dict), set(), set()
    for raw in prices:
        if not isinstance(raw, dict): raise ValueError("price rows must be dictionaries")
        symbol = _text(raw.get("symbol"), "price symbol")
        price_day = _day(raw.get("date"), "price date")
        key = (symbol, price_day)
        if key in seen: raise ValueError(f"duplicate price: {symbol} {price_day}")
        seen.add(key)
        close = _number(raw.get("close"), "close", positive=True)
        if price_day > day: continue
        data[symbol][price_day] = close
        calendar_set.add(price_day)
        if symbol in cohort and symbol not in names:
            names[symbol] = str(raw.get("name") or symbol)
    calendar = sorted(calendar_set)
    results = []
    for symbol in cohort:
        row = {"symbol": symbol, "name": names.get(symbol, symbol), "as_of": as_of,
               "candidate": False, "z_score": None, "last_daily_return": None,
               "prior_mean_return": None, "prior_volatility": None}
        if day not in data[symbol]: row["reason"] = "missing_current_price"
        elif len(calendar) < lookback+2: row["reason"] = "insufficient_history"
        else:
            window = calendar[-lookback-2:]
            if any(session not in data[symbol] for session in window): row["reason"] = "missing_lookback_price"
            else:
                values = [data[symbol][session] for session in window]
                returns = [_number(current/previous-1, "daily return") for previous, current in zip(values, values[1:])]
                baseline = returns[:-1]
                mean, sigma = _number(fmean(baseline), "prior mean return"), _number(pstdev(baseline), "prior volatility")
                row.update(last_daily_return=returns[-1], prior_mean_return=mean, prior_volatility=sigma)
                if sigma <= 1e-12: row["reason"] = "zero_historical_volatility"
                else:
                    z_score = _number((returns[-1]-mean)/sigma, "z score")
                    row.update(z_score=z_score, candidate=z_score <= threshold,
                               reason="current_2sigma_candidate" if z_score <= threshold else "no_current_signal")
        results.append(row)
    return {"as_of": as_of, "results": results, "candidates": [row for row in results if row["candidate"]],
            "metadata": dict(_metadata(), lookback=lookback, z_threshold=threshold,
                             signal_basis="current price-only; previous lookback returns exclude current return",
                             interpretation="2-sigma research candidate; not certified 60% win probability or a BUY recommendation")}
