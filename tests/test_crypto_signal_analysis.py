from __future__ import annotations

from decimal import Decimal
from unittest.mock import ANY

from flask import Flask

from app.routes import crypto
from app.services.ai_routing.contracts import (
    AnalysisStatus,
    RoutingResult,
    TokenUsage,
)


def _invoke(payload):
    app = Flask(__name__)
    with app.test_request_context("/signal-analysis", method="POST", json=payload):
        response = crypto.crypto_signal_analysis.__wrapped__()
        if isinstance(response, tuple):
            body, status = response
        else:
            body, status = response, response.status_code
        return body.get_json(), status


def _result(*, provider="deepseek", fallback=False, text="저비용 분석"):
    return RoutingResult(
        text=text,
        analysis_status=(
            AnalysisStatus.SUCCESS_FALLBACK if fallback else AnalysisStatus.SUCCESS_PRIMARY
        ),
        primary_provider="deepseek",
        actual_provider=provider,
        model="deepseek-v4-flash" if provider == "deepseek" else "gpt-5.5",
        fallback_used=fallback,
        fallback_reason="timeout" if fallback else None,
        evidence_validated=True,
        usage=TokenUsage(input_tokens=100, output_tokens=30),
        estimated_cost_usd=Decimal("0.0002"),
    )


def test_crypto_signal_analysis_routes_bulk_text_and_preserves_response(monkeypatch):
    seen = []
    monkeypatch.setattr(crypto, "route_text", lambda request: seen.append(request) or _result())

    body, status = _invoke(
        {
            "symbol": "BTC",
            "score": 81,
            "pivot_high": 100,
            "current_price": 102,
            "vol_ratio": 1.5,
        }
    )

    assert status == 200
    assert body["analysis"] == "저비용 분석"
    assert body["symbol"] == "BTC"
    assert body["model"] == "deepseek-v4-flash"
    assert body["routing"]["actual_provider"] == "deepseek"
    assert body["routing"]["usage"]["total_tokens"] == 130
    request = seen[0]
    assert request.operation.value == "bulk_text"
    assert request.run_id == request.request_id
    assert request.max_output_tokens == 600
    assert request.caller_endpoint == "/api/crypto/signal-analysis"
    assert body["routing"]["run_id"] == request.run_id
    assert body["routing"]["request_id"] == request.request_id


def test_crypto_signal_analysis_exposes_single_openai_fallback_metadata(monkeypatch):
    monkeypatch.setattr(
        crypto,
        "route_text",
        lambda request: _result(provider="openai", fallback=True, text="백업 분석"),
    )

    body, status = _invoke({"symbol": "ETH"})

    assert status == 200
    assert body["analysis"] == "백업 분석"
    assert body["model"] == "gpt-5.5"
    assert body["routing"]["fallback_used"] is True
    assert body["routing"]["fallback_reason"] == "timeout"


def test_crypto_signal_analysis_returns_explicit_degraded_error(monkeypatch):
    monkeypatch.setattr(
        crypto,
        "route_text",
        lambda request: RoutingResult(
            text=None,
            analysis_status=AnalysisStatus.DEGRADED,
            primary_provider="deepseek",
            fallback_used=True,
            fallback_reason="authentication",
        ),
    )

    body, status = _invoke({"symbol": "SOL"})

    assert status == 503
    assert body == {
        "error": "AI analysis unavailable",
        "symbol": "SOL",
        "analysis_status": "DEGRADED",
        "routing": {
            "run_id": ANY,
            "request_id": ANY,
            "analysis_status": "DEGRADED",
            "primary_provider": "deepseek",
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
        },
    }


def test_crypto_signal_analysis_still_requires_symbol(monkeypatch):
    monkeypatch.setattr(crypto, "route_text", lambda request: (_ for _ in ()).throw(AssertionError))

    body, status = _invoke({})

    assert status == 400
    assert body == {"error": "symbol required"}
