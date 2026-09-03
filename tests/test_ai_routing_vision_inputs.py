from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.services.ai_routing.budget import BudgetLimits, BudgetManager
from app.services.ai_routing.breaker import CircuitBreaker
from app.services.ai_routing.contracts import (
    AnalysisStatus,
    Operation,
    RoutingRequest,
    VisionImage,
)
from app.services.ai_routing.providers import (
    AdapterResponse,
    GeminiAdapter,
    OpenAICompatibleAdapter,
)
from app.services.ai_routing.router import (
    VISION_BUDGET_POOL,
    AIRouter,
    estimate_reservation_input_tokens,
    reserve_openai_fallback,
    vision_budget_limits,
)
from app.services.ai_routing.store import RoutingStore


class _OpenAIClient:
    def __init__(self):
        self.chat = self
        self.completions = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"signal":"HOLD"}'))],
            usage=None,
        )


class _NeverCalledAdapter:
    request_timeout_seconds = 1

    def __init__(self):
        self.calls = 0

    def generate(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("oversized payload must be rejected before dispatch")


class _StaticAdapter:
    request_timeout_seconds = 1

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def generate(self, *_args, **_kwargs):
        self.calls += 1
        return AdapterResponse(text=self.text)


def test_openai_vision_serializes_provider_neutral_image_once_for_gpt5():
    client = _OpenAIClient()
    adapter = OpenAICompatibleAdapter(lambda: client, provider="openai")
    request = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        images=(VisionImage(data=b"png", mime_type="image/png", detail="high"),),
    )

    adapter.generate(request, model="gpt-5.5", max_output_tokens=768)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["max_completion_tokens"] == 768
    assert "max_tokens" not in call
    image = call["messages"][-1]["content"][1]
    assert image["type"] == "image_url"
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


def test_gemini_vision_uses_part_factory_for_same_neutral_image():
    calls = []
    client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: calls.append(kwargs)
            or SimpleNamespace(text='{"signal":"HOLD"}', usage_metadata=None)
        )
    )
    adapter = GeminiAdapter(
        lambda: client,
        lambda **kwargs: kwargs,
        image_part_factory=lambda *, data, mime_type: (mime_type, data),
    )
    request = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        images=(VisionImage(data=b"png", mime_type="image/png"),),
        thinking_budget=0,
        response_schema={
            "type": "OBJECT",
            "properties": {"signal": {"type": "STRING"}},
            "required": ["signal"],
        },
    )

    adapter.generate(request, model="gemini-2.5-flash", max_output_tokens=768)

    assert calls[0]["contents"] == ["analyze", ("image/png", b"png")]
    assert calls[0]["config"]["response_schema"]["required"] == ["signal"]
    assert calls[0]["config"]["thinking_config"] == {"thinking_budget": 0}


def test_gemini_omits_zero_thinking_for_models_that_do_not_support_it():
    calls = []
    client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: calls.append(kwargs)
            or SimpleNamespace(text='{"signal":"HOLD"}', usage_metadata=None)
        )
    )
    adapter = GeminiAdapter(lambda: client, lambda **kwargs: kwargs)
    request = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        thinking_budget=0,
    )

    adapter.generate(request, model="gemini-2.5-pro", max_output_tokens=768)

    assert "thinking_config" not in calls[0]["config"]


def test_vision_reservation_uses_dimensions_not_compressed_byte_length():
    compressed = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        images=(
            VisionImage(
                data=b"x" * 100_000,
                width_px=1_200,
                height_px=800,
            ),
        ),
    )
    less_compressed = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        images=(
            VisionImage(
                data=b"x" * 500_000,
                width_px=1_200,
                height_px=800,
            ),
        ),
    )

    assert estimate_reservation_input_tokens(compressed) == estimate_reservation_input_tokens(
        less_compressed
    )


def test_unknown_vision_dimensions_use_a_conservative_bounded_estimate():
    known = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        images=(
            VisionImage(data=b"x" * 100_000, width_px=1_200, height_px=800),
        ),
    )
    unknown = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        images=(VisionImage(data=b"x" * 100_000),),
    )

    known_tokens = estimate_reservation_input_tokens(known)
    unknown_tokens = estimate_reservation_input_tokens(unknown)

    assert unknown_tokens >= known_tokens
    assert unknown_tokens < 20_000


def test_png_dimensions_are_attached_to_provider_neutral_metadata():
    png_header = (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + (1_200).to_bytes(4, "big")
        + (800).to_bytes(4, "big")
    )

    image = VisionImage(data=png_header)

    assert (image.width_px, image.height_px) == (1_200, 800)


def test_vision_payload_byte_guard_runs_before_budget_or_provider(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_VISION_MAX_PAYLOAD_BYTES", str(64 * 1024))
    store = RoutingStore(tmp_path / "usage.sqlite3")
    manager = BudgetManager(
        store,
        limits=vision_budget_limits(),
        pool=VISION_BUDGET_POOL,
    )
    gemini = _NeverCalledAdapter()
    openai = _NeverCalledAdapter()
    router = AIRouter(
        {"gemini": gemini, "openai": openai},
        store=store,
        breaker=CircuitBreaker(store),
        vision_budget=manager,
    )
    request = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        run_id="oversized",
        request_id="oversized:1",
        images=(
            VisionImage(data=b"x" * 70_000, width_px=1_200, height_px=800),
        ),
    )

    result = router.route_vision(request)

    assert result.analysis_status is AnalysisStatus.FAILED_TECHNICAL
    assert result.fallback_reason == "payload_too_large"
    assert gemini.calls == openai.calls == 0
    assert manager.snapshot("oversized").used_calls == 0


def test_exhausted_openai_vision_pool_does_not_block_gemini_primary(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    manager = BudgetManager(
        store,
        limits=BudgetLimits(
            max_calls=1,
            max_input_tokens=20_000,
            max_output_tokens=2_000,
            low_priority_cutoff=1.0,
        ),
        pool=VISION_BUDGET_POOL,
    )
    assert manager.reserve(
        run_id="shared-run",
        request_id="already-held",
        operation=Operation.VISION,
        input_tokens=1_000,
        output_tokens=768,
    ).approved
    gemini = _StaticAdapter("primary")
    openai = _NeverCalledAdapter()
    router = AIRouter(
        {"gemini": gemini, "openai": openai},
        store=store,
        breaker=CircuitBreaker(store),
        vision_budget=manager,
    )
    request = RoutingRequest(
        operation=Operation.VISION,
        prompt="analyze",
        run_id="shared-run",
        request_id="rank-two",
        images=(VisionImage(data=b"png"),),
        openai_fallback_allowed=True,
    )

    result = router.route_vision(request)

    assert result.analysis_status is AnalysisStatus.SUCCESS_PRIMARY
    assert result.actual_provider == "gemini"
    assert gemini.calls == 1
    assert openai.calls == 0


def test_five_realistic_ranked_chart_reservations_fit_atomic_vision_pool(tmp_path):
    store = RoutingStore(tmp_path / "usage.sqlite3")
    limits = vision_budget_limits()
    manager = BudgetManager(store, limits=limits, pool=VISION_BUDGET_POOL)

    def reserve(rank: int):
        request = RoutingRequest(
            operation=Operation.VISION,
            prompt="analyze a Korean stock chart",
            run_id="chart-run",
            request_id=f"chart-run:{rank}",
            max_output_tokens=768,
            images=(
                VisionImage(
                    data=b"x" * 105_000,
                    width_px=1_200,
                    height_px=800,
                    detail="high",
                ),
            ),
            openai_fallback_allowed=True,
        )
        return reserve_openai_fallback(request, budget=manager)

    with ThreadPoolExecutor(max_workers=5) as executor:
        reservations = list(executor.map(reserve, range(1, 6)))

    assert all(item.approved for item in reservations)
    snapshot = manager.snapshot("chart-run")
    assert snapshot.used_calls == 5
    assert snapshot.used_input_tokens <= limits.max_input_tokens

    sixth = reserve(6)
    assert sixth.approved is False
    assert sixth.reason in {"priority_reserve", "hard_cap"}
