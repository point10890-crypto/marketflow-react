#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Final Top 10 Report Generator
Combines Smart Money Screener + AI Analysis to produce the ultimate stock picks
"""

import os
import json
import pandas as pd
from datetime import datetime
from typing import Dict, List
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FinalReportGenerator:
    """Generate final Top 10 report combining all analyses"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'final_top10_report.json')
    
    def load_data(self) -> tuple:
        """Load smart money picks and AI summaries"""
        # Load quantitative data
        quant_path = os.path.join(self.data_dir, 'output', 'smart_money_picks_v2.csv')
        if not os.path.exists(quant_path):
            raise FileNotFoundError(f"Smart money picks not found: {quant_path}")
        quant_df = pd.read_csv(quant_path)
        
        # Load AI summaries
        ai_path = os.path.join(self.data_dir, 'output', 'ai_summaries.json')
        ai_summaries = {}
        if os.path.exists(ai_path):
            with open(ai_path, 'r', encoding='utf-8') as f:
                ai_summaries = json.load(f)
        
        return quant_df, ai_summaries
    
    def extract_ai_recommendation(self, summary: str) -> tuple:
        """Extract recommendation and sentiment from AI summary"""
        summary_lower = summary.lower()
        
        # Score based on keywords
        ai_score = 0
        recommendation = "관망"
        
        # Strong buy signals
        if "적극 매수" in summary or "strong buy" in summary_lower:
            ai_score += 20
            recommendation = "적극 매수"
        elif "매수" in summary and "조정 시" in summary:
            ai_score += 15
            recommendation = "조정 시 매수"
        elif "매수" in summary or "buy" in summary_lower:
            ai_score += 10
            recommendation = "매수"
        
        # Caution signals
        if "과매수" in summary or "overbought" in summary_lower:
            ai_score -= 5
        if "조정 가능성" in summary:
            ai_score -= 3
        
        # Positive signals
        if "상승 추세" in summary or "bullish" in summary_lower:
            ai_score += 5
        if "긍정적" in summary:
            ai_score += 3
        if "성장" in summary:
            ai_score += 3
        
        return ai_score, recommendation
    
    def calculate_final_score(self, row: pd.Series, ai_summaries: Dict) -> Dict:
        """Calculate final combined score"""
        ticker = row['ticker']
        
        # Quantitative score (0-100)
        quant_score = row.get('composite_score', 50)
        
        # AI analysis score
        ai_score = 0
        ai_recommendation = "분석 없음"
        ai_summary = ""
        
        if ticker in ai_summaries:
            ai_summary = ai_summaries[ticker].get('summary', '')
            ai_score, ai_recommendation = self.extract_ai_recommendation(ai_summary)
        
        # Final score: 80% quantitative + 20% AI bonus
        final_score = quant_score * 0.8 + max(0, ai_score) * 1.0
        
        return {
            'ticker': ticker,
            'name': row.get('name', ticker),
            'final_score': round(final_score, 1),
            'quant_score': quant_score,
            'ai_bonus': ai_score,
            'ai_recommendation': ai_recommendation,
            'grade': row.get('grade', 'N/A'),
            'current_price': row.get('current_price', 0),
            'target_upside': row.get('target_upside', 0),
            'sd_stage': row.get('sd_stage', 'N/A'),
            'inst_pct': row.get('inst_pct', 0),
            'rsi': row.get('rsi', 0),
            'ai_summary': ai_summary[:500] if ai_summary else ''
        }
    
    def generate_report(self, top_n: int = 10) -> List[Dict]:
        """Generate final Top N report"""
        logger.info("📊 Generating Final Top 10 Report...")
        
        quant_df, ai_summaries = self.load_data()
        
        # Calculate final scores for all stocks with AI summaries
        results = []
        for _, row in quant_df.iterrows():
            ticker = row['ticker']
            if ticker in ai_summaries:  # Only include stocks with AI analysis
                result = self.calculate_final_score(row, ai_summaries)
                results.append(result)
        
        # Sort by final score
        results.sort(key=lambda x: x['final_score'], reverse=True)
        
        # Take top N
        top_results = results[:top_n]
        
        # Add rank
        for i, r in enumerate(top_results, 1):
            r['rank'] = i
        
        # Save report
        report = {
            'generated_at': datetime.now().isoformat(),
            'total_analyzed': len(results),
            'top_picks': top_results
        }
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Report saved to {self.output_file}")
        
        # Also save smart_money_current.json for Flask dashboard
        current_file = os.path.join(self.data_dir, 'output', 'smart_money_current.json')
        current_data = {
            'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            'analysis_timestamp': datetime.now().isoformat(),
            'picks': [
                {
                    'ticker': p['ticker'],
                    'name': p['name'],
                    'rank': p['rank'],
                    'final_score': p['final_score'],
                    'quant_score': p['quant_score'],
                    'ai_bonus': p['ai_bonus'],
                    'ai_recommendation': p['ai_recommendation'],
                    'price_at_analysis': p['current_price'],
                    'target_upside': p['target_upside'],
                    'sd_stage': p['sd_stage'],
                    'inst_pct': p['inst_pct'],
                    'rsi': p['rsi'],
                    'ai_summary': p['ai_summary']
                }
                for p in top_results
            ]
        }
        
        with open(current_file, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Dashboard data saved to {current_file}")
        
        # Save to history folder for date filter
        history_dir = os.path.join(self.data_dir, 'history')
        if not os.path.exists(history_dir):
            os.makedirs(history_dir)
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        history_file = os.path.join(history_dir, f'picks_{today_str}.json')
        
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ History saved to {history_file}")
        
        return top_results
    
    def print_report(self, top_picks: List[Dict]):
        """Print formatted report"""
        print("\n" + "="*100)
        print("🏆 FINAL TOP 10 PICKS - 수치 분석 + AI 분석 종합")
        print("="*100)
        
        for pick in top_picks:
            rec_emoji = "🔥" if pick['ai_recommendation'] == "적극 매수" else "📈" if "매수" in pick['ai_recommendation'] else "📊"
            
            print(f"\n#{pick['rank']} {pick['ticker']} - {pick['name']}")
            print(f"   💰 Final Score: {pick['final_score']}/100 (Quant: {pick['quant_score']}, AI: +{pick['ai_bonus']})")
            print(f"   {rec_emoji} AI 추천: {pick['ai_recommendation']}")
            print(f"   📊 수급: {pick['sd_stage']} | 기관: {pick['inst_pct']:.1f}% | RSI: {pick['rsi']}")
            print(f"   💵 현재가: ${pick['current_price']:.2f} | 목표 Upside: {pick['target_upside']:+.1f}%")
            
            # Short AI summary
            if pick['ai_summary']:
                short_summary = pick['ai_summary'][:200] + "..." if len(pick['ai_summary']) > 200 else pick['ai_summary']
                print(f"   🤖 {short_summary}")
        
        print("\n" + "="*100)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Final Top 10 Report Generator')
    parser.add_argument('--dir', default='.', help='Data directory')
    parser.add_argument('--top', type=int, default=10, help='Top N picks')
    args = parser.parse_args()
    
    generator = FinalReportGenerator(data_dir=args.dir)
    top_picks = generator.generate_report(top_n=args.top)
    generator.print_report(top_picks)


if __name__ == "__main__":
    main()
