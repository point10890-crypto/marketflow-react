#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KR Market Configuration
국장 분석 시스템 설정 - 외인/기관 수급 기반
"""
from dataclasses import dataclass, field
from typing import Literal, Optional, List, Tuple
from enum import Enum


class MarketRegime(Enum):
    """시장 상태"""
    KR_BULLISH = "강세장"      # KOSPI > 20MA > 60MA, 외인 순매수
    KR_NEUTRAL = "중립"        # 혼조세
    KR_BEARISH = "약세장"      # KOSPI < 20MA, 외인 순매도

class SignalType(Enum):
    """진입 시그널 유형"""
    FOREIGNER_BUY = "외인매수"     # 외국인 5일 연속 순매수
    INST_SCOOP = "기관매집"        # 기관 10일 순매수 + 거래량 급증
    DOUBLE_BUY = "쌍끌이"          # 외인 + 기관 동시 매수


@dataclass
class TrendThresholds:
    """수급 트렌드 판단 기준"""
    # 외국인 (Foreign)
    foreign_strong_buy: int = 5_000_000     # 강매수 (5백만주)
    foreign_buy: int = 2_000_000            # 매수 (2백만주)
    foreign_neutral: int = -1_000_000       # 중립
    foreign_sell: int = -2_000_000          # 매도
    foreign_strong_sell: int = -5_000_000   # 강매도
    
    # 기관 (Institutional)
    inst_strong_buy: int = 3_000_000        # 강매수 (3백만주)
    inst_buy: int = 1_000_000               # 매수 (1백만주)
    inst_neutral: int = -500_000            # 중립
    inst_sell: int = -1_000_000             # 매도
    inst_strong_sell: int = -3_000_000      # 강매도
    
    # 비율 기준
    high_ratio_foreign: float = 12.0        # 외국인 고비율
    high_ratio_inst: float = 8.0            # 기관 고비율


@dataclass 
class MarketGateConfig:
    """Market Gate 설정 - 시장 진입 조건"""
    # 환율 기준 (USD/KRW)
    usd_krw_safe: float = 1350.0            # 안전 (초록)
    usd_krw_warning: float = 1400.0         # 주의 (노랑)
    usd_krw_danger: float = 1450.0          # 위험 (빨강)
    
    # KOSPI 기준
    kospi_ma_short: int = 20                # 단기 이평
    kospi_ma_long: int = 60                 # 장기 이평
    
    # 외인 수급 기준
    foreign_net_buy_threshold: int = 500_000_000_000  # 5000억원 순매수


@dataclass
class BacktestConfig:
    """백테스트 설정"""
    # === 진입 조건 ===
    entry_trigger: Literal["FOREIGNER_BUY", "INST_SCOOP", "DOUBLE_BUY"] = "DOUBLE_BUY"
    
    # 최소 점수/등급
    min_score: int = 60                     # 최소 수급 점수 (0-100)
    min_consecutive_days: int = 3           # 최소 연속 매수일
    
    # === 청산 조건 ===
    stop_loss_pct: float = 5.0              # 손절 (%)
    take_profit_pct: float = 15.0           # 익절 (%)
    trailing_stop_pct: float = 5.0          # 트레일링 스탑 (고점 대비 %)
    max_hold_days: int = 15                 # 최대 보유 기간 (일)
    
    # RSI 기반 청산
    rsi_exit_threshold: int = 70            # RSI 70 도달 시 절반 익절
    
    # 외인 청산 조건
    exit_on_foreign_sell: bool = True       # 외인 순매도 전환 시 청산
    foreign_sell_days: int = 2              # N일 연속 순매도 시
    
    # === Market Regime ===
    allowed_regimes: List[str] = field(default_factory=lambda: ["KR_BULLISH", "KR_NEUTRAL"])
    use_usd_krw_gate: bool = True           # 환율 게이트 사용
    
    # === 자금 관리 ===
    initial_capital: float = 100_000_000    # 초기 자본 (1억원)
    position_size_pct: float = 10.0         # 포지션 크기 (자본의 %)
    max_positions: int = 10                 # 최대 동시 보유 종목
    
    # === 수수료/슬리피지 ===
    commission_pct: float = 0.015           # 거래 수수료 (0.015%)
    slippage_pct: float = 0.1               # 슬리피지 (0.1%)
    tax_pct: float = 0.23                   # 세금 (매도 시 0.23%)
    
    def get_total_cost_pct(self) -> float:
        """총 거래 비용 (왕복)"""
        return (self.commission_pct * 2) + self.slippage_pct + self.tax_pct
    
    def should_trade_in_regime(self, regime: str) -> bool:
        """해당 시장 상태에서 거래 가능 여부"""
        return regime in self.allowed_regimes
    
    @classmethod
    def conservative(cls) -> "BacktestConfig":
        """보수적 설정 - 안정적 수익 추구"""
        return cls(
            entry_trigger="DOUBLE_BUY",
            min_score=70,
            min_consecutive_days=5,
            stop_loss_pct=3.0,
            take_profit_pct=10.0,
            trailing_stop_pct=4.0,
            max_hold_days=10,
            exit_on_foreign_sell=True,
            foreign_sell_days=1,
            position_size_pct=5.0,
            max_positions=5
        )
    
    @classmethod
    def aggressive(cls) -> "BacktestConfig":
        """공격적 설정 - 고수익 추구"""
        return cls(
            entry_trigger="FOREIGNER_BUY",
            min_score=50,
            min_consecutive_days=3,
            stop_loss_pct=7.0,
            take_profit_pct=25.0,
            trailing_stop_pct=6.0,
            max_hold_days=20,
            exit_on_foreign_sell=False,
            position_size_pct=15.0,
            max_positions=15
        )


@dataclass
class ScreenerConfig:
    """스크리너 설정"""
    # 데이터 소스
    data_source: Literal["naver", "krx", "both"] = "naver"
    
    # 분석 기간
    lookback_days: int = 60                 # 분석 기간 (일)
    
    # 점수 가중치
    weight_foreign: float = 0.40            # 외국인 수급 (40%)
    weight_inst: float = 0.30               # 기관 수급 (30%)
    weight_technical: float = 0.20          # 기술적 분석 (20%)
    weight_fundamental: float = 0.10        # 펀더멘털 (10%)
    
    # Top N
    top_n: int = 20                         # 상위 N개 종목 선정
    
    # 필터
    min_market_cap: int = 100_000_000_000   # 최소 시총 (1000억)
    min_avg_volume: int = 100_000           # 최소 평균 거래량
    exclude_admin: bool = True              # 관리종목 제외
    exclude_etf: bool = True                # ETF 제외


# === 상수 정의 ===
KOSPI_TICKER = "^KS11"
KOSDAQ_TICKER = "^KQ11"
USD_KRW_TICKER = "KRW=X"

# 섹터 분류 (GICS 기준)
SECTORS = {
    "반도체": ["005930", "000660", "042700"],
    "2차전지": ["373220", "006400", "003670"],
    "자동차": ["005380", "000270", "012330"],
    "조선": ["329180", "009540", "010140"],
    "금융": ["105560", "055550", "086790"],
    "바이오": ["207940", "068270", "326030"],
    "인터넷": ["035420", "035720", "377300"],
    "에너지": ["096770", "010950", "034020"],
}


# ═══════════════════════════════════════════════════════════════════════════
# 부팅 시 런타임 설정 검증 (리뷰 2026-09-02 §3.4-7)
# ═══════════════════════════════════════════════════════════════════════════
#
# 누락된 키는 지금까지 "조용히 폴백"(LLM → 키워드, DART → 0점, 텔레그램 → 미발송)으로
# 흡수돼 며칠 뒤에야 드러났다. 부팅 시 한 번 이름만(값은 절대 로그하지 않음) 점검한다.
#   - create_app()      : 문제마다 WARNING, MARKETFLOW_STRICT_CONFIG=1 이면 기동 중단
#   - scheduler.py 데몬 : WARNING 만 (누락 키가 있어도 나머지 잡은 계속 돈다)
import os as _os


class RuntimeConfigError(RuntimeError):
    """strict 모드에서 필수 설정이 빠졌을 때. 메시지는 변수 이름만 담는다."""


def _env_present(name: str) -> bool:
    return bool((_os.getenv(name) or '').strip())


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = _os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


LLM_PROVIDER_KEYS = ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY')
TELEGRAM_REQUIRED = ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')
KIS_REQUIRED = ('KIS_APP_KEY', 'KIS_APP_SECRET')


def validate_runtime_config(strict: "bool | None" = None) -> "list[str]":
    """운영에 실제로 영향을 주는 환경변수의 존재 여부를 점검한다.

    Returns:
        사람이 읽을 수 있는 문제 목록 (비어 있으면 정상). 값은 절대 포함하지 않는다.
    Raises:
        RuntimeConfigError: strict=True (또는 strict=None 이고 MARKETFLOW_STRICT_CONFIG=1)
        이며 문제가 하나라도 있을 때.
    """
    problems: list[str] = []

    if not _env_present('SECRET_KEY'):
        problems.append('SECRET_KEY is not set — auth tokens will not survive a restart')

    if not any(_env_present(key) for key in LLM_PROVIDER_KEYS):
        problems.append(
            'no LLM provider key set (need one of DEEPSEEK_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY) '
            '— every LLM path will silently fall back to keyword/template output'
        )

    telegram_flags = sorted(
        name for name, value in _os.environ.items()
        if name.endswith('_TELEGRAM_ENABLED') and value.strip().lower() in ('1', 'true', 'yes', 'on')
    )
    if telegram_flags:
        missing = [name for name in TELEGRAM_REQUIRED if not _env_present(name)]
        if missing:
            problems.append(
                f"{' and '.join(missing)} not set while telegram is enabled via {', '.join(telegram_flags)}"
            )

    if not _env_present('DART_API_KEY'):
        problems.append('DART_API_KEY is not set — disclosure score will always be 0')

    kis_consumers = []
    if _env_truthy('MIROFISH_USE_KIS', default=True):      # live_data.py 기본값 on
        kis_consumers.append('MIROFISH_USE_KIS')
    if _env_truthy('WORKER_SCREENER_ENABLED', default=True):  # app/__init__.py 기본값 on
        kis_consumers.append('WORKER_SCREENER_ENABLED')
    if kis_consumers:
        missing = [name for name in KIS_REQUIRED if not _env_present(name)]
        if missing:
            problems.append(
                f"{' and '.join(missing)} not set while {', '.join(kis_consumers)} is on "
                '(KIS OpenAPI screener/live data will fail)'
            )

    if strict is None:
        strict = _env_truthy('MARKETFLOW_STRICT_CONFIG')
    if strict and problems:
        raise RuntimeConfigError('runtime config invalid: ' + '; '.join(problems))
    return problems
