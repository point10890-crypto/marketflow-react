# PART2: 설정 파일 (config.py)

## `crypto_market/config.py`

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TimeframeCfg:
    timeframe: str
    limit: int
    swing_k: int
    max_swings_lookback: int

    # VCP tightness
    min_r12: float
    min_r23: float
    require_descending_highs: bool
    require_ascending_lows: bool

    # scoring bounds
    c3_lo: float
    c3_hi: float
    atrp_lo: float
    atrp_hi: float
    sep_lo: float
    sep_hi: float

    # breakout/retest
    breakout_min_pct: float
    breakout_max_pct: float
    min_vol_ratio: float
    max_wick_ratio: float
    retest_tol_pct: float
    max_bars_after_breakout: int


@dataclass(frozen=True)
class ScannerCfg:
    exchange: str = "binance"
    quote: str = "USDT"

    universe_top_n: int = 200
    min_quote_volume_usdt: float = 5_000_000.0

    # publish gates
    min_score_4h: int = 40
    min_score_1d: int = 35
    allow_liquidity: tuple[str, ...] = ("A", "B", "C")
    liquidity_exception_score: int = 60
    cooldown_hours_breakout: int = 12
    cooldown_hours_retest: int = 24
    per_symbol_per_day_limit: int = 5

    tf_4h: TimeframeCfg = TimeframeCfg(
        timeframe="4h",
        limit=600,
        swing_k=3,
        max_swings_lookback=220,
        min_r12=1.25,
        min_r23=1.20,
        require_descending_highs=True,
        require_ascending_lows=True,
        c3_lo=2.0, c3_hi=15.0,
        atrp_lo=0.5, atrp_hi=6.0,
        sep_lo=0.3, sep_hi=10.0,
        breakout_min_pct=0.1,
        breakout_max_pct=15.0,
        min_vol_ratio=0.8,
        max_wick_ratio=0.80,
        retest_tol_pct=1.0,
        max_bars_after_breakout=10,
    )

    tf_1d: TimeframeCfg = TimeframeCfg(
        timeframe="1d",
        limit=600,
        swing_k=3,
        max_swings_lookback=260,
        min_r12=1.25,
        min_r23=1.20,
        require_descending_highs=True,
        require_ascending_lows=True,
        c3_lo=3.0, c3_hi=20.0,
        atrp_lo=0.8, atrp_hi=8.0,
        sep_lo=0.5, sep_hi=15.0,
        breakout_min_pct=0.1,
        breakout_max_pct=15.0,
        min_vol_ratio=0.8,
        max_wick_ratio=0.80,
        retest_tol_pct=1.5,
        max_bars_after_breakout=10,
    )


# ===== TIERED VCP GRADES =====
# Grade A: Strict classic VCP (Minervini-style)
GRADE_A_PARAMS = {
    "min_r12": 1.25,
    "min_r23": 1.20,
    "require_descending_highs": True,
    "require_ascending_lows": True,
    "trend_mode": "STRICT",  # close > EMA50 > EMA200 + rising EMA200
}

# Grade B: Relaxed VCP (uptrend but relaxed structure)
GRADE_B_PARAMS = {
    "min_r12": 1.15,
    "min_r23": 1.10,
    "require_descending_highs": False,
    "require_ascending_lows": False,
    "trend_mode": "ABOVE_EMA50",  # close > EMA50
}

# Grade C: Basic contraction (minimal trend requirement)
GRADE_C_PARAMS = {
    "min_r12": 1.05,
    "min_r23": 1.02,
    "require_descending_highs": False,
    "require_ascending_lows": False,
    "trend_mode": "ABOVE_EMA200",  # close > EMA200
}

# Grade D: Accumulation (for bear markets - potential reversals)
GRADE_D_PARAMS = {
    "min_r12": 1.02,
    "min_r23": 1.01,
    "require_descending_highs": False,
    "require_ascending_lows": False,
    "trend_mode": "ANY",  # No trend requirement
}


ALL_GRADES = [
    (GRADE_A_PARAMS, "A"),
    (GRADE_B_PARAMS, "B"),
    (GRADE_C_PARAMS, "C"),
    (GRADE_D_PARAMS, "D"),
]
```

---

## 설명

### TimeframeCfg
- **timeframe**: `"4h"` 또는 `"1d"`
- **swing_k**: 스윙 포인트 탐지용 K값 (기본 3)
- **min_r12, min_r23**: VCP 수축 비율 임계값

### ScannerCfg
- **universe_top_n**: 거래량 상위 200개 코인 분석
- **min_quote_volume_usdt**: 최소 거래대금 500만 달러

### Tiered Grades (A/B/C/D)
- **A등급**: Minervini 수준의 엄격한 VCP
- **B등급**: EMA50 위에서 완화된 구조
- **C등급**: EMA200 위에서 기본 수축
- **D등급**: 추세 무관 축적 패턴 (약세장용)
