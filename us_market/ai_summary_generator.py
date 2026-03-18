#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Stock Summary Generator v2.0
Combines quantitative data with news to generate investment summaries

Supported AI Models:
- Google Gemini (default)
- OpenAI GPT-4
- Anthropic Claude
- Local Models (via Ollama)

Usage:
    python ai_summary_generator.py --provider gemini --top 20
    python ai_summary_generator.py --provider openai --ticker AAPL
    python ai_summary_generator.py --provider claude --refresh
"""

import os
import pandas as pd
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from abc import ABC, abstractmethod
import requests
from tqdm import tqdm
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NewsCollector:
    """Collect news for stocks from multiple sources"""
    
    def __init__(self, finnhub_key: str = None):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.finnhub_key = finnhub_key or os.getenv('FINNHUB_API_KEY')
    
    def get_yahoo_news(self, ticker: str, limit: int = 3) -> List[Dict]:
        """Get news from Yahoo Finance"""
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            news = stock.news
            
            if not news:
                return []
            
            articles = []
            for item in news[:limit]:
                articles.append({
                    'title': item.get('title', ''),
                    'publisher': item.get('publisher', 'Yahoo Finance'),
                    'link': item.get('link', ''),
                    'published': datetime.fromtimestamp(item.get('providerPublishTime', 0)).strftime('%Y-%m-%d'),
                    'source': 'Yahoo'
                })
            
            return articles
            
        except Exception as e:
            logger.debug(f"Yahoo news error for {ticker}: {e}")
            return []
    
    def get_google_news(self, ticker: str, company_name: str = None, limit: int = 3) -> List[Dict]:
        """Get news from Google News RSS"""
        try:
            import xml.etree.ElementTree as ET
            from urllib.parse import quote
            
            # Search query: ticker + company name
            query = f"{ticker} stock"
            if company_name and company_name != ticker:
                query = f'"{company_name}" OR {ticker} stock'
            
            url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
            
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code != 200:
                return []
            
            root = ET.fromstring(response.content)
            articles = []
            
            for item in root.findall('.//item')[:limit]:
                title = item.find('title')
                pub_date = item.find('pubDate')
                link = item.find('link')
                source = item.find('source')
                
                if title is not None:
                    # Parse date
                    date_str = pub_date.text if pub_date is not None else ''
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(date_str)
                        formatted_date = dt.strftime('%Y-%m-%d')
                    except:
                        formatted_date = datetime.now().strftime('%Y-%m-%d')
                    
                    articles.append({
                        'title': title.text,
                        'publisher': source.text if source is not None else 'Google News',
                        'link': link.text if link is not None else '',
                        'published': formatted_date,
                        'source': 'Google'
                    })
            
            return articles
            
        except Exception as e:
            logger.debug(f"Google news error for {ticker}: {e}")
            return []
    
    def get_finnhub_news(self, ticker: str, limit: int = 3) -> List[Dict]:
        """Get news from Finnhub API (requires API key)"""
        if not self.finnhub_key:
            return []
        
        try:
            from datetime import date, timedelta
            
            # Get news from last 7 days
            to_date = date.today()
            from_date = to_date - timedelta(days=7)
            
            url = f"https://finnhub.io/api/v1/company-news"
            params = {
                'symbol': ticker,
                'from': from_date.isoformat(),
                'to': to_date.isoformat(),
                'token': self.finnhub_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return []
            
            news_data = response.json()
            articles = []
            
            for item in news_data[:limit]:
                articles.append({
                    'title': item.get('headline', ''),
                    'publisher': item.get('source', 'Finnhub'),
                    'link': item.get('url', ''),
                    'published': datetime.fromtimestamp(item.get('datetime', 0)).strftime('%Y-%m-%d'),
                    'source': 'Finnhub',
                    'summary': item.get('summary', '')[:200]  # Finnhub provides summaries
                })
            
            return articles
            
        except Exception as e:
            logger.debug(f"Finnhub news error for {ticker}: {e}")
            return []
    
    def get_news_for_ticker(self, ticker: str, company_name: str = None) -> List[Dict]:
        """Get aggregated news from all sources"""
        all_news = []
        
        # 1. Yahoo Finance (always available)
        yahoo_news = self.get_yahoo_news(ticker, limit=3)
        all_news.extend(yahoo_news)
        logger.debug(f"  Yahoo: {len(yahoo_news)} articles")
        
        # 2. Google News RSS (more comprehensive)
        google_news = self.get_google_news(ticker, company_name, limit=3)
        all_news.extend(google_news)
        logger.debug(f"  Google: {len(google_news)} articles")
        
        # 3. Finnhub (if API key available)
        if self.finnhub_key:
            finnhub_news = self.get_finnhub_news(ticker, limit=3)
            all_news.extend(finnhub_news)
            logger.debug(f"  Finnhub: {len(finnhub_news)} articles")
        
        # Remove duplicates based on title similarity
        unique_news = self._deduplicate_news(all_news)
        
        # Sort by date (newest first) and limit
        unique_news.sort(key=lambda x: x.get('published', ''), reverse=True)
        
        return unique_news[:8]  # Return top 8 unique articles
    
    def _deduplicate_news(self, news: List[Dict]) -> List[Dict]:
        """Remove duplicate news based on title similarity"""
        seen_titles = set()
        unique = []
        
        for article in news:
            # Simple dedup: first 50 chars of title
            title_key = article['title'][:50].lower()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(article)
        
        return unique


class GeminiSummaryGenerator:
    """Generate stock summaries using Gemini AI"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not found in environment")
        
        # Gemini 3.0 Pro Preview (User Requested)
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-preview:generateContent"
    
    def generate_summary(self, ticker: str, data: Dict, news: List[Dict], lang: str = 'ko', macro_context: Dict = None) -> str:
        """Generate AI summary for a stock"""
        
        # Build prompt with all data
        prompt = self._build_prompt(ticker, data, news, lang, macro_context)
        
        try:
            response = requests.post(
                f"{self.base_url}?key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "role": "user",  # Required for Gemini 3.0
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 4000,
                        "thinkingConfig": {
                            "thinkingLevel": "low"
                        }
                    }
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Robust extraction
                try:
                    candidates = result.get('candidates', [])
                    if not candidates:
                        logger.warning(f"No candidates returned for {ticker}. Result: {result}")
                        return self._get_fallback_json(ticker, "AI Analysis Unavailable (No Candidates)")
                        
                    candidate = candidates[0]
                    # Check for safety blocks
                    if candidate.get('finishReason') == 'SAFETY':
                        logger.warning(f"Safety filter triggered for {ticker}")
                        return self._get_fallback_json(ticker, "AI Analysis Blocked by Safety Filter")
                        
                    parts = candidate.get('content', {}).get('parts', [])
                    if not parts:
                        logger.warning(f"No content parts for {ticker}. Result: {result}")
                        return self._get_fallback_json(ticker, "AI Analysis Unavailable (Empty Content)")
                        
                    text = parts[0]['text']
                    return text.strip()
                    
                except Exception as e:
                    logger.error(f"Error parsing Gemini response for {ticker}: {e} -> {result}")
                    return self._get_fallback_json(ticker, f"Error parsing AI response: {str(e)}")
            else:
                logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                return self._get_fallback_json(ticker, f"API Error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error generating summary for {ticker}: {e}")
            return self._get_fallback_json(ticker, f"Connection Error: {str(e)}")

    def _get_fallback_json(self, ticker: str, reason: str) -> str:
        """Return a valid JSON string for error cases"""
        import json
        fallback = {
            "thesis": f"AI Analaysis Failed: {reason}",
            "catalysts": [],
            "bear_cases": [],
            "data_conflicts": ["AI Generation Error"],
            "key_metrics": {},
            "recommendation": "HOLD",
            "confidence": 0
        }
        return json.dumps(fallback, ensure_ascii=False)
    
    def _build_prompt(self, ticker: str, data: Dict, news: List[Dict], lang: str = 'ko', macro_context: Dict = None) -> str:
        """Build the prompt for Gemini with structured JSON output"""
        
        # Macro Context String Construction
        macro_text = ""
        if macro_context:
            indicators = macro_context.get('macro_indicators', {})
            vix = indicators.get('VIX', {}).get('value', 'N/A')
            yield_10y = indicators.get('10Y_Yield', {}).get('value', 'N/A')
            ai_macro_summary = macro_context.get('ai_analysis', 'N/A')
            
            # Extract only the summary part if it's too long (optional)
            if len(ai_macro_summary) > 500 and lang == 'en':
                ai_macro_summary = ai_macro_summary[:500] + "..."

            if lang == 'en':
                macro_text = f"""
## Market Context (Macro Environment)
- VIX (Volatility): {vix} (High > 20 is Fear)
- 10Y Treasury Yield: {yield_10y}%
- Market Regime Analysis:
{ai_macro_summary}
"""
            else:
                macro_text = f"""
## 시장 상황 (Macro Context)
- VIX (공포지수): {vix} (20 이상은 공포)
- 10년물 국채 금리: {yield_10y}%
- 시장 전체 분석 요약:
{ai_macro_summary}
"""

        # Format news
        news_text = ""
        if news:
            news_items = []
            for i, article in enumerate(news[:5], 1):
                news_items.append(f"{i}. [{article['published']}] {article['title']}")
            news_text = "\n".join(news_items)
        else:
            news_text = "No recent news" if lang == 'en' else "최근 주요 뉴스 없음"
        
        if lang == 'en':
            prompt = f"""You are a professional hedge fund analyst. Analyze the following data and provide a structured investment opinion WITH EVIDENCE.
{macro_text}
## Stock Information
- Ticker: {ticker}
- Company: {data.get('name', ticker)}
- Current Price: ${data.get('current_price', 0):.2f}
- Grade: {data.get('grade', 'N/A')}
- Total Score: {data.get('composite_score', 0)}/100

## Technical Analysis
- Supply/Demand Score: {data.get('sd_score', 0)}/100 ({data.get('sd_stage', 'N/A')})
- Institutional Ownership: {data.get('inst_pct', 0):.1f}%
- RSI: {data.get('rsi', 0)}
- MA Signal: {data.get('ma_signal', 'N/A')}
- P/E: {data.get('pe', 'N/A')}
- Revenue Growth: {data.get('revenue_growth', 0)}%
- Target Upside: {data.get('target_upside', 0):+.1f}%
- vs S&P 500: {data.get('rs_vs_spy_20d', 0):+.1f}%

## Recent News (USE THESE AS EVIDENCE)
{news_text}

## CRITICAL: Response Format
Respond ONLY with valid JSON. adhere strictly to these rules:
1. EVIDENCE: Every catalyst and risk MUST have a source/date citation.
2. BEAR CASES: Provide exactly 3 separate risks, even if the stock is a Strong Buy.
3. CONFLICTS: Highlight any mismatch between data (e.g. good Technicals vs bad News).

JSON Structure:
{{
  "thesis": "1-2 sentence core investment thesis based on specific data",
  "catalysts": [
    {{
      "point": "Catalyst description",
      "evidence": "Specific data/quote [Source, Date]"
    }}
  ],
  "bear_cases": [
    {{
      "point": "Risk 1 (e.g. Valuation Concern)",
      "evidence": "PE is 45x vs Sector 20x [Source]"
    }},
    {{
      "point": "Risk 2 (e.g. Insider Selling)",
      "evidence": "CEO sold $5M shares last month [SEC Form 4]"
    }},
    {{
      "point": "Risk 3 (e.g. Macro Headwind)",
      "evidence": "Rising yields hurt high P/E stocks [Macro Context]"
    }}
  ],
  "data_conflicts": ["Specific conflict: e.g. 'RSI is oversold (30) but News sentiment is very negative'"],
  "key_metrics": {{
    "pe": {data.get('pe', 'null')},
    "growth": {data.get('revenue_growth', 0)},
    "rsi": {data.get('rsi', 50)},
    "inst_pct": {data.get('inst_pct', 0):.1f}
  }},
  "recommendation": "BUY or HOLD or SELL",
  "confidence": 75
}}"""
        else:
            prompt = f"""당신은 전문 헤지펀드 애널리스트입니다. 다음 데이터를 분석하여 근거와 함께 구조화된 투자 의견을 작성해주세요.
{macro_text}
## 종목 정보
- 티커: {ticker}
- 회사명: {data.get('name', ticker)}
- 현재가: ${data.get('current_price', 0):.2f}
- 등급: {data.get('grade', 'N/A')}
- 종합점수: {data.get('composite_score', 0)}/100

## 수치 분석
- 수급 점수: {data.get('sd_score', 0)}/100 ({data.get('sd_stage', 'N/A')})
- 기관 보유: {data.get('inst_pct', 0):.1f}%
- RSI: {data.get('rsi', 0)}
- MA Signal: {data.get('ma_signal', 'N/A')}
- P/E: {data.get('pe', 'N/A')}
- 매출 성장률: {data.get('revenue_growth', 0)}%
- 목표가 대비: {data.get('target_upside', 0):+.1f}%
- S&P 500 대비: {data.get('rs_vs_spy_20d', 0):+.1f}%

## 최근 뉴스 (반드시 근거로 활용할 것)
{news_text}

## 중요: 응답 형식 (신뢰성 강화)
반드시 아래 JSON 형식으로만 응답하세요. 다음 규칙을 엄격히 준수하십시오:
1. **증거 제시(Evidence)**: 모든 주장에는 반드시 [출처, 날짜]를 명시해야 합니다. (예: "매출 20% 증가 [2024-Q3 실적발표]")
2. **반대 시나리오(Bear Cases)**: 매수 추천 종목이라도, 반드시 **3가지 구체적인 하락/리스크 시나리오**를 작성하십시오.
3. **데이터 충돌**: 기술적 지표와 펀더멘털/뉴스가 엇갈리는 경우 이를 명시하십시오.

JSON 구조:
{{
  "thesis": "핵심 투자 논거 1-2문장 (구체적 데이터 기반)",
  "catalysts": [
    {{
      "point": "상승 촉매 내용",
      "evidence": "이를 뒷받침하는 데이터/인용 [출처]"
    }}
  ],
  "bear_cases": [
    {{
      "point": "리스크 1 (예: 밸류에이션 부담)",
      "evidence": "PER 45배로 섹터 평균 20배 대비 고평가 [데이터]"
    }},
    {{
      "point": "리스크 2 (예: 내부자 매도)",
      "evidence": "CEO가 지난달 500만불 매도 [SEC 공시]"
    }},
    {{
      "point": "리스크 3 (예: 거시경제 역풍)",
      "evidence": "금리 상승으로 성장주 할인율 증가 [Macro Context]"
    }}
  ],
  "data_conflicts": ["예: 'RSI는 과매도(30)이나 뉴스 센티먼트는 매우 부정적임'"],
  "key_metrics": {{
    "pe": {data.get('pe', 'null')},
    "growth": {data.get('revenue_growth', 0)},
    "rsi": {data.get('rsi', 50)},
    "inst_pct": {data.get('inst_pct', 0):.1f}
  }},
  "recommendation": "BUY 또는 HOLD 또는 SELL",
  "confidence": 75
}}"""

        return prompt


class OpenAISummaryGenerator:
    """Generate stock summaries using OpenAI GPT-4"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")

        self.base_url = "https://api.openai.com/v1/chat/completions"
        self.model = "o3-mini"

    def generate_summary(self, ticker: str, data: Dict, news: List[Dict], lang: str = 'ko', macro_context: Dict = None) -> str:
        """Generate AI summary using OpenAI o3-mini"""
        # Reuse Gemini's prompt builder (same format works)
        gemini_gen = GeminiSummaryGenerator.__new__(GeminiSummaryGenerator)
        gemini_gen.api_key = ""  # Just for prompt building
        prompt = gemini_gen._build_prompt(ticker, data, news, lang, macro_context)

        try:
            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "developer", "content": "You are a professional hedge fund analyst. Always respond with valid JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    "reasoning_effort": "medium",
                    "max_completion_tokens": 8000
                },
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content'].strip()
            else:
                logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
                return self._get_fallback_json(ticker, f"API Error: {response.status_code}")

        except Exception as e:
            logger.error(f"Error generating summary for {ticker}: {e}")
            return self._get_fallback_json(ticker, str(e))

    def _get_fallback_json(self, ticker: str, reason: str) -> str:
        fallback = {
            "thesis": f"AI Analysis Failed: {reason}",
            "catalysts": [],
            "bear_cases": [],
            "data_conflicts": ["AI Generation Error"],
            "key_metrics": {},
            "recommendation": "HOLD",
            "confidence": 0
        }
        return json.dumps(fallback, ensure_ascii=False)


class PerplexitySummaryGenerator:
    """Generate stock summaries using Perplexity Sonar (with real-time web search)"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('PERPLEXITY_API_KEY')
        if not self.api_key:
            raise ValueError("PERPLEXITY_API_KEY not found in environment")

        self.base_url = "https://api.perplexity.ai/chat/completions"
        self.model = "sonar-pro"  # Real-time web search enabled

    def generate_summary(self, ticker: str, data: Dict, news: List[Dict], lang: str = 'ko', macro_context: Dict = None) -> str:
        """Generate AI summary using Perplexity with live web search"""
        gemini_gen = GeminiSummaryGenerator.__new__(GeminiSummaryGenerator)
        gemini_gen.api_key = ""
        base_prompt = gemini_gen._build_prompt(ticker, data, news, lang, macro_context)

        # Add web search instruction for Perplexity
        search_instruction = f"\n\nIMPORTANT: Search the web for the latest news and analyst opinions about {ticker} ({data.get('name', ticker)}) to supplement your analysis. Include any breaking news from the past 24-48 hours."

        try:
            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a professional hedge fund analyst with access to real-time web data. Always respond with valid JSON only."},
                        {"role": "user", "content": base_prompt + search_instruction}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 4000
                },
                timeout=90
            )

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content'].strip()
            else:
                logger.error(f"Perplexity API error: {response.status_code} - {response.text}")
                return self._get_fallback_json(ticker, f"API Error: {response.status_code}")

        except Exception as e:
            logger.error(f"Error generating summary for {ticker}: {e}")
            return self._get_fallback_json(ticker, str(e))

    def _get_fallback_json(self, ticker: str, reason: str) -> str:
        fallback = {
            "thesis": f"AI Analysis Failed: {reason}",
            "catalysts": [],
            "bear_cases": [],
            "data_conflicts": ["AI Generation Error"],
            "key_metrics": {},
            "recommendation": "HOLD",
            "confidence": 0
        }
        return json.dumps(fallback, ensure_ascii=False)


def get_ai_provider(provider: str = 'gemini'):
    """Factory function to get the appropriate AI provider

    Available providers:
    - gemini: Google Gemini 3 Pro (default, fast)
    - openai: OpenAI o3-mini (high quality reasoning)
    - perplexity: Perplexity Sonar Reasoning Pro (real-time web search + reasoning)
    """
    providers = {
        'gemini': GeminiSummaryGenerator,
        'openai': OpenAISummaryGenerator,
        'perplexity': PerplexitySummaryGenerator,
    }

    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(providers.keys())}")

    return providers[provider]()


class AIStockAnalyzer:
    """Main class for AI stock analysis with multi-provider support"""

    def __init__(self, data_dir: str = '.', provider: str = 'gemini'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'ai_summaries.json')
        self.provider_name = provider

        # Load existing summaries
        self.summaries = self._load_summaries()

        # Initialize components
        self.news_collector = NewsCollector()

        # Initialize AI provider with fallback
        try:
            self.summary_generator = get_ai_provider(provider)
            logger.info(f"✅ AI Provider: {provider.upper()}")
        except ValueError as e:
            logger.warning(f"⚠️ {e}. Falling back to Gemini.")
            self.summary_generator = GeminiSummaryGenerator()
    
    def _load_summaries(self) -> Dict:
        """Load existing summaries from cache"""
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_summaries(self):
        """Save summaries to cache"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(self.summaries, f, ensure_ascii=False, indent=2)
    
    def load_stock_data(self) -> pd.DataFrame:
        """Load the smart money picks data"""
        csv_path = os.path.join(self.data_dir, 'output', 'smart_money_picks_v2.csv')
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Smart money picks not found: {csv_path}")
        return pd.read_csv(csv_path)

    def _load_macro_context(self) -> Dict:
        """Load macro analysis context"""
        macro_file = os.path.join(self.data_dir, 'output', 'macro_analysis.json')
        if os.path.exists(macro_file):
            try:
                with open(macro_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load macro context: {e}")
        return None
        
    def analyze_stock(self, ticker: str, data: Dict, force_refresh: bool = False) -> Dict:
        """Analyze a single stock and generate summary in both languages"""
        
        # Check cache (summaries valid for 1 day)
        if not force_refresh and ticker in self.summaries:
            cached = self.summaries[ticker]
            cached_time = datetime.fromisoformat(cached.get('updated', '2000-01-01'))
            if datetime.now() - cached_time < timedelta(hours=24):
                return cached
        
        # Load Macro Context (New Feature)
        macro_context = self._load_macro_context()
        
        # Collect news (use company name for better search)
        company_name = data.get('name', ticker)
        news = self.news_collector.get_news_for_ticker(ticker, company_name)
        
        # Generate Korean summary
        summary_ko = self.summary_generator.generate_summary(ticker, data, news, 'ko', macro_context)
        
        # Generate English summary
        summary_en = self.summary_generator.generate_summary(ticker, data, news, 'en', macro_context)
        
        # Cache result with both languages and sources
        sources = [
            {
                'title': n.get('title', ''),
                'url': n.get('link', ''),
                'date': n.get('published', ''),
                'source': n.get('publisher', '')
            }
            for n in news[:5]
        ]
        
        self.summaries[ticker] = {
            'summary': summary_ko,  # Default (Korean) for backward compatibility
            'summary_ko': summary_ko,
            'summary_en': summary_en,
            'sources': sources,  # News sources used for analysis
            'news_count': len(news),
            'updated': datetime.now().isoformat()
        }
        self._save_summaries()
        
        return self.summaries[ticker]
    
    def run(self, top_n: int = 15, force_refresh: bool = False) -> Dict:
        """Generate summaries for top N stocks"""
        logger.info("🤖 Starting AI Stock Analysis...")
        
        # Load data
        df = self.load_stock_data()
        top_stocks = df.head(top_n)
        
        logger.info(f"📊 Analyzing top {len(top_stocks)} stocks")
        
        results = {}
        
        for idx, row in tqdm(top_stocks.iterrows(), total=len(top_stocks), desc="Generating AI Summaries"):
            ticker = row['ticker']
            data = row.to_dict()
            
            try:
                summary = self.analyze_stock(ticker, data, force_refresh)
                results[ticker] = summary
                time.sleep(0.5)  # Rate limiting
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")
                results[ticker] = f"분석 실패: {str(e)}"
        
        logger.info(f"✅ Generated {len(results)} AI summaries")
        logger.info(f"📁 Saved to {self.output_file}")
        
        return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description='AI Stock Summary Generator v2.0')
    parser.add_argument('--dir', default='.', help='Data directory')
    parser.add_argument('--top', type=int, default=20, help='Number of stocks to analyze')
    parser.add_argument('--refresh', action='store_true', help='Force refresh all summaries')
    parser.add_argument('--ticker', type=str, help='Analyze specific ticker')
    parser.add_argument('--provider', choices=['gemini', 'openai', 'perplexity'],
                        default='gemini', help='AI provider: gemini (default), openai (o3-mini), perplexity (web search + reasoning)')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"🤖 AI Stock Analyzer v2.0")
    print(f"   Provider: {args.provider.upper()}")
    print(f"{'='*60}\n")

    analyzer = AIStockAnalyzer(data_dir=args.dir, provider=args.provider)
    
    if args.ticker:
        # Analyze single ticker
        df = analyzer.load_stock_data()
        stock_data = df[df['ticker'] == args.ticker]
        if stock_data.empty:
            print(f"❌ Ticker {args.ticker} not found")
            return
        
        data = stock_data.iloc[0].to_dict()
        summary = analyzer.analyze_stock(args.ticker, data, force_refresh=True)
        print(f"\n🤖 AI Summary for {args.ticker}:\n")
        print(summary)
    else:
        # Analyze top N
        results = analyzer.run(top_n=args.top, force_refresh=args.refresh)
        
        print(f"\n{'='*80}")
        print("🤖 AI STOCK SUMMARIES")
        print(f"{'='*80}")
        
        for ticker, summary in list(results.items())[:5]:
            print(f"\n[{ticker}]")
            print(summary)
            print("-" * 40)


if __name__ == "__main__":
    main()
