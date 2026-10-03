"""Current-cohort selection and evidence gates; no network or app imports."""
import copy
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest


AS_OF = "2026-10-01"


def module():
    path = Path(__file__).resolve().parents[1] / "app/services/mirofish/large_cap_universe.py"
    assert path.exists(), "Current large-cap cohort support has not been implemented"
    spec = importlib.util.spec_from_file_location("large_cap_universe_test", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def listing(count=1):
    return [{"symbol": f"{index + 1:06d}", "name": f"Stock {index + 1}", "market": "KOSPI",
             "market_cap": (count-index)*1e12, "volume": 1000., "share_type": "common",
             "source": "https://example.test/listing.csv", "date": AS_OF} for index in range(count)]


def financial(symbol="000001", **changes):
    return dict({"symbol": symbol, "available_date": "2026-08-15", "equity": 100e9,
                 "liabilities": 100e9, "net_income": 5e9, "operating_profit": 8e9,
                 "fs_div": "CFS", "source": "https://example.test/filing/123",
                 "period_end": "2026-06-30", "fetched_at": "2026-10-03T01:00:00Z"}, **changes)


def prices():
    days = [(date(2026, 7, 30)+timedelta(days=i)).isoformat() for i in range(64)]
    rows, close = [], 100.
    rows.append({"symbol": "000001", "name": "Stock 1", "date": days[0], "close": close})
    for i, day in enumerate(days[1:], 1):
        close *= 1+(-.05 if i == 63 else [.008, .01, .012][i % 3])
        rows.append({"symbol": "000001", "name": "Stock 1", "date": day, "close": close})
    assert days[-1] == AS_OF
    return rows


def test_selects_exact_top100_without_refilling_failed_quality_candidates():
    rows = listing(101)
    rows[0]["volume"] = 0
    selected = module().select_large_caps(rows, AS_OF)
    assert len(selected["ranked"]) == 100
    assert selected["ranked"][-1]["symbol"] == "000100"
    gate = module().evaluate_quality(selected["ranked"], [financial(row["symbol"]) for row in rows], AS_OF)
    assert len(gate["passed"]) == 99
    assert "000101" not in {row["symbol"] for row in gate["passed"]}
    assert gate["held"][0]["reason"] == "zero_volume"


def test_cap_ties_break_by_symbol_independent_of_input_order():
    rows = listing(3)
    for row in rows: row["market_cap"] = 1e12
    selected = module().select_large_caps(list(reversed(rows)), AS_OF, top_n=2)
    assert [row["symbol"] for row in selected["ranked"]] == ["000001", "000002"]


def test_kosdaq_global_is_ranked_as_kosdaq_and_keeps_source_market():
    rows = listing(3)
    rows[0]["market"] = "KOSDAQ GLOBAL"
    rows[1]["market"] = "KONEX"
    before = copy.deepcopy(rows)
    selected = module().select_large_caps(rows, AS_OF, top_n=1)
    assert selected["ranked"][0]["symbol"] == "000001"
    assert selected["ranked"][0]["market"] == "KOSDAQ"
    assert selected["ranked"][0]["source_market"] == "KOSDAQ GLOBAL"
    assert selected["excluded"][0]["symbol"] == "000002"
    assert selected["excluded"][0]["reason"] == "unsupported_market"
    assert rows == before


@pytest.mark.parametrize("share_type", ["preferred", "fund", "spac", "unknown"])
def test_non_common_security_types_are_excluded_before_cap_ranking(share_type):
    rows = listing(2)
    rows[0]["share_type"] = share_type
    report = module().select_large_caps(rows, AS_OF)
    assert [row["symbol"] for row in report["ranked"]] == ["000002"]
    assert report["excluded"][0]["reason"] == "not_common_stock"


@pytest.mark.parametrize("change", [{"date": "2026-09-30"}, {"market_cap": float("nan")},
                                    {"market_cap": 0}, {"volume": -1}, {"source": ""}])
def test_malformed_or_mixed_snapshot_listing_is_rejected(change):
    rows = listing()
    rows[0].update(change)
    with pytest.raises(ValueError): module().select_large_caps(rows, AS_OF)


def test_duplicate_symbol_and_unbounded_top_n_are_rejected():
    row = listing()[0]
    with pytest.raises(ValueError, match="duplicate"): module().select_large_caps([row, dict(row)], AS_OF)
    with pytest.raises(ValueError): module().select_large_caps([row], AS_OF, top_n=101)


def test_missing_financials_are_held_and_never_assumed_profitable():
    gate = module().evaluate_quality(listing(), [], AS_OF)
    assert gate["passed"] == []
    assert gate["held"][0]["reason"] == "missing_financials"


@pytest.mark.parametrize("change,reason", [
    ({"available_date": "2025-01-01", "period_end": "2024-12-31"}, "stale_financials"),
    ({"source": ""}, "missing_financial_source"),
    ({"fs_div": None}, "missing_financial_fs_div"),
    ({"fetched_at": None}, "missing_financial_fetched_at"),
    ({"equity": -1}, "nonpositive_equity"),
    ({"net_income": -1}, "nonpositive_net_income"),
    ({"operating_profit": 0}, "nonpositive_operating_profit"),
    ({"liabilities": -1}, "negative_liabilities"),
    ({"liabilities": 151e9}, "high_debt_ratio"),
    ({"period_end": "2026-12-31"}, "future_financial_period"),
])
def test_missing_provenance_or_legitimate_bad_financials_block_quality(change, reason):
    gate = module().evaluate_quality(listing(), [financial(**change)], AS_OF)
    assert gate["passed"] == []
    assert gate["held"][0]["reason"] == reason


def test_malformed_financial_numbers_are_errors_instead_of_negative_business_results():
    with pytest.raises(ValueError, match="finite"):
        module().evaluate_quality(listing(), [financial(net_income=float("inf"))], AS_OF)


def test_future_filing_cannot_replace_the_latest_available_current_record():
    current, future = financial(), financial(available_date="2026-10-02", net_income=-1)
    gate = module().evaluate_quality(listing(), [future, current], AS_OF)
    assert gate["passed"][0]["financial"]["available_date"] == current["available_date"]
    assert gate["passed"][0]["debt_ratio"] == pytest.approx(100.)
    missing = module().evaluate_quality(listing(), [future], AS_OF)
    assert missing["held"][0]["reason"] == "missing_financials"


def test_latest_available_bad_record_is_not_replaced_by_older_good_results():
    records = [financial(), financial(available_date="2026-09-01", net_income=-1)]
    gate = module().evaluate_quality(listing(), records, AS_OF)
    assert gate["held"][0]["reason"] == "nonpositive_net_income"


def test_current_z_uses_previous_sixty_returns_and_excludes_current_return():
    rows = prices()
    report = module().current_technical(rows, listing(), AS_OF)
    current = report["results"][0]
    expected_sigma = ((.008-.01)**2*20 + (.012-.01)**2*20)/60
    assert current["z_score"] == pytest.approx((-.05-.01)/expected_sigma**.5)
    assert current["candidate"]
    assert current["last_daily_return"] == pytest.approx(-.05)
    assert current["name"] == "Stock 1"
    assert report["metadata"]["historical_point_in_time"] is False
    assert report["metadata"]["win_rate_certified"] is False
    json.dumps(report, allow_nan=False)


def test_technical_never_expands_the_supplied_cohort_or_uses_future_prices():
    rows = prices()
    extras = [dict(row, symbol="OTHER") for row in rows]
    future = dict(rows[-1], date="2026-10-02", close=1)
    baseline = module().current_technical(rows, ["000001"], AS_OF)
    modified = module().current_technical(rows + extras + [future], ["000001"], AS_OF)
    assert baseline == modified
    assert [row["symbol"] for row in modified["results"]] == ["000001"]


def test_latest_missing_price_is_held_instead_of_rolling_back_to_an_older_signal():
    rows = prices()
    rows[-1]["symbol"] = "OTHER"
    report = module().current_technical(rows, ["000001"], AS_OF)
    assert not report["results"][0]["candidate"]
    assert report["results"][0]["reason"] == "missing_current_price"


def test_missing_calendar_window_price_prevents_a_multiday_return_signal():
    rows = prices()
    extra = dict(rows[10], symbol="OTHER")
    rows.pop(10)
    report = module().current_technical(rows + [extra], ["000001"], AS_OF)
    assert report["results"][0]["reason"] == "missing_lookback_price"


def test_zero_sigma_and_short_history_are_held():
    rows = prices()
    for row in rows: row["close"] = 100.
    assert module().current_technical(rows, ["000001"], AS_OF)["results"][0]["reason"] == "zero_historical_volatility"
    assert module().current_technical(rows[-20:], ["000001"], AS_OF)["results"][0]["reason"] == "insufficient_history"


def test_inputs_are_not_mutated_by_the_pipeline():
    rows, fundamentals, closes = listing(), [financial()], prices()
    original = copy.deepcopy((rows, fundamentals, closes))
    ranked = module().select_large_caps(rows, AS_OF)["ranked"]
    module().evaluate_quality(ranked, fundamentals, AS_OF)
    module().current_technical(closes, ranked, AS_OF)
    assert (rows, fundamentals, closes) == original


def test_financial_freshness_and_debt_limit_are_inclusive_at_the_boundary():
    available = (date.fromisoformat(AS_OF)-timedelta(days=180)).isoformat()
    period = (date.fromisoformat(available)-timedelta(days=30)).isoformat()
    record = financial(available_date=available, period_end=period, liabilities=150e9)
    assert module().evaluate_quality(listing(), [record], AS_OF)["passed"]
    record["available_date"] = (date.fromisoformat(available)-timedelta(days=1)).isoformat()
    assert module().evaluate_quality(listing(), [record], AS_OF)["held"][0]["reason"] == "stale_financials"


def test_cfs_and_ofs_are_never_merged_to_manufacture_a_passing_record():
    cfs = financial(net_income=-1)
    ofs = financial(fs_div="OFS", operating_profit=-1)
    gate = module().evaluate_quality(listing(), [ofs, cfs], AS_OF)
    assert gate["held"][0]["financial"]["fs_div"] == "CFS"
    assert gate["held"][0]["reason"] == "nonpositive_net_income"


def test_blank_fetch_timestamp_is_missing_evidence_while_malformed_is_an_error():
    gate = module().evaluate_quality(listing(), [financial(fetched_at="")], AS_OF)
    assert gate["held"][0]["reason"] == "missing_financial_fetched_at"
    with pytest.raises(ValueError, match="timestamp"):
        module().evaluate_quality(listing(), [financial(fetched_at="not-a-time")], AS_OF)


def test_financial_period_after_publication_cannot_be_current_evidence():
    record = financial(available_date="2026-06-01", period_end="2026-06-30")
    gate = module().evaluate_quality(listing(), [record], AS_OF)
    assert not gate["passed"]
    assert gate["held"][0]["reason"] == "financial_period_after_publication"


@pytest.mark.parametrize("mutation", ["duplicate_price", "duplicate_cohort", "nan", "overflow"])
def test_technical_rejects_malformed_or_ambiguous_prices(mutation):
    rows, cohort = prices(), ["000001"]
    if mutation == "duplicate_price": rows.append(dict(rows[-1]))
    elif mutation == "duplicate_cohort": cohort.append("000001")
    elif mutation == "nan": rows[-1]["close"] = float("nan")
    else:
        rows[-2]["close"] = 1e-308
        rows[-1]["close"] = 1e308
    with pytest.raises(ValueError): module().current_technical(rows, cohort, AS_OF)


def test_malformed_security_or_statement_types_have_clear_validation_errors():
    rows = listing()
    rows[0]["share_type"] = []
    with pytest.raises(ValueError, match="share_type"):
        module().select_large_caps(rows, AS_OF)
    with pytest.raises(ValueError, match="fs_div"):
        module().evaluate_quality(listing(), [financial(fs_div=[])], AS_OF)
