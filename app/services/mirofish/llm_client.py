"""MiroFish LLM 클라이언트 — DeepSeek V4 (기본) / Gemini (회귀 토글).

2026-06-10 Gemini 선불 크레딧 소진 (429 RESOURCE_EXHAUSTED) 으로 DeepSeek V4 전환.
- 기본 provider: deepseek (MIROFISH_LLM_PROVIDER=gemini 로 즉시 회귀 가능)
- 기본 모델: deepseek-v4-flash (DEEPSEEK_MODEL 로 오버라이드 — 예: deepseek-v4-pro)
- thinking mode 기본 비활성 (JSON 추출/채팅에 불필요한 지연·비용 제거).
  MIROFISH_LLM_THINKING=1 로 활성화 가능.

사용:
    from app.services.mirofish.llm_client import generate_text
    raw = generate_text(prompt, temperature=0.2, max_tokens=8192, json_mode=True)
    # 실패 시 None — 호출부의 기존 None 처리 흐름 그대로 사용
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL_DEFAULT = 'deepseek-v4-flash'
GEMINI_MODEL_DEFAULT = 'gemini-2.5-flash'


def get_provider() -> str:
    """deepseek (기본) | gemini"""
    return os.getenv('MIROFISH_LLM_PROVIDER', 'deepseek').strip().lower()


def deepseek_model(model_env: str | None = None) -> str:
    """모델 결정 — 컴포넌트별 env 우선, 전역 DEEPSEEK_MODEL, 기본 v4-flash.

    주의: 컴포넌트 env (예: MIROFISH_DEBATE_MODEL) 에 gemini 모델명이 들어있으면 무시.
    """
    if model_env:
        v = os.getenv(model_env, '').strip()
        if v and v.startswith('deepseek'):
            return v
    return os.getenv('DEEPSEEK_MODEL', DEEPSEEK_MODEL_DEFAULT)


def deepseek_extra_body() -> dict[str, Any]:
    """V4 thinking 토글 — 기본 비활성 (속도/비용 우선)."""
    if os.getenv('MIROFISH_LLM_THINKING', '0').strip().lower() in ('1', 'true', 'yes', 'on'):
        return {}  # 기본값 enabled 유지
    return {'thinking': {'type': 'disabled'}}


def get_deepseek_client():
    """OpenAI 호환 DeepSeek 클라이언트. 키 미설정 시 None."""
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning('[llm_client] openai 패키지 미설치')
        return None
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=90)


def _generate_deepseek(prompt: str, *, system: str | None, model_env: str | None,
                       temperature: float, max_tokens: int, json_mode: bool) -> str | None:
    client = get_deepseek_client()
    if client is None:
        logger.warning('[llm_client] DEEPSEEK_API_KEY 미설정')
        return None
    messages: list[dict[str, str]] = []
    if system:
        messages.append({'role': 'system', 'content': system})
    if json_mode and 'json' not in prompt.lower():
        # DeepSeek json_object 모드는 프롬프트에 'json' 언급 필수
        prompt = prompt + '\n\n반드시 유효한 JSON 으로만 응답하세요.'
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
    except Exception as e:
        logger.warning(f'[llm_client] DeepSeek call failed: {type(e).__name__}: {e}')
        return None


def _generate_gemini(prompt: str, *, system: str | None, model_env: str | None,
                     temperature: float, max_tokens: int, json_mode: bool) -> str | None:
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        logger.warning('[llm_client] GEMINI/GOOGLE_API_KEY 미설정')
        return None
    try:
        from google import genai
        from google.genai import types as gt
    except ImportError:
        logger.warning('[llm_client] google-genai 미설치')
        return None
    model = os.getenv(model_env, GEMINI_MODEL_DEFAULT) if model_env else GEMINI_MODEL_DEFAULT
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
            model=model,
            contents=prompt,
            config=gt.GenerateContentConfig(**config_kwargs),
        )
        return (resp.text or '').strip() or None
    except Exception as e:
        logger.warning(f'[llm_client] Gemini call failed: {type(e).__name__}: {e}')
        return None


def generate_text(prompt: str, *, system: str | None = None, model_env: str | None = None,
                  temperature: float = 0.3, max_tokens: int = 4096,
                  json_mode: bool = False) -> str | None:
    """단순 텍스트/JSON 생성 — provider 자동 라우팅.

    Args:
        prompt: 사용자 프롬프트
        system: 시스템 프롬프트 (옵션)
        model_env: 컴포넌트별 모델 오버라이드 env 이름 (예: 'MIROFISH_DEBATE_MODEL')
        temperature / max_tokens: 생성 파라미터
        json_mode: True 면 JSON 강제 출력

    Returns:
        생성 텍스트 또는 실패 시 None (호출부의 기존 None-fallback 흐름 그대로)
    """
    provider = get_provider()
    if provider == 'gemini':
        return _generate_gemini(prompt, system=system, model_env=model_env,
                                temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
    return _generate_deepseek(prompt, system=system, model_env=model_env,
                              temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
