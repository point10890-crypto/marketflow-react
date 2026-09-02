"""Unit tests for MultiAIConsensusScreener (N-way consensus, v2)."""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

# 프로젝트 루트 import 경로
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.llm_analyzer import (  # noqa: E402
    DeepSeekScreener,
    GeminiScreener,
    GrokScreener,
    MultiAIConsensusScreener,
    MODEL_DEEPSEEK,
    MODEL_GEMINI,
    MODEL_OPENAI,
    MODEL_GROK,
)
from engine import llm_analyzer as llm_analyzer_module  # noqa: E402
from app.services.ai_routing.contracts import (  # noqa: E402
    AnalysisStatus,
    ProviderErrorClass,
    RoutingResult,
    TokenUsage,
)


def _pick(code: str, name: str = "", rank: int = 1, conf: str = "MEDIUM",
          reason: str = "test reason", risk: str = "test risk",
          expected_return: str = "5%") -> dict:
    return {
        "stock_code": code,
        "stock_name": name or f"name_{code}",
        "rank": rank,
        "confidence": conf,
        "reason": reason,
        "risk": risk,
        "expected_return": expected_return,
    }


def _result(picks: list[dict], model: str = "test-model", market_view: str = "",
            top_themes: list[str] | None = None) -> dict:
    return {
        "picks": picks,
        "model": model,
        "market_view": market_view,
        "top_themes": top_themes or [],
        "generated_at": "2026-04-25T00:00:00",
    }


def _build_screener_3way() -> MultiAIConsensusScreener:
    """3-way (Gemini+OpenAI+Grok) screener factory."""
    os.environ["MULTI_AI_INCLUDE_GROK"] = "1"
    return MultiAIConsensusScreener()


def _build_screener_2way() -> MultiAIConsensusScreener:
    """2-way legacy (Gemini+OpenAI only)."""
    os.environ["MULTI_AI_INCLUDE_GROK"] = "0"
    return MultiAIConsensusScreener()


def test_shadow_flag_without_explicit_providers_records_not_run(monkeypatch):
    monkeypatch.setenv("MULTI_AI_SHADOW_COMPARE", "1")
    monkeypatch.delenv("MULTI_AI_INCLUDE_GEMINI", raising=False)
    monkeypatch.delenv("MULTI_AI_INCLUDE_GROK", raising=False)
    screener = MultiAIConsensusScreener()

    class Primary:
        model_name = "deepseek-v4-pro"

        async def screen_candidates(self, _signals, **_kwargs):
            return {"picks": [], "model": self.model_name}

    screener.screeners[MODEL_DEEPSEEK] = Primary()
    output = __import__("asyncio").run(
        screener.screen_candidates([{"stock_code": "005930"}], run_id="shadow-run")
    )

    assert screener.shadow_screeners == {}
    assert output["shadow_comparison"] == {
        "status": "not_run",
        "reason": "no_explicit_shadow_providers",
        "compared": False,
        "verdict_blended": False,
        "models_attempted": [],
    }
    empty = __import__("asyncio").run(screener.screen_candidates([]))
    assert empty["shadow_comparison"]["reason"] == "no_explicit_shadow_providers"
    assert empty["shadow_comparison"]["compared"] is False


# ───────────────────────────────────────────────────────────────────
# Test 1: 3-of-3 intersection → consensus_strong, boost 2 levels
# ───────────────────────────────────────────────────────────────────
def test_3of3_consensus_strong_low_to_high():
    s = _build_screener_3way()
    p_g = _pick("000001", rank=1, conf="LOW")
    p_o = _pick("000001", rank=2, conf="LOW")
    p_x = _pick("000001", rank=3, conf="LOW")

    out = s._build_consensus({
        MODEL_GEMINI: _result([p_g]),
        MODEL_OPENAI: _result([p_o]),
        MODEL_GROK: _result([p_x]),
    })

    assert len(out["picks"]) == 1
    pick = out["picks"][0]
    assert pick["source"] == "consensus_strong"
    assert pick["confidence"] == "HIGH"  # LOW(2) - 2 = HIGH(0)
    assert out["strong_count"] == 1
    assert out["consensus_count"] == 1


def test_3of3_consensus_strong_medium_to_high():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("X", conf="MEDIUM", rank=1)]),
        MODEL_OPENAI: _result([_pick("X", conf="HIGH", rank=2)]),
        MODEL_GROK: _result([_pick("X", conf="MEDIUM", rank=3)]),
    })
    assert out["picks"][0]["confidence"] == "HIGH"  # min(MEDIUM,HIGH,MEDIUM) = HIGH(0), boost 2 → still HIGH


# ───────────────────────────────────────────────────────────────────
# Test 2: 2-of-3 페어 (각 페어별 개별 케이스)
# ───────────────────────────────────────────────────────────────────
def test_2of3_gemini_openai_pair():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("A", conf="LOW", rank=1)]),
        MODEL_OPENAI: _result([_pick("A", conf="LOW", rank=2)]),
        MODEL_GROK: _result([]),
    })
    assert len(out["picks"]) == 1
    p = out["picks"][0]
    assert p["source"] == "consensus"
    assert p["confidence"] == "MEDIUM"  # LOW(2) - 1 = MEDIUM(1)
    assert "gemini_rank" in p and "openai_rank" in p
    assert "grok_rank" not in p  # placeholder 99 금지
    assert out["strong_count"] == 0


def test_2of3_gemini_grok_pair():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("B", conf="LOW", rank=1)]),
        MODEL_OPENAI: _result([]),
        MODEL_GROK: _result([_pick("B", conf="LOW", rank=2)]),
    })
    p = out["picks"][0]
    assert p["source"] == "consensus"
    assert "openai_rank" not in p
    assert "gemini_rank" in p and "grok_rank" in p


def test_2of3_openai_grok_pair():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([]),
        MODEL_OPENAI: _result([_pick("C", conf="LOW", rank=1)]),
        MODEL_GROK: _result([_pick("C", conf="LOW", rank=2)]),
    })
    p = out["picks"][0]
    assert p["source"] == "consensus"
    assert "gemini_rank" not in p
    assert "openai_rank" in p and "grok_rank" in p


# ───────────────────────────────────────────────────────────────────
# Test 3: 1-of-3 단독 → <model>_only, downgrade
# ───────────────────────────────────────────────────────────────────
def test_solo_gemini_only_downgrade():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("S1", conf="HIGH")]),
        MODEL_OPENAI: _result([]),
        MODEL_GROK: _result([]),
    })
    p = out["picks"][0]
    assert p["source"] == "gemini_only"
    assert p["confidence"] == "MEDIUM"  # HIGH → MEDIUM


def test_solo_openai_only_downgrade():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([]),
        MODEL_OPENAI: _result([_pick("S2", conf="MEDIUM")]),
        MODEL_GROK: _result([]),
    })
    p = out["picks"][0]
    assert p["source"] == "openai_only"
    assert p["confidence"] == "LOW"


def test_solo_grok_only_downgrade():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([]),
        MODEL_OPENAI: _result([]),
        MODEL_GROK: _result([_pick("S3", conf="LOW")]),
    })
    p = out["picks"][0]
    assert p["source"] == "grok_only"
    assert p["confidence"] == "LOW"


# ───────────────────────────────────────────────────────────────────
# Test 4: 완전 disjoint
# ───────────────────────────────────────────────────────────────────
def test_disjoint_no_strong_no_pair():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("D1")]),
        MODEL_OPENAI: _result([_pick("D2")]),
        MODEL_GROK: _result([_pick("D3")]),
    })
    assert out["strong_count"] == 0
    assert out["consensus_count"] == 0
    sources = {p["source"] for p in out["picks"]}
    assert sources == {"gemini_only", "openai_only", "grok_only"}


# ───────────────────────────────────────────────────────────────────
# Test 5: Grok 빈 결과 → 2-way 와 호환 동작
# ───────────────────────────────────────────────────────────────────
def test_grok_empty_degrades_to_2way():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("E1", rank=1, conf="LOW")]),
        MODEL_OPENAI: _result([_pick("E1", rank=2, conf="LOW")]),
        MODEL_GROK: _result([]),  # Grok 실패 (빈 결과)
    })
    # E1 은 2-of-3 합의 → consensus
    p = out["picks"][0]
    assert p["source"] == "consensus"
    assert out["strong_count"] == 0


# ───────────────────────────────────────────────────────────────────
# Test 6: MULTI_AI_INCLUDE_GROK=0 → 2-way legacy
# ───────────────────────────────────────────────────────────────────
def test_grok_disabled_via_env():
    s = _build_screener_2way()
    assert MODEL_GROK not in s.screeners
    # OpenAI는 DeepSeek logical slot 실패 시 중앙 router 안에서만 한 번 대체한다.
    assert MODEL_DEEPSEEK in s.screeners
    assert MODEL_OPENAI not in s.screeners
    assert MODEL_GEMINI not in s.screeners


def test_openai_cannot_be_enabled_as_a_parallel_shadow_voter(monkeypatch):
    """OpenAI is a failed-slot replacement, never another verdict path."""
    monkeypatch.setenv("MULTI_AI_SHADOW_COMPARE", "1")
    monkeypatch.setenv("MULTI_AI_SHADOW_INCLUDE_OPENAI", "1")
    monkeypatch.setenv("MULTI_AI_INCLUDE_GEMINI", "0")
    monkeypatch.setenv("MULTI_AI_INCLUDE_GROK", "0")

    screener = MultiAIConsensusScreener()

    assert MODEL_OPENAI not in screener.screeners
    assert MODEL_OPENAI not in screener.shadow_screeners


class _RoutedSlot:
    client = True
    model_name = "logical-deepseek-slot"

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def screen_candidates(self, signals_data, *, run_id=None, request_id=None):
        self.calls.append((signals_data, run_id, request_id))
        return dict(self.result)


@pytest.mark.asyncio
async def test_routed_primary_slot_uses_stable_identity_and_unsafe_shadow_is_not_run():
    primary = _RoutedSlot({
        "picks": [_pick("PRIMARY")],
        "model": "deepseek-v4-flash",
        "routing": {"actual_provider": "deepseek", "fallback_used": False},
        "market_view": "primary",
        "top_themes": ["primary-theme"],
    })
    shadow = _RoutedSlot({
        "picks": [_pick("SHADOW")],
        "model": "shadow-model",
        "market_view": "shadow",
        "top_themes": ["shadow-theme"],
    })
    screener = MultiAIConsensusScreener.__new__(MultiAIConsensusScreener)
    screener.screeners = {MODEL_DEEPSEEK: primary}
    screener.shadow_compare = True
    screener.shadow_screeners = {MODEL_GEMINI: shadow}
    screener.devil_advocate = None

    out = await screener.screen_candidates(
        [{"stock_code": "PRIMARY"}], run_id="jongga-run"
    )

    assert [pick["stock_code"] for pick in out["picks"]] == ["PRIMARY"]
    assert out["consensus_method"] == "routed_primary_v1"
    assert out["routing"]["actual_provider"] == "deepseek"
    assert out["shadow_comparison"]["status"] == "not_run"
    assert out["shadow_comparison"]["reason"] == "unsafe_billable_shadow_transport"
    assert out["shadow_comparison"]["compared"] is False
    assert out["shadow_comparison"]["verdict_blended"] is False
    assert "SHADOW" not in {pick["stock_code"] for pick in out["picks"]}
    assert shadow.calls == []
    assert primary.calls[0][1:] == (
        "jongga-run",
        "jongga-run:multi-ai-primary",
    )


@pytest.mark.asyncio
async def test_primary_routed_slot_has_no_shorter_outer_timeout(monkeypatch):
    """The central provider deadlines own cancellation; to_thread must not outlive UI."""
    primary = _RoutedSlot({
        "picks": [],
        "model": "deepseek-v4-flash",
        "routing": {"actual_provider": "deepseek", "fallback_used": False},
    })
    screener = MultiAIConsensusScreener.__new__(MultiAIConsensusScreener)
    screener.screeners = {MODEL_DEEPSEEK: primary}
    screener.shadow_compare = False
    screener.shadow_screeners = {}
    screener.devil_advocate = None
    monkeypatch.setattr(
        "engine.llm_analyzer.asyncio.wait_for",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("central routed slot must not use an outer timeout")
        ),
    )

    result = await screener.screen_candidates(
        [{"stock_code": "005930"}], run_id="jongga-run"
    )

    assert result["consensus_method"] == "routed_primary_v1"
    assert len(primary.calls) == 1
    assert result["routing"]["actual_provider"] == "deepseek"


@pytest.mark.asyncio
async def test_primary_pick_identity_and_prices_are_rehydrated_from_submitted_row():
    primary = _RoutedSlot({
        "picks": [{
            "stock_code": "005930",
            "stock_name": "모델이 만든 이름",
            "market": "NASDAQ",
            "current_price": 1,
            "entry_price": 1,
            "stop_price": 0,
            "target_price": 999999,
            "expected_return": "9999%",
            "confidence": "HIGH",
            "reason": "입력 근거 해석",
            "risk": "변동성",
        }],
        "model": "deepseek-v4-flash",
        "routing": {"actual_provider": "deepseek", "fallback_used": False},
    })
    screener = MultiAIConsensusScreener.__new__(MultiAIConsensusScreener)
    screener.screeners = {MODEL_DEEPSEEK: primary}
    screener.shadow_compare = False
    screener.shadow_screeners = {}
    screener.devil_advocate = None
    submitted = [{
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "market": "KOSPI",
        "current_price": 70_000,
        "entry_price": 70_000,
        "stop_price": 66_500,
        "target_price": 77_000,
    }]

    output = await screener.screen_candidates(submitted, run_id="jongga-run")

    pick = output["picks"][0]
    assert pick["stock_code"] == "005930"
    assert pick["stock_name"] == "삼성전자"
    assert pick["market"] == "KOSPI"
    assert pick["current_price"] == 70_000
    assert pick["entry_price"] == 70_000
    assert pick["stop_price"] == 66_500
    assert pick["target_price"] == 77_000
    assert pick["expected_return"] == "10.0%"
    assert pick["reason"] == "입력 근거 해석"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_picks, expected_error",
    [
        ([{"stock_code": "005930"}, {"stock_code": "005930"}], ProviderErrorClass.NUMERIC_MISMATCH),
        ([{"stock_code": 5930}], ProviderErrorClass.NUMERIC_MISMATCH),
        ([{"stock_code": "UNKNOWN"}], ProviderErrorClass.NUMERIC_MISMATCH),
        ([{"stock_code": "005930", "expected_return": float("nan")}], ProviderErrorClass.NUMERIC_MISMATCH),
        ([{"stock_code": "005930", "rank": float("inf")}], ProviderErrorClass.NUMERIC_MISMATCH),
    ],
)
async def test_routed_primary_rejects_duplicate_unknown_malformed_or_nonfinite_picks(
    monkeypatch, model_picks, expected_error
):
    observed = {}

    def enforce_validator(request):
        payload = {"picks": model_picks, "market_view": "", "top_themes": []}
        observed["error"] = request.domain_validator(payload)
        return RoutingResult(
            text=None,
            analysis_status=AnalysisStatus.FAILED_TECHNICAL,
            primary_provider="deepseek",
            actual_provider=None,
            model="deepseek-v4-flash",
            usage=TokenUsage.unknown(),
        )

    monkeypatch.setattr(llm_analyzer_module, "route_text", enforce_validator)
    screener = DeepSeekScreener(api_key="mocked")

    result = await screener.screen_candidates([{
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "market": "KOSPI",
        "entry_price": 70_000,
        "target_price": 77_000,
    }])

    assert observed["error"] is expected_error
    assert result["picks"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "submitted",
    [
        [
            {"stock_code": "005930", "stock_name": "삼성전자", "entry_price": 70_000},
            {"stock_code": "005930", "stock_name": "중복", "entry_price": 70_000},
        ],
        [{"stock_name": "코드 누락", "entry_price": 70_000}],
        [{"stock_code": "005930", "stock_name": "NaN", "entry_price": float("nan")}],
        [{"stock_code": "005930", "stock_name": "Inf", "target_price": float("inf")}],
        [{"stock_code": "005930", "stock_name": "Nested", "evidence": {"score": float("nan")}}],
    ],
    ids=["duplicate", "missing", "nan", "infinite", "nested-nonfinite"],
)
async def test_invalid_submitted_rows_survive_final_projection_as_technical_artifact(
    monkeypatch, submitted
):
    monkeypatch.setattr(
        llm_analyzer_module,
        "route_text",
        lambda *_a, **_kw: pytest.fail("invalid canonical input must not call a provider"),
    )
    primary = DeepSeekScreener(api_key="mocked")
    screener = MultiAIConsensusScreener.__new__(MultiAIConsensusScreener)
    screener.screeners = {MODEL_DEEPSEEK: primary}
    screener.shadow_compare = False
    screener.shadow_screeners = {}
    screener.devil_advocate = None

    result = await screener.screen_candidates(submitted, run_id="invalid-input-run")

    assert result["picks"] == []
    assert result["analysis_status"] == "FAILED_TECHNICAL"
    assert result["error"] == "invalid_candidate_input"
    assert result["error_class"] == "numeric_mismatch"
    assert result["models_attempted"] == []
    assert result["models_succeeded"] == []
    assert result["total_cost_usd"] == "0"
    assert result["routing"] == {
        "operation": "bulk_text",
        "run_id": "invalid-input-run",
        "request_id": "invalid-input-run:multi-ai-primary",
        "analysis_status": "FAILED_TECHNICAL",
        "primary_provider": "deepseek",
        "actual_provider": None,
        "model": primary.model_name,
        "fallback_used": False,
        "fallback_reason": "invalid_candidate_input",
        "retry_reason": None,
        "usage": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "usage_estimated": False,
        },
        "usage_complete": True,
        "estimated_cost_usd": "0",
        "attempt_count": 0,
        "telemetry_recorded": False,
        "attempts": [],
    }


@pytest.mark.asyncio
async def test_explicit_shadow_provider_is_not_started_without_cancel_safe_transport():
    primary = _RoutedSlot({
        "picks": [_pick("PRIMARY")],
        "model": "deepseek-v4-flash",
        "routing": {"actual_provider": "deepseek", "fallback_used": False},
    })
    shadow = _RoutedSlot({"picks": [_pick("SHADOW")], "model": "shadow-model"})
    screener = MultiAIConsensusScreener.__new__(MultiAIConsensusScreener)
    screener.screeners = {MODEL_DEEPSEEK: primary}
    screener.shadow_compare = True
    screener.shadow_screeners = {MODEL_GEMINI: shadow}
    screener.devil_advocate = None

    output = await screener.screen_candidates(
        [{"stock_code": "PRIMARY", "stock_name": "canonical"}],
        run_id="jongga-shadow-run",
    )

    assert shadow.calls == []
    assert output["shadow_comparison"] == {
        "status": "not_run",
        "reason": "unsafe_billable_shadow_transport",
        "compared": False,
        "verdict_blended": False,
        "models_attempted": [],
        "models_requested": [MODEL_GEMINI],
        "run_id": "jongga-shadow-run",
        "request_ids": {
            MODEL_GEMINI: "jongga-shadow-run:multi-ai-shadow:gemini"
        },
    }


@pytest.mark.asyncio
async def test_shadow_error_boundaries_return_only_fixed_codes(caplog):
    secret = "credential-canary-shadow-error-must-not-escape"

    class Failing:
        model_name = "shadow-model"

        async def screen_candidates(self, _signals):
            raise RuntimeError(secret)

    screener = MultiAIConsensusScreener.__new__(MultiAIConsensusScreener)
    safe = await screener._safe_screen(Failing(), [{"stock_code": "005930"}], 1)

    gemini = GeminiScreener.__new__(GeminiScreener)
    gemini.client = SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(secret))
    ))
    gemini.model_name = "gemini-test"
    gemini_result = await gemini.screen_candidates([{"stock_code": "005930"}])

    class _Completions:
        async def create(self, **_kwargs):
            raise RuntimeError(secret)

    grok = GrokScreener.__new__(GrokScreener)
    grok.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    grok.model_name = "grok-test"
    grok_result = await grok.screen_candidates([{"stock_code": "005930"}])

    for result in (safe, gemini_result, grok_result):
        assert result["error"] == "provider_unavailable"
        assert result["error_class"] == "unknown"
        assert secret not in str(result)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_shadow_early_results_use_fixed_reason_and_error_codes():
    for screener in (
        GeminiScreener.__new__(GeminiScreener),
        GrokScreener.__new__(GrokScreener),
    ):
        screener.client = None
        screener.model_name = "shadow-model"
        unavailable = await screener.screen_candidates([{"stock_code": "005930"}])
        assert unavailable["error"] == "provider_unavailable"
        assert unavailable["error_class"] == "client_unavailable"

        screener.client = object()
        empty = await screener.screen_candidates([])
        assert empty["error"] == "no_candidates"
        assert empty["error_class"] is None


# ───────────────────────────────────────────────────────────────────
# Test 7: HIGH confidence 캡 (오버플로우 없음)
# ───────────────────────────────────────────────────────────────────
def test_high_confidence_cap():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("H1", conf="HIGH", rank=1)]),
        MODEL_OPENAI: _result([_pick("H1", conf="HIGH", rank=1)]),
        MODEL_GROK: _result([_pick("H1", conf="HIGH", rank=1)]),
    })
    assert out["picks"][0]["confidence"] == "HIGH"  # boost 2 from HIGH(0) = HIGH(0), no overflow


# ───────────────────────────────────────────────────────────────────
# Test 8: 정렬 안정성 (avg_rank 기반)
# ───────────────────────────────────────────────────────────────────
def test_sort_by_avg_rank():
    s = _build_screener_3way()
    # 두 종목 모두 3-of-3 strong, 같은 confidence — avg rank 로 정렬
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("FAR", rank=10), _pick("NEAR", rank=1)]),
        MODEL_OPENAI: _result([_pick("FAR", rank=10), _pick("NEAR", rank=1)]),
        MODEL_GROK: _result([_pick("FAR", rank=10), _pick("NEAR", rank=1)]),
    })
    # NEAR 가 먼저 와야 함
    assert out["picks"][0]["stock_code"] == "NEAR"
    assert out["picks"][1]["stock_code"] == "FAR"


# ───────────────────────────────────────────────────────────────────
# Test 9: _merge_pick 은 placeholder 99 미포함
# ───────────────────────────────────────────────────────────────────
def test_merge_pick_no_placeholder_rank():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("M1", rank=5)]),
        MODEL_OPENAI: _result([_pick("M1", rank=7)]),
        MODEL_GROK: _result([]),
    })
    p = out["picks"][0]
    assert p["gemini_rank"] == 5
    assert p["openai_rank"] == 7
    assert "grok_rank" not in p, "Grok 미선정 종목에 grok_rank=99 placeholder 들어가면 안 됨"


# ───────────────────────────────────────────────────────────────────
# Test 10: models_succeeded 가 실제 picks 생성한 모델만 포함
# ───────────────────────────────────────────────────────────────────
def test_models_succeeded_excludes_failed():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([_pick("X1")], model="gemini-2.5-flash"),
        MODEL_OPENAI: _result([], model="gpt-4o"),  # 실패
        MODEL_GROK: _result([_pick("X1")], model="grok-4"),
    })
    succeeded = out["models_succeeded"]
    attempted = out["models_attempted"]
    assert "gemini-2.5-flash" in succeeded
    assert "grok-4" in succeeded
    assert "gpt-4o" not in succeeded
    assert "gpt-4o" in attempted


# ───────────────────────────────────────────────────────────────────
# Test 11: consensus_method 스키마 버전 bump
# ───────────────────────────────────────────────────────────────────
def test_consensus_method_v2():
    s = _build_screener_3way()
    out = s._build_consensus({
        MODEL_GEMINI: _result([]),
        MODEL_OPENAI: _result([]),
        MODEL_GROK: _result([]),
    })
    assert out["consensus_method"] == "multi_ai_v2"
