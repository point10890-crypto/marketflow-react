"""Unit tests for MultiAIConsensusScreener (N-way consensus, v2)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 프로젝트 루트 import 경로
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.llm_analyzer import (  # noqa: E402
    MultiAIConsensusScreener,
    MODEL_GEMINI,
    MODEL_OPENAI,
    MODEL_GROK,
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
    assert MODEL_GEMINI in s.screeners
    assert MODEL_OPENAI in s.screeners


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
