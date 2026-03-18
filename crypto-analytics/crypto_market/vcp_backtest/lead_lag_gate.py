#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Trading Gate
Uses macro indicators to gate/filter VCP entries based on lead-lag analysis.

Key Indicators (from Granger Causality Analysis):
- TNX_MoM (10Y Treasury Yield change) - 2 month lead, p=0.0002
- VIX_MoM (Volatility change) - 2 month lead, p=0.001
- SPY_3M (S&P 500 3-month momentum) - 2 month lead, p=0.0039

Usage:
    gate = LeadLagGate()
    if gate.should_trade():
        # Execute VCP trades
"""
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class MacroCondition:
    """A single macro condition for the gate"""
    indicator: str
    operator: str  # "gt", "lt", "gte", "lte", "between"
    value: float
    value2: Optional[float] = None  # For "between"
    description: str = ""


@dataclass
class LeadLagGateResult:
    """Result of lead-lag gate check"""
    should_trade: bool
    signal_strength: str  # "STRONG", "MODERATE", "WEAK", "BLOCKED"
    score: int  # 0-100
    conditions_met: List[str]
    conditions_failed: List[str]
    recommendation: str


class LeadLagGate:
    """
    Macro-based trading gate using lead-lag indicators.
    """
    
    # Default conditions based on Granger analysis results
    DEFAULT_CONDITIONS = [
        MacroCondition("SPY_3M", "gt", 0, description="SPY 3개월 모멘텀 양수"),
        MacroCondition("VIX", "lt", 25, description="VIX 25 미만 (공포 낮음)"),
        MacroCondition("VIX_MoM", "lt", 20, description="VIX 월간 변화 20% 미만"),
        MacroCondition("TNX_MoM", "between", -10, 10, description="금리 변동 안정 (-10%~10%)"),
    ]
    
    def __init__(self, conditions: List[MacroCondition] = None):
        self.conditions = conditions or self.DEFAULT_CONDITIONS
        self._cached_data: Dict[str, float] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_duration = timedelta(hours=4)
    
    def set_macro_data(self, data: Dict[str, float]) -> None:
        """Set macro indicator values manually"""
        self._cached_data = data
        self._cache_timestamp = datetime.now()
    
    def fetch_macro_data(self) -> Dict[str, float]:
        """
        Fetch current macro indicator values.
        Uses lead_lag.data_fetcher if available.
        """
        # Check cache
        if self._cache_timestamp and \
           datetime.now() - self._cache_timestamp < self._cache_duration:
            return self._cached_data
        
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from lead_lag import fetch_all_data
            
            # Fetch recent data
            df = fetch_all_data(
                start_date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
                resample="monthly",
                include_derivatives=True
            )
            
            if df.empty:
                return {}
            
            # Get latest row
            latest = df.iloc[-1]
            
            data = {}
            for col in df.columns:
                if col.startswith('_'):
                    continue
                val = latest.get(col)
                if val is not None and not (isinstance(val, float) and val != val):  # not nan
                    data[col] = float(val)
            
            self._cached_data = data
            self._cache_timestamp = datetime.now()
            
            logger.info(f"Fetched {len(data)} macro indicators")
            return data
            
        except Exception as e:
            logger.warning(f"Failed to fetch macro data: {e}")
            return self._cached_data
    
    def _check_condition(self, condition: MacroCondition, value: float) -> bool:
        """Check if a single condition is met"""
        if condition.operator == "gt":
            return value > condition.value
        elif condition.operator == "lt":
            return value < condition.value
        elif condition.operator == "gte":
            return value >= condition.value
        elif condition.operator == "lte":
            return value <= condition.value
        elif condition.operator == "between":
            return condition.value <= value <= condition.value2
        return False
    
    def evaluate(self, data: Dict[str, float] = None) -> LeadLagGateResult:
        """
        Evaluate all conditions and return gate result.
        """
        if data is None:
            data = self.fetch_macro_data()
        
        if not data:
            return LeadLagGateResult(
                should_trade=True,  # Default to allowing trades if no data
                signal_strength="UNKNOWN",
                score=50,
                conditions_met=[],
                conditions_failed=["No macro data available"],
                recommendation="데이터 없음 - 기본 설정으로 진행"
            )
        
        conditions_met = []
        conditions_failed = []
        
        for condition in self.conditions:
            indicator = condition.indicator
            
            if indicator not in data:
                continue
            
            value = data[indicator]
            passed = self._check_condition(condition, value)
            
            if passed:
                conditions_met.append(f"✅ {condition.description} ({indicator}={value:.1f})")
            else:
                conditions_failed.append(f"❌ {condition.description} ({indicator}={value:.1f})")
        
        # Calculate score (0-100)
        total_conditions = len(conditions_met) + len(conditions_failed)
        if total_conditions > 0:
            score = int((len(conditions_met) / total_conditions) * 100)
        else:
            score = 50
        
        # Determine signal strength
        if score >= 80:
            signal_strength = "STRONG"
            should_trade = True
            recommendation = "🟢 매크로 환경 양호 - 적극 트레이딩 가능"
        elif score >= 60:
            signal_strength = "MODERATE"
            should_trade = True
            recommendation = "🟡 매크로 환경 보통 - 선별적 트레이딩"
        elif score >= 40:
            signal_strength = "WEAK"
            should_trade = True
            recommendation = "🟠 매크로 환경 약함 - 보수적 접근 권장"
        else:
            signal_strength = "BLOCKED"
            should_trade = False
            recommendation = "🔴 매크로 환경 부정적 - 트레이딩 비추천"
        
        return LeadLagGateResult(
            should_trade=should_trade,
            signal_strength=signal_strength,
            score=score,
            conditions_met=conditions_met,
            conditions_failed=conditions_failed,
            recommendation=recommendation
        )
    
    def should_trade(self, data: Dict[str, float] = None) -> bool:
        """Simple check if trading is allowed"""
        return self.evaluate(data).should_trade
    
    def get_current_status(self) -> str:
        """Get human-readable current status"""
        result = self.evaluate()
        
        status = f"""
╔══════════════════════════════════════════════════════════╗
║           LEAD-LAG TRADING GATE STATUS                   ║
╠══════════════════════════════════════════════════════════╣
║ Signal Strength: {result.signal_strength:>10}  │  Score: {result.score:>3}/100    ║
║ Should Trade:    {str(result.should_trade):>10}                          ║
╠══════════════════════════════════════════════════════════╣
║ {result.recommendation:<56} ║
╠══════════════════════════════════════════════════════════╣
"""
        
        if result.conditions_met:
            status += "║ ✅ CONDITIONS MET:                                       ║\n"
            for c in result.conditions_met[:3]:
                status += f"║   {c[:53]:<53} ║\n"
        
        if result.conditions_failed:
            status += "║ ❌ CONDITIONS FAILED:                                    ║\n"
            for c in result.conditions_failed[:3]:
                status += f"║   {c[:53]:<53} ║\n"
        
        status += "╚══════════════════════════════════════════════════════════╝"
        
        return status


# CPI Event-based risk reduction
def is_near_cpi_release(days_buffer: int = 3) -> Tuple[bool, str]:
    """
    Check if we're near a CPI release date.
    CPI is typically released mid-month (10th-15th).
    
    Returns:
        (is_near, reason)
    """
    today = datetime.now()
    day = today.day
    
    # CPI typically released around 10th-14th of month
    cpi_window_start = 10 - days_buffer
    cpi_window_end = 14 + days_buffer
    
    if cpi_window_start <= day <= cpi_window_end:
        return True, f"CPI 발표 근접 (현재 {day}일, 발표 10-14일)"
    
    return False, f"CPI 발표일 아님 (현재 {day}일)"


if __name__ == "__main__":
    print("\n📊 LEAD-LAG TRADING GATE TEST")
    print("=" * 50)
    
    # Create gate with default conditions
    gate = LeadLagGate()
    
    # Set mock macro data
    mock_data = {
        "SPY_3M": 5.2,      # Positive momentum
        "VIX": 18.5,        # Low fear
        "VIX_MoM": -2.3,    # VIX decreasing
        "TNX_MoM": 3.5,     # Rates stable
    }
    
    gate.set_macro_data(mock_data)
    
    # Evaluate
    result = gate.evaluate()
    
    print(f"\n🎯 Result:")
    print(f"   Should Trade: {result.should_trade}")
    print(f"   Signal: {result.signal_strength}")
    print(f"   Score: {result.score}/100")
    print(f"   Recommendation: {result.recommendation}")
    
    print(f"\n📋 Conditions Met ({len(result.conditions_met)}):")
    for c in result.conditions_met:
        print(f"   {c}")
    
    print(f"\n📋 Conditions Failed ({len(result.conditions_failed)}):")
    for c in result.conditions_failed:
        print(f"   {c}")
    
    # Test CPI check
    is_near, reason = is_near_cpi_release()
    print(f"\n📅 CPI Check: {reason}")
    
    print("\n" + gate.get_current_status())
    
    print("\n✅ Lead-Lag Gate test complete!")
