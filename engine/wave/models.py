"""
Wave Pattern 데이터 모델
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum


class PatternClass(str, Enum):
    M = "M"   # Double-top variants (bearish)
    W = "W"   # Double-bottom variants (bullish)


class SignalType(str, Enum):
    CONFIRMATION = "CONFIRMATION"  # 넥라인 돌파 확인형
    PREEMPTIVE = "PREEMPTIVE"      # P5 형성 선취매형


class WaveType(str, Enum):
    """32가지 M&W 파동 분류"""
    # W (Double-bottom) variants — bullish
    W_SYMMETRIC = "W_SYMMETRIC"
    W_RIGHT_HIGHER = "W_RIGHT_HIGHER"
    W_LEFT_HIGHER = "W_LEFT_HIGHER"
    W_ASCENDING_NECKLINE = "W_ASCENDING_NECKLINE"
    W_DESCENDING_NECKLINE = "W_DESCENDING_NECKLINE"
    W_FLAT_NECKLINE = "W_FLAT_NECKLINE"
    W_WIDE = "W_WIDE"
    W_NARROW = "W_NARROW"
    W_ADAM_ADAM = "W_ADAM_ADAM"           # 뾰족-뾰족
    W_ADAM_EVE = "W_ADAM_EVE"            # 뾰족-둥근
    W_EVE_ADAM = "W_EVE_ADAM"            # 둥근-뾰족
    W_EVE_EVE = "W_EVE_EVE"             # 둥근-둥근
    W_COMPLEX = "W_COMPLEX"              # 3+ 저점
    INV_HEAD_SHOULDERS = "INV_HEAD_SHOULDERS"  # 역헤드앤숄더
    W_TRIPLE_BOTTOM = "W_TRIPLE_BOTTOM"
    W_ROUNDING = "W_ROUNDING"            # 원형 바닥

    # M (Double-top) variants — bearish
    M_SYMMETRIC = "M_SYMMETRIC"
    M_RIGHT_HIGHER = "M_RIGHT_HIGHER"
    M_LEFT_HIGHER = "M_LEFT_HIGHER"
    M_ASCENDING_NECKLINE = "M_ASCENDING_NECKLINE"
    M_DESCENDING_NECKLINE = "M_DESCENDING_NECKLINE"
    M_FLAT_NECKLINE = "M_FLAT_NECKLINE"
    M_WIDE = "M_WIDE"
    M_NARROW = "M_NARROW"
    M_ADAM_ADAM = "M_ADAM_ADAM"
    M_ADAM_EVE = "M_ADAM_EVE"
    M_EVE_ADAM = "M_EVE_ADAM"
    M_EVE_EVE = "M_EVE_EVE"
    M_COMPLEX = "M_COMPLEX"
    HEAD_SHOULDERS = "HEAD_SHOULDERS"     # 헤드앤숄더
    M_TRIPLE_TOP = "M_TRIPLE_TOP"
    M_ROUNDING = "M_ROUNDING"             # 원형 천장


# 파동 타입별 메타데이터
WAVE_META: Dict[str, Dict] = {
    # W variants (bullish)
    WaveType.W_SYMMETRIC:           {"bias":  0.7, "reliability": 75, "label": "대칭 쌍바닥"},
    WaveType.W_RIGHT_HIGHER:        {"bias":  0.8, "reliability": 80, "label": "우상향 쌍바닥"},
    WaveType.W_LEFT_HIGHER:         {"bias":  0.5, "reliability": 60, "label": "좌고 쌍바닥"},
    WaveType.W_ASCENDING_NECKLINE:  {"bias":  0.8, "reliability": 78, "label": "상승 넥라인 W"},
    WaveType.W_DESCENDING_NECKLINE: {"bias":  0.4, "reliability": 55, "label": "하강 넥라인 W"},
    WaveType.W_FLAT_NECKLINE:       {"bias":  0.7, "reliability": 72, "label": "수평 넥라인 W"},
    WaveType.W_WIDE:                {"bias":  0.6, "reliability": 65, "label": "넓은 W"},
    WaveType.W_NARROW:              {"bias":  0.7, "reliability": 70, "label": "좁은 W"},
    WaveType.W_ADAM_ADAM:           {"bias":  0.7, "reliability": 72, "label": "뾰족-뾰족 W"},
    WaveType.W_ADAM_EVE:            {"bias":  0.8, "reliability": 82, "label": "뾰족-둥근 W"},
    WaveType.W_EVE_ADAM:            {"bias":  0.6, "reliability": 65, "label": "둥근-뾰족 W"},
    WaveType.W_EVE_EVE:             {"bias":  0.7, "reliability": 74, "label": "둥근-둥근 W"},
    WaveType.W_COMPLEX:             {"bias":  0.5, "reliability": 58, "label": "복합 W"},
    WaveType.INV_HEAD_SHOULDERS:    {"bias":  0.9, "reliability": 85, "label": "역헤드앤숄더"},
    WaveType.W_TRIPLE_BOTTOM:       {"bias":  0.8, "reliability": 80, "label": "삼중 바닥"},
    WaveType.W_ROUNDING:            {"bias":  0.6, "reliability": 68, "label": "원형 바닥"},

    # M variants (bearish)
    WaveType.M_SYMMETRIC:           {"bias": -0.7, "reliability": 75, "label": "대칭 쌍봉"},
    WaveType.M_RIGHT_HIGHER:        {"bias": -0.5, "reliability": 60, "label": "우상향 쌍봉"},
    WaveType.M_LEFT_HIGHER:         {"bias": -0.8, "reliability": 80, "label": "좌고 쌍봉"},
    WaveType.M_ASCENDING_NECKLINE:  {"bias": -0.4, "reliability": 55, "label": "상승 넥라인 M"},
    WaveType.M_DESCENDING_NECKLINE: {"bias": -0.8, "reliability": 78, "label": "하강 넥라인 M"},
    WaveType.M_FLAT_NECKLINE:       {"bias": -0.7, "reliability": 72, "label": "수평 넥라인 M"},
    WaveType.M_WIDE:                {"bias": -0.6, "reliability": 65, "label": "넓은 M"},
    WaveType.M_NARROW:              {"bias": -0.7, "reliability": 70, "label": "좁은 M"},
    WaveType.M_ADAM_ADAM:           {"bias": -0.7, "reliability": 72, "label": "뾰족-뾰족 M"},
    WaveType.M_ADAM_EVE:            {"bias": -0.8, "reliability": 82, "label": "뾰족-둥근 M"},
    WaveType.M_EVE_ADAM:            {"bias": -0.6, "reliability": 65, "label": "둥근-뾰족 M"},
    WaveType.M_EVE_EVE:             {"bias": -0.7, "reliability": 74, "label": "둥근-둥근 M"},
    WaveType.M_COMPLEX:             {"bias": -0.5, "reliability": 58, "label": "복합 M"},
    WaveType.HEAD_SHOULDERS:        {"bias": -0.9, "reliability": 85, "label": "헤드앤숄더"},
    WaveType.M_TRIPLE_TOP:          {"bias": -0.8, "reliability": 80, "label": "삼중 천장"},
    WaveType.M_ROUNDING:            {"bias": -0.6, "reliability": 68, "label": "원형 천장"},
}


@dataclass
class TurningPoint:
    """ZigZag 전환점"""
    index: int
    date: str
    price: float
    point_type: str   # 'HIGH' or 'LOW'

    def to_dict(self) -> dict:
        return {"index": self.index, "date": self.date, "price": self.price, "type": self.point_type}


@dataclass
class FivePointPattern:
    """5점 기반 M&W 패턴"""
    points: List[TurningPoint]
    pattern_class: str       # 'M' or 'W'
    wave_type: str           # WaveType value
    neckline_price: float
    confidence: float = 0.0        # 0-100
    completion_pct: float = 0.0    # 0-100
    neckline_distance_pct: float = 0.0
    bullish_bias: float = 0.0      # -1.0 ~ 1.0
    volume_confirmed: bool = False

    def to_dict(self) -> dict:
        meta = WAVE_META.get(self.wave_type, {})
        return {
            "points": [p.to_dict() for p in self.points],
            "pattern_class": self.pattern_class,
            "wave_type": self.wave_type,
            "wave_label": meta.get("label", self.wave_type),
            "neckline_price": round(self.neckline_price, 2),
            "confidence": round(self.confidence, 1),
            "completion_pct": round(self.completion_pct, 1),
            "neckline_distance_pct": round(self.neckline_distance_pct, 2),
            "bullish_bias": self.bullish_bias,
            "volume_confirmed": self.volume_confirmed,
        }


@dataclass
class WaveSignal:
    """패턴 기반 매매 시그널"""
    ticker: str
    market: str
    pattern: FivePointPattern
    signal_type: str         # CONFIRMATION or PREEMPTIVE
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    score: int = 0           # 0-100
    detected_at: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "market": self.market,
            "pattern": self.pattern.to_dict(),
            "signal_type": self.signal_type,
            "entry_price": round(self.entry_price, 2),
            "stop_price": round(self.stop_price, 2),
            "target_price": round(self.target_price, 2),
            "score": self.score,
            "detected_at": self.detected_at,
        }


@dataclass
class WaveDetectResult:
    """단일 종목 패턴 감지 결과"""
    ticker: str
    market: str
    patterns: List[FivePointPattern] = field(default_factory=list)
    chart_data: list = field(default_factory=list)   # OHLCV dicts
    turning_points: List[TurningPoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "market": self.market,
            "patterns": [p.to_dict() for p in self.patterns],
            "chart_data": self.chart_data,
            "turning_points": [tp.to_dict() for tp in self.turning_points],
            "pattern_count": len(self.patterns),
        }
