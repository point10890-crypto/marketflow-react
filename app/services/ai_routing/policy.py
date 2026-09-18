"""Immutable operation policies; legacy env cannot reorder providers."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping
from urllib.parse import urlsplit

from .contracts import Operation, RoutePolicy


_MODEL_DEFAULTS = {
    "deepseek_fast": "deepseek-v4-flash",
    "deepseek_decisive": "deepseek-v4-pro",
    "openai": "gpt-5.5",
    "gemini_vision": "gemini-2.5-flash",
}
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


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


def _endpoint_identity(value: object) -> str | None:
    """Return a credential-free canonical HTTP endpoint identity."""
    if (
        not isinstance(value, str)
        or not value
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    if (
        scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    host = host.lower().rstrip(".")
    if not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is not None and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    ):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if not path.startswith("/"):
        return None
    if path != "/":
        path = path.rstrip("/")
    return f"{scheme}://{host}{path}"


def deepseek_vision_endpoint_identity() -> str | None:
    """Configured DeepSeek image endpoint, normalized without credentials."""
    base_url = os.getenv("DEEPSEEK_BASE_URL", _DEEPSEEK_BASE_URL).strip()
    if not base_url:
        base_url = _DEEPSEEK_BASE_URL
    return _endpoint_identity(f"{base_url.rstrip('/')}/chat/completions")


def vision_attestation_is_valid(
    attestation: Mapping[str, object] | None,
    *,
    model: str,
    now: datetime | None = None,
) -> bool:
    """Validate a Task-14-compatible, model-bound Vision health snapshot."""
    if not isinstance(attestation, Mapping) or not model:
        return False
    if (
        attestation.get("provider") != "deepseek"
        or attestation.get("model") != model
        or attestation.get("modality") != "vision"
        or attestation.get("capable") is not True
        or attestation.get("healthy") is not True
    ):
        return False
    expected_endpoint = deepseek_vision_endpoint_identity()
    attested_endpoint = _endpoint_identity(attestation.get("endpoint"))
    if expected_endpoint is None or attested_endpoint != expected_endpoint:
        return False

    ttl_seconds = attestation.get("ttl_seconds")
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or ttl_seconds <= 0
    ):
        return False
    checked_at_raw = attestation.get("checked_at")
    if not isinstance(checked_at_raw, str):
        return False
    try:
        checked_at = datetime.fromisoformat(checked_at_raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        return False

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return False
    age_seconds = (
        current.astimezone(timezone.utc) - checked_at.astimezone(timezone.utc)
    ).total_seconds()
    return 0 <= age_seconds < ttl_seconds


def policy_for(
    operation: Operation | str,
    *,
    vision_attestation: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> RoutePolicy:
    operation = Operation(operation)
    if operation is Operation.BULK_TEXT:
        return RoutePolicy(operation, ("deepseek", "openai"), _models(), 768, "text", 10)
    if operation is Operation.COMPACT_DEBATE:
        return RoutePolicy(operation, ("deepseek", "openai"), _models(), 768, "text", 30)
    if operation is Operation.DECISIVE_TEXT:
        return RoutePolicy(operation, ("deepseek", "openai"), _models(decisive=True), 1200, "text", 100)
    if operation is Operation.VISION:
        models = _models()
        vision_model = models.get("deepseek_vision", "")
        if vision_attestation_is_valid(
            vision_attestation,
            model=vision_model,
            now=now,
        ):
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
