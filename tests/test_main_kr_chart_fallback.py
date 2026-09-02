# -*- coding: utf-8 -*-
"""KR AI Chart 분석기의 Vision 폴백 회복력 회귀 테스트.

2026-08-15 사고: 삼성전기 1종목의 Gemini JSON 파싱 실패가 전역 래치
(`_gemini_available = False`)를 트립시켜, 이후 모든 종목이 접근 권한도 없는
gpt-4o-mini 로 넘어가 통째로 드롭됐다. 100종목 중 37종목만 분석된 원인.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from decimal import Decimal

import pytest

from app.services.ai_routing.contracts import AnalysisStatus, RoutingResult, TokenUsage
from app.services.ai_routing.validation import validate_response


@pytest.fixture()
def mk(monkeypatch):
    """무거운 선택적 의존성을 스텁으로 막고 main_kr 를 임포트한다."""
    for name in ("google", "google.genai", "google.genai.types"):
        sys.modules.setdefault(name, types.ModuleType(name))
    # 차트 렌더링 스택은 이 테스트와 무관하고 로컬에 없을 수 있다.
    for name in ("mplfinance", "yfinance"):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.__getattr__ = lambda attr: (lambda *a, **k: None)  # type: ignore[attr-defined]
            sys.modules[name] = stub
    genai_mod = sys.modules["google.genai"]
    if not hasattr(genai_mod, "Client"):
        genai_mod.Client = object  # type: ignore[attr-defined]
    types_mod = sys.modules["google.genai.types"]
    for attr in ("Part", "GenerateContentConfig"):
        if not hasattr(types_mod, attr):
            setattr(types_mod, attr, object)

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")

    import main_kr

    main_kr.API_KEY = "test-gemini"
    main_kr.OPENAI_API_KEY = "test-openai"
    main_kr.reset_vision_health()
    return main_kr


def _run(mk, calls, tickers):
    """tickers 를 순차 분석하고 결과 리스트를 돌려준다."""
    sem = asyncio.Semaphore(1)

    async def go():
        out = []
        for ticker in tickers:
            out.append(
                await mk.analyze_chart(
                    None,
                    ticker,
                    ticker,
                    "chart.png",
                    sem,
                    run_id="chart-run",
                    candidate_rank=len(out) + 1,
                )
            )
        return out

    return asyncio.run(go())


def _routing_result(text, *, provider="gemini", fallback=False):
    return RoutingResult(
        text=text,
        analysis_status=(
            AnalysisStatus.SUCCESS_FALLBACK if fallback else AnalysisStatus.SUCCESS_PRIMARY
        ),
        primary_provider="gemini",
        actual_provider=provider,
        model="model-used",
        fallback_used=fallback,
        fallback_reason="timeout" if fallback else None,
        evidence_validated=True,
        usage=TokenUsage(input_tokens=20, output_tokens=10),
        estimated_cost_usd=Decimal("0.001"),
    )


def test_analyze_chart_uses_central_vision_and_preserves_business_shape(
    mk, monkeypatch, tmp_path
):
    """Central routing must stay additive to the historical chart payload."""
    image = tmp_path / "chart.png"
    image.write_bytes(b"fake-png")
    seen = []

    def fake_route(request, **_kwargs):
        seen.append(request)
        return _routing_result(
            '{"signal":"BUY","confidence":77,"reasons":["근거"]}',
            provider="gemini",
        )

    monkeypatch.setattr(mk, "route_vision", fake_route)

    result = asyncio.run(
        mk.analyze_chart(
            None,
            "005930.KS",
            "삼성전자",
            str(image),
            asyncio.Semaphore(1),
            run_id="chart-run",
            candidate_rank=1,
        )
    )

    request = seen[0]
    assert request.operation.value == "vision"
    assert request.run_id == "chart-run"
    assert request.request_id == "chart-run:005930.KS"
    assert request.max_output_tokens == 768
    assert request.openai_fallback_allowed is True
    assert request.images[0].data == b"fake-png"
    assert result["signal"] == "BUY"
    assert result["종목코드"] == "005930"
    assert result["종목명"] == "삼성전자"
    assert result["시장"] == "코스피"
    assert result["routing"]["actual_provider"] == "gemini"
    assert result["routing"]["usage"]["total_tokens"] == 30


def test_only_top_five_candidates_are_openai_fallback_eligible(mk, monkeypatch, tmp_path):
    image = tmp_path / "chart.png"
    image.write_bytes(b"fake-png")
    requests = []

    def fake_route(request, **_kwargs):
        requests.append(request)
        return _routing_result(None)

    monkeypatch.setattr(mk, "route_vision", fake_route)

    async def go():
        semaphore = asyncio.Semaphore(1)
        for rank in range(1, 8):
            await mk.analyze_chart(
                None,
                f"{rank:06d}.KS",
                f"종목{rank}",
                str(image),
                semaphore,
                run_id="same-run",
                candidate_rank=rank,
            )

    asyncio.run(go())

    assert [request.openai_fallback_allowed for request in requests] == [
        True, True, True, True, True, False, False
    ]


def test_unranked_legacy_caller_cannot_bypass_openai_top_five_cap(
    mk, monkeypatch, tmp_path
):
    image = tmp_path / "chart.png"
    image.write_bytes(b"fake-png")
    requests = []
    monkeypatch.setattr(
        mk,
        "route_vision",
        lambda request, **_kwargs: requests.append(request) or _routing_result(None),
    )

    asyncio.run(
        mk.analyze_chart(
            None,
            "005930.KS",
            "삼성전자",
            str(image),
            asyncio.Semaphore(1),
            run_id="legacy-unranked-run",
        )
    )

    assert requests[0].openai_fallback_allowed is False


def test_vision_batch_admits_only_first_twenty_ranked_candidates(mk):
    chart_map = {f"{rank:06d}.KS": f"chart-{rank}.png" for rank in range(1, 26)}

    admitted = mk._ranked_vision_candidates(chart_map)

    assert len(admitted) == 20
    assert admitted[0][0] == "000001.KS"
    assert admitted[-1][0] == "000020.KS"


def test_vision_failure_keeps_secret_free_unavailable_metadata(mk, monkeypatch, tmp_path):
    image = tmp_path / "chart.png"
    image.write_bytes(b"fake-png")
    monkeypatch.setattr(
        mk,
        "route_vision",
        lambda request, **_kwargs: RoutingResult(
            text=None,
            analysis_status=AnalysisStatus.FAILED_TECHNICAL,
            primary_provider="gemini",
            fallback_used=True,
            fallback_reason="authentication",
        ),
    )

    result = asyncio.run(
        mk.analyze_chart(
            None,
            "005930.KS",
            "삼성전자",
            str(image),
            asyncio.Semaphore(1),
            run_id="chart-run",
            candidate_rank=1,
        )
    )

    assert result == {
        "종목코드": "005930",
        "종목명": "삼성전자",
        "시장": "코스피",
        "image_analysis_status": "unavailable",
        "routing": {
            "run_id": "chart-run",
            "request_id": "chart-run:005930.KS",
            "analysis_status": "FAILED_TECHNICAL",
            "primary_provider": "gemini",
            "actual_provider": None,
            "model": None,
            "fallback_used": True,
            "fallback_reason": "authentication",
            "retry_reason": None,
            "usage": {
                "input_tokens": None,
                "cached_input_tokens": None,
                "output_tokens": None,
                "reasoning_tokens": None,
                "total_tokens": None,
                "usage_estimated": True,
            },
            "estimated_cost_usd": None,
            "attempt_count": 0,
            "attempts": [],
        },
    }


def test_summary_artifact_preserves_terminal_vision_status_and_routing(
    mk, monkeypatch
):
    monkeypatch.setattr(mk.pd.DataFrame, "to_csv", lambda *_args, **_kwargs: None)
    unavailable = {
        "종목코드": "005930",
        "종목명": "삼성전자",
        "시장": "코스피",
        "image_analysis_status": "unavailable",
        "routing": {
            "run_id": "chart-run",
            "request_id": "chart-run:005930.KS",
            "analysis_status": "FAILED_TECHNICAL",
            "primary_provider": "gemini",
            "actual_provider": None,
            "model": None,
            "fallback_used": True,
            "fallback_reason": "authentication",
            "usage": {"total_tokens": None},
            "estimated_cost_usd": None,
        },
    }

    frame = mk.summarize_results([unavailable])
    record = frame.iloc[0].to_dict()

    assert record["image_analysis_status"] == "unavailable"
    assert record["ai_analysis_status"] == "FAILED_TECHNICAL"
    assert record["ai_primary_provider"] == "gemini"
    assert record["ai_fallback_used"] is True
    assert record["ai_fallback_reason"] == "authentication"
    assert record["ai_run_id"] == "chart-run"
    assert record["ai_request_id"] == "chart-run:005930.KS"


@pytest.mark.parametrize(
    "provider_text",
    [
        '```json\n{"signal":"HOLD","confidence":61,"reasons":["steady"]}\n```',
        '{"signal":"HOLD","confidence":61,"reasons":["steady"]',
    ],
)
def test_chart_local_json_repair_happens_before_central_validation(
    mk, monkeypatch, tmp_path, provider_text
):
    image = tmp_path / "chart.png"
    image.write_bytes(b"fake-png")

    def validating_route(request, **_kwargs):
        validation = validate_response(provider_text, request)
        assert validation.valid is True
        return _routing_result(provider_text)

    monkeypatch.setattr(mk, "route_vision", validating_route)

    result = asyncio.run(
        mk.analyze_chart(
            None,
            "005930.KS",
            "삼성전자",
            str(image),
            asyncio.Semaphore(1),
            run_id="chart-repair-run",
            candidate_rank=6,
        )
    )

    assert result is not None
    assert result["signal"] == "HOLD"


def test_openai_fallback_uses_supported_model_default(mk):
    """계정에 없는 gpt-4o-mini 를 하드코딩하면 폴백이 항상 403 이다."""
    assert mk.OPENAI_VISION_MODEL != "gpt-4o-mini"
    assert mk.OPENAI_VISION_MODEL, "폴백 모델명은 환경변수로 교체 가능해야 한다"


def test_displayed_vision_model_uses_same_env_as_central_policy(mk, monkeypatch):
    monkeypatch.setenv("AI_GEMINI_VISION_MODEL", "gemini-vision-explicit")

    reloaded = importlib.reload(mk)

    assert reloaded.MODEL == "gemini-vision-explicit"


def test_buy_candidate_batch_passes_one_run_and_global_candidate_ranks(
    mk, monkeypatch
):
    import importlib
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")
    monkeypatch.setattr(sys.modules["google.genai"], "Client", lambda **_kwargs: object())
    monkeypatch.setattr(mk, "render_chart", lambda *_a, **_k: "chart.png")
    seen = []

    async def fake_analyze(_client, ticker, _name, _path, _semaphore, **kwargs):
        seen.append((ticker, kwargs["run_id"], kwargs["candidate_rank"]))
        return {"signal": "HOLD"}

    monkeypatch.setattr(mk, "analyze_chart", fake_analyze)
    frame = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=60),
        "Open": [1] * 60,
        "High": [2] * 60,
        "Low": [1] * 60,
        "Close": [2] * 60,
        "Volume": [100] * 60,
    })
    batch = [
        (f"{rank:06d}", f"{rank:06d}.KS", f"종목{rank}")
        for rank in range(1, 8)
    ]
    prices = {code: frame for code, _ticker, _name in batch}

    results = asyncio.run(
        script.analyze_batch(
            batch,
            prices,
            concurrency=2,
            run_id="buy-screen-run",
            rank_offset=0,
        )
    )

    assert len(results) == 7  # Gemini primary remains available to every candidate.
    assert {run_id for _ticker, run_id, _rank in seen} == {"buy-screen-run"}
    assert [rank for _ticker, _run_id, rank in seen] == list(range(1, 8))
