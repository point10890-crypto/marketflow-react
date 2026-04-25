"""Unit tests for ClaudeDevilAdvocate (consensus_strong post-review)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 모든 Claude 호출은 mock — 실제 키 불필요. 단, anthropic.AsyncAnthropic 는 init 시 키를 요구하므로 stub 주입.
# setdefault 가 아닌 강제 할당 — shell 환경에 빈 문자열로 세팅되어 있을 수 있음.
if not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = "test-key-stub-not-real"
os.environ["DEVIL_ADVOCATE_ENABLED"] = "1"


def _build_screener_with_da():
    """Helper to build screener with Devil's Advocate enabled."""
    os.environ["DEVIL_ADVOCATE_ENABLED"] = "1"
    os.environ["MULTI_AI_INCLUDE_GROK"] = "1"
    # API 키가 없으면 client 가 None 이라 review 스킵 — 테스트는 mock 으로 우회
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-stub")
    from engine.llm_analyzer import MultiAIConsensusScreener
    return MultiAIConsensusScreener()


def _strong_pick(code: str = "005930", name: str = "삼성전자") -> dict:
    return {
        "stock_code": code,
        "stock_name": name,
        "rank": 1,
        "confidence": "HIGH",
        "reason": "[Gemini] AI 메모리 [GPT-4o] HBM [Grok] 펀더멘털",
        "risk": "글로벌 매크로",
        "expected_return": "+10%",
        "source": "consensus_strong",
        "gemini_rank": 1,
        "openai_rank": 1,
        "grok_rank": 1,
    }


def _signal(code: str = "005930") -> dict:
    return {
        "stock_code": code,
        "grade": "S",
        "change_pct": 8.5,
        "trading_value": 1_500_000_000_000,
        "volume_ratio": 0.7,
        "foreign_5d": -800,
        "inst_5d": 200,
        "score": {"total": 13},
        "checklist": {"has_consolidation": False, "negative_news": False, "upper_wick_long": True},
    }


def _mock_anthropic_response(text: str, in_tok: int = 1000, out_tok: int = 200):
    """Build a fake anthropic Message object with .content[0].text and .usage."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(input_tokens=in_tok, output_tokens=out_tok)
    return msg


# ─────────────────────────────────────────────────────────────
# Test 1: WARN verdict → confidence 1단계 강등
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_warn_verdict_downgrades_one_level():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    fake_response = _mock_anthropic_response(
        '{"flags":[{"category":"volume_decay","severity":"MEDIUM","evidence":"거래량 -30%"}],'
        '"verdict":"WARN","reasoning":"매수세 약화"}'
    )
    with patch.object(da.client.messages, "create", new=AsyncMock(return_value=fake_response)):
        result = await da.review_strong_picks([_strong_pick()], [_signal()])

    assert len(result) == 1
    r = result[0]
    assert r["verdict"] == "WARN"
    assert len(r["flags"]) == 1
    assert r["flags"][0]["category"] == "volume_decay"
    assert r["flags"][0]["severity"] == "MEDIUM"
    assert da.last_run_cost_usd > 0


# ─────────────────────────────────────────────────────────────
# Test 2: BLOCK verdict → 두 HIGH flags
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_block_verdict_with_two_high_flags():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    fake_response = _mock_anthropic_response(
        '{"flags":['
        '{"category":"chart_trap","severity":"HIGH","evidence":"블로우오프"},'
        '{"category":"supply_warning","severity":"HIGH","evidence":"외인 매도"}'
        '],"verdict":"BLOCK","reasoning":"위험"}'
    )
    with patch.object(da.client.messages, "create", new=AsyncMock(return_value=fake_response)):
        result = await da.review_strong_picks([_strong_pick()], [_signal()])

    assert result[0]["verdict"] == "BLOCK"
    assert len(result[0]["flags"]) == 2
    assert all(f["severity"] == "HIGH" for f in result[0]["flags"])


# ─────────────────────────────────────────────────────────────
# Test 3: PASS verdict → flags 비어있음
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pass_verdict_no_flags():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    fake_response = _mock_anthropic_response(
        '{"flags":[],"verdict":"PASS","reasoning":"리스크 없음"}'
    )
    with patch.object(da.client.messages, "create", new=AsyncMock(return_value=fake_response)):
        result = await da.review_strong_picks([_strong_pick()], [_signal()])

    assert result[0]["verdict"] == "PASS"
    assert result[0]["flags"] == []


# ─────────────────────────────────────────────────────────────
# Test 4: Claude 호출 실패 → graceful (verdict=PASS, 비용 0)
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_claude_exception_graceful_passthrough():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    with patch.object(da.client.messages, "create", new=AsyncMock(side_effect=RuntimeError("API down"))):
        result = await da.review_strong_picks([_strong_pick()], [_signal()])

    assert len(result) == 1
    assert result[0]["verdict"] == "PASS"
    assert result[0]["flags"] == []


# ─────────────────────────────────────────────────────────────
# Test 5: JSON 파싱 실패 → graceful PASS
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_json_parse_failure_graceful():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    fake_response = _mock_anthropic_response("This is not JSON at all")
    with patch.object(da.client.messages, "create", new=AsyncMock(return_value=fake_response)):
        result = await da.review_strong_picks([_strong_pick()], [_signal()])

    assert result[0]["verdict"] == "PASS"
    assert result[0]["flags"] == []


# ─────────────────────────────────────────────────────────────
# Test 6: 빈 strong_picks → Claude 호출 X
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_empty_strong_picks_no_call():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    with patch.object(da.client.messages, "create", new=AsyncMock()) as mock_create:
        result = await da.review_strong_picks([], [])

    assert result == []
    mock_create.assert_not_called()
    assert da.last_run_cost_usd == 0.0


# ─────────────────────────────────────────────────────────────
# Test 7: DEVIL_ADVOCATE_ENABLED=0 → 전체 스킵
# ─────────────────────────────────────────────────────────────
def test_disabled_via_env():
    os.environ["DEVIL_ADVOCATE_ENABLED"] = "0"
    # 모듈 재import 위해 테스트 안에서 dynamic import
    import importlib
    import engine.llm_analyzer
    importlib.reload(engine.llm_analyzer)
    s = engine.llm_analyzer.MultiAIConsensusScreener()
    assert s.devil_advocate is None
    # 복구
    os.environ["DEVIL_ADVOCATE_ENABLED"] = "1"
    importlib.reload(engine.llm_analyzer)


# ─────────────────────────────────────────────────────────────
# Test 8: invalid verdict → "PASS" 로 정규화
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_invalid_verdict_normalized_to_pass():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    fake_response = _mock_anthropic_response(
        '{"flags":[],"verdict":"NUCLEAR","reasoning":"weird verdict"}'
    )
    with patch.object(da.client.messages, "create", new=AsyncMock(return_value=fake_response)):
        result = await da.review_strong_picks([_strong_pick()], [_signal()])

    assert result[0]["verdict"] == "PASS"


# ─────────────────────────────────────────────────────────────
# Test 9: invalid severity → "LOW" 로 정규화
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_invalid_severity_normalized_to_low():
    from engine.llm_analyzer import ClaudeDevilAdvocate
    da = ClaudeDevilAdvocate()
    assert da.client is not None

    fake_response = _mock_anthropic_response(
        '{"flags":[{"category":"x","severity":"CRITICAL","evidence":"e"}],'
        '"verdict":"WARN","reasoning":"r"}'
    )
    with patch.object(da.client.messages, "create", new=AsyncMock(return_value=fake_response)):
        result = await da.review_strong_picks([_strong_pick()], [_signal()])

    assert result[0]["flags"][0]["severity"] == "LOW"


# ─────────────────────────────────────────────────────────────
# Test 10: Integration — _review_strong_picks 가 픽 confidence 강등
# ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_integration_warn_downgrades_pick_confidence():
    s = _build_screener_with_da()
    if s.devil_advocate is None or s.devil_advocate.client is None:
        pytest.skip("ANTHROPIC_API_KEY not set")

    consensus = {
        "picks": [
            _strong_pick(),  # HIGH
            {**_strong_pick("000660", "SK하이닉스"), "source": "consensus"},  # 2-of-3 → 검토 X
        ],
        "consensus_count": 2,
        "strong_count": 1,
        "total_cost_usd": 0.05,
    }
    fake_response = _mock_anthropic_response(
        '{"flags":[{"category":"chart_trap","severity":"MEDIUM","evidence":"e"}],'
        '"verdict":"WARN","reasoning":"r"}'
    )
    with patch.object(s.devil_advocate.client.messages, "create", new=AsyncMock(return_value=fake_response)):
        out = await s._review_strong_picks(consensus, [_signal()])

    # consensus_strong 픽: HIGH → MEDIUM
    assert out["picks"][0]["confidence"] == "MEDIUM"
    assert out["picks"][0]["review_verdict"] == "WARN"
    assert len(out["picks"][0]["devil_advocate_flags"]) == 1
    # consensus 픽: 검토 안 됨
    assert "review_verdict" not in out["picks"][1]
    # 메타
    assert out["devil_advocate_enabled"] is True
    assert out["devil_advocate_flagged_count"] == 1
    assert out["devil_advocate_cost_usd"] > 0
    assert out["total_cost_usd"] > 0.05  # 합산
