"""
점수 계산기 - 종가베팅 핵심 로직

점수 체계:
- 뉴스/재료: 0~3점 (필수)
- 거래대금: 0~3점 (필수)
- 차트패턴: 0~2점
- 캔들형태: 0~1점
- 기간조정: 0~1점
- 수급: 0~2점
- 공시: 0~2점
- 애널리스트: 0~3점
- 총점: 17점 만점
"""

from typing import List, Optional, Tuple
from datetime import date, timedelta

from engine.models import (
    StockData, SupplyData, ChartData, NewsData,
    ScoreDetail, ChecklistDetail
)
from engine.config import SignalConfig, Grade


class Scorer:
    """점수 계산기"""
    
    def __init__(self, config: SignalConfig = None):
        self.config = config or SignalConfig()
    
    def calculate(
        self,
        stock: StockData,
        charts: List[ChartData],
        news_list: List[NewsData],
        supply: Optional[SupplyData],
        llm_result: Optional[dict] = None,
        dart_result: Optional[dict] = None,
        analyst_result: Optional[dict] = None,
    ) -> Tuple[ScoreDetail, ChecklistDetail]:
        """
        전체 점수 계산
        """
        score = ScoreDetail()
        checklist = ChecklistDetail()
        
        # 1. 뉴스/재료 점수 (0~3점) - LLM 반영
        news_score, news_check = self._score_news(news_list, llm_result)
        score.news = news_score
        # LLM 결과가 있으면 이유 및 소스 저장
        if llm_result:
            score.llm_reason = llm_result.get("reason", "")
            score.llm_source = llm_result.get("source", "")
            
        checklist.has_news = news_check["has_news"]
        checklist.news_sources = news_check["sources"]
        checklist.negative_news = news_check["negative"]
        
        # 2. 거래대금 점수 (0~3점)
        volume_score, volume_check = self._score_volume(stock)
        score.volume = volume_score
        checklist.volume_sufficient = volume_check
        
        # 3. 차트패턴 점수 (0~2점)
        chart_score, chart_check = self._score_chart(stock, charts)
        score.chart = chart_score
        checklist.is_new_high = chart_check["new_high"]
        checklist.is_breakout = chart_check["breakout"]
        checklist.ma_aligned = chart_check["ma_aligned"]
        
        # 4. 캔들형태 점수 (0~1점)
        candle_score, candle_check = self._score_candle(stock, charts)
        score.candle = candle_score
        checklist.good_candle = candle_check["good"]
        checklist.upper_wick_long = candle_check["upper_wick_long"]
        
        # 5. 기간조정 점수 (0~1점)
        consolidation_score, consolidation_check = self._score_consolidation(charts)
        score.consolidation = consolidation_score
        checklist.has_consolidation = consolidation_check
        
        # 6. 수급 점수 (0~2점)
        supply_score, supply_check = self._score_supply(supply)
        score.supply = supply_score
        checklist.supply_positive = supply_check

        # 7. 공시 점수 (0~2점) — DART 호재공시
        disclosure_score, disclosure_check = self._score_disclosure(dart_result)
        score.disclosure = disclosure_score
        checklist.has_disclosure = disclosure_check["has_disclosure"]
        checklist.disclosure_types = disclosure_check.get("types", [])

        # 악재 공시 시 뉴스 점수도 0으로 초기화
        if disclosure_check.get("negative"):
            score.news = 0
            checklist.negative_news = True

        # 8. 애널리스트 컨센서스 점수 (0~3점)
        analyst_score = self._score_analyst(analyst_result)
        score.analyst = analyst_score

        return score, checklist
    
    def _score_news(self, news_list: List[NewsData], llm_result: Optional[dict] = None) -> Tuple[int, dict]:
        """
        뉴스/재료 점수 계산 (LLM or 키워드)
        """
        check = {
            "has_news": False,
            "sources": [],
            "negative": False,
            "positive_count": 0,
            "major_count": 0,
        }
        
        if not news_list:
            return 0, check
            
        check["has_news"] = True
        
        # LLM 결과가 있으면 우선 사용
        if llm_result:
            llm_score = llm_result.get("score", 0)
            # LLM 점수: 3->3, 2->2, 1->1, 0->0
            # v2 기준: 확실한 호재 3점, 긍정 2점
            final_score = llm_score

            # 뉴스 소스 수집
            sources = list(set([n.source for n in news_list]))
            check["sources"] = sources

            # LLM 0점이어도 뉴스가 2개 이상 있으면 최소 1점 부여 (관심도)
            if final_score == 0 and len(news_list) >= 2:
                final_score = 1

            return final_score, check

        # 기존 키워드 로직 (백업)
        
        # 주요 언론사 목록
        MAJOR_SOURCES = [
            "연합뉴스", "한국경제", "매일경제", "머니투데이", "이데일리",
            "서울경제", "아시아경제", "파이낸셜뉴스", "헤럴드경제", "조선비즈",
        ]
        
        major_sources = []
        positive_count = 0
        negative_count = 0
        
        for news in news_list:
            # 주요 언론사 체크
            is_major = any(m in news.source for m in MAJOR_SOURCES)
            if is_major:
                major_sources.append(news.source)
            
            # 감성 체크
            if news.sentiment == "positive":
                positive_count += 1
            elif news.sentiment == "negative":
                negative_count += 1
        
        check["sources"] = list(set(major_sources))
        check["major_count"] = len(check["sources"])
        check["positive_count"] = positive_count
        check["negative"] = negative_count > 0
        
        # 부정적 뉴스 있으면 0점
        if negative_count > 0:
            return 0, check
        
        # 점수 계산
        if len(check["sources"]) >= 2 and positive_count >= 1:
            return 3, check
        elif len(check["sources"]) >= 1 and positive_count >= 1:
            return 2, check
        elif len(news_list) > 0:
            return 1, check
        
        return 0, check
    
    def _score_volume(self, stock: StockData) -> Tuple[int, bool]:
        """
        거래대금 점수 계산

        기준:
        - 3점: 500억 이상
        - 2점: 100억 이상
        - 1점: 20억 이상
        - 0점: 5억 미만
        """
        tv = stock.trading_value

        if tv >= 50_000_000_000:       # 500억
            return 3, True
        elif tv >= 10_000_000_000:      # 100억
            return 2, True
        elif tv >= 2_000_000_000:       # 20억
            return 1, True
        elif tv >= 500_000_000:         # 5억
            return 1, True

        return 0, False
    
    def _score_chart(
        self,
        stock: StockData,
        charts: List[ChartData]
    ) -> Tuple[int, dict]:
        """
        차트 패턴 점수 계산
        
        기준:
        - 2점: 신고가 돌파 + 이평선 정배열
        - 1점: 신고가 근접 또는 이평선 정배열
        - 0점: 해당 없음
        """
        check = {
            "new_high": False,
            "breakout": False,
            "ma_aligned": False,
        }
        
        if len(charts) < 20:
            return 0, check
        
        current = stock.close
        latest_chart = charts[-1] if charts else None
        
        # 1. 52주 신고가 체크
        if stock.high_52w > 0:
            # 현재가가 52주 고가의 95% 이상이면 신고가 근접
            if current >= stock.high_52w * 0.95:
                check["new_high"] = True
            # 52주 고가 돌파
            if current > stock.high_52w:
                check["breakout"] = True
        
        # 또는 최근 60일 고가 돌파
        if len(charts) >= 60:
            high_60d = max(c.high for c in charts[-60:])
            if current > high_60d:
                check["breakout"] = True
        
        # 2. 이평선 정배열 체크
        if latest_chart and all([
            latest_chart.ma5,
            latest_chart.ma10,
            latest_chart.ma20,
        ]):
            # 정배열: 현재가 > 5일 > 10일 > 20일
            if (current > latest_chart.ma5 > 
                latest_chart.ma10 > latest_chart.ma20):
                check["ma_aligned"] = True
        
        # 점수 계산
        score = 0
        if check["new_high"] or check["breakout"]:
            score += 1
        if check["ma_aligned"]:
            score += 1
        
        return min(score, 2), check
    
    def _score_candle(
        self,
        stock: StockData,
        charts: List[ChartData]
    ) -> Tuple[int, dict]:
        """
        캔들 형태 점수 계산
        
        좋은 캔들:
        - 장대양봉 (몸통 비율 70% 이상)
        - 윗꼬리 짧음 (몸통 대비 30% 이하)
        - 아랫꼬리 적당 (지지 확인)
        """
        check = {
            "good": False,
            "upper_wick_long": False,
            "body_ratio": 0.0,
        }
        
        o, h, l, c = stock.open, stock.high, stock.low, stock.close
        
        if o == 0 or h == l:  # 데이터 없음
            return 0, check
        
        # 양봉인지 확인
        if c <= o:
            return 0, check
        
        # 몸통 크기
        body = c - o
        total_range = h - l
        
        if total_range == 0:
            return 0, check
        
        body_ratio = body / total_range
        check["body_ratio"] = body_ratio
        
        # 윗꼬리 길이
        upper_wick = h - c
        upper_wick_ratio = upper_wick / body if body > 0 else 999
        
        # 아랫꼬리 길이
        lower_wick = o - l
        lower_wick_ratio = lower_wick / body if body > 0 else 0
        
        # 윗꼬리가 너무 길면 좋지 않음
        if upper_wick_ratio > 0.5:  # 몸통의 50% 이상
            check["upper_wick_long"] = True
        
        # 좋은 캔들 조건
        # 1. 몸통 비율 60% 이상
        # 2. 윗꼬리 짧음 (몸통 대비 30% 이하)
        if body_ratio >= 0.6 and upper_wick_ratio <= 0.3:
            check["good"] = True
            return 1, check
        
        # 보통 캔들: 몸통 50% 이상, 윗꼬리 50% 이하
        if body_ratio >= 0.5 and upper_wick_ratio <= 0.5:
            check["good"] = True
            return 1, check
        
        return 0, check
    
    def _score_consolidation(self, charts: List[ChartData]) -> Tuple[int, bool]:
        """
        기간 조정 점수 계산
        
        기준:
        - 최근 5~20일간 횡보 후 돌파
        - 변동성 축소 (볼린저 밴드 수축)
        """
        if len(charts) < 20:
            return 0, False
        
        recent_20 = charts[-20:]
        recent_5 = charts[-5:]
        
        # 최근 20일 가격 범위
        high_20 = max(c.high for c in recent_20)
        low_20 = min(c.low for c in recent_20)
        range_20 = (high_20 - low_20) / low_20 if low_20 > 0 else 999
        
        # 최근 5일 가격 범위
        high_5 = max(c.high for c in recent_5)
        low_5 = min(c.low for c in recent_5)
        range_5 = (high_5 - low_5) / low_5 if low_5 > 0 else 999
        
        # 변동성 축소 확인: 최근 5일 범위가 20일 범위의 50% 이하
        volatility_contracted = range_5 < range_20 * 0.5
        
        # 횡보 확인: 20일 범위가 15% 이내
        sideways = range_20 <= 0.15
        
        # 돌파 확인: 오늘 종가가 20일 고가 돌파
        current = charts[-1].close
        breakout = current > high_20
        
        # 기간조정 후 돌파
        if (sideways or volatility_contracted) and breakout:
            return 1, True
        
        return 0, False
    
    def _score_supply(self, supply: Optional[SupplyData]) -> Tuple[int, bool]:
        """
        수급 점수 계산 (최근 5일 누적 기준)
        
        기준:
        - 2점: 외인 + 기관 동시 순매수 (5일 누적)
        - 1점: 외인 또는 기관 순매수 (5일 누적)
        - 0점: 둘 다 순매도
        """
        if not supply:
            return 0, False
        
        foreign_buy = supply.foreign_buy_5d > 0
        inst_buy = supply.inst_buy_5d > 0
        
        if foreign_buy and inst_buy:
            return 2, True
        elif foreign_buy or inst_buy:
            return 1, True
        
        return 0, False

    def _score_disclosure(self, dart_result: Optional[dict]) -> Tuple[int, dict]:
        """
        DART 호재공시 점수 계산

        기준:
        - 2점: 강한 호재 (자사주취득, 무상증자, 대규모수주)
        - 1점: 보통 호재 (배당, 합병, 영업양수도)
        - 0점: 공시 없음
        - -2점: 악재 (감자, 부도, 상장폐지) → 뉴스 점수도 리셋
        """
        check = {
            "has_disclosure": False,
            "types": [],
            "negative": False,
        }

        if not dart_result or not dart_result.get("has_disclosure"):
            return 0, check

        check["has_disclosure"] = True
        check["types"] = dart_result.get("types", [])

        score = dart_result.get("score", 0)

        if dart_result.get("negative"):
            check["negative"] = True
            return -2, check

        # score는 DARTCollector가 이미 계산 (0, 1, 2)
        return max(0, min(2, score)), check

    def _score_analyst(self, analyst_result: Optional[dict]) -> int:
        """
        애널리스트 컨센서스 점수 계산 (yfinance 기반)

        analyst_result 구조:
          {"consensus_score": float, "result": str, "analyst_count": int}

        점수 기준:
        - 3점: 적극매수 (consensus_score >= 4.3)
        - 2점: 매수 (consensus_score >= 3.7)
        - 1점: 중립 (consensus_score >= 2.7)
        - 0점: 매도/적극매도 또는 데이터 없음
        """
        if not analyst_result:
            return 0

        consensus = analyst_result.get("consensus_score", 0)
        analyst_count = analyst_result.get("analyst_count", 0)

        # 애널리스트 수가 너무 적으면 신뢰도 낮음
        if analyst_count < 3:
            return 0

        if consensus >= 4.3:
            return 3  # 적극매수
        elif consensus >= 3.7:
            return 2  # 매수
        elif consensus >= 2.7:
            return 1  # 중립
        else:
            return 0  # 매도/적극매도

    def determine_grade(
        self,
        stock: StockData,
        score: ScoreDetail
    ) -> Grade:
        """
        등급 결정
        
        기준:
        - S급: 점수 10점+ & 거래대금 1조+
        - A급: 점수 8점+ & 거래대금 5천억+
        - B급: 점수 6점+ & 거래대금 1천억+
        - C급: 그 외
        """
        total = score.total
        tv = stock.trading_value
        
        # 필수 조건 미충족시 C등급
        if not score.mandatory_passed:
            return Grade.C
        
        # S급
        s_config = self.config.grade_configs[Grade.S]
        if total >= s_config.min_score and tv >= s_config.min_trading_value:
            if s_config.min_change_pct <= stock.change_pct <= s_config.max_change_pct:
                return Grade.S
        
        # A급
        a_config = self.config.grade_configs[Grade.A]
        if total >= a_config.min_score and tv >= a_config.min_trading_value:
            if a_config.min_change_pct <= stock.change_pct <= a_config.max_change_pct:
                return Grade.A
        
        # B급
        b_config = self.config.grade_configs[Grade.B]
        if total >= b_config.min_score and tv >= b_config.min_trading_value:
            return Grade.B
        
        return Grade.C
