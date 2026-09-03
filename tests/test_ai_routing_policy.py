from datetime import datetime, timedelta, timezone

import pytest

from app.services.ai_routing.contracts import AnalysisStatus, Operation
from app.services.ai_routing.policy import policy_for


_NOW = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)


def _vision_attestation(**overrides):
    record = {
        "provider": "deepseek",
        "endpoint": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-vision-tested",
        "modality": "vision",
        "checked_at": (_NOW - timedelta(seconds=30)).isoformat(),
        "ttl_seconds": 300,
        "capable": True,
        "healthy": True,
    }
    record.update(overrides)
    return record


def test_decisive_policy_cannot_be_reordered_by_legacy_env(monkeypatch):
    monkeypatch.setenv("MIROFISH_LLM_PROVIDER_ORDER", "openai,deepseek")

    policy = policy_for(Operation.DECISIVE_TEXT)

    assert policy.providers == ("deepseek", "openai")
    assert policy.max_output_tokens == 1200


def test_vision_policy_starts_with_gemini():
    policy = policy_for(Operation.VISION)

    assert policy.providers[0] == "gemini"
    assert "deepseek" not in policy.providers


def test_vision_adds_deepseek_only_for_current_exact_attestation(monkeypatch):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")

    policy = policy_for(
        Operation.VISION,
        vision_attestation=_vision_attestation(),
        now=_NOW,
    )

    assert policy.providers == ("gemini", "deepseek", "openai")
    assert policy.models["deepseek"] == "deepseek-vision-tested"


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "openai"},
        {"endpoint": "https://proxy.example/chat/completions"},
        {"endpoint": "https://api.deepseek.com/v1/chat/completions"},
        {"model": "deepseek-vision-other"},
        {"modality": "text"},
        {"capable": False},
        {"healthy": False},
        {"capable": 1},
        {"healthy": "true"},
    ],
)
def test_vision_skips_deepseek_for_identity_or_health_mismatch(monkeypatch, overrides):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")

    policy = policy_for(
        Operation.VISION,
        vision_attestation=_vision_attestation(**overrides),
        now=_NOW,
    )

    assert policy.providers == ("gemini", "openai")


@pytest.mark.parametrize(
    "overrides",
    [
        {"checked_at": (_NOW - timedelta(seconds=300)).isoformat()},
        {"checked_at": (_NOW + timedelta(microseconds=1)).isoformat()},
        {"checked_at": "2026-09-03T03:00:00"},
        {"checked_at": "not-a-timestamp"},
        {"ttl_seconds": 0},
        {"ttl_seconds": -1},
        {"ttl_seconds": True},
        {"ttl_seconds": "300"},
        {"ttl_seconds": float("inf")},
    ],
)
def test_vision_skips_deepseek_for_stale_future_or_malformed_time(
    monkeypatch, overrides
):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")

    policy = policy_for(
        Operation.VISION,
        vision_attestation=_vision_attestation(**overrides),
        now=_NOW,
    )

    assert policy.providers == ("gemini", "openai")


def test_vision_attestation_honors_its_finite_positive_ttl(monkeypatch):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")

    policy = policy_for(
        Operation.VISION,
        vision_attestation=_vision_attestation(
            checked_at=(_NOW - timedelta(hours=2)).isoformat(),
            ttl_seconds=86_400,
        ),
        now=_NOW,
    )

    assert policy.providers == ("gemini", "deepseek", "openai")


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://operator:secret@api.deepseek.com/chat/completions",
        "https://api.deepseek.com/chat/completions?api_key=secret",
        "https://api.deepseek.com/chat/completions#secret",
        "https://api.deepseek.com/chat/\ncompletions",
        "api.deepseek.com/chat/completions",
    ],
)
def test_vision_attestation_rejects_non_secret_safe_endpoint(monkeypatch, endpoint):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")

    policy = policy_for(
        Operation.VISION,
        vision_attestation=_vision_attestation(endpoint=endpoint),
        now=_NOW,
    )

    assert policy.providers == ("gemini", "openai")


def test_legacy_vision_verification_flags_cannot_activate_deepseek(monkeypatch):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")
    monkeypatch.setenv("AI_DEEPSEEK_VISION_CAPABILITY_VERIFIED", "1")
    monkeypatch.setenv("AI_DEEPSEEK_VISION_HEALTH_VERIFIED", "1")

    assert policy_for(Operation.VISION).providers == ("gemini", "openai")


def test_vision_attestation_matches_normalized_host_and_configured_port(monkeypatch):
    monkeypatch.setenv("AI_DEEPSEEK_VISION_MODEL", "deepseek-vision-tested")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://API.DEEPSEEK.COM:443/")

    policy = policy_for(
        Operation.VISION,
        vision_attestation=_vision_attestation(),
        now=_NOW,
    )

    assert policy.providers == ("gemini", "deepseek", "openai")


def test_result_distinguishes_hold_and_hold_review():
    assert AnalysisStatus.HOLD_REVIEW != "HOLD"
    assert AnalysisStatus.HOLD_REVIEW.value == "HOLD_REVIEW"


def test_model_environment_changes_model_not_operation_tier(monkeypatch):
    monkeypatch.setenv("AI_DEEPSEEK_DECISIVE_MODEL", "deepseek-approved-pro")
    monkeypatch.setenv("AI_DEEPSEEK_FAST_MODEL", "deepseek-approved-fast")

    decisive = policy_for(Operation.DECISIVE_TEXT)
    bulk = policy_for(Operation.BULK_TEXT)

    assert decisive.models["deepseek"] == "deepseek-approved-pro"
    assert bulk.models["deepseek"] == "deepseek-approved-fast"
    assert decisive.providers == ("deepseek", "openai")
