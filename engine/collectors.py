"""
데이터 수집기
- KRXCollector: pykrx 기반 시세/수급 데이터 수집
- NewsCollector: 네이버 금융 뉴스 크롤링
"""

import asyncio
import os
from datetime import date, datetime, timedelta
from typing import List, Optional
import requests
from bs4 import BeautifulSoup
import pandas as pd
from pykrx import stock as pykrx_stock
import FinanceDataReader as fdr

from .models import StockData, SupplyData, ChartData, NewsData
from .config import SignalConfig


class KRXCollector:
    """KRX 데이터 수집기 (pykrx/fdr 기반)"""
    
    def __init__(self, config: SignalConfig = None):
        self.config = config or SignalConfig()
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
        
    async def get_top_gainers(self, market: str, limit: int = 50) -> List[StockData]:
        """
        상승률 상위 종목 조회 (비동기 래핑)
        """
        candidates = []
        
        # 1. FDR 시도
        try:
            df = fdr.StockListing('KRX')
            
            # 필터링
            market_map = {'KOSPI': 'KOSPI', 'KOSDAQ': 'KOSDAQ'}
            if market in market_map:
                df = df[df['Market'] == market_map[market]]
                
            # 데이터 타입 변환 (안전장치)
            cols_to_numeric = ['Close', 'ChagesRatio', 'Volume', 'Amount', 'Open', 'High', 'Low', 'Changes']
            for col in cols_to_numeric:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            # 등락률 기준 정렬 (ChagesRatio)
            df = df.sort_values(by='ChagesRatio', ascending=False)
            
            count = 0
            for _, row in df.iterrows():
                if count >= limit: break
                
                name = str(row['Name'])
                if any(k in name for k in self.config.exclude_keywords): continue
                if self.config.exclude_preferred and name.endswith('우'): continue
                
                price = int(row['Close'])
                change_pct = float(row['ChagesRatio'])
                if not (self.config.min_price <= price <= self.config.max_price): continue
                if not (self.config.min_change_pct <= change_pct <= self.config.max_change_pct): continue
                if int(row['Amount']) < self.config.min_trading_value: continue
                
                candidates.append(StockData(
                    code=str(row['Code']),
                    name=name,
                    market=market,
                    sector=row.get('Sector', ''),
                    market_cap=row.get('Marcap', 0),
                    open=int(row['Open']),
                    high=int(row['High']),
                    low=int(row['Low']),
                    close=price,
                    volume=int(row['Volume']),
                    trading_value=int(row['Amount']),
                    change_pct=change_pct,
                    change=row.get('Changes', 0)
                ))
                count += 1
            
            if candidates:
                return candidates

        except Exception as e:
            print(f"Warning: FDR fetching failed ({e}), trying pykrx...")

        # 2. Pykrx (Fallback)
        try:
            today_str = date.today().strftime("%Y%m%d")
            
            # 최근 영업일 찾기 (최대 7일 전까지)
            target_date = today_str
            df = pd.DataFrame()
            
            for _ in range(7):
                try:
                    df = pykrx_stock.get_market_ohlcv(target_date, market=market)
                    if not df.empty:
                        break
                except:
                    pass
                # 하루 전으로
                curr = datetime.strptime(target_date, "%Y%m%d")
                target_date = (curr - timedelta(days=1)).strftime("%Y%m%d")
            
            if df.empty:
                print("Warning: Pykrx could not fetch data, trying Naver crawling...")
                return await self._fetch_naver_ranking(market, limit)

            # pykrx 컬럼: 시가, 고가, 저가, 종가, 거래량, 거래대금, 등락률
            df = df.sort_values(by='등락률', ascending=False)
            
            candidates = []
            count = 0
            for code, row in df.iterrows():
                if count >= limit: break
                
                code = str(code)
                name = pykrx_stock.get_market_ticker_name(code)
                
                if any(k in name for k in self.config.exclude_keywords): continue
                if self.config.exclude_preferred and name.endswith('우'): continue
                
                price = int(row['종가'])
                change_pct = float(row['등락률'])
                
                if not (self.config.min_price <= price <= self.config.max_price): continue
                if not (self.config.min_change_pct <= change_pct <= self.config.max_change_pct): continue
                if int(row['거래대금']) < self.config.min_trading_value: continue
                
                candidates.append(StockData(
                    code=code,
                    name=name,
                    market=market,
                    sector="",
                    market_cap=0,
                    open=int(row['시가']),
                    high=int(row['고가']),
                    low=int(row['저가']),
                    close=price,
                    volume=int(row['거래량']),
                    trading_value=int(row['거래대금']),
                    change_pct=change_pct,
                    change=0
                ))
                count += 1
                
            return candidates

        except Exception as e:
            print(f"Error fetching top gainers (pykrx): {e}, trying Naver crawling...")
            return await self._fetch_naver_ranking(market, limit)

    async def _fetch_naver_ranking(self, market: str, limit: int = 50) -> List[StockData]:
        """네이버 금융 상승률 상위 크롤링 (Fallback)"""
        sosok = 0 if market == 'KOSPI' else 1
        url = f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}"
        
        candidates = []
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            # cp949 decoding
            html = resp.content.decode('cp949', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            
            rows = soup.select('table.type_2 tr')
            count = 0
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 10: continue
                
                # 종목명/코드
                title_tag = cols[1].find('a')
                if not title_tag: continue
                
                name = title_tag.text.strip()
                code = title_tag['href'].split('=')[-1]
                
                # 제외 조건
                if any(k in name for k in self.config.exclude_keywords): continue
                if self.config.exclude_preferred and name.endswith('우'): continue
                
                # 데이터 파싱
                try:
                    price_txt = cols[2].text.strip().replace(',', '')
                    if not price_txt.isdigit(): continue
                    price = int(price_txt)
                    
                    change_pct_str = cols[4].text.strip().replace('%', '').replace('+', '')
                    change_pct = float(change_pct_str)
                    
                    volume_txt = cols[5].text.strip().replace(',', '')
                    volume = int(volume_txt)
                    
                    # 거래대금 추정 (volume * price)
                    trading_value = volume * price 
                except:
                    continue
                
                # 필터링
                if not (self.config.min_price <= price <= self.config.max_price): continue
                if not (self.config.min_change_pct <= change_pct <= self.config.max_change_pct): continue
                if trading_value < self.config.min_trading_value: continue
                
                candidates.append(StockData(
                    code=code,
                    name=name,
                    market=market,
                    sector="",
                    market_cap=0,
                    open=price, high=price, low=price, # 상세 정보 없음, 현재가로 대체
                    close=price,
                    volume=volume,
                    trading_value=trading_value,
                    change_pct=change_pct,
                    change=0
                ))
                
                count += 1
                if count >= limit: break
                
        except Exception as e:
            print(f"Error fetching Naver ranking: {e}")
            
        return candidates

    async def get_stock_detail(self, code: str) -> Optional[StockData]:
        """개별 종목 상세 (52주 신고가 등 확인용)"""
        # 이미 Listing에서 대부분 가져왔지만 52주 고가는 따로 체크 필요
        # fdr로 1년치 데이터 가져와서 계산
        try:
            end = date.today()
            start = end - timedelta(days=370)
            df = fdr.DataReader(code, start, end)
            
            if df.empty: return None
            
            # 최근 52주 (약 250거래일)
            df_52w = df.tail(250)
            high_52w = int(df_52w['High'].max())
            low_52w = int(df_52w['Low'].min())
            
            last_row = df.iloc[-1]
            
            return StockData(
                code=code,
                name="", # 이름은 밖에서 채워야 함
                market="",
                high_52w=high_52w,
                low_52w=low_52w,
                close=int(last_row['Close']),
                open=int(last_row['Open']),
                high=int(last_row['High']),
                low=int(last_row['Low']),
                volume=int(last_row['Volume']),
                trading_value=int(last_row['Close'] * last_row['Volume']), # 근사치
                change=int(last_row['Change']), # fdr Close diff
                change_pct=float(last_row['Comp'] if 'Comp' in last_row else 0) # fdr 컬럼 확인 필요
            )
        except:
            return None

    async def get_chart_data(self, code: str, days: int = 60) -> List[ChartData]:
        """차트 데이터 조회"""
        try:
            end = date.today()
            start = end - timedelta(days=days*2) # 넉넉히
            df = fdr.DataReader(code, start, end)
            
            charts = []
            # 이동평균 계산
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA10'] = df['Close'].rolling(window=10).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            
            # 최근 N일
            df = df.tail(days)
            
            for date_idx, row in df.iterrows():
                charts.append(ChartData(
                    code=code,
                    date=date_idx.date(),
                    open=int(row['Open']),
                    high=int(row['High']),
                    low=int(row['Low']),
                    close=int(row['Close']),
                    volume=int(row['Volume']),
                    ma5=row['MA5'] if not pd.isna(row['MA5']) else None,
                    ma10=row['MA10'] if not pd.isna(row['MA10']) else None,
                    ma20=row['MA20'] if not pd.isna(row['MA20']) else None
                ))
            return charts
        except Exception as e:
            print(f"Error fetching chart: {e}")
            return []

    async def get_supply_data(self, code: str) -> Optional[SupplyData]:
        """수급 데이터 조회 (Local CSV - all_institutional_trend_data.csv)"""
        try:
            # CSV가 로드되어 있지 않으면 로드
            if not hasattr(self, 'supply_df') or self.supply_df is None:
                # 경로 수정: data/all_institutional_trend_data.csv
                # Flask 실행 위치(루트) 기준
                csv_path = 'data/all_institutional_trend_data.csv'
                
                # 만약 파일이 없으면 절대 경로로 한 번 더 시도
                if not os.path.exists(csv_path):
                    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'all_institutional_trend_data.csv')
                
                if os.path.exists(csv_path):
                    self.supply_df = pd.read_csv(csv_path, dtype={'ticker': str})
                    self.supply_df.set_index('ticker', inplace=True)
                else:
                    print(f"Warning: Supply data CSV not found at {csv_path}")
                    self.supply_df = pd.DataFrame()

            if self.supply_df.empty or code not in self.supply_df.index:
                return None
                
            row = self.supply_df.loc[code]
            
            # 5일 누적 순매수 데이터 사용
            return SupplyData(
                code=code,
                date=date.today(), # 실제 데이터 날짜는 row['scrape_date']에 있음
                foreign_net=int(row['foreign_net_buy_5d']), # 여기선 5일치를 net으로 매핑하거나 별도 필드 사용
                inst_net=int(row['institutional_net_buy_5d']),
                foreign_buy_5d=int(row['foreign_net_buy_5d']),
                inst_buy_5d=int(row['institutional_net_buy_5d'])
            )
        except Exception as e:
            # print(f"Error supply (CSV): {e}")
            return None

import aiohttp
import asyncio
import re
from urllib.parse import quote, urljoin
from dataclasses import dataclass

@dataclass
class NewsSource:
    """뉴스 소스 설정"""
    name: str
    is_major: bool
    credibility: float  # 신뢰도 (0~1)

# 주요 언론사 목록
MAJOR_SOURCES = {
    # 경제 전문지
    "한국경제": NewsSource("한국경제", True, 0.9),
    "매일경제": NewsSource("매일경제", True, 0.9),
    "머니투데이": NewsSource("머니투데이", True, 0.85),
    "이데일리": NewsSource("이데일리", True, 0.85),
    "서울경제": NewsSource("서울경제", True, 0.85),
    "아시아경제": NewsSource("아시아경제", True, 0.8),
    "파이낸셜뉴스": NewsSource("파이낸셜뉴스", True, 0.8),
    "헤럴드경제": NewsSource("헤럴드경제", True, 0.8),
    "조선비즈": NewsSource("조선비즈", True, 0.85),
    
    # 종합 일간지
    "연합뉴스": NewsSource("연합뉴스", True, 0.95),
    "동아일보": NewsSource("동아일보", True, 0.85),
    "중앙일보": NewsSource("중앙일보", True, 0.85),
    "조선일보": NewsSource("조선일보", True, 0.85),
    
    # 통신사
    "뉴스1": NewsSource("뉴스1", True, 0.8),
    "뉴시스": NewsSource("뉴시스", True, 0.8),
}

class EnhancedNewsCollector:
    """향상된 뉴스 수집기 (네이버/다음/구글 + LLM 본문 수집)"""
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    def __init__(self, config: SignalConfig = None):
        self.config = config or SignalConfig()
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        # Use ThreadedResolver to avoid aiodns/c-ares DNS issues on Windows
        resolver = aiohttp.resolver.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        self._session = aiohttp.ClientSession(
            headers=self.HEADERS, timeout=timeout, connector=connector
        )
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
            
    # 호환성을 위한 메서드 이름 매핑
    async def get_stock_news(self, stock_code: str, limit: int = 3, stock_name: str = "") -> List[NewsData]:
        """기존 인터페이스 호환용 (collect_all + 본문 수집)"""
        # stock_name이 없으면 code로라도... (하지만 검색엔 name이 좋음)
        # KRXCollector 등에서 name을 넘겨주도록 generator 수정 필요.
        # 일단 name이 없으면 생략하고 finance만?
        
        all_news = await self.collect_all(stock_code, stock_name, days=2)
        
        # 주요 뉴스 우선 정렬
        all_news.sort(key=lambda x: (
            self._get_source_info(x.source).credibility, 
            x.published_at or datetime.min
        ), reverse=True)
        
        top_news = all_news[:limit]
        
        # 본문 수집 (LLM용)
        await self.fetch_news_bodies(top_news)
        
        return top_news
    
    async def collect_all(self, stock_code: str, stock_name: str, days: int = 3) -> List[NewsData]:
        """모든 소스에서 뉴스 수집"""
        tasks = [self._collect_naver_finance(stock_code, days)]
        if stock_name:
            tasks.append(self._collect_naver_search(stock_name, days))
            # 다음 검색은 일단 제외 (너무 많아질 수 있음 or 속도)
            # tasks.append(self._collect_daum_search(stock_name, days))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_news = []
        for result in results:
            if isinstance(result, list):
                all_news.extend(result)
        
        # 중복 제거
        seen_titles = set()
        unique_news = []
        for news in all_news:
            normalized = re.sub(r'[^\w]', '', news.title)
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                unique_news.append(news)
                
        # 날짜순 정렬
        unique_news.sort(key=lambda x: x.published_at or datetime.min, reverse=True)
        return unique_news

    async def _collect_naver_finance(self, stock_code: str, days: int) -> List[NewsData]:
        """네이버 금융 - 종목 뉴스"""
        url = f"https://finance.naver.com/item/news_news.naver?code={stock_code}&page=1"
        news_list = []
        cutoff = datetime.now() - timedelta(days=days)
        
        try:
            # Referer 추가
            headers = self.HEADERS.copy()
            headers['Referer'] = f"https://finance.naver.com/item/main.naver?code={stock_code}"
            
            async with self._session.get(url, headers=headers) as resp:
                # 네이버 금융은 cp949
                content = await resp.read()
                try:
                    html = content.decode('cp949')
                except:
                    html = content.decode('utf-8', errors='ignore')
            
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("table.type5 tbody tr")
            
            for row in rows:
                title_tag = row.select_one("td.title a")
                info_tag = row.select_one("td.info")
                date_tag = row.select_one("td.date")
                
                if not title_tag:
                    continue
                
                title = title_tag.text.strip()
                source = info_tag.text.strip() if info_tag else "Unknown"
                date_text = date_tag.text.strip() if date_tag else ""
                
                published_at = self._parse_naver_date(date_text)
                if published_at and published_at < cutoff:
                    break
                
                news_list.append(NewsData(
                    code=stock_code,
                    title=title,
                    source=source,
                    published_at=published_at,
                    url="https://finance.naver.com" + title_tag.get("href", ""),
                    sentiment="neutral",
                ))
        except Exception as e:
            print(f"Error Naver Finance: {e}")
            
        return news_list

    async def _collect_naver_search(self, stock_name: str, days: int) -> List[NewsData]:
        """네이버 뉴스 검색"""
        today = datetime.now()
        start_date = (today - timedelta(days=days)).strftime("%Y.%m.%d")
        end_date = today.strftime("%Y.%m.%d")
        
        encoded_query = quote(stock_name)
        url = f"https://search.naver.com/search.naver?where=news&query={encoded_query}&sort=1&ds={start_date}&de={end_date}"
        
        news_list = []
        try:
            async with self._session.get(url) as resp:
                html = await resp.text()
            
            soup = BeautifulSoup(html, "html.parser")
            items = soup.select("div.news_area")
            
            for item in items[:5]: # 상위 5개만
                title_tag = item.select_one("a.news_tit")
                source_tag = item.select_one("a.info.press")
                
                if not title_tag: continue
                
                title = title_tag.text.strip()
                source = source_tag.text.strip() if source_tag else "Unknown"
                
                # 날짜 파싱 생략 (복잡) -> 현재 시간
                
                news_list.append(NewsData(
                    code="",
                    title=title,
                    source=source,
                    published_at=datetime.now(),
                    url=title_tag.get("href", ""),
                    sentiment="neutral",
                ))
        except Exception as e:
            print(f"Error Naver Search: {e}")
            
        return news_list

    async def fetch_news_bodies(self, news_list: List[NewsData]):
        """뉴스 본문 일괄 수집"""
        tasks = [self._fetch_single_body(news) for news in news_list]
        await asyncio.gather(*tasks)

    async def _fetch_single_body(self, news: NewsData):
        """단일 뉴스 본문 수집"""
        if not news.url: return
        
        try:
            # 타임아웃 3초
            async with self._session.get(news.url, timeout=3) as resp:
                # 인코딩 추론 필요
                # 네이버 금융은 cp949, 일반 뉴스는 utf-8 등 다양
                content = await resp.read()
                
                # 매우 단순화된 인코딩 시도
                html = ""
                try:
                    html = content.decode('cp949')
                except:
                    try:
                        html = content.decode('utf-8')
                    except:
                        html = str(content)
                        
            soup = BeautifulSoup(html, 'html.parser')
            
            # 본문 추출 (네이버 금융, 네이버 뉴스 등)
            body = soup.select_one('#news_read') or soup.select_one('#dic_area') or soup.select_one('.articleCont')
            
            if body:
                text = body.get_text(separator=' ').strip()
                news.summary = text[:500] + "..."
            else:
                # 못 찾으면 메타 태그라도
                desc = soup.select_one('meta[property="og:description"]')
                if desc:
                    news.summary = desc.get('content', '')[:200]
                    
        except Exception as e:
            # 본문 수집 실패해도 치명적이지 않음
            pass

    def _parse_naver_date(self, text: str) -> Optional[datetime]:
        try:
            if re.match(r"\d{4}\.\d{2}\.\d{2}", text):
                return datetime.strptime(text[:10], "%Y.%m.%d")
            return self._parse_relative_date(text)
        except:
            return None

    def _parse_relative_date(self, text: str) -> Optional[datetime]:
        now = datetime.now()
        try:
            if "분" in text:
                val = int(re.search(r"(\d+)", text).group(1))
                return now - timedelta(minutes=val)
            elif "시간" in text:
                val = int(re.search(r"(\d+)", text).group(1))
                return now - timedelta(hours=val)
            elif "일" in text:
                val = int(re.search(r"(\d+)", text).group(1))
                return now - timedelta(days=val)
            elif "어제" in text:
                return now - timedelta(days=1)
        except:
            pass
        return None
        
    def _get_source_info(self, source: str) -> NewsSource:
        for name, info in MAJOR_SOURCES.items():
            if name in source:
                return info
        return NewsSource(source, False, 0.5)

