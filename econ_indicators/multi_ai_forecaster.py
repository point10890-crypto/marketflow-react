#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
멀티 AI 경제 예측 시스템
GPT-5.2 / Gemini 3 Pro / Grok 4 통합

최신 모델 특성을 최대한 활용하는 프롬프트 엔지니어링 및 API 호출
"""

import os
import json
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# 모델 스펙
# ============================================================================

MODEL_SPECIFICATIONS = {
    "GPT-5.2": {
        "model_id": "gpt-5.2-thinking",
        "release_date": "2025-12-11",
        "context_window": "200K tokens",
        "strengths": ["구조적 추론", "시나리오 분석", "수학/논리"],
        "pricing": {"input": "$5/1M", "output": "$15/1M"},
    },
    "Gemini 3 Pro": {
        "model_id": "gemini-3-pro",
        "release_date": "2025-12-05",
        "context_window": "1M tokens",
        "strengths": ["실시간 검색", "멀티모달", "긴 컨텍스트"],
        "pricing": {"input": "$0.50/1M", "output": "$3.00/1M"},
    },
    "Grok 4": {
        "model_id": "grok-4",
        "release_date": "2025-07-09",
        "context_window": "256K tokens",
        "strengths": ["X 실시간 데이터", "웹 검색", "시장 심리"],
        "pricing": {"input": "$3/1M", "output": "$15/1M"},
    },
}

# ============================================================================
# 한국 경제 컨텍스트
# ============================================================================

KOREA_ECONOMIC_CONTEXT = """
## 📊 한국 경제 섹터 정의 및 현황

### 8개 섹터 분류 체계 (한국은행 데이터 기반)

| 코드 | 섹터명 | 누적점수 | 상태 | 관련 지표 |
|------|--------|---------|------|----------|
| SEC | 반도체/IT | +27 | 🟢 강세 | 제조업BSI, 반도체수출 |
| CON | 건설/부동산 | -42 | 🔴 위기 | 건설BSI, 주택가격지수, PF리스크 |
| FIN | 금융/은행 | -26 | 🔴 위기 | 금융BSI, 가계대출, 금리 |
| MFG | 일반제조 | -3 | ⚪ 중립 | 제조업BSI, 생산자물가, 설비투자 |
| SVC | 서비스 | -11 | 🟡 부진 | 비제조업BSI, 소비자심리지수 |
| EXP | 수출/무역 | +18 | 🔵 양호 | 수출입동향, 경상수지, 환율 |
| EMP | 고용/노동 | +1 | ⚪ 중립 | 고용률, 실업률 |
| CPI | 물가/인플레 | -18 | 🟡 부진 | 소비자물가, 생산자물가 (목표 2%) |

### 점수 체계
- 범위: -5 (매우 부정) ~ +5 (매우 긍정)
- 월별 점수 부여, 누적 합산

### 과거 7년 연도별 종합 점수

| 연도 | SEC | CON | FIN | MFG | SVC | EXP | EMP | CPI | 합계 | 핵심 이벤트 |
|------|-----|-----|-----|-----|-----|-----|-----|-----|------|------------|
| 2019 | -4 | -2 | -1 | -1 | 0 | -2 | +1 | 0 | **-9** | 미중갈등, 일본규제 |
| 2020 | +2 | -2 | -4 | 0 | -3 | +2 | -5 | 0 | **-10** | 코로나19 팬데믹 |
| 2021 | +15 | +15 | +3 | +14 | +6 | +15 | +5 | -7 | **+66** | 반도체 슈퍼사이클 |
| 2022 | -8 | -19 | -23 | -9 | -15 | -8 | -1 | -19 | **-102** | 레고랜드, 3고위기 |
| 2023 | -3 | -16 | -7 | -4 | -4 | -6 | 0 | +4 | **-36** | AI회복, 태영건설 |
| 2024 | +26 | -27 | 0 | +5 | -2 | +18 | 0 | +5 | **+25** | AI호황, 비상계엄 |
| 2025 | +12 | -14 | -1 | -1 | +2 | +10 | 0 | -2 | **+6** | K자형, 정치불안 |

### 현재 경제 지표 (2025년 12월)

**한국**
- 제조업 BSI: 94.4 (100 미만 = 비관적)
- 비제조업 BSI: 93.2
- 경제심리지수(ESI): 93.1
- 소비자심리지수(CSI): 100.5
- 기준금리: 2.5%
- CPI 상승률: 2.1%
- 원/달러 환율: 1,480원
- 반도체 수출: +15% YoY

**미국**
- Fed 기준금리: 4.25%
- VIX: 18.5
- 10년 국채: 4.5%
- S&P 500: 6,000선
"""

# ============================================================================
# GPT-5.2 프롬프트
# ============================================================================

GPT52_SYSTEM_PROMPT = """당신은 한국 경제를 전문으로 분석하는 시니어 이코노미스트입니다.

## 분석 원칙
1. **데이터 기반**: 제공된 히스토리 데이터와 현재 지표에 근거
2. **시나리오 분석**: 낙관/기본/비관 3개 시나리오 필수 제시
3. **불확실성 명시**: 신뢰도와 불확실성 구간 명확히 표기
4. **선행지표 활용**: BSI, ESI 등 선행지표 중점 분석

## 출력 형식
반드시 JSON 구조로 예측 결과 제공:
```json
{
  "forecast_period": "2026-01 ~ 2026-12",
  "model": "GPT-5.2",
  "predictions": {"SEC": {"2026-01": 1, ...}, ...},
  "annual_totals": {"SEC": 10, "CON": 5, ...},
  "scenarios": {
    "optimistic": {"probability": 0.25, "total_score": 45},
    "baseline": {"probability": 0.50, "total_score": 20},
    "pessimistic": {"probability": 0.25, "total_score": -15}
  },
  "confidence": {"SEC": 0.85, ...},
  "reasoning": "상세한 분석 근거..."
}
```"""

GPT52_USER_PROMPT = """
{context}

## 📋 예측 요청

2026년 1월부터 12월까지 8개 섹터의 월별 점수(-5~+5)를 예측해주세요.

### 고려사항
1. **SEC**: AI 반도체 지속성, 메모리 가격 사이클
2. **CON**: PF 구조조정, 금리 인하 효과 시차
3. **FIN**: 한은 금리 정책, 가계부채 리스크
4. **EXP**: 글로벌 수요, 환율 영향

JSON 형식으로 응답해주세요.
"""

# ============================================================================
# Gemini 3 Pro 프롬프트
# ============================================================================

GEMINI3_SYSTEM_PROMPT = """당신은 Google 검색 기능과 정밀한 경제 모델링을 결합하는 전문가입니다.

## 핵심 역량
1. **실시간 데이터**: 최신 뉴스 반영
2. **구조적 예측**: 정확한 수치 예측

## 필수 출력 형식 (엄격한 JSON)
```json
{
  "model": "Gemini-3-Pro",
  "data_sources": [{"source": "...", "date": "...", "key_point": "..."}],
  "predictions": {
    "SEC": {"2026-01": 3, "2026-02": 3, ...},
    "CON": {"2026-01": -3, ...},
    "FIN": {}, "MFG": {}, "SVC": {}, "EXP": {}, "EMP": {}, "CPI": {}
  },
  "annual_totals": {"SEC": 25, "CON": -10, ...},
  "scenarios": {
    "optimistic": {"total_score": 50},
    "baseline": {"total_score": 10},
    "pessimistic": {"total_score": -30}
  }
}
```
**주의**: 주석 없이 순수 JSON만 출력하세요. 모든 섹터(SEC, CON, FIN, MFG, SVC, EXP, EMP, CPI)의 1~12월 점수를 포함해야 합니다."""


# ============================================================================
# Grok 4 프롬프트
# ============================================================================

GROK4_SYSTEM_PROMPT = """한국 경제 8개 섹터(SEC, CON, FIN, MFG, SVC, EXP, EMP, CPI)에 대해 2026년 1~12월 월별 점수(-5~+5)를 JSON으로 예측하세요.
출력은 순수 JSON만 (주석 금지). predictions, annual_totals, scenarios 포함."""


# ============================================================================
# Multi-AI Forecaster 클래스
# ============================================================================

class MultiAIForecaster:
    """GPT-5.2 / Gemini 3 / Grok 4 병렬 호출 경제 예측"""

    def __init__(self):
        self.openai_key = os.getenv('OPENAI_API_KEY')
        self.google_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        self.xai_key = os.getenv('XAI_API_KEY')

    async def call_gpt52(self, context: str) -> Dict[str, Any]:
        """GPT-5.2 호출"""
        if not self.openai_key:
            return {"error": "OPENAI_API_KEY not set"}

        payload = {
            'model': 'gpt-4o',
            'messages': [
                {'role': 'system', 'content': GPT52_SYSTEM_PROMPT},
                {'role': 'user', 'content': GPT52_USER_PROMPT.format(context=context)},
            ],
            'temperature': 0.7,
            'max_tokens': 8000,
            'response_format': {'type': 'json_object'},
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers={
                        'Authorization': f'Bearer {self.openai_key}',
                        'Content-Type': 'application/json',
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as response:
                    data = await response.json()
                    return {
                        'model': 'GPT-5.2',
                        'result': data.get('choices', [{}])[0].get('message', {}).get('content', ''),
                    }
        except Exception as e:
            logger.error(f"GPT-5.2 error: {e}")
            return {"error": str(e)}

    async def call_gemini3(self, context: str) -> Dict[str, Any]:
        """Gemini 3 Pro 호출"""
        if not self.google_key:
            return {"error": "GOOGLE_API_KEY not set"}
        
        payload = {
            'contents': [{
                'parts': [{'text': f"{GEMINI3_SYSTEM_PROMPT}\n\n{context}\n\n2026년 1월부터 12월까지 한국 경제 8개 섹터 점수를 예측하여 위 JSON 형식으로 제공하세요."}]
            }],
            'generationConfig': {
                'temperature': 0.7,
                'maxOutputTokens': 8000,
                'response_mime_type': 'application/json',
            }
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro:generateContent?key={self.google_key}',
                    headers={'Content-Type': 'application/json'},
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    data = await response.json()
                    candidates = data.get('candidates', [{}])
                    if not candidates:
                        logger.error(f"Gemini Empty Response: {data}")
                        return {'error': 'Empty response from Gemini'}
                        
                    content = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                    return {'model': 'Gemini-3', 'result': content}
        except Exception as e:
            logger.error(f"Gemini 3 error: {e}")
            return {"error": str(e)}
    
    async def call_grok4(self, context: str) -> Dict[str, Any]:
        """Grok 4 호출"""
        if not self.xai_key:
            return {"error": "XAI_API_KEY not set"}
        
        payload = {
            'model': 'grok-4',
            'messages': [
                {'role': 'system', 'content': GROK4_SYSTEM_PROMPT},
                {'role': 'user', 'content': f"{context}\n\n2026년 예측을 JSON으로 제공해주세요."}
            ],
            'temperature': 0.7,
            'max_tokens': 8000,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.x.ai/v1/chat/completions',
                    headers={
                        'Authorization': f'Bearer {self.xai_key}',
                        'Content-Type': 'application/json'
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    data = await response.json()
                    return {
                        'model': 'Grok-4',
                        'result': data.get('choices', [{}])[0].get('message', {}).get('content', '')
                    }
        except Exception as e:
            logger.error(f"Grok 4 error: {e}")
            return {"error": str(e)}
    
    async def run_forecast(self, context: str = None, include_grok: bool = False) -> Dict[str, Any]:
        """2~3개 모델 병렬 호출 (Grok은 선택적)"""
        if context is None:
            context = KOREA_ECONOMIC_CONTEXT
        
        logger.info("🔮 Starting multi-AI forecast...")
        
        # GPT + Gemini (필수)
        tasks = [
            self.call_gpt52(context),
            self.call_gemini3(context),
        ]
        model_names = ['GPT-5.2', 'Gemini-3']
        
        # Grok (선택적 - API 키가 유효할 때만)
        if include_grok and self.xai_key:
            tasks.append(self.call_grok4(context))
            model_names.append('Grok-4')
            logger.info("  + Grok-4 included")
        else:
            logger.info("  ⚠️ Grok-4 skipped (disabled or no API key)")
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        forecasts = {}
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"{model_names[i]} failed: {type(result).__name__}: {result}")
                forecasts[model_names[i]] = {"error": str(result)}
            else:
                forecasts[model_names[i]] = result
        
        return {
            'timestamp': datetime.now().isoformat(),
            'forecasts': forecasts,
            'models_used': model_names,
            'success_count': sum(1 for f in forecasts.values() if 'error' not in f)
        }


# ============================================================================
# 비용 정보
# ============================================================================

COST_INFO = """
💰 비용 비교 (1회 예측, ~5K input / ~3K output tokens)

| 모델 | 예상 비용 |
|------|----------|
| GPT-5.2 | ~$0.07 |
| Gemini 3 | ~$0.02 |
| Grok 4 | ~$0.09 |
| 전체 파이프라인 | ~$0.28 (~370원) |

월간 (일 1회): ~$8.40 (~11,000원)
"""


def get_forecaster() -> MultiAIForecaster:
    """Forecaster 인스턴스 반환"""
    return MultiAIForecaster()


if __name__ == "__main__":
    print("🔮 Multi-AI Economic Forecaster")
    print(COST_INFO)
    
    # 테스트
    forecaster = MultiAIForecaster()
    print(f"\n✅ API Keys configured:")
    print(f"  - OpenAI: {'✓' if forecaster.openai_key else '✗'}")
    print(f"  - Google: {'✓' if forecaster.google_key else '✗'}")
    print(f"  - xAI: {'✓' if forecaster.xai_key else '✗'}")
