from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

from app.services.ai_routing.contracts import (
    AnalysisStatus,
    ProviderAttempt,
    ProviderErrorClass,
    RoutingResult,
    TokenUsage,
)
from app.services.ai_routing.contracts import Operation, RoutingRequest
from app.services.ai_routing.router import estimate_reservation_input_tokens
from app.services.mirofish import chat_agent


def _success(envelope, *, provider="deepseek", fallback=False):
    return RoutingResult(
        text=json.dumps(envelope, ensure_ascii=False),
        analysis_status=(
            AnalysisStatus.SUCCESS_FALLBACK if fallback else AnalysisStatus.SUCCESS_PRIMARY
        ),
        primary_provider="deepseek",
        actual_provider=provider,
        model="deepseek-v4-flash" if provider == "deepseek" else "gpt-5.5",
        fallback_used=fallback,
        fallback_reason="timeout" if fallback else None,
        evidence_validated=True,
        usage=TokenUsage(input_tokens=100, output_tokens=20),
        estimated_cost_usd=Decimal("0.001"),
    )


def _tool_call(name="get_market_clock", call_id="call-1"):
    return {
        "content": "",
        "tool_calls": [{"id": call_id, "name": name, "arguments": "{}"}],
    }


class _Router:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    def route_text(self, request):
        self.requests.append(request)
        return self.results.pop(0)


def _attempt(
    provider,
    *,
    status,
    usage,
    cost,
    error=None,
    selected=False,
    number=1,
):
    return ProviderAttempt(
        request_id="chat-run:iteration:1",
        run_id="chat-run",
        provider=provider,
        model="deepseek-v4-flash" if provider == "deepseek" else "gpt-5.5",
        endpoint="chat.completions.tools",
        operation=Operation.INTERACTIVE_TEXT,
        attempt_number=number,
        selected=selected,
        status=status,
        usage=usage,
        estimated_cost_usd=cost,
        error_class=error,
    )


def test_compat_profile_retains_five_iteration_hard_stop(monkeypatch):
    monkeypatch.setenv("MIROFISH_CHAT_PROFILE", "compat")
    monkeypatch.setitem(chat_agent.TOOL_REGISTRY, "get_market_clock", lambda: {"open": True})
    router = _Router([_success(_tool_call(call_id=f"c{i}")) for i in range(5)])

    result = chat_agent.run_chat("시장 상태", [], router=router, run_id="chat-run")

    assert result["iterations"] == 5
    assert len(router.requests) == 5
    assert result["method"] == "llm_error"
    assert result["analysis_status"] == "DEGRADED"
    assert result["error_class"] == "iteration_limit"


def test_compact_profile_defaults_to_two_and_never_exceeds_three(monkeypatch):
    monkeypatch.setenv("MIROFISH_CHAT_PROFILE", "compact")
    monkeypatch.setenv("MIROFISH_CHAT_COMPACT_ITERATIONS", "99")
    monkeypatch.setitem(chat_agent.TOOL_REGISTRY, "get_market_clock", lambda: {"open": True})
    router = _Router([_success(_tool_call(call_id=f"c{i}")) for i in range(3)])

    result = chat_agent.run_chat("시장 상태", [], router=router, run_id="chat-run")

    assert result["iterations"] == 3
    assert len(router.requests) == 3
    assert result["method"] == "llm_error"


@__import__("pytest").mark.parametrize("profile", ["compat", "compact"])
def test_max_bound_chat_envelope_stays_below_preflight_and_reaches_router(profile):
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": "이전대화" * 600,
        }
        for index in range(10)
    ]
    router = _Router([_success({"content": "완료", "tool_calls": []})])

    result = chat_agent.run_chat(
        "최신질문" * 2_000,
        history,
        profile=profile,
        router=router,
        run_id=f"max-{profile}",
    )

    assert result["method"] == "llm"
    assert len(router.requests) == 1
    assert estimate_reservation_input_tokens(router.requests[0]) < 30_000
    prompt = json.loads(router.requests[0].prompt)
    assert any(message["role"] == "user" for message in prompt["messages"])


def test_later_iteration_envelope_is_bounded_and_keeps_native_tool_pair(monkeypatch):
    monkeypatch.setitem(
        chat_agent.TOOL_REGISTRY,
        "get_market_clock",
        lambda: {"blob": "근거" * 10_000},
    )
    router = _Router([
        _success(_tool_call(call_id="pair-1")),
        _success({"content": "완료", "tool_calls": []}),
    ])

    result = chat_agent.run_chat(
        "최신질문" * 2_000,
        [{"role": "assistant", "content": "과거" * 2_000}] * 10,
        profile="compat",
        router=router,
        run_id="pair-run",
    )

    assert result["method"] == "llm"
    assert estimate_reservation_input_tokens(router.requests[1]) < 30_000
    messages = json.loads(router.requests[1].prompt)["messages"]
    assistant_ids = {
        call["id"]
        for message in messages
        if message["role"] == "assistant"
        for call in message.get("tool_calls", [])
    }
    tool_ids = {
        message["tool_call_id"] for message in messages if message["role"] == "tool"
    }
    assert assistant_ids == tool_ids == {"pair-1"}


def test_under_budget_tool_evidence_keeps_critical_level_numbers(monkeypatch):
    monkeypatch.setitem(
        chat_agent.TOOL_REGISTRY,
        "analyze_levels",
        lambda **_kwargs: {
            "data_quality": {"notes": "x" * 320},
            "entry_price": 70000,
            "stop_price": 68000,
            "target_price": 75000,
        },
    )
    router = _Router([
        _success(_tool_call(name="analyze_levels", call_id="levels-1")),
        _success({"content": "완료", "tool_calls": []}),
    ])

    result = chat_agent.run_chat(
        "가격대", [], router=router, run_id="levels-run"
    )

    assert result["method"] == "llm"
    assert len(router.requests[1].prompt.encode("utf-8")) < 28_000
    messages = json.loads(router.requests[1].prompt)["messages"]
    tool_message = next(message for message in messages if message["role"] == "tool")
    summary = json.loads(tool_message["content"])["summary"]
    assert '"entry_price": 70000' in summary
    assert '"target_price": 75000' in summary
    assert '"stop_price": 68000' in summary


def test_compact_tool_evidence_is_bounded_and_addressed_by_evidence_id(monkeypatch):
    monkeypatch.setenv("MIROFISH_CHAT_PROFILE", "compact")
    monkeypatch.delenv("MIROFISH_CHAT_COMPACT_ITERATIONS", raising=False)
    huge = "SENSITIVE-LIKE-RAW-" + ("x" * 9_000)
    monkeypatch.setitem(chat_agent.TOOL_REGISTRY, "get_market_clock", lambda: {"blob": huge})
    router = _Router([
        _success(_tool_call()),
        _success({"content": "요약 완료", "tool_calls": []}),
    ])

    result = chat_agent.run_chat("시장 상태", [], router=router, run_id="chat-run")

    second_prompt = json.loads(router.requests[1].prompt)
    tool_message = next(msg for msg in second_prompt["messages"] if msg["role"] == "tool")
    evidence = json.loads(tool_message["content"])
    assert evidence["evidence_id"].startswith("tool:")
    assert evidence["truncated"] is True
    assert len(evidence["summary"]) <= 600
    assert huge not in router.requests[1].prompt
    assert result["tool_calls"][0]["evidence_id"] == evidence["evidence_id"]


def test_chat_reports_openai_as_one_fallback_without_hiding_usage(monkeypatch):
    monkeypatch.setenv("MIROFISH_CHAT_PROFILE", "compact")
    router = _Router([
        _success(
            {"content": "백업 답변", "tool_calls": []},
            provider="openai",
            fallback=True,
        )
    ])

    result = chat_agent.run_chat("질문", [], router=router, run_id="chat-run")

    assert result["method"] == "llm"
    assert result["analysis_status"] == "SUCCESS_FALLBACK"
    assert result["routing"]["actual_provider"] == "openai"
    assert result["routing"]["fallback_used"] is True
    assert result["routing"]["usage"]["total_tokens"] == 120
    assert result["routing"]["run_id"] == "chat-run"


def test_chat_usage_and_cost_include_every_physical_attempt(monkeypatch):
    attempts = (
        _attempt(
            "deepseek",
            status="failed",
            usage=TokenUsage(input_tokens=80, output_tokens=4),
            cost=Decimal("0.001"),
            error=ProviderErrorClass.INVALID_JSON,
        ),
        _attempt(
            "openai",
            status="success",
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            cost=Decimal("0.003"),
            selected=True,
            number=2,
        ),
    )
    routed = _success(
        {"content": "백업 답변", "tool_calls": []},
        provider="openai",
        fallback=True,
    )
    routed = RoutingResult(**{**routed.__dict__, "attempts": attempts})

    result = chat_agent.run_chat(
        "질문", [], router=_Router([routed]), run_id="chat-run"
    )

    usage = result["routing"]["usage"]
    assert usage["input_tokens"] == 180
    assert usage["output_tokens"] == 24
    assert usage["total_tokens"] == 204
    assert usage["complete"] is True
    assert result["routing"]["estimated_cost_usd"] == "0.004"
    assert result["routing"]["cost_complete"] is True
    assert len(result["routing"]["calls"][0]["attempts"]) == 2


def test_chat_usage_marks_unknown_failed_attempt_incomplete(monkeypatch):
    attempts = (
        _attempt(
            "deepseek",
            status="failed",
            usage=TokenUsage.unknown(),
            cost=None,
            error=ProviderErrorClass.TIMEOUT,
        ),
        _attempt(
            "openai",
            status="success",
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            cost=Decimal("0.003"),
            selected=True,
            number=2,
        ),
    )
    routed = _success(
        {"content": "백업 답변", "tool_calls": []},
        provider="openai",
        fallback=True,
    )
    routed = RoutingResult(**{**routed.__dict__, "attempts": attempts})

    result = chat_agent.run_chat(
        "질문", [], router=_Router([routed]), run_id="chat-run"
    )

    assert result["routing"]["usage"]["complete"] is False
    assert result["routing"]["usage"]["input_tokens"] is None
    assert result["routing"]["usage"]["known_input_tokens"] == 100
    assert result["routing"]["estimated_cost_usd"] is None
    assert result["routing"]["known_estimated_cost_usd"] == "0.003"
    assert result["routing"]["cost_complete"] is False


def test_chat_metadata_retains_earlier_iteration_fallback(monkeypatch):
    monkeypatch.setenv("MIROFISH_CHAT_PROFILE", "compact")
    monkeypatch.setitem(chat_agent.TOOL_REGISTRY, "get_market_clock", lambda: {"open": True})
    router = _Router([
        _success(_tool_call(), provider="openai", fallback=True),
        _success({"content": "완료", "tool_calls": []}),
    ])

    result = chat_agent.run_chat("질문", [], router=router, run_id="chat-run")

    assert result["routing"]["fallback_used"] is True
    assert result["routing"]["fallback_reason"] == "timeout"
    assert [call["actual_provider"] for call in result["routing"]["calls"]] == [
        "openai",
        "deepseek",
    ]
    assert result["routing"]["usage"]["total_tokens"] == 240
    assert result["routing"]["estimated_cost_usd"] == "0.002"
    assert [call["usage"]["total_tokens"] for call in result["routing"]["calls"]] == [
        120,
        120,
    ]
    assert [call["estimated_cost_usd"] for call in result["routing"]["calls"]] == [
        "0.001",
        "0.001",
    ]
    assert router.requests[0].openai_fallback_allowed is True
    assert router.requests[1].openai_fallback_allowed is False


def test_chat_provider_exhaustion_is_explicit_error(monkeypatch):
    router = _Router([
        RoutingResult(
            text=None,
            analysis_status=AnalysisStatus.DEGRADED,
            primary_provider="deepseek",
            fallback_used=True,
            fallback_reason="authentication",
        )
    ])

    result = chat_agent.run_chat("질문", [], router=router, run_id="chat-run")

    assert result["method"] == "llm_error"
    assert result["analysis_status"] == "DEGRADED"
    assert result["error_class"] == "authentication"
    assert "정상" not in result["reply"]


def test_terminal_provider_error_is_distinct_from_fallback_reason(monkeypatch):
    attempts = (
        _attempt(
            "deepseek",
            status="failed",
            usage=TokenUsage.unknown(),
            cost=None,
            error=ProviderErrorClass.AUTHENTICATION,
        ),
        _attempt(
            "openai",
            status="failed",
            usage=TokenUsage.unknown(),
            cost=None,
            error=ProviderErrorClass.RATE_LIMIT,
            number=2,
        ),
    )
    failed = RoutingResult(
        text=None,
        analysis_status=AnalysisStatus.FAILED_TECHNICAL,
        primary_provider="deepseek",
        fallback_used=True,
        fallback_reason=ProviderErrorClass.AUTHENTICATION,
        attempts=attempts,
    )

    result = chat_agent.run_chat(
        "질문", [], router=_Router([failed]), run_id="chat-run"
    )

    assert result["error_class"] == "rate_limit"
    assert result["routing"]["fallback_reason"] == "authentication"
    assert result["routing"]["terminal_error"] == "rate_limit"


def test_all_chat_iterations_share_run_and_have_distinct_request_ids(monkeypatch):
    monkeypatch.setenv("MIROFISH_CHAT_PROFILE", "compact")
    monkeypatch.setitem(chat_agent.TOOL_REGISTRY, "get_market_clock", lambda: {"open": True})
    router = _Router([
        _success(_tool_call()),
        _success({"content": "완료", "tool_calls": []}),
    ])

    chat_agent.run_chat("시장 상태", [], router=router, run_id="fixed-run")

    assert {request.run_id for request in router.requests} == {"fixed-run"}
    assert [request.request_id for request in router.requests] == [
        "fixed-run:iteration:1",
        "fixed-run:iteration:2",
    ]


def test_tool_failure_returns_explicit_degraded_method(monkeypatch):
    router = _Router([
        _success(_tool_call(name="missing_tool")),
        _success({"content": "도구 없이 답변", "tool_calls": []}),
    ])

    result = chat_agent.run_chat("질문", [], router=router, run_id="chat-run")

    assert result["method"] == "llm_degraded"
    assert result["analysis_status"] == "DEGRADED"
    assert result["error_class"] == "tool_failure"
    assert result["routing"]["tool_error_count"] == 1


def test_malformed_tool_arguments_never_execute_tool(monkeypatch):
    executions = []
    monkeypatch.setitem(
        chat_agent.TOOL_REGISTRY,
        "get_market_clock",
        lambda **kwargs: executions.append(kwargs) or {"open": True},
    )
    malformed = {
        "content": "",
        "tool_calls": [{
            "id": "call-1",
            "name": "get_market_clock",
            "arguments": "{not-json",
        }],
    }
    router = _Router([
        _success(malformed),
        _success({"content": "완료", "tool_calls": []}),
    ])

    result = chat_agent.run_chat("질문", [], router=router, run_id="chat-run")

    assert executions == []
    assert result["method"] == "llm_degraded"
    assert result["tool_calls"][0]["argument_status"] == "invalid"


def test_default_chat_router_uses_independent_budget_pool():
    router = chat_agent._build_chat_router()

    assert router.budget.pool == "chat"
    assert set(router.adapters) == {"deepseek", "openai"}


def test_early_paths_include_stable_run_and_error_metadata(monkeypatch):
    empty = chat_agent.run_chat("", [], run_id="fixed-empty")

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    unconfigured = chat_agent.run_chat("질문", [], run_id="fixed-unconfigured")

    assert empty["analysis_status"] == "DEGRADED"
    assert empty["error_class"] == "empty_input"
    assert empty["routing"]["run_id"] == "fixed-empty"
    assert empty["routing"]["calls"] == []
    assert unconfigured["analysis_status"] == "DEGRADED"
    assert unconfigured["error_class"] == "client_unavailable"
    assert unconfigured["routing"]["run_id"] == "fixed-unconfigured"
    assert unconfigured["routing"]["calls"] == []


def test_tool_adapter_preserves_native_messages_and_uses_one_gpt5_call():
    calls = []
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(
                        content="완료",
                        tool_calls=[],
                    ))],
                    usage=None,
                )
            )
        )
    )
    adapter = chat_agent._ChatToolsAdapter("openai", lambda: client)
    messages = [{"role": "user", "content": "질문"}]
    tools = [{"type": "function", "function": {"name": "get_market_clock"}}]

    response = adapter.generate(
        RoutingRequest(
            operation=Operation.INTERACTIVE_TEXT,
            prompt=json.dumps({"messages": messages, "tools": tools}),
        ),
        model="gpt-5.5",
        max_output_tokens=1200,
    )

    assert len(calls) == 1
    assert calls[0]["messages"] == messages
    assert calls[0]["tools"] == tools
    assert calls[0]["max_completion_tokens"] == 1200
    assert "max_tokens" not in calls[0]
    assert json.loads(response.text) == {"content": "완료", "tool_calls": []}


def test_tool_helpers_do_not_return_raw_exception_text(monkeypatch):
    secret = "sk-sensitive-value"
    monkeypatch.setattr(chat_agent.workflow, "read_latest_workflow", lambda: {"id": "x"})
    monkeypatch.setattr(
        chat_agent.workflow,
        "build_share_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    monkeypatch.setattr(
        chat_agent.live_data,
        "resolve_target",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    outputs = [
        chat_agent._get_top3_summary(),
        chat_agent._get_workflow_share(),
        chat_agent._resolve_target("005930"),
    ]

    assert all(secret not in json.dumps(output) for output in outputs)
    assert all(output["error"] == "tool_failed: RuntimeError" for output in outputs)


def test_nested_tool_errors_are_sanitized_before_model_and_client_preview(monkeypatch):
    secret = "https://kis.test/fail?token=sk-sensitive-path-C:/private/key.txt"
    monkeypatch.setitem(
        chat_agent.TOOL_REGISTRY,
        "analyze_levels",
        lambda **_kwargs: {
            "status": "fallback",
            "levels": {"entry": 70000},
            "data_quality": {"kis_error": secret},
            "fallback_from_kis_error": secret,
        },
    )
    router = _Router([
        _success(_tool_call(name="analyze_levels")),
        _success({"content": "완료", "tool_calls": []}),
    ])

    result = chat_agent.run_chat(
        "삼성전자 가격대", [], router=router, run_id="chat-sanitize"
    )

    assert secret not in router.requests[1].prompt
    assert secret not in json.dumps(result, ensure_ascii=False)
    assert "upstream_error" in router.requests[1].prompt


def test_tool_sanitizer_preserves_healthy_falsey_error_metadata():
    healthy = {
        "status": "ok",
        "data_quality": {"kis_error": None, "error_count": 0},
        "fallback_from_kis_error": False,
    }

    sanitized = chat_agent._sanitize_tool_result(healthy)

    assert sanitized == healthy


def test_empty_chat_envelope_is_rejected_so_router_can_fallback():
    error = chat_agent._chat_envelope_validator({"content": "", "tool_calls": []})

    assert error is chat_agent.ProviderErrorClass.EMPTY
