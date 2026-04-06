"""
Gemini 2.5 Flash 고급 기능 래퍼 (DART 심층분석 전용).

이 모듈은 신규 `google-genai` SDK(>=1.60)를 사용합니다.
기존 `engine/llm_analyzer.py` 는 레거시 `google.generativeai` SDK 를 쓰고
있어서 이 파일은 독립적으로 동작합니다.

제공 기능:
  1. Structured Output — JSON 스키마 강제
  2. Code Execution — 샌드박스에서 Python 실행 (DCF 계산)
  3. Grounding Search — Google Search 실시간 검색
  4. URL Context — 웹 URL 직접 분석
  5. 기본 generate — plain text

컨텍스트 캐싱(Context Caching) 은 SDK 가 1M 토큰 이상 인풋만 캐싱하므로
10년 재무제표 정도 사이즈(수 KB)에선 의미 없어 **사용하지 않습니다**.
대신 `data/dart_deep/` 에 결과 JSON 을 24h TTL 로 저장하는 파이프라인-
레벨 캐시로 처리합니다.
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

logger = logging.getLogger("marketflow.gemini_advanced")

DEFAULT_MODEL = "gemini-2.5-flash"


def _get_api_key() -> Optional[str]:
    """GEMINI_API_KEY 우선, 없으면 GOOGLE_API_KEY 폴백."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _client() -> Optional[genai.Client]:
    api_key = _get_api_key()
    if not api_key:
        logger.warning("gemini_advanced: no API key set")
        return None
    return genai.Client(api_key=api_key)


def generate_text(prompt: str, *, model: str = DEFAULT_MODEL, temperature: float = 0.4) -> str:
    """일반 텍스트 생성."""
    client = _client()
    if not client:
        return ""
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        return (resp.text or "").strip()
    except Exception as e:
        logger.warning(f"generate_text failed: {type(e).__name__}: {e}")
        return ""


def generate_structured(
    prompt: str,
    schema: Dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
) -> Optional[Dict[str, Any]]:
    """
    JSON 스키마 강제 생성.

    schema 는 OpenAPI 3 방언(google-genai `response_schema` 포맷). dict 로 넘기면
    SDK 가 알아서 변환합니다.
    """
    client = _client()
    if not client:
        return None
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            return None
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"generate_structured: invalid JSON: {e}")
        return None
    except Exception as e:
        logger.warning(f"generate_structured failed: {type(e).__name__}: {e}")
        return None


def generate_with_code_execution(
    prompt: str, *, model: str = DEFAULT_MODEL, temperature: float = 0.2
) -> Dict[str, Any]:
    """
    Code Execution 툴로 AI 가 Python 코드를 작성/실행/결과 해석.

    Returns:
        {
          "text": 모델의 최종 자연어 답변,
          "executed_code": 실행된 파이썬 코드 (여러 개면 \\n\\n 로 이어붙임),
          "code_output": 샌드박스 stdout,
        }
    """
    client = _client()
    result = {"text": "", "executed_code": "", "code_output": ""}
    if not client:
        return result

    try:
        tool = types.Tool(code_execution=types.ToolCodeExecution())
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                tools=[tool],
            ),
        )

        code_parts: list[str] = []
        output_parts: list[str] = []
        text_parts: list[str] = []

        for cand in resp.candidates or []:
            content = cand.content
            if not content:
                continue
            for part in content.parts or []:
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                if getattr(part, "executable_code", None):
                    code = getattr(part.executable_code, "code", "") or ""
                    if code:
                        code_parts.append(code)
                if getattr(part, "code_execution_result", None):
                    out = getattr(part.code_execution_result, "output", "") or ""
                    if out:
                        output_parts.append(out)

        result["text"] = "\n".join(text_parts).strip()
        result["executed_code"] = "\n\n".join(code_parts).strip()
        result["code_output"] = "\n".join(output_parts).strip()
        return result
    except Exception as e:
        logger.warning(f"generate_with_code_execution failed: {type(e).__name__}: {e}")
        return result


def generate_with_search(
    prompt: str, *, model: str = DEFAULT_MODEL, temperature: float = 0.4
) -> Dict[str, Any]:
    """
    Google Search Grounding.

    Returns:
        {
          "text": 답변,
          "citations": [{"title": ..., "uri": ...}],
        }
    """
    client = _client()
    result = {"text": "", "citations": []}
    if not client:
        return result

    try:
        tool = types.Tool(google_search=types.GoogleSearch())
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                tools=[tool],
            ),
        )

        result["text"] = (resp.text or "").strip()

        citations: list[Dict[str, str]] = []
        for cand in resp.candidates or []:
            gm = getattr(cand, "grounding_metadata", None)
            if not gm:
                continue
            chunks = getattr(gm, "grounding_chunks", None) or []
            for ch in chunks:
                web = getattr(ch, "web", None)
                if not web:
                    continue
                citations.append(
                    {
                        "title": getattr(web, "title", "") or "",
                        "uri": getattr(web, "uri", "") or "",
                    }
                )
        # 중복 제거
        seen = set()
        uniq = []
        for c in citations:
            key = c["uri"]
            if key and key not in seen:
                seen.add(key)
                uniq.append(c)
        result["citations"] = uniq[:10]
        return result
    except Exception as e:
        logger.warning(f"generate_with_search failed: {type(e).__name__}: {e}")
        return result


def analyze_url(
    url: str, prompt: str, *, model: str = DEFAULT_MODEL, temperature: float = 0.3
) -> str:
    """
    URL Context 툴로 원격 페이지를 읽고 요약.

    prompt 에는 URL 을 포함해야 합니다 (예: "다음 링크 요약: {url}").
    """
    client = _client()
    if not client:
        return ""
    try:
        tool = types.Tool(url_context=types.UrlContext())
        full_prompt = f"{prompt}\n\nURL: {url}"
        resp = client.models.generate_content(
            model=model,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                tools=[tool],
            ),
        )
        return (resp.text or "").strip()
    except Exception as e:
        logger.warning(f"analyze_url failed: {type(e).__name__}: {e}")
        return ""
