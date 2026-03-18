from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class SetupCandidate:
    exchange: str
    symbol: str
    timeframe: str
    event_ts: int

    pivot_high: float

    c1_range_pct: float
    c2_range_pct: float
    c3_range_pct: float
    atrp_pct: float

    ema50: float
    ema200: float
    ema_sep_pct: float
    above_ema50_ratio: float

    vol_ma20: float
    liquidity_bucket: str
    market_regime: str

@dataclass
class SignalEvent:
    exchange: str
    symbol: str
    timeframe: str
    event_ts: int
    signal_type: str  # BREAKOUT/RETEST_OK

    pivot_high: float
    c1_range_pct: float
    c2_range_pct: float
    c3_range_pct: float
    atrp_pct: float
    ema_sep_pct: float
    above_ema50_ratio: float
    liquidity_bucket: str
    market_regime: str

    breakout_close_pct: float
    vol_ratio: float
    wick_ratio: float

    retest_tolerance_pct: Optional[float] = None
    retest_depth_pct: Optional[float] = None
    retest_vol_ratio: Optional[float] = None
    retest_close_above: Optional[int] = None

    score: int = 0
    ml_win_prob: Optional[float] = None
    event_id: str = ""
    dedupe_key: str = ""
    summary_text: str = ""
    tags: Optional[List[str]] = None
