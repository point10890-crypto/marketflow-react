# -*- coding: utf-8 -*-
"""KR AI Chart 분석기의 Vision 폴백 회복력 회귀 테스트.

2026-08-15 사고: 삼성전기 1종목의 Gemini JSON 파싱 실패가 전역 래치
(`_gemini_available = False`)를 트립시켜, 이후 모든 종목이 접근 권한도 없는
gpt-4o-mini 로 넘어가 통째로 드롭됐다. 100종목 중 37종목만 분석된 원인.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest


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
            out.append(await mk.analyze_chart(None, ticker, ticker, "chart.png", sem))
        return out

    return asyncio.run(go())


def test_single_gemini_parse_failure_does_not_disable_gemini(mk, monkeypatch):
    """한 종목의 일시적 파싱 실패가 나머지 종목의 Gemini 분석을 막으면 안 된다."""
    seen: list[str] = []

    def fake_gemini(client, ticker, name, image_path):
        seen.append(ticker)
        if ticker == "009150.KS" and seen.count(ticker) <= mk.GEMINI_ITEM_RETRIES + 1:
            return None  # 이 종목만 재시도까지 전부 실패
        return {"signal": "BUY", "confidence": 70}

    def fail_openai(*args, **kwargs):
        return None  # 폴백은 계정 권한 문제로 항상 실패한다고 가정

    monkeypatch.setattr(mk, "_call_gemini", fake_gemini)
    monkeypatch.setattr(mk, "_call_openai_vision", fail_openai)

    results = _run(mk, None, ["005930.KS", "009150.KS", "000660.KS", "035420.KS"])

    assert results[1] is None, "실패한 종목 자체는 드롭되는 게 맞다"
    assert [r["signal"] for r in (results[0], results[2], results[3])] == ["BUY"] * 3, (
        "1건 실패 후 후속 종목이 Gemini 로 정상 분석돼야 한다"
    )


def test_gemini_disabled_only_after_consecutive_failures(mk, monkeypatch):
    """연속 실패가 임계치를 넘으면 그때는 Gemini 호출을 멈춘다(키 소진 대응)."""
    calls: list[str] = []

    monkeypatch.setattr(mk, "_call_gemini",
                        lambda client, ticker, name, path: calls.append(ticker) or None)
    monkeypatch.setattr(mk, "_call_openai_vision",
                        lambda ticker, name, path: {"signal": "HOLD", "confidence": 50})

    tickers = [f"{i:06d}.KS" for i in range(mk.GEMINI_FAILURE_THRESHOLD + 5)]
    results = _run(mk, None, tickers)

    assert all(r is not None for r in results), "폴백이 살아있으면 결과는 나와야 한다"
    attempted = len(set(calls))
    assert attempted == mk.GEMINI_FAILURE_THRESHOLD, (
        f"연속 {mk.GEMINI_FAILURE_THRESHOLD}종목 실패 후 Gemini 시도를 멈춰야 한다 "
        f"(실제 {attempted}종목 시도)"
    )


def test_gemini_success_resets_failure_streak(mk, monkeypatch):
    """중간에 성공하면 연속 실패 카운터가 초기화돼 래치가 트립되지 않는다."""
    state = {"n": 0}

    def flaky(client, ticker, name, image_path):
        state["n"] += 1
        # 실패/성공을 번갈아 — 연속 실패는 절대 임계치에 못 미친다
        return None if state["n"] % 2 else {"signal": "BUY", "confidence": 60}

    monkeypatch.setattr(mk, "_call_gemini", flaky)
    monkeypatch.setattr(mk, "_call_openai_vision", lambda *a, **k: None)

    tickers = [f"{i:06d}.KS" for i in range(mk.GEMINI_FAILURE_THRESHOLD * 3)]
    _run(mk, None, tickers)

    assert mk.gemini_is_available(), "간헐적 실패로 Gemini 가 꺼지면 안 된다"


def test_openai_fallback_uses_supported_model_default(mk):
    """계정에 없는 gpt-4o-mini 를 하드코딩하면 폴백이 항상 403 이다."""
    assert mk.OPENAI_VISION_MODEL != "gpt-4o-mini"
    assert mk.OPENAI_VISION_MODEL, "폴백 모델명은 환경변수로 교체 가능해야 한다"
