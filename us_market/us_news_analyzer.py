#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Market News Analyzer (Perplexity + Gemini)

전략:
- Perplexity Sonar: 실시간 웹 검색으로 최신 영문 뉴스 수집
- Gemini: 수집된 뉴스 분석 및 호재 점수화 (0~3점)

사용법:
    python3 us_news_analyzer.py AAPL       # 단일 종목 분석
    python3 us_news_analyzer.py --batch    # Smart Money 종목 일괄 분석
"""

import os
import sys
import json
import asyncio
import aiohttp
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv

# 상위 디렉토리의 .env 파일 로드
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
load_dotenv()  # 현재 디렉토리도 체크


class USPerplexityClient:
    """Perplexity API 클라이언트 (US Market용)"""
    
    API_URL = "https://api.perplexity.ai/chat/completions"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("PERPLEXITY_API_KEY")
    
    async def search_stock_news(self, ticker: str, company_name: str = "") -> Dict:
        """
        Perplexity Sonar로 US 종목 관련 최신 뉴스 검색
        
        Returns:
            {
                "news_summary": "뉴스 요약",
                "citations": ["https://...", ...],
                "sentiment": "bullish|bearish|neutral"
            }
        """
        if not self.api_key:
            return {"news_summary": "", "citations": [], "sentiment": "neutral"}
        
        display_name = f"{ticker}" if not company_name else f"{company_name} ({ticker})"
        
        query = f"""
        Search for the latest news and market updates about "{display_name}" stock.
        
        Please provide:
        1. Breaking news from the last 24-48 hours (earnings, guidance, analyst ratings)
        2. Any recent SEC filings or insider trading activity
        3. Market sentiment and price target changes
        4. Sector/industry trends affecting this stock
        5. Institutional buying or selling activity
        
        Format your response in Korean (한국어). Be concise and focus on actionable information.
        """
        
        payload = {
            "model": "sonar",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert US stock market analyst. Provide accurate, objective information about stocks. Focus on recent news that could impact the stock price. Always respond in Korean."
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
            "return_citations": True,
            "search_recency_filter": "day"
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.API_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        print(f"[Perplexity Error] Status {response.status}: {error_text[:200]}")
                        return {"news_summary": "", "citations": [], "sentiment": "neutral"}
                    
                    data = await response.json()
                    
                    # Debug: print response structure
                    print(f"  > [Debug] Response keys: {data.keys()}")
                    
                    # 응답 파싱
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    citations = data.get("citations", [])
                    
                    # Perplexity 새 API는 citations가 다른 위치에 있을 수 있음
                    if not citations and "choices" in data:
                        msg = data["choices"][0].get("message", {})
                        citations = msg.get("citations", [])
                    
                    return {
                        "news_summary": content,
                        "citations": citations,
                        "sentiment": self._detect_sentiment(content)
                    }
        
        except asyncio.TimeoutError:
            print(f"[Perplexity] Timeout for {ticker}")
            return {"news_summary": "", "citations": [], "sentiment": "neutral"}
        except Exception as e:
            print(f"[Perplexity Error] {e}")
            return {"news_summary": "", "citations": [], "sentiment": "neutral"}
    
    def _detect_sentiment(self, content: str) -> str:
        """간단한 키워드 기반 센티멘트 감지"""
        bullish_keywords = ["상향", "호재", "급등", "매수", "목표가 상향", "실적 개선", "beat", "outperform"]
        bearish_keywords = ["하향", "악재", "급락", "매도", "목표가 하향", "실적 부진", "miss", "downgrade"]
        
        content_lower = content.lower()
        bullish_count = sum(1 for k in bullish_keywords if k in content_lower)
        bearish_count = sum(1 for k in bearish_keywords if k in content_lower)
        
        if bullish_count > bearish_count + 1:
            return "bullish"
        elif bearish_count > bullish_count + 1:
            return "bearish"
        return "neutral"


class USGeminiAnalyzer:
    """Gemini 기반 US 뉴스 분석기"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.model = None
        
        if not self.api_key:
            print("[Warning] GOOGLE_API_KEY not found")
        else:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel("gemini-2.0-flash")
            except ImportError:
                print("[Warning] google-generativeai not installed")
    
    async def analyze_news(self, ticker: str, news_content: str) -> Dict:
        """
        뉴스 내용을 분석하여 호재 점수(0~3)와 요약 생성
        
        Returns:
            {"score": 2, "reason": "...", "action": "BUY|HOLD|AVOID"}
        """
        if not self.model or not news_content:
            return {"score": 0, "reason": "뉴스 없음", "action": "HOLD"}
        
        prompt = f"""
다음은 미국 주식 {ticker}에 대한 최신 뉴스입니다:

{news_content}

위 뉴스를 분석하여 다음 형식의 JSON으로 응답해주세요:

{{
    "score": 0~3 사이의 정수 (0: 악재, 1: 중립, 2: 약간 호재, 3: 강한 호재),
    "reason": "점수 판단 이유 (한 줄 요약)",
    "action": "BUY" | "HOLD" | "AVOID",
    "catalysts": ["주요 호재/악재 1", "주요 호재/악재 2"],
    "risk": "주요 리스크 요인 (있는 경우)"
}}

JSON만 출력하세요.
"""
        
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self.model.generate_content, prompt),
                timeout=30
            )
            
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            
            result = json.loads(text)
            return {
                "score": int(result.get("score", 0)),
                "reason": result.get("reason", ""),
                "action": result.get("action", "HOLD"),
                "catalysts": result.get("catalysts", []),
                "risk": result.get("risk", "")
            }
        
        except asyncio.TimeoutError:
            print(f"[Gemini] Timeout for {ticker}")
            return {"score": 0, "reason": "분석 타임아웃", "action": "HOLD"}
        except Exception as e:
            print(f"[Gemini Error] {e}")
            return {"score": 0, "reason": str(e), "action": "HOLD"}


class USNewsAnalyzer:
    """US Market 통합 뉴스 분석기"""
    
    def __init__(self):
        self.perplexity = USPerplexityClient()
        self.gemini = USGeminiAnalyzer()
    
    async def analyze(self, ticker: str, company_name: str = "") -> Dict:
        """
        종목 뉴스 검색 및 분석
        
        Returns:
            {
                "ticker": "AAPL",
                "news_score": 2,
                "sentiment": "bullish",
                "reason": "...",
                "action": "BUY",
                "citations": [...],
                "analyzed_at": "..."
            }
        """
        print(f"  > [Perplexity] Searching news for {ticker}...")
        news_result = await self.perplexity.search_stock_news(ticker, company_name)
        
        print(f"  > [Perplexity] Found {len(news_result['citations'])} citations")
        
        if news_result["news_summary"]:
            print(f"  > [Gemini] Analyzing news...")
            analysis = await self.gemini.analyze_news(ticker, news_result["news_summary"])
        else:
            analysis = {"score": 0, "reason": "뉴스 없음", "action": "HOLD"}
        
        return {
            "ticker": ticker,
            "news_score": analysis.get("score", 0),
            "sentiment": news_result.get("sentiment", "neutral"),
            "reason": analysis.get("reason", ""),
            "action": analysis.get("action", "HOLD"),
            "catalysts": analysis.get("catalysts", []),
            "risk": analysis.get("risk", ""),
            "citations": news_result.get("citations", []),
            "analyzed_at": datetime.now().isoformat()
        }
    
    async def analyze_batch(self, tickers: List[str], delay: float = 1.0) -> List[Dict]:
        """여러 종목 일괄 분석"""
        results = []
        for ticker in tickers:
            result = await self.analyze(ticker)
            results.append(result)
            await asyncio.sleep(delay)  # Rate limiting
        return results


async def main():
    """테스트 실행"""
    analyzer = USNewsAnalyzer()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--batch":
            # Smart Money CSV에서 종목 로드
            import pandas as pd
            csv_path = os.path.join(os.path.dirname(__file__), "output/smart_money_picks_v2.csv")
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                tickers = df["ticker"].head(5).tolist()
                results = await analyzer.analyze_batch(tickers)
                
                # 결과 저장
                output_path = os.path.join(os.path.dirname(__file__), "output", "news_analysis.json")
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                print(f"\n✅ Saved to {output_path}")
            else:
                print("❌ smart_money_picks_v2.csv not found")
        else:
            ticker = sys.argv[1].upper()
            result = await analyzer.analyze(ticker)
            print(f"\n📊 {ticker} News Analysis:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 기본 테스트
        result = await analyzer.analyze("NVDA", "NVIDIA Corporation")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
