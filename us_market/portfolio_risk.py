#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio Risk Analyzer
- Calculates correlation matrix for top picks
- Identifies concentration risk
- Suggests diversification candidates
"""

import os
import json
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import seaborn as sns
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PortfolioRiskAnalyzer:
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        self.output_file = os.path.join(data_dir, 'output', 'portfolio_risk.json')
        
    def get_correlation_matrix(self, tickers: List[str], period: str = '6mo') -> Dict:
        """Calculate correlation matrix for tickers"""
        try:
            logger.info(f"⚖️ fetching history for correlation analysis...")
            
            # Fetch data
            data = yf.download(tickers, period=period, progress=False)['Close']
            
            if data.empty:
                return {'error': 'No data fetched'}
            
            # Calculate daily returns
            returns = data.pct_change().dropna()
            
            # Correlation Matrix
            corr_matrix = returns.corr()
            
            # Identify high correlation pairs (> 0.8)
            high_corr_pairs = []
            
            # Iterate only upper triangle to avoid duplicates
            cols = corr_matrix.columns
            for i in range(len(cols)):
                for j in range(i+1, len(cols)):
                    t1, t2 = cols[i], cols[j]
                    val = corr_matrix.iloc[i, j]
                    
                    if val > 0.80:
                        high_corr_pairs.append({
                            'pair': [t1, t2],
                            'correlation': round(float(val), 2),
                            'recommendation': 'High overlap - consider holding only one'
                        })
                        
            # Portfolio Volatility (Equal Weight approximation)
            # Weights
            n = len(tickers)
            weights = np.array([1/n] * n)
            
            # Covariance
            cov_matrix = returns.cov() * 252 # Annualized
            
            # Portfolio Variance = w.T * Cov * w
            port_variance = np.dot(weights.T, np.dot(cov_matrix, weights))
            port_volatility = np.sqrt(port_variance)
            
            # Convert matrix to dict for JSON
            # Replace NaN with 0
            corr_dict = corr_matrix.fillna(0).round(2).to_dict()
            
            return {
                'correlation_matrix': corr_dict,
                'high_correlation_pairs': high_corr_pairs,
                'portfolio_volatility_annualized': round(float(port_volatility) * 100, 2),
                'risk_level': 'High' if port_volatility > 0.25 else 'Moderate' if port_volatility > 0.15 else 'Low'
            }
            
        except Exception as e:
            logger.error(f"Error calculating correlation: {e}")
            return {'error': str(e)}

    def analyze_portfolio(self, tickers: List[str]) -> Dict:
        """Analyze portfolio risk"""
        logger.info(f"⚖️ Analyzing portfolio risk for {len(tickers)} tickers: {tickers}")
        
        result = self.get_correlation_matrix(tickers)
        
        output = {
            'timestamp': datetime.now().isoformat(),
            'tickers': tickers,
            'analysis': result
        }
        
        # Save results
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            
        logger.info(f"✅ Saved risk analysis to {self.output_file}")
        
        return output

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', nargs='+', help='List of tickers')
    args = parser.parse_args()
    
    analyzer = PortfolioRiskAnalyzer()
    
    # Default watchlist
    target_tickers = args.tickers
    if not target_tickers:
        try:
            picks_file = os.path.join('us_market', 'output', 'smart_money_picks_v2.csv')
            if os.path.exists(picks_file):
                df = pd.read_csv(picks_file)
                # Take top 10 for portfolio sim
                target_tickers = df['ticker'].tolist()[:10]
            else:
                 target_tickers = ['AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META']
        except:
             target_tickers = ['AAPL', 'NVDA']
             
    result = analyzer.analyze_portfolio(target_tickers)
    analysis = result['analysis']
    
    print("\n" + "="*60)
    print("⚖️ PORTFOLIO RISK ANALYSIS")
    print("="*60)
    
    if 'error' in analysis:
        print(f"Error: {analysis['error']}")
    else:
        print(f"\n📊 Annualized Volatility: {analysis['portfolio_volatility_annualized']}% ({analysis['risk_level']})")
        
        if analysis['high_correlation_pairs']:
            print("\n⚠️ High Correlation Alerts (> 0.8):")
            for pair in analysis['high_correlation_pairs']:
                print(f"  - {pair['pair'][0]} <-> {pair['pair'][1]}: {pair['correlation']} (Diversification Risk)")
        else:
            print("\n✅ Good Diversification (No pairs > 0.8 correlation)")

if __name__ == "__main__":
    main()
