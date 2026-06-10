"""Shared MiroFish LLM client with provider fallback.

The analysis pipeline must keep running when Gemini billing/quota is exhausted.
This module is intentionally small and dependency-light so GraphRAG extraction,
agent debate, CIO verdicts, auto-runners, and chat helpers can all share the
same routing rule.

Default order:
    deepseek -> openai -> gemini

If MIROFISH_LLM_PROVIDER=gemini is set for Gemini-first operation, the order is:
    gemini -> deepseek -> openai

Override with MIROFISH_LLM_PROVIDER_ORDER, for example:
    MIROFISH_LLM_PROVIDER_ORDER=gemini,deepseek,openai

Disable a temporarily bad provider with:
    MIROFISH_LLM_DISABLED=gemini
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL_DEFAULT = 'deepseek-v4-flash'
GEMINI_MODEL_DEFAULT = 'gemini-2.5-flash'
OPENAI_MODEL_DEFAULT = 'gpt-4o-mini'

ProviderCall = Callable[..., str | None]
SUPPORTED_PROVIDERS = ('deepseek', 'openai', 'gemini')


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
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=90)


def get_openai_client():
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning('[llm_client] openai package is not installed')
        return None
    return OpenAI(api_key=api_key, timeout=90)


def _json_prompt(prompt: str, suffix: str) -> str:
    if 'json' in prompt.lower():
        return prompt
    return f'{prompt}\n\n{suffix}'


def _generate_deepseek(prompt: str, *, system: str | None, model_env: str | None,
                       temperature: float, max_tokens: int, json_mode: bool) -> str | None:
    client = get_deepseek_client()
    if client is None:
        logger.warning('[llm_client] DEEPSEEK_API_KEY is not configured')
        return None
    messages: list[dict[str, str]] = []
    if system:
        messages.append({'role': 'system', 'content': system})
    if json_mode:
        prompt = _json_prompt(prompt, 'Respond only in valid JSON.')
    messages.append({'role': 'user', 'content': prompt})
    kwargs: dict[str, Any] = {
        'model': deepseek_model(model_env),
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
        'extra_body': deepseek_extra_body(),
    }
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    try:
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or '').strip() or None
    except Exception as exc:
        logger.warning('[llm_client] DeepSeek call failed: %s: %s', type(exc).__name__, exc)
        return None


def _generate_openai(prompt: str, *, system: str | None, model_env: str | None,
                     temperature: float, max_tokens: int, json_mode: bool) -> str | None:
    client = get_openai_client()
    if client is None:
        logger.warning('[llm_client] OPENAI_API_KEY is not configured')
        return None
    messages: list[dict[str, str]] = []
    if system:
        messages.append({'role': 'system', 'content': system})
    if json_mode:
        prompt = _json_prompt(prompt, 'Respond only in valid JSON.')
    messages.append({'role': 'user', 'content': prompt})
    kwargs: dict[str, Any] = {
        'model': openai_model(model_env),
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    try:
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or '').strip() or None
    except Exception as exc:
        logger.warning('[llm_client] OpenAI call failed: %s: %s', type(exc).__name__, exc)
        return None


def _generate_gemini(prompt: str, *, system: str | None, model_env: str | None,
                     temperature: float, max_tokens: int, json_mode: bool) -> str | None:
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        logger.warning('[llm_client] GEMINI_API_KEY/GOOGLE_API_KEY is not configured')
        return None
    try:
        from google import genai
        from google.genai import types as gt
    except ImportError:
        logger.warning('[llm_client] google-genai package is not installed')
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
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=gemini_model(model_env),
            contents=prompt,
            config=gt.GenerateContentConfig(**config_kwargs),
        )
        return (resp.text or '').strip() or None
    except Exception as exc:
        logger.warning('[llm_client] Gemini call failed: %s: %s', type(exc).__name__, exc)
        return None


def _call_provider(provider: str, prompt: str, *, system: str | None, model_env: str | None,
                   temperature: float, max_tokens: int, json_mode: bool) -> str | None:
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
    )


def generate_text_with_provider(prompt: str, *, system: str | None = None,
                                model_env: str | None = None,
                                temperature: float = 0.3,
                                max_tokens: int = 4096,
                                json_mode: bool = False) -> tuple[str | None, str]:
    """Generate text and return the provider that succeeded.

    Returns:
        (text, provider). Provider is 'none' when every configured provider fails.
    """
    order = provider_order()
    if not order:
        logger.warning('[llm_client] every provider is disabled')
        return None, 'none'

    failed: list[str] = []
    for provider in order:
        text = _call_provider(
            provider,
            prompt,
            system=system,
            model_env=model_env,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        if text:
            if failed:
                logger.info('[llm_client] provider fallback succeeded: %s after %s', provider, failed)
            return text, provider
        failed.append(provider)

    logger.warning('[llm_client] all providers failed in order: %s', order)
    return None, 'none'


def generate_text(prompt: str, *, system: str | None = None, model_env: str | None = None,
                  temperature: float = 0.3, max_tokens: int = 4096,
                  json_mode: bool = False) -> str | None:
    """Generate plain text or JSON text with automatic provider fallback."""
    text, _provider = generate_text_with_provider(
        prompt,
        system=system,
        model_env=model_env,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )
    return text
