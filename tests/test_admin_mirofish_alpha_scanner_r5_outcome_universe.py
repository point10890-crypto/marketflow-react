"""R5 regressions for outcome-memory provenance and scanner universe safety."""

from __future__ import annotations

import copy

import pytest

from app.services.mirofish import alpha_scanner, workflow


MARKET_CUTOFF = "2026-09-03T06:30:00+00:00"
OUTCOME_AVAILABLE_AT = "2026-09-03T07:00:00+00:00"
SCANNER_CEILING = "2026-09-03T07:05:00+00:00"


def _market_artifacts() -> dict:
    """One symbol whose latest authoritative market input is exactly 06:30 UTC."""
    symbol = "005930"
    signal_available_at = "2026-09-03T06:00:00+00:00"
    price = {
        "symbol": symbol,
        "name": "Samsung",
        "date": "2026-09-03",
        "available_at": MARKET_CUTOFF,
        "current_price": 100.0,
        "change_rate": 3.0,
        "open": 98.0,
        "high": 102.0,
        "low": 97.0,
        "volume": 10_000_000,
        "trading_value": 1_000_000_000_000.0,
    }
    return {
        "ticker_map": {
            symbol: {
                "symbol": symbol,
                "market": "KOSPI",
                "display_name": "Samsung",
            },
        },
        "daily_prices": {symbol: price},
        "price_history": {symbol: [price]},
        "screener": {
            "filename": "screener_leading_latest.json",
            "exists": True,
            "generated_at": signal_available_at,
            "mtime": signal_available_at,
            "data": {
                "results": [{
                    "code": symbol,
                    "name": "Samsung",
                    "score": {"total_enriched": 80},
                }],
            },
        },
        "vcp": {
            "filename": "vcp_kr_latest.json",
            "exists": True,
            "generated_at": signal_available_at,
            "mtime": signal_available_at,
            "data": {
                "signals": [{
                    "symbol": symbol,
                    "name": "Samsung",
                    "market": "KOSPI",
                    "composite": {
                        "composite_score": 85,
                        "entry_ready": True,
                    },
                }],
            },
        },
        "jongga": {
            "filename": "jongga_v2_latest.json",
            "exists": True,
            "generated_at": signal_available_at,
            "mtime": signal_available_at,
            "data": {
                "signals": [{
                    "stock_code": symbol,
                    "stock_name": "Samsung",
                    "market": "KOSPI",
                    "score": {"total": 15},
                    "checklist": {},
                }],
            },
        },
        "tradingview": {"signals_by_symbol": {}},
        "institutional_trend": {},
        "kind_blacklist": {"entries": {}},
        "credit_balance": {"entries": {}},
        "rs_ratings": {"entries": {}},
        "kis_live": {},
        "dart_events": {},
        "news_theme_social": {},
        "candidate_symbols": {symbol},
    }


def _applied_outcome_advisory(*, available_at: str = OUTCOME_AVAILABLE_AT) -> dict:
    return {
        "available": True,
        "applied_to_scoring": True,
        "source": "workflow_outcomes",
        "lookahead_safe": True,
        "asof": available_at,
        "evaluated_count": 20,
        "workflow_count_scanned": 24,
        "horizon_days": 5,
        "hit_rate_recent": 0.72,
        "recommendations": {
            "baseline_hit_rate": 0.50,
            "tag_score_adjust": {"leading_screener": 1.25},
        },
    }


def _candidate(
    artifacts: dict,
    *,
    advisory: dict | None = None,
    requested_symbols: set[str] | None = None,
) -> dict:
    candidates = alpha_scanner._build_candidate_pool(
        copy.deepcopy(artifacts),
        generated_at=SCANNER_CEILING,
        requested_symbols=requested_symbols or {"005930"},
        performance_advisory=copy.deepcopy(advisory or {}),
    )
    assert len(candidates) == 1
    return candidates[0]


def _packet(candidate: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(
        workflow.ta_engine,
        "routing_model_ids",
        lambda: {"bulk": "deepseek-v4-pro", "decisive": "gpt-5-mini"},
    )
    return workflow._build_candidate_packet(candidate, use_llm=True)


def test_applied_outcome_memory_closes_cutoff_and_evidence_identity(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, "DATA_ROOT", str(tmp_path))
    artifacts = _market_artifacts()

    baseline = _candidate(artifacts)
    applied = _candidate(artifacts, advisory=_applied_outcome_advisory())
    repeated = _candidate(artifacts, advisory=_applied_outcome_advisory())

    assert baseline["source_cutoff"] == MARKET_CUTOFF
    assert applied["ranking_score"] - baseline["ranking_score"] == pytest.approx(3.45)
    assert applied["source_cutoff"] == OUTCOME_AVAILABLE_AT
    assert applied["replay_context"]["source_cutoff"] == OUTCOME_AVAILABLE_AT
    assert applied["replay_context"]["lookahead_safe"] is True
    assert "workflow_outcomes" in applied["replay_context"]["data_sources"]

    outcome = next(
        source
        for source in applied["source_packets"]
        if source["source"] == "workflow_outcomes"
    )
    assert outcome["observed_at"] == OUTCOME_AVAILABLE_AT
    assert outcome["freshness"] == "fresh"
    assert 0 < outcome["confidence"] <= 1
    assert outcome["evidence_id"] == next(
        source["evidence_id"]
        for source in repeated["source_packets"]
        if source["source"] == "workflow_outcomes"
    )

    normalized = outcome["content"]["normalized"]
    assert normalized["source"] == "workflow_outcomes"
    assert normalized["available_at"] == OUTCOME_AVAILABLE_AT
    assert normalized["as_of"] == OUTCOME_AVAILABLE_AT
    assert normalized["lookahead_safe"] is True
    assert normalized["evaluated_count"] == 20
    assert normalized["workflow_count_scanned"] == 24
    assert normalized["horizon_days"] == 5
    assert normalized["hit_rate_recent"] == pytest.approx(0.72)
    assert normalized["baseline_hit_rate"] == pytest.approx(0.50)
    assert normalized["global_ranking_delta"] == pytest.approx(2.20)
    assert normalized["tag_ranking_delta"] == pytest.approx(1.25)
    assert normalized["total_ranking_delta"] == pytest.approx(3.45)
    assert normalized["matched_tags"] == {"leading_screener": 1.25}

    baseline_packet = _packet(baseline, monkeypatch)
    applied_packet = _packet(applied, monkeypatch)
    repeated_packet = _packet(repeated, monkeypatch)

    assert baseline_packet["as_of"] == MARKET_CUTOFF
    assert applied_packet["as_of"] == OUTCOME_AVAILABLE_AT
    assert applied_packet["fingerprint"] != baseline_packet["fingerprint"]
    assert repeated_packet["fingerprint"] == applied_packet["fingerprint"]
    packet_outcome = next(
        source
        for source in applied_packet["sources"]
        if source["source"] == "workflow_outcomes"
    )
    assert packet_outcome["fetched_at"] == OUTCOME_AVAILABLE_AT
    assert packet_outcome["evidence_id"] == outcome["evidence_id"]
    assert packet_outcome["content"]["normalized"] == normalized
    assert packet_outcome["content_fingerprint"]


def test_future_outcome_advisory_is_score_inert_and_absent_from_packet(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, "DATA_ROOT", str(tmp_path))
    artifacts = _market_artifacts()
    baseline = _candidate(artifacts)
    future = _candidate(
        artifacts,
        advisory=_applied_outcome_advisory(
            available_at="2026-09-03T07:06:00+00:00",
        ),
    )

    assert future["ranking_score"] == baseline["ranking_score"]
    assert future["source_cutoff"] == MARKET_CUTOFF
    assert future["replay_context"]["lookahead_safe"] is True
    assert "workflow_outcomes" not in future["replay_context"]["data_sources"]
    assert all(
        source["source"] != "workflow_outcomes"
        for source in future["source_packets"]
    )
    assert _packet(future, monkeypatch)["fingerprint"] == _packet(
        baseline, monkeypatch,
    )["fingerprint"]


@pytest.mark.parametrize("requested_symbols", [set(), {"005930"}])
def test_future_price_only_universe_omits_empty_provenance_candidate(
    tmp_path, monkeypatch, requested_symbols,
):
    monkeypatch.setattr(alpha_scanner, "DATA_ROOT", str(tmp_path))
    artifacts = _market_artifacts()
    artifacts["screener"]["data"] = {"results": []}
    artifacts["vcp"]["data"] = {"signals": []}
    artifacts["jongga"]["data"] = {"signals": []}
    future_price = {
        **artifacts["daily_prices"]["005930"],
        "available_at": "2026-09-03T07:10:00+00:00",
    }
    artifacts["daily_prices"] = {"005930": future_price}
    artifacts["price_history"] = {"005930": [future_price]}

    candidates = alpha_scanner._build_candidate_pool(
        artifacts,
        generated_at=SCANNER_CEILING,
        requested_symbols=requested_symbols,
        performance_advisory={},
    )

    assert candidates == []
