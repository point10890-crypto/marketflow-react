"""
데이터 모델 정의
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Dict, List
from enum import Enum

from .config import Grade


class SignalStatus(Enum):
    """시그널 상태"""
    PENDING = "PENDING"       # 대기중
    EXECUTED = "EXECUTED"     # 체결됨
    CANCELLED = "CANCELLED"   # 취소됨
    EXPIRED = "EXPIRED"       # 만료됨


@dataclass
class StockData:
    """종목 기본 데이터"""
    code: str                          # 종목코드
    name: str                          # 종목명
    market: str                        # 시장 (KOSPI/KOSDAQ)
    sector: Optional[str] = None       # 업종
    market_cap: int = 0                # 시가총액
    
    # 당일 시세
    open: int = 0                      # 시가
    high: int = 0                      # 고가
    low: int = 0                       # 저가
    close: int = 0                     # 종가(현재가)
    prev_close: int = 0                # 전일종가
    volume: int = 0                    # 거래량
    trading_value: int = 0             # 거래대금
    
    # 등락
    change: int = 0                    # 등락금액
    change_pct: float = 0.0            # 등락률
    
    # 52주 고저
    high_52w: int = 0                  # 52주 최고가
    low_52w: int = 0                   # 52주 최저가


@dataclass
class SupplyData:
    """수급 데이터"""
    code: str
    date: date
    
    # 투자자별 순매수
    foreign_net: int = 0               # 외국인 순매수
    inst_net: int = 0                  # 기관 순매수
    retail_net: int = 0                # 개인 순매수
    
    # 세부 기관
    pension_net: int = 0               # 연기금 순매수
    invest_net: int = 0                # 투신 순매수
    insurance_net: int = 0             # 보험 순매수
    
    # 프로그램
    program_buy: int = 0               # 프로그램 매수
    program_sell: int = 0              # 프로그램 매도
    program_net: int = 0               # 프로그램 순매수
    
    # 외국인 보유
    foreign_hold_pct: float = 0.0      # 외국인 보유비율

    # 누적 순매수
    foreign_buy_5d: int = 0            # 외국인 5일 누적 순매수
    inst_buy_5d: int = 0               # 기관 5일 누적 순매수


@dataclass
class ChartData:
    """차트 데이터 (일봉)"""
    code: str
    date: date
    open: int
    high: int
    low: int
    close: int
    volume: int
    
    # 이동평균
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma120: Optional[float] = None


@dataclass
class NewsData:
    """뉴스 데이터"""
    code: str
    title: str
    source: str                        # 언론사
    published_at: datetime
    url: Optional[str] = None
    summary: str = ""                  # 본문 요약 (LLM용)
    sentiment: Optional[str] = None    # positive/negative/neutral


@dataclass
class ScoreDetail:
    """점수 상세"""
    # 필수 조건
    news: int = 0                      # 뉴스/재료 (0~3점)
    volume: int = 0                    # 거래대금 (0~3점)
    
    # 보조 조건
    chart: int = 0                     # 차트패턴 (0~2점)
    candle: int = 0                    # 캔들형태 (0~1점)
    consolidation: int = 0             # 기간조정 (0~1점)
    supply: int = 0                    # 수급 (0~2점)
    disclosure: int = 0                # 공시 (0~2점) - DART 호재공시
    analyst: int = 0                   # 애널리스트 (0~3점) - yfinance 컨센서스

    llm_reason: str = ""               # LLM 분석 결과
    llm_source: str = ""               # LLM 소스 (gemini/claude/openai/keyword_fallback)

    @property
    def total(self) -> int:
        """총점"""
        return (self.news + self.volume + self.chart +
                self.candle + self.consolidation + self.supply +
                max(0, self.disclosure) + self.analyst)
    
    @property
    def mandatory_passed(self) -> bool:
        """필수 조건 충족 여부 - 뉴스 OR 거래대금 중 하나 이상 충족"""
        return self.news >= 1 or self.volume >= 1
    
    def to_dict(self) -> Dict:
        return {
            "news": self.news,
            "volume": self.volume,
            "chart": self.chart,
            "candle": self.candle,
            "consolidation": self.consolidation,
            "supply": self.supply,
            "disclosure": self.disclosure,
            "analyst": self.analyst,
            "llm_reason": self.llm_reason,
            "llm_source": self.llm_source,
            "total": self.total,
        }


@dataclass
class ChecklistDetail:
    """체크리스트 상세"""
    # 필수 조건
    has_news: bool = False             # 뉴스/재료 있음
    news_sources: List[str] = field(default_factory=list)  # 뉴스 출처
    volume_sufficient: bool = False    # 거래대금 충족
    
    # 보조 조건
    is_new_high: bool = False          # 신고가 여부
    is_breakout: bool = False          # 돌파 여부
    ma_aligned: bool = False           # 이평선 정배열
    good_candle: bool = False          # 좋은 캔들 형태
    has_consolidation: bool = False    # 기간조정 있음
    supply_positive: bool = False      # 수급 양호
    
    # 공시 정보
    has_disclosure: bool = False       # DART 공시 있음
    disclosure_types: List[str] = field(default_factory=list)  # 공시 유형

    # 부정적 요소
    negative_news: bool = False        # 부정적 뉴스
    upper_wick_long: bool = False      # 윗꼬리 김
    volume_spike_suspicious: bool = False  # 의심스러운 거래량
    
    def to_dict(self) -> Dict:
        return {
            # 플랫 구조 (프론트엔드 직접 접근용)
            "has_news": self.has_news,
            "news_sources": self.news_sources,
            "volume_sufficient": self.volume_sufficient,
            "is_new_high": self.is_new_high,
            "is_breakout": self.is_breakout,
            "ma_aligned": self.ma_aligned,
            "good_candle": self.good_candle,
            "has_consolidation": self.has_consolidation,
            "supply_positive": self.supply_positive,
            "has_disclosure": self.has_disclosure,
            "disclosure_types": self.disclosure_types,
            "negative_news": self.negative_news,
            "upper_wick_long": self.upper_wick_long,
            "volume_suspicious": self.volume_spike_suspicious,
        }


@dataclass
class Signal:
    """매매 시그널"""
    id: Optional[int] = None
    
    # 종목 정보
    stock_code: str = ""
    stock_name: str = ""
    market: str = ""
    sector: Optional[str] = None
    
    # 시그널 정보
    signal_date: date = None
    signal_time: datetime = None
    grade: Grade = Grade.C
    
    # 점수
    score: ScoreDetail = field(default_factory=ScoreDetail)
    checklist: ChecklistDetail = field(default_factory=ChecklistDetail)
    
    # 가격 정보
    current_price: int = 0             # 현재가 (진입 예정가)
    entry_price: int = 0               # 진입가
    stop_price: int = 0                # 손절가
    target_price: int = 0              # 목표가
    
    # 포지션 정보
    r_value: float = 0.0               # R 값 (리스크 금액)
    position_size: float = 0.0         # 포지션 크기 (금액)
    quantity: int = 0                  # 수량
    r_multiplier: float = 0.0          # R 배수
    
    # 시장 데이터
    trading_value: int = 0             # 거래대금
    change_pct: float = 0.0            # 등락률
    volume_ratio: float = 0.0          # 거래량 비율 (vs 20일 평균)
    foreign_5d: int = 0                # 외국인 5일 누적 순매수
    inst_5d: int = 0                   # 기관 5일 누적 순매수
    
    # 상태
    status: SignalStatus = SignalStatus.PENDING
    created_at: datetime = None
    updated_at: datetime = None
    
    # 메모
    memo: str = ""
    
    # 관련 뉴스 (UI 표시용)
    news_items: List[Dict] = field(default_factory=list)
    
    # 테마 정보 (LLM 추출)
    themes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "market": self.market,
            "sector": self.sector,
            "signal_date": str(self.signal_date),
            "grade": self.grade.value,
            "score": self.score.to_dict(),
            "checklist": self.checklist.to_dict(),
            "current_price": self.current_price,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "quantity": self.quantity,
            "position_size": self.position_size,
            "r_value": self.r_value,
            "r_multiplier": self.r_multiplier,
            "trading_value": self.trading_value,
            "change_pct": self.change_pct,
            "volume_ratio": self.volume_ratio,
            "foreign_5d": self.foreign_5d,
            "inst_5d": self.inst_5d,
            "status": self.status.value,
            "news_items": self.news_items,
            "themes": self.themes,
        }


@dataclass
class ScreenerResult:
    """스크리너 결과"""
    date: date
    total_candidates: int              # 전체 후보
    filtered_count: int                # 필터 통과
    signals: List[Signal] = field(default_factory=list)
    
    # 통계
    by_grade: Dict[str, int] = field(default_factory=dict)
    by_market: Dict[str, int] = field(default_factory=dict)
    
    processing_time_ms: float = 0.0
