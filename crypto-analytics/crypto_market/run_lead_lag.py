#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis CLI Runner
Command-line interface for running lead-lag and Granger causality analysis.

ULTRATHINK Features:
- Fetches data from yfinance + FRED
- Runs cross-correlation with multiple lags
- Runs Granger causality tests
- Uses LLM (Gemini) for interpretation
- Outputs results in formatted tables
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lead_lag import (
    fetch_all_data,
    get_data_summary,
    build_lead_lag_matrix,
    print_lead_lag_matrix,
    find_granger_causal_indicators,
    print_granger_results,
    interpret_lead_lag_results,
    interpret_granger_results,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════╗
║          LEAD-LAG CORRELATION ANALYSIS                       ║
║          ULTRATHINK Implementation                           ║
╚══════════════════════════════════════════════════════════════╝
    """)


def run_analysis(args):
    """Run full lead-lag analysis"""
    logger.info(f"Starting analysis: {args.start} to {args.end or 'today'}")
    logger.info(f"Target: {args.target}, Max Lag: {args.max_lag}")
    
    # Fetch data
    logger.info("📥 Fetching data...")
    df = fetch_all_data(
        start_date=args.start,
        end_date=args.end,
        resample="monthly"
    )
    
    if df.empty:
        print("❌ Failed to fetch data. Check your internet connection.")
        return
    
    # Show data summary
    summary = get_data_summary(df)
    print(f"\n📊 DATA SUMMARY")
    print(f"   Period: {summary['date_range']['start']} to {summary['date_range']['end']}")
    print(f"   Observations: {summary['date_range']['periods']}")
    print(f"   Variables: {len(summary['columns'])}")
    
    # Determine target variable
    target = args.target
    if target == "BTC" and "BTC_ret" in df.columns:
        target = "BTC_ret"  # Use returns for analysis
    
    if target not in df.columns:
        print(f"❌ Target '{target}' not found. Available: {df.columns.tolist()}")
        return
    
    # ===== CROSS-CORRELATION ANALYSIS =====
    print("\n" + "=" * 60)
    print("🔬 PART 1: CROSS-CORRELATION ANALYSIS")
    print("=" * 60)
    
    matrix = build_lead_lag_matrix(
        df,
        target=target,
        max_lag=args.max_lag,
        lang=args.lang
    )
    
    print_lead_lag_matrix(matrix)
    
    # ===== GRANGER CAUSALITY ANALYSIS =====
    print("\n" + "=" * 60)
    print("🔬 PART 2: GRANGER CAUSALITY ANALYSIS")
    print("=" * 60)
    
    granger_results = find_granger_causal_indicators(
        df,
        target=target,
        max_lag=args.max_lag
    )
    
    print_granger_results(granger_results, target)
    
    # ===== LLM INTERPRETATION =====
    if args.use_llm:
        print("\n" + "=" * 60)
        print("🤖 PART 3: AI INTERPRETATION (Gemini)")
        print("=" * 60)
        
        # Prepare results for LLM
        lead_lag_dicts = [r.to_dict() for r in matrix.results[:10]]
        granger_dicts = [r.to_dict() for r in granger_results[:5]]
        
        print("\n📝 Lead-Lag Interpretation:")
        print("-" * 40)
        interpretation = interpret_lead_lag_results(
            lead_lag_dicts,
            target=args.target,
            lang=args.lang
        )
        print(interpretation)
        
        if granger_results:
            print("\n📝 Granger Causality Interpretation:")
            print("-" * 40)
            granger_interp = interpret_granger_results(
                granger_dicts,
                target=args.target,
                lang=args.lang
            )
            print(granger_interp)
    
    # ===== SAVE RESULTS =====
    if args.output:
        results = {
            "metadata": {
                "target": args.target,
                "period": f"{args.start} to {args.end or 'today'}",
                "max_lag": args.max_lag,
                "generated_at": datetime.now().isoformat()
            },
            "lead_lag": [r.to_dict() for r in matrix.results],
            "granger": [r.to_dict() for r in granger_results],
            "data_summary": summary
        }
        
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ Results saved to {args.output}")
    
    # ===== TRADING SIGNALS =====
    print("\n" + "=" * 60)
    print("📈 KEY TAKEAWAYS")
    print("=" * 60)
    
    # Leading indicators (positive lag)
    leaders = [r for r in matrix.results if r.optimal_lag > 0 and abs(r.optimal_correlation) > 0.3]
    if leaders:
        print("\n🔮 LEADING INDICATORS (move BEFORE target):")
        for r in leaders[:5]:
            print(f"   ⬆️ {r.var1}: {r.optimal_lag} months ahead, r={r.optimal_correlation:+.3f}")
    
    # Lagging indicators (negative lag)
    laggers = [r for r in matrix.results if r.optimal_lag < 0 and abs(r.optimal_correlation) > 0.3]
    if laggers:
        print("\n📉 LAGGING INDICATORS (move AFTER target):")
        for r in laggers[:5]:
            print(f"   ⬇️ {r.var1}: {abs(r.optimal_lag)} months behind, r={r.optimal_correlation:+.3f}")
    
    # Granger causal
    if granger_results:
        print("\n🎯 PREDICTIVE INDICATORS (Granger Causal):")
        for r in granger_results[:5]:
            print(f"   ⭐ {r.cause}: predicts at lag {r.best_lag} (p={r.best_p_value:.4f})")


def main():
    print_banner()
    
    parser = argparse.ArgumentParser(description='Lead-Lag Correlation Analysis')
    
    parser.add_argument('--start', default='2020-01-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default=None, help='End date (YYYY-MM-DD, defaults to today)')
    parser.add_argument('--target', default='BTC', help='Target variable to analyze')
    parser.add_argument('--max-lag', type=int, default=12, help='Maximum lag in periods')
    parser.add_argument('--lang', default='ko', choices=['ko', 'en'], help='Output language')
    parser.add_argument('--use-llm', action='store_true', default=True, help='Use LLM for interpretation')
    parser.add_argument('--no-llm', action='store_false', dest='use_llm', help='Disable LLM interpretation')
    parser.add_argument('--output', '-o', help='Output JSON file')
    
    args = parser.parse_args()
    
    run_analysis(args)


if __name__ == "__main__":
    main()
