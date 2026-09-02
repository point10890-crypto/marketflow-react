"""Shared MiroFish compatibility wrapper for central AI routing.

The analysis pipeline must keep running when Gemini billing/quota is exhausted.
This module is intentionally small and dependency-light so GraphRAG extraction,
agent debate, CIO verdicts, auto-runners, and chat helpers can all share the
same routing rule.

Text operations use DeepSeek -> OpenAI. Vision uses Gemini -> OpenAI.
Operation policy cannot be reordered by legacy provider-order settings.

Disable a temporarily bad provider with:
    MIROFISH_LLM_DISABLED=gemini
"""

from __future__ import annotations

import logging
import os
import copy
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator
from uuid import uuid4

from app.services.ai_routing.contracts import Operation, ProviderErrorClass, RoutingRequest, TokenUsage
from app.services.ai_routing.providers import (
    AdapterResponse,
    CallableAdapter,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    ProviderCallError,
    classify_exception,
    normalize_gemini_usage,
    normalize_openai_usage,
)
from app.services.ai_routing.router import AIRouter

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL_DEFAULT = 'deepseek-v4-flash'
GEMINI_MODEL_DEFAULT = 'gemini-2.5-flash'
OPENAI_MODEL_DEFAULT = 'gpt-5.5'

ProviderCall = Callable[..., str | None]
SUPPORTED_PROVIDERS = ('deepseek', 'openai', 'gemini')

# Per-request diagnostics.  ContextVar keeps concurrent Flask requests from
# overwriting one another and deliberately stores no prompts, responses, keys,
# URLs with credentials, or exception messages.
_provider_failure: ContextVar[dict[str, str]] = ContextVar(
    'mirofish_llm_provider_failure', default={}
)
_provider_usage: ContextVar[dict[str, TokenUsage]] = ContextVar(
    'mirofish_llm_provider_usage', default={}
)
_provider_error_class: ContextVar[dict[str, ProviderErrorClass]] = ContextVar(
    'mirofish_llm_provider_error_class', default={}
)
_last_generation_metadata: ContextVar[dict[str, Any] | None] = ContextVar(
    'mirofish_llm_generation_metadata', default=None
)
_generation_collector: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    'mirofish_llm_generation_collector', default=None
)
_generation_run_id: ContextVar[str | None] = ContextVar(
    'mirofish_llm_generation_run_id', default=None
)


def _safe_failure(provider: str, reason: str, exc: Exception | None = None) -> None:
    failures = dict(_provider_failure.get())
    failures[provider] = f'{reason}:{type(exc).__name__}' if exc else reason
    _provider_failure.set(failures)


def _safe_error_class(provider: str, error_class: ProviderErrorClass) -> None:
    classes = dict(_provider_error_class.get())
    classes[provider] = error_class
    _provider_error_class.set(classes)


def _clear_provider_attempt_state(provider: str) -> None:
    for context in (_provider_failure, _provider_usage, _provider_error_class):
        values = dict(context.get())
        values.pop(provider, None)
        context.set(values)


def _model_for(provider: str, model_env: str | None) -> str:
    return {
        'deepseek': deepseek_model,
        'openai': openai_model,
        'gemini': gemini_model,
    }[provider](model_env)


def get_last_generation_metadata() -> dict[str, Any] | None:
    """Return a copy of diagnostics for the latest call in this context.

    This is safe to persist with a run artifact: it never contains prompts,
    completions, credentials, or raw provider error messages.
    """
    metadata = _last_generation_metadata.get()
    if metadata is None:
        return None
    return copy.deepcopy(metadata)


def _publish_metadata(metadata: dict[str, Any]) -> None:
    _last_generation_metadata.set(copy.deepcopy(metadata))
    collector = _generation_collector.get()
    if collector is not None:
        collector.append(copy.deepcopy(metadata))


@contextmanager
def collect_generation_metadata(run_id: str | None = None) -> Iterator[list[dict[str, Any]]]:
    """Collect all LLM diagnostics produced inside one engine/run scope.

    Example::

        with collect_generation_metadata() as llm_calls:
            run_deep_analysis(...)
        artifact['llm_calls'] = llm_calls

    Nested and concurrent request scopes remain isolated through ContextVar.
    """
    collected: list[dict[str, Any]] = []
    token = _generation_collector.set(collected)
    run_token = _generation_run_id.set(run_id or str(uuid4()))
    try:
        yield collected
    finally:
        _generation_run_id.reset(run_token)
        _generation_collector.reset(token)


def get_provider() -> str:
    """Return the primary provider name.

    Unknown values fall back to DeepSeek because the current production policy is
    to avoid making Gemini the only live dependency.
    """
    provider = os.getenv('MIROFISH_LLM_PROVIDER', 'deepseek').strip().lower()
    return provider if provider in SUPPORTED_PROVIDERS else 'deepseek'


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, '')
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(',') if part.strip()]


def disabled_providers() -> set[str]:
    return {item for item in _csv_env('MIROFISH_LLM_DISABLED') if item in SUPPORTED_PROVIDERS}


def provider_order() -> list[str]:
    """Return the de-duplicated provider order after env overrides."""
    requested = [item for item in _csv_env('MIROFISH_LLM_PROVIDER_ORDER') if item in SUPPORTED_PROVIDERS]
    primary = get_provider()
    if not requested:
        if primary == 'gemini':
            requested = ['gemini', 'deepseek', 'openai']
        elif primary == 'openai':
            requested = ['openai', 'deepseek', 'gemini']
        else:
            requested = ['deepseek', 'openai', 'gemini']

    order: list[str] = []
    for provider in [*requested, *SUPPORTED_PROVIDERS]:
        if provider not in order:
            order.append(provider)

    disabled = disabled_providers()
    return [provider for provider in order if provider not in disabled]


def deepseek_model(model_env: str | None = None) -> str:
    """Resolve a DeepSeek model.

    Component-specific envs can be passed in, but Gemini/OpenAI model names are
    ignored for this provider.
    """
    if model_env:
        value = os.getenv(model_env, '').strip()
        if value and value.startswith('deepseek'):
            return value
    return os.getenv('DEEPSEEK_MODEL', DEEPSEEK_MODEL_DEFAULT).strip() or DEEPSEEK_MODEL_DEFAULT


def openai_model(model_env: str | None = None) -> str:
    """Resolve an OpenAI fallback model."""
    if model_env:
        value = os.getenv(model_env, '').strip()
        if value and not value.startswith(('deepseek', 'gemini')):
            return value
    return (
        os.getenv('OPENAI_FALLBACK_MODEL')
        or os.getenv('OPENAI_MODEL')
        or OPENAI_MODEL_DEFAULT
    ).strip()


def gemini_model(model_env: str | None = None) -> str:
    """Resolve a Gemini model."""
    if model_env:
        value = os.getenv(model_env, '').strip()
        if value and value.startswith('gemini'):
            return value
    return os.getenv('GEMINI_MODEL', GEMINI_MODEL_DEFAULT).strip() or GEMINI_MODEL_DEFAULT


def deepseek_extra_body() -> dict[str, Any]:
    """Disable thinking by default to keep structured extraction fast and stable."""
    if os.getenv('MIROFISH_LLM_THINKING', '0').strip().lower() in ('1', 'true', 'yes', 'on'):
        return {}
    return {'thinking': {'type': 'disabled'}}


def get_deepseek_client():
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning('[llm_client] openai package is not installed')
        return None
    return OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=90,
        max_retries=0,
    )


def get_openai_client():
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning('[llm_client] openai package is not installed')
        return None
    return OpenAI(api_key=api_key, timeout=90, max_retries=0)


def _json_prompt(prompt: str, suffix: str) -> str:
    if 'json' in prompt.lower():
        return prompt
    return f'{prompt}\n\n{suffix}'


def _generate_deepseek(prompt: str, *, system: str | None, model_env: str | None,
                       temperature: float, max_tokens: int, json_mode: bool,
                       model_override: str | None = None) -> str | None:
    client = get_deepseek_client()
    if client is None:
        logger.warning('[llm_client] DEEPSEEK_API_KEY is not configured')
        _safe_failure('deepseek', 'client_unavailable')
        _safe_error_class('deepseek', ProviderErrorClass.CLIENT_UNAVAILABLE)
        return None
    messages: list[dict[str, str]] = []
    if system:
        messages.append({'role': 'system', 'content': system})
    if json_mode:
        prompt = _json_prompt(prompt, 'Respond only in valid JSON.')
    messages.append({'role': 'user', 'content': prompt})
    kwargs: dict[str, Any] = {
        'model': model_override or deepseek_model(model_env),
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
        'extra_body': deepseek_extra_body(),
    }
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    try:
        resp = client.chat.completions.create(**kwargs)
        usage = dict(_provider_usage.get())
        usage['deepseek'] = normalize_openai_usage(getattr(resp, 'usage', None))
        _provider_usage.set(usage)
        message = resp.choices[0].message
        text = (message.content or '').strip() or None
        if text is None and getattr(message, 'refusal', None):
            _safe_error_class('deepseek', ProviderErrorClass.REFUSAL)
        return text
    except Exception as exc:
        error_class = classify_exception(exc)
        logger.warning('[llm_client] DeepSeek call failed: %s', error_class.value)
        _safe_failure('deepseek', error_class.value)
        _safe_error_class('deepseek', error_class)
        return None


def _generate_openai(prompt: str, *, system: str | None, model_env: str | None,
                     temperature: float, max_tokens: int, json_mode: bool,
                     model_override: str | None = None) -> str | None:
    client = get_openai_client()
    if client is None:
        logger.warning('[llm_client] OPENAI_API_KEY is not configured')
        _safe_failure('openai', 'client_unavailable')
        _safe_error_class('openai', ProviderErrorClass.CLIENT_UNAVAILABLE)
        return None
    messages: list[dict[str, str]] = []
    if system:
        messages.append({'role': 'system', 'content': system})
    if json_mode:
        prompt = _json_prompt(prompt, 'Respond only in valid JSON.')
    messages.append({'role': 'user', 'content': prompt})
    model = model_override or openai_model(model_env)
    kwargs: dict[str, Any] = {'model': model, 'messages': messages}
    if model.startswith(('gpt-5', 'o1', 'o3', 'o4')):
        kwargs['max_completion_tokens'] = max_tokens
    else:
        kwargs['temperature'] = temperature
        kwargs['max_tokens'] = max_tokens
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    try:
        resp = client.chat.completions.create(**kwargs)
        usage = dict(_provider_usage.get())
        usage['openai'] = normalize_openai_usage(getattr(resp, 'usage', None))
        _provider_usage.set(usage)
        message = resp.choices[0].message
        text = (message.content or '').strip() or None
        if text is None and getattr(message, 'refusal', None):
            _safe_error_class('openai', ProviderErrorClass.REFUSAL)
        return text
    except Exception as exc:
        error_class = classify_exception(exc)
        logger.warning('[llm_client] OpenAI call failed: %s', error_class.value)
        _safe_failure('openai', error_class.value)
        _safe_error_class('openai', error_class)
        return None


def _generate_gemini(prompt: str, *, system: str | None, model_env: str | None,
                     temperature: float, max_tokens: int, json_mode: bool,
                     model_override: str | None = None) -> str | None:
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        logger.warning('[llm_client] GEMINI_API_KEY/GOOGLE_API_KEY is not configured')
        _safe_failure('gemini', 'client_unavailable')
        _safe_error_class('gemini', ProviderErrorClass.CLIENT_UNAVAILABLE)
        return None
    try:
        from google import genai
        from google.genai import types as gt
    except ImportError:
        logger.warning('[llm_client] google-genai package is not installed')
        _safe_failure('gemini', 'client_unavailable')
        _safe_error_class('gemini', ProviderErrorClass.CLIENT_UNAVAILABLE)
        return None
    config_kwargs: dict[str, Any] = {
        'temperature': temperature,
        'max_output_tokens': max_tokens,
    }
    if system:
        config_kwargs['system_instruction'] = system
    if json_mode:
        config_kwargs['response_mime_type'] = 'application/json'
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=gt.HttpOptions(
                timeout=int(GEMINI_REQUEST_TIMEOUT_SECONDS * 1_000)
            ),
        )
        resp = client.models.generate_content(
            model=model_override or gemini_model(model_env),
            contents=prompt,
            config=gt.GenerateContentConfig(**config_kwargs),
        )
        usage = dict(_provider_usage.get())
        usage['gemini'] = normalize_gemini_usage(getattr(resp, 'usage_metadata', None))
        _provider_usage.set(usage)
        return (resp.text or '').strip() or None
    except Exception as exc:
        error_class = classify_exception(exc)
        logger.warning('[llm_client] Gemini call failed: %s', error_class.value)
        _safe_failure('gemini', error_class.value)
        _safe_error_class('gemini', error_class)
        return None


def _call_provider(provider: str, prompt: str, *, system: str | None, model_env: str | None,
                   temperature: float, max_tokens: int, json_mode: bool,
                   model_override: str | None = None) -> str | None:
    calls: dict[str, ProviderCall] = {
        'deepseek': _generate_deepseek,
        'openai': _generate_openai,
        'gemini': _generate_gemini,
    }
    return calls[provider](
        prompt,
        system=system,
        model_env=model_env,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
        model_override=model_override,
    )


def _error_class_for_legacy_failure(provider: str) -> ProviderErrorClass:
    typed = _provider_error_class.get().get(provider)
    if typed is not None:
        return typed
    reason = _provider_failure.get().get(provider, '')
    prefix = reason.split(':', 1)[0]
    return {
        'client_unavailable': ProviderErrorClass.CLIENT_UNAVAILABLE,
        'invalid_json': ProviderErrorClass.INVALID_JSON,
        'empty_response': ProviderErrorClass.EMPTY,
    }.get(prefix, ProviderErrorClass.UNKNOWN if prefix else ProviderErrorClass.EMPTY)


def _routing_adapters(model_env: str | None) -> dict[str, CallableAdapter]:
    adapters: dict[str, CallableAdapter] = {}
    disabled = disabled_providers()
    for provider in SUPPORTED_PROVIDERS:
        if provider in disabled:
            continue

        def call(*, request, model, max_output_tokens, _provider=provider):
            _clear_provider_attempt_state(_provider)
            text = _call_provider(
                _provider,
                request.prompt,
                system=request.system,
                model_env=model_env,
                temperature=request.temperature,
                max_tokens=max_output_tokens,
                json_mode=request.json_mode,
                model_override=model,
            )
            if text is None:
                raise ProviderCallError(
                    _error_class_for_legacy_failure(_provider),
                    usage=_provider_usage.get().get(_provider, TokenUsage.unknown()),
                )
            return AdapterResponse(
                text=text,
                usage=_provider_usage.get().get(_provider, TokenUsage.unknown()),
                endpoint='legacy.generate',
            )

        adapters[provider] = CallableAdapter(call, endpoint='legacy.generate')
    return adapters


def _legacy_failure_reason(error_class: ProviderErrorClass | str | None, status: str) -> str | None:
    if status == 'success':
        return None
    value = error_class.value if isinstance(error_class, ProviderErrorClass) else error_class
    if value == ProviderErrorClass.EMPTY.value:
        return 'empty_response'
    return str(value or status)


def _usage_metadata(usage: TokenUsage) -> dict[str, Any]:
    return {
        'input_tokens': usage.input_tokens,
        'cached_input_tokens': usage.cached_input_tokens,
        'uncached_input_tokens': usage.uncached_input_tokens,
        'output_tokens': usage.output_tokens,
        'reasoning_tokens': usage.reasoning_tokens,
        'total_tokens': usage.total_tokens,
        'usage_estimated': usage.usage_estimated,
        'mapping_version': usage.mapping_version,
        'mapping_status': usage.mapping_status,
        'raw_total_tokens': usage.raw_total_tokens,
    }


def generate_text_with_metadata(prompt: str, *, system: str | None = None,
                                model_env: str | None = None,
                                temperature: float = 0.3,
                                max_tokens: int = 4096,
                                json_mode: bool = False,
                                operation: Operation | str | None = None,
                                run_id: str | None = None,
                                request_id: str | None = None,
                                caller_endpoint: str | None = None,
                                ) -> tuple[str | None, dict[str, Any]]:
    """Generate through the central router and publish legacy-safe diagnostics."""
    started = time.perf_counter()
    _provider_failure.set({})
    _provider_usage.set({})
    _provider_error_class.set({})
    selected_operation = Operation(operation) if operation is not None else Operation.BULK_TEXT
    adapters = _routing_adapters(model_env)
    all_providers_disabled = not adapters
    router = AIRouter(adapters=adapters)
    effective_run_id = run_id or _generation_run_id.get()
    request = RoutingRequest(
        operation=selected_operation,
        prompt=prompt,
        system=system,
        run_id=effective_run_id,
        request_id=request_id,
        json_mode=json_mode,
        max_output_tokens=max_tokens,
        caller_endpoint=caller_endpoint or 'mirofish.llm_client',
        temperature=temperature,
    )
    result = (
        router.route_vision(request)
        if selected_operation is Operation.VISION
        else router.route_text(request)
    )
    attempts = [
        {
            'attempt': attempt.attempt_number,
            'provider': attempt.provider,
            'model': attempt.model,
            'success': attempt.status == 'success',
            'failure_reason': _legacy_failure_reason(attempt.error_class, attempt.status),
            'latency_ms': attempt.latency_ms,
            'usage': _usage_metadata(attempt.usage),
            'estimated_cost_usd': (
                str(attempt.estimated_cost_usd) if attempt.estimated_cost_usd is not None else None
            ),
            'pricing_version': attempt.pricing_version,
            'breaker_state': attempt.breaker_state,
            'status': attempt.status,
        }
        for attempt in result.attempts
    ]
    breaker_state = next(
        (attempt['breaker_state'] for attempt in reversed(attempts) if attempt['success']),
        attempts[-1]['breaker_state'] if attempts else 'closed',
    )
    metadata = {
        'provider': result.actual_provider or 'none',
        'model': result.model,
        'success': result.text is not None,
        'json_mode': json_mode,
        'fallback_used': result.fallback_used,
        'fallback_reason': (
            _legacy_failure_reason(result.fallback_reason, 'failed')
            if result.fallback_reason is not None
            else None
        ),
        'retry_reason': (
            _legacy_failure_reason(result.retry_reason, 'failed')
            if result.retry_reason is not None
            else None
        ),
        'failure_reason': (
            None
            if result.text is not None
            else (
                'all_providers_disabled'
                if all_providers_disabled
                else _legacy_failure_reason(result.fallback_reason, 'failed')
            )
        ),
        'attempts': attempts,
        'latency_ms': round((time.perf_counter() - started) * 1000, 2),
        'analysis_status': result.analysis_status.value,
        'primary_provider': result.primary_provider,
        'actual_provider': result.actual_provider,
        'usage': _usage_metadata(result.usage),
        'estimated_cost_usd': (
            str(result.estimated_cost_usd) if result.estimated_cost_usd is not None else None
        ),
        'breaker_state': breaker_state,
        'numeric_validation': result.numeric_validation,
        'evidence_validated': result.evidence_validated,
        'run_id': effective_run_id,
    }
    _publish_metadata(metadata)
    return result.text, metadata


def generate_text_with_provider(prompt: str, *, system: str | None = None,
                                model_env: str | None = None,
                                temperature: float = 0.3,
                                max_tokens: int = 4096,
                                json_mode: bool = False,
                                operation: Operation | str | None = None,
                                run_id: str | None = None,
                                request_id: str | None = None,
                                caller_endpoint: str | None = None) -> tuple[str | None, str]:
    """Generate text and return the provider that succeeded (legacy API)."""
    text, metadata = generate_text_with_metadata(
        prompt, system=system, model_env=model_env, temperature=temperature,
        max_tokens=max_tokens, json_mode=json_mode, operation=operation,
        run_id=run_id, request_id=request_id, caller_endpoint=caller_endpoint,
    )
    return text, str(metadata['provider'])


def generate_text(prompt: str, *, system: str | None = None, model_env: str | None = None,
                  temperature: float = 0.3, max_tokens: int = 4096,
                  json_mode: bool = False, operation: Operation | str | None = None,
                  run_id: str | None = None, request_id: str | None = None,
                  caller_endpoint: str | None = None) -> str | None:
    """Generate plain text or JSON text with automatic provider fallback."""
    text, _provider = generate_text_with_provider(
        prompt,
        system=system,
        model_env=model_env,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
        operation=operation,
        run_id=run_id,
        request_id=request_id,
        caller_endpoint=caller_endpoint,
    )
    return text
