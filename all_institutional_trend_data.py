#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import numpy as np
import requests
from bs4 import BeautifulSoup
import re
from tqdm import tqdm
import concurrent.futures
from typing import Dict, List, Optional, Tuple
import json
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('institutional_trend_analyzer.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class TrendConfig:
    """트렌드 분석 설정"""
    strong_buy_inst: int = 3000000      # 기관 강매수 기준 (3백만주)
    buy_inst: int = 1000000             # 기관 매수 기준 (1백만주)
    neutral_inst: int = -500000         # 기관 중립 기준
    sell_inst: int = -1000000           # 기관 매도 기준
    strong_sell_inst: int = -3000000    # 기관 강매도 기준

    strong_buy_foreign: int = 5000000   # 외국인 강매수 기준 (5백만주)
    buy_foreign: int = 2000000          # 외국인 매수 기준 (2백만주)
    neutral_foreign: int = -1000000     # 외국인 중립 기준
    sell_foreign: int = -2000000        # 외국인 매도 기준
    strong_sell_foreign: int = -5000000 # 외국인 강매도 기준

    high_ratio_inst: float = 8.0        # 기관 고비율 기준
    high_ratio_foreign: float = 12.0    # 외국인 고비율 기준

    accumulation_volume_threshold: int = 1000000  # 매집 판단 최소 거래량

@dataclass
class InstitutionalData:
    """기관 데이터 구조"""
    ticker: str
    scrape_date: str
    data_source: str
    total_days: int

    # 기관 순매매량
    institutional_net_buy_60d: int = 0
    institutional_net_buy_20d: int = 0
    institutional_net_buy_10d: int = 0
    institutional_net_buy_5d: int = 0

    # 외국인 순매매량
    foreign_net_buy_60d: int = 0
    foreign_net_buy_20d: int = 0
    foreign_net_buy_10d: int = 0
    foreign_net_buy_5d: int = 0

    # 거래량
    total_volume_60d: int = 0
    total_volume_20d: int = 0
    total_volume_10d: int = 0
    total_volume_5d: int = 0

    # 거래량 대비 비율
    institutional_ratio_60d: float = 0.0
    institutional_ratio_20d: float = 0.0
    institutional_ratio_10d: float = 0.0
    institutional_ratio_5d: float = 0.0

    foreign_ratio_60d: float = 0.0
    foreign_ratio_20d: float = 0.0
    foreign_ratio_10d: float = 0.0
    foreign_ratio_5d: float = 0.0

    # 가격 변화
    price_change_60d: float = 0.0

    # 트렌드 분석
    institutional_trend: str = 'neutral'
    foreign_trend: str = 'neutral'
    supply_demand_index: float = 50.0
    supply_demand_stage: str = '중립'

    # 매집 신호
    strong_accumulation: int = 0
    accumulation_signal: int = 0
    accumulation_intensity: str = '보통'
    trend_strength: str = '보통'

    # 추가 분석 지표
    momentum_score: float = 0.0
    consistency_score: float = 0.0
    volume_pattern: str = '보통'
    risk_level: str = '중간'

class EnhancedKoreanInstitutionalTrendAnalyzer:
    """한국 주식 전체 기관/외국인 순매매 트렌드 분석기 (업그레이드 버전)"""

    def __init__(self, data_dir: str = None, config: TrendConfig = None):
        # DATA_DIR 환경 변수 우선 사용
        if data_dir is None:
            data_dir = os.getenv('DATA_DIR', '.')
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        self.all_institutional_csv_path = self.data_dir / 'all_institutional_trend_data.csv'
        self.config = config or TrendConfig()

        # 세션 설정 (연결 풀링)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

        # 네이버 금융 URL 패턴
        self.base_url = "https://finance.naver.com/item/frgn.naver"

        # 캐시 및 성능 최적화
        self._cache = {}
        self._cache_expiry = {}
        self.cache_duration = 300  # 5분

        # 스레드 락
        self._lock = threading.Lock()

        # 요청 제한 (rate limiting)
        self.request_delay = 0.3
        self.max_retries = 3
        self.backoff_factor = 1.5

        logger.info(f"✅ Enhanced 기관 트렌드 분석기 초기화 완료")
        logger.info(f"📁 데이터 디렉토리: {self.data_dir}")

    def __del__(self):
        """소멸자 - 세션 정리"""
        if hasattr(self, 'session'):
            self.session.close()

    def load_all_stock_info(self) -> pd.DataFrame:
        """전체 주식 정보 로드 (캐시 지원)"""
        cache_key = 'stock_info'

        # 캐시 확인
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        try:
            stock_info_path = self.data_dir / 'korean_stocks_list.csv'

            if stock_info_path.exists():
                df = pd.read_csv(stock_info_path, encoding='utf-8')
                logger.info(f"✅ 전체 주식 정보 로드: {len(df)}개 종목")

                # 캐시 저장
                self._cache[cache_key] = df
                self._cache_expiry[cache_key] = time.time() + self.cache_duration

                return df
            else:
                logger.error("❌ stock_info.csv 파일이 없습니다")
                return pd.DataFrame()

        except Exception as e:
            logger.error(f"❌ 주식 정보 로드 실패: {e}")
            return pd.DataFrame()

    def _is_cache_valid(self, key: str) -> bool:
        """캐시 유효성 검사"""
        return (key in self._cache and
                key in self._cache_expiry and
                time.time() < self._cache_expiry[key])

    def _make_request_with_retry(self, url: str, timeout: int = 15) -> Optional[requests.Response]:
        """재시도 로직이 있는 HTTP 요청"""
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=timeout)
                response.raise_for_status()

                # 요청 제한
                time.sleep(self.request_delay)
                return response

            except requests.exceptions.RequestException as e:
                wait_time = self.backoff_factor ** attempt
                logger.warning(f"⚠️ 요청 실패 (시도 {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    logger.info(f"🔄 {wait_time:.1f}초 후 재시도...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ 최대 재시도 횟수 초과: {url}")
                    return None

        return None

    def scrape_naver_institutional_trend_data(self, ticker: str) -> Optional[InstitutionalData]:
        """네이버에서 60일 기관/외국인 순매매 트렌드 데이터 스크래핑 (업그레이드)"""
        try:
            # 캐시 확인
            cache_key = f"institutional_{ticker}"
            if self._is_cache_valid(cache_key):
                return self._cache[cache_key]

            # 네이버 금융 URL
            url = f"{self.base_url}?code={ticker}"

            # 웹페이지 요청
            response = self._make_request_with_retry(url)
            if not response:
                return self._create_fallback_data(ticker)

            # 한글 인코딩 설정
            response.encoding = 'euc-kr'

            # BeautifulSoup으로 파싱
            soup = BeautifulSoup(response.text, 'html.parser')

            # 기관/외국인 순매매 테이블 찾기
            daily_data = self._extract_daily_data(soup)

            # 트렌드 분석
            if daily_data and len(daily_data) >= 5:  # 최소 5일 데이터 필요
                institutional_data = self._analyze_comprehensive_trend(ticker, daily_data)

                # 캐시 저장
                with self._lock:
                    self._cache[cache_key] = institutional_data
                    self._cache_expiry[cache_key] = time.time() + self.cache_duration

                return institutional_data
            else:
                logger.warning(f"⚠️ {ticker} 충분한 데이터 없음 (수집된 일수: {len(daily_data) if daily_data else 0})")
                return self._create_fallback_data(ticker)

        except Exception as e:
            logger.warning(f"⚠️ {ticker} 스크래핑 실패: {e}")
            return self._create_fallback_data(ticker)

    def _extract_daily_data(self, soup: BeautifulSoup) -> List[Dict]:
        """일별 데이터 추출"""
        daily_data = []

        try:
            # 테이블 찾기 - 더 정확한 선택자 사용
            tables = soup.find_all('table', class_='type2')
            if not tables:
                tables = soup.find_all('table')

            for table in tables:
                rows = table.find_all('tr')

                for row in rows:
                    cells = row.find_all(['td', 'th'])

                    if len(cells) >= 7:  # 기관/외국인 데이터가 있는 행
                        try:
                            # 날짜 확인 (더 강건한 정규식)
                            date_cell = cells[0].get_text(strip=True)
                            if not re.match(r'\d{4}\.\d{2}\.\d{2}', date_cell):
                                continue

                            # 데이터 추출
                            close_price = self._parse_number(cells[1].get_text(strip=True))
                            volume = self._parse_number(cells[4].get_text(strip=True))
                            inst_value = self._parse_number_with_sign(cells[5].get_text(strip=True))
                            foreign_value = self._parse_number_with_sign(cells[6].get_text(strip=True))

                            # 데이터 유효성 검사
                            if volume > 0:  # 거래량이 있는 경우만
                                daily_data.append({
                                    'date': date_cell,
                                    'close_price': close_price,
                                    'volume': volume,
                                    'institutional_net_buy': inst_value,
                                    'foreign_net_buy': foreign_value
                                })

                                # 60일 데이터만 수집
                                if len(daily_data) >= 60:
                                    break

                        except (IndexError, ValueError) as e:
                            continue

                if len(daily_data) >= 60:
                    break

            return daily_data

        except Exception as e:
            logger.warning(f"⚠️ 일별 데이터 추출 실패: {e}")
            return []

    def _parse_number(self, text: str) -> int:
        """숫자 파싱 (개선된 버전)"""
        try:
            # 쉼표 제거 및 공백 제거
            text = re.sub(r'[,\s]', '', text)

            # 숫자만 추출
            numbers = re.findall(r'\d+', text)
            return int(numbers[0]) if numbers else 0

        except:
            return 0

    def _parse_number_with_sign(self, text: str) -> int:
        """부호를 포함한 숫자 파싱 (개선된 버전)"""
        try:
            # 쉼표 제거 및 공백 제거
            text = re.sub(r'[,\s]', '', text)

            # + 또는 - 기호와 숫자 추출
            if '+' in text or '▲' in text:
                numbers = re.findall(r'\d+', text)
                return int(numbers[0]) if numbers else 0
            elif '-' in text or '▼' in text:
                numbers = re.findall(r'\d+', text)
                return -int(numbers[0]) if numbers else 0
            else:
                numbers = re.findall(r'\d+', text)
                return int(numbers[0]) if numbers else 0

        except:
            return 0

    def _analyze_comprehensive_trend(self, ticker: str, daily_data: List[Dict]) -> InstitutionalData:
        """종합적인 트렌드 분석 (업그레이드)"""
        try:
            df = pd.DataFrame(daily_data)

            # 기간별 데이터 분할
            periods = {
                '60d': df,
                '20d': df.head(20),
                '10d': df.head(10),
                '5d': df.head(5)
            }

            # 기본 지표 계산
            metrics = {}
            for period, data in periods.items():
                metrics[f'institutional_net_buy_{period}'] = int(data['institutional_net_buy'].sum())
                metrics[f'foreign_net_buy_{period}'] = int(data['foreign_net_buy'].sum())
                metrics[f'total_volume_{period}'] = int(data['volume'].sum())

                # 거래량 대비 비율 계산
                total_volume = metrics[f'total_volume_{period}']
                if total_volume > 0:
                    metrics[f'institutional_ratio_{period}'] = round(
                        (metrics[f'institutional_net_buy_{period}'] / total_volume * 100), 2
                    )
                    metrics[f'foreign_ratio_{period}'] = round(
                        (metrics[f'foreign_net_buy_{period}'] / total_volume * 100), 2
                    )
                else:
                    metrics[f'institutional_ratio_{period}'] = 0.0
                    metrics[f'foreign_ratio_{period}'] = 0.0

            # 가격 변화 계산
            price_change_60d = 0.0
            if len(df) >= 2:
                price_change_60d = round(
                    (df.iloc[0]['close_price'] - df.iloc[-1]['close_price']) / df.iloc[-1]['close_price'] * 100, 2
                )

            # 고급 트렌드 분석
            trend_analysis = self._advanced_trend_analysis(metrics)

            # 추가 지표 계산
            additional_metrics = self._calculate_additional_metrics(df, metrics)

            # InstitutionalData 객체 생성
            institutional_data = InstitutionalData(
                ticker=ticker,
                scrape_date=datetime.now().strftime('%Y-%m-%d'),
                data_source='naver_finance_enhanced',
                total_days=len(df),
                price_change_60d=price_change_60d,
                **metrics,
                **trend_analysis,
                **additional_metrics
            )

            return institutional_data

        except Exception as e:
            logger.warning(f"⚠️ {ticker} 트렌드 분석 실패: {e}")
            return self._create_fallback_data(ticker)

    def _advanced_trend_analysis(self, metrics: Dict) -> Dict:
        """고급 트렌드 분석"""
        try:
            # 기관 트렌드 분석
            inst_trend = self._determine_advanced_trend(
                metrics['institutional_net_buy_60d'],
                metrics['institutional_net_buy_20d'],
                metrics['institutional_net_buy_5d'],
                metrics['institutional_ratio_20d'],
                'institutional'
            )

            # 외국인 트렌드 분석
            foreign_trend = self._determine_advanced_trend(
                metrics['foreign_net_buy_60d'],
                metrics['foreign_net_buy_20d'],
                metrics['foreign_net_buy_5d'],
                metrics['foreign_ratio_20d'],
                'foreign'
            )

            # 수급 지수 계산 (개선된 알고리즘)
            supply_demand_index = self._calculate_enhanced_supply_demand_index(metrics)

            # 수급 단계 판단
            supply_demand_stage = self._determine_supply_demand_stage(supply_demand_index)

            # 매집 신호 분석
            accumulation_analysis = self._analyze_accumulation_signals(metrics)

            # 트렌드 강도 계산
            trend_strength = self._calculate_trend_strength(metrics)

            return {
                'institutional_trend': inst_trend,
                'foreign_trend': foreign_trend,
                'supply_demand_index': round(supply_demand_index, 1),
                'supply_demand_stage': supply_demand_stage,
                'trend_strength': trend_strength,
                **accumulation_analysis
            }

        except Exception as e:
            logger.warning(f"⚠️ 고급 트렌드 분석 실패: {e}")
            return {
                'institutional_trend': 'neutral',
                'foreign_trend': 'neutral',
                'supply_demand_index': 50.0,
                'supply_demand_stage': '중립',
                'strong_accumulation': 0,
                'accumulation_signal': 0,
                'accumulation_intensity': '보통',
                'trend_strength': '보통'
            }

    def _determine_advanced_trend(self, total_60d: int, total_20d: int, total_5d: int,
                                ratio_20d: float, investor_type: str) -> str:
        """고급 트렌드 판단 (거래량 비율과 모멘텀 고려)"""
        try:
            if investor_type == 'institutional':
                # 기관 트렌드 판단
                if (total_60d > self.config.strong_buy_inst and
                    total_5d > 0 and
                    ratio_20d > self.config.high_ratio_inst):
                    return 'strong_buying'
                elif (total_60d > self.config.buy_inst and
                      (ratio_20d > 3 or total_20d > total_60d * 0.4)):
                    return 'buying'
                elif (total_60d < self.config.strong_sell_inst and
                      ratio_20d < -self.config.high_ratio_inst):
                    return 'strong_selling'
                elif (total_60d < self.config.sell_inst and
                      (ratio_20d < -3 or total_20d < total_60d * 0.4)):
                    return 'selling'
                else:
                    return 'neutral'
            else:  # foreign
                # 외국인 트렌드 판단
                if (total_60d > self.config.strong_buy_foreign and
                    total_5d > 0 and
                    ratio_20d > self.config.high_ratio_foreign):
                    return 'strong_buying'
                elif (total_60d > self.config.buy_foreign and
                      (ratio_20d > 5 or total_20d > total_60d * 0.4)):
                    return 'buying'
                elif (total_60d < self.config.strong_sell_foreign and
                      ratio_20d < -self.config.high_ratio_foreign):
                    return 'strong_selling'
                elif (total_60d < self.config.sell_foreign and
                      (ratio_20d < -5 or total_20d < total_60d * 0.4)):
                    return 'selling'
                else:
                    return 'neutral'

        except Exception as e:
            logger.warning(f"⚠️ 고급 트렌드 판단 실패: {e}")
            return 'neutral'

    def _calculate_enhanced_supply_demand_index(self, metrics: Dict) -> float:
        """향상된 수급 지수 계산 (0-100)"""
        try:
            # 기관 점수 (0-50)
            inst_score = self._calculate_investor_score(
                metrics['institutional_net_buy_60d'],
                metrics['institutional_net_buy_20d'],
                metrics['institutional_net_buy_5d'],
                metrics['institutional_ratio_20d'],
                'institutional'
            )

            # 외국인 점수 (0-50)
            foreign_score = self._calculate_investor_score(
                metrics['foreign_net_buy_60d'],
                metrics['foreign_net_buy_20d'],
                metrics['foreign_net_buy_5d'],
                metrics['foreign_ratio_20d'],
                'foreign'
            )

            # 거래량 가중치 적용
            volume_weight = min(metrics['total_volume_20d'] / 10000000, 1.0)  # 최대 1천만주 기준

            final_score = (inst_score + foreign_score) * (0.8 + 0.2 * volume_weight)

            return min(max(final_score, 0), 100)

        except Exception as e:
            logger.warning(f"⚠️ 수급 지수 계산 실패: {e}")
            return 50.0

    def _calculate_investor_score(self, total_60d: int, total_20d: int, total_5d: int,
                                ratio_20d: float, investor_type: str) -> float:
        """투자자별 점수 계산 (0-50)"""
        try:
            # 기본 점수 (순매매량 기준)
            if investor_type == 'institutional':
                base_score = min(max(total_60d / 6000000 * 25 + 25, 0), 35)
            else:  # foreign
                base_score = min(max(total_60d / 10000000 * 25 + 25, 0), 35)

            # 최근 활동 점수 (0-10)
            recent_score = min(max(total_20d / (total_60d + 1) * 10, 0), 10)

            # 거래량 비율 점수 (0-5)
            ratio_score = min(max(ratio_20d / 10 * 2.5 + 2.5, 0), 5)

            return base_score + recent_score + ratio_score

        except Exception as e:
            logger.warning(f"⚠️ 투자자 점수 계산 실패: {e}")
            return 25.0

    def _analyze_accumulation_signals(self, metrics: Dict) -> Dict:
        """매집 신호 분석"""
        try:
            # 강한 매집 신호
            strong_accumulation = 0
            if (metrics['institutional_net_buy_20d'] > 2000000 and
                metrics['foreign_net_buy_20d'] > 3000000 and
                metrics['institutional_net_buy_5d'] > 0 and
                metrics['foreign_net_buy_5d'] > 0 and
                (metrics['institutional_ratio_20d'] > 8 or metrics['foreign_ratio_20d'] > 12) and
                metrics['total_volume_20d'] > self.config.accumulation_volume_threshold):
                strong_accumulation = 1

            # 일반 매집 신호
            accumulation_signal = 0
            if (metrics['institutional_net_buy_20d'] > 0 and
                metrics['foreign_net_buy_20d'] > 0 and
                (metrics['institutional_ratio_20d'] > 3 or metrics['foreign_ratio_20d'] > 5)):
                accumulation_signal = 1

            # 매집 강도
            total_ratio = metrics['institutional_ratio_20d'] + metrics['foreign_ratio_20d']
            if total_ratio > 25:
                accumulation_intensity = '매우강함'
            elif total_ratio > 15:
                accumulation_intensity = '강함'
            elif total_ratio > 8:
                accumulation_intensity = '보통'
            elif total_ratio > 0:
                accumulation_intensity = '약함'
            else:
                accumulation_intensity = '매도세'

            return {
                'strong_accumulation': strong_accumulation,
                'accumulation_signal': accumulation_signal,
                'accumulation_intensity': accumulation_intensity
            }

        except Exception as e:
            logger.warning(f"⚠️ 매집 신호 분석 실패: {e}")
            return {
                'strong_accumulation': 0,
                'accumulation_signal': 0,
                'accumulation_intensity': '보통'
            }

    def _calculate_trend_strength(self, metrics: Dict) -> str:
        """트렌드 강도 계산"""
        try:
            total_net_buy = metrics['institutional_net_buy_60d'] + metrics['foreign_net_buy_60d']
            total_ratio = metrics['institutional_ratio_20d'] + metrics['foreign_ratio_20d']

            # 거래량 비율을 고려한 강도 판단
            if total_ratio > 20 and total_net_buy > 5000000:
                return '매우강함'
            elif total_ratio > 12 and total_net_buy > 2000000:
                return '강함'
            elif total_ratio > 6 or total_net_buy > 1000000:
                return '보통'
            elif total_ratio > 0 or total_net_buy > -1000000:
                return '약함'
            else:
                return '매우약함'

        except Exception as e:
            logger.warning(f"⚠️ 트렌드 강도 계산 실패: {e}")
            return '보통'

    def _calculate_additional_metrics(self, df: pd.DataFrame, metrics: Dict) -> Dict:
        """추가 지표 계산"""
        try:
            # 모멘텀 점수 (최근 5일 vs 이전 기간)
            recent_5d_inst = metrics['institutional_net_buy_5d']
            prev_15d_inst = metrics['institutional_net_buy_20d'] - recent_5d_inst

            recent_5d_foreign = metrics['foreign_net_buy_5d']
            prev_15d_foreign = metrics['foreign_net_buy_20d'] - recent_5d_foreign

            if prev_15d_inst != 0:
                inst_momentum = (recent_5d_inst * 3 - prev_15d_inst) / abs(prev_15d_inst) * 100
            else:
                inst_momentum = 0

            if prev_15d_foreign != 0:
                foreign_momentum = (recent_5d_foreign * 3 - prev_15d_foreign) / abs(prev_15d_foreign) * 100
            else:
                foreign_momentum = 0

            momentum_score = round((inst_momentum + foreign_momentum) / 2, 1)

            # 일관성 점수 (변동성 기반)
            if len(df) >= 10:
                inst_daily = df['institutional_net_buy'].head(10).tolist()
                foreign_daily = df['foreign_net_buy'].head(10).tolist()

                inst_consistency = 100 - min(np.std(inst_daily) / (abs(np.mean(inst_daily)) + 1) * 100, 100)
                foreign_consistency = 100 - min(np.std(foreign_daily) / (abs(np.mean(foreign_daily)) + 1) * 100, 100)

                consistency_score = round((inst_consistency + foreign_consistency) / 2, 1)
            else:
                consistency_score = 50.0

            # 거래량 패턴
            avg_volume = metrics['total_volume_20d'] / 20
            recent_volume = metrics['total_volume_5d'] / 5

            if recent_volume > avg_volume * 1.5:
                volume_pattern = '급증'
            elif recent_volume > avg_volume * 1.2:
                volume_pattern = '증가'
            elif recent_volume < avg_volume * 0.7:
                volume_pattern = '감소'
            elif recent_volume < avg_volume * 0.5:
                volume_pattern = '급감'
            else:
                volume_pattern = '보통'

            # 리스크 레벨
            total_ratio = abs(metrics['institutional_ratio_20d']) + abs(metrics['foreign_ratio_20d'])
            if total_ratio > 20:
                risk_level = '높음'
            elif total_ratio > 10:
                risk_level = '중간'
            else:
                risk_level = '낮음'

            return {
                'momentum_score': momentum_score,
                'consistency_score': consistency_score,
                'volume_pattern': volume_pattern,
                'risk_level': risk_level
            }

        except Exception as e:
            logger.warning(f"⚠️ 추가 지표 계산 실패: {e}")
            return {
                'momentum_score': 0.0,
                'consistency_score': 50.0,
                'volume_pattern': '보통',
                'risk_level': '중간'
            }

    def _determine_supply_demand_stage(self, supply_demand_index: float) -> str:
        """수급 단계 판단"""
        if supply_demand_index >= 85:
            return "강한매집"
        elif supply_demand_index >= 70:
            return "매집"
        elif supply_demand_index >= 60:
            return "약매집"
        elif supply_demand_index >= 40:
            return "중립"
        elif supply_demand_index >= 30:
            return "약분산"
        elif supply_demand_index >= 15:
            return "분산"
        else:
            return "강한분산"

    def _create_fallback_data(self, ticker: str) -> InstitutionalData:
        """스크래핑 실패시 대체 데이터"""
        return InstitutionalData(
            ticker=ticker,
            scrape_date=datetime.now().strftime('%Y-%m-%d'),
            data_source='fallback_estimation',
            total_days=0
        )

    def download_all_institutional_data(self, max_stocks: int = None,
                                      max_workers: int = 5,
                                      save_interval: int = 100) -> pd.DataFrame:
        """전체 주식 기관 데이터 다운로드 (멀티스레딩)"""
        logger.info("🚀 Enhanced 전체 주식 기관/외국인 순매매 트렌드 데이터 다운로드 시작...")

        # 전체 주식 정보 로드
        stock_df = self.load_all_stock_info()

        if stock_df.empty:
            logger.error("❌ 주식 정보를 로드할 수 없습니다")
            return pd.DataFrame()

        # 최대 종목 수 제한 (테스트용)
        if max_stocks:
            stock_df = stock_df.head(max_stocks)
            logger.info(f"📊 테스트 모드: 상위 {max_stocks}개 종목만 처리")

        tickers = stock_df['ticker'].tolist()
        logger.info(f"📈 총 {len(tickers)}개 종목 처리 예정 (스레드: {max_workers}개)")

        results = []
        success_count = 0
        fail_count = 0

        # 멀티스레딩으로 데이터 수집
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 진행률 표시
            with tqdm(total=len(tickers), desc="기관 데이터 수집") as pbar:
                # Future 객체들을 제출
                future_to_ticker = {
                    executor.submit(self.scrape_naver_institutional_trend_data, ticker): ticker
                    for ticker in tickers
                }

                # 결과 수집
                for i, future in enumerate(concurrent.futures.as_completed(future_to_ticker)):
                    ticker = future_to_ticker[future]

                    try:
                        institutional_data = future.result()
                        if institutional_data and institutional_data.total_days > 0:
                            results.append(asdict(institutional_data))
                            success_count += 1
                        else:
                            fail_count += 1

                    except Exception as e:
                        logger.warning(f"⚠️ {ticker} 처리 실패: {e}")
                        fail_count += 1

                    pbar.update(1)

                    # 주기적 중간 저장 (제거됨)
                    # if (i + 1) % save_interval == 0 and results:
                    #     self._save_intermediate_results(results, i + 1)

        df = pd.DataFrame(results)

        logger.info(f"✅ Enhanced 전체 기관 데이터 다운로드 완료!")
        logger.info(f"   📊 성공: {success_count}개")
        logger.info(f"   ❌ 실패: {fail_count}개")
        logger.info(f"   📈 성공률: {success_count/(success_count+fail_count)*100:.1f}%" if (success_count+fail_count) > 0 else "성공률: 0%")

        return df

    def _save_intermediate_results(self, results: List[Dict], count: int):
        """중간 결과 저장"""
        try:
            temp_df = pd.DataFrame(results)
            temp_path = self.data_dir / f'temp_institutional_data_{count}.csv'
            temp_df.to_csv(temp_path, index=False, encoding='utf-8-sig')
            logger.info(f"💾 중간 저장: {temp_path} ({len(temp_df)}개)")
        except Exception as e:
            logger.warning(f"⚠️ 중간 저장 실패: {e}")

    def save_institutional_data(self, df: pd.DataFrame) -> bool:
        """기관 수급 데이터를 CSV에 저장 (메타데이터 포함)"""
        try:
            if df.empty:
                logger.warning("⚠️ 저장할 데이터가 없습니다")
                return False

            # 데이터 정리 및 검증
            df_cleaned = self._clean_and_validate_data(df)

            # CSV 파일로 저장
            df_cleaned.to_csv(self.all_institutional_csv_path, index=False, encoding='utf-8-sig')

            # 상세 메타데이터 저장
            metadata = self._create_metadata(df_cleaned)
            metadata_df = pd.DataFrame([metadata])
            metadata_path = self.data_dir / 'all_institutional_metadata.csv'
            metadata_df.to_csv(metadata_path, index=False, encoding='utf-8-sig')

            # 통계 요약 저장
            summary = self._create_summary_statistics(df_cleaned)
            summary_df = pd.DataFrame([summary])
            summary_path = self.data_dir / 'institutional_summary.csv'
            summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')

            logger.info(f"📁 Enhanced 기관 트렌드 데이터 저장 완료: {self.all_institutional_csv_path}")
            logger.info(f"   📊 데이터 개수: {len(df_cleaned)}개")
            logger.info(f"   📅 수집 일시: {metadata['collection_date']}")

            return True

        except Exception as e:
            logger.error(f"❌ 기관 데이터 저장 실패: {e}")
            return False

    def _clean_and_validate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """데이터 정리 및 검증"""
        try:
            # 중복 제거
            df_cleaned = df.drop_duplicates(subset=['ticker'])

            # 필수 컬럼 확인
            required_columns = [
                'ticker', 'institutional_net_buy_60d', 'foreign_net_buy_60d',
                'institutional_ratio_20d', 'foreign_ratio_20d', 'supply_demand_index'
            ]

            missing_columns = [col for col in required_columns if col not in df_cleaned.columns]
            if missing_columns:
                logger.warning(f"⚠️ 누락된 컬럼: {missing_columns}")

            # 데이터 타입 변환
            numeric_columns = [col for col in df_cleaned.columns if 'ratio' in col or 'index' in col or 'score' in col or 'change' in col]
            for col in numeric_columns:
                if col in df_cleaned.columns:
                    df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors='coerce').fillna(0)

            # 이상치 제거 (너무 극단적인 값)
            for col in numeric_columns:
                if col in df_cleaned.columns:
                    q99 = df_cleaned[col].quantile(0.99)
                    q01 = df_cleaned[col].quantile(0.01)
                    df_cleaned[col] = df_cleaned[col].clip(lower=q01, upper=q99)

            logger.info(f"✅ 데이터 정리 완료: {len(df)} → {len(df_cleaned)}개")
            return df_cleaned

        except Exception as e:
            logger.warning(f"⚠️ 데이터 정리 실패: {e}")
            return df

    def _create_metadata(self, df: pd.DataFrame) -> Dict:
        """메타데이터 생성"""
        return {
            'collection_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_stocks': len(df),
            'data_source': 'naver_finance_enhanced_60day_trend',
            'description': 'Enhanced 전체 한국 주식 60일 기관/외국인 순매매 트렌드 데이터',
            'version': '2.0',
            'columns_count': len(df.columns),
            'successful_scrapes': len(df[df['total_days'] > 0]),
            'failed_scrapes': len(df[df['total_days'] == 0]),
            'average_data_days': df['total_days'].mean(),
            'config_used': asdict(self.config)
        }

    def _create_summary_statistics(self, df: pd.DataFrame) -> Dict:
        """통계 요약 생성"""
        try:
            return {
                'summary_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_stocks': len(df),

                # 기관 통계
                'inst_net_buy_20d_mean': df['institutional_net_buy_20d'].mean(),
                'inst_net_buy_20d_median': df['institutional_net_buy_20d'].median(),
                'inst_ratio_20d_mean': df['institutional_ratio_20d'].mean(),
                'inst_ratio_20d_median': df['institutional_ratio_20d'].median(),

                # 외국인 통계
                'foreign_net_buy_20d_mean': df['foreign_net_buy_20d'].mean(),
                'foreign_net_buy_20d_median': df['foreign_net_buy_20d'].median(),
                'foreign_ratio_20d_mean': df['foreign_ratio_20d'].mean(),
                'foreign_ratio_20d_median': df['foreign_ratio_20d'].median(),

                # 수급 지수 통계
                'supply_demand_index_mean': df['supply_demand_index'].mean(),
                'supply_demand_index_median': df['supply_demand_index'].median(),
                'supply_demand_index_std': df['supply_demand_index'].std(),

                # 매집 신호 통계
                'strong_accumulation_count': df['strong_accumulation'].sum(),
                'accumulation_signal_count': df['accumulation_signal'].sum(),
                'strong_accumulation_ratio': df['strong_accumulation'].sum() / len(df) * 100,

                # 트렌드 분포
                'inst_buying_count': len(df[df['institutional_trend'].str.contains('buying', na=False)]),
                'foreign_buying_count': len(df[df['foreign_trend'].str.contains('buying', na=False)]),

                # 고위험 종목
                'high_risk_count': len(df[df['risk_level'] == '높음']),
                'high_momentum_count': len(df[df['momentum_score'] > 50])
            }

        except Exception as e:
            logger.warning(f"⚠️ 통계 요약 생성 실패: {e}")
            return {'summary_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'error': str(e)}

def main():
    """메인 실행 함수"""
    logger.info("🚀 Enhanced 한국 주식 전체 기관/외국인 순매매 트렌드 데이터 다운로드 시작...")

    # 설정 커스터마이징 (필요시)
    config = TrendConfig(
        strong_buy_inst=2500000,    # 기관 강매수 기준을 2.5백만주로 조정
        strong_buy_foreign=4000000, # 외국인 강매수 기준을 4백만주로 조정
        high_ratio_inst=6.0,        # 기관 고비율 기준을 6%로 조정
        high_ratio_foreign=10.0     # 외국인 고비율 기준을 10%로 조정
    )

    # Enhanced 분석기 초기화
    analyzer = EnhancedKoreanInstitutionalTrendAnalyzer(config=config)

    # 전체 데이터 다운로드 (멀티스레딩 사용)
    df = analyzer.download_all_institutional_data(
        max_stocks=None,        # 전체 종목 (테스트시 50으로 설정)
        max_workers=8,          # 동시 처리 스레드 수
        save_interval=100       # 100개마다 중간 저장
    )

    if not df.empty:
        # 데이터 저장
        if analyzer.save_institutional_data(df):
            print(f"\n🎯 Enhanced 전체 기관/외국인 순매매 트렌드 데이터 다운로드 및 저장 완료!")
            print(f"📊 총 {len(df)}개 종목")
            print(f"📁 저장 위치: {analyzer.all_institutional_csv_path}")

            # Enhanced 샘플 데이터 출력
            print(f"\n📋 Enhanced 샘플 데이터:")
            sample_cols = [
                'ticker', 'institutional_net_buy_20d', 'foreign_net_buy_20d',
                'institutional_ratio_20d', 'foreign_ratio_20d',
                'supply_demand_stage', 'accumulation_intensity',
                'momentum_score', 'risk_level'
            ]
            available_cols = [col for col in sample_cols if col in df.columns]
            print(df[available_cols].head(10))

            # Enhanced 통계 정보
            print(f"\n📊 Enhanced 통계 정보:")
            print(f"   기관 20일 순매수 평균: {df['institutional_net_buy_20d'].mean():,.0f}")
            print(f"   외국인 20일 순매수 평균: {df['foreign_net_buy_20d'].mean():,.0f}")
            print(f"   기관 20일 비율 평균: {df['institutional_ratio_20d'].mean():.2f}%")
            print(f"   외국인 20일 비율 평균: {df['foreign_ratio_20d'].mean():.2f}%")
            print(f"   수급 지수 평균: {df['supply_demand_index'].mean():.1f}")
            if 'momentum_score' in df.columns:
                print(f"   모멘텀 점수 평균: {df['momentum_score'].mean():.1f}")
            if 'consistency_score' in df.columns:
                print(f"   일관성 점수 평균: {df['consistency_score'].mean():.1f}")

            # Enhanced 트렌드 분석
            print(f"\n📈 Enhanced 트렌드 분석:")
            inst_trends = df['institutional_trend'].value_counts()
            foreign_trends = df['foreign_trend'].value_counts()
            print(f"   기관 트렌드: {dict(inst_trends)}")
            print(f"   외국인 트렌드: {dict(foreign_trends)}")

            if 'risk_level' in df.columns:
                risk_levels = df['risk_level'].value_counts()
                print(f"   리스크 레벨: {dict(risk_levels)}")

            # 강한 매집 종목 (Enhanced)
            strong_accumulation = df[df['strong_accumulation'] == 1]
            if not strong_accumulation.empty:
                print(f"\n🔥 강한 매집 신호 종목 ({len(strong_accumulation)}개):")
                display_cols = [
                    'ticker', 'institutional_net_buy_20d', 'foreign_net_buy_20d',
                    'institutional_ratio_20d', 'foreign_ratio_20d',
                    'supply_demand_stage', 'accumulation_intensity'
                ]
                if 'momentum_score' in strong_accumulation.columns:
                    display_cols.append('momentum_score')
                print(strong_accumulation[display_cols])

            # 고위험 고수익 종목
            if 'risk_level' in df.columns and 'momentum_score' in df.columns:
                high_risk_high_momentum = df[
                    (df['risk_level'] == '높음') &
                    (df['momentum_score'] > 30) &
                    (df['supply_demand_index'] > 70)
                ]
                if not high_risk_high_momentum.empty:
                    print(f"\n⚡ 고위험 고모멘텀 종목 ({len(high_risk_high_momentum)}개):")
                    print(high_risk_high_momentum[['ticker', 'momentum_score', 'supply_demand_index', 'risk_level', 'trend_strength']])

            # 일관성 높은 매집 종목
            if 'consistency_score' in df.columns:
                consistent_accumulation = df[
                    (df['consistency_score'] > 70) &
                    (df['accumulation_signal'] == 1)
                ]
                if not consistent_accumulation.empty:
                    print(f"\n🎯 일관성 높은 매집 종목 ({len(consistent_accumulation)}개):")
                    print(consistent_accumulation[['ticker', 'consistency_score', 'accumulation_intensity', 'supply_demand_stage']].head())

        else:
            print(f"\n❌ Enhanced 기관 데이터 저장 실패!")
    else:
        print(f"\n❌ Enhanced 기관 데이터 다운로드 실패!")

if __name__ == "__main__":
    main()