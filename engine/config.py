"""
종가베팅 시그널 생성기 설정
"""

from dataclasses import dataclass, field
from typing import Dict, List
from enum import Enum


class Grade(Enum):
    """종목 등급"""
    S = "S"  # 최고 - 풀배팅
    A = "A"  # 우수 - 기본배팅
    B = "B"  # 보통 - 절반배팅
    C = "C"  # 미달 - 매매안함


@dataclass
class GradeConfig:
    """등급별 설정"""
    min_trading_value: int      # 최소 거래대금 (원)
    min_change_pct: float       # 최소 등락률 (%)
    max_change_pct: float       # 최대 등락률 (%)
    min_score: int              # 최소 점수
    r_multiplier: float         # R 배수


@dataclass
class SignalConfig:
    """시그널 생성기 설정"""
    
    # === 기본 필터 ===
    min_trading_value: int = 500_000_000          # 최소 거래대금: 5억
    min_change_pct: float = 3.0                   # 최소 등락률: 3%
    max_change_pct: float = 29.9                  # 최대 등락률: 29.9% (상한가 제외)
    min_price: int = 1000                         # 최소 주가: 1,000원
    max_price: int = 500000                       # 최대 주가: 50만원
    
    # === 제외 조건 ===
    exclude_etf: bool = True                      # ETF 제외
    exclude_etn: bool = True                      # ETN 제외
    exclude_spac: bool = True                     # 스팩 제외
    exclude_preferred: bool = True                # 우선주 제외
    exclude_reits: bool = True                    # 리츠 제외
    exclude_keywords: List[str] = field(default_factory=lambda: [
        "스팩", "SPAC", "ETF", "ETN", "리츠", "우B", "우C", 
        "1우", "2우", "3우", "인버스", "레버리지"
    ])
    
    # === 점수 가중치 ===
    score_weights: Dict[str, int] = field(default_factory=lambda: {
        "news": 3,           # 뉴스/재료 (필수)
        "volume": 3,         # 거래대금 (필수)
        "chart": 2,          # 차트패턴
        "candle": 1,         # 캔들형태
        "consolidation": 1,  # 기간조정
        "supply": 2,         # 수급
        "disclosure": 2,     # DART 호재공시
        "analyst": 3,        # 애널리스트 컨센서스 (yfinance)
    })
    
    # === 등급별 기준 ===
    grade_configs: Dict[Grade, GradeConfig] = field(default_factory=lambda: {
        Grade.S: GradeConfig(
            min_trading_value=50_000_000_000,     # 500억
            min_change_pct=8.0,
            max_change_pct=20.0,
            min_score=9,
            r_multiplier=1.5,
        ),
        Grade.A: GradeConfig(
            min_trading_value=10_000_000_000,     # 100억
            min_change_pct=5.0,
            max_change_pct=15.0,
            min_score=7,
            r_multiplier=1.0,
        ),
        Grade.B: GradeConfig(
            min_trading_value=2_000_000_000,      # 20억
            min_change_pct=3.0,
            max_change_pct=12.0,
            min_score=5,
            r_multiplier=0.5,
        ),
        Grade.C: GradeConfig(
            min_trading_value=500_000_000,        # 5억
            min_change_pct=3.0,
            max_change_pct=29.9,
            min_score=0,
            r_multiplier=0.0,  # 매매 안함
        ),
    })
    
    # === 매매 설정 ===
    stop_loss_pct: float = 0.03       # 손절: -3%
    take_profit_pct: float = 0.05     # 익절: +5%
    gap_target_pct: float = 0.03      # 갭상승 익절: +3%
    gap_stop_pct: float = -0.02       # 갭하락 손절: -2%
    time_stop_hour: int = 10          # 시간손절: 10시
    
    # === 리스크 관리 ===
    r_ratio: float = 0.005            # R 비율: 0.5%
    max_positions: int = 100           # 최대 동시 보유 (제한 없음)
    daily_loss_limit_r: float = 2.0   # 일일 손실 한도: 2R
    weekly_loss_limit_r: float = 4.0  # 주간 손실 한도: 4R
    
    # === 뉴스 키워드 ===
    positive_keywords: List[str] = field(default_factory=lambda: [
        # 실적 관련
        "흑자전환", "실적개선", "어닝서프라이즈", "사상최대", "호실적",
        "매출증가", "영업이익", "순이익", "분기최대",
        # 계약/수주
        "수주", "계약체결", "공급계약", "납품계약", "MOU", "LOI",
        "대규모계약", "독점계약", "장기공급",
        # 신사업/기술
        "신약개발", "임상성공", "FDA승인", "CE인증", "특허취득",
        "기술이전", "라이선스", "신제품", "양산", "상용화",
        # 투자/M&A
        "지분투자", "인수합병", "자회사편입", "지분확대",
        # 정책/테마
        "정부지원", "국책사업", "수혜주", "관련주", "테마",
        # 수급
        "외국인매수", "기관매수", "프로그램매수",
    ])
    
    negative_keywords: List[str] = field(default_factory=lambda: [
        # 부정적 이슈
        "횡령", "배임", "분식", "상장폐지", "관리종목", "감사의견거절",
        "자본잠식", "부도", "파산", "워크아웃", "법정관리",
        "검찰", "수사", "구속", "기소",
        # 실적 악화
        "적자전환", "적자확대", "실적악화", "매출감소",
        # 수급 악화
        "대량매도", "공매도급증", "외국인매도",
    ])
    
    # 인스턴스 메서드로 기본값 접근 지원
    @classmethod
    def default(cls):
        return cls()
