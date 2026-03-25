# app/routes/stock_analyzer.py
"""종목 분석 (yfinance + Gemini AI) — 클라우드 호환, Selenium 불필요

데이터 소스:
  - yfinance: 애널리스트 추천, 목표가, 재무제표, 시세 (KR + US)
  - Finnhub:  추천 트렌드 보조 데이터 (US, 60회/분 무료)
  - Gemini:   AI 투자 요약 (컨센서스 + 목표가 기반 한국어 3문장)

v2: 버그수정 (iloc[-1]→iloc[0], 52wk low=0, np.int64, yf1.1 news)
    + Gemini AI 요약, 분기 재무, 뉴스 헤드라인
"""

import os
import time
import logging
import pandas as pd
from io import BytesIO
from flask import Blueprint, jsonify, request, send_file
from datetime import datetime

logger = logging.getLogger('stock_analyzer')

stock_analyzer_bp = Blueprint('stock_analyzer', __name__)


def _consensus_label(score: float) -> str:
    """컨센서스 점수 → 한글 라벨 (공용)"""
    if score >= 4.3:
        return '적극 매수'
    elif score >= 3.7:
        return '매수'
    elif score >= 2.7:
        return '중립'
    elif score >= 2.0:
        return '매도'
    return '적극 매도'


# ── 경로 설정 ──
from app.utils.paths import BASE_DIR, DATA_DIR, TICKER_MAP_PATH

_DATA_DIR = DATA_DIR

# ── KR 종목 매핑 (lazy load) ──
_kr_stocks = None


def _load_kr_stocks():
    """ticker_to_yahoo_map.csv 로드 — KR 종목 이름 → yfinance 심볼 매핑"""
    global _kr_stocks
    if _kr_stocks is not None:
        return _kr_stocks

    try:
        df = pd.read_csv(TICKER_MAP_PATH)
        _kr_stocks = []
        for _, row in df.iterrows():
            _kr_stocks.append({
                'ticker': str(row.get('ticker', '')).strip(),
                'yahoo': str(row.get('yahoo_ticker', '')).strip(),
                'name': str(row.get('name', '')).strip(),
                'market': str(row.get('market', '')).strip(),
            })
        logger.info(f"[StockAnalyzer] {len(_kr_stocks)}개 KR 종목 매핑 로드")
    except Exception as e:
        logger.error(f"[StockAnalyzer] 매핑 로드 실패: {e}")
        _kr_stocks = []

    return _kr_stocks


# ── US 인기 종목 (빠른 검색용, 한글명 포함) ──
# (ticker, english_name, korean_name)
_US_POPULAR = [
    ('AAPL', 'Apple', '애플'), ('MSFT', 'Microsoft', '마이크로소프트'), ('GOOGL', 'Alphabet', '알파벳/구글'),
    ('AMZN', 'Amazon', '아마존'), ('NVDA', 'NVIDIA', '엔비디아'), ('META', 'Meta Platforms', '메타'),
    ('TSLA', 'Tesla', '테슬라'), ('BRK-B', 'Berkshire Hathaway', '버크셔해서웨이'), ('JPM', 'JPMorgan Chase', 'JP모건'),
    ('V', 'Visa', '비자'), ('UNH', 'UnitedHealth', '유나이티드헬스'), ('MA', 'Mastercard', '마스터카드'),
    ('HD', 'Home Depot', '홈디포'), ('PG', 'Procter & Gamble', 'P&G/프록터앤갬블'), ('JNJ', 'Johnson & Johnson', '존슨앤존슨'),
    ('COST', 'Costco', '코스트코'), ('ABBV', 'AbbVie', '애브비'), ('CRM', 'Salesforce', '세일즈포스'),
    ('MRK', 'Merck', '머크'), ('AVGO', 'Broadcom', '브로드컴'), ('KO', 'Coca-Cola', '코카콜라'),
    ('PEP', 'PepsiCo', '펩시코'), ('TMO', 'Thermo Fisher', '써모피셔'), ('AMD', 'AMD', 'AMD'),
    ('NFLX', 'Netflix', '넷플릭스'), ('ADBE', 'Adobe', '어도비'), ('DIS', 'Disney', '디즈니'),
    ('INTC', 'Intel', '인텔'), ('QCOM', 'Qualcomm', '퀄컴'), ('CSCO', 'Cisco', '시스코'),
    ('BA', 'Boeing', '보잉'), ('GS', 'Goldman Sachs', '골드만삭스'), ('CAT', 'Caterpillar', '캐터필러'),
    ('IBM', 'IBM', 'IBM'), ('GE', 'GE Aerospace', 'GE/제너럴일렉트릭'), ('UBER', 'Uber', '우버'),
    ('PLTR', 'Palantir', '팔란티어'), ('COIN', 'Coinbase', '코인베이스'), ('MSTR', 'MicroStrategy', '마이크로스트래티지'),
    ('ARM', 'ARM Holdings', 'ARM/에이알엠'), ('SMCI', 'Super Micro', '슈퍼마이크로'), ('MU', 'Micron', '마이크론'),
    ('SNOW', 'Snowflake', '스노우플레이크'), ('PANW', 'Palo Alto Networks', '팔로알토'), ('CRWD', 'CrowdStrike', '크라우드스트라이크'),
    ('SQ', 'Block', '블록/스퀘어'), ('SHOP', 'Shopify', '쇼피파이'), ('ROKU', 'Roku', '로쿠'),
    ('SOFI', 'SoFi', '소파이'), ('RIVN', 'Rivian', '리비안'),
]


# ============================================================
# 헬퍼: 52주 저/고가 보정 (KR 종목 yfinance 0.0 버그 수정)
# ============================================================

def _fix_52wk_range(ticker_obj, info: dict) -> dict:
    """fiftyTwoWeekLow/High가 0 또는 None이면 1년 히스토리로 직접 계산"""
    low_ok = (info.get('fiftyTwoWeekLow') or 0) > 0
    high_ok = (info.get('fiftyTwoWeekHigh') or 0) > 0

    if low_ok and high_ok:
        return info  # 이미 정상

    try:
        hist = ticker_obj.history(period='1y')
        if hist is not None and len(hist) > 0:
            # 당일 미결 행(Low=0)을 제외하고 계산
            valid = hist[hist['Low'] > 0]
            if len(valid) > 0:
                if not low_ok:
                    info['fiftyTwoWeekLow'] = round(float(valid['Low'].min()), 0)
                if not high_ok:
                    info['fiftyTwoWeekHigh'] = round(float(valid['High'].max()), 0)
    except Exception as e:
        logger.debug(f"52wk range 보정 실패: {e}")

    return info


# ============================================================
# 헬퍼: 분기 재무 데이터 추출
# ============================================================

def _get_quarterly_financials(ticker_obj) -> dict:
    """분기별 매출·순이익 (최근 4분기) — quarterly_income_stmt 사용"""
    result = {}
    try:
        stmt = ticker_obj.quarterly_income_stmt
        if stmt is None:
            return result

        if 'Total Revenue' in stmt.index:
            rev = stmt.loc['Total Revenue'].dropna()
            result['revenue_quarters'] = [
                {'date': col.strftime('%Y-%m'), 'value': int(val)}
                for col, val in list(zip(rev.index, rev.values))[:4]
            ]

        if 'Net Income' in stmt.index:
            ni = stmt.loc['Net Income'].dropna()
            result['net_income_quarters'] = [
                {'date': col.strftime('%Y-%m'), 'value': int(val)}
                for col, val in list(zip(ni.index, ni.values))[:4]
            ]
    except Exception as e:
        logger.debug(f"분기 재무 추출 실패: {e}")

    return result


# ============================================================
# 헬퍼: 뉴스 헤드라인 (yfinance 1.1.0 구조)
# ============================================================

def _get_news_headlines(ticker_obj) -> list:
    """최신 뉴스 5건 — yfinance 1.1.x content 구조 대응"""
    headlines = []
    try:
        news = ticker_obj.news
        if not news:
            return headlines

        for item in news[:5]:
            # yfinance 1.1.x: {'id': ..., 'content': {'title': ..., 'summary': ..., 'canonicalUrl': ...}}
            content = item.get('content', {})
            if isinstance(content, dict):
                title = content.get('title', '')
                summary = content.get('summary', '')
                url = (content.get('canonicalUrl') or {}).get('url', '')
                provider = (content.get('provider') or {}).get('displayName', '')
                pub_time = content.get('pubDate', '')
            else:
                # 구버전 호환
                title = item.get('title', '')
                summary = ''
                url = item.get('link', '')
                provider = item.get('publisher', '')
                pub_time = ''

            if title:
                headlines.append({
                    'title': title,
                    'summary': summary[:200] if summary else '',
                    'url': url,
                    'provider': provider,
                    'pub_time': pub_time,
                })
    except Exception as e:
        logger.debug(f"뉴스 추출 실패: {e}")

    return headlines


# ============================================================
# 헬퍼: Gemini AI 투자 요약
# ============================================================

def _gemini_analysis(
    stock_name: str,
    yahoo_ticker: str,
    recommendation: str,
    consensus_score: float | None,
    analyst_count: int,
    current_price: float | None,
    price_targets: dict | None,
    key_stats: dict | None,
) -> str | None:
    """Gemini 2.0 Flash으로 애널리스트 데이터 기반 한국어 투자 요약 생성 (3문장 이내)"""
    api_key = os.getenv('GEMINI_API_KEY', '')
    if not api_key or not recommendation or recommendation == '데이터 없음':
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        currency = 'KRW' if '.KS' in yahoo_ticker or '.KQ' in yahoo_ticker else 'USD'
        price_fmt = f"{current_price:,.0f} {currency}" if current_price else "미확인"

        # 목표가 상승여력
        upside_txt = ''
        if price_targets and price_targets.get('mean') and current_price and current_price > 0:
            upside_pct = (price_targets['mean'] - current_price) / current_price * 100
            upside_txt = f"\n목표가 평균: {price_targets['mean']:,.0f} {currency} (현재가 대비 {upside_pct:+.1f}%)"

        sector = (key_stats or {}).get('sector', '')
        pe = (key_stats or {}).get('pe_ratio')
        pe_txt = f"\nPER: {pe:.1f}x" if pe else ''

        prompt = f"""다음 종목의 애널리스트 분석 데이터를 바탕으로 투자 의견 요약을 한국어 3문장 이내로 작성하세요.

종목: {stock_name} ({yahoo_ticker})
섹터: {sector or '미확인'}
현재가: {price_fmt}
애널리스트 컨센서스: {recommendation} (점수 {consensus_score}/5.0, {analyst_count}명 참여){upside_txt}{pe_txt}

요구사항:
- 반드시 3문장 이내
- 컨센서스 의견과 목표가 상승여력 포함
- 투자 권유 없이 데이터 기반 서술
- 불필요한 면책조항 없이 간결하게"""

        resp = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.3, max_output_tokens=250),
        )
        return resp.text.strip()
    except Exception as e:
        logger.warning(f"Gemini 분석 실패 ({yahoo_ticker}): {e}")
        return None


# ============================================================
# 분석 엔진 (yfinance + Finnhub)
# ============================================================

def _analyze_with_yfinance(yahoo_ticker: str) -> dict:
    """yfinance로 종목 분석 — 추천, 목표가, 재무, 시세

    수정 내역 (v2):
      - recs.iloc[-1] → recs.iloc[0] (가장 최신 데이터 사용)
      - 52주 저/고가 0.0 보정 (KR 종목 yfinance 버그)
      - np.int64 → int 변환 (JSON 직렬화 안전성)
      - 분기 재무, 뉴스, Gemini AI 분석 추가
    """
    import yfinance as yf

    ticker = yf.Ticker(yahoo_ticker)
    result = {
        'yahoo_ticker': yahoo_ticker,
        'recommendation': None,
        'recommendation_detail': None,
        'recommendation_period': None,
        'price_targets': None,
        'current_price': None,
        'key_stats': None,
        'revenue_quarters': None,
        'net_income_quarters': None,
        'news': None,
        'ai_analysis': None,
        'source': 'yfinance',
    }

    # ── 1) 기본 정보 (시세, 시총, PER 등) ──
    try:
        info = ticker.info or {}
        logger.info(f"[yfinance] {yahoo_ticker} info keys: {list(info.keys())[:10]}")
        result['current_price'] = info.get('currentPrice') or info.get('regularMarketPrice')

        # fast_info 폴백: info가 비어있으면 fast_info에서 가격 추출
        if not result['current_price']:
            try:
                fi = ticker.fast_info
                result['current_price'] = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
            except Exception:
                pass

        # history 폴백: 최근 종가 사용
        if not result['current_price']:
            try:
                hist = ticker.history(period='5d')
                if hist is not None and len(hist) > 0:
                    result['current_price'] = round(float(hist['Close'].iloc[-1]), 2)
            except Exception:
                pass

        # 52주 저/고가 보정 (KR 종목 0.0 버그 수정)
        info = _fix_52wk_range(ticker, info)

        result['key_stats'] = {
            'name': info.get('shortName') or info.get('longName', ''),
            'sector': info.get('sector', ''),
            'industry': info.get('industry', ''),
            'market_cap': info.get('marketCap'),
            'pe_ratio': info.get('trailingPE'),
            'forward_pe': info.get('forwardPE'),
            'dividend_yield': info.get('dividendYield'),
            'beta': info.get('beta'),
            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
            'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
            'revenue': info.get('totalRevenue'),
            'profit_margin': info.get('profitMargins'),
            'currency': info.get('currency', 'KRW' if '.K' in yahoo_ticker else 'USD'),
        }
    except Exception as e:
        logger.warning(f"yfinance info 실패 ({yahoo_ticker}): {e}")

    # ── 2) 애널리스트 추천 (strongBuy/buy/hold/sell/strongSell) ──
    # [BUG FIX v2] iloc[-1] → iloc[0]: 가장 최신(현재 월) 데이터 사용
    try:
        recs = ticker.recommendations
        if recs is not None and len(recs) > 0:
            # iloc[0] = 현재 월(0m), iloc[1] = 1개월 전, ...
            latest = recs.iloc[0]
            period = str(latest.get('period', ''))  # '0m', '-1m', '-2m', '-3m'

            detail = {
                'strongBuy': int(latest.get('strongBuy', 0)),
                'buy': int(latest.get('buy', 0)),
                'hold': int(latest.get('hold', 0)),
                'sell': int(latest.get('sell', 0)),
                'strongSell': int(latest.get('strongSell', 0)),
            }
            result['recommendation_detail'] = detail
            result['recommendation_period'] = period  # 프론트엔드에 기간 표시용

            total = sum(detail.values())
            if total > 0:
                score = (
                    detail['strongBuy'] * 5 +
                    detail['buy'] * 4 +
                    detail['hold'] * 3 +
                    detail['sell'] * 2 +
                    detail['strongSell'] * 1
                ) / total

                result['recommendation'] = _consensus_label(score)
                result['consensus_score'] = round(score, 2)
                result['analyst_count'] = total
    except Exception as e:
        logger.warning(f"yfinance recommendations 실패 ({yahoo_ticker}): {e}")

    # ── 3) 목표가 ──
    try:
        targets = ticker.analyst_price_targets
        if targets and isinstance(targets, dict):
            result['price_targets'] = {
                'current': targets.get('current'),
                'high': targets.get('high'),
                'low': targets.get('low'),
                'mean': targets.get('mean'),
                'median': targets.get('median'),
            }
            # 현재가 대비 상승 여력
            cp = result['current_price']
            mean_t = targets.get('mean')
            if cp and mean_t and cp > 0:
                upside = ((mean_t - cp) / cp) * 100
                result['upside_potential'] = round(upside, 1)
    except Exception as e:
        logger.warning(f"yfinance price_targets 실패 ({yahoo_ticker}): {e}")

    # ── 4) 분기 재무 데이터 ──
    financials = _get_quarterly_financials(ticker)
    result.update(financials)

    # ── 5) 뉴스 헤드라인 (yfinance 1.1.x 구조) ──
    result['news'] = _get_news_headlines(ticker)

    return result


def _analyze_with_fmp(symbol: str) -> dict:
    """FMP API로 종목 분석 — yfinance 실패 시 클라우드 폴백

    FMP 무료 티어 사용 엔드포인트:
      /stable/quote            → price, yearHigh/Low, marketCap
      /stable/profile          → sector, industry, beta, 52wk range
      /stable/price-target-consensus → 목표가
      /stable/grades           → 애널리스트 등급 → 컨센서스 계산
      /stable/income-statement → 분기 매출/순이익
    """
    import requests
    from collections import Counter

    api_key = os.getenv('FMP_API_KEY', '')
    if not api_key:
        return {}

    # KR 종목은 FMP 미지원 (US 전용)
    is_kr = symbol.endswith('.KS') or symbol.endswith('.KQ')
    if is_kr:
        return {}

    fmp_symbol = symbol
    h = {'User-Agent': 'Mozilla/5.0'}
    base = 'https://financialmodelingprep.com/stable'

    result = {
        'recommendation': None, 'recommendation_detail': None,
        'recommendation_period': 'FMP', 'price_targets': None,
        'current_price': None, 'key_stats': None,
        'revenue_quarters': None, 'net_income_quarters': None,
        'news': None, 'ai_analysis': None, 'source': 'fmp',
    }

    # ── 1) Quote ──
    try:
        r = requests.get(f'{base}/quote?symbol={fmp_symbol}&apikey={api_key}', headers=h, timeout=10)
        if r.ok and r.json():
            q = r.json()[0]
            result['current_price'] = q.get('price')
            result['key_stats'] = {
                'name': q.get('name', ''), 'sector': '', 'industry': '',
                'market_cap': q.get('marketCap'), 'pe_ratio': None, 'forward_pe': None,
                'dividend_yield': None, 'beta': None,
                'fifty_two_week_high': q.get('yearHigh'),
                'fifty_two_week_low': q.get('yearLow'),
                'revenue': None, 'profit_margin': None, 'currency': 'USD',
            }
    except Exception:
        pass

    # ── 2) Profile (sector/industry/beta) ──
    try:
        r = requests.get(f'{base}/profile?symbol={fmp_symbol}&apikey={api_key}', headers=h, timeout=10)
        if r.ok and r.json() and result.get('key_stats'):
            p = r.json()[0]
            ks = result['key_stats']
            ks['sector'] = p.get('sector', '')
            ks['industry'] = p.get('industry', '')
            ks['beta'] = p.get('beta')
            # 52wk range fallback: "169.21-288.62"
            rng = p.get('range', '')
            if rng and '-' in rng and not (ks.get('fifty_two_week_low') or 0):
                parts = rng.split('-')
                try:
                    ks['fifty_two_week_low'] = float(parts[0])
                    ks['fifty_two_week_high'] = float(parts[1])
                except ValueError:
                    pass
    except Exception:
        pass

    # ── 3) Price Target ──
    try:
        r = requests.get(f'{base}/price-target-consensus?symbol={fmp_symbol}&apikey={api_key}', headers=h, timeout=10)
        if r.ok:
            td = r.json()
            t = (td[0] if isinstance(td, list) else td) if td else {}
            if t and not isinstance(t, str):
                result['price_targets'] = {
                    'current': result.get('current_price'),
                    'high': t.get('targetHigh'), 'low': t.get('targetLow'),
                    'mean': t.get('targetConsensus'), 'median': t.get('targetMedian'),
                }
                cp = result.get('current_price')
                m = t.get('targetConsensus')
                if cp and m and cp > 0:
                    result['upside_potential'] = round((m - cp) / cp * 100, 1)
    except Exception:
        pass

    # ── 4) Grades → 컨센서스 ──
    try:
        r = requests.get(f'{base}/grades?symbol={fmp_symbol}&limit=30&apikey={api_key}', headers=h, timeout=10)
        if r.ok and r.json():
            grades = r.json()
            # 회사별 최신 등급 (limit=30은 최신순이므로 첫 등장만 취함)
            by_company: dict[str, str] = {}
            for item in grades:
                co = item.get('gradingCompany', '')
                if co and co not in by_company:
                    by_company[co] = item.get('newGrade', '')

            BUY = ['buy', 'outperform', 'overweight', 'market outperform', 'sector outperform', 'positive']
            SELL = ['sell', 'underperform', 'underweight', 'market underperform', 'sector underperform', 'negative']

            cnt: dict[str, int] = {'strongBuy': 0, 'buy': 0, 'hold': 0, 'sell': 0, 'strongSell': 0}
            for g in by_company.values():
                gl = g.lower().strip()
                if 'strong buy' in gl:
                    cnt['strongBuy'] += 1
                elif 'strong sell' in gl:
                    cnt['strongSell'] += 1
                elif any(t in gl for t in BUY):
                    cnt['buy'] += 1
                elif any(t in gl for t in SELL):
                    cnt['sell'] += 1
                else:
                    cnt['hold'] += 1

            total = sum(cnt.values())
            if total > 0:
                score = (cnt['strongBuy']*5 + cnt['buy']*4 + cnt['hold']*3
                         + cnt['sell']*2 + cnt['strongSell']*1) / total
                result['recommendation'] = _consensus_label(score)
                result['consensus_score'] = round(score, 2)
                result['analyst_count'] = total
                result['recommendation_detail'] = cnt
    except Exception:
        pass

    # ── 5) Quarterly Financials ──
    try:
        r = requests.get(
            f'{base}/income-statement?symbol={fmp_symbol}&period=quarter&limit=4&apikey={api_key}',
            headers=h, timeout=10,
        )
        if r.ok and r.json():
            stmts = r.json()
            result['revenue_quarters'] = [
                {'date': s.get('date', '')[:7], 'value': int(s.get('revenue') or 0)}
                for s in stmts if s.get('revenue')
            ]
            result['net_income_quarters'] = [
                {'date': s.get('date', '')[:7], 'value': int(s.get('netIncome') or 0)}
                for s in stmts if s.get('netIncome') is not None
            ]
    except Exception:
        pass

    # ── 6) News (FMP v3 → Yahoo Finance fallback) ──
    def _parse_fmp_news(articles: list) -> list:
        return [
            {
                'title': a.get('title', ''),
                'summary': (a.get('text') or '')[:200],
                'url': a.get('url', '#'),
                'provider': a.get('site', ''),
                'pub_time': a.get('publishedDate', ''),
            }
            for a in articles[:5]
            if a.get('title')
        ]

    try:
        # 1차: FMP v3 stock_news
        r = requests.get(
            f'https://financialmodelingprep.com/api/v3/stock_news?tickers={fmp_symbol}&limit=5&apikey={api_key}',
            headers=h, timeout=10,
        )
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                result['news'] = _parse_fmp_news(data)
    except Exception:
        pass

    if not result.get('news'):
        try:
            # 2차: FMP stable news
            r = requests.get(
                f'{base}/news?symbol={fmp_symbol}&limit=5&apikey={api_key}',
                headers=h, timeout=10,
            )
            if r.ok:
                data = r.json()
                if isinstance(data, list) and data:
                    result['news'] = _parse_fmp_news(data)
        except Exception:
            pass

    if not result.get('news'):
        try:
            # 3차: Google News RSS (API 키 불필요, IP 제한 없음)
            import xml.etree.ElementTree as ET
            company_name = (result.get('key_stats') or {}).get('name') or fmp_symbol
            query = requests.utils.quote(f'{fmp_symbol} {company_name} stock')
            rss_url = f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
            r = requests.get(rss_url, headers=h, timeout=8)
            if r.ok:
                root = ET.fromstring(r.content)
                items = root.findall('.//item')
                result['news'] = [
                    {
                        'title': item.findtext('title', ''),
                        'summary': '',
                        'url': item.findtext('link', '#'),
                        'provider': item.findtext('source', ''),
                        'pub_time': item.findtext('pubDate', ''),
                    }
                    for item in items[:5]
                    if item.findtext('title')
                ]
        except Exception:
            pass

    return result


def _supplement_with_finnhub(ticker_symbol: str, yf_result: dict) -> dict:
    """Finnhub으로 US 종목 추천 데이터 보완 (무료 60회/분)"""
    api_key = os.getenv('FINNHUB_API_KEY', '')
    if not api_key or '.K' in ticker_symbol:
        return yf_result

    try:
        import requests
        url = f'https://finnhub.io/api/v1/stock/recommendation?symbol={ticker_symbol}&token={api_key}'
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                latest = data[0]
                yf_result['finnhub_supplement'] = {
                    'strongBuy': latest.get('strongBuy', 0),
                    'buy': latest.get('buy', 0),
                    'hold': latest.get('hold', 0),
                    'sell': latest.get('sell', 0),
                    'strongSell': latest.get('strongSell', 0),
                    'period': latest.get('period', ''),
                }
    except Exception as e:
        logger.warning(f"Finnhub 보완 실패 ({ticker_symbol}): {e}")

    return yf_result


# ============================================================
# API Endpoints
# ============================================================

@stock_analyzer_bp.route('/search')
def search_stocks():
    """종목 검색 (KR + US, 이름/티커 부분 매칭, 최대 20건)"""
    q = request.args.get('q', '').strip().lower()
    market = request.args.get('market', 'all').strip().lower()

    if not q:
        return jsonify([])

    results = []

    # 1) KR 종목 검색
    if market in ('kr', 'all'):
        kr_stocks = _load_kr_stocks()
        for s in kr_stocks:
            name = s['name'].lower()
            ticker = s['ticker'].lower()
            yahoo = s['yahoo'].lower()
            if q in name or q in ticker or q in yahoo:
                results.append({
                    'name': s['name'],
                    'ticker': s['yahoo'],
                    'code': s['ticker'],
                    'market': s['market'],
                    'type': 'KR',
                })
                if len(results) >= 20:
                    break

    # 2) US 종목 검색 (영문명 + 한글명)
    if market in ('us', 'all') and len(results) < 20:
        for t_sym, name, name_kr in _US_POPULAR:
            if q in t_sym.lower() or q in name.lower() or q in name_kr.lower():
                results.append({
                    'name': name,
                    'name_kr': name_kr,
                    'ticker': t_sym,
                    'code': t_sym,
                    'market': 'US',
                    'type': 'US',
                })
                if len(results) >= 20:
                    break

    # 3) US 직접 티커 입력 (목록에 없는 종목, 영문만)
    if len(results) == 0 and q.isascii() and q.replace('-', '').isalpha() and len(q) <= 5:
        results.append({
            'name': q.upper(),
            'ticker': q.upper(),
            'code': q.upper(),
            'market': 'US',
            'type': 'US_DIRECT',
        })

    return jsonify(results)


_ANALYZE_CACHE_DIR = os.path.join(_DATA_DIR, 'stock_analyzer_cache')
os.makedirs(_ANALYZE_CACHE_DIR, exist_ok=True)

# 캐시 TTL: 6시간 (v2: 24h → 6h, 시장 데이터 신선도)
_CACHE_TTL_HOURS = 6


def _get_cached_analysis(ticker: str) -> dict | None:
    """캐시된 분석 결과 반환 (6시간 유효)

    뉴스/AI분석 누락 캐시는 무효화하여 재수집.
    """
    cache_file = os.path.join(_ANALYZE_CACHE_DIR, f'{ticker.replace(".", "_")}.json')
    if not os.path.exists(cache_file):
        return None
    try:
        import json
        with open(cache_file, 'r', encoding='utf-8') as f:
            cached = json.load(f)
        cached_time = datetime.strptime(cached.get('date', ''), '%Y-%m-%d %H:%M:%S')
        age_hours = (datetime.now() - cached_time).total_seconds() / 3600
        if age_hours < _CACHE_TTL_HOURS:
            # 뉴스가 없거나 AI 분석이 없는 캐시는 무효화 (구버전 캐시)
            if not cached.get('news') or not cached.get('ai_analysis'):
                return None
            cached['_from_cache'] = True
            cached['_cache_age_hours'] = round(age_hours, 1)
            return cached
    except Exception:
        pass
    return None


def _save_analysis_cache(ticker: str, response: dict):
    """분석 결과를 캐시에 저장"""
    cache_file = os.path.join(_ANALYZE_CACHE_DIR, f'{ticker.replace(".", "_")}.json')
    try:
        import json
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"캐시 저장 실패 ({ticker}): {e}")


@stock_analyzer_bp.route('/analyze', methods=['POST'])
def analyze_stock():
    """종목 분석 — yfinance + Gemini AI

    Request body: { "ticker": "005930.KS" | "AAPL", "name": "삼성전자" }
    """
    data = request.json or {}
    ticker = data.get('ticker', '').strip()
    name = data.get('name', ticker)

    if not ticker:
        return jsonify({'error': '티커가 없습니다.'}), 400

    # 캐시 확인 (6시간 TTL)
    cached = _get_cached_analysis(ticker)
    if cached:
        logger.info(f"[StockAnalyzer] {ticker}: 캐시 반환 ({cached.get('_cache_age_hours', '?')}h)")
        return jsonify(cached)

    try:
        start = time.time()
        result = _analyze_with_yfinance(ticker)

        # Finnhub 보조 (US 종목만, API 키 있을 때)
        if not ticker.endswith('.KS') and not ticker.endswith('.KQ'):
            result = _supplement_with_finnhub(ticker, result)

        # ── FMP 폴백: yfinance가 데이터를 못 가져온 경우 (클라우드 환경) ──
        yf_failed = not result.get('current_price') and not result.get('recommendation')
        if yf_failed and not ticker.endswith('.KS') and not ticker.endswith('.KQ'):
            logger.info(f"[StockAnalyzer] {ticker}: yfinance 실패 → FMP 폴백 시도")
            fmp_result = _analyze_with_fmp(ticker)
            if fmp_result.get('current_price') or fmp_result.get('recommendation'):
                result = fmp_result
                logger.info(f"[StockAnalyzer] {ticker}: FMP 폴백 성공 (price={fmp_result.get('current_price')})")

        elapsed = round(time.time() - start, 1)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        recommendation = result.get('recommendation')
        if not recommendation:
            if result.get('current_price'):
                recommendation = '데이터 없음'
            else:
                logger.warning(f"[StockAnalyzer] {ticker}: yfinance 데이터 없음")
                return jsonify({
                    'error': f'{name} ({ticker}) — Yahoo Finance 데이터를 가져올 수 없습니다. '
                             f'KR 중소형주는 Yahoo Finance 미제공 종목일 수 있습니다.',
                    'name': name,
                    'ticker': ticker,
                }), 404

        # Gemini AI 분석 (recommendation 있을 때만)
        ai_text = None
        if recommendation and recommendation != '데이터 없음':
            ai_text = _gemini_analysis(
                stock_name=name,
                yahoo_ticker=ticker,
                recommendation=recommendation,
                consensus_score=result.get('consensus_score'),
                analyst_count=result.get('analyst_count', 0),
                current_price=result.get('current_price'),
                price_targets=result.get('price_targets'),
                key_stats=result.get('key_stats'),
            )

        response = {
            'name': name,
            'ticker': ticker,
            'result': recommendation,
            'date': now,
            'elapsed': elapsed,

            # 컨센서스
            'consensus_score': result.get('consensus_score'),
            'analyst_count': result.get('analyst_count', 0),
            'recommendation_detail': result.get('recommendation_detail'),
            'recommendation_period': result.get('recommendation_period'),

            # 가격 / 목표가
            'price_targets': result.get('price_targets'),
            'current_price': result.get('current_price'),
            'upside_potential': result.get('upside_potential'),

            # 주요 지표
            'key_stats': result.get('key_stats'),
            'finnhub_supplement': result.get('finnhub_supplement'),
            'source': result.get('source', 'yfinance'),

            # 신규 필드 (v2)
            'ai_analysis': ai_text,
            'revenue_quarters': result.get('revenue_quarters'),
            'net_income_quarters': result.get('net_income_quarters'),
            'news': result.get('news'),
        }

        _save_analysis_cache(ticker, response)
        return jsonify(response)

    except Exception as e:
        logger.exception(f"분석 실패 ({ticker}): {e}")
        return jsonify({
            'error': f'{name} 분석 실패: {str(e)[:200]}',
            'name': name,
        }), 500


@stock_analyzer_bp.route('/export', methods=['POST'])
def export_history():
    """클라이언트 조회 기록을 Excel로 변환하여 다운로드"""
    data = request.json or {}
    records = data.get('records', [])

    if not records:
        return jsonify({'error': '저장할 데이터가 없습니다.'}), 400

    df = pd.DataFrame(records)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)

    filename = datetime.now().strftime('%y%m%d') + '_analyst_consensus.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )
