#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KR Market - Data Models
국장 분석 시스템 데이터 모델
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from datetime import datetime


@dataclass
class StockInfo:
    """종목 기본 정보"""
    ticker: str
    name: str
    market: str                         # KOSPI / KOSDAQ
    sector: Optional[str] = None
    market_cap: Optional[int] = None    # 시가총액
    is_etf: bool = False
    is_admin: bool = False              # 관리종목


@dataclass
class InstitutionalFlow:
    """기관/외국인 수급 데이터"""
    ticker: str
    date: str
    
    # 외국인 순매매
    foreign_net_buy: int = 0            # 주수
    foreign_net_buy_amount: int = 0     # 금액 (원)
    foreign_holding_pct: float = 0.0    # 보유 비율 (%)
    
    # 기관 순매매  
    inst_net_buy: int = 0
    inst_net_buy_amount: int = 0
    
    # 개인 순매매
    retail_net_buy: int = 0
    retail_net_buy_amount: int = 0
    
    # 거래량
    volume: int = 0
    close_price: float = 0.0


@dataclass
class TrendAnalysis:
    """수급 트렌드 분석 결과"""
    ticker: str
    analysis_date: str
    
    # 기간별 외국인 순매매
    foreign_net_60d: int = 0
    foreign_net_20d: int = 0
    foreign_net_10d: int = 0
    foreign_net_5d: int = 0
    
    # 기간별 기관 순매매
    inst_net_60d: int = 0
    inst_net_20d: int = 0
    inst_net_10d: int = 0
    inst_net_5d: int = 0
    
    # 거래량 대비 비율
    foreign_ratio_20d: float = 0.0
    inst_ratio_20d: float = 0.0
    
    # 연속 매수일
    foreign_consecutive_buy_days: int = 0
    inst_consecutive_buy_days: int = 0
    
    # 트렌드 판단
    foreign_trend: str = "neutral"      # strong_buying, buying, neutral, selling, strong_selling
    inst_trend: str = "neutral"
    
    # 종합 점수 (0-100)
    supply_demand_score: float = 50.0
    supply_demand_stage: str = "중립"   # 강한매집, 매집, 약매집, 중립, 약분산, 분산, 강한분산
    
    # 매집 신호
    is_double_buy: bool = False         # 쌍끌이
    accumulation_intensity: str = "보통"
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Signal:
    """매수/매도 시그널"""
    ticker: str
    name: str
    signal_type: str                    # FOREIGNER_BUY, INST_SCOOP, DOUBLE_BUY
    signal_time: int                    # Unix timestamp
    
    # 시그널 강도
    score: int                          # 0-100
    grade: str                          # A, B, C, D
    
    # 가격 정보
    price: float
    pivot_high: Optional[float] = None  # 돌파 기준점
    
    # 수급 정보
    foreign_net_5d: int = 0
    inst_net_5d: int = 0
    consecutive_days: int = 0
    
    # 시장 상태
    market_regime: str = "KR_NEUTRAL"
    usd_krw: float = 0.0
    
    # 기술적 지표
    rsi: Optional[float] = None
    ma_alignment: Optional[str] = None  # 정배열, 역배열, 혼조
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Trade:
    """개별 거래 기록"""
    ticker: str
    name: str
    
    # 진입
    entry_time: int                     # Unix timestamp
    entry_price: float
    entry_type: str                     # FOREIGNER_BUY, INST_SCOOP, DOUBLE_BUY
    entry_score: int
    
    # 청산 (진행 중이면 None)
    exit_time: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None   # STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, TIME_EXIT, FOREIGN_SELL, RSI_EXIT
    
    # 포지션 정보
    quantity: int = 0
    position_value: float = 0.0
    stop_loss: float = 0.0
    take_profit: Optional[float] = None
    
    # 수급 정보 (진입 시점)
    foreign_net_5d: int = 0
    inst_net_5d: int = 0
    
    # 시장 상태
    market_regime: str = "KR_NEUTRAL"
    
    @property
    def is_closed(self) -> bool:
        return self.exit_price is not None
    
    @property
    def return_pct(self) -> float:
        if not self.is_closed:
            return 0.0
        return ((self.exit_price - self.entry_price) / self.entry_price) * 100
    
    @property
    def pnl(self) -> float:
        """손익 금액"""
        if not self.is_closed:
            return 0.0
        return (self.exit_price - self.entry_price) * self.quantity
    
    @property
    def r_multiple(self) -> float:
        """리스크 대비 수익 (R-Multiple)"""
        if not self.is_closed or self.stop_loss == 0:
            return 0.0
        risk = self.entry_price - self.stop_loss
        if risk <= 0:
            return 0.0
        reward = self.exit_price - self.entry_price
        return reward / risk
    
    @property
    def is_winner(self) -> bool:
        return self.return_pct > 0
    
    @property
    def holding_days(self) -> int:
        if not self.is_closed:
            return 0
        return (self.exit_time - self.entry_time) // 86400
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['is_closed'] = self.is_closed
        d['return_pct'] = self.return_pct
        d['pnl'] = self.pnl
        d['r_multiple'] = self.r_multiple
        d['is_winner'] = self.is_winner
        d['holding_days'] = self.holding_days
        return d


@dataclass
class BacktestResult:
    """백테스트 결과"""
    # 설정
    config_name: str
    start_date: str
    end_date: str
    
    # 거래 통계
    total_trades: int = 0
    winners: int = 0
    losers: int = 0
    
    # 수익률
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    avg_winner_pct: float = 0.0
    avg_loser_pct: float = 0.0
    
    # R-Multiple
    avg_r_multiple: float = 0.0
    total_r: float = 0.0
    
    # 리스크 지표
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    
    # 벤치마크 비교
    kospi_return_pct: float = 0.0
    kosdaq_return_pct: float = 0.0
    alpha: float = 0.0                  # KOSPI 대비 초과수익
    
    # 자금
    initial_capital: float = 0.0
    final_capital: float = 0.0
    
    # 기간 통계
    avg_holding_days: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    
    # 시그널별 통계
    signal_stats: Dict = field(default_factory=dict)
    
    # 상세 데이터
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[tuple] = field(default_factory=list)  # [(timestamp, equity), ...]
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['trades'] = [t.to_dict() if hasattr(t, 'to_dict') else t for t in self.trades]
        return d


@dataclass
class MarketStatus:
    """현재 시장 상태"""
    timestamp: int
    
    # 지수
    kospi: float = 0.0
    kospi_change_pct: float = 0.0
    kosdaq: float = 0.0
    kosdaq_change_pct: float = 0.0
    
    # 환율
    usd_krw: float = 0.0
    usd_krw_change_pct: float = 0.0
    
    # 외인/기관 당일 순매매 (전체)
    foreign_net_total: int = 0          # 금액 (억원)
    inst_net_total: int = 0
    retail_net_total: int = 0
    
    # 시장 상태
    regime: str = "KR_NEUTRAL"
    regime_score: float = 50.0          # 0-100 (100이면 매우 강세)
    
    # 게이트 상태
    is_gate_open: bool = True
    gate_reason: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
