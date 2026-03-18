#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 경제 분석 요약기 (한국 컨텍스트 포함)
Gemini API를 통한 경제 지표 종합 분석
"""

import os
import requests
from typing import List, Dict, Optional
import logging

from dotenv import load_dotenv

# Load .env from parent directory
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EconAISummarizer:
    """Gemini 기반 경제 분석 요약"""
    
    def __init__(self):
        self.api_key = os.getenv('GOOGLE_API_KEY')
        # 가장 강력한 모델 사용
        self.model = os.getenv('GEMINI_MODEL', 'gemini-3-pro-preview')
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not found. AI summarization will not work.")
    
    def summarize(self, indicators: List[str], 
                  indicator_data: Dict,
                  question: str = None,
                  include_kr_context: bool = True) -> str:
        """
        경제 지표 AI 요약 생성
        
        Args:
            indicators: 선택된 지표 ID 리스트
            indicator_data: 지표별 현재 데이터
            question: 사용자 질문 (선택)
            include_kr_context: 한국 섹터 점수 컨텍스트 포함 여부
        """
        if not self.api_key:
            return "⚠️ GOOGLE_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요."
        
        prompt = self._build_prompt(indicators, indicator_data, question, include_kr_context)
        return self._call_api(prompt)
    
    def _build_prompt(self, indicators: List[str], data: Dict,
                      question: str, include_kr: bool) -> str:
        """프롬프트 생성"""
        
        prompt = """당신은 미국과 한국 경제를 분석하는 전문 이코노미스트입니다.
아래 데이터를 바탕으로 현재 경제 상황을 분석해주세요.

## 선택된 경제 지표
"""
        # 지표 데이터 추가
        for ind in indicators:
            if ind in data:
                d = data[ind]
                prompt += f"- **{d.get('name', ind)}**: {d.get('value')} "
                change_pct = d.get('change_pct', 0)
                emoji = '📈' if change_pct > 0 else '📉' if change_pct < 0 else '➡️'
                prompt += f"({emoji} 전월비: {change_pct:+.1f}%)\n"
        
        # 한국 컨텍스트 추가
        if include_kr:
            prompt += """

## 한국 경제 섹터별 현황 (2019-2025 누적 점수, 한국은행 데이터 기반)

| 섹터 | 누적점수 | 상태 | 최근 동향 |
|------|---------|------|----------|
| 반도체/IT | +27 | 🟢 강세 | AI반도체 호황, K자형 성장 주도 |
| 건설/부동산 | -42 | 🔴 위기 | PF리스크, 건설투자 역성장 지속 |
| 금융/은행 | -26 | 🔴 위기 | 금리 부담, 가계부채 리스크 |
| 일반제조 | -3 | ⚪ 중립 | 반도체 제외 부진 |
| 서비스 | -11 | 🟡 부진 | 내수 회복 중 |
| 수출/무역 | +18 | 🔵 양호 | 반도체 수출 견인 |
| 고용/노동 | +1 | ⚪ 중립 | 고용 상대적 안정 |
| 물가/인플레 | -18 | 🟡 부진 | 환율 불안 (1480원대) |

## 최근 주요 이벤트
- 2024.12: 12.3 비상계엄 → 정치불안, 환율 급등
- 2025: K자형 성장 지속 (IT↑ 비IT↓), GDP 성장률 1.0% 전망
- 한은 기준금리 2.5% (4회 연속 동결 후 인하 기대)
- 2026년 전망: GDP 1.8%, 내수 중심 회복 기대
"""
        
        if question:
            prompt += f"\n## 💬 사용자 질문\n{question}\n"
        
        prompt += """

## 분석 요청
위 데이터를 바탕으로:
1. **현재 경제 상황 요약** (한미 비교 포함, 2-3문장)
2. **주요 리스크 요인** (3가지)
3. **투자 시사점** (섹터별 전략)
4. **향후 전망** (3-6개월)

을 분석해주세요. 

**형식 요구사항:**
- 한국어로 답변
- 이모지 적절히 사용
- 핵심만 간결하게 (총 500단어 이내)
- 마크다운 형식 사용
"""
        return prompt
    
    def _call_api(self, prompt: str) -> str:
        """Gemini API 호출"""
        headers = {'Content-Type': 'application/json'}
        
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {
                'temperature': 0.7,
                'maxOutputTokens': 2048,
            }
        }
        
        try:
            response = requests.post(
                f"{self.base_url}?key={self.api_key}",
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            
            # 응답 파싱
            if 'candidates' in result and len(result['candidates']) > 0:
                parts = result['candidates'][0].get('content', {}).get('parts', [])
                if parts:
                    return parts[0].get('text', 'AI 분석 결과를 파싱할 수 없습니다.')
            
            return "AI 분석 결과가 비어있습니다."
            
        except requests.exceptions.Timeout:
            logger.error("Gemini API timeout")
            return "⚠️ AI 분석 시간 초과 (60초). 나중에 다시 시도해주세요."
        except requests.exceptions.RequestException as e:
            logger.error(f"Gemini API error: {e}")
            return f"⚠️ AI 분석 오류: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return f"⚠️ 예상치 못한 오류: {str(e)}"
    
    def quick_analysis(self, topic: str = 'market_outlook') -> str:
        """
        빠른 분석 (사전 정의된 주제)
        
        Args:
            topic: 'market_outlook', 'sector_rotation', 'risk_assessment'
        """
        prompts = {
            'market_outlook': "현재 미국과 한국 주식시장의 단기 전망을 100단어로 요약해주세요.",
            'sector_rotation': "현재 경제 상황에서 유망한 섹터와 피해야 할 섹터를 알려주세요.",
            'risk_assessment': "현재 글로벌 경제의 주요 리스크 요인 3가지를 설명해주세요."
        }
        
        prompt = prompts.get(topic, prompts['market_outlook'])
        return self._call_api(prompt)


if __name__ == "__main__":
    # 테스트
    summarizer = EconAISummarizer()
    
    print("\n🤖 AI Summarizer Test\n")
    
    if not summarizer.api_key:
        print("⚠️ GOOGLE_API_KEY not set")
    else:
        # 간단한 요약 테스트
        sample_data = {
            'DGS10': {'name': '10Y Treasury', 'value': 4.25, 'change_pct': 0.5},
            '^VIX': {'name': 'VIX', 'value': 18.5, 'change_pct': -3.2},
        }
        
        result = summarizer.summarize(
            indicators=['DGS10', '^VIX'],
            indicator_data=sample_data,
            question="현재 시장 상황은?"
        )
        print(result[:500] + "..." if len(result) > 500 else result)
        
    print("\n✅ EconAISummarizer test passed!")
