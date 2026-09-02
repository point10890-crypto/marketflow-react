"""전사 공용 LLM 폴백 어댑터 — Gemini 소진 시 DeepSeek V4 → OpenAI 자동 대체.

2026-06-10 Gemini 선불 크레딧 소진 (429 RESOURCE_EXHAUSTED) 대응.
브리핑/US 뉴스/크립토 등 분석 파이프라인이 Gemini 1차 실패 후 이 어댑터를 호출.

체인: DeepSeek V4 (최저가) → OpenAI (gpt-4o-mini)
- 각 provider 실패 시 다음으로 자동 진행
- 둘 다 실패 시 (None, 'none') 반환 → 호출부의 기존 템플릿/keyword 폴백 유지

사용:
    from llm_fallback import generate_json_fallback, generate_text_fallback
    data, provider = generate_json_fallback(prompt, max_tokens=8192)
    if data is None:
        ...  # 기존 비-LLM 폴백
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger('llm_fallback')

DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash')
OPENAI_FALLBACK_MODEL = os.getenv('OPENAI_FALLBACK_MODEL', 'gpt-5.5')  # 계정 보유 모델 (gpt-4o 계열 없음)


def _parse_json(text: str) -> dict | None:
    """JSON 파싱 — direct → markdown block → outermost braces."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    md = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if md:
        try:
            return json.loads(md.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r'\{[\s\S]*\}', text)
    if brace:
        try:
            return json.loads(brace.group())
        except json.JSONDecodeError:
            pass
    return None


def _call_deepseek(prompt: str, *, system: str | None, max_tokens: int,
                   temperature: float, json_mode: bool) -> str | None:
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=120)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({'role': 'system', 'content': system})
        if json_mode and 'json' not in prompt.lower():
            prompt = prompt + '\n\n반드시 유효한 JSON 으로만 응답하세요.'
        messages.append({'role': 'user', 'content': prompt})
        kwargs: dict[str, Any] = {
            'model': DEEPSEEK_MODEL,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'extra_body': {'thinking': {'type': 'disabled'}},
        }
        if json_mode:
            kwargs['response_format'] = {'type': 'json_object'}
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or '').strip() or None
    except Exception as e:
        logger.warning(f'[llm_fallback] DeepSeek failed: {type(e).__name__}: {e}')
        return None


def _call_openai(prompt: str, *, system: str | None, max_tokens: int,
                 temperature: float, json_mode: bool) -> str | None:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=120)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({'role': 'system', 'content': system})
        if json_mode and 'json' not in prompt.lower():
            prompt = prompt + '\n\nRespond only in valid JSON.'
        messages.append({'role': 'user', 'content': prompt})
        kwargs: dict[str, Any] = {'model': OPENAI_FALLBACK_MODEL, 'messages': messages}
        # gpt-5/o 계열은 max_tokens·temperature 를 거부한다 (mirofish llm_client 와 동일 분기)
        if OPENAI_FALLBACK_MODEL.startswith(('gpt-5', 'o1', 'o3', 'o4')):
            kwargs['max_completion_tokens'] = max_tokens
        else:
            kwargs['temperature'] = temperature
            kwargs['max_tokens'] = max_tokens
        if json_mode:
            kwargs['response_format'] = {'type': 'json_object'}
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or '').strip() or None
    except Exception as e:
        logger.warning(f'[llm_fallback] OpenAI failed: {type(e).__name__}: {e}')
        return None


def generate_text_fallback(prompt: str, *, system: str | None = None,
                           max_tokens: int = 4096, temperature: float = 0.7) -> tuple[str | None, str]:
    """DeepSeek → OpenAI 텍스트 생성 폴백.

    Returns:
        (생성 텍스트 또는 None, 사용된 provider 'deepseek'|'openai'|'none')
    """
    text = _call_deepseek(prompt, system=system, max_tokens=max_tokens,
                          temperature=temperature, json_mode=False)
    if text:
        return text, 'deepseek'
    text = _call_openai(prompt, system=system, max_tokens=max_tokens,
                        temperature=temperature, json_mode=False)
    if text:
        return text, 'openai'
    return None, 'none'


def generate_json_fallback(prompt: str, *, system: str | None = None,
                           max_tokens: int = 8192, temperature: float = 0.7) -> tuple[dict | None, str]:
    """DeepSeek → OpenAI JSON 생성 폴백.

    Returns:
        (파싱된 dict 또는 None, 사용된 provider 'deepseek'|'openai'|'none')
    """
    raw = _call_deepseek(prompt, system=system, max_tokens=max_tokens,
                         temperature=temperature, json_mode=True)
    data = _parse_json(raw) if raw else None
    if data is not None:
        return data, 'deepseek'

    raw = _call_openai(prompt, system=system, max_tokens=max_tokens,
                       temperature=temperature, json_mode=True)
    data = _parse_json(raw) if raw else None
    if data is not None:
        return data, 'openai'

    return None, 'none'
