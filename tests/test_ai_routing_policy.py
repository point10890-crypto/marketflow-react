from app.services.ai_routing.contracts import AnalysisStatus, Operation
from app.services.ai_routing.policy import policy_for


def test_decisive_policy_cannot_be_reordered_by_legacy_env(monkeypatch):
    monkeypatch.setenv("MIROFISH_LLM_PROVIDER_ORDER", "openai,deepseek")

    policy = policy_for(Operation.DECISIVE_TEXT)

    assert policy.providers == ("deepseek", "openai")
    assert policy.max_output_tokens == 1200


def test_vision_policy_starts_with_gemini():
    policy = policy_for(Operation.VISION)

    assert policy.providers[0] == "gemini"
    assert "deepseek" not in policy.providers


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
