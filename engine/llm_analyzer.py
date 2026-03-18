"""
🤖 LLM 뉴스 분석 시스템 (Perplexity + Gemini + Claude + OpenAI)
실시간 웹 검색과 고도화된 AI 분석을 결합하여 종목별 호재 점수를 산출합니다.
Claude AI 독립 종목 선별 기능을 포함합니다.
"""

import os
import json
import re
import asyncio
import httpx
import google.generativeai as genai
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# API 상태 추적 (Rate Limit 관리)
API_STATUS = {
    'perplexity': {'available': True, 'last_error': None, 'error_count': 0},
    'gemini': {'available': True, 'last_error': None, 'error_count': 0},
    'claude': {'available': True, 'last_error': None, 'error_count': 0},
    'openai': {'available': True, 'last_error': None, 'error_count': 0}
}

def reset_api_status():
    """API 상태 초기화 (세션 시작 시 호출)"""
    global API_STATUS
    for key in API_STATUS:
        API_STATUS[key] = {'available': True, 'last_error': None, 'error_count': 0}

class PerplexityClient:
    """Perplexity Sonar API를 이용한 실시간 뉴스 검색"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("PERPLEXITY_API_KEY")
        self.base_url = "https://api.perplexity.ai/chat/completions"
        self.model = "sonar"
        
    async def search_stock_news(self, stock_name: str) -> Dict:
        """최근 24시간 이내의 종목 관련 뉴스 검색 및 요약"""
        global API_STATUS

        if not self.api_key:
            return {"news_summary": "", "citations": [], "error": "No API Key"}

        if not API_STATUS['perplexity']['available']:
            return {"news_summary": "", "citations": [], "error": f"Rate Limited: {API_STATUS['perplexity']['last_error']}"}
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        query = f"'{stock_name}' 종목에 대한 최신 뉴스와 시장 동향을 검색해주세요. 1. 최근 24시간 이내의 주요 뉴스(호재/악재), 2. 실적/수주/계약 정보, 3. 관련 테마 및 산업 동향을 포함해 답변해주세요."
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "당신은 한국 주식 시장 전문 리서치 애널리스트입니다. 사실을 기반으로 명확하고 간결하게 답변하세요."},
                {"role": "user", "content": query}
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
            "return_citations": True,
            "search_recency_filter": "day"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.base_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                return {
                    "news_summary": data["choices"][0]["message"]["content"],
                    "citations": data.get("citations", []),
                    "source": "perplexity"
                }
        except Exception as e:
            error_msg = str(e).lower()
            print(f"[ERROR] Perplexity Search Failed: {e}")

            # Rate Limit 감지
            if 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg or 'quota' in error_msg:
                API_STATUS['perplexity']['available'] = False
                API_STATUS['perplexity']['last_error'] = 'Rate Limit'
                API_STATUS['perplexity']['error_count'] += 1
                print("[WARN] Perplexity Rate Limit - 임시 비활성화")

            return {"news_summary": "", "citations": [], "error": str(e)}

class OpenAIAnalyzer:
    """OpenAI GPT를 이용한 뉴스 종합 분석 (Gemini Fallback)"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=self.api_key)
            self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini") # 가성비 모델 기본값
        else:
            self.client = None
            
    async def analyze_news(self, stock_name: str, perplexity_news: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        global API_STATUS

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
                API_STATUS['openai']['available'] = False
                API_STATUS['openai']['last_error'] = 'Rate Limit'
                API_STATUS['openai']['error_count'] += 1
                print("[WARN] OpenAI Rate Limit - 임시 비활성화")

            return {"score": 0, "reason": f"OpenAI Error: {e}", "themes": []}

class GeminiAnalyzer:
    """Gemini를 이용한 뉴스 종합 분석 및 점수 산출"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
            self.model = genai.GenerativeModel(model_name)
        else:
            self.model = None
            
    async def analyze_news(self, stock_name: str, perplexity_news: str, traditional_news: List[Dict] = None, dart_text: str = "") -> Dict:
        """Perplexity 결과와 네이버 뉴스를 통합 분석하여 점수화"""
        global API_STATUS

        if not self.model:
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
                self.model.generate_content,
                prompt,
                generation_config={"response_mime_type": "application/json"}
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
                API_STATUS['gemini']['available'] = False
                API_STATUS['gemini']['last_error'] = 'Rate Limit'
                API_STATUS['gemini']['error_count'] += 1
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
        global API_STATUS

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
                API_STATUS['claude']['available'] = False
                API_STATUS['claude']['last_error'] = 'Rate Limit'
                API_STATUS['claude']['error_count'] += 1
                print("[WARN] Claude Rate Limit - 임시 비활성화")

            return {"score": 0, "reason": f"Claude Error: {e}", "themes": []}


class LLMAnalyzer:
    """통합 뉴스 분석 오케스트레이터 (Perplexity -> Gemini -> Claude -> OpenAI -> Fallback)

    4중 API 폴백 시스템:
    1. Perplexity (실시간 검색) - Rate Limit 시 스킵
    2. Gemini (분석) - Rate Limit 시 Claude로 폴백
    3. Claude (분석) - Rate Limit 시 OpenAI로 폴백
    4. OpenAI (분석) - Rate Limit 시 키워드 분석으로 폴백
    """

    def __init__(self):
        self.perplexity = PerplexityClient()
        self.gemini = GeminiAnalyzer()
        self.claude = ClaudeAnalyzer()
        self.openai = OpenAIAnalyzer()
        # model 속성 추가 (generator.py 호환성)
        self.model = self.gemini.model or self.claude.client or self.openai.client

    def get_api_status(self) -> Dict:
        """현재 API 상태 반환"""
        return {
            'perplexity': 'active' if API_STATUS['perplexity']['available'] else 'rate_limited',
            'gemini': 'active' if API_STATUS['gemini']['available'] else 'rate_limited',
            'claude': 'active' if API_STATUS['claude']['available'] else 'rate_limited',
            'openai': 'active' if API_STATUS['openai']['available'] else 'rate_limited',
            'errors': {k: v['error_count'] for k, v in API_STATUS.items()}
        }

    async def analyze_news_sentiment(self, stock_name: str, news_items: List[Dict] = None, dart_text: str = "") -> Dict:
        """뉴스 감성 분석 통합 프로세스 (3중 폴백 시스템) + DART 공시 정보"""
        news_summary = ""
        citations = []
        analysis_source = "none"

        # 1. Perplexity 검색 (실시간 정보) - Rate Limit 시 스킵
        if API_STATUS['perplexity']['available']:
            p_res = await self.perplexity.search_stock_news(stock_name)
            news_summary = p_res.get("news_summary", "")
            citations = p_res.get("citations", [])

            # Rate Limit 방지
            if news_summary:
                await asyncio.sleep(1)
                analysis_source = "perplexity"
        else:
            print(f"[SKIP] Perplexity Rate Limited - {stock_name}")

        # 분석 대상 데이터가 없으면 빠른 종료
        if not news_summary and not news_items:
            return self._keyword_fallback(stock_name, [])

        analysis = None

        # 2. Main Analysis (Gemini Attempt) - Rate Limit 시 스킵
        if API_STATUS['gemini']['available']:
            analysis = await self.gemini.analyze_news(stock_name, news_summary, news_items, dart_text)
            if analysis.get("score") > 0 or "Error" not in analysis.get("reason", ""):
                analysis["source"] = f"{analysis_source}+gemini" if analysis_source else "gemini_only"
            else:
                analysis = None  # Gemini 실패 - OpenAI로 폴백
        else:
            print(f"[SKIP] Gemini Rate Limited - {stock_name}")

        # 2.5 Claude Fallback (Gemini 실패 시) - Rate Limit 시 스킵
        if analysis is None and API_STATUS['claude']['available']:
            print(f"[FALLBACK] Gemini Failed for {stock_name}, trying Claude...")
            analysis = await self.claude.analyze_news(stock_name, news_summary, news_items, dart_text)
            if analysis.get("score") > 0 or "Error" not in analysis.get("reason", ""):
                analysis["source"] = f"{analysis_source}+claude" if analysis_source else "claude_only"
            else:
                analysis = None  # Claude도 실패
        elif analysis is None and not API_STATUS['claude']['available']:
            print(f"[SKIP] Claude Rate Limited - {stock_name}")

        # 3. Fallback Analysis (OpenAI Attempt) - Rate Limit 시 스킵
        if analysis is None and API_STATUS['openai']['available']:
            print(f"[FALLBACK] Claude Failed for {stock_name}, trying OpenAI...")
            analysis = await self.openai.analyze_news(stock_name, news_summary, news_items, dart_text)
            if analysis.get("score") > 0 or "Error" not in analysis.get("reason", ""):
                analysis["source"] = f"{analysis_source}+openai" if analysis_source else "openai_only"
            else:
                analysis = None  # OpenAI도 실패
        elif analysis is None:
            print(f"[SKIP] OpenAI Rate Limited - {stock_name}")

        # 4. Final Fallback (Keyword) - 모든 LLM 실패 시
        if analysis is None or (analysis.get("score") == 0 and ("Error" in analysis.get("reason", "") or "Rate" in analysis.get("reason", ""))):
            print(f"[FALLBACK] All LLMs failed for {stock_name}, using keywords...")
            return self._keyword_fallback(stock_name, news_items)

        # 성공 시 결과 반환
        if not isinstance(analysis, dict):
            return self._keyword_fallback(stock_name, news_items)

        analysis["citations"] = citations
        analysis["api_status"] = self.get_api_status()
        return analysis

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
        self.model = None
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(self.model_name)

    async def screen_candidates(self, signals_data: List[Dict]) -> Dict:
        if not self.model:
            return {"picks": [], "error": "No Gemini Client", "generated_at": datetime.now().isoformat()}
        if not signals_data:
            return {"picks": [], "error": "No signals", "generated_at": datetime.now().isoformat()}

        candidates_text = self._build_candidates_summary(signals_data)
        prompt = self._build_screening_prompt(candidates_text, len(signals_data))

        try:
            response = await asyncio.to_thread(
                self.model.generate_content,
                prompt,
                generation_config={"response_mime_type": "application/json"}
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
        self.model_name = os.getenv("OPENAI_SCREENER_MODEL", "gpt-4o")
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
            response = await self.client.chat.completions.create(
                model=self.model_name,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": "You are a professional Korean stock market portfolio manager. Respond only in valid JSON. Analyze all candidates comprehensively."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content.strip()
            result = self._parse_json_response(content)
            result["generated_at"] = datetime.now().isoformat()
            result["model"] = self.model_name
            return result
        except Exception as e:
            print(f"[ERROR] OpenAI Screener Failed: {e}")
            return {"picks": [], "error": str(e), "generated_at": datetime.now().isoformat(), "model": self.model_name}


class MultiAIConsensusScreener:
    """Multi-AI Consensus 종목 선별기

    Gemini + OpenAI 두 AI가 독립적으로 종목을 선별한 뒤,
    양쪽 모두 선택한 종목(Consensus)을 우선 추천합니다.
    """

    def __init__(self):
        self.gemini_screener = GeminiScreener()
        self.openai_screener = OpenAIScreener()

    async def screen_candidates(self, signals_data: List[Dict]) -> Dict:
        """두 AI를 병렬 실행하고 Consensus 결과 반환"""
        if not signals_data:
            return {
                "picks": [], "consensus_count": 0,
                "gemini_count": 0, "openai_count": 0,
                "market_view": "", "top_themes": [],
                "generated_at": datetime.now().isoformat(),
                "models": [], "consensus_method": "multi_ai"
            }

        # 1. 병렬 실행
        gemini_result, openai_result = await asyncio.gather(
            self._safe_screen(self.gemini_screener, signals_data),
            self._safe_screen(self.openai_screener, signals_data),
        )

        # 2. 합의 도출
        return self._build_consensus(gemini_result, openai_result)

    async def _safe_screen(self, screener, signals_data: List[Dict], timeout: int = 60) -> Dict:
        """개별 스크리너 (타임아웃 + 에러 핸들링)"""
        try:
            return await asyncio.wait_for(
                screener.screen_candidates(signals_data),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            model_name = getattr(screener, 'model_name', 'unknown')
            print(f"[TIMEOUT] {model_name} Screener timed out after {timeout}s")
            return {"picks": [], "error": f"Timeout after {timeout}s", "model": model_name}
        except Exception as e:
            model_name = getattr(screener, 'model_name', 'unknown')
            print(f"[ERROR] {model_name} Screener Failed: {e}")
            return {"picks": [], "error": str(e), "model": model_name}

    def _build_consensus(self, gemini_result: Dict, openai_result: Dict) -> Dict:
        """두 AI 결과를 합의 알고리즘으로 병합"""
        gemini_picks = gemini_result.get("picks", [])
        openai_picks = openai_result.get("picks", [])

        # stock_code 기반 매핑
        gemini_map = {p.get("stock_code", ""): p for p in gemini_picks if p.get("stock_code")}
        openai_map = {p.get("stock_code", ""): p for p in openai_picks if p.get("stock_code")}

        gemini_codes = set(gemini_map.keys())
        openai_codes = set(openai_map.keys())

        # 교집합 = Consensus
        consensus_codes = gemini_codes & openai_codes
        gemini_only_codes = gemini_codes - openai_codes
        openai_only_codes = openai_codes - gemini_codes

        # Consensus picks (양쪽 합의 → confidence 상향)
        consensus_picks = []
        for code in sorted(consensus_codes, key=lambda c: self._consensus_sort_key(gemini_map[c], openai_map[c])):
            merged = self._merge_pick(gemini_map[code], openai_map[code])
            consensus_picks.append(merged)

        # Single-AI picks (한쪽만 → confidence 하향)
        gemini_only = []
        for code in sorted(gemini_only_codes, key=lambda c: gemini_map[c].get("rank", 99)):
            pick = gemini_map[code].copy()
            pick["source"] = "gemini_only"
            pick["confidence"] = self._downgrade_confidence(pick.get("confidence", "LOW"))
            gemini_only.append(pick)

        openai_only = []
        for code in sorted(openai_only_codes, key=lambda c: openai_map[c].get("rank", 99)):
            pick = openai_map[code].copy()
            pick["source"] = "openai_only"
            pick["confidence"] = self._downgrade_confidence(pick.get("confidence", "LOW"))
            openai_only.append(pick)

        # 통합 + 재순위
        all_picks = consensus_picks + gemini_only + openai_only
        for i, p in enumerate(all_picks, 1):
            p["rank"] = i

        # Market views 병합
        views = []
        if gemini_result.get("market_view"):
            views.append(f"[Gemini] {gemini_result['market_view']}")
        if openai_result.get("market_view"):
            views.append(f"[GPT-4o] {openai_result['market_view']}")

        # Themes 병합 (중복 제거)
        all_themes = []
        for t in (gemini_result.get("top_themes", []) + openai_result.get("top_themes", [])):
            if t not in all_themes:
                all_themes.append(t)

        # 활성 모델
        models_used = []
        if gemini_picks:
            models_used.append(gemini_result.get("model", "gemini-2.5-flash"))
        if openai_picks:
            models_used.append(openai_result.get("model", "gpt-4o"))

        return {
            "picks": all_picks,
            "consensus_count": len(consensus_picks),
            "gemini_count": len(gemini_picks),
            "openai_count": len(openai_picks),
            "market_view": " | ".join(views),
            "top_themes": all_themes[:6],
            "generated_at": datetime.now().isoformat(),
            "models": models_used,
            "consensus_method": "multi_ai",
        }

    def _consensus_sort_key(self, gp: Dict, op: Dict) -> tuple:
        """Consensus 정렬 키 (높은 confidence + 낮은 avg rank 우선)"""
        conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        avg_rank = (gp.get("rank", 99) + op.get("rank", 99)) / 2
        best_conf = min(
            conf_order.get(gp.get("confidence", "LOW"), 2),
            conf_order.get(op.get("confidence", "LOW"), 2)
        )
        return (best_conf, avg_rank)

    def _merge_pick(self, gp: Dict, op: Dict) -> Dict:
        """양쪽 AI 결과를 하나로 병합 (confidence 상향)"""
        conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        reverse = {0: "HIGH", 1: "MEDIUM", 2: "LOW"}

        g_conf = conf_order.get(gp.get("confidence", "LOW"), 2)
        o_conf = conf_order.get(op.get("confidence", "LOW"), 2)
        best = min(g_conf, o_conf)
        boosted = max(0, best - 1)  # 1단계 상향

        return {
            "stock_code": gp.get("stock_code", ""),
            "stock_name": gp.get("stock_name", op.get("stock_name", "")),
            "rank": 0,  # 나중에 재배정
            "confidence": reverse[boosted],
            "reason": f"[Gemini] {gp.get('reason', '')} [GPT-4o] {op.get('reason', '')}",
            "risk": gp.get("risk", op.get("risk", "")),
            "expected_return": gp.get("expected_return", op.get("expected_return", "")),
            "source": "consensus",
            "gemini_rank": gp.get("rank", 99),
            "openai_rank": op.get("rank", 99),
        }

    def _downgrade_confidence(self, confidence: str) -> str:
        """Single-AI picks confidence 1단계 하향"""
        downgrades = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}
        return downgrades.get(confidence, "LOW")


if __name__ == "__main__":
    # 간단한 테스트
    async def test():
        analyzer = LLMAnalyzer()
        print("🔍 분석 테스트 시작: 삼성전자")
        result = await analyzer.analyze_news_sentiment("삼성전자", [])
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(test())
