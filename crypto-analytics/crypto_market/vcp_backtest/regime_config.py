#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regime-aware VCP Configuration
Dynamically adjusts VCP parameters based on Market Gate color.

Gate Colors:
- GREEN (score >= 72): 공격 모드 - 완화된 필터
- YELLOW (48-71): 주의 모드 - 강화된 필터
- RED (< 48): 관망 모드 - 최소 진입 또는 스킵
"""
from dataclasses import dataclass
from typing import Literal, Optional
from .config import BacktestConfig


@dataclass
class RegimeConfig:
    """Configuration for a specific market regime"""
    gate: Literal["GREEN", "YELLOW", "RED"]
    description: str
    
    # VCP Signal Parameters
    min_score: int
    min_grade: str
    min_vol_ratio: float
    
    # Entry Parameters
    entry_trigger: Literal["BREAKOUT", "RETEST", "BOTH"]
    
    # Risk Parameters
    take_profit_pct: float
    trailing_stop_pct: float
    max_hold_bars: int
    max_concurrent_positions: int
    
    @classmethod
    def green(cls) -> "RegimeConfig":
        """GREEN: 공격 모드 - 시장이 강세일 때"""
        return cls(
            gate="GREEN",
            description="공격 모드: 시장 강세, 완화된 필터로 더 많은 기회 포착",
            min_score=45,
            min_grade="C",
            min_vol_ratio=1.1,
            entry_trigger="BOTH",
            take_profit_pct=12.0,
            trailing_stop_pct=5.0,
            max_hold_bars=25,
            max_concurrent_positions=6,
        )
    
    @classmethod
    def yellow(cls) -> "RegimeConfig":
        """YELLOW: 주의 모드 - 시장이 불확실할 때"""
        return cls(
            gate="YELLOW",
            description="주의 모드: 시장 불확실, 강화된 필터로 고품질 신호만",
            min_score=60,
            min_grade="B",
            min_vol_ratio=1.4,
            entry_trigger="BREAKOUT",
            take_profit_pct=8.0,
            trailing_stop_pct=4.0,
            max_hold_bars=15,
            max_concurrent_positions=3,
        )
    
    @classmethod
    def red(cls) -> "RegimeConfig":
        """RED: 관망 모드 - 시장이 약세일 때"""
        return cls(
            gate="RED",
            description="관망 모드: 시장 약세, RETEST만 허용 또는 스킵",
            min_score=75,
            min_grade="A",
            min_vol_ratio=1.8,
            entry_trigger="RETEST",  # Only retest entries
            take_profit_pct=6.0,
            trailing_stop_pct=3.0,
            max_hold_bars=10,
            max_concurrent_positions=1,
        )
    
    @classmethod
    def for_gate(cls, gate_color: str) -> "RegimeConfig":
        """Get config for a specific gate color"""
        gate_map = {
            "GREEN": cls.green,
            "YELLOW": cls.yellow,
            "RED": cls.red,
        }
        return gate_map.get(gate_color.upper(), cls.yellow)()
    
    def to_backtest_config(self, **overrides) -> BacktestConfig:
        """Convert to BacktestConfig for backtesting"""
        config_dict = {
            "min_score": self.min_score,
            "min_grade": self.min_grade,
            "entry_trigger": self.entry_trigger,
            "take_profit_pct": self.take_profit_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "max_hold_bars": self.max_hold_bars,
            "max_concurrent_positions": self.max_concurrent_positions,
            "use_market_gate": True,
            "allow_btc_side": self.gate == "GREEN",
            "allow_btc_down": False,
        }
        config_dict.update(overrides)
        return BacktestConfig(**config_dict)


def get_regime_explanation(gate_color: str, score: int) -> str:
    """
    "왜 요즘은 안 잡히는가?" 설명 생성
    """
    config = RegimeConfig.for_gate(gate_color)
    
    explanations = {
        "GREEN": f"""
🟢 **시장 상태: GREEN (점수: {score}/100)**

✅ **지금은 VCP 트레이딩에 좋은 환경입니다.**

현재 설정:
- 최소 점수: {config.min_score}+ (낮음 = 더 많은 기회)
- 최소 등급: {config.min_grade} 이상
- 진입 방식: {config.entry_trigger}
- 최대 동시 포지션: {config.max_concurrent_positions}개
""",
        "YELLOW": f"""
🟡 **시장 상태: YELLOW (점수: {score}/100)**

⚠️ **시장이 불확실하여 엄격한 필터가 적용됩니다.**

신호가 적게 나오는 이유:
- 최소 점수: {config.min_score}+ (높음 = 고품질만)
- 최소 등급: {config.min_grade} 이상 필요
- 진입 방식: {config.entry_trigger}만 허용
- 포지션 수 제한: {config.max_concurrent_positions}개

💡 시장 상황이 개선되면 자동으로 필터가 완화됩니다.
""",
        "RED": f"""
🔴 **시장 상태: RED (점수: {score}/100)**

🚫 **시장이 약세이므로 거의 모든 신호가 필터링됩니다.**

신호가 안 나오는 이유:
- 최소 점수: {config.min_score}+ (매우 높음)
- A등급만 허용
- RETEST 진입만 허용 (브레이크아웃 스킵)
- 최대 1개 포지션만

💡 이 구간에서는 관망하거나 현금 비중을 높이는 것이 권장됩니다.
""",
    }
    
    return explanations.get(gate_color.upper(), explanations["YELLOW"])


def compare_gate_performance(
    with_gate_results: dict,
    without_gate_results: dict
) -> str:
    """
    Gate 사용 여부에 따른 성과 비교 리포트 생성
    """
    def safe_get(d, key, default=0):
        return d.get(key, default) or default
    
    wg = with_gate_results
    ng = without_gate_results
    
    report = f"""
═══════════════════════════════════════════════════════════
📊 MARKET GATE 성과 비교
═══════════════════════════════════════════════════════════

┌─────────────────────┬───────────────┬───────────────┐
│       지표          │   Gate 미적용  │   Gate 적용   │
├─────────────────────┼───────────────┼───────────────┤
│ 총 트레이드         │ {safe_get(ng, 'total_trades'):>10}개  │ {safe_get(wg, 'total_trades'):>10}개  │
│ 승률                │ {safe_get(ng, 'win_rate'):>10.1f}%  │ {safe_get(wg, 'win_rate'):>10.1f}%  │
│ Profit Factor       │ {safe_get(ng, 'profit_factor'):>10.2f}  │ {safe_get(wg, 'profit_factor'):>10.2f}  │
│ Max Drawdown        │ {safe_get(ng, 'max_dd'):>10.1f}%  │ {safe_get(wg, 'max_dd'):>10.1f}%  │
│ Sharpe Ratio        │ {safe_get(ng, 'sharpe'):>10.2f}  │ {safe_get(wg, 'sharpe'):>10.2f}  │
│ 총 수익 ($)         │ {safe_get(ng, 'total_pnl'):>10.0f}  │ {safe_get(wg, 'total_pnl'):>10.0f}  │
└─────────────────────┴───────────────┴───────────────┘

"""
    
    # Calculate improvements
    wr_diff = safe_get(wg, 'win_rate') - safe_get(ng, 'win_rate')
    pf_diff = safe_get(wg, 'profit_factor') - safe_get(ng, 'profit_factor')
    
    if wr_diff > 0:
        report += f"✅ Gate 적용 시 승률 +{wr_diff:.1f}% 개선\n"
    elif wr_diff < 0:
        report += f"⚠️ Gate 적용 시 승률 {wr_diff:.1f}% 하락 (트레이드 수 감소로 인한 변동)\n"
    
    if pf_diff > 0:
        report += f"✅ Gate 적용 시 Profit Factor +{pf_diff:.2f} 개선\n"
    
    return report


if __name__ == "__main__":
    # Test regime configs
    for gate in ["GREEN", "YELLOW", "RED"]:
        config = RegimeConfig.for_gate(gate)
        print(f"\n{'='*50}")
        print(f"Gate: {gate}")
        print(f"Description: {config.description}")
        print(f"Min Score: {config.min_score}")
        print(f"Entry: {config.entry_trigger}")
        print(f"Max Positions: {config.max_concurrent_positions}")
