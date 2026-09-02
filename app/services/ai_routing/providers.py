"""Provider adapter boundary and native token-usage normalization."""

from __future__ import annotations

import os
import base64
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .contracts import ProviderErrorClass, RoutingRequest, TokenUsage, VisionImage


OPENAI_COMPATIBLE_REQUEST_TIMEOUT_SECONDS = 90
GEMINI_REQUEST_TIMEOUT_SECONDS = 90
MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS = max(
    OPENAI_COMPATIBLE_REQUEST_TIMEOUT_SECONDS,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
)


@dataclass(frozen=True)
class AdapterResponse:
    text: str | None
    usage: TokenUsage = field(default_factory=TokenUsage.unknown)
    endpoint: str | None = None


class ProviderCallError(RuntimeError):
    """Secret-free provider failure passed to routing policy."""

    def __init__(
        self,
        error_class: ProviderErrorClass | str,
        *,
        usage: TokenUsage | None = None,
    ) -> None:
        self.error_class = ProviderErrorClass(error_class)
        self.usage = usage or TokenUsage.unknown()
        super().__init__(self.error_class.value)


class ProviderAdapter(Protocol):
    endpoint: str
    request_timeout_seconds: float

    def generate(
        self,
        request: RoutingRequest,
        *,
        model: str,
        max_output_tokens: int,
    ) -> AdapterResponse: ...


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def normalize_openai_usage(raw: Any) -> TokenUsage:
    if raw is None:
        return TokenUsage.unknown()
    prompt_details = _field(raw, "prompt_tokens_details")
    completion_details = _field(raw, "completion_tokens_details")
    return TokenUsage(
        input_tokens=_field(raw, "prompt_tokens"),
        cached_input_tokens=_field(prompt_details, "cached_tokens", 0),
        output_tokens=_field(raw, "completion_tokens"),
        reasoning_tokens=_field(completion_details, "reasoning_tokens", 0),
        raw_total_tokens=_field(raw, "total_tokens"),
        mapping_version="openai-compatible-v1",
    )


def normalize_gemini_usage(raw: Any) -> TokenUsage:
    if raw is None:
        return TokenUsage.unknown()
    candidate_tokens = _field(raw, "candidates_token_count")
    thinking_tokens = _field(raw, "thoughts_token_count", 0) or 0
    billable_output = (
        candidate_tokens + thinking_tokens if candidate_tokens is not None else None
    )
    return TokenUsage(
        input_tokens=_field(raw, "prompt_token_count"),
        cached_input_tokens=_field(raw, "cached_content_token_count", 0),
        output_tokens=billable_output,
        reasoning_tokens=thinking_tokens,
        raw_total_tokens=_field(raw, "total_token_count"),
        mapping_version="gemini-v1",
    )


def classify_exception(exc: Exception) -> ProviderErrorClass:
    if isinstance(exc, ProviderCallError):
        return exc.error_class
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    if status in (401, 403):
        return ProviderErrorClass.AUTHENTICATION
    if status == 402:
        return ProviderErrorClass.INSUFFIC_BALANCE
    if status == 429:
        return ProviderErrorClass.RATE_LIMIT
    if status in (404, 410):
        return ProviderErrorClass.MODEL_UNAVAILABLE
    if isinstance(status, int) and status >= 500:
        return ProviderErrorClass.SERVER_ERROR
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return ProviderErrorClass.TIMEOUT
    if isinstance(exc, ConnectionError) or "connection" in type(exc).__name__.lower():
        return ProviderErrorClass.CONNECTION
    return ProviderErrorClass.UNKNOWN


class CallableAdapter:
    """Adapter for compatibility wrappers and deterministic tests."""

    def __init__(
        self,
        call: Callable[..., Any],
        *,
        endpoint: str,
        request_timeout_seconds: float = MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.call = call
        self.endpoint = endpoint
        self.request_timeout_seconds = request_timeout_seconds

    def generate(self, request: RoutingRequest, *, model: str, max_output_tokens: int) -> AdapterResponse:
        try:
            result = self.call(request=request, model=model, max_output_tokens=max_output_tokens)
        except ProviderCallError:
            raise
        except Exception as exc:
            raise ProviderCallError(classify_exception(exc)) from None
        if isinstance(result, AdapterResponse):
            return result
        return AdapterResponse(text=result, endpoint=self.endpoint)


class OpenAICompatibleAdapter:
    endpoint = "chat.completions"

    def __init__(
        self,
        client_factory: Callable[[], Any],
        *,
        provider: str,
        extra_body: Mapping[str, Any] | None = None,
        request_timeout_seconds: float = OPENAI_COMPATIBLE_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.client_factory = client_factory
        self.provider = provider
        self.extra_body = dict(extra_body or {})
        self.request_timeout_seconds = request_timeout_seconds

    def generate(self, request: RoutingRequest, *, model: str, max_output_tokens: int) -> AdapterResponse:
        client = self.client_factory()
        if client is None:
            raise ProviderCallError(ProviderErrorClass.CLIENT_UNAVAILABLE)
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        prompt = request.prompt
        if request.json_mode and "json" not in prompt.lower():
            prompt = f"{prompt}\n\nRespond only in valid JSON."
        user_content: Any = prompt
        if request.images:
            image_parts: list[Any] = []
            for image in request.images:
                if isinstance(image, VisionImage):
                    encoded = base64.b64encode(image.data).decode("ascii")
                    image_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image.mime_type};base64,{encoded}",
                                "detail": image.detail,
                            },
                        }
                    )
                else:
                    image_parts.append(image)
            user_content = [{"type": "text", "text": prompt}, *image_parts]
        messages.append({"role": "user", "content": user_content})
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if model.startswith(("gpt-5", "o1", "o3", "o4")):
            kwargs["max_completion_tokens"] = max_output_tokens
        else:
            kwargs["temperature"] = request.temperature
            kwargs["max_tokens"] = max_output_tokens
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = client.chat.completions.create(**kwargs)
            text = _field(_field(_field(response, "choices", [None])[0], "message"), "content")
            return AdapterResponse(
                text=text.strip() if isinstance(text, str) else None,
                usage=normalize_openai_usage(_field(response, "usage")),
                endpoint=self.endpoint,
            )
        except Exception as exc:
            raise ProviderCallError(classify_exception(exc)) from None


class GeminiAdapter:
    endpoint = "models.generate_content"

    def __init__(
        self,
        client_factory: Callable[[], Any],
        config_factory: Callable[..., Any],
        *,
        image_part_factory: Callable[..., Any] | None = None,
        request_timeout_seconds: float = GEMINI_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.client_factory = client_factory
        self.config_factory = config_factory
        self.image_part_factory = image_part_factory
        self.request_timeout_seconds = request_timeout_seconds

    def generate(self, request: RoutingRequest, *, model: str, max_output_tokens: int) -> AdapterResponse:
        client = self.client_factory()
        if client is None:
            raise ProviderCallError(ProviderErrorClass.CLIENT_UNAVAILABLE)
        config: dict[str, Any] = {
            "temperature": request.temperature,
            "max_output_tokens": max_output_tokens,
        }
        if request.system:
            config["system_instruction"] = request.system
        if request.json_mode:
            config["response_mime_type"] = "application/json"
        if request.images:
            image_parts: list[Any] = []
            for image in request.images:
                if isinstance(image, VisionImage):
                    if self.image_part_factory is None:
                        raise ProviderCallError(ProviderErrorClass.CLIENT_UNAVAILABLE)
                    image_parts.append(
                        self.image_part_factory(data=image.data, mime_type=image.mime_type)
                    )
                else:
                    image_parts.append(image)
            contents: Any = [request.prompt, *image_parts]
        else:
            contents = request.prompt
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=self.config_factory(**config),
            )
            text = _field(response, "text")
            return AdapterResponse(
                text=text.strip() if isinstance(text, str) else None,
                usage=normalize_gemini_usage(_field(response, "usage_metadata")),
                endpoint=self.endpoint,
            )
        except Exception as exc:
            raise ProviderCallError(classify_exception(exc)) from None


def build_default_adapters() -> dict[str, ProviderAdapter]:
    """Build lazy SDK adapters without making network calls."""
    def openai_client():
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return None
        from openai import OpenAI
        return OpenAI(
            api_key=key,
            timeout=OPENAI_COMPATIBLE_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def deepseek_client():
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            return None
        from openai import OpenAI
        return OpenAI(
            api_key=key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=OPENAI_COMPATIBLE_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def gemini_client():
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            return None
        from google import genai
        from google.genai import types
        return genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                timeout=int(GEMINI_REQUEST_TIMEOUT_SECONDS * 1_000)
            ),
        )

    def gemini_config(**kwargs):
        from google.genai import types
        return types.GenerateContentConfig(**kwargs)

    def gemini_image_part(*, data: bytes, mime_type: str):
        from google.genai import types
        return types.Part.from_bytes(data=data, mime_type=mime_type)

    return {
        "deepseek": OpenAICompatibleAdapter(
            deepseek_client,
            provider="deepseek",
            extra_body={"thinking": {"type": "disabled"}},
        ),
        "openai": OpenAICompatibleAdapter(openai_client, provider="openai"),
        "gemini": GeminiAdapter(
            gemini_client,
            gemini_config,
            image_part_factory=gemini_image_part,
        ),
    }
