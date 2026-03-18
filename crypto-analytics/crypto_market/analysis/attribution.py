#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Attribution
Decompose trading performance by various dimensions.

Features:
1. Gate/Grade/Entry type attribution
2. Profit concentration analysis
3. Signal funnel analysis
"""
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# Add parent path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class AttributionResult:
    """Result of attribution analysis"""
    dimension: str
    breakdown: Dict[str, Dict]
    insights: List[str]


class PerformanceAttribution:
    """
    Performance attribution and decomposition.
    """
    
    def __init__(self, trades: List[Dict]):
        self.trades = trades
    
    def by_gate(self) -> AttributionResult:
        """Breakdown by Market Gate (GREEN/YELLOW/RED)"""
        breakdown = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0})
        
        for trade in self.trades:
            # Extract gate from market_regime or gate field
            gate = trade.get('gate', trade.get('market_regime', 'UNKNOWN'))
            if '|' in str(gate):
                gate = gate.split('|')[0]
            gate = gate.upper().replace('BTC_UP', 'GREEN').replace('BTC_SIDE', 'YELLOW').replace('BTC_DOWN', 'RED')
            
            pnl = trade.get('pnl', trade.get('return_pct', 0))
            is_win = pnl > 0
            
            breakdown[gate]['trades'] += 1
            breakdown[gate]['wins'] += 1 if is_win else 0
            breakdown[gate]['total_pnl'] += pnl
        
        # Calculate stats
        for gate, stats in breakdown.items():
            if stats['trades'] > 0:
                stats['win_rate'] = stats['wins'] / stats['trades'] * 100
                stats['avg_pnl'] = stats['total_pnl'] / stats['trades']
                stats['pf'] = self._calc_profit_factor([
                    t for t in self.trades 
                    if t.get('gate', t.get('market_regime', '')).upper().startswith(gate[:3])
                ])
        
        insights = self._generate_gate_insights(dict(breakdown))
        
        return AttributionResult(
            dimension="Market Gate",
            breakdown=dict(breakdown),
            insights=insights
        )
    
    def by_grade(self) -> AttributionResult:
        """Breakdown by VCP Grade (A/B/C/D)"""
        breakdown = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0})
        
        for trade in self.trades:
            regime = trade.get('market_regime', '')
            grade = 'D'
            if '|' in str(regime):
                parts = regime.split('|')
                grade = parts[1] if len(parts) > 1 else 'D'
            
            pnl = trade.get('pnl', trade.get('return_pct', 0))
            is_win = pnl > 0
            
            breakdown[grade]['trades'] += 1
            breakdown[grade]['wins'] += 1 if is_win else 0
            breakdown[grade]['total_pnl'] += pnl
        
        # Calculate stats
        for grade, stats in breakdown.items():
            if stats['trades'] > 0:
                stats['win_rate'] = stats['wins'] / stats['trades'] * 100
                stats['avg_pnl'] = stats['total_pnl'] / stats['trades']
        
        return AttributionResult(
            dimension="VCP Grade",
            breakdown=dict(breakdown),
            insights=self._generate_grade_insights(dict(breakdown))
        )
    
    def by_entry_type(self) -> AttributionResult:
        """Breakdown by Entry Type (BREAKOUT/RETEST)"""
        breakdown = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0})
        
        for trade in self.trades:
            entry_type = trade.get('entry_type', trade.get('signal_type', 'UNKNOWN'))
            
            pnl = trade.get('pnl', trade.get('return_pct', 0))
            is_win = pnl > 0
            
            breakdown[entry_type]['trades'] += 1
            breakdown[entry_type]['wins'] += 1 if is_win else 0
            breakdown[entry_type]['total_pnl'] += pnl
        
        # Calculate stats
        for entry_type, stats in breakdown.items():
            if stats['trades'] > 0:
                stats['win_rate'] = stats['wins'] / stats['trades'] * 100
                stats['avg_pnl'] = stats['total_pnl'] / stats['trades']
        
        return AttributionResult(
            dimension="Entry Type",
            breakdown=dict(breakdown),
            insights=[]
        )
    
    def profit_concentration(self) -> Dict:
        """Analyze profit concentration (top N% = X% of profits)"""
        if not self.trades:
            return {}
        
        # Sort trades by P&L
        sorted_trades = sorted(
            self.trades, 
            key=lambda t: t.get('pnl', t.get('return_pct', 0)), 
            reverse=True
        )
        
        total_pnl = sum(t.get('pnl', t.get('return_pct', 0)) for t in self.trades)
        total_profits = sum(
            t.get('pnl', t.get('return_pct', 0)) 
            for t in self.trades 
            if t.get('pnl', t.get('return_pct', 0)) > 0
        )
        
        n_trades = len(self.trades)
        
        # Calculate concentration at various percentiles
        concentration = {}
        for pct in [10, 20, 30, 50]:
            n = max(1, int(n_trades * pct / 100))
            top_trades = sorted_trades[:n]
            top_pnl = sum(t.get('pnl', t.get('return_pct', 0)) for t in top_trades)
            
            concentration[f'top_{pct}pct'] = {
                'trades': n,
                'pnl': top_pnl,
                'pct_of_total': (top_pnl / total_profits * 100) if total_profits > 0 else 0
            }
        
        return {
            'total_trades': n_trades,
            'total_pnl': total_pnl,
            'total_profits': total_profits,
            'concentration': concentration,
            'insight': self._concentration_insight(concentration)
        }
    
    def signal_funnel(
        self,
        universe_size: int = 0,
        scanned: int = 0,
        passed_score: int = 0,
        passed_grade: int = 0,
        passed_gate: int = 0
    ) -> Dict:
        """Analyze signal funnel from universe to trades"""
        traded = len(self.trades)
        wins = len([t for t in self.trades if t.get('pnl', t.get('return_pct', 0)) > 0])
        
        funnel = [
            ('Universe', universe_size, 100.0),
            ('Scanned', scanned, (scanned/universe_size*100) if universe_size > 0 else 0),
            ('Score > threshold', passed_score, (passed_score/universe_size*100) if universe_size > 0 else 0),
            ('Grade pass', passed_grade, (passed_grade/universe_size*100) if universe_size > 0 else 0),
            ('Gate pass', passed_gate, (passed_gate/universe_size*100) if universe_size > 0 else 0),
            ('Traded', traded, (traded/universe_size*100) if universe_size > 0 else 0),
            ('Profitable', wins, (wins/universe_size*100) if universe_size > 0 else 0),
        ]
        
        return {
            'stages': funnel,
            'conversion_rate': (traded/universe_size*100) if universe_size > 0 else 0,
            'win_rate': (wins/traded*100) if traded > 0 else 0
        }
    
    def _calc_profit_factor(self, trades: List[Dict]) -> float:
        """Calculate profit factor"""
        gross_profit = sum(
            t.get('pnl', t.get('return_pct', 0)) 
            for t in trades 
            if t.get('pnl', t.get('return_pct', 0)) > 0
        )
        gross_loss = abs(sum(
            t.get('pnl', t.get('return_pct', 0)) 
            for t in trades 
            if t.get('pnl', t.get('return_pct', 0)) < 0
        ))
        
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    def _generate_gate_insights(self, breakdown: Dict) -> List[str]:
        """Generate insights from gate breakdown"""
        insights = []
        
        # Compare GREEN vs RED
        if 'GREEN' in breakdown and 'RED' in breakdown:
            green_wr = breakdown['GREEN'].get('win_rate', 0)
            red_wr = breakdown['RED'].get('win_rate', 0)
            
            if green_wr > red_wr + 10:
                insights.append(f"GREEN gate outperforms RED by {green_wr-red_wr:.0f}% win rate")
            
        # Check if YELLOW is problematic
        if 'YELLOW' in breakdown:
            yellow_pf = breakdown['YELLOW'].get('pf', 1.0)
            if yellow_pf < 1.0:
                insights.append("YELLOW gate underperforms (PF < 1.0) - consider tighter filters")
        
        return insights
    
    def _generate_grade_insights(self, breakdown: Dict) -> List[str]:
        """Generate insights from grade breakdown"""
        insights = []
        
        # Check A grade performance
        if 'A' in breakdown:
            a_wr = breakdown['A'].get('win_rate', 0)
            if a_wr > 60:
                insights.append(f"A-grade signals have {a_wr:.0f}% win rate - prioritize these")
        
        # Check if D grades are worth it
        if 'D' in breakdown:
            d_pnl = breakdown['D'].get('total_pnl', 0)
            if d_pnl < 0:
                insights.append("D-grade signals are net negative - consider filtering out")
        
        return insights
    
    def _concentration_insight(self, concentration: Dict) -> str:
        """Generate concentration insight"""
        top_10 = concentration.get('top_10pct', {})
        pct = top_10.get('pct_of_total', 0)
        
        if pct > 80:
            return f"⚠️ 상위 10% 트레이드가 수익의 {pct:.0f}% 차지 - 손절 중요"
        elif pct > 50:
            return f"상위 10% 트레이드가 수익의 {pct:.0f}% 차지 - 대박/쪽박 구조"
        else:
            return f"수익이 고르게 분산됨 (상위 10% = {pct:.0f}%)"
    
    def full_report(self) -> str:
        """Generate full attribution report"""
        gate = self.by_gate()
        grade = self.by_grade()
        entry = self.by_entry_type()
        concentration = self.profit_concentration()
        
        report = """
═══════════════════════════════════════════════════════════════
                    PERFORMANCE ATTRIBUTION REPORT
═══════════════════════════════════════════════════════════════

📊 BY MARKET GATE:
"""
        
        for g, stats in gate.breakdown.items():
            report += f"   {g:8}: {stats['trades']:3} trades, WR {stats.get('win_rate', 0):5.1f}%, "
            report += f"PF {stats.get('pf', 0):.2f}\n"
        
        if gate.insights:
            report += "\n   Insights:\n"
            for insight in gate.insights:
                report += f"   → {insight}\n"
        
        report += "\n📊 BY VCP GRADE:\n"
        for g in ['A', 'B', 'C', 'D']:
            if g in grade.breakdown:
                stats = grade.breakdown[g]
                report += f"   {g}:      {stats['trades']:3} trades, WR {stats.get('win_rate', 0):5.1f}%, "
                report += f"Avg P&L {stats.get('avg_pnl', 0):+.2f}%\n"
        
        report += "\n📊 BY ENTRY TYPE:\n"
        for e, stats in entry.breakdown.items():
            report += f"   {e:10}: {stats['trades']:3} trades, WR {stats.get('win_rate', 0):5.1f}%\n"
        
        report += f"\n📊 PROFIT CONCENTRATION:\n"
        for key, data in concentration.get('concentration', {}).items():
            report += f"   {key}: {data['pct_of_total']:.1f}% of profits\n"
        
        report += f"\n   {concentration.get('insight', '')}\n"
        
        report += """
═══════════════════════════════════════════════════════════════
"""
        return report


if __name__ == "__main__":
    print("\n📈 PERFORMANCE ATTRIBUTION TEST")
    print("=" * 50)
    
    # Mock trades
    mock_trades = [
        {'gate': 'GREEN', 'market_regime': 'BTC_UP|A', 'signal_type': 'BREAKOUT', 'pnl': 5.2},
        {'gate': 'GREEN', 'market_regime': 'BTC_UP|B', 'signal_type': 'BREAKOUT', 'pnl': 3.1},
        {'gate': 'GREEN', 'market_regime': 'BTC_UP|A', 'signal_type': 'RETEST', 'pnl': -1.5},
        {'gate': 'YELLOW', 'market_regime': 'BTC_SIDE|B', 'signal_type': 'BREAKOUT', 'pnl': -2.0},
        {'gate': 'YELLOW', 'market_regime': 'BTC_SIDE|C', 'signal_type': 'BREAKOUT', 'pnl': 1.2},
        {'gate': 'RED', 'market_regime': 'BTC_DOWN|D', 'signal_type': 'RETEST', 'pnl': -3.0},
    ]
    
    attr = PerformanceAttribution(mock_trades)
    print(attr.full_report())
    
    # Test concentration
    conc = attr.profit_concentration()
    print(f"\n💡 Concentration insight: {conc.get('insight', '')}")
    
    print("\n✅ Attribution test complete!")
