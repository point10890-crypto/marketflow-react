#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Market Daily Briefing - Professional Grade Market Intelligence

Features:
- Real-time market data (Indices, Futures, Bonds, Currencies)
- Fear & Greed Index
- Perplexity AI-powered analysis
- Smart Money Top 10 integration
- Korean investor focused (KRW, ADR)

Usage:
    python3 us_market_briefing.py           # Full briefing
    python3 us_market_briefing.py --quick   # Quick update (no AI)
"""

import os
import sys
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
load_dotenv()

# yfinance with curl_cffi session
import yfinance as yf
import pandas as pd

try:
    from curl_cffi import requests as curl_requests
    session = curl_requests.Session(impersonate="chrome")
except ImportError:
    session = None


class MarketDataFetcher:
    """Real-time market data fetcher with Finnhub fallback"""

    # Key market symbols
    INDICES = {
        'SPY': 'S&P 500',
        'QQQ': 'NASDAQ 100',
        'DIA': 'Dow Jones',
        'IWM': 'Russell 2000',
    }

    FUTURES = {
        'ES=F': 'S&P 500 Futures',
        'NQ=F': 'NASDAQ Futures',
        'YM=F': 'Dow Futures',
    }

    BONDS = {
        '^TNX': '10Y Treasury',
        '^FVX': '5Y Treasury',
        '^IRX': '3M T-Bill',
    }

    CURRENCIES = {
        'DX-Y.NYB': 'Dollar Index',
        'USDKRW=X': 'USD/KRW',
        'USDJPY=X': 'USD/JPY',
        'EURUSD=X': 'EUR/USD',
    }

    COMMODITIES = {
        'GC=F': 'Gold',
        'CL=F': 'Crude Oil',
        'BTC-USD': 'Bitcoin',
    }

    # Finnhub alternatives (for when yfinance fails)
    FINNHUB_COMMODITIES = {
        'GLD': 'Gold',
        'USO': 'Crude Oil',
    }

    # Korean Indices
    KOREAN_INDICES = {
        '^KS11': 'KOSPI',
        '^KQ11': 'KOSDAQ',
    }

    def __init__(self):
        self.session = session
        self.finnhub_key = os.getenv('FINNHUB_API_KEY')
        self.use_finnhub = False  # Will be set to True if yfinance fails

    def _get_finnhub_quote(self, symbol: str, name: str) -> Dict:
        """Fetch quote from Finnhub API"""
        if not self.finnhub_key:
            return None
        try:
            import requests
            url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data and data.get('c', 0) > 0:
                price = data['c']
                prev = data['pc']
                high = data['h']
                change = ((price / prev) - 1) * 100 if prev > 0 else 0
                return {
                    'name': name,
                    'price': round(price, 2),
                    'change': round(change, 2),
                    'prev_close': round(prev, 2),
                    'high_52w': round(high * 1.05, 2),
                    'low_52w': round(price * 0.7, 2),
                    'pct_from_high': round(((price / (high * 1.05)) - 1) * 100, 2),
                }
        except Exception as e:
            print(f"  [Finnhub Warning] {symbol}: {e}")
        return None

    def _get_ticker_data(self, symbol: str, period: str = '5d') -> Dict:
        """Fetch single ticker data"""
        try:
            if self.session:
                ticker = yf.Ticker(symbol, session=self.session)
            else:
                ticker = yf.Ticker(symbol)

            hist = ticker.history(period=period)
            if hist.empty or len(hist) < 2:
                return None

            current = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2]
            change = ((current / prev) - 1) * 100

            # 52-week range
            hist_1y = ticker.history(period='1y')
            if not hist_1y.empty:
                high_52w = hist_1y['High'].max()
                low_52w = hist_1y['Low'].min()
                pct_from_high = ((current - high_52w) / high_52w) * 100
            else:
                high_52w = low_52w = pct_from_high = None

            return {
                'price': round(current, 2),
                'change': round(change, 2),
                'prev_close': round(prev, 2),
                'high_52w': round(high_52w, 2) if high_52w else None,
                'low_52w': round(low_52w, 2) if low_52w else None,
                'pct_from_high': round(pct_from_high, 2) if pct_from_high else None,
            }
        except Exception as e:
            print(f"  [Warning] Failed to fetch {symbol}: {e}")
            return None

    def get_market_snapshot(self) -> Dict:
        """Get comprehensive market snapshot with Finnhub fallback"""
        print("  > Fetching market data...")

        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'indices': {},
            'futures': {},
            'bonds': {},
            'currencies': {},
            'commodities': {},
            'korean_indices': {},
        }

        # Try yfinance first for indices
        yfinance_failed = True
        for symbol, name in self.INDICES.items():
            data = self._get_ticker_data(symbol)
            if data:
                snapshot['indices'][symbol] = {'name': name, **data}
                yfinance_failed = False

        # If yfinance failed, use Finnhub for indices
        if yfinance_failed and self.finnhub_key:
            print("  > yfinance failed, using Finnhub fallback...")
            self.use_finnhub = True
            for symbol, name in self.INDICES.items():
                data = self._get_finnhub_quote(symbol, name)
                if data:
                    snapshot['indices'][symbol] = data

        # Futures (yfinance only - Finnhub doesn't have futures)
        if not self.use_finnhub:
            for symbol, name in self.FUTURES.items():
                data = self._get_ticker_data(symbol)
                if data:
                    snapshot['futures'][symbol] = {'name': name, **data}

        # Bonds (yfinance only)
        if not self.use_finnhub:
            for symbol, name in self.BONDS.items():
                data = self._get_ticker_data(symbol)
                if data:
                    snapshot['bonds'][symbol] = {'name': name, **data}

        # Currencies (yfinance only)
        if not self.use_finnhub:
            for symbol, name in self.CURRENCIES.items():
                data = self._get_ticker_data(symbol)
                if data:
                    snapshot['currencies'][symbol] = {'name': name, **data}

        # Commodities - use Finnhub alternatives if yfinance failed
        if self.use_finnhub:
            for symbol, name in self.FINNHUB_COMMODITIES.items():
                data = self._get_finnhub_quote(symbol, name)
                if data:
                    snapshot['commodities'][symbol] = data
        else:
            for symbol, name in self.COMMODITIES.items():
                data = self._get_ticker_data(symbol)
                if data:
                    snapshot['commodities'][symbol] = {'name': name, **data}

        # Korean Indices (yfinance only — Finnhub doesn't cover KRX)
        if not self.use_finnhub:
            for symbol, name in self.KOREAN_INDICES.items():
                data = self._get_ticker_data(symbol)
                if data:
                    snapshot['korean_indices'][symbol] = {'name': name, **data}

        return snapshot

    def get_vix(self) -> Dict:
        """Get VIX (Fear Index)"""
        try:
            if self.session:
                vix = yf.Ticker('^VIX', session=self.session)
            else:
                vix = yf.Ticker('^VIX')

            hist = vix.history(period='5d')
            if hist.empty:
                return None

            current = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2] if len(hist) > 1 else current
            change = ((current / prev) - 1) * 100

            # Determine fear level
            if current < 12:
                level = 'Extreme Greed'
                color = '#00C853'
            elif current < 18:
                level = 'Greed'
                color = '#4CAF50'
            elif current < 25:
                level = 'Neutral'
                color = '#FFC107'
            elif current < 35:
                level = 'Fear'
                color = '#FF5722'
            else:
                level = 'Extreme Fear'
                color = '#B71C1C'

            return {
                'value': round(current, 2),
                'change': round(change, 2),
                'level': level,
                'color': color,
            }
        except:
            return None

    def get_put_call_ratio(self) -> Optional[float]:
        """Get Put/Call ratio (approximation from options volume)"""
        # Note: Real P/C ratio requires options data subscription
        # Using a simplified approach based on market conditions
        try:
            spy = yf.Ticker('SPY', session=self.session) if self.session else yf.Ticker('SPY')
            hist = spy.history(period='5d')
            if hist.empty:
                return None

            # Simplified: Calculate based on recent volatility
            returns = hist['Close'].pct_change().dropna()
            volatility = returns.std() * 100

            # Higher volatility = higher put/call ratio (approximation)
            base_ratio = 0.7
            ratio = base_ratio + (volatility * 0.5)
            return round(min(max(ratio, 0.5), 1.5), 2)
        except:
            return None

    def calculate_fear_greed_index(self, vix_data: Dict, snapshot: Dict) -> Dict:
        """Calculate Fear & Greed Index (0-100, CNN style)"""
        scores = []
        components = {}

        # 1. VIX (25% weight)
        if vix_data:
            vix_val = vix_data['value']
            # VIX 10 = 100 (Extreme Greed), VIX 40 = 0 (Extreme Fear)
            vix_score = max(0, min(100, 100 - ((vix_val - 10) / 30 * 100)))
            scores.append(('vix', vix_score, 0.25))
            components['vix'] = {'value': vix_val, 'score': round(vix_score)}

        # 2. Market Momentum (25% weight) - S&P 500 vs 125-day MA
        spy_data = snapshot.get('indices', {}).get('SPY')
        if spy_data:
            pct_from_high = spy_data.get('pct_from_high', 0) or 0
            # 0% from high = 100, -20% from high = 0
            momentum_score = max(0, min(100, 100 + (pct_from_high * 5)))
            scores.append(('momentum', momentum_score, 0.25))
            components['momentum'] = {'pct_from_high': pct_from_high, 'score': round(momentum_score)}

        # 3. Market Breadth (20% weight) - Approximation
        # Using IWM (small caps) vs SPY performance
        iwm_data = snapshot.get('indices', {}).get('IWM')
        if spy_data and iwm_data:
            spy_chg = spy_data.get('change', 0)
            iwm_chg = iwm_data.get('change', 0)
            # Small caps outperforming = bullish
            breadth_diff = iwm_chg - spy_chg
            breadth_score = max(0, min(100, 50 + (breadth_diff * 10)))
            scores.append(('breadth', breadth_score, 0.20))
            components['breadth'] = {'spy_chg': spy_chg, 'iwm_chg': iwm_chg, 'score': round(breadth_score)}

        # 4. Safe Haven Demand (15% weight) - Gold vs Stocks
        gold_data = snapshot.get('commodities', {}).get('GC=F')
        if spy_data and gold_data:
            spy_chg = spy_data.get('change', 0)
            gold_chg = gold_data.get('change', 0)
            # Gold outperforming stocks = fear
            haven_diff = spy_chg - gold_chg
            haven_score = max(0, min(100, 50 + (haven_diff * 10)))
            scores.append(('safe_haven', haven_score, 0.15))
            components['safe_haven'] = {'stock_chg': spy_chg, 'gold_chg': gold_chg, 'score': round(haven_score)}

        # 5. Junk Bond Demand (15% weight) - Spread approximation
        # Using bond yields as proxy
        tnx_data = snapshot.get('bonds', {}).get('^TNX')
        if tnx_data:
            yield_chg = tnx_data.get('change', 0)
            # Falling yields (flight to safety) = fear
            junk_score = max(0, min(100, 50 + (yield_chg * 5)))
            scores.append(('junk_bond', junk_score, 0.15))
            components['junk_bond'] = {'yield_change': yield_chg, 'score': round(junk_score)}

        # Calculate weighted average
        if scores:
            total_weight = sum(w for _, _, w in scores)
            weighted_sum = sum(score * weight for _, score, weight in scores)
            final_score = weighted_sum / total_weight if total_weight > 0 else 50
        else:
            final_score = 50

        # Determine level
        if final_score >= 80:
            level = 'Extreme Greed'
            color = '#00C853'
        elif final_score >= 60:
            level = 'Greed'
            color = '#4CAF50'
        elif final_score >= 40:
            level = 'Neutral'
            color = '#FFC107'
        elif final_score >= 20:
            level = 'Fear'
            color = '#FF5722'
        else:
            level = 'Extreme Fear'
            color = '#B71C1C'

        return {
            'score': round(final_score),
            'level': level,
            'color': color,
            'components': components,
        }


class PerplexityAnalyzer:
    """Perplexity AI-powered market analysis"""

    API_URL = "https://api.perplexity.ai/chat/completions"

    def __init__(self):
        self.api_key = os.getenv("PERPLEXITY_API_KEY")
        if not self.api_key:
            print("  [Warning] PERPLEXITY_API_KEY not found")

    async def _query(self, prompt: str, system_prompt: str = None) -> Dict:
        """Query Perplexity API"""
        if not self.api_key:
            return {"content": "", "citations": []}

        if system_prompt is None:
            system_prompt = """You are a senior Wall Street analyst providing institutional-grade market intelligence.

Your analysis style:
- Lead with the most important market-moving information
- Use specific numbers, percentages, and data points
- Cite sources (Fed statements, economic data releases, earnings)
- Be concise but comprehensive
- Focus on actionable insights

Always respond in Korean (한국어) with a professional tone."""

        payload = {
            "model": "sonar",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 4000,
            "return_citations": True,
            "search_recency_filter": "week",
            "search_domain_filter": [
                "reuters.com", "bloomberg.com", "cnbc.com",
                "wsj.com", "marketwatch.com", "finance.yahoo.com",
                "investing.com", "barrons.com", "seekingalpha.com",
                "federalreserve.gov"
            ]
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.API_URL, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=90)
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        print(f"  [Perplexity Error] {response.status}: {error[:200]}")
                        return {"content": "", "citations": []}

                    data = await response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    citations = data.get("citations", [])

                    return {"content": content, "citations": citations}
        except Exception as e:
            print(f"  [Perplexity Error] {e}")
            return {"content": "", "citations": []}

    async def get_market_analysis(self, snapshot: Dict, quant_signals: Dict = None) -> Dict:
        """Get comprehensive market analysis with quant signal context"""

        # Build context from snapshot
        spy = snapshot.get('indices', {}).get('SPY', {})
        qqq = snapshot.get('indices', {}).get('QQQ', {})
        vix = snapshot.get('vix', {})
        tnx = snapshot.get('bonds', {}).get('^TNX', {})
        dxy = snapshot.get('currencies', {}).get('DX-Y.NYB', {})
        usdkrw = snapshot.get('currencies', {}).get('USDKRW=X', {})
        btc = snapshot.get('commodities', {}).get('BTC-USD', {})
        gold = snapshot.get('commodities', {}).get('GC=F', {})

        context = f"""
현재 시장 데이터:
- S&P 500: {spy.get('price', 'N/A')} ({spy.get('change', 0):+.2f}%)
- NASDAQ: {qqq.get('price', 'N/A')} ({qqq.get('change', 0):+.2f}%)
- VIX: {vix.get('value', 'N/A')} ({vix.get('level', 'N/A')})
- 10년물 금리: {tnx.get('price', 'N/A')}%
- 달러인덱스: {dxy.get('price', 'N/A')} ({dxy.get('change', 0):+.2f}%)
- 원/달러: {usdkrw.get('price', 'N/A')}원
- 비트코인: ${btc.get('price', 'N/A'):,.0f} ({btc.get('change', 0):+.2f}%)
- 금: ${gold.get('price', 'N/A'):,.0f} ({gold.get('change', 0):+.2f}%)
"""

        # Add quant signal context if available
        quant_context = ""
        if quant_signals:
            ds = quant_signals.get('decision_signal', {})
            regime = quant_signals.get('regime', {})
            pred = quant_signals.get('prediction', {})
            risk = quant_signals.get('risk', {})
            bt = quant_signals.get('backtest', {})
            track = quant_signals.get('track_record', {})
            picks = quant_signals.get('top_picks', [])

            quant_context = f"""
## 퀀트 시그널 대시보드 (우리 시스템 분석 결과)

### 종합 투자 신호
- Decision Signal: {ds.get('action', 'N/A')} ({ds.get('score', 'N/A')}점/100)
- Timing: {ds.get('timing', 'N/A')}

### 신호 구성 요소
- Market Gate: {ds.get('components', {}).get('market_gate', {}).get('score', 'N/A')}점 (기여: {ds.get('components', {}).get('market_gate', {}).get('contribution', 0):+.1f})
- Market Regime: {regime.get('regime', 'N/A')} (Confidence: {regime.get('confidence', 'N/A')}%) (기여: {ds.get('components', {}).get('regime', {}).get('contribution', 0):+.1f})
- ML Prediction: SPY {pred.get('spy_bullish', 'N/A')}% Bullish, QQQ {pred.get('qqq_bullish', 'N/A')}% Bullish (기여: {ds.get('components', {}).get('prediction', {}).get('contribution', 0):+.1f})
- Risk Level: {risk.get('risk_level', 'N/A')}, VaR(95%,5d): ${risk.get('var_95_5d', 0):,.0f} (기여: {ds.get('components', {}).get('risk', {}).get('contribution', 0):+.1f})
- Business Cycle: {ds.get('components', {}).get('sector_phase', {}).get('phase', 'N/A')} (기여: {ds.get('components', {}).get('sector_phase', {}).get('contribution', 0):+.1f})

### AI Top Picks (퀀트 스크리닝 + AI 분석)
"""
            for p in picks[:5]:
                quant_context += f"- #{p.get('rank', '?')} {p.get('ticker', '?')} ({p.get('name', '')}) | Score: {p.get('final_score', 0)} | {p.get('ai_recommendation', 'N/A')} | Upside: {p.get('target_upside', 0):+.1f}%\n"

            quant_context += f"""
### 백테스트 실적
- 수익률: {bt.get('total_return', 'N/A')}% | Alpha vs SPY: {bt.get('alpha', 'N/A')}%
- Sharpe: {bt.get('sharpe', 'N/A')} | Max Drawdown: {bt.get('max_dd', 'N/A')}% | Win Rate: {bt.get('win_rate', 'N/A')}%

### Track Record (실제 추천 성과)
- 총 추천: {track.get('total_picks', 'N/A')}건 | 승률: {track.get('win_rate', 'N/A')}%
- 평균 수익률: {track.get('avg_return', 'N/A')}% | Alpha vs SPY: {track.get('alpha', 'N/A')}%
"""

        prompt = f"""[Search: US stock market today S&P 500 NASDAQ Fed interest rate economic data]

{context}
{quant_context}

위 실시간 시장 데이터와 퀀트 시그널을 종합하여 오늘 미국 주식시장을 분석해주세요.

## 분석 포맷

### 1. 핵심 요약 (3문장)
- 오늘 시장의 핵심 이슈 + 우리 시스템의 종합 판단 요약
- 가장 중요한 시장 움직임
- Decision Signal과 ML Prediction이 시사하는 향후 전망

### 2. 시장 동향 & 퀀트 신호 해석
- 주요 지수 움직임의 원인
- Market Gate, Regime, ML Prediction이 말해주는 것
- Business Cycle 위치와 섹터 전략 연결

### 3. 매크로 & 이벤트
- 오늘 발표된 경제지표와 시장 반응
- Fed 관련 뉴스/발언
- Risk Level과 VaR가 시사하는 리스크 수준

### 4. 채권/외환/원자재
- 금리 동향과 주식시장 영향
- 달러/원 환율과 한국 투자자 영향
- 금/비트코인 흐름

### 5. 추천 종목 & 전략
- AI Top Picks 종목들의 공통 특징과 선정 이유
- 현재 Decision Signal({ds.get('action', 'N/A')})에 맞는 매매 전략
- 백테스트/Track Record 기반 신뢰도 평가
- 리스크 관리 포인트

### 6. 한국 투자자 액션 플랜
- 오늘 바로 실행할 수 있는 구체적 전략
- 주목 섹터와 종목
- 원/달러 환율 고려 포인트

구체적인 수치와 날짜를 포함하고, 퀀트 시그널의 숫자를 직접 인용하여 설명해주세요.
"""
        return await self._query(prompt)

    async def get_sector_rotation(self) -> Dict:
        """Get sector rotation analysis"""
        prompt = """[Search: US stock market sector rotation ETF flows XLK XLF XLE XLV this week]

미국 주식시장 섹터 로테이션 현황을 분석해주세요.

## 분석 포맷

### 강세 섹터 TOP 3
각 섹터별로:
- 상승률과 원인
- 대표 종목 2-3개
- 지속 가능성 평가

### 약세 섹터 TOP 3
각 섹터별로:
- 하락률과 원인
- 주의해야 할 리스크
- 반등 가능성

### 자금 흐름
- 어디서 어디로 자금이 이동하는지
- ETF 순유입/유출 상위

### 경기 사이클 관점
- 현재 경기 사이클 위치 (초기 확장/중기/후기/침체)
- 이에 따른 섹터 전략

한국어로 답변해주세요.
"""
        return await self._query(prompt)

    async def get_earnings_preview(self) -> Dict:
        """Get earnings preview"""
        prompt = """
이번 주 미국 실적 시즌 현황을 분석해주세요.

## 분석 포맷

### 실적 시즌 현황
- 발표 진행률 (몇 % 완료)
- Beat 비율
- 전년 대비 이익 성장률

### 최근 주요 실적 (어제/오늘)
각 기업별:
- EPS: 실적 vs 예상
- 매출: 실적 vs 예상
- 가이던스 변화
- 시장 반응

### 이번 주 주요 발표 예정
- 날짜별 주요 기업
- 시장 예상치
- 주목 포인트

### 실적 시즌 전략
- 실적 발표 전/후 트레이딩 전략
- 주의해야 할 리스크

한국어로 답변해주세요.
"""
        return await self._query(prompt)


class SmartMoneyIntegration:
    """Integrate Smart Money picks into briefing"""

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir

    def get_top_picks_summary(self, top_n: int = 5) -> Dict:
        """Get top Smart Money picks summary"""
        try:
            report_path = os.path.join(self.data_dir, 'output', 'final_top10_report.json')
            if not os.path.exists(report_path):
                return None

            with open(report_path, 'r', encoding='utf-8') as f:
                report = json.load(f)

            picks = report.get('top_picks', [])[:top_n]

            return {
                'timestamp': report.get('generated_at') or report.get('timestamp'),
                'picks': [{
                    'rank': p.get('rank'),
                    'ticker': p.get('ticker'),
                    'name': p.get('name'),
                    'final_score': p.get('final_score'),
                    'ai_recommendation': p.get('ai_recommendation'),
                    'target_upside': p.get('target_upside'),
                    'sd_stage': p.get('sd_stage'),
                } for p in picks]
            }
        except Exception as e:
            print(f"  [Warning] Smart Money integration failed: {e}")
            return None

    def get_performance_summary(self) -> Dict:
        """Get recent performance summary"""
        try:
            history_dir = os.path.join(self.data_dir, 'history')
            if not os.path.exists(history_dir):
                return None

            # Get recent history files
            files = sorted([f for f in os.listdir(history_dir)
                          if f.startswith('picks_') and f.endswith('.json')],
                          reverse=True)[:5]

            if not files:
                return None

            # Calculate average performance
            csv_path = os.path.join(self.data_dir, 'data', 'us_daily_prices.csv')
            if not os.path.exists(csv_path):
                return None

            df = pd.read_csv(csv_path)
            latest_date = df['Date'].max()
            latest_df = df[df['Date'] == latest_date]

            performances = []
            for f in files[:3]:  # Last 3 dates
                date_str = f[6:-5]
                filepath = os.path.join(history_dir, f)

                with open(filepath, 'r', encoding='utf-8') as hf:
                    snapshot = json.load(hf)

                changes = []
                for pick in snapshot.get('picks', []):
                    ticker = pick['ticker']
                    price_at_rec = pick.get('price_at_analysis', 0)
                    row = latest_df[latest_df['Ticker'] == ticker]
                    if not row.empty and price_at_rec > 0:
                        current = float(row['Close'].iloc[0])
                        change = ((current / price_at_rec) - 1) * 100
                        changes.append(change)

                if changes:
                    import numpy as np
                    performances.append({
                        'date': date_str,
                        'avg_return': round(np.mean(changes), 2),
                        'win_rate': round(len([c for c in changes if c > 0]) / len(changes) * 100, 1),
                    })

            if performances:
                import numpy as np
                return {
                    'recent_dates': performances,
                    'overall_avg': round(np.mean([p['avg_return'] for p in performances]), 2),
                    'overall_win_rate': round(np.mean([p['win_rate'] for p in performances]), 1),
                }
            return None
        except Exception as e:
            print(f"  [Warning] Performance summary failed: {e}")
            return None


class USMarketBriefing:
    """Main briefing orchestrator"""

    def __init__(self):
        self.data_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_fetcher = MarketDataFetcher()
        self.analyzer = PerplexityAnalyzer()
        self.smart_money = SmartMoneyIntegration(data_dir=self.data_dir)

    def _load_quant_signals(self) -> Dict:
        """Load all quant signal data from output files for AI context"""
        signals = {}
        output_dir = os.path.join(self.data_dir, 'output')

        def load_json(filename):
            path = os.path.join(output_dir, filename)
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
            return {}

        # 1. Market Regime
        regime_data = load_json('regime_config.json')
        signals['regime'] = {
            'regime': regime_data.get('regime', 'unknown'),
            'confidence': regime_data.get('confidence', 0),
        }

        # 2. ML Prediction
        pred_data = load_json('index_predictions.json')
        preds = pred_data.get('predictions', {})
        spy_pred = preds.get('spy', preds.get('SPY', {}))
        qqq_pred = preds.get('qqq', preds.get('QQQ', {}))
        signals['prediction'] = {
            'spy_bullish': spy_pred.get('bullish_probability', 50),
            'qqq_bullish': qqq_pred.get('bullish_probability', 50),
        }

        # 3. Risk Alerts
        risk_data = load_json('risk_alerts.json')
        summary = risk_data.get('portfolio_summary', {})
        signals['risk'] = {
            'risk_level': summary.get('risk_level', 'Unknown'),
            'var_95_5d': abs(summary.get('portfolio_var_95_5d', 0)),
            'cvar_95_5d': abs(summary.get('portfolio_cvar_95_5d', 0)),
        }

        # 4. Top Picks
        report_data = load_json('final_top10_report.json')
        signals['top_picks'] = report_data.get('top_picks', [])[:5]

        # 5. Backtest
        bt_data = load_json('backtest_results.json')
        bt_summary = bt_data.get('summary', bt_data.get('performance', {}))
        signals['backtest'] = {
            'total_return': bt_summary.get('total_return_pct', bt_summary.get('total_return', 'N/A')),
            'alpha': bt_summary.get('alpha_vs_spy', bt_summary.get('alpha', 'N/A')),
            'sharpe': bt_summary.get('sharpe_ratio', bt_summary.get('sharpe', 'N/A')),
            'max_dd': bt_summary.get('max_drawdown_pct', bt_summary.get('max_drawdown', 'N/A')),
            'win_rate': bt_summary.get('win_rate', 'N/A'),
        }

        # 6. Track Record
        track_data = load_json('smart_money_current.json')
        # Load cumulative track record from tracker history
        history_dir = os.path.join(self.data_dir, 'history')
        total_picks = 0
        total_wins = 0
        all_returns = []
        spy_returns = []
        if os.path.exists(history_dir):
            import glob
            for hfile in sorted(glob.glob(os.path.join(history_dir, 'picks_*.json')))[-20:]:
                try:
                    with open(hfile, 'r') as f:
                        snap = json.load(f)
                    for pick in snap.get('picks', []):
                        total_picks += 1
                except Exception:
                    pass

        perf_data = self.smart_money.get_performance_summary()
        signals['track_record'] = {
            'total_picks': total_picks or 'N/A',
            'win_rate': perf_data.get('overall_win_rate', 'N/A') if perf_data else 'N/A',
            'avg_return': perf_data.get('overall_avg', 'N/A') if perf_data else 'N/A',
            'alpha': 'N/A',
        }

        # 7. Decision Signal (computed — mirrors backend logic)
        gate_score = 50
        regime_contrib = {'risk_on': 15, 'neutral': 0, 'risk_off': -10, 'crisis': -15}.get(
            signals['regime']['regime'], 0)
        pred_contrib = 0
        spy_bull = signals['prediction']['spy_bullish']
        if spy_bull >= 70:
            pred_contrib = 10
        elif spy_bull <= 30:
            pred_contrib = -10
        risk_contrib = {'Low': 5, 'Moderate': 0, 'High': -10, 'Critical': -20}.get(
            signals['risk']['risk_level'], 0)

        # Load sector phase
        rotation_data = load_json('sector_rotation.json')
        phase = rotation_data.get('rotation_signals', {}).get('current_phase', 'Unknown')
        phase_contrib = {'Early Cycle': 10, 'Mid Cycle': 5, 'Late Cycle': -5, 'Recession': -15}.get(phase, 0)

        ds_score = 50 + 0 + regime_contrib + pred_contrib + risk_contrib + phase_contrib
        ds_score = max(0, min(100, ds_score))

        if ds_score >= 70:
            action = 'BUY'
        elif ds_score >= 55:
            action = 'BUY'
        elif ds_score >= 45:
            action = 'HOLD'
        else:
            action = 'DEFENSIVE'

        signals['decision_signal'] = {
            'score': ds_score,
            'action': action,
            'timing': 'NOW' if gate_score >= 70 else ('WAIT' if gate_score < 40 else 'SELECTIVE'),
            'components': {
                'market_gate': {'score': gate_score, 'contribution': 0},
                'regime': {'regime': signals['regime']['regime'], 'contribution': regime_contrib},
                'prediction': {'spy_bullish': spy_bull, 'contribution': pred_contrib},
                'risk': {'level': signals['risk']['risk_level'], 'contribution': risk_contrib},
                'sector_phase': {'phase': phase, 'contribution': phase_contrib},
            }
        }

        return signals

    async def generate_full_briefing(self) -> Dict:
        """Generate comprehensive market briefing"""
        print("\n" + "="*60)
        print("📊 US Market Professional Briefing")
        print("="*60)

        results = {
            'timestamp': datetime.now().isoformat(),
            'version': '2.0',
        }

        # 1. Real-time market data
        print("\n[1/6] Fetching real-time market data...")
        snapshot = self.data_fetcher.get_market_snapshot()
        results['timestamp'] = self._require_snapshot_timestamp(snapshot)
        results['market_data'] = snapshot

        # 2. VIX
        print("[2/6] Fetching VIX...")
        vix_data = self.data_fetcher.get_vix()
        results['vix'] = vix_data

        # 3. Fear & Greed Index
        print("[3/6] Calculating Fear & Greed Index...")
        fear_greed = self.data_fetcher.calculate_fear_greed_index(vix_data, snapshot)
        results['fear_greed'] = fear_greed

        # 4. AI Analysis (with quant signal context)
        print("[4/6] Loading quant signals & running AI market analysis...")
        snapshot['vix'] = vix_data  # Add VIX to snapshot for context
        quant_signals = self._load_quant_signals()
        analysis = await self.analyzer.get_market_analysis(snapshot, quant_signals)
        results['ai_analysis'] = {
            'content': analysis['content'],
            'citations': analysis['citations'],
        }
        results['quant_signals'] = quant_signals

        # 5. Sector Rotation
        print("[5/6] Analyzing sector rotation...")
        sector = await self.analyzer.get_sector_rotation()
        results['sector_rotation'] = {
            'content': sector['content'],
            'citations': sector['citations'],
        }

        # 6. Smart Money Integration
        print("[6/6] Integrating Smart Money data...")
        smart_picks = self.smart_money.get_top_picks_summary()
        smart_perf = self.smart_money.get_performance_summary()
        results['smart_money'] = {
            'top_picks': smart_picks,
            'performance': smart_perf,
        }

        # Save results
        output_path = os.path.join(os.path.dirname(__file__), "output/market_briefing.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Briefing saved to {output_path}")

        return results

    def _load_existing_briefing(self) -> Dict:
        """Load existing briefing data if available"""
        output_path = os.path.join(os.path.dirname(__file__), "output/market_briefing.json")
        if os.path.exists(output_path):
            try:
                with open(output_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _has_valid_market_data(self, snapshot: Dict) -> bool:
        """Check if snapshot has valid market data"""
        if not isinstance(snapshot, dict):
            return False
        indices = snapshot.get('indices', {})
        return isinstance(indices, dict) and bool(indices)

    def _require_snapshot_timestamp(self, snapshot: Dict) -> str:
        """Reject failed collection before paid analysis or artifact writes."""
        if self._has_valid_market_data(snapshot):
            timestamp = snapshot.get('timestamp')
            try:
                if isinstance(timestamp, str):
                    datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    return timestamp
            except ValueError:
                pass
        raise RuntimeError('Briefing market data refresh failed; previous artifact preserved')

    async def generate_quick_briefing(self) -> Dict:
        """Generate quick briefing (market data only, no AI)"""
        print("\n" + "="*60)
        print("📊 US Market Quick Briefing (No AI)")
        print("="*60)

        # Load existing data for fallback
        existing = self._load_existing_briefing()

        results = {
            'timestamp': datetime.now().isoformat(),
            'version': '2.0',
            'mode': 'quick',
        }

        # 1. Real-time market data
        print("\n[1/4] Fetching real-time market data...")
        snapshot = self.data_fetcher.get_market_snapshot()

        # A failed fetch is not a new observation. Leave the last good file and
        # its timestamp intact instead of making cached indices look fresh.
        results['timestamp'] = self._require_snapshot_timestamp(snapshot)
        results['market_data'] = snapshot

        # 2. VIX
        print("[2/4] Fetching VIX...")
        vix_data = self.data_fetcher.get_vix()
        if vix_data:
            results['vix'] = vix_data
        elif existing.get('vix'):
            print("  ⚠️  Using cached VIX data (fetch failed)")
            results['vix'] = existing['vix']
        else:
            results['vix'] = vix_data

        # 3. Fear & Greed Index
        print("[3/4] Calculating Fear & Greed Index...")
        if results.get('vix') and self._has_valid_market_data(results.get('market_data', {})):
            fear_greed = self.data_fetcher.calculate_fear_greed_index(results['vix'], results['market_data'])
            results['fear_greed'] = fear_greed
        elif existing.get('fear_greed'):
            print("  ⚠️  Using cached Fear & Greed data")
            results['fear_greed'] = existing['fear_greed']
        else:
            results['fear_greed'] = {'score': 50, 'level': 'Neutral', 'color': '#FFC107', 'components': {}}

        # 4. Smart Money
        print("[4/4] Integrating Smart Money data...")
        smart_picks = self.smart_money.get_top_picks_summary()
        smart_perf = self.smart_money.get_performance_summary()
        results['smart_money'] = {
            'top_picks': smart_picks,
            'performance': smart_perf,
        }

        # Preserve AI analysis from existing if available
        if existing.get('ai_analysis'):
            results['ai_analysis'] = existing['ai_analysis']
            results['ai_analysis_timestamp'] = existing.get('ai_analysis_timestamp') or existing.get('timestamp')
        if existing.get('sector_rotation'):
            results['sector_rotation'] = existing['sector_rotation']

        # Save results
        output_path = os.path.join(os.path.dirname(__file__), "output/market_briefing.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Quick briefing saved to {output_path}")

        return results

    def display_briefing(self, results: Dict):
        """Display briefing in terminal"""
        print("\n" + "="*70)
        print("📈 US MARKET PROFESSIONAL BRIEFING")
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("="*70)

        # Market Data
        print("\n📊 MARKET SNAPSHOT")
        print("-"*50)

        indices = results.get('market_data', {}).get('indices', {})
        for symbol, data in indices.items():
            chg = data.get('change', 0)
            emoji = "🟢" if chg >= 0 else "🔴"
            print(f"  {emoji} {data['name']}: {data['price']:,.2f} ({chg:+.2f}%)")

        # Fear & Greed
        fg = results.get('fear_greed', {})
        if fg:
            print(f"\n🎭 Fear & Greed Index: {fg.get('score', 'N/A')} ({fg.get('level', 'N/A')})")

        # VIX
        vix = results.get('vix', {})
        if vix:
            print(f"😰 VIX: {vix.get('value', 'N/A')} ({vix.get('level', 'N/A')})")

        # Bonds & FX
        bonds = results.get('market_data', {}).get('bonds', {})
        currencies = results.get('market_data', {}).get('currencies', {})

        print("\n📉 BONDS & CURRENCIES")
        print("-"*50)
        tnx = bonds.get('^TNX', {})
        if tnx:
            print(f"  10Y Treasury: {tnx.get('price', 'N/A')}%")

        dxy = currencies.get('DX-Y.NYB', {})
        if dxy:
            print(f"  Dollar Index: {dxy.get('price', 'N/A')} ({dxy.get('change', 0):+.2f}%)")

        usdkrw = currencies.get('USDKRW=X', {})
        if usdkrw:
            print(f"  USD/KRW: {usdkrw.get('price', 'N/A'):,.0f}원 ({usdkrw.get('change', 0):+.2f}%)")

        # Smart Money
        sm = results.get('smart_money', {})
        if sm and sm.get('top_picks'):
            print("\n🎯 SMART MONEY TOP 5")
            print("-"*50)
            for p in sm['top_picks'].get('picks', [])[:5]:
                print(f"  #{p['rank']} {p['ticker']}: Score {p['final_score']} | {p['ai_recommendation']}")

        # AI Analysis
        ai = results.get('ai_analysis', {})
        if ai and ai.get('content'):
            print("\n📝 AI MARKET ANALYSIS")
            print("-"*50)
            print(ai['content'][:1500] + "..." if len(ai['content']) > 1500 else ai['content'])

        print("\n" + "="*70)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='US Market Professional Briefing')
    parser.add_argument('--quick', action='store_true', help='Quick update (no AI)')
    args = parser.parse_args()

    briefing = USMarketBriefing()

    if args.quick:
        results = await briefing.generate_quick_briefing()
    else:
        results = await briefing.generate_full_briefing()

    briefing.display_briefing(results)


if __name__ == "__main__":
    asyncio.run(main())
