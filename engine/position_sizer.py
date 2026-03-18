"""
포지션 사이저 - R 기반 리스크 관리

핵심 공식:
R값 = 총자본 × R비율
리스크금액 = R값 × 등급배수
포지션크기 = 리스크금액 ÷ 손절률
수량 = 포지션크기 ÷ 진입가

예시 (자본 5천만원, A등급, 손절 3%):
R값 = 50,000,000 × 0.005 = 250,000원
리스크금액 = 250,000 × 1.0 = 250,000원
포지션크기 = 250,000 ÷ 0.03 = 8,333,333원
수량 = 8,333,333 ÷ 10,000 = 833주
"""

from dataclasses import dataclass
from typing import Optional
from engine.config import SignalConfig, Grade


@dataclass
class PositionResult:
    """포지션 계산 결과"""
    entry_price: int          # 진입가
    stop_price: int           # 손절가
    target_price: int         # 목표가
    quantity: int             # 수량
    position_size: float      # 포지션 크기 (금액)
    r_value: float            # R 값
    risk_amount: float        # 리스크 금액
    r_multiplier: float       # R 배수
    
    # 수익/손실 예상
    potential_profit: float   # 예상 수익
    potential_loss: float     # 예상 손실
    risk_reward_ratio: float  # 손익비
    
    # 비율
    position_pct: float       # 포지션 비율 (총자본 대비)
    
    def __str__(self) -> str:
        return f"""
포지션 계산 결과
================
진입가: {self.entry_price:,}원
손절가: {self.stop_price:,}원 (-3%)
목표가: {self.target_price:,}원 (+5%)
수량: {self.quantity:,}주
포지션 크기: {self.position_size:,.0f}원
R값: {self.r_value:,.0f}원
R배수: {self.r_multiplier}
예상 수익: +{self.potential_profit:,.0f}원
예상 손실: -{self.potential_loss:,.0f}원
손익비: 1:{self.risk_reward_ratio:.2f}
        """.strip()


class PositionSizer:
    """포지션 사이저"""
    
    def __init__(
        self,
        capital: float,
        config: SignalConfig = None
    ):
        """
        Args:
            capital: 총 자본금
            config: 설정
        """
        self.capital = capital
        self.config = config or SignalConfig()
        
        # R 값 계산
        self.r_value = capital * self.config.r_ratio
    
    def calculate(
        self,
        entry_price: int,
        grade: Grade,
        available_cash: Optional[float] = None,
    ) -> PositionResult:
        """
        포지션 크기 계산
        
        Args:
            entry_price: 진입가
            grade: 등급 (S/A/B/C)
            available_cash: 가용 현금 (없으면 전체 자본 사용)
        
        Returns:
            PositionResult
        """
        # 등급별 R 배수
        grade_config = self.config.grade_configs[grade]
        r_multiplier = grade_config.r_multiplier
        
        # C등급은 매매 안함
        if r_multiplier == 0:
            return PositionResult(
                entry_price=entry_price,
                stop_price=int(entry_price * (1 - self.config.stop_loss_pct)),
                target_price=int(entry_price * (1 + self.config.take_profit_pct)),
                quantity=0,
                position_size=0,
                r_value=self.r_value,
                risk_amount=0,
                r_multiplier=0,
                potential_profit=0,
                potential_loss=0,
                risk_reward_ratio=0,
                position_pct=0,
            )
        
        # 리스크 금액 = R값 × 등급배수
        risk_amount = self.r_value * r_multiplier
        
        # 손절가
        stop_price = int(entry_price * (1 - self.config.stop_loss_pct))
        
        # 목표가
        target_price = int(entry_price * (1 + self.config.take_profit_pct))
        
        # 포지션 크기 = 리스크금액 ÷ 손절률
        position_size = risk_amount / self.config.stop_loss_pct
        
        # 가용 현금 제한
        if available_cash is not None:
            position_size = min(position_size, available_cash)
        
        # 최대 포지션 비율 제한 (자본의 50%)
        max_position = self.capital * 0.5
        position_size = min(position_size, max_position)
        
        # 수량 계산 (정수)
        quantity = int(position_size / entry_price)
        
        # 실제 포지션 크기 재계산
        actual_position_size = quantity * entry_price
        
        # 예상 수익/손실
        potential_profit = quantity * (target_price - entry_price)
        potential_loss = quantity * (entry_price - stop_price)
        
        # 손익비
        risk_reward_ratio = (self.config.take_profit_pct / self.config.stop_loss_pct) if self.config.stop_loss_pct > 0 else 0
        
        # 포지션 비율
        position_pct = (actual_position_size / self.capital) * 100 if self.capital > 0 else 0
        
        return PositionResult(
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            quantity=quantity,
            position_size=actual_position_size,
            r_value=self.r_value,
            risk_amount=risk_amount,
            r_multiplier=r_multiplier,
            potential_profit=potential_profit,
            potential_loss=potential_loss,
            risk_reward_ratio=risk_reward_ratio,
            position_pct=position_pct,
        )
    
    def get_grade_info(self, grade: Grade) -> dict:
        """등급 정보 조회"""
        config = self.config.grade_configs[grade]
        return {
            "grade": grade.value,
            "r_multiplier": config.r_multiplier,
            "risk_amount": self.r_value * config.r_multiplier,
            "min_trading_value": config.min_trading_value,
            "min_score": config.min_score,
        }
    
    def check_daily_limit(self, today_loss: float) -> bool:
        """일일 손실 한도 체크"""
        limit = self.r_value * self.config.daily_loss_limit_r
        return abs(today_loss) < limit
    
    def check_weekly_limit(self, weekly_loss: float) -> bool:
        """주간 손실 한도 체크"""
        limit = self.r_value * self.config.weekly_loss_limit_r
        return abs(weekly_loss) < limit
    
    def calculate_kelly(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """
        켈리 공식으로 최적 베팅 비율 계산
        
        Kelly % = W - [(1-W) / R]
        W = 승률
        R = 평균수익 / 평균손실
        
        Args:
            win_rate: 승률 (0~1)
            avg_win: 평균 수익률
            avg_loss: 평균 손실률 (양수)
        
        Returns:
            최적 베팅 비율 (0~1)
        """
        if avg_loss == 0:
            return 0
        
        r = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / r)
        
        # 켈리의 반 (보수적)
        half_kelly = kelly / 2
        
        # 0~1 범위로 제한
        return max(0, min(1, half_kelly))
