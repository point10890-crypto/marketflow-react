"""
🤖 LLM 뉴스 분석 시스템 (Gemini Grounding + Claude + OpenAI + xAI Grok)
Gemini Google Search Grounding으로 실시간 웹 검색+분석을 단일 호출로 수행합니다.
Multi-AI 폴백 체인과 독립 종목 선별 기능을 포함합니다.
"""

import os
import json
import re
import asyncio
import logging
import httpx
import hashlib
from google import genai
from google.genai import types as genai_types
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from app.services.ai_routing.contracts import (
    Operation,
    ProviderErrorClass,
    RoutingRequest,
    RoutingResult,
)
from app.services.ai_routing.router import route_text
from app.services.ai_routing.providers import normalize_gemini_usage

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


def _enum_value(value):
    return getattr(value, "value", value)


def _routing_metadata(
    result: RoutingResult,
    *,
    run_id: str | None = None,
    request_id: str | None = None,
) -> Dict:
    usage = result.usage
    first_attempt = result.attempts[0] if result.attempts else None
    resolved_run_id = run_id or (
        first_attempt.run_id if first_attempt is not None else None
    )
    resolved_request_id = request_id or (
        first_attempt.request_id if first_attempt is not None else None
    )
    return {
        "run_id": resolved_run_id,
        "request_id": resolved_request_id,
        "analysis_status": result.analysis_status.value,
        "primary_provider": result.primary_provider,
        "actual_provider": result.actual_provider,
        "model": result.model,
        "fallback_used": result.fallback_used,
        "fallback_reason": _enum_value(result.fallback_reason),
        "retry_reason": _enum_value(result.retry_reason),
        "usage": {
            "input_tokens": usage.input_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "output_tokens": usage.output_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "total_tokens": usage.total_tokens,
            "usage_estimated": usage.usage_estimated,
        },
        "estimated_cost_usd": (
            str(result.estimated_cost_usd)
            if isinstance(result.estimated_cost_usd, Decimal)
            else result.estimated_cost_usd
        ),
        "attempt_count": len(result.attempts),
    }


def _news_response_validator(payload) -> ProviderErrorClass | None:
    if not isinstance(payload, dict):
        return ProviderErrorClass.INVALID_JSON
    score = payload.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 3:
        return ProviderErrorClass.INVALID_JSON
    if not isinstance(payload.get("reason"), str):
        return ProviderErrorClass.INVALID_JSON
    if not isinstance(payload.get("themes"), list):
        return ProviderErrorClass.INVALID_JSON
    return None


def _parse_json_object(text: str | None) -> Dict | None:
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _valid_http_url(value: object) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
    except (TypeError, ValueError):
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _fresh_attributed_news_record(
    record: Dict,
    *,
    now: datetime | None = None,
) -> bool:
    """Require source, citation, and recent timestamp on the same record."""
    source = str(record.get("source") or "").strip()
    if source.casefold() in {"", "unknown", "none", "n/a", "na", "미상", "알 수 없음"}:
        return False
    if not _valid_http_url(record.get("url")):
        return False
    published_text = str(record.get("published_at") or "").strip()
    if not published_text:
        return False
    try:
        published = datetime.fromisoformat(published_text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        # Korean news collectors yield naive local timestamps.  Interpret
        # them as KST before comparing in UTC; treating them as UTC can make a
        # current article appear to be in the future.
        published = published.replace(tzinfo=_KST)
    reference = now or datetime.now(timezone.utc)
    age = reference.astimezone(timezone.utc) - published.astimezone(timezone.utc)
    return -timedelta(hours=1) <= age <= timedelta(days=7)

# 환경변수 로드
load_dotenv()

# API 상태 추적 (Rate Limit 관리)
API_STATUS = {
    'gemini_grounding': {'available': True, 'last_error': None, 'error_count': 0},
    'gemini': {'available': True, 'last_error': None, 'error_count': 0},
    'deepseek': {'available': True, 'last_error': None, 'error_count': 0},
    'claude': {'available': True, 'last_error': None, 'error_count': 0},
    'openai': {'available': True, 'last_error': None, 'error_count': 0},
    'xai': {'available': True, 'last_error': None, 'error_count': 0}
}

# Lock to protect API_STATUS mutations from async coroutines
_api_status_lock = asyncio.Lock()

async def _mark_unavailable(api_name: str, error_type: str = 'Rate Limit'):
    """Mark an API as unavailable with lock protection"""
    async with _api_status_lock:
        API_STATUS[api_name]['available'] = False
        API_STATUS[api_name]['last_error'] = error_type
        API_STATUS[api_name]['error_count'] += 1

def reset_api_status():
    """API 상태 초기화 (세션 시작 시 호출)"""
    global API_STATUS
    for key in API_STATUS:
        API_STATUS[key] = {'available': True, 'last_error': None, 'error_count': 0}

class GeminiGroundingClient:
    """Gemini + Google Search Grounding (REST API) — 실시간 검색+분석 통합"""

    # gemini-2.0-flash 는 2026-08 시점에 폐기됐다 (HTTP 404 "no longer available").
    # 하드코딩돼 있어서 전 종목의 실시간 검색 분석이 조용히 DeepSeek 폴백으로
    # 넘어갔다 — 폴백에는 웹 검색이 없으므로 결과가 아니라 근거가 바뀐 것이다.
    # 다음 폐기 때 코드 수정 없이 넘기도록 env 로 뺀다.
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = os.getenv("GEMINI_GROUNDING_MODEL", self.DEFAULT_MODEL)
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

    async def search_and_analyze(self, stock_name: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        """Google Search Grounding으로 실시간 뉴스 검색 + 분석을 단일 호출로 수행"""
        if not self.api_key:
            return {"score": 0, "reason": "No Gemini API Key", "themes": [], "source": "none"}

        if not API_STATUS['gemini_grounding']['available']:
            return {"score": 0, "reason": f"Rate Limited: {API_STATUS['gemini_grounding']['last_error']}", "themes": [], "source": "none"}

        trad_text = ""
        if traditional_news:
            for i, item in enumerate(traditional_news[:5], 1):
                trad_text += f"[{i}] {item.get('title')} - {item.get('summary', '')[:100]}\n"

        dart_section = ""
        if dart_text:
            dart_section = f"\n[공식 공시 정보 (DART 전자공시)]\n{dart_text}\n"

        prompt = f"""당신은 한국 주식 시장 전문 리서치 애널리스트입니다.
'{stock_name}' 종목에 대해 다음을 수행하세요:

1. Google 검색으로 최근 24시간 이내의 '{stock_name}' 관련 최신 뉴스, 실적/수주/계약 정보, 테마/산업 동향을 검색하세요.
2. 검색 결과와 아래 추가 정보를 종합 분석하여 호재 강도를 평가하세요.

[기존 뉴스 정보]
{trad_text}
{dart_section}

분석 결과를 아래 JSON 형식으로 출력하세요:
- score: 0~3점 (3:확실한 호재/수주/실적, 2:긍정 기대감, 1:중립, 0:악재/무소식)
- reason: 분석 핵심 이유 (한 문장)
- themes: 핵심 투자 테마 1~3개 (리스트 형식)
- news_summary: 검색된 주요 뉴스 요약 (2~3문장)
* 공식 공시(DART)가 있으면 뉴스보다 높은 신뢰도로 반영하세요 (자사주취득, 무상증자, 대규모수주 = 3점 수준)

JSON Format: {{"score": 2, "reason": "...", "themes": ["...", "..."], "news_summary": "..."}}"""

        # gemini-2.5-flash 는 추론 모델이라 사고 토큰을 출력 예산에서 먼저 쓴다.
        # 실측: 예산 1024 에 사고만 1,532 토큰 -> finishReason=MAX_TOKENS 로 JSON 이
        # 81자에서 잘리고, 파싱 실패 후 전 종목이 DeepSeek 폴백으로 넘어갔다.
        #
        # 이 호출은 추론 과제가 아니라 '검색 후 구조화 추출' 이므로 사고를 끈다.
        # 끄면 같은 예산에서 출력 700 토큰이 나오고 인용도 8 -> 11 개로 늘었다.
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
                "thinkingConfig": {"thinkingBudget": 0},
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}?key={self.api_key}",
                    json=payload
                )
                response.raise_for_status()
                resp_data = response.json()

            # Extract text from response
            text = ""
            candidates = resp_data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    if "text" in part:
                        text += part["text"]

            # Extract grounding citations
            citations = []
            if candidates:
                grounding = candidates[0].get("groundingMetadata", {})
                for chunk in grounding.get("groundingChunks", []):
                    web = chunk.get("web", {})
                    if web.get("uri"):
                        citations.append(web["uri"])

            text = text.strip()
            if not text:
                return {"score": 0, "reason": "Empty response from Gemini Grounding", "themes": [], "source": "none"}

            # Parse JSON from response
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                else:
                    data = {"score": 0, "reason": f"JSON Decode Failed: {text[:80]}", "themes": []}

            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            if not isinstance(data, dict):
                data = {"score": 0, "reason": "Invalid response format", "themes": []}

            data["source"] = "gemini_grounding"
            data["citations"] = citations
            raw_usage = resp_data.get("usageMetadata") or {}
            usage = normalize_gemini_usage({
                "prompt_token_count": raw_usage.get("promptTokenCount"),
                "cached_content_token_count": raw_usage.get("cachedContentTokenCount", 0),
                "candidates_token_count": raw_usage.get("candidatesTokenCount"),
                "thoughts_token_count": raw_usage.get("thoughtsTokenCount", 0),
                "total_token_count": raw_usage.get("totalTokenCount"),
            })
            data["usage"] = {
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
                "total_tokens": usage.total_tokens,
                "usage_estimated": usage.usage_estimated,
            }
            return data

        except Exception as e:
            error_msg = str(e).lower()
            print(f"[ERROR] Gemini Grounding Failed: {type(e).__name__}")

            if 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg or 'quota' in error_msg or 'resource' in error_msg:
                await _mark_unavailable('gemini_grounding', 'Rate Limit')
                print("[WARN] Gemini Grounding Rate Limit - 임시 비활성화")

            return {
                "score": 0,
                "reason": f"Grounding Error: {type(e).__name__}",
                "themes": [],
                "source": "none",
            }

class OpenAIAnalyzer:
    """OpenAI GPT를 이용한 뉴스 종합 분석 (Gemini Fallback)"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=self.api_key)
            # 2026-09-02: 계정에 gpt-4o 계열이 없다 (보유 모델 gpt-5.5 뿐) — 구 기본값은 매 호출 404
            self.model = os.getenv("OPENAI_MODEL", "gpt-5.5")
        else:
            self.client = None
            
    async def analyze_news(self, stock_name: str, perplexity_news: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        if not self.client:
            return {"score": 0, "reason": "No OpenAI Client", "themes": []}

        if not API_STATUS['openai']['available']:
            return {"score": 0, "reason": f"Rate Limited: {API_STATUS['openai']['last_error']}", "themes": []}

        trad_text = ""
        if traditional_news:
            for i, item in enumerate(traditional_news[:5], 1):
                trad_text += f"[{i}] {item.get('title')} - {item.get('summary', '')[:100]}\n"

        dart_section = ""
        if dart_text:
            dart_section = f"""
        [공식 공시 정보 (DART 전자공시)]
        {dart_text}
        """

        prompt = f"""
        당신은 주식 투자 전문가입니다. 다음 '{stock_name}' 종목의 정보를 분석하여 호재 강도와 테마를 추출하세요.

        [Perplexity 실시간 검색 결과]
        {perplexity_news}

        [기존 뉴스 정보]
        {trad_text}
        {dart_section}
        위 정보를 종합 분석하여 아래 형식을 따르는 JSON 객체로만 출력하세요.
        - score: 0~3점 (3:확실한 호재/수주/실적, 2:긍정 기대감, 1:중립, 0:악재/무소식)
        - reason: 분석 핵심 이유 (한 문장)
        - themes: 핵심 투자 테마 1~3개 (리스트 형식)
        * 공식 공시(DART)가 있으면 뉴스보다 높은 신뢰도로 반영하세요 (자사주취득, 무상증자, 대규모수주 = 3점 수준)

        JSON Format: {{"score": 2, "reason": "...", "themes": ["...", "..."]}}
        """
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful financial analyst. Respond only in JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            error_msg = str(e).lower()
            print(f"[ERROR] OpenAI Analysis Failed: {e}")

            # Rate Limit 감지
            if 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg or 'quota' in error_msg:
                await _mark_unavailable('openai', 'Rate Limit')
                print("[WARN] OpenAI Rate Limit - 임시 비활성화")

            return {"score": 0, "reason": f"OpenAI Error: {e}", "themes": []}

class GeminiAnalyzer:
    """Gemini를 이용한 뉴스 종합 분석 및 점수 산출"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
            self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        else:
            self.client = None
            self.model_name = None

    async def analyze_news(self, stock_name: str, perplexity_news: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        """Perplexity 결과와 네이버 뉴스를 통합 분석하여 점수화"""
        if not self.client:
            return {"score": 0, "reason": "No Gemini Model", "themes": []}

        if not API_STATUS['gemini']['available']:
            return {"score": 0, "reason": f"Rate Limited: {API_STATUS['gemini']['last_error']}", "themes": []}

        trad_text = ""
        if traditional_news:
            for i, item in enumerate(traditional_news[:5], 1):
                trad_text += f"[{i}] {item.get('title')} - {item.get('summary', '')[:100]}\n"

        dart_section = ""
        if dart_text:
            dart_section = f"""
        [공식 공시 정보 (DART 전자공시)]
        {dart_text}
        """

        prompt = f"""
        당신은 주식 투자 전문가입니다. 다음 '{stock_name}' 종목의 정보를 분석하여 호재 강도와 테마를 추출하세요.

        [Perplexity 실시간 검색 결과]
        {perplexity_news}

        [기존 뉴스 정보]
        {trad_text}
        {dart_section}
        위 정보를 종합 분석하여 아래 형식을 따르는 JSON 객체로만 출력하세요.
        - score: 0~3점 (3:확실한 호재/수주/실적, 2:긍정 기대감, 1:중립, 0:악재/무소식)
        - reason: 분석 핵심 이유 (한 문장)
        - themes: 핵심 투자 테마 1~3개 (리스트 형식)
        * 공식 공시(DART)가 있으면 뉴스보다 높은 신뢰도로 반영하세요 (자사주취득, 무상증자, 대규모수주 = 3점 수준)

        JSON Format: {{"score": 2, "reason": "...", "themes": ["...", "..."]}}
        """
        
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            text = response.text.strip()
            # JSON 파싱 및 예외 처리
            try:
                data = json.loads(text)
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                return data if isinstance(data, dict) else {"score": 0, "reason": "Invalid JSON format", "themes": []}
            except json.JSONDecodeError:
                # 텍스트에서 JSON 부분만 추출 시도
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return {"score": 0, "reason": f"JSON Decode Failed: {text[:50]}", "themes": []}
        except Exception as e:
            error_msg = str(e).lower()
            print(f"[ERROR] Gemini Analysis Failed: {e}")

            # Rate Limit 감지
            if 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg or 'quota' in error_msg or 'resource' in error_msg:
                await _mark_unavailable('gemini', 'Rate Limit')
                print("[WARN] Gemini Rate Limit - 임시 비활성화")

            return {"score": 0, "reason": f"Analysis Error: {e}", "themes": []}

class ClaudeAnalyzer:
    """Claude Haiku 4.5를 이용한 뉴스 종합 분석 (Gemini Fallback)"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model_name = "claude-haiku-4-5-20251001"
        if self.api_key:
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        else:
            self.client = None

    async def analyze_news(self, stock_name: str, perplexity_news: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        """Perplexity 결과와 네이버 뉴스를 통합 분석하여 점수화"""
        if not self.client:
            return {"score": 0, "reason": "No Claude Client", "themes": []}

        if not API_STATUS['claude']['available']:
            return {"score": 0, "reason": f"Rate Limited: {API_STATUS['claude']['last_error']}", "themes": []}

        trad_text = ""
        if traditional_news:
            for i, item in enumerate(traditional_news[:5], 1):
                trad_text += f"[{i}] {item.get('title')} - {item.get('summary', '')[:100]}\n"

        dart_section = ""
        if dart_text:
            dart_section = f"""
[공식 공시 정보 (DART 전자공시)]
{dart_text}
"""

        prompt = f"""당신은 주식 투자 전문가입니다. 다음 '{stock_name}' 종목의 정보를 분석하여 호재 강도와 테마를 추출하세요.

[Perplexity 실시간 검색 결과]
{perplexity_news}

[기존 뉴스 정보]
{trad_text}
{dart_section}
위 정보를 종합 분석하여 아래 형식을 따르는 JSON 객체로만 출력하세요.
- score: 0~3점 (3:확실한 호재/수주/실적, 2:긍정 기대감, 1:중립, 0:악재/무소식)
- reason: 분석 핵심 이유 (한 문장)
- themes: 핵심 투자 테마 1~3개 (리스트 형식)
* 공식 공시(DART)가 있으면 뉴스보다 높은 신뢰도로 반영하세요 (자사주취득, 무상증자, 대규모수주 = 3점 수준)

JSON Format: {{"score": 2, "reason": "...", "themes": ["...", "..."]}}"""

        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=512,
                system="You are a helpful financial analyst. Respond only in valid JSON.",
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text.strip()

            try:
                return json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return {"score": 0, "reason": f"JSON Decode Failed: {content[:50]}", "themes": []}

        except Exception as e:
            error_msg = str(e).lower()
            print(f"[ERROR] Claude Analysis Failed: {e}")

            if 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg or 'quota' in error_msg or 'overloaded' in error_msg:
                await _mark_unavailable('claude', 'Rate Limit')
                print("[WARN] Claude Rate Limit - 임시 비활성화")

            return {"score": 0, "reason": f"Claude Error: {e}", "themes": []}


class DeepSeekAnalyzer:
    """DeepSeek V4 기반 뉴스 분석 (OpenAI 호환 API).

    2026-06-10 Gemini 선불 크레딧 소진 대응 — Gemini 실패 시 1차 폴백.
    가장 저렴한 폴백이므로 Claude/OpenAI 보다 먼저 시도.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.client = None
        if self.api_key:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )

    async def analyze_news(self, stock_name: str, news_context: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        if not self.client:
            return {"score": 0, "reason": "No DeepSeek Client", "themes": []}

        if not API_STATUS['deepseek']['available']:
            return {"score": 0, "reason": f"Rate Limited: {API_STATUS['deepseek']['last_error']}", "themes": []}

        trad_text = ""
        if traditional_news:
            for i, item in enumerate(traditional_news[:5], 1):
                trad_text += f"[{i}] {item.get('title')} - {item.get('summary', '')[:100]}\n"

        dart_section = ""
        if dart_text:
            dart_section = f"\n[공식 공시 정보 (DART 전자공시)]\n{dart_text}\n"

        prompt = f"""당신은 주식 투자 전문가입니다. 다음 '{stock_name}' 종목의 정보를 분석하여 호재 강도와 테마를 추출하세요.

[실시간 검색 결과]
{news_context}

[기존 뉴스 정보]
{trad_text}
{dart_section}
위 정보를 종합 분석하여 아래 형식을 따르는 JSON 객체로만 출력하세요.
- score: 0~3점 (3:확실한 호재/수주/실적, 2:긍정 기대감, 1:중립, 0:악재/무소식)
- reason: 분석 핵심 이유 (한 문장)
- themes: 핵심 투자 테마 1~3개 (리스트 형식)
* 공식 공시(DART)가 있으면 뉴스보다 높은 신뢰도로 반영하세요

JSON Format: {{"score": 2, "reason": "...", "themes": ["...", "..."]}}"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful financial analyst. Respond only in JSON."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=512,
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            )
            content = response.choices[0].message.content.strip()
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return {"score": 0, "reason": f"JSON Decode Failed: {content[:50]}", "themes": []}
        except Exception as e:
            error_msg = str(e).lower()
            print(f"[ERROR] DeepSeek Analysis Failed: {e}")

            if 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg or 'quota' in error_msg or 'insufficient' in error_msg:
                await _mark_unavailable('deepseek', 'Rate Limit')
                print("[WARN] DeepSeek Rate Limit - 임시 비활성화")

            return {"score": 0, "reason": f"DeepSeek Error: {e}", "themes": []}


class XAIAnalyzer:
    """xAI Grok 기반 뉴스 분석 (OpenAI 호환 API)"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        self.model_name = "grok-3-mini-fast"
        self.client = None
        if self.api_key:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=self.api_key, base_url="https://api.x.ai/v1")

    async def analyze_news(self, stock_name: str, news_context: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        if not self.client:
            return {"score": 0, "reason": "No xAI Client", "themes": []}

        if not API_STATUS['xai']['available']:
            return {"score": 0, "reason": f"Rate Limited: {API_STATUS['xai']['last_error']}", "themes": []}

        trad_text = ""
        if traditional_news:
            for i, item in enumerate(traditional_news[:5], 1):
                trad_text += f"[{i}] {item.get('title')} - {item.get('summary', '')[:100]}\n"

        dart_section = ""
        if dart_text:
            dart_section = f"\n[공식 공시 정보 (DART 전자공시)]\n{dart_text}\n"

        prompt = f"""당신은 주식 투자 전문가입니다. 다음 '{stock_name}' 종목의 정보를 분석하여 호재 강도와 테마를 추출하세요.

[실시간 검색 결과]
{news_context}

[기존 뉴스 정보]
{trad_text}
{dart_section}
위 정보를 종합 분석하여 아래 형식을 따르는 JSON 객체로만 출력하세요.
- score: 0~3점 (3:확실한 호재/수주/실적, 2:긍정 기대감, 1:중립, 0:악재/무소식)
- reason: 분석 핵심 이유 (한 문장)
- themes: 핵심 투자 테마 1~3개 (리스트 형식)
* 공식 공시(DART)가 있으면 뉴스보다 높은 신뢰도로 반영하세요

JSON Format: {{"score": 2, "reason": "...", "themes": ["...", "..."]}}"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful financial analyst. Respond only in JSON."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=512
            )
            content = response.choices[0].message.content.strip()
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return {"score": 0, "reason": f"JSON Decode Failed: {content[:50]}", "themes": []}
        except Exception as e:
            error_msg = str(e).lower()
            print(f"[ERROR] xAI Analysis Failed: {e}")

            if 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg or 'quota' in error_msg:
                await _mark_unavailable('xai', 'Rate Limit')
                print("[WARN] xAI Rate Limit - 임시 비활성화")

            return {"score": 0, "reason": f"xAI Error: {e}", "themes": []}


class LLMAnalyzer:
    """Source-bounded news analysis with one centrally owned DS -> OA slot.

    Gemini Search Grounding remains a specialized source acquisition path when
    no stored source packet exists.  It is never silently substituted by an
    ungrounded multi-provider chain.
    """

    def __init__(self):
        self.grounding = GeminiGroundingClient()

    def get_api_status(self) -> Dict:
        """현재 API 상태 반환"""
        return {
            'gemini_grounding': 'active' if API_STATUS['gemini_grounding']['available'] else 'rate_limited',
            'gemini': 'active' if API_STATUS['gemini']['available'] else 'rate_limited',
            'deepseek': 'active' if API_STATUS['deepseek']['available'] else 'rate_limited',
            'claude': 'active' if API_STATUS['claude']['available'] else 'rate_limited',
            'openai': 'active' if API_STATUS['openai']['available'] else 'rate_limited',
            'xai': 'active' if API_STATUS['xai']['available'] else 'rate_limited',
            'errors': {k: v['error_count'] for k, v in API_STATUS.items()}
        }

    @staticmethod
    def _is_usable_analysis(result: Dict | None) -> bool:
        """True only when a result is actual analysis, not an API failure.

        A real no-catalyst analysis can legitimately have score=0. Operational
        failures are identified through explicit source/reason markers so the
        pipeline can continue to DeepSeek/OpenAI instead of stopping early.
        """
        if not isinstance(result, dict):
            return False
        if str(result.get('source', '')).lower() == 'none':
            return False

        reason = str(result.get('reason', '')).lower()
        failure_markers = (
            'error',
            'rate limit',
            'rate limited',
            '429',
            'quota',
            'resource_exhausted',
            'resource exhausted',
            'api key',
            'no gemini',
            'no deepseek',
            'no claude',
            'no openai',
            'no xai',
            'no client',
            'no model',
            'decode failed',
            'json decode failed',
            'invalid response',
            'invalid json',
            'empty response',
        )
        return not any(marker in reason for marker in failure_markers)

    async def analyze_news_sentiment(
        self,
        stock_name: str,
        news_items: List[Dict] = None,
        dart_text: str = "",
        *,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> Dict:
        """Interpret verified source records through BULK_TEXT.

        OpenAI is only the central router's one replacement for the failed
        DeepSeek slot. Source-less text is handled by deterministic rules and
        cannot independently contribute BUY evidence.
        """
        items = [dict(item) for item in (news_items or []) if isinstance(item, dict)][:5]
        logical_run_id = run_id or f"jongga-news:{uuid4()}"
        logical_request_id = request_id or f"{logical_run_id}:news"
        source_evidence = self._source_evidence(items, dart_text)
        eligible_evidence = [
            item for item in source_evidence if _fresh_attributed_news_record(item)
        ]
        citations = [str(item["url"]) for item in eligible_evidence]

        if not source_evidence:
            grounded = await self._ground_when_no_sources(
                stock_name,
                items,
                dart_text,
                run_id=logical_run_id,
                request_id=logical_request_id,
            )
            if grounded is not None:
                return grounded
            return self._rule_only_result(stock_name, items, dart_text)

        if not eligible_evidence:
            return self._rule_only_result(stock_name, items, dart_text)

        evidence_lines = [
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in eligible_evidence
        ]
        prompt = f"""'{stock_name}' 뉴스·공시 근거를 해석하세요.

[검증된 근거 레코드]
{chr(10).join(evidence_lines)}

JSON 객체만 반환: {{"score":0~3,"reason":"한 문장","themes":["최대 3개"]}}.
제공되지 않은 사실·수치·출처를 만들지 마세요."""
        routed = await asyncio.to_thread(
            route_text,
            RoutingRequest(
                operation=Operation.BULK_TEXT,
                prompt=prompt,
                system="한국 주식 뉴스 근거 해석기. 검증된 입력만 사용하고 JSON으로 답하세요.",
                run_id=logical_run_id,
                request_id=logical_request_id,
                json_mode=True,
                max_output_tokens=512,
                caller_endpoint="engine.llm_analyzer.analyze_news_sentiment",
                domain_validator=_news_response_validator,
            ),
        )
        analysis = _parse_json_object(routed.text)
        if analysis is None:
            fallback = self._rule_only_result(stock_name, items, dart_text)
            fallback["routing"] = _routing_metadata(
                routed,
                run_id=logical_run_id,
                request_id=logical_request_id,
            )
            return fallback

        analysis["source"] = (
            "openai_fallback" if routed.actual_provider == "openai" else "deepseek"
        )
        analysis["citations"] = citations
        analysis["source_evidence"] = source_evidence
        analysis["eligible_evidence_ids"] = [
            item["evidence_id"] for item in eligible_evidence
        ]
        analysis["non_grounded_summary"] = False
        analysis["buy_evidence_eligible"] = True
        analysis["routing"] = _routing_metadata(
            routed,
            run_id=logical_run_id,
            request_id=logical_request_id,
        )
        analysis["api_status"] = self.get_api_status()
        return analysis

    @staticmethod
    def _source_evidence(news_items: List[Dict], dart_text: str) -> List[Dict]:
        records: List[Dict] = []
        for item in news_items[:5]:
            title = str(item.get("title") or "")[:240]
            summary = str(item.get("summary") or "")[:400]
            source = str(item.get("source") or "")[:100]
            url = str(item.get("url") or "")[:1_000]
            published_at = str(item.get("published_at") or "")[:80]
            fingerprint = "|".join((title, source, url, published_at))
            records.append({
                "evidence_id": "news:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16],
                "title": title,
                "summary": summary,
                "source": source,
                "url": url,
                "published_at": published_at,
            })
        if dart_text:
            bounded = str(dart_text)[:2_000]
            records.append({
                "evidence_id": "dart:" + hashlib.sha256(bounded.encode("utf-8")).hexdigest()[:16],
                "title": "DART 공시",
                "summary": bounded,
                "source": "DART",
                "url": "",
                "published_at": "",
            })
        return records

    async def _ground_when_no_sources(
        self,
        stock_name: str,
        news_items: List[Dict],
        dart_text: str,
        *,
        run_id: str,
        request_id: str,
    ) -> Dict | None:
        grounding = getattr(self, "grounding", None)
        if grounding is None or not API_STATUS["gemini_grounding"]["available"]:
            return None
        result = await grounding.search_and_analyze(stock_name, news_items, dart_text)
        if not self._is_usable_analysis(result):
            return None
        citations = [
            str(value)
            for value in result.get("citations", [])
            if _valid_http_url(value)
        ]
        if not citations:
            return None
        freshness_verified = result.get("freshness_verified") is True
        output = dict(result)
        output["source"] = "gemini_grounding"
        output["citations"] = citations
        output["non_grounded_summary"] = False
        output["freshness_verified"] = freshness_verified
        output["buy_evidence_eligible"] = freshness_verified
        if not freshness_verified:
            output["score"] = min(1, int(output.get("score") or 0))
            output["analysis_status"] = "DEGRADED"
        output["routing"] = {
            "operation": Operation.SPECIALIZED_GEMINI.value,
            "run_id": run_id,
            "request_id": request_id,
            "analysis_status": output.get(
                "analysis_status", "SUCCESS_PRIMARY"
            ),
            "primary_provider": "gemini",
            "actual_provider": "gemini",
            "model": getattr(grounding, "model_name", None),
            "fallback_used": False,
            "fallback_reason": None,
            "retry_reason": None,
            "usage": output.get("usage"),
            "estimated_cost_usd": None,
            "attempt_count": 1,
        }
        output["api_status"] = self.get_api_status()
        return output

    def _rule_only_result(
        self,
        stock_name: str,
        news_items: List[Dict],
        dart_text: str = "",
    ) -> Dict:
        output = self._keyword_fallback(stock_name, news_items)
        output["score"] = min(1, int(output.get("score") or 0))
        output["citations"] = []
        output["source_evidence"] = self._source_evidence(news_items, dart_text)
        output["non_grounded_summary"] = True
        output["buy_evidence_eligible"] = False
        output["analysis_status"] = "DEGRADED"
        return output

    def _keyword_fallback(self, stock_name: str, news_items: List[Dict]) -> Dict:
        """API 실패 시 키워드 기반 단순 분석"""
        score = 0
        reason = "No news data available"
        themes = []
        
        if news_items:
            positive = ["수주", "계약", "흑자", "성공", "급등", "어닝", "FDA", "M&A", "특허", "공급", "개발"]
            negative = ["영업정지", "배임", "횡령", "적자", "상장폐지", "급락", "수사", "불성실"]
            
            all_text = " ".join([n.get("title", "") + n.get("summary", "") for n in news_items])
            
            if any(w in all_text for w in negative):
                score = 0
                reason = "부정적 키워드 감지됨"
            else:
                matches = [w for w in positive if w in all_text]
                # 매칭된 키워드 수에 따라 점수 부여 (최대 2점 - LLM보다는 보수적)
                if len(matches) >= 2:
                    score = 2
                elif len(matches) == 1:
                    score = 1
                else:
                    score = 0
                    
                reason = f"키워드 분석 ({', '.join(matches[:3])})" if matches else "호재 키워드 없음"
            
        return {
            "score": score,
            "reason": reason,
            "themes": themes,
            "source": "keyword_fallback"
        }

class ClaudeScreener:
    """Claude 기반 독립적 종목 선별기

    전체 시그널 데이터를 받아 Claude가 독립적으로
    Top Picks를 선별하고 추천 이유를 제공합니다.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model_name = "claude-haiku-4-5-20251001"
        if self.api_key:
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        else:
            self.client = None

    async def screen_candidates(self, signals_data: List[Dict]) -> Dict:
        """
        전체 시그널 데이터를 받아 Claude가 독립적으로 종목을 선별합니다.

        Args:
            signals_data: Signal.to_dict() 결과 리스트

        Returns:
            { "picks": [...], "market_view": "...", "top_themes": [...] }
        """
        if not self.client:
            return {"picks": [], "error": "No Claude Client", "generated_at": datetime.now().isoformat()}

        if not signals_data:
            return {"picks": [], "error": "No signals to screen", "generated_at": datetime.now().isoformat()}

        candidates_text = self._build_candidates_summary(signals_data)

        prompt = f"""당신은 한국 주식시장 전문 포트폴리오 매니저입니다.
아래는 오늘의 종가베팅(Closing Bet) 시그널 후보 종목 {len(signals_data)}개의 데이터입니다.

[후보 종목 데이터]
{candidates_text}

위 데이터를 종합적으로 분석하여 최종 Top 10~15 종목을 선별해주세요.

선별 기준:
1. 뉴스/재료의 질적 수준 (단순 테마 vs 실적/수주)
2. 수급 흐름 (외인+기관 동시 매수 우선)
3. 차트 기술적 위치 (신고가/돌파/정배열)
4. 거래대금 충분성
5. 리스크 대비 보상 (Risk/Reward)

다음 JSON 형식으로만 응답하세요:
{{
    "picks": [
        {{
            "stock_code": "코드",
            "stock_name": "종목명",
            "rank": 순위,
            "confidence": "HIGH/MEDIUM/LOW",
            "reason": "선별 이유 (한국어, 2~3문장)",
            "risk": "주요 리스크 (한 문장)",
            "expected_return": "기대 수익률 범위"
        }}
    ],
    "market_view": "오늘 시장에 대한 전체적 평가 (한국어, 한 문장)",
    "top_themes": ["오늘의 핫 테마 1", "테마 2", "테마 3"]
}}"""

        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=4096,
                system="You are a professional Korean stock market portfolio manager. Respond only in valid JSON. Analyze all candidates comprehensively.",
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text.strip()

            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    result = {"picks": [], "error": "JSON parse failed"}

            result["generated_at"] = datetime.now().isoformat()
            result["model"] = self.model_name
            return result

        except Exception as e:
            print(f"[ERROR] Claude Screener Failed: {e}")
            return {
                "picks": [],
                "error": str(e),
                "generated_at": datetime.now().isoformat(),
                "model": self.model_name
            }

    def _build_candidates_summary(self, signals_data: List[Dict]) -> str:
        """시그널 데이터를 Claude에 전달할 간결한 텍스트로 변환"""
        lines = []
        for i, s in enumerate(signals_data, 1):
            score = s.get("score", {})
            lines.append(
                f"#{i} [{s.get('grade','?')}] {s.get('stock_name','')}({s.get('stock_code','')}) "
                f"| 등락: {s.get('change_pct', 0):+.1f}% "
                f"| 거래대금: {s.get('trading_value', 0) / 100_000_000:.0f}억 "
                f"| 점수: {score.get('total', 0)} "
                f"(뉴스{score.get('news',0)} 수급{score.get('supply',0)} 차트{score.get('chart',0)} 거래량{score.get('volume',0)}) "
                f"| 외인5d: {s.get('foreign_5d', 0):+,} 기관5d: {s.get('inst_5d', 0):+,} "
                f"| AI: {score.get('llm_reason', 'N/A')[:80]} "
                f"| 테마: {', '.join(s.get('themes', []))}"
            )
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Multi-AI Consensus Screening System
# ─────────────────────────────────────────────────────────────

class BaseScreener:
    """AI 스크리너 공통 베이스 클래스"""

    async def _chat_with_token_limit(self, client, *, model: str, messages: list,
                                     max_output_tokens: int, **kwargs):
        """OpenAI 호환 chat 호출. 토큰 한도 파라미터명을 모델에 맞춰 협상한다.

        구형 모델은 `max_tokens`, 신형(o1·gpt-5 계열)은 `max_completion_tokens`
        만 받는다. 모델명으로 분기하면 모델을 바꿀 때마다 다시 깨지므로,
        거부 응답을 보고 한 번 재시도한다.

        2026-08-05: 계정에 gpt-4o 가 없어 gpt-5.5 로 바꿨더니 이번엔
        "Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens'"
        로 스크리너가 통째로 실패했다.
        """
        try:
            return await client.chat.completions.create(
                model=model, messages=messages,
                max_tokens=max_output_tokens, **kwargs
            )
        except Exception as exc:
            text = str(exc)
            if 'max_completion_tokens' not in text:
                raise
            return await client.chat.completions.create(
                model=model, messages=messages,
                max_completion_tokens=max_output_tokens, **kwargs
            )

    def _build_candidates_summary(self, signals_data: List[Dict]) -> str:
        """시그널 데이터를 AI에 전달할 간결한 텍스트로 변환"""
        lines = []
        for i, s in enumerate(signals_data, 1):
            score = s.get("score", {})
            disc = s.get("disclosure_info", {})
            disc_text = ""
            if disc.get("has_disclosure"):
                disc_text = f" | 공시: {', '.join(disc.get('types', []))}"
            lines.append(
                f"#{i} [{s.get('grade','?')}] {s.get('stock_name','')}({s.get('stock_code','')}) "
                f"| 등락: {s.get('change_pct', 0):+.1f}% "
                f"| 거래대금: {s.get('trading_value', 0) / 100_000_000:.0f}억 "
                f"| 점수: {score.get('total', 0)} "
                f"(뉴스{score.get('news',0)} 수급{score.get('supply',0)} 차트{score.get('chart',0)} "
                f"거래량{score.get('volume',0)} 공시{score.get('disclosure',0)}) "
                f"| 외인5d: {s.get('foreign_5d', 0):+,} 기관5d: {s.get('inst_5d', 0):+,} "
                f"| AI: {score.get('llm_reason', 'N/A')[:80]} "
                f"| 테마: {', '.join(s.get('themes', []))}"
                f"{disc_text}"
            )
        return "\n".join(lines)

    def _build_screening_prompt(self, candidates_text: str, count: int) -> str:
        """스크리닝 프롬프트 생성"""
        return f"""당신은 한국 주식시장 전문 포트폴리오 매니저입니다.
아래는 오늘의 종가베팅(Closing Bet) 시그널 후보 종목 {count}개의 데이터입니다.

[후보 종목 데이터]
{candidates_text}

위 데이터를 종합적으로 분석하여 최종 Top 10~15 종목을 선별해주세요.

선별 기준:
1. 뉴스/재료의 질적 수준 (단순 테마 vs 실적/수주)
2. 수급 흐름 (외인+기관 동시 매수 우선)
3. 차트 기술적 위치 (신고가/돌파/정배열)
4. 거래대금 충분성
5. 리스크 대비 보상 (Risk/Reward)
6. DART 공시 정보 (자사주취득, 무상증자, 대규모수주 등 호재공시 우선)

다음 JSON 형식으로만 응답하세요:
{{
    "picks": [
        {{
            "stock_code": "코드",
            "stock_name": "종목명",
            "rank": 순위,
            "confidence": "HIGH/MEDIUM/LOW",
            "reason": "선별 이유 (한국어, 2~3문장)",
            "risk": "주요 리스크 (한 문장)",
            "expected_return": "기대 수익률 범위"
        }}
    ],
    "market_view": "오늘 시장에 대한 전체적 평가 (한국어, 한 문장)",
    "top_themes": ["오늘의 핫 테마 1", "테마 2", "테마 3"]
}}"""

    def _parse_json_response(self, content: str) -> dict:
        """JSON 응답 파싱 (regex fallback 포함)"""
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    result = {"picks": [], "error": "JSON parse failed"}
            else:
                result = {"picks": [], "error": "JSON parse failed"}
        return result


class GeminiScreener(BaseScreener):
    """Gemini 2.5 Flash 기반 독립적 종목 선별기"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = os.getenv("GEMINI_SCREENER_MODEL", "gemini-2.5-flash")
        self.client = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    async def screen_candidates(self, signals_data: List[Dict]) -> Dict:
        if not self.client:
            return {"picks": [], "error": "No Gemini Client", "generated_at": datetime.now().isoformat()}
        if not signals_data:
            return {"picks": [], "error": "No signals", "generated_at": datetime.now().isoformat()}

        candidates_text = self._build_candidates_summary(signals_data)
        prompt = self._build_screening_prompt(candidates_text, len(signals_data))

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            content = response.text.strip()
            result = self._parse_json_response(content)
            result["generated_at"] = datetime.now().isoformat()
            result["model"] = self.model_name
            return result
        except Exception as e:
            print(f"[ERROR] Gemini Screener Failed: {e}")
            return {"picks": [], "error": str(e), "generated_at": datetime.now().isoformat(), "model": self.model_name}


class OpenAIScreener(BaseScreener):
    """GPT-4o 기반 독립적 종목 선별기"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = os.getenv("OPENAI_SCREENER_MODEL", "gpt-5.5")  # 계정 보유 모델 (gpt-4o 없음)
        self.client = None
        if self.api_key:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=self.api_key)

    async def screen_candidates(self, signals_data: List[Dict]) -> Dict:
        if not self.client:
            return {"picks": [], "error": "No OpenAI Client", "generated_at": datetime.now().isoformat()}
        if not signals_data:
            return {"picks": [], "error": "No signals", "generated_at": datetime.now().isoformat()}

        candidates_text = self._build_candidates_summary(signals_data)
        prompt = self._build_screening_prompt(candidates_text, len(signals_data))

        try:
            response = await self._chat_with_token_limit(
                self.client,
                model=self.model_name,
                max_output_tokens=4096,
                messages=[
                    {"role": "system", "content": "You are a professional Korean stock market portfolio manager. Respond only in valid JSON. Analyze all candidates comprehensively."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content.strip()
            result = self._parse_json_response(content)
            result["generated_at"] = datetime.now().isoformat()
            result["model"] = self.model_name
            return result
        except Exception as e:
            print(f"[ERROR] OpenAI Screener Failed: {e}")
            return {"picks": [], "error": str(e), "generated_at": datetime.now().isoformat(), "model": self.model_name}


class DeepSeekScreener(BaseScreener):
    """One logical DeepSeek-first slot with one central OpenAI replacement."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model_name = os.getenv("AI_DEEPSEEK_FAST_MODEL", "deepseek-v4-flash")
        # Historical callers use this as an availability marker. The central
        # slot can also run when only the approved OpenAI fallback is configured.
        self.client = bool(self.api_key or os.getenv("OPENAI_API_KEY"))

    async def screen_candidates(
        self,
        signals_data: List[Dict],
        *,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> Dict:
        if not signals_data:
            return {"picks": [], "error": "No signals", "generated_at": datetime.now().isoformat()}

        candidates_text = self._build_candidates_summary(signals_data)
        prompt = self._build_screening_prompt(candidates_text, len(signals_data))
        allowed_codes = {
            str(item.get("stock_code") or "") for item in signals_data
            if item.get("stock_code")
        }

        def validate(payload):
            if not isinstance(payload, dict) or not isinstance(payload.get("picks"), list):
                return ProviderErrorClass.INVALID_JSON
            for pick in payload["picks"]:
                if not isinstance(pick, dict):
                    return ProviderErrorClass.INVALID_JSON
                if str(pick.get("stock_code") or "") not in allowed_codes:
                    return ProviderErrorClass.NUMERIC_MISMATCH
            return None

        logical_run_id = run_id or f"jongga-screener:{uuid4()}"
        logical_request_id = request_id or f"{logical_run_id}:multi-ai-primary"
        routed = await asyncio.to_thread(
            route_text,
            RoutingRequest(
                operation=Operation.BULK_TEXT,
                prompt=prompt,
                system=(
                    "You are a professional Korean stock market portfolio manager. "
                    "Respond only in valid JSON and use only supplied candidates."
                ),
                run_id=logical_run_id,
                request_id=logical_request_id,
                json_mode=True,
                max_output_tokens=768,
                caller_endpoint="engine.MultiAIConsensusScreener.primary",
                domain_validator=validate,
            ),
        )
        result = self._parse_json_response(routed.text) if routed.text else {"picks": []}
        result["generated_at"] = datetime.now().isoformat()
        result["model"] = routed.model
        result["routing"] = _routing_metadata(
            routed,
            run_id=logical_run_id,
            request_id=logical_request_id,
        )
        if not routed.text:
            result["error"] = "AI screening unavailable"
            result["analysis_status"] = routed.analysis_status.value
        return result


class GrokScreener(BaseScreener):
    """xAI Grok-4 기반 독립적 종목 선별기 (OpenAI 호환 API)

    Multi-AI Consensus 의 3번째 독립 투표자.
    OpenAI 계열과 다른 학습/정렬 방법론으로 groupthink 위험 완화.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        self.model_name = os.getenv("XAI_SCREENER_MODEL", "grok-4")
        self.client = None
        if self.api_key:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=self.api_key, base_url="https://api.x.ai/v1")

    async def screen_candidates(self, signals_data: List[Dict]) -> Dict:
        if not self.client:
            return {"picks": [], "error": "No xAI Client", "generated_at": datetime.now().isoformat()}
        if not signals_data:
            return {"picks": [], "error": "No signals", "generated_at": datetime.now().isoformat()}

        candidates_text = self._build_candidates_summary(signals_data)
        prompt = self._build_screening_prompt(candidates_text, len(signals_data))

        try:
            response = await self._chat_with_token_limit(
                self.client,
                model=self.model_name,
                max_output_tokens=4096,
                messages=[
                    {"role": "system", "content": "You are a professional Korean stock market portfolio manager. Respond only in valid JSON. Analyze all candidates comprehensively."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content.strip()
            result = self._parse_json_response(content)
            result["generated_at"] = datetime.now().isoformat()
            result["model"] = self.model_name

            usage = getattr(response, "usage", None)
            if usage is not None:
                in_tok = getattr(usage, "prompt_tokens", 0) or 0
                out_tok = getattr(usage, "completion_tokens", 0) or 0
                cost_est = (in_tok / 1_000_000) * 3.0 + (out_tok / 1_000_000) * 15.0
                result["usage"] = {"input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": round(cost_est, 4)}
                logger.info(f"[Grok] tokens in={in_tok} out={out_tok} cost=${cost_est:.4f}")
            return result
        except Exception as e:
            print(f"[ERROR] Grok Screener Failed: {e}")
            return {"picks": [], "error": str(e), "generated_at": datetime.now().isoformat(), "model": self.model_name}


# Multi-AI 모델 식별자 상수
MODEL_GEMINI = "gemini"
MODEL_OPENAI = "openai"
MODEL_GROK = "grok"
MODEL_DEEPSEEK = "deepseek"

_MODEL_DISPLAY = {
    MODEL_DEEPSEEK: "DeepSeek",
    MODEL_GEMINI: "Gemini",
    MODEL_OPENAI: "GPT-5.5",
    MODEL_GROK: "Grok",
}

_MODEL_DEFAULT = {
    MODEL_DEEPSEEK: "deepseek-v4-pro",
    MODEL_GEMINI: "gemini-2.5-flash",
    MODEL_OPENAI: "gpt-5.5",
    MODEL_GROK: "grok-4",
}


class MultiAIConsensusScreener:
    """Cost-aware primary verdict plus an explicitly isolated shadow comparison."""

    GROK_TIMEOUT = 90    # reasoning 모델은 60s 초과 가능
    DEFAULT_TIMEOUT = 60

    def __init__(self):
        # This dictionary contains logical verdict paths, not physical providers.
        # OpenAI lives only inside the central DeepSeek slot as one replacement.
        self.screeners: Dict[str, "BaseScreener"] = {
            MODEL_DEEPSEEK: DeepSeekScreener(),
        }
        self.shadow_compare = os.getenv("MULTI_AI_SHADOW_COMPARE", "0") == "1"
        self.shadow_screeners: Dict[str, "BaseScreener"] = {}
        if self.shadow_compare:
            if os.getenv("MULTI_AI_INCLUDE_GEMINI", "0") == "1":
                self.shadow_screeners[MODEL_GEMINI] = GeminiScreener()
            if os.getenv("MULTI_AI_INCLUDE_GROK", "0") == "1":
                self.shadow_screeners[MODEL_GROK] = GrokScreener()
        # The legacy Claude critic is not part of the user verdict path. Decisive
        # review is owned by the central DECISIVE_TEXT pipeline elsewhere.
        self.devil_advocate: Optional["ClaudeDevilAdvocate"] = None

    async def screen_candidates(
        self,
        signals_data: List[Dict],
        *,
        run_id: str | None = None,
    ) -> Dict:
        """Run one DS-first logical path; shadow output never mutates its picks."""
        if not signals_data:
            empty_result = {
                "picks": [], "consensus_count": 0, "strong_count": 0,
                "deepseek_count": 0, "gemini_count": 0, "openai_count": 0, "grok_count": 0,
                "market_view": "", "top_themes": [],
                "generated_at": datetime.now().isoformat(),
                "models": [], "models_attempted": list(self.screeners.keys()),
                "models_succeeded": [], "consensus_method": "routed_primary_v1",
            }
            if self.shadow_compare:
                empty_result["shadow_comparison"] = {
                    "status": "not_run",
                    "reason": (
                        "no_candidates"
                        if self.shadow_screeners
                        else "no_explicit_shadow_providers"
                    ),
                    "compared": False,
                    "verdict_blended": False,
                    "models_attempted": [],
                }
            return empty_result

        logical_run_id = run_id or f"jongga-multi-ai:{uuid4()}"
        primary = self.screeners[MODEL_DEEPSEEK]
        try:
            # The central route owns provider deadlines and fallback. Wrapping
            # its to_thread call in a shorter asyncio timeout would only detach
            # the worker while it continues spending in the background.
            primary_result = await primary.screen_candidates(
                signals_data,
                run_id=logical_run_id,
                request_id=f"{logical_run_id}:multi-ai-primary",
            )
        except Exception as exc:
            logger.warning("[MultiAI] primary routed slot failed: %s", type(exc).__name__)
            primary_result = {
                "picks": [],
                "error": "AI screening unavailable",
                "model": getattr(primary, "model_name", None),
            }

        output = self._build_routed_primary(primary_result)
        if self.shadow_compare:
            if self.shadow_screeners:
                names = list(self.shadow_screeners)
                shadow_results = await asyncio.gather(*[
                    self._safe_screen(
                        self.shadow_screeners[name], signals_data, self._timeout_for(name)
                    )
                    for name in names
                ])
                shadow = self._build_consensus(dict(zip(names, shadow_results)))
                primary_codes = {
                    str(item.get("stock_code")) for item in output.get("picks", [])
                }
                shadow_codes = [
                    str(item.get("stock_code")) for item in shadow.get("picks", [])
                ]
                output["shadow_comparison"] = {
                    "status": "completed",
                    "compared": True,
                    "picks": shadow_codes,
                    "overlap_count": len(primary_codes.intersection(shadow_codes)),
                    "models_attempted": shadow.get("models_attempted", []),
                    "verdict_blended": False,
                }
            else:
                output["shadow_comparison"] = {
                    "status": "not_run",
                    "reason": "no_explicit_shadow_providers",
                    "compared": False,
                    "verdict_blended": False,
                    "models_attempted": [],
                }
        return output

    @staticmethod
    def _build_routed_primary(result: Dict) -> Dict:
        routing = result.get("routing") if isinstance(result.get("routing"), dict) else {}
        actual_provider = routing.get("actual_provider") or "deepseek"
        source = "openai_fallback" if actual_provider == "openai" else "deepseek"
        picks = []
        for rank, item in enumerate(result.get("picks", []), 1):
            if not isinstance(item, dict):
                continue
            pick = dict(item)
            pick["rank"] = rank
            pick["source"] = source
            picks.append(pick)
        model = result.get("model")
        return {
            "picks": picks,
            "consensus_count": 0,
            "strong_count": 0,
            "deepseek_count": len(picks) if actual_provider == "deepseek" else 0,
            "gemini_count": 0,
            "openai_count": len(picks) if actual_provider == "openai" else 0,
            "grok_count": 0,
            "market_view": result.get("market_view", ""),
            "top_themes": list(result.get("top_themes", []))[:6],
            "generated_at": result.get("generated_at") or datetime.now().isoformat(),
            "models": [model] if model and picks else [],
            "models_attempted": [model] if model else [],
            "models_succeeded": [model] if model and picks else [],
            "consensus_method": "routed_primary_v1",
            "routing": routing,
            "analysis_status": result.get("analysis_status") or routing.get("analysis_status"),
            "total_cost_usd": routing.get("estimated_cost_usd") or 0.0,
        }

    async def _review_strong_picks(self, consensus: Dict, signals_data: List[Dict]) -> Dict:
        """consensus_strong 픽에 대해 Claude 가 반대 입장으로 리스크 검토.

        실패 시 graceful — 픽은 변경 없이 통과.
        """
        strong_picks = [p for p in consensus.get("picks", []) if p.get("source") == "consensus_strong"]
        if not strong_picks:
            return consensus

        try:
            reviewed = await self.devil_advocate.review_strong_picks(strong_picks, signals_data)
        except Exception as e:
            logger.warning(f"[DevilAdvocate] review failed: {type(e).__name__}: {e}")
            return consensus

        # 픽 업데이트 + 비용 합산
        review_by_code = {r["stock_code"]: r for r in reviewed if r.get("stock_code")}
        new_picks = []
        flagged_count = 0
        for p in consensus["picks"]:
            if p.get("source") == "consensus_strong" and p.get("stock_code") in review_by_code:
                review = review_by_code[p["stock_code"]]
                p["devil_advocate_flags"] = review.get("flags", [])
                p["review_verdict"] = review.get("verdict", "PASS")
                p["review_reasoning"] = review.get("reasoning", "")
                # confidence 강등 (WARN: -1, BLOCK: -2)
                if review.get("verdict") == "WARN":
                    p["confidence"] = self._downgrade_confidence(p.get("confidence", "HIGH"))
                    flagged_count += 1
                elif review.get("verdict") == "BLOCK":
                    p["confidence"] = self._downgrade_confidence(self._downgrade_confidence(p.get("confidence", "HIGH")))
                    flagged_count += 1
            new_picks.append(p)
        consensus["picks"] = new_picks

        # 메타 추가
        review_cost = self.devil_advocate.last_run_cost_usd
        consensus["devil_advocate_enabled"] = True
        consensus["devil_advocate_model"] = self.devil_advocate.model_name
        consensus["devil_advocate_flagged_count"] = flagged_count
        consensus["devil_advocate_cost_usd"] = round(review_cost, 4)
        consensus["total_cost_usd"] = round(consensus.get("total_cost_usd", 0.0) + review_cost, 4)

        return consensus

    def _timeout_for(self, model_name: str) -> int:
        return self.GROK_TIMEOUT if model_name == MODEL_GROK else self.DEFAULT_TIMEOUT

    async def _safe_screen(self, screener, signals_data: List[Dict], timeout: int = 60) -> Dict:
        """개별 스크리너 (타임아웃 + 에러 핸들링)"""
        model_name = getattr(screener, 'model_name', 'unknown')
        try:
            return await asyncio.wait_for(
                screener.screen_candidates(signals_data),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"[MultiAI] {model_name} screener timed out after {timeout}s")
            return {"picks": [], "error": f"Timeout after {timeout}s", "model": model_name}
        except Exception as e:
            logger.warning(
                f"[MultiAI] {model_name} screener failed: {type(e).__name__}: {e}"
            )
            return {"picks": [], "error": str(e), "model": model_name}

    def _build_consensus(self, results: Dict[str, Dict]) -> Dict:
        """N-way 합의 알고리즘.

        results: {MODEL_GEMINI: result, MODEL_OPENAI: result, MODEL_GROK?: result}
        """
        # stock_code → pick 매핑 (모델별)
        maps: Dict[str, Dict[str, Dict]] = {
            name: {p.get("stock_code", ""): p for p in res.get("picks", []) if p.get("stock_code")}
            for name, res in results.items()
        }
        sets: Dict[str, set] = {name: set(m.keys()) for name, m in maps.items()}
        active_models = [name for name in sets.keys() if sets[name] or results[name].get("picks") is not None]

        # 교집합 단계적 차감 (∅ 시 모두 demote 되는 버그 방지)
        all_codes_strong: set
        if len(sets) >= 3 and all(s for s in sets.values()):
            all_codes_strong = set.intersection(*sets.values())
        elif len(sets) >= 2:
            # 2-way 모드 (Grok 비활성 또는 빈 결과) → strong = ∅
            all_codes_strong = set()
        else:
            all_codes_strong = set()

        # 페어 합의 (∪ 모든 페어) − strong
        pair_codes: set = set()
        names = list(sets.keys())
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                pair_codes |= (sets[a] & sets[b])
        pair_codes -= all_codes_strong

        # Solo (각 모델 단독)
        solo_by_model: Dict[str, set] = {}
        for name in names:
            others_union = set().union(*(sets[m] for m in names if m != name)) if names else set()
            solo_by_model[name] = sets[name] - others_union

        # 1) consensus_strong picks (3-of-3)
        strong_picks = []
        for code in sorted(all_codes_strong, key=lambda c: self._consensus_sort_key({m: maps[m][c] for m in names if c in maps[m]})):
            picks_for_code = {m: maps[m][c] for m in names for c in [code] if c in maps[m]}
            strong_picks.append(self._merge_pick(code, picks_for_code, tier="consensus_strong"))

        # 2) consensus picks (2-of-3 페어)
        pair_picks = []
        for code in sorted(pair_codes, key=lambda c: self._consensus_sort_key({m: maps[m][c] for m in names if c in maps[m]})):
            picks_for_code = {m: maps[m][code] for m in names if code in maps[m]}
            pair_picks.append(self._merge_pick(code, picks_for_code, tier="consensus"))

        # 3) Solo picks (1-of-N)
        solo_picks = []
        for name in names:
            for code in sorted(solo_by_model[name], key=lambda c: maps[name][c].get("rank", 99)):
                pick = maps[name][code].copy()
                pick["source"] = f"{name}_only"
                pick["confidence"] = self._downgrade_confidence(pick.get("confidence", "LOW"))
                pick.setdefault("expected_return", "")
                solo_picks.append(pick)

        # 통합 + 재순위 (strong > pair > solo)
        all_picks = strong_picks + pair_picks + solo_picks
        for i, p in enumerate(all_picks, 1):
            p["rank"] = i

        # Market views 병합 (선정 모델만)
        views = []
        for name in names:
            mv = results[name].get("market_view")
            if mv:
                views.append(f"[{_MODEL_DISPLAY.get(name, name)}] {mv}")

        # Themes 병합 (중복 제거)
        all_themes: List[str] = []
        for name in names:
            for t in results[name].get("top_themes", []):
                if t not in all_themes:
                    all_themes.append(t)

        # 활성 모델 (실제 picks 생성한 모델)
        models_succeeded = [
            results[name].get("model", _MODEL_DEFAULT.get(name, name))
            for name in names if maps[name]
        ]
        models_attempted = [
            results[name].get("model", _MODEL_DEFAULT.get(name, name))
            for name in names
        ]

        # 모델별 카운트 (FE 호환: gemini_count/openai_count, 신규: grok_count)
        counts = {f"{name}_count": len(maps[name]) for name in names}
        # Grok 미활성 시 grok_count 0 고정 (FE 안전성)
        counts.setdefault("grok_count", 0)

        # 사용 비용 합산 (Grok)
        total_cost = 0.0
        for name in names:
            usage = results[name].get("usage")
            if isinstance(usage, dict):
                total_cost += float(usage.get("cost_usd") or 0.0)

        return {
            "picks": all_picks,
            "consensus_count": len(strong_picks) + len(pair_picks),  # 기존 호환: 합의 통합 카운트
            "strong_count": len(strong_picks),                        # 신규: 3-of-3 카운트
            **counts,
            "market_view": " | ".join(views),
            "top_themes": all_themes[:6],
            "generated_at": datetime.now().isoformat(),
            "models": models_succeeded,
            "models_attempted": models_attempted,
            "models_succeeded": models_succeeded,
            "consensus_method": "multi_ai_v2",
            "total_cost_usd": round(total_cost, 4) if total_cost else 0.0,
        }

    def _consensus_sort_key(self, picks_by_model: Dict[str, Dict]) -> tuple:
        """합의 정렬 키 — 선정한 모델 ranks 만 평균 (1-of-N 페널티 방지)."""
        conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        ranks = [p.get("rank", 99) for p in picks_by_model.values()]
        avg_rank = sum(ranks) / len(ranks) if ranks else 99
        confs = [conf_order.get(p.get("confidence", "LOW"), 2) for p in picks_by_model.values()]
        best_conf = min(confs) if confs else 2
        return (best_conf, avg_rank)

    def _merge_pick(self, code: str, picks_by_model: Dict[str, Dict], tier: str) -> Dict:
        """N-way 병합. tier ∈ {"consensus_strong", "consensus"}."""
        conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        reverse = {0: "HIGH", 1: "MEDIUM", 2: "LOW"}

        # 최고 confidence 기준 boost
        confs = [conf_order.get(p.get("confidence", "LOW"), 2) for p in picks_by_model.values()]
        best = min(confs) if confs else 2
        levels = 2 if tier == "consensus_strong" else 1
        boosted = self._boost_confidence_index(best, levels)

        # stock_name (첫 비어있지 않은 값)
        stock_name = ""
        for p in picks_by_model.values():
            if p.get("stock_name"):
                stock_name = p["stock_name"]
                break

        # 모델별 reason 분리 저장 + concat
        reasons_dict: Dict[str, str] = {}
        reason_parts: List[str] = []
        for name, p in picks_by_model.items():
            r = p.get("reason", "")
            if r:
                reasons_dict[name] = r
                reason_parts.append(f"[{_MODEL_DISPLAY.get(name, name)}] {r}")

        # rank 필드: 선정 모델만 (placeholder 99 금지)
        rank_fields = {f"{name}_rank": p.get("rank", 99) for name, p in picks_by_model.items()}

        # risk / expected_return: 첫 비어있지 않은 값
        risk = ""
        expected_return = ""
        for p in picks_by_model.values():
            if not risk and p.get("risk"):
                risk = p["risk"]
            if not expected_return and p.get("expected_return"):
                expected_return = p["expected_return"]

        merged = {
            "stock_code": code,
            "stock_name": stock_name,
            "rank": 0,  # 추후 재배정
            "confidence": reverse[boosted],
            "reason": " ".join(reason_parts),
            "reasons": reasons_dict,
            "risk": risk,
            "expected_return": expected_return,
            "source": tier,
        }
        merged.update(rank_fields)
        return merged

    def _boost_confidence_index(self, conf_idx: int, levels: int = 1) -> int:
        """confidence index 를 N단계 상향 (HIGH=0 캡)."""
        return max(0, conf_idx - max(0, levels))

    def _downgrade_confidence(self, confidence: str) -> str:
        """Solo picks confidence 1단계 하향"""
        downgrades = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}
        return downgrades.get(confidence, "LOW")


class ClaudeDevilAdvocate:
    """Claude 기반 Devil's Advocate 리스크 리뷰어.

    consensus_strong (3-of-3) 픽에 대해 반대 입장으로 함정 신호를 강제 추출.
    Voter 가 아닌 Critic — groupthink 면역.
    """

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"
    DEFAULT_TIMEOUT = 30
    MAX_PARALLEL = 5

    # claude-haiku-4-5 pricing (per 1M tokens)
    HAIKU_INPUT_PRICE = 0.80
    HAIKU_OUTPUT_PRICE = 4.00

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model_name = os.getenv("DEVIL_ADVOCATE_MODEL", self.DEFAULT_MODEL)
        self.timeout = int(os.getenv("DEVIL_ADVOCATE_TIMEOUT", str(self.DEFAULT_TIMEOUT)))
        self.client = None
        self.last_run_cost_usd = 0.0
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"[DevilAdvocate] client init failed: {e}")
                self.client = None

    async def review_strong_picks(self, strong_picks: List[Dict], signals_data: List[Dict]) -> List[Dict]:
        """각 strong pick 을 병렬 review. 반환: [{stock_code, flags, verdict, reasoning}]"""
        if not self.client or not strong_picks:
            self.last_run_cost_usd = 0.0
            return []

        # signal_data → code 매핑 (재무/수급 컨텍스트 주입용)
        sig_by_code = {s.get("stock_code"): s for s in signals_data if s.get("stock_code")}

        # 병렬 실행 (semaphore 제한)
        sem = asyncio.Semaphore(self.MAX_PARALLEL)

        async def _bounded(pick):
            async with sem:
                return await self._review_single(pick, sig_by_code.get(pick.get("stock_code"), {}))

        coros = [_bounded(p) for p in strong_picks]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # 결과 정규화
        normalized: List[Dict] = []
        total_cost = 0.0
        for pick, res in zip(strong_picks, results):
            if isinstance(res, Exception):
                logger.warning(f"[DevilAdvocate] {pick.get('stock_code')} review failed: {res}")
                continue
            if not isinstance(res, dict):
                continue
            total_cost += res.get("_cost_usd", 0.0)
            normalized.append({
                "stock_code": pick.get("stock_code"),
                "flags": res.get("flags", []),
                "verdict": res.get("verdict", "PASS"),
                "reasoning": res.get("reasoning", ""),
            })

        self.last_run_cost_usd = total_cost
        return normalized

    async def _review_single(self, pick: Dict, signal: Dict) -> Dict:
        """단일 픽 review. Claude API 호출 + JSON 파싱."""
        stock_name = pick.get("stock_name", "")
        stock_code = pick.get("stock_code", "")
        reason = pick.get("reason", "")

        # 컨텍스트 패킹 (signal 에서 보강)
        score = signal.get("score", {}) if signal else {}
        checklist = signal.get("checklist", {}) if signal else {}
        context_lines = []
        if signal:
            context_lines.append(f"등급: {signal.get('grade', 'N/A')} | 점수: {score.get('total', 0)}/17")
            context_lines.append(f"등락률: {signal.get('change_pct', 0):+.1f}% | 거래대금: {signal.get('trading_value', 0):,.0f}원")
            context_lines.append(f"외인5일: {signal.get('foreign_5d', 0):+,}억 | 기관5일: {signal.get('inst_5d', 0):+,}억")
            context_lines.append(f"거래량배수: {signal.get('volume_ratio', 0):.2f}x | 변동성축소: {checklist.get('has_consolidation', False)}")
            context_lines.append(f"악재뉴스: {checklist.get('negative_news', False)} | 윗꼬리장대: {checklist.get('upper_wick_long', False)}")

        prompt = f"""당신은 한국 주식시장의 매우 보수적인 리스크 분석가입니다.
3개 AI(Gemini, GPT-4o, Grok)가 모두 매수 추천한 종목 '{stock_name}({stock_code})'에 대해
**반대 입장에서** 함정 가능성을 적극적으로 찾아내야 합니다.

[3사 합의 매수 사유]
{reason}

[정량 데이터]
{chr(10).join(context_lines) if context_lines else '데이터 부족'}

[검증 카테고리]
- volume_decay: 거래대금 감소 추세 (5일 평균 vs 당일)
- chart_trap: 단기 과열/블로우오프 탑/긴 윗꼬리/저항선 진입
- supply_warning: 외인/기관 매도 전환 시그널
- theme_bubble: 테마 거품/유사 종목 동시 급등 후 차별화 부재
- disclosure_risk: 잠재적 악재공시 단서 (소송, 특수관계자 거래, 회계 의심)
- valuation_overreach: PER/PBR 과열 (재료 대비 가격 과도)
- news_quality: 단순 추측성/루머 vs 실적/수주 확정

[출력 규칙]
- 함정 가능성이 명확하면 flags 에 1-3개 항목 (severity: HIGH/MEDIUM/LOW)
- 각 flag 의 evidence 는 위 [정량 데이터] 또는 [매수 사유] 에서 인용
- 함정 신호 없으면 flags=[], verdict="PASS"
- verdict: PASS(문제없음) | WARN(MEDIUM 이상 1개+) | BLOCK(HIGH 2개+)

JSON 형식으로만 응답:
{{
  "flags": [
    {{"category": "volume_decay", "severity": "HIGH", "evidence": "거래량배수 0.7x — 5일 평균 대비 30% 감소"}}
  ],
  "verdict": "WARN",
  "reasoning": "한 문장으로 종합 평가"
}}"""

        try:
            response = await asyncio.wait_for(
                self.client.messages.create(
                    model=self.model_name,
                    max_tokens=1024,
                    system="You are a conservative Korean stock risk analyst. Find traps, not opportunities. Respond only in valid JSON.",
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=self.timeout,
            )
            content = response.content[0].text.strip()

            # 비용 계산
            cost = (response.usage.input_tokens / 1_000_000) * self.HAIKU_INPUT_PRICE + \
                   (response.usage.output_tokens / 1_000_000) * self.HAIKU_OUTPUT_PRICE

            # JSON 파싱 (graceful)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if not match:
                    return {"flags": [], "verdict": "PASS", "reasoning": "JSON parse failed", "_cost_usd": cost}
                parsed = json.loads(match.group())

            # verdict 검증 (스키마 안전)
            verdict = parsed.get("verdict", "PASS").upper()
            if verdict not in ("PASS", "WARN", "BLOCK"):
                verdict = "PASS"

            # flags 정규화
            raw_flags = parsed.get("flags", []) or []
            flags = []
            for f in raw_flags:
                if not isinstance(f, dict):
                    continue
                sev = str(f.get("severity", "LOW")).upper()
                if sev not in ("HIGH", "MEDIUM", "LOW"):
                    sev = "LOW"
                flags.append({
                    "category": str(f.get("category", "unknown"))[:32],
                    "severity": sev,
                    "evidence": str(f.get("evidence", ""))[:200],
                })

            return {
                "flags": flags[:5],  # 상한
                "verdict": verdict,
                "reasoning": str(parsed.get("reasoning", ""))[:300],
                "_cost_usd": cost,
            }

        except asyncio.TimeoutError:
            logger.warning(f"[DevilAdvocate] {stock_code} timeout after {self.timeout}s")
            return {"flags": [], "verdict": "PASS", "reasoning": "timeout", "_cost_usd": 0.0}
        except Exception as e:
            logger.warning(f"[DevilAdvocate] {stock_code} review error: {type(e).__name__}: {e}")
            return {"flags": [], "verdict": "PASS", "reasoning": f"error: {e}", "_cost_usd": 0.0}


if __name__ == "__main__":
    # 간단한 테스트
    async def test():
        analyzer = LLMAnalyzer()
        print("🔍 분석 테스트 시작: 삼성전자")
        result = await analyzer.analyze_news_sentiment("삼성전자", [])
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(test())
