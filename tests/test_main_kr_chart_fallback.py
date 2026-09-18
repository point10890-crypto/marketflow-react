# -*- coding: utf-8 -*-
"""KR AI Chart 분석기의 Vision 폴백 회복력 회귀 테스트.

2026-08-15 사고: 삼성전기 1종목의 Gemini JSON 파싱 실패가 전역 래치
(`_gemini_available = False`)를 트립시켜, 이후 모든 종목이 접근 권한도 없는
gpt-4o-mini 로 넘어가 통째로 드롭됐다. 100종목 중 37종목만 분석된 원인.
"""
from __future__ import annotations

import asyncio
import base64
import importlib
import json
import sys
import types
from decimal import Decimal

import pytest

from app.services.ai_routing.contracts import AnalysisStatus, RoutingResult, TokenUsage
from app.services.ai_routing.validation import validate_response


_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_valid_png(path):
    path.write_bytes(_VALID_PNG)
    return path


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
    _write_valid_png(image)
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

    assert seen[0].response_schema["required"] == [
        "signal",
        "confidence",
        "reasons",
        "ma_status",
        "rsi_zone",
        "volume_trend",
    ]
    assert seen[0].thinking_budget == 0
    assert seen[0].max_primary_attempts is None

    request = seen[0]
    assert request.operation.value == "vision"
    assert request.run_id == "chart-run"
    assert request.request_id == "chart-run:005930.KS"
    assert request.max_output_tokens == 768
    assert request.openai_fallback_allowed is True
    assert request.images[0].data == _VALID_PNG
    assert result["signal"] == "BUY"
    assert result["종목코드"] == "005930"
    assert result["종목명"] == "삼성전자"
    assert result["시장"] == "코스피"
    assert result["routing"]["actual_provider"] == "gemini"
    assert result["routing"]["usage"]["total_tokens"] == 30


def test_only_top_five_candidates_are_openai_fallback_eligible(mk, monkeypatch, tmp_path):
    image = tmp_path / "chart.png"
    _write_valid_png(image)
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
    _write_valid_png(image)
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
    _write_valid_png(image)
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
                "raw_total_tokens": None,
                "mapping_version": "normalized-v1",
                "mapping_status": "unverified",
                "complete": False,
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
    ("input_case", "expected_error_class"),
    [
        ("missing", "input_unreadable"),
        ("unreadable", "input_unreadable"),
        ("empty", "input_empty"),
        ("corrupt", "input_corrupt"),
    ],
)
def test_chart_input_failure_returns_zero_usage_technical_artifact_without_provider_call(
    mk, monkeypatch, tmp_path, input_case, expected_error_class
):
    """A bad local chart must fail visibly before any billable provider boundary."""
    image = tmp_path / "chart.png"
    if input_case == "empty":
        image.write_bytes(b"")
    elif input_case == "corrupt":
        image.write_bytes(b"not-a-png")

    if input_case == "unreadable":
        real_open = open

        def unreadable_open(path, *args, **kwargs):
            if str(path) == str(image):
                raise PermissionError("sensitive-provider-detail")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(mk, "open", unreadable_open, raising=False)

    provider_calls = []

    def forbidden_route(request, **_kwargs):
        provider_calls.append(request)
        pytest.fail("route_vision must not run for an invalid local chart")

    monkeypatch.setattr(mk, "route_vision", forbidden_route)

    result = asyncio.run(
        mk.analyze_chart(
            None,
            "005930.KS",
            "삼성전자",
            str(image),
            asyncio.Semaphore(1),
            run_id="chart-input-run",
            candidate_rank=1,
        )
    )

    assert provider_calls == []
    assert result["종목코드"] == "005930"
    assert result["종목명"] == "삼성전자"
    assert result["시장"] == "코스피"
    assert result["image_analysis_status"] == "unavailable"
    routing = result["routing"]
    assert routing["run_id"] == "chart-input-run"
    assert routing["request_id"] == "chart-input-run:005930.KS"
    assert routing["analysis_status"] == "FAILED_TECHNICAL"
    assert routing["error_class"] == expected_error_class
    assert routing["failure_reason"] == expected_error_class
    assert routing["attempt_count"] == 0
    assert routing["attempts"] == []
    assert routing["usage"] == {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "usage_estimated": False,
        "raw_total_tokens": 0,
        "mapping_version": "normalized-v1",
        "mapping_status": "valid",
        "complete": True,
    }
    assert routing["estimated_cost_usd"] == "0"
    assert "sensitive-provider-detail" not in json.dumps(result, ensure_ascii=False)


def test_chart_input_failure_generates_stable_correlation_ids(mk, monkeypatch, tmp_path):
    monkeypatch.setattr(
        mk,
        "route_vision",
        lambda *_args, **_kwargs: pytest.fail(
            "route_vision must not run for a missing local chart"
        ),
    )

    result = asyncio.run(
        mk.analyze_chart(
            None,
            "000660.KS",
            "SK하이닉스",
            str(tmp_path / "missing.png"),
            asyncio.Semaphore(1),
            candidate_rank=2,
        )
    )

    run_id = result["routing"]["run_id"]
    assert run_id.startswith("kr-chart:")
    assert result["routing"]["request_id"] == f"{run_id}:000660.KS"


def test_chart_input_failure_is_preserved_in_csv_projection(mk, monkeypatch, tmp_path):
    monkeypatch.setattr(
        mk,
        "route_vision",
        lambda *_args, **_kwargs: pytest.fail(
            "route_vision must not run for an empty local chart"
        ),
    )
    monkeypatch.setattr(mk.pd.DataFrame, "to_csv", lambda *_args, **_kwargs: None)
    image = tmp_path / "empty.png"
    image.write_bytes(b"")

    artifact = asyncio.run(
        mk.analyze_chart(
            None,
            "005930.KS",
            "삼성전자",
            str(image),
            asyncio.Semaphore(1),
            run_id="chart-input-run",
            candidate_rank=1,
        )
    )
    record = mk.summarize_results([artifact]).iloc[0].to_dict()

    assert record["종목코드"] == "005930"
    assert record["image_analysis_status"] == "unavailable"
    assert record["ai_analysis_status"] == "FAILED_TECHNICAL"
    assert record["ai_error_class"] == "input_empty"
    assert record["ai_failure_reason"] == "input_empty"
    assert record["ai_total_tokens"] == 0
    assert record["ai_usage_complete"] is True
    assert record["ai_estimated_cost_usd"] == "0"


@pytest.mark.parametrize(
    "provider_text",
    [
        '```json\n{"signal":"HOLD","confidence":61,"reasons":["steady"]}\n```',
        '{"signal":"HOLD","confidence":61,"reasons":["steady"]',
        '분석 결과: {"signal":"HOLD","confidence":61,"reasons":["steady"]} 완료',
        "{'signal':'HOLD','confidence':'61%','reasons':'steady'}",
    ],
)
def test_chart_local_json_repair_happens_before_central_validation(
    mk, monkeypatch, tmp_path, provider_text
):
    image = tmp_path / "chart.png"
    _write_valid_png(image)

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
    assert result["confidence"] == 61
    assert result["reasons"] == ["steady"]


def test_decimal_percentage_confidence_is_integer_and_summary_safe(mk, monkeypatch):
    normalized = mk._normalize_chart_json(
        '{"signal":"BUY","confidence":"61.5%","reasons":["steady"]}'
    )
    payload = json.loads(normalized)

    assert payload["confidence"] == 62
    assert isinstance(payload["confidence"], int)
    assert mk._chart_domain_validator(payload) is None

    payload.update({"종목코드": "005930", "종목명": "삼성전자", "시장": "KOSPI"})
    monkeypatch.setattr(mk.pd.DataFrame, "to_csv", lambda *_args, **_kwargs: None)

    summary = mk.summarize_results([payload])

    assert summary.iloc[0]["confidence"] == 62


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


def test_buy_candidate_batch_hard_caps_paid_vision_calls(mk, monkeypatch):
    import importlib
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")
    monkeypatch.setattr(mk, "render_chart", lambda *_a, **_k: "chart.png")
    seen = []

    async def fake_analyze(_client, ticker, _name, _path, _semaphore, **kwargs):
        seen.append((
            ticker,
            kwargs["candidate_rank"],
            kwargs["max_primary_attempts"],
        ))
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
        for rank in range(1, 31)
    ]
    prices = {code: frame for code, _ticker, _name in batch}

    async def run_multiple_batches():
        first = await script.analyze_batch(
            batch[:12],
            prices,
            concurrency=10,
            run_id="hard-cap-run",
            rank_offset=0,
            vision_limit=999,
        )
        second = await script.analyze_batch(
            batch[12:],
            prices,
            concurrency=10,
            run_id="hard-cap-run",
            rank_offset=12,
            vision_limit=999,
        )
        return first + second

    results = asyncio.run(run_multiple_batches())

    assert len(results) == script.MAX_VISION_CALLS == 20
    assert len(seen) == 20
    assert [rank for _ticker, rank, _attempts in seen] == list(range(1, 21))
    assert {attempts for _ticker, _rank, attempts in seen} == {1}


def test_buy_candidate_batch_renders_the_same_sanitized_ohlcv_used_for_ranking(
    mk,
    monkeypatch,
):
    import importlib
    import math
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")
    dates = list(pd.date_range("2026-03-02", periods=60))
    frame = pd.DataFrame({
        "date": dates,
        "Open": [100.0] * 60,
        "High": [101.0] * 60,
        "Low": [99.0] * 60,
        "Close": [100.0] * 60,
        "Volume": [100_000] * 60,
    })
    duplicate = frame.iloc[[20]].copy()
    duplicate["Close"] = 105.0
    invalid_future = frame.iloc[[-1]].copy()
    invalid_future["date"] = pd.Timestamp("2026-05-02")
    invalid_future["Close"] = float("inf")
    raw = pd.concat([frame, duplicate, invalid_future], ignore_index=True)
    captured = []

    def render(clean, *_args, **_kwargs):
        captured.append(clean.copy())
        return "chart.png"

    async def analyze(*_args, **_kwargs):
        return {"signal": "HOLD"}

    monkeypatch.setattr(mk, "render_chart", render)
    monkeypatch.setattr(mk, "analyze_chart", analyze)

    asyncio.run(
        script.analyze_batch(
            [("000010", "000010.KS", "테스트")],
            {"000010": raw},
            concurrency=1,
            run_id="sanitized-chart-run",
        )
    )

    assert len(captured) == 1
    chart = captured[0]
    assert chart.index.is_unique
    assert chart.index.max() == dates[-1]
    assert all(math.isfinite(float(value)) for value in chart["Close"])


def test_deterministic_prefilter_ranks_trend_volume_and_liquidity_before_vision(
    mk,
):
    import importlib
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")

    def frame(closes, volumes):
        return pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=len(closes)),
            "Open": closes,
            "High": [value * 1.01 for value in closes],
            "Low": [value * 0.99 for value in closes],
            "Close": closes,
            "Volume": volumes,
        })

    universe = [
        ("000001", "000001.KS", "하락"),
        ("000002", "000002.KS", "상승거래증가"),
        ("000003", "000003.KS", "횡보"),
    ]
    prices = {
        "000001": frame([200 - i for i in range(80)], [100_000] * 80),
        "000002": frame(
            [100 + i for i in range(80)],
            [100_000] * 60 + [300_000] * 20,
        ),
        "000003": frame([100] * 80, [100_000] * 80),
    }

    ranked = script.rank_prefilter_candidates(universe, prices, limit=2)

    assert [candidate[0] for candidate in ranked] == ["000002", "000003"]


def test_buy_screen_limits_are_hard_bounded(mk):
    import importlib

    script = importlib.import_module("scripts.screen_buy_candidates")

    assert script.bounded_run_limits(target=999, vision_calls=999) == (10, 20)
    assert script.bounded_run_limits(target=8, vision_calls=5) == (5, 5)


def test_prefilter_rejects_stale_invalid_data_and_keeps_market_cap_ties(mk):
    import importlib
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")
    as_of = pd.Timestamp("2026-04-30")

    def frame(*, end=as_of, invalid_latest=False):
        closes = [100.0] * 60
        if invalid_latest:
            closes[-1] = float("nan")
        return pd.DataFrame({
            "date": pd.date_range(end=end, periods=60),
            "Open": closes,
            "High": [101.0] * 60,
            "Low": [99.0] * 60,
            "Close": closes,
            "Volume": [100_000] * 60,
        })

    universe = [
        ("000002", "000002.KS", "시총선두"),
        ("000001", "000001.KS", "시총차순"),
        ("000003", "000003.KS", "지연데이터"),
        ("000004", "000004.KS", "결측데이터"),
    ]
    prices = {
        "000002": frame(),
        "000001": frame(),
        "000003": frame(end=as_of - pd.Timedelta(days=1)),
        "000004": frame(invalid_latest=True),
    }

    ranked = script.rank_prefilter_candidates(
        universe,
        prices,
        limit=20,
        as_of=as_of,
    )

    assert [candidate[0] for candidate in ranked] == ["000002", "000001"]


def test_universe_falls_back_to_local_map_when_live_krx_listing_fails(
    mk,
    monkeypatch,
    tmp_path,
):
    import importlib
    import pandas as pd
    import FinanceDataReader as fdr

    script = importlib.import_module("scripts.screen_buy_candidates")
    ticker_map = tmp_path / "ticker_to_yahoo_map.csv"
    ticker_map.write_text(
        "ticker,market,yahoo_ticker,name\n"
        "000010,KOSPI,000010.KS,첫째\n"
        "000020,KOSDAQ,000020.KQ,둘째\n"
        "000005,KOSPI,000005.KS,우선주\n"
        "000030,KOSDAQ,000030.KQ,테스트스팩\n",
        encoding="utf-8",
    )
    prices = pd.DataFrame({
        "ticker": ["000010", "000020", "000005", "000030"],
        "date": pd.to_datetime(["2026-04-30"] * 4),
        "name": ["로컬첫째", "로컬둘째", "로컬우선", "테스트스팩"],
    })
    monkeypatch.setattr(script, "TICKER_MAP_CSV", ticker_map)

    def fail_listing(_market):
        raise ValueError("empty upstream response")

    monkeypatch.setattr(fdr, "StockListing", fail_listing)

    assert script.build_universe(10, prices=prices) == [
        ("000010", "000010.KS", "로컬첫째"),
        ("000020", "000020.KQ", "로컬둘째"),
    ]


def test_prefilter_as_of_uses_modal_complete_date_not_one_future_outlier(mk):
    import importlib
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")

    def frame(end):
        return pd.DataFrame({
            "date": pd.date_range(end=end, periods=60),
            "Open": [100.0] * 60,
            "High": [101.0] * 60,
            "Low": [99.0] * 60,
            "Close": [100.0] * 60,
            "Volume": [100_000] * 60,
        })

    universe = [
        ("000010", "000010.KS", "정상1"),
        ("000020", "000020.KS", "정상2"),
        ("000030", "000030.KS", "정상3"),
        ("000040", "000040.KS", "미래이상치"),
    ]
    prices = {
        "000010": frame("2026-04-30"),
        "000020": frame("2026-04-30"),
        "000030": frame("2026-04-30"),
        "000040": frame("2026-05-01"),
    }

    assert script.prefilter_as_of(universe, prices) == pd.Timestamp("2026-04-30")


def test_daily_vision_reservation_is_persistent_and_hard_capped(mk, tmp_path):
    import datetime
    import importlib

    script = importlib.import_module("scripts.screen_buy_candidates")
    state_path = tmp_path / "buy_screen_vision_budget.json"
    day = datetime.date(2026, 4, 30)

    assert script.reserve_daily_vision_calls(15, day=day, state_path=state_path) == 15
    assert script.reserve_daily_vision_calls(20, day=day, state_path=state_path) == 5
    assert script.reserve_daily_vision_calls(1, day=day, state_path=state_path) == 0
    assert (
        script.reserve_daily_vision_calls(
            999,
            day=day + datetime.timedelta(days=1),
            state_path=state_path,
        )
        == 20
    )

    lower_state = tmp_path / "buy_screen_vision_budget_lower.json"
    assert (
        script.reserve_daily_vision_calls(
            5,
            day=day,
            state_path=lower_state,
            daily_limit=5,
        )
        == 5
    )
    assert (
        script.reserve_daily_vision_calls(
            5,
            day=day,
            state_path=lower_state,
            daily_limit=5,
        )
        == 0
    )
    assert not script.daily_vision_run_completed(day=day, state_path=lower_state)
    script.mark_daily_vision_run_completed(
        run_id="completed-run",
        day=day,
        state_path=lower_state,
    )
    assert script.daily_vision_run_completed(day=day, state_path=lower_state)
    completed_state = json.loads(lower_state.read_text(encoding="utf-8"))

    assert (
        script.reserve_daily_vision_calls(
            5,
            day=day,
            state_path=lower_state,
            run_id="blocked-rerun",
            daily_limit=5,
        )
        == 0
    )

    rerun_state = json.loads(lower_state.read_text(encoding="utf-8"))
    assert rerun_state["completed_run_id"] == "completed-run"
    assert rerun_state["completed_at"] == completed_state["completed_at"]


def test_non_trading_override_allows_only_latest_trading_day(mk, monkeypatch):
    import datetime
    import importlib
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")
    monkeypatch.setenv("ALLOW_KR_NON_TRADING_RUN", "true")
    sunday = datetime.date(2026, 4, 26)

    assert script.price_data_is_fresh(pd.Timestamp("2026-04-24"), today=sunday)
    assert not script.price_data_is_fresh(pd.Timestamp("2026-04-23"), today=sunday)
    assert not script.price_data_is_fresh(pd.Timestamp("2026-04-27"), today=sunday)


def test_all_vision_failures_preserve_last_known_good_csv(
    mk,
    monkeypatch,
    tmp_path,
):
    import importlib
    import pandas as pd

    script = importlib.import_module("scripts.screen_buy_candidates")
    output = tmp_path / "buy_candidates_kr.csv"
    output.write_text("last-known-good", encoding="utf-8")
    prices = pd.DataFrame({
        "ticker": ["000010"],
        "date": pd.to_datetime(["2026-04-30"]),
        "name": ["테스트"],
    })
    candidate = ("000010", "000010.KS", "테스트")
    monkeypatch.setattr(script, "OUT_CSV", output)
    monkeypatch.setattr(script, "load_prices", lambda: prices)
    monkeypatch.setattr(script, "build_universe", lambda *_a, **_k: [candidate])
    monkeypatch.setattr(script, "prefilter_as_of", lambda *_a, **_k: pd.Timestamp("2026-04-30"))
    monkeypatch.setattr(script, "price_data_is_fresh", lambda *_a, **_k: True)
    monkeypatch.setattr(script, "rank_prefilter_candidates", lambda *_a, **_k: [candidate])
    monkeypatch.setattr(script, "reserve_daily_vision_calls", lambda *_a, **_k: 1)
    monkeypatch.setattr(mk, "reset_vision_health", lambda: None)

    async def unavailable(*_args, **_kwargs):
        return [{"image_analysis_status": "unavailable"}]

    monkeypatch.setattr(script, "analyze_batch", unavailable)
    monkeypatch.setattr(sys, "argv", ["screen_buy_candidates.py", "--no-send"])

    assert script.main() == 1
    assert output.read_text(encoding="utf-8") == "last-known-good"


def test_chart_renderer_is_declared_as_runtime_dependency():
    from pathlib import Path

    requirements = (Path(__file__).parents[1] / "requirements.txt").read_text(
        encoding="utf-8",
    ).lower()

    assert "mplfinance" in requirements


def test_daily_vision_budget_runtime_state_is_gitignored():
    from pathlib import Path

    ignore = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8")

    assert "data/runtime/buy_screen_vision_budget.json" in ignore.splitlines()
