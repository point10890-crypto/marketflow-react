from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.ai_routing.contracts import Operation, ProviderAttempt, TokenUsage
from app.services.ai_routing.store import RoutingStore
from app.services.ai_routing.telemetry import record_attempt
from app.services.mirofish import evidence_packet


UTC = timezone.utc


def _packet() -> dict:
    return evidence_packet.build_evidence_packet(
        {
            "symbol": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "as_of": "2026-09-02T06:30:00+00:00",
            "price": {
                "current_price": 71_000,
                "change_pct": 1.25,
                "volume": 12_345_678,
                "date": "2026-09-02T06:30:00+00:00",
            },
            "alpha_score": 82.5,
            "risk_score": 21.0,
            "source_packets": [
                {
                    "evidence_id": "price-005930",
                    "source": "kis",
                    "source_type": "price",
                    "fetched_at": "2026-09-02T06:29:00+00:00",
                    "content": {"current_price": 71_000, "volume": 12_345_678},
                },
                {
                    "evidence_id": "dart-005930",
                    "source": "opendart",
                    "source_type": "filing",
                    "fetched_at": "2026-09-02T06:00:00+00:00",
                    "content": {"text": "quarterly filing"},
                },
            ],
        },
        models={},
        execution_inputs={"use_llm": True, "brain": {"regime": "bull"}},
    )


def _result(packet: dict, profile: str, *, verdict: str = "BUY", calls: int = 0) -> dict:
    run_id = f"routing-{profile}"
    return {
        "id": f"artifact-{profile}",
        "target": packet["name"],
        "symbol": packet["symbol"],
        "market": packet["market"],
        "profile": profile,
        "routing_run_id": run_id,
        "evidence_fingerprint": packet["fingerprint"],
        "evidence_packet": copy.deepcopy(packet),
        "analysis_status": "SUCCESS_PRIMARY",
        "provider_usage": {
            "calls": calls,
            "attempts": calls,
            "successes": calls,
            "failures": 0,
            "fallbacks": 0,
            "providers": {},
        },
        "verdict": {"verdict": verdict, "confidence": 74},
        "force": profile == "compact",
        "raw_prompt": "never-copy-this-prompt",
        "raw_error": "Authorization: Bearer never-copy-this-secret",
    }


def _healthy_snapshot(packet: dict) -> dict:
    return {
        "schema_version": "ai-routing-health-v1",
        "checked_at": "2026-09-02T06:29:30+00:00",
        "ttl_seconds": 300,
        "providers": [
            {
                "provider": "deepseek",
                "operation": "decisive_text",
                "configured": True,
                "available": True,
                "model": "deepseek-v4-pro",
                "status": "healthy",
                "checked_at": "2026-09-02T06:29:30+00:00",
                "ttl_seconds": 300,
            },
            {
                "provider": "openai",
                "operation": "decisive_text",
                "configured": True,
                "available": True,
                "model": "gpt-5.5",
                "status": "healthy",
                "checked_at": "2026-09-02T06:29:30+00:00",
                "ttl_seconds": 300,
            },
        ],
    }


def _attempt(
    *, run_id: str, request_id: str, attempt_number: int, usage: TokenUsage
) -> ProviderAttempt:
    return ProviderAttempt(
        request_id=request_id,
        run_id=run_id,
        provider="deepseek",
        model="deepseek-v4-pro",
        endpoint="chat.completions",
        operation=Operation.DECISIVE_TEXT,
        attempt_number=attempt_number,
        selected=True,
        status="success",
        latency_ms=12,
        max_output_tokens=1200,
        usage=usage,
        caller_endpoint="scripts.compare_tradingagents_profiles",
    )


def test_offline_comparison_uses_only_saved_results_and_keeps_unknown_tokens_null():
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()
    called = []

    report = comparison.compare_profiles(
        packet,
        full_result=_result(packet, "full"),
        compact_result=_result(packet, "compact"),
        live=False,
        runner=lambda **kwargs: called.append(kwargs),
    )

    assert called == []
    assert report["live"] is False and report["blocked"] is False
    assert report["packet_id"] == packet["fingerprint"]
    assert report["symbol"] == "005930"
    assert report["as_of"] == packet["as_of"]
    assert report["profiles"]["full"]["call_count"] == 0
    assert report["profiles"]["full"]["input_tokens"] is None
    assert report["profiles"]["full"]["output_tokens"] is None
    assert report["profiles"]["full"]["total_tokens"] is None
    assert report["profiles"]["full"]["schema_success"] is True
    assert report["verdict_disagreement"] is False
    serialized = json.dumps(report, ensure_ascii=False)
    assert "never-copy-this-prompt" not in serialized
    assert "never-copy-this-secret" not in serialized


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda packet: packet.update({"symbol": "000000"}), "packet_fingerprint_mismatch"),
        (
            lambda packet: packet["sources"][0].update(
                {"content": {"current_price": 999_999}}
            ),
            "source_fingerprint_mismatch",
        ),
        (
            lambda packet: packet["sources"][0].update(
                {"fetched_at": "2026-09-02T07:00:00+00:00"}
            ),
            "source_after_as_of",
        ),
    ],
)
def test_invalid_packet_fails_closed_before_any_runner(mutate, code):
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()
    mutate(packet)
    called = []

    with pytest.raises(comparison.ReplayValidationError, match=f"^{code}$"):
        comparison.compare_profiles(
            packet,
            live=True,
            runner=lambda **kwargs: called.append(kwargs),
            health_snapshot=_healthy_snapshot(packet),
            now=datetime(2026, 9, 2, 6, 30, tzinfo=UTC),
        )

    assert called == []


def test_ledger_tokens_are_reported_and_partial_usage_stays_unknown(tmp_path):
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()
    store = RoutingStore(tmp_path / "usage.sqlite3")
    record_attempt(
        _attempt(
            run_id="routing-full",
            request_id="full-1",
            attempt_number=1,
            usage=TokenUsage(input_tokens=100, output_tokens=20),
        ),
        store=store,
    )
    record_attempt(
        _attempt(
            run_id="routing-compact",
            request_id="compact-1",
            attempt_number=1,
            usage=TokenUsage(input_tokens=40, output_tokens=10),
        ),
        store=store,
    )
    record_attempt(
        _attempt(
            run_id="routing-compact",
            request_id="compact-2",
            attempt_number=1,
            usage=TokenUsage.unknown(),
        ),
        store=store,
    )

    report = comparison.compare_profiles(
        packet,
        full_result=_result(packet, "full", calls=1),
        compact_result=_result(packet, "compact", calls=2),
        store=store,
    )

    full = report["profiles"]["full"]
    compact = report["profiles"]["compact"]
    assert (full["input_tokens"], full["output_tokens"], full["total_tokens"]) == (100, 20, 120)
    assert full["usage_completeness"] == 1.0
    assert compact["ledger_live_attempts"] == 2
    assert compact["input_tokens"] is None
    assert compact["output_tokens"] is None
    assert compact["total_tokens"] is None
    assert compact["known_total_tokens"] == 50
    assert compact["unknown_usage_attempts"] == 1
    assert compact["usage_completeness"] == 0.5


def test_comparison_reports_verdict_numeric_source_schema_identity_and_hidden_failures():
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()
    full = _result(packet, "full", verdict="BUY", calls=1)
    compact = _result(packet, "compact", verdict="SELL")
    compact["symbol"] = "000000"
    compact["verdict"]["current_price"] = 72_000
    compact["verdict"]["evidence_ids"] = ["fabricated-evidence"]
    compact.pop("analysis_status")

    report = comparison.compare_profiles(
        packet,
        full_result=full,
        compact_result=compact,
    )

    assert report["verdict_disagreement"] is True
    assert any(item["code"] == "numeric_mismatch" for item in report["numeric_violations"])
    assert any(item["code"] == "unknown_evidence_id" for item in report["source_violations"])
    assert any(item["code"] == "symbol_mismatch" for item in report["identity_violations"])
    assert any(item["code"] == "analysis_status_missing" for item in report["hidden_failures"])
    assert report["profiles"]["compact"]["schema_success"] is False


def test_live_comparison_is_blocked_when_only_openai_is_healthy(monkeypatch):
    from scripts import compare_tradingagents_profiles as comparison

    monkeypatch.setenv("AI_DEEPSEEK_DECISIVE_MODEL", "deepseek-v4-pro")
    packet = _packet()
    snapshot = _healthy_snapshot(packet)
    snapshot["providers"][0].update({"available": False, "status": "authentication"})
    called = []

    report = comparison.compare_profiles(
        packet,
        live=True,
        runner=lambda **kwargs: called.append(kwargs),
        health_snapshot=snapshot,
        now=datetime(2026, 9, 2, 6, 30, tzinfo=UTC),
    )

    assert called == []
    assert report["blocked"] is True
    assert report["blocked_reason"] == "deepseek_decisive_health_unavailable"
    assert report["profiles"]["full"]["call_count"] is None


def test_explicit_malformed_health_never_falls_back_to_another_snapshot(monkeypatch):
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()
    monkeypatch.setattr(
        comparison,
        "_safe_health_snapshot",
        lambda _path: pytest.fail("explicit health must not fall back"),
    )

    report = comparison.compare_profiles(
        packet,
        live=True,
        runner=lambda **_kwargs: pytest.fail("blocked health must not run"),
        health_snapshot={},
        now=datetime(2026, 9, 2, 6, 30, tzinfo=UTC),
    )

    assert report["blocked_reason"] == "deepseek_decisive_health_unavailable"


def test_non_finite_canonical_numeric_input_is_rejected_before_runner():
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()
    packet["numeric_inputs"]["current_price"] = float("nan")
    packet["fingerprint"] = evidence_packet._sha({  # canonical producer contract
        key: value for key, value in packet.items() if key != "fingerprint"
    })

    with pytest.raises(comparison.ReplayValidationError, match="^packet_numeric_non_finite$"):
        comparison.compare_profiles(
            packet,
            full_result=_result(packet, "full"),
            compact_result=_result(packet, "compact"),
        )


def test_live_comparison_passes_identical_frozen_inputs_to_isolated_profiles(monkeypatch, tmp_path):
    from scripts import compare_tradingagents_profiles as comparison

    monkeypatch.setenv("AI_DEEPSEEK_DECISIVE_MODEL", "deepseek-v4-pro")
    packet = _packet()
    calls = []

    def runner(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return _result(kwargs["packet"], kwargs["profile"])

    report = comparison.compare_profiles(
        packet,
        live=True,
        runner=runner,
        health_snapshot=_healthy_snapshot(packet),
        artifact_root=tmp_path / "comparison",
        now=datetime(2026, 9, 2, 6, 30, tzinfo=UTC),
    )

    assert report["blocked"] is False
    assert [item["profile"] for item in calls] == ["full", "compact"]
    assert calls[0]["packet"] == calls[1]["packet"] == packet
    assert calls[0]["frozen_bundle"] == calls[1]["frozen_bundle"]
    assert calls[0]["artifact_root"] != calls[1]["artifact_root"]
    assert calls[0]["force"] is False
    assert calls[1]["force"] is True


def test_runner_mutation_of_canonical_packet_fails_closed(tmp_path):
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()

    def mutating_runner(**kwargs):
        kwargs["packet"]["symbol"] = "000000"
        return _result(packet, kwargs["profile"])

    with pytest.raises(comparison.ReplayValidationError, match="^runner_mutated_packet$"):
        comparison.compare_profiles(
            packet,
            live=True,
            runner=mutating_runner,
            health_snapshot=_healthy_snapshot(packet),
            artifact_root=tmp_path,
            now=datetime(2026, 9, 2, 6, 30, tzinfo=UTC),
        )


def test_default_engine_runner_injects_frozen_bundle_and_restores_globals(monkeypatch, tmp_path):
    from scripts import compare_tradingagents_profiles as comparison
    from app.services.mirofish.tradingagents import data_hub, engine

    packet = _packet()
    original_gather = data_hub.gather_bundle
    original_root = engine.RUNS_ROOT
    seen = {}

    def fake_engine(target, **kwargs):
        seen["bundle"] = data_hub.gather_bundle(target)
        seen["root"] = engine.RUNS_ROOT
        seen["kwargs"] = kwargs
        return _result(kwargs["evidence_packet"], kwargs["profile"])

    monkeypatch.setattr(engine, "run_deep_analysis", fake_engine)
    frozen = data_hub.bundle_from_evidence_packet(packet, brain={"regime": "bull"})
    output = comparison.run_engine_profile(
        profile="compact",
        packet=copy.deepcopy(packet),
        frozen_bundle=copy.deepcopy(frozen),
        artifact_root=tmp_path / "compact",
        force=True,
    )

    assert output["profile"] == "compact"
    assert seen["bundle"] == frozen
    assert seen["root"] == str(tmp_path / "compact")
    assert seen["kwargs"]["force"] is True
    assert data_hub.gather_bundle is original_gather
    assert engine.RUNS_ROOT == original_root


def test_cli_offline_reads_only_explicit_files_and_writes_sanitized_report(tmp_path):
    from scripts import compare_tradingagents_profiles as comparison

    packet = _packet()
    packet_path = tmp_path / "packet.json"
    full_path = tmp_path / "full.json"
    compact_path = tmp_path / "compact.json"
    output_path = tmp_path / "report.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    full_path.write_text(json.dumps(_result(packet, "full")), encoding="utf-8")
    compact_path.write_text(json.dumps(_result(packet, "compact")), encoding="utf-8")

    assert comparison.main([
        str(packet_path),
        "--full-result", str(full_path),
        "--compact-result", str(compact_path),
        "--output", str(output_path),
    ]) == 0

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["live"] is False
    assert "never-copy-this-secret" not in output_path.read_text(encoding="utf-8")
