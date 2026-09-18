"""LLM 프로바이더 체인 — Gemini → DeepSeek → OpenAI → Anthropic (키 있는 것만, 실패 시 다음).

- SDK 없이 `requests` HTTP 호출만 사용 → 의존성 최소, 테스트에서 모킹 용이.
- 모든 프로바이더 실패 시 None 반환 → 호출부는 템플릿 폴백으로 진행.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

from studio.config import Settings

log = logging.getLogger("studio.content.llm")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


def parse_json_text(text: str) -> dict[str, Any] | None:
    """직접 → ```json 블록 → 가장 바깥 중괄호 순으로 JSON 파싱."""
    if not text:
        return None
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    md = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if md:
        try:
            return json.loads(md.group(1))
        except ValueError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except ValueError:
            pass
    return None


class LLMClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None, order: list[str] | None = None) -> None:
        self.settings = settings
        self.http = session or requests.Session()
        self.order = order or settings.llm_order
        self.last_error: str = ""

    # ------------------------------------------------------------------ 상태
    def providers(self) -> list[str]:
        keys = self.settings.llm_keys()
        return [p for p in self.order if keys.get(p)]

    def available(self) -> bool:
        return bool(self.providers())

    # ------------------------------------------------------------------ 생성
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResult | None:
        errors: list[str] = []
        for provider in self.providers():
            try:
                text, model = self._call(provider, prompt, system=system, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature)
                if text and text.strip():
                    return LLMResult(text=text.strip(), provider=provider, model=model)
                errors.append(f"{provider}: 빈 응답")
            except Exception as e:  # 다음 프로바이더로
                msg = f"{provider}: {str(e)[:200]}"
                errors.append(msg)
                log.warning("LLM 실패 — %s", msg)
        self.last_error = " | ".join(errors)
        return None

    def generate_json(self, prompt: str, **kwargs: Any) -> tuple[dict[str, Any] | None, str]:
        kwargs.setdefault("json_mode", True)
        result = self.generate(prompt, **kwargs)
        if result is None:
            return None, "none"
        data = parse_json_text(result.text)
        if data is None:
            log.warning("LLM JSON 파싱 실패 (%s)", result.provider)
            return None, result.provider
        return data, result.provider

    # ------------------------------------------------------------------ 프로바이더
    def _call(self, provider: str, prompt: str, **kw: Any) -> tuple[str, str]:
        s = self.settings
        if provider == "gemini":
            return self._gemini(prompt, **kw), s.gemini_model
        if provider == "deepseek":
            return self._openai_compat(s.deepseek_base_url, s.deepseek_api_key, s.deepseek_model, prompt, provider="deepseek", **kw), s.deepseek_model
        if provider == "openai":
            return self._openai_compat(s.openai_base_url, s.openai_api_key, s.openai_model, prompt, provider="openai", **kw), s.openai_model
        if provider == "anthropic":
            return self._anthropic(prompt, **kw), s.anthropic_model
        raise LLMError(f"알 수 없는 프로바이더: {provider}")

    def _gemini(self, prompt: str, *, system: str | None, json_mode: bool, max_tokens: int, temperature: float) -> str:
        s = self.settings
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        resp = self.http.post(
            GEMINI_URL.format(model=s.gemini_model),
            params={"key": s.gemini_api_key},
            json=body,
            timeout=s.llm_timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"후보 없음: {str(data)[:200]}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)

    def _openai_compat(
        self, base_url: str, api_key: str, model: str, prompt: str, *, provider: str,
        system: str | None, json_mode: bool, max_tokens: int, temperature: float,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if json_mode and "json" not in prompt.lower():
            prompt = prompt + "\n\n반드시 유효한 JSON 객체로만 응답하세요."
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {"model": model, "messages": messages}
        reasoning_family = provider == "openai" and model.lower().startswith(("gpt-5", "o1", "o3", "o4"))
        if reasoning_family:
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        url = base_url.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        resp = self.http.post(
            url + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=self.settings.llm_timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"choices 없음: {str(data)[:200]}")
        return (choices[0].get("message") or {}).get("content") or ""

    def _anthropic(self, prompt: str, *, system: str | None, json_mode: bool, max_tokens: int, temperature: float) -> str:
        s = self.settings
        if json_mode and "json" not in prompt.lower():
            prompt = prompt + "\n\n반드시 유효한 JSON 객체로만 응답하세요."
        body: dict[str, Any] = {
            "model": s.anthropic_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        resp = self.http.post(
            ANTHROPIC_URL,
            headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body,
            timeout=s.llm_timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content") or [] if block.get("type") == "text")
