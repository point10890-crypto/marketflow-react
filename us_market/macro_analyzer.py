#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Macro Market Analyzer
- Collects macro indicators (Fed rate, VIX, DXY, yields, commodities)
- Compares current conditions to historical patterns
- Uses Gemini 3.0 AI to generate predictions and warnings
"""

import os
import json
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from dotenv import load_dotenv

# Load .env from current directory or parent directory
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MacroDataCollector:
    """Collect macro market data from various sources"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.fred_api_key = os.getenv('FRED_API_KEY')  # Optional
        
        # Comprehensive Macro tickers for yfinance
        self.macro_tickers = {
            # ===== Volatility & Risk =====
            'VIX': '^VIX',               # Fear Index
            'SKEW': '^SKEW',             # Tail Risk / Black Swan
            
            # ===== Currency =====
            'DXY': 'DX-Y.NYB',            # Dollar Index
            'EUR/USD': 'EURUSD=X',        # Euro/Dollar
            'USD/JPY': 'USDJPY=X',        # Dollar/Yen
            
            # ===== Yields & Bonds =====
            '2Y_Yield': '^IRX',           # 2-Year Treasury
            '10Y_Yield': '^TNX',          # 10-Year Treasury
            '30Y_Yield': '^TYX',          # 30-Year Treasury
            'HY_Credit': 'HYG',           # High Yield Bond ETF
            'IG_Credit': 'LQD',           # Investment Grade Bond ETF
            
            # ===== Commodities =====
            'GOLD': 'GC=F',               # Gold Futures
            'SILVER': 'SI=F',             # Silver Futures
            'OIL': 'CL=F',                # WTI Crude Oil
            'COPPER': 'HG=F',             # Copper Futures (경기 선행)
            'NAT_GAS': 'NG=F',            # Natural Gas
            
            # ===== US Indices =====
            'SPY': 'SPY',                 # S&P 500 ETF
            'QQQ': 'QQQ',                 # Nasdaq 100 ETF
            'IWM': 'IWM',                 # Russell 2000 ETF
            'DIA': 'DIA',                 # Dow Jones ETF
            
            # ===== Crypto =====
            'BTC': 'BTC-USD',             # Bitcoin
            'ETH': 'ETH-USD',             # Ethereum
            
            # ===== Global Markets =====
            'CSI300': '000300.SS',        # China CSI 300
            'NIKKEI': '^N225',            # Japan Nikkei 225
            'DAX': '^GDAXI',              # Germany DAX
            'FTSE': '^FTSE',              # UK FTSE 100
            'KOSPI': '^KS11',             # Korea KOSPI
            
            # ===== Market Breadth & Credit =====
            'RSP': 'RSP',                 # S&P 500 Equal Weight (Breadth)
            'IEF': 'IEF',                 # 7-10Y Treasury (Safe Asset)
            
            # ===== Sector ETFs (Risk Appetite) =====
            'XLF': 'XLF',                 # Financials
            'XLE': 'XLE',                 # Energy
            'XLK': 'XLK',                 # Technology
            'XLU': 'XLU',                 # Utilities (Defensive)
            
            # ===== Housing & REITs =====
            'XHB': 'XHB',                 # Homebuilders ETF
            'VNQ': 'VNQ',                 # Real Estate ETF
        }
    
    def get_current_macro_data(self) -> Dict:
        """Get current macro indicator values"""
        logger.info("📊 Fetching current macro data...")
        
        macro_data = {}
        
        try:
            tickers_list = list(self.macro_tickers.values())
            data = yf.download(tickers_list, period='5d', progress=False)
            
            if data.empty:
                return {}
            
            for name, ticker in self.macro_tickers.items():
                try:
                    ticker_data = data['Close'][ticker].dropna()
                    if len(ticker_data) < 2:
                        continue
                    
                    close = ticker_data.iloc[-1]
                    prev_close = ticker_data.iloc[-2]
                    
                    # Skip if still NaN
                    import math
                    if math.isnan(close) or math.isnan(prev_close):
                        continue
                    
                    change_pct = ((close / prev_close) - 1) * 100
                    
                    # Get 52-week high/low
                    hist = yf.Ticker(ticker).history(period='1y')
                    if not hist.empty:
                        high_52w = hist['High'].max()
                        low_52w = hist['Low'].min()
                        pct_from_high = ((close / high_52w) - 1) * 100
                        pct_from_low = ((close / low_52w) - 1) * 100
                    else:
                        high_52w = low_52w = pct_from_high = pct_from_low = 0
                    
                    macro_data[name] = {
                        'value': round(close, 2),
                        'change_1d': round(change_pct, 2),
                        'high_52w': round(high_52w, 2),
                        'low_52w': round(low_52w, 2),
                        'pct_from_high': round(pct_from_high, 2),
                        'pct_from_low': round(pct_from_low, 2),
                        'data_quality': 'actual',
                        'last_updated': datetime.now().isoformat()
                    }
                except Exception as e:
                    logger.debug(f"Error getting {name}: {e}")
            
        except Exception as e:
            logger.error(f"Error fetching macro data: {e}")
        
        # Calculate derived indicators
        self._add_derived_indicators(macro_data)
        
        # Add Fear & Greed Index
        fear_greed = self.get_fear_greed_index()
        if fear_greed:
            macro_data['FearGreed'] = fear_greed
        else:
            # Fallback with simulated data quality indicator
            macro_data['FearGreed'] = {
                'value': 50,
                'change_1d': 0,
                'signal': 'Neutral (unavailable)',
                'pct_from_high': 0,
                'pct_from_low': 0,
                'data_quality': 'simulated',
                'note': 'CNN API unavailable - using neutral placeholder'
            }
        
        return macro_data
    
    def _add_derived_indicators(self, macro_data: Dict):
        """Calculate derived indicators from base data"""
        
        # 1. Yield Spread (Recession)
        if '2Y_Yield' in macro_data and '10Y_Yield' in macro_data:
            y2 = macro_data['2Y_Yield']['value']
            y10 = macro_data['10Y_Yield']['value']
            spread = y10 - y2
            
            macro_data['YieldSpread'] = {
                'value': round(spread, 2),
                'change_1d': 0,
                'pct_from_high': 0,
                'signal': 'Inverted ⚠️' if spread < 0 else 'Normal',
                'desc': '10Y - 2Y Yield'
            }
            
        # 2. Market Breadth (RSP vs SPY) - Equal Weight vs Market Cap
        if 'RSP' in macro_data and 'SPY' in macro_data:
            rsp = macro_data['RSP']['value']
            spy = macro_data['SPY']['value']
            ratio = rsp / spy
            
            # Simple trend check (comparing to recent history would be better, but using static check for now)
            # Ideally we check slope. Here we just provide the ratio value.
            macro_data['Breadth'] = {
                'value': round(ratio, 4),
                'change_1d': 0,
                'pct_from_high': 0,
                'signal': 'Check Trend',
                'desc': 'RSP/SPY Ratio (Rising = Healthy)'
            }
            
        # 3. Credit Stress (HYG vs IEF) - Junk vs Treasury
        if 'HY_Credit' in macro_data and 'IEF' in macro_data:
            hyg = macro_data['HY_Credit']['value']
            ief = macro_data['IEF']['value']
            ratio = hyg / ief
            
            macro_data['CreditRisk'] = {
                'value': round(ratio, 4),
                'change_1d': 0,
                'pct_from_high': 0,
                'signal': 'Check Trend',
                'desc': 'HYG/IEF Ratio (Falling = Stress)'
            }
    
    def get_fear_greed_index(self) -> Optional[Dict]:
        """Scrape CNN Fear & Greed Index"""
        try:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                score = data.get('fear_and_greed', {}).get('score', 50)
                rating = data.get('fear_and_greed', {}).get('rating', 'Neutral')
                
                return {
                    'value': round(score, 0),
                    'change_1d': 0,
                    'signal': rating,
                    'pct_from_high': 0,
                    'pct_from_low': 0
                }
        except Exception as e:
            logger.debug(f"Error fetching Fear & Greed: {e}")
        return None
    
    def get_macro_news(self, limit: int = 10) -> List[Dict]:
        """Get macro/Fed/economy related news"""
        logger.info("📰 Fetching macro news...")
        
        news = []
        
        try:
            import xml.etree.ElementTree as ET
            from urllib.parse import quote
            
            # Search for Fed, economy, interest rate news
            queries = [
                "Federal Reserve interest rate",
                "Fed Powell monetary policy",
                "US economy outlook 2026"
            ]
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            for query in queries:
                url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
                
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    continue
                
                root = ET.fromstring(response.content)
                
                for item in root.findall('.//item')[:3]:
                    title = item.find('title')
                    pub_date = item.find('pubDate')
                    source = item.find('source')
                    
                    if title is not None:
                        news.append({
                            'title': title.text,
                            'source': source.text if source is not None else 'Google News',
                            'date': pub_date.text if pub_date is not None else '',
                            'category': query.split()[0]  # Fed, US, etc.
                        })
            
        except Exception as e:
            logger.error(f"Error fetching macro news: {e}")
        
        return news[:limit]
    
    def get_historical_patterns(self) -> List[Dict]:
        """Get historical pattern data for comparison"""
        
        # Historical significant events and outcomes
        patterns = [
            {
                'event': 'Fed Rate Cut Cycle Start (2019)',
                'date': '2019-07-31',
                'conditions': {
                    'VIX': 'Low (15-18)',
                    'SPY_trend': 'Uptrend',
                    'Treasury_yield': 'Declining'
                },
                'outcome': {
                    'SPY_6m': '+12%',
                    'QQQ_6m': '+18%',
                    'sectors_best': ['Technology', 'Consumer Discretionary'],
                    'sectors_worst': ['Financials', 'Energy']
                }
            },
            {
                'event': 'QE3 Start (2012)',
                'date': '2012-09-13',
                'conditions': {
                    'VIX': 'Moderate (15-20)',
                    'SPY_trend': 'Recovery',
                    'Treasury_yield': 'Low'
                },
                'outcome': {
                    'SPY_6m': '+10%',
                    'QQQ_6m': '+8%',
                    'sectors_best': ['Financials', 'Housing'],
                    'sectors_worst': ['Utilities', 'Consumer Staples']
                }
            },
            {
                'event': 'Fed Pivot Signal (2023)',
                'date': '2023-11-01',
                'conditions': {
                    'VIX': 'Elevated then declining',
                    'SPY_trend': 'Recovery from October low',
                    'Treasury_yield': 'Peak and declining'
                },
                'outcome': {
                    'SPY_3m': '+15%',
                    'QQQ_3m': '+20%',
                    'sectors_best': ['Technology', 'Communications'],
                    'sectors_worst': ['Energy', 'Utilities']
                }
            }
        ]
        
        return patterns
    
    def get_corporate_sentiment(self) -> Dict:
        """Get corporate sentiment from earnings and SEC filings"""
        sentiment = {
            'earnings_tone': 'Neutral',
            'guidance_trend': 'Stable',
            'filing_activity': 'Normal',
            'details': []
        }
        
        try:
            # Load Earnings Transcripts Analysis
            earnings_file = os.path.join(self.data_dir, 'output', 'earnings_transcripts.json')
            if os.path.exists(earnings_file):
                with open(earnings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                analyses = data.get('analyses', {})
                if analyses:
                    # Simple aggregation (improve this with real sentiment scores later)
                    # For now just checking if we have data
                    sentiment['earnings_tone'] = f"Analyzed {len(analyses)} companies"
                    sentiment['details'].append(f"Earnings data for {len(analyses)} tickers")
            
            # Load SEC Filings
            sec_file = os.path.join(self.data_dir, 'output', 'sec_filings.json')
            if os.path.exists(sec_file):
                with open(sec_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                filings = data.get('filings', {})
                sentiment['filing_activity'] = f"Recent filings: {len(filings)} companies"
                
        except Exception as e:
            logger.error(f"Error getting corporate sentiment: {e}")
            
        return sentiment


class MacroAIAnalyzer:
    """Use Gemini 3.0 to analyze macro conditions and predict opportunities"""
    
    def __init__(self):
        self.api_key = os.getenv('GOOGLE_API_KEY')
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-preview:generateContent"
    
    def analyze_macro_conditions(self, macro_data: Dict, news: List[Dict], patterns: List[Dict], corp_sentiment: Dict = None, lang: str = 'ko') -> str:
        """Generate AI analysis of current macro conditions"""
        
        prompt = self._build_macro_prompt(macro_data, news, patterns, corp_sentiment, lang)
        
        try:
            response = requests.post(
                f"{self.base_url}?key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 2500,
                        "thinkingConfig": {
                            "thinkingLevel": "low"
                        }
                    }
                },
                timeout=90
            )
            
            if response.status_code == 200:
                result = response.json()
                text = result['candidates'][0]['content']['parts'][0]['text']
                return text.strip()
            else:
                logger.error(f"Gemini API error: {response.status_code}")
                return "AI 분석 생성 실패"
                
        except Exception as e:
            logger.error(f"Error generating macro analysis: {e}")
            return f"AI 분석 실패: {str(e)}"
    
    def _build_macro_prompt(self, macro_data: Dict, news: List[Dict], patterns: List[Dict], corp_sentiment: Dict = None, lang: str = 'ko') -> str:
        """Build prompt for Gemini"""
        
        # Format current data
        macro_text = ""
        for name, data in macro_data.items():
            change = data.get('change_1d', 0)
            pct_high = data.get('pct_from_high', 0)
            signal = data.get('signal', '')
            if signal:
                macro_text += f"- {name}: {data['value']} ({signal})\n"
            else:
                macro_text += f"- {name}: {data['value']} ({change:+.2f}% today), {pct_high:.1f}% from 52w high\n"

        # Format news
        news_text = "\n".join([f"- [{n['source']}] {n['title']}" for n in news[:5]])

        # Format historical patterns
        patterns_text = ""
        for p in patterns:
            patterns_text += f"\n### {p['event']}\n"
            patterns_text += f"Conditions: {p['conditions']}\n"
            outcome = p['outcome']
            spy_perf = outcome.get('SPY_6m') or outcome.get('SPY_3m', 'N/A')
            qqq_perf = outcome.get('QQQ_6m') or outcome.get('QQQ_3m', 'N/A')
            patterns_text += f"Result: SPY {spy_perf}, QQQ {qqq_perf}\n"
            patterns_text += f"Best sectors: {', '.join(outcome.get('sectors_best', []))}\n"

        # Format corporate sentiment
        corp_text = "No corporate data available."
        if corp_sentiment:
            corp_text = f"Earnings Tone: {corp_sentiment.get('earnings_tone', 'N/A')}\n"
            corp_text += f"Filing Activity: {corp_sentiment.get('filing_activity', 'N/A')}\n"
            if corp_sentiment.get('details'):
                 corp_text += "Details: " + ", ".join(corp_sentiment['details'])

        if lang == 'en':
            prompt = f"""You are a global macro analyst. Analyze the current market conditions and provide investment strategy.
            
## FOCUS ON THESE REGIME INDICATORS:
1. Market Breadth: Check 'Breadth' (RSP/SPY). Rising ratio = Healthy Rally. Falling = Narrow/Fragile.
2. Credit Stress: Check 'CreditRisk' (HYG/IEF). Rising ratio = Risk On. Falling = Stress/Risk Off.
3. Yield Curve: Check 'YieldSpread' (10Y-2Y). Negative = Recession Warning.

## Corporate Sentiment (Earnings/SEC)
{corp_text}

## Current Macro Indicators
{macro_text}

## Recent Major News
{news_text}

## Similar Historical Situations
{patterns_text}

## Analysis Request
1. Current situation summary (2-3 sentences)
2. Compare with most similar historical pattern
3. 🚀 Opportunity Alert: Favorable sectors/assets in current conditions
4. ⚠️ Warning Alert: Risks to watch
5. Investment strategy suggestions (be specific)

Write in English, use emojis appropriately. Be concise and focus on key points."""
        else:
            prompt = f"""당신은 글로벌 매크로 전문 애널리스트입니다. 현재 시장 상황을 분석하고 투자 전략을 제시해주세요.

## 기업 실적/공시 분위기 (Corporate Sentiment)
{corp_text}

## 현재 매크로 지표
{macro_text}

## 최근 주요 뉴스
{news_text}

## 과거 유사한 상황들
{patterns_text}

## 분석 요청
1. 현재 상황 요약 (2-3문장)
2. 가장 유사한 과거 패턴 비교
3. 🚀 기회 알림: 현재 상황에서 유리한 섹터/자산
4. ⚠️ 경고 알림: 주의해야 할 리스크
5. 투자 전략 제안 (구체적으로)

한국어로 작성하고, 이모지를 적절히 사용하세요. 핵심만 간결하게 작성하세요."""

        return prompt


class GPTAIAnalyzer:
    """Use OpenAI GPT to analyze macro conditions and predict opportunities"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.base_url = "https://api.openai.com/v1/chat/completions"
        self.model = "o3-mini"
    
    def analyze_macro_conditions(self, macro_data: Dict, news: List[Dict], patterns: List[Dict], lang: str = 'ko') -> str:
        """Generate AI analysis of current macro conditions using GPT"""
        
        if not self.api_key:
            return "OpenAI API 키가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 추가하세요."
        
        prompt = self._build_macro_prompt(macro_data, news, patterns, lang)
        
        try:
            response = requests.post(
                self.base_url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "developer", "content": "You are a professional global macro analyst with expertise in market analysis and investment strategy."},
                        {"role": "user", "content": prompt}
                    ],
                    "reasoning_effort": "medium",
                    "max_completion_tokens": 2500
                },
                timeout=90
            )
            
            if response.status_code == 200:
                result = response.json()
                text = result['choices'][0]['message']['content']
                return text.strip()
            else:
                logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
                return f"GPT 분석 생성 실패: {response.status_code} - {response.text}"
                
        except Exception as e:
            logger.error(f"Error generating GPT macro analysis: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return f"GPT 분석 실패: {str(e)}"
    
    def _build_macro_prompt(self, macro_data: Dict, news: List[Dict], patterns: List[Dict], lang: str = 'ko') -> str:
        """Build prompt for GPT"""
        
        # Format current data
        macro_text = ""
        for name, data in macro_data.items():
            change = data.get('change_1d', 0)
            pct_high = data.get('pct_from_high', 0)
            signal = data.get('signal', '')
            if signal:
                macro_text += f"- {name}: {data['value']} ({signal})\n"
            else:
                macro_text += f"- {name}: {data['value']} ({change:+.2f}% today), {pct_high:.1f}% from 52w high\n"

        # Format news
        news_text = "\n".join([f"- [{n['source']}] {n['title']}" for n in news[:5]])

        # Format historical patterns
        patterns_text = ""
        for p in patterns:
            patterns_text += f"\n### {p['event']}\n"
            patterns_text += f"Conditions: {p['conditions']}\n"
            outcome = p['outcome']
            spy_perf = outcome.get('SPY_6m') or outcome.get('SPY_3m', 'N/A')
            qqq_perf = outcome.get('QQQ_6m') or outcome.get('QQQ_3m', 'N/A')
            patterns_text += f"Result: SPY {spy_perf}, QQQ {qqq_perf}\n"
            patterns_text += f"Best sectors: {', '.join(outcome.get('sectors_best', []))}\n"

        if lang == 'en':
            prompt = f"""Analyze the current market conditions and provide investment strategy.

## Current Macro Indicators
{macro_text}

## Recent Major News
{news_text}

## Similar Historical Situations
{patterns_text}

## Analysis Request
1. Current situation summary (2-3 sentences)
2. Compare with most similar historical pattern
3. 🚀 Opportunity Alert: Favorable sectors/assets in current conditions
4. ⚠️ Warning Alert: Risks to watch
5. Investment strategy suggestions (be specific)

Write in English, use emojis appropriately. Be concise and focus on key points."""
        else:
            prompt = f"""현재 시장 상황을 분석하고 투자 전략을 제시해주세요.

## 현재 매크로 지표
{macro_text}

## 최근 주요 뉴스
{news_text}

## 과거 유사한 상황들
{patterns_text}

## 분석 요청
1. 현재 상황 요약 (2-3문장)
2. 가장 유사한 과거 패턴 비교
3. 🚀 기회 알림: 현재 상황에서 유리한 섹터/자산
4. ⚠️ 경고 알림: 주의해야 할 리스크
5. 투자 전략 제안 (구체적으로)

한국어로 작성하고, 이모지를 적절히 사용하세요. 핵심만 간결하게 작성하세요."""

        return prompt


class MacroMarketAnalyzer:
    """Main class for macro market analysis"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'macro_analysis.json')
        
        self.collector = MacroDataCollector(data_dir)
        self.ai_analyzer = MacroAIAnalyzer()  # Gemini
        self.gpt_analyzer = GPTAIAnalyzer()   # GPT
    
    def run_analysis(self) -> Dict:
        """Run full macro analysis"""
        logger.info("🌍 Starting Macro Market Analysis...")
        
        # Collect data
        macro_data = self.collector.get_current_macro_data()
        news = self.collector.get_macro_news()
        patterns = self.collector.get_historical_patterns()
        corp_sentiment = self.collector.get_corporate_sentiment()
        
        logger.info(f"📊 Collected {len(macro_data)} indicators, {len(news)} news articles")
        
        timestamp = datetime.now().isoformat()
        
        # === GEMINI ANALYSIS ===
        logger.info("🤖 [Step 1/2] Generating AI analysis with Gemini 3.0 (Korean)...")
        ai_analysis_ko = self.ai_analyzer.analyze_macro_conditions(macro_data, news, patterns, corp_sentiment, 'ko')
        
        logger.info("🤖 [Step 1/2] Generating AI analysis with Gemini 3.0 (English)...")
        ai_analysis_en = self.ai_analyzer.analyze_macro_conditions(macro_data, news, patterns, corp_sentiment, 'en')
        
        # Build and save Gemini Korean version
        result_ko = {
            'timestamp': timestamp,
            'lang': 'ko',
            'model': 'gemini',
            'macro_indicators': macro_data,
            'news': news,
            'historical_patterns': patterns,
            'corporate_sentiment': corp_sentiment,
            'ai_analysis': ai_analysis_ko
        }
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result_ko, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Gemini Korean analysis saved to {self.output_file}")
        
        # Build and save Gemini English version
        result_en = {
            'timestamp': timestamp,
            'lang': 'en',
            'model': 'gemini',
            'macro_indicators': macro_data,
            'news': news,
            'historical_patterns': patterns,
            'corporate_sentiment': corp_sentiment,
            'ai_analysis': ai_analysis_en
        }
        
        en_output_file = self.output_file.replace('.json', '_en.json')
        with open(en_output_file, 'w', encoding='utf-8') as f:
            json.dump(result_en, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Gemini English analysis saved to {en_output_file}")
        
        # === GPT ANALYSIS ===
        if os.getenv('OPENAI_API_KEY'):
            logger.info("🧠 [Step 2/2] Generating AI analysis with o3-mini (Korean)...")
            gpt_analysis_ko = self.gpt_analyzer.analyze_macro_conditions(macro_data, news, patterns, 'ko')
            
            logger.info("🧠 [Step 2/2] Generating AI analysis with o3-mini (English)...")
            gpt_analysis_en = self.gpt_analyzer.analyze_macro_conditions(macro_data, news, patterns, 'en')
            
            # Build and save GPT Korean version
            gpt_result_ko = {
                'timestamp': timestamp,
                'lang': 'ko',
                'model': 'gpt',
                'macro_indicators': macro_data,
                'news': news,
                'historical_patterns': patterns,
                'ai_analysis': gpt_analysis_ko
            }
            
            gpt_ko_file = os.path.join(self.data_dir, 'output', 'macro_analysis_gpt.json')
            with open(gpt_ko_file, 'w', encoding='utf-8') as f:
                json.dump(gpt_result_ko, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ GPT Korean analysis saved to {gpt_ko_file}")
            
            # Build and save GPT English version
            gpt_result_en = {
                'timestamp': timestamp,
                'lang': 'en',
                'model': 'gpt',
                'macro_indicators': macro_data,
                'news': news,
                'historical_patterns': patterns,
                'ai_analysis': gpt_analysis_en
            }
            
            gpt_en_file = os.path.join(self.data_dir, 'output', 'macro_analysis_gpt_en.json')
            with open(gpt_en_file, 'w', encoding='utf-8') as f:
                json.dump(gpt_result_en, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ GPT English analysis saved to {gpt_en_file}")
        else:
            logger.warning("⚠️ OPENAI_API_KEY not set, skipping GPT analysis")
        
        return result_ko


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Macro Market Analyzer')
    parser.add_argument('--dir', default='.', help='Data directory')
    args = parser.parse_args()
    
    analyzer = MacroMarketAnalyzer(data_dir=args.dir)
    result = analyzer.run_analysis()
    
    print("\n" + "="*80)
    print("🌍 MACRO MARKET ANALYSIS")
    print("="*80)
    
    print("\n📊 현재 매크로 지표:")
    for name, data in result['macro_indicators'].items():
        change = data['change_1d']
        emoji = "🟢" if change >= 0 else "🔴"
        print(f"  {emoji} {name}: {data['value']} ({change:+.2f}%)")
    
    print("\n" + "-"*80)
    print("🤖 AI 분석:")
    print("-"*80)
    print(result['ai_analysis'])


if __name__ == "__main__":
    main()
