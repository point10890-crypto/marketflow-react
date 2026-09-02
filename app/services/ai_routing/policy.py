"""Immutable operation policies; legacy env cannot reorder providers."""

from __future__ import annotations

import os

from .contracts import Operation, RoutePolicy


_MODEL_DEFAULTS = {
    "deepseek_fast": "deepseek-v4-flash",
    "deepseek_decisive": "deepseek-v4-pro",
    "openai": "gpt-5.5",
    "gemini_vision": "gemini-2.5-flash",
}


def _env_model(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _models(*, decisive: bool = False) -> dict[str, str]:
    deepseek_env = "AI_DEEPSEEK_DECISIVE_MODEL" if decisive else "AI_DEEPSEEK_FAST_MODEL"
    deepseek_default = (
        _MODEL_DEFAULTS["deepseek_decisive"] if decisive else _MODEL_DEFAULTS["deepseek_fast"]
    )
    models = {
        "deepseek": _env_model(deepseek_env, deepseek_default),
        "openai": _env_model("AI_OPENAI_FALLBACK_MODEL", _MODEL_DEFAULTS["openai"]),
        "gemini": _env_model("AI_GEMINI_VISION_MODEL", _MODEL_DEFAULTS["gemini_vision"]),
    }
    vision_model = os.getenv("AI_DEEPSEEK_VISION_MODEL", "").strip()
    if vision_model:
        models["deepseek_vision"] = vision_model
    return models


def _deepseek_vision_verified() -> bool:
    return (
        os.getenv("AI_DEEPSEEK_VISION_CAPABILITY_VERIFIED") == "1"
        and os.getenv("AI_DEEPSEEK_VISION_HEALTH_VERIFIED") == "1"
        and bool(os.getenv("AI_DEEPSEEK_VISION_MODEL", "").strip())
    )


def policy_for(operation: Operation | str) -> RoutePolicy:
    operation = Operation(operation)
    if operation is Operation.BULK_TEXT:
        return RoutePolicy(operation, ("deepseek", "openai"), _models(), 768, "text", 10)
    if operation is Operation.COMPACT_DEBATE:
        return RoutePolicy(operation, ("deepseek", "openai"), _models(), 768, "text", 30)
    if operation is Operation.DECISIVE_TEXT:
        return RoutePolicy(operation, ("deepseek", "openai"), _models(decisive=True), 1200, "text", 100)
    if operation is Operation.VISION:
        models = _models()
        if _deepseek_vision_verified():
            models["deepseek"] = models["deepseek_vision"]
            providers = ("gemini", "deepseek", "openai")
        else:
            providers = ("gemini", "openai")
        return RoutePolicy(operation, providers, models, 768, "vision", 20)
    if operation is Operation.INTERACTIVE_TEXT:
        return RoutePolicy(operation, ("deepseek", "openai"), _models(), 1200, "text", 60)
    return RoutePolicy(
        operation,
        ("gemini", "deepseek", "openai"),
        _models(),
        1200,
        "text",
        50,
    )
