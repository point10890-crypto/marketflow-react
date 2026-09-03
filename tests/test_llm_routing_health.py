from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.ai_routing.contracts import Operation
from app.services.ai_routing.policy import policy_for, vision_attestation_is_valid
from app.services.ai_routing.providers import AdapterResponse
from app.services.ai_routing.reporting import (
    HEALTH_SCHEMA_VERSION,
    get_llm_routing_status,
)
from app.services.ai_routing.store import RoutingStore
from scripts import llm_routing_health as health


_NOW = datetime(2026, 9, 3, 4, 5, 6, tzinfo=timezone.utc)
_PROVIDER_FIELDS = {
    "provider",
    "operation",
    "configured",
    "available",
    "model",
    "status",
    "checked_at",
    "ttl_seconds",
}
_ENV_NAMES = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_BASE_URL",
    "AI_DEEPSEEK_DECISIVE_MODEL",
    "AI_OPENAI_FALLBACK_MODEL",
    "AI_GEMINI_VISION_MODEL",
    "AI_DEEPSEEK_VISION_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_provider_environment(monkeypatch):
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class _Adapter:
    endpoint = "https://credential:must-not-leak@example.test/private"
    request_timeout_seconds = 1.0

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def generate(self, request, *, model, max_output_tokens):
        self.calls.append((request, model, max_output_tokens))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _HttpFailure(RuntimeError):
    def __init__(self, status_code: int, raw_message: str):
        self.status_code = status_code
        super().__init__(raw_message)


def _record(report, provider, operation):
    return next(
        item
        for item in report["providers"]
        if item["provider"] == provider and item["operation"] == operation
    )


def test_offline_default_does_not_build_or_call_adapters_or_overwrite_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-deepseek-credential")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai-credential")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-gemini-credential")
    monkeypatch.setenv(
        "DEEPSEEK_BASE_URL",
        "https://operator:fixture-password@private.example/v1?key=fixture-query",
    )
    snapshot_path = tmp_path / "health.json"
    original = b'{"persisted":"must-survive-offline"}\n'
    snapshot_path.write_bytes(original)

    def forbidden_build():
        raise AssertionError("offline mode constructed provider adapters")

    monkeypatch.setattr(health, "build_default_adapters", forbidden_build)

    report = health.run_health_check(snapshot_path=snapshot_path, now=_NOW)

    assert snapshot_path.read_bytes() == original
    assert report["schema_version"] == HEALTH_SCHEMA_VERSION
    assert report["mode"] == "offline"
    assert report["cost_saving_activation"] == {
        "ready": False,
        "status": "blocked",
        "reason": "live_probe_required",
    }
    assert len(report["providers"]) == 3
    assert all(set(item) == _PROVIDER_FIELDS for item in report["providers"])
    serialized = json.dumps(report, sort_keys=True)
    assert "fixture-deepseek-credential" not in serialized
    assert "fixture-openai-credential" not in serialized
    assert "fixture-gemini-credential" not in serialized
    assert "fixture-password" not in serialized
    assert "fixture-query" not in serialized


def test_live_calls_each_configured_vendor_once_records_once_and_writes_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    monkeypatch.setenv("OPENAI_API_KEY", "configured")
    monkeypatch.setenv("GEMINI_API_KEY", "configured")
    adapters = {
        provider: _Adapter(AdapterResponse(text="healthy"))
        for provider in ("deepseek", "openai", "gemini")
    }
    attempts = []
    snapshot_path = tmp_path / "health.json"

    report = health.run_health_check(
        live=True,
        adapters=adapters,
        attempt_recorder=attempts.append,
        snapshot_path=snapshot_path,
        now=_NOW,
    )

    assert {provider: len(adapter.calls) for provider, adapter in adapters.items()} == {
        "deepseek": 1,
        "openai": 1,
        "gemini": 1,
    }
    assert adapters["deepseek"].calls[0][0].operation is Operation.DECISIVE_TEXT
    assert adapters["openai"].calls[0][0].operation is Operation.DECISIVE_TEXT
    assert adapters["gemini"].calls[0][0].operation is Operation.VISION
    # Gemini 2.5 Flash may spend roughly 50-60 tokens on internal reasoning
    # before emitting the one-word health response.  A smaller cap produces a
    # false EMPTY result even though image authentication and processing work.
    assert adapters["gemini"].calls[0][2] >= 64
    assert len(attempts) == 3
    assert all(item.attempt_number == 1 for item in attempts)
    assert all(item.fallback_from is None for item in attempts)
    assert all(item.caller_endpoint == "llm_routing_health" for item in attempts)
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == report
    assert all(set(item) == _PROVIDER_FIELDS for item in report["providers"])
    assert all(item["status"] == "healthy" for item in report["providers"])
    assert report["cost_saving_activation"] == {
        "ready": True,
        "status": "ready",
        "reason": "deepseek_decisive_healthy",
    }
    assert report["telemetry"] == {"complete": True, "status": "complete"}


@pytest.mark.parametrize("recorder_result", [False, OSError("raw-ledger-secret")])
def test_live_telemetry_failure_is_persisted_and_blocks_activation(
    tmp_path, monkeypatch, recorder_result
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    deepseek = _Adapter(AdapterResponse(text="healthy"))

    def recorder(_attempt):
        if isinstance(recorder_result, Exception):
            raise recorder_result
        return recorder_result

    snapshot_path = tmp_path / "health.json"
    report = health.run_health_check(
        live=True,
        adapters={"deepseek": deepseek},
        attempt_recorder=recorder,
        snapshot_path=snapshot_path,
        now=_NOW,
    )

    assert len(deepseek.calls) == 1
    assert report["telemetry"] == {"complete": False, "status": "unavailable"}
    assert report["cost_saving_activation"] == {
        "ready": False,
        "status": "blocked",
        "reason": "health_accounting_unavailable",
    }
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == report
    serialized = json.dumps(report, sort_keys=True)
    assert "raw-ledger-secret" not in serialized


def test_live_physical_probe_without_recorder_fails_accounting_closed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    deepseek = _Adapter(AdapterResponse(text="healthy"))

    report = health.run_health_check(
        live=True,
        adapters={"deepseek": deepseek},
        attempt_recorder=None,
        snapshot_path=tmp_path / "health.json",
        now=_NOW,
    )

    assert len(deepseek.calls) == 1
    assert report["telemetry"] == {"complete": False, "status": "unavailable"}
    assert report["cost_saving_activation"] == {
        "ready": False,
        "status": "blocked",
        "reason": "health_accounting_unavailable",
    }


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (_HttpFailure(401, "raw-401-secret"), "authentication"),
        (_HttpFailure(403, "raw-403-secret"), "authentication"),
        (_HttpFailure(402, "raw-402-secret"), "insufficient_balance"),
        (_HttpFailure(429, "raw-429-secret"), "rate_limit"),
        (_HttpFailure(404, "raw-404-secret"), "model_unavailable"),
        (_HttpFailure(503, "raw-503-secret"), "server_error"),
        (TimeoutError("raw-timeout-secret"), "timeout"),
        (ConnectionError("raw-connection-secret"), "connection"),
        (RuntimeError("raw-unknown-secret"), "unknown"),
    ],
)
def test_live_classifies_failures_without_exposing_raw_exception(
    tmp_path, monkeypatch, failure, expected_status
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-key-must-not-leak")
    attempts = []

    report = health.run_health_check(
        live=True,
        adapters={"deepseek": _Adapter(failure)},
        attempt_recorder=attempts.append,
        snapshot_path=tmp_path / "health.json",
        now=_NOW,
    )

    deepseek = _record(report, "deepseek", Operation.DECISIVE_TEXT.value)
    assert deepseek["available"] is False
    assert deepseek["status"] == expected_status
    assert report["cost_saving_activation"]["ready"] is False
    assert attempts[0].error_class.value == expected_status
    serialized = json.dumps(report, sort_keys=True)
    assert "raw-" not in serialized
    assert "fixture-key-must-not-leak" not in serialized


def test_openai_only_success_is_not_cost_saving_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "configured")
    openai = _Adapter(AdapterResponse(text="healthy"))
    deepseek = _Adapter(AssertionError("unconfigured DeepSeek was called"))

    report = health.run_health_check(
        live=True,
        adapters={"deepseek": deepseek, "openai": openai},
        attempt_recorder=lambda _attempt: None,
        snapshot_path=tmp_path / "health.json",
        now=_NOW,
    )

    assert len(openai.calls) == 1
    assert deepseek.calls == []
    assert _record(report, "openai", Operation.DECISIVE_TEXT.value)["status"] == "healthy"
    assert report["cost_saving_activation"] == {
        "ready": False,
        "status": "blocked",
        "reason": "deepseek_decisive_unconfigured",
    }


def test_decisive_deepseek_success_does_not_self_attest_vision(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-verified")
    deepseek = _Adapter(AdapterResponse(text="healthy decisive response"))

    report = health.run_health_check(
        live=True,
        adapters={"deepseek": deepseek},
        attempt_recorder=lambda _attempt: None,
        snapshot_path=tmp_path / "health.json",
        now=_NOW,
    )

    assert len(deepseek.calls) == 1
    assert "vision_attestation" not in report
    assert not any(
        item["provider"] == "deepseek" and item["operation"] == Operation.VISION.value
        for item in report["providers"]
    )
    assert policy_for(
        Operation.VISION,
        vision_attestation=report.get("vision_attestation"),
        now=_NOW,
    ).providers == ("gemini", "openai")


def test_one_deepseek_probe_can_carry_a_separately_validated_vision_attestation(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-verified")
    calls = []
    checked_at = (_NOW - timedelta(seconds=1)).isoformat()

    def probe(spec):
        calls.append(spec)
        return health.ProbeResult(
            response=AdapterResponse(text="healthy decisive response"),
            vision_attestation={
                "provider": "deepseek",
                "endpoint": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-vision-verified",
                "modality": "vision",
                "checked_at": checked_at,
                "ttl_seconds": 300,
                "capable": True,
                "healthy": True,
                "diagnostic": "must-not-be-persisted",
            },
        )

    snapshot_path = tmp_path / "health.json"
    report = health.run_health_check(
        live=True,
        probe=probe,
        attempt_recorder=lambda _attempt: None,
        snapshot_path=snapshot_path,
        now=_NOW,
    )

    assert len(calls) == 1
    assert calls[0].provider == "deepseek"
    assert calls[0].operation is Operation.DECISIVE_TEXT
    attestation = report["vision_attestation"]
    assert set(attestation) == {
        "provider",
        "endpoint",
        "model",
        "modality",
        "checked_at",
        "ttl_seconds",
        "capable",
        "healthy",
    }
    assert "diagnostic" not in json.dumps(report, sort_keys=True)
    assert vision_attestation_is_valid(
        attestation,
        model="deepseek-vision-verified",
        now=_NOW,
    )
    vision_record = _record(report, "deepseek", Operation.VISION.value)
    assert set(vision_record) == _PROVIDER_FIELDS
    assert vision_record["model"] == "deepseek-vision-verified"
    assert vision_record["available"] is True
    assert policy_for(
        Operation.VISION,
        vision_attestation=attestation,
        now=_NOW,
    ).providers == ("gemini", "deepseek", "openai")
    status = get_llm_routing_status(
        store=RoutingStore(tmp_path / "vision-usage.sqlite3"),
        health_path=snapshot_path,
        now=_NOW,
    )
    reported_vision = _record(status, "deepseek", Operation.VISION.value)
    assert reported_vision["status"] == "healthy"
    assert reported_vision["checked_at"] == attestation["checked_at"]
    assert reported_vision["ttl_seconds"] == attestation["ttl_seconds"]
    assert status["provider_order"][Operation.VISION.value] == [
        "gemini",
        "deepseek",
        "openai",
    ]


def test_invalid_vision_attestation_is_omitted_without_leaking_endpoint_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-verified")

    def probe(_spec):
        return health.ProbeResult(
            response=AdapterResponse(text="healthy decisive response"),
            vision_attestation={
                "provider": "deepseek",
                "endpoint": (
                    "https://operator:raw-endpoint-secret@api.deepseek.com/"
                    "chat/completions"
                ),
                "model": "deepseek-vision-verified",
                "modality": "vision",
                "checked_at": _NOW.isoformat(),
                "ttl_seconds": 300,
                "capable": True,
                "healthy": True,
            },
        )

    report = health.run_health_check(
        live=True,
        probe=probe,
        attempt_recorder=lambda _attempt: None,
        snapshot_path=tmp_path / "health.json",
        now=_NOW,
    )

    assert "vision_attestation" not in report
    assert "raw-endpoint-secret" not in json.dumps(report, sort_keys=True)


def test_live_snapshot_is_consumable_by_read_only_routing_status(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    monkeypatch.setenv("OPENAI_API_KEY", "configured")
    monkeypatch.setenv("GEMINI_API_KEY", "configured")
    adapters = {
        provider: _Adapter(AdapterResponse(text="healthy"))
        for provider in ("deepseek", "openai", "gemini")
    }
    snapshot_path = tmp_path / "health.json"
    health.run_health_check(
        live=True,
        adapters=adapters,
        attempt_recorder=lambda _attempt: None,
        snapshot_path=snapshot_path,
        now=_NOW,
    )

    status = get_llm_routing_status(
        store=RoutingStore(tmp_path / "usage.sqlite3"),
        health_path=snapshot_path,
        now=_NOW + timedelta(seconds=1),
    )

    assert status["freshness"]["status"] == "fresh"
    assert _record(status, "deepseek", Operation.DECISIVE_TEXT.value)["status"] == "healthy"
    assert _record(status, "openai", Operation.DECISIVE_TEXT.value)["status"] == "healthy"
    assert _record(status, "gemini", Operation.VISION.value)["status"] == "healthy"


@pytest.mark.parametrize("ttl_seconds", [0, -1, True, 86_401])
def test_invalid_snapshot_ttl_fails_before_any_live_call(
    tmp_path, monkeypatch, ttl_seconds
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    deepseek = _Adapter(AdapterResponse(text="healthy"))

    with pytest.raises(ValueError, match="ttl_seconds"):
        health.run_health_check(
            live=True,
            adapters={"deepseek": deepseek},
            snapshot_path=tmp_path / "health.json",
            now=_NOW,
            ttl_seconds=ttl_seconds,
        )

    assert deepseek.calls == []
    assert not (tmp_path / "health.json").exists()
