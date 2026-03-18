#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US ETF Fund Flow Analysis
Tracks money flows into/out of major ETFs (SPY, QQQ, Sector ETFs)
"""

import os
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from tqdm import tqdm
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

try:
    from macro_analyzer import MacroAIAnalyzer
except ImportError:
    # Handle case where script is run from different directory
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from macro_analyzer import MacroAIAnalyzer

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ETFFlowAnalyzer:
    """ETF Fund Flow Analysis for market sentiment"""
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'us_etf_flows.csv')
        
        # Major ETFs to track
        self.etf_list = {
            # Broad Market
            'SPY': ('S&P 500', 'Broad Market'),
            'QQQ': ('NASDAQ 100', 'Broad Market'),
            'IWM': ('Russell 2000', 'Broad Market'),
            'DIA': ('Dow Jones', 'Broad Market'),
            
            # Sector ETFs (SPDR Select Sector)
            'XLK': ('Technology', 'Sector'),
            'XLF': ('Financials', 'Sector'),
            'XLV': ('Health Care', 'Sector'),
            'XLE': ('Energy', 'Sector'),
            'XLI': ('Industrials', 'Sector'),
            'XLP': ('Consumer Staples', 'Sector'),
            'XLY': ('Consumer Discretionary', 'Sector'),
            'XLU': ('Utilities', 'Sector'),
            'XLB': ('Materials', 'Sector'),
            'XLRE': ('Real Estate', 'Sector'),
            'XLC': ('Communication Services', 'Sector'),
            
            # Thematic/Leveraged
            'ARKK': ('ARK Innovation', 'Thematic'),
            'TQQQ': ('NASDAQ 3x Bull', 'Leveraged'),
            'SQQQ': ('NASDAQ 3x Bear', 'Leveraged'),
            
            # International
            'EEM': ('Emerging Markets', 'International'),
            'VEA': ('Developed Markets', 'International'),
            
            # Bonds
            'TLT': ('20+ Year Treasury', 'Bonds'),
            'HYG': ('High Yield Corporate', 'Bonds'),
            
            # Commodities
            'GLD': ('Gold', 'Commodities'),
            'USO': ('Crude Oil', 'Commodities'),
        }
        
        # Initialize AI Analyzer
        self.ai_analyzer = MacroAIAnalyzer()
        self.ai_output_file = os.path.join(data_dir, 'output', 'etf_flow_analysis.json')
    
    def download_etf_data(self, ticker: str, period: str = '3mo') -> pd.DataFrame:
        """Download ETF price and volume data"""
        try:
            etf = yf.Ticker(ticker)
            hist = etf.history(period=period)
            
            if hist.empty:
                return pd.DataFrame()
            
            hist = hist.reset_index()
            hist['ticker'] = ticker
            return hist
            
        except Exception as e:
            logger.debug(f"Failed to download {ticker}: {e}")
            return pd.DataFrame()
    
    def calculate_flow_proxy(self, df: pd.DataFrame) -> Dict:
        """
        Calculate fund flow proxy using price-volume analysis
        Note: True AUM flows require premium data, this is an approximation
        """
        if len(df) < 20:
            return None
        
        df = df.sort_values('Date').reset_index(drop=True)
        
        # Dollar Volume (proxy for flow magnitude)
        df['dollar_volume'] = df['Close'] * df['Volume']
        
        # Daily Return
        df['return'] = df['Close'].pct_change()
        
        # Signed Dollar Volume (positive on up days, negative on down days)
        df['signed_flow'] = df['dollar_volume'] * np.sign(df['return'].fillna(0))
        
        # Calculate metrics
        latest = df.iloc[-1]
        
        # 5-day and 20-day aggregates
        flow_5d = df['signed_flow'].tail(5).sum()
        flow_20d = df['signed_flow'].tail(20).sum()
        
        # Average dollar volume
        avg_dollar_vol_5d = df['dollar_volume'].tail(5).mean()
        avg_dollar_vol_20d = df['dollar_volume'].tail(20).mean()
        
        # Volume trend
        vol_ratio = avg_dollar_vol_5d / avg_dollar_vol_20d if avg_dollar_vol_20d > 0 else 1
        
        # Price momentum
        price_5d = (latest['Close'] / df['Close'].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
        price_20d = (latest['Close'] / df['Close'].iloc[-21] - 1) * 100 if len(df) >= 21 else 0
        
        # Flow score (0-100)
        score = 50
        
        # 5-day flow contribution
        flow_5d_norm = flow_5d / avg_dollar_vol_20d if avg_dollar_vol_20d > 0 else 0
        if flow_5d_norm > 2:
            score += 20
        elif flow_5d_norm > 1:
            score += 10
        elif flow_5d_norm < -2:
            score -= 20
        elif flow_5d_norm < -1:
            score -= 10
        
        # Volume ratio contribution
        if vol_ratio > 1.3:
            score += 10
        elif vol_ratio > 1.1:
            score += 5
        elif vol_ratio < 0.8:
            score -= 5
        
        # Price momentum contribution
        if price_5d > 3:
            score += 10
        elif price_5d > 1:
            score += 5
        elif price_5d < -3:
            score -= 10
        elif price_5d < -1:
            score -= 5
        
        score = max(0, min(100, score))
        
        # Determine flow status
        if score >= 70:
            status = "Strong Inflow"
        elif score >= 55:
            status = "Inflow"
        elif score >= 45:
            status = "Neutral"
        elif score >= 30:
            status = "Outflow"
        else:
            status = "Strong Outflow"
        
        return {
            'date': latest['Date'],
            'close': round(latest['Close'], 2),
            'volume': int(latest['Volume']),
            'dollar_volume': round(latest['dollar_volume'] / 1e6, 2),  # In millions
            'flow_5d': round(flow_5d / 1e9, 3),  # In billions
            'flow_20d': round(flow_20d / 1e9, 3),  # In billions
            'vol_ratio': round(vol_ratio, 2),
            'price_5d': round(price_5d, 2),
            'price_20d': round(price_20d, 2),
            'flow_score': round(score, 1),
            'flow_status': status
        }
    
    def run(self) -> pd.DataFrame:
        """Analyze fund flows for all ETFs"""
        logger.info("🚀 Starting ETF Fund Flow Analysis...")

        results = []

        for ticker, (name, category) in tqdm(self.etf_list.items(), desc="Analyzing ETFs"):
            df = self.download_etf_data(ticker)

            if df.empty:
                continue

            analysis = self.calculate_flow_proxy(df)

            if analysis:
                result = {
                    'ticker': ticker,
                    'name': name,
                    'category': category,
                    **analysis
                }
                results.append(result)

        # Create DataFrame
        results_df = pd.DataFrame(results)

        # Save CSV
        results_df.to_csv(self.output_file, index=False)
        logger.info(f"✅ CSV saved: {self.output_file}")

        # Save API JSON (프론트엔드 연동용)
        sentiment = self.get_market_sentiment(results_df)
        flows_json = []
        for r in results:
            date_val = r.get('date', '')
            if hasattr(date_val, 'strftime'):
                date_val = date_val.strftime('%Y-%m-%d')
            flows_json.append({
                'ticker': r['ticker'],
                'name': r['name'],
                'category': r['category'],
                'close': r.get('close', 0),
                'flow_5d': r.get('flow_5d', 0),
                'flow_20d': r.get('flow_20d', 0),
                'flow_score': r.get('flow_score', 50),
                'flow_status': r.get('flow_status', 'Neutral'),
                'price_5d': r.get('price_5d', 0),
                'price_20d': r.get('price_20d', 0),
                'vol_ratio': r.get('vol_ratio', 1),
                'dollar_volume': r.get('dollar_volume', 0),
            })

        api_json = {
            'flows': flows_json,
            'sentiment': sentiment,
            'updated_at': datetime.now().isoformat(),
        }
        api_json_path = os.path.join(self.data_dir, 'output', 'etf_flows.json')
        with open(api_json_path, 'w', encoding='utf-8') as f:
            json.dump(api_json, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ API JSON saved: {api_json_path}")

        # Print summary by category
        logger.info("\n📊 Summary by Category:")
        for category in results_df['category'].unique():
            cat_df = results_df[results_df['category'] == category]
            avg_score = cat_df['flow_score'].mean()
            logger.info(f"   {category}: Avg Score {avg_score:.1f}")

        return results_df
    
    def generate_ai_analysis(self, results_df: pd.DataFrame) -> None:
        """Generate AI analysis for ETF flows"""
        logger.info("🤖 Generating AI analysis for ETF flows...")
        
        # Prepare data for prompt
        sentiment = self.get_market_sentiment(results_df)
        top_inflows = results_df.nlargest(5, 'flow_score')
        top_outflows = results_df.nsmallest(5, 'flow_score')
        
        inflow_text = ""
        for _, row in top_inflows.iterrows():
            inflow_text += f"- {row['ticker']} ({row['name']}): Score {row['flow_score']}\n"
            
        outflow_text = ""
        for _, row in top_outflows.iterrows():
            outflow_text += f"- {row['ticker']} ({row['name']}): Score {row['flow_score']}\n"
            
        prompt = f"""You are a professional ETF strategist. Analyze the current fund flows.

## Market Sentiment
- Overall: {sentiment['sentiment']} (Score: {sentiment['overall_score']})
- Risk-On Score: {sentiment['risk_on_score']}
- Risk-Off Score: {sentiment['risk_off_score']}

## 📈 Top Inflows (Money moving INTO)
{inflow_text}

## 📉 Top Outflows (Money moving OUT OF)
{outflow_text}

## Analysis Request
1. Interpret the rotation: What does the flow from Top Outflows to Top Inflows signify? (e.g., Rotation to Small Caps, Defensive shift, etc.)
2. Risk Sentiment: Is the market risking on or off? Why?
3. Actionable Insight: One sentence strategy.

Write in Korean (한국어). Use emojis. Be professional but concise."""

        # Call AI
        # We can reuse the macro_analyzer's method but we need to pass dummy args or create a new method?
        # MacroAIAnalyzer.analyze_macro_conditions expects specifics.
        # Let's use the internal _build_macro_prompt... wait, no.
        # We should use the base_url and api_key directly or extend the class.
        # But for simplicity, let's just call the private method style or make a direct request here?
        # NO, re-using existing logic is better. But MacroAIAnalyzer is specific to Macro.
        # Let's actually use the raw call logic here to be safe and avoid modifying macro_analyzer heavily.
        # OR, since I already verified MacroAIAnalyzer has a generic structure?
        # It has `analyze_macro_conditions`.
        
        # Let's TRY to use MacroAIAnalyzer but we need to format it to fit.
        # Actually, `analyze_macro_conditions` calls `_build_macro_prompt`.
        # It's tightly coupled.
        # It's better to implement a simple call here using the API key from env.
        
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            logger.warning("⚠️ GOOGLE_API_KEY not found, skipping AI analysis")
            return

        import requests
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent" 
        # Note: using 2.0 flash or 1.5 flash for speed/cost, or reuse 3.0? User asked for 3.0.
        # Let's use the same model as macro_analyzer: gemini-3-pro-preview if possible, or fall back to flash.
        # I'll use 1.5 flash for reliability as 3.0 is preview. User asked for 3.0 "모델 1.5를 쓰는거야 3.0 사용해달라고 했는데".
        # So I MUST use 3.0.
        
        # User requested COMPULSORY Gemini 3.0 usage
        model = "gemini-3-pro-preview"
        logger.info(f"🤖 User requested 3.0. Using {model} exclusively...")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        
        try:
            response = requests.post(
                f"{url}?key={api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 8000,
                        # Gemini 3.0 requires explicit thinking config or large token budget
                        "thinkingConfig": {
                            "thinkingLevel": "low"
                        }
                    },
                    # Safety settings to preventing blocking
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                    ]
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result_json = response.json()
                
                # Debug logging
                # logger.info(f"Debug Response: {json.dumps(result_json)[:200]}...")

                # Check for valid content
                if 'candidates' in result_json and result_json['candidates']:
                    candidate = result_json['candidates'][0]
                    if 'content' in candidate and 'parts' in candidate['content']:
                        text = candidate['content']['parts'][0]['text']
                        
                        # Add version info
                        final_text = f"**[Analysis by Gemini 3.0]**\n\n{text}"
                        
                        # Save standalone AI analysis
                        with open(self.ai_output_file, 'w', encoding='utf-8') as f:
                            json.dump({
                                'ai_analysis': final_text,
                                'timestamp': datetime.now().isoformat(),
                                'model': model
                            }, f, ensure_ascii=False)

                        # Merge into API JSON (etf_flows.json)
                        api_json_path = os.path.join(self.data_dir, 'output', 'etf_flows.json')
                        if os.path.exists(api_json_path):
                            try:
                                with open(api_json_path, 'r', encoding='utf-8') as f:
                                    api_data = json.load(f)
                                api_data['ai_analysis'] = final_text
                                with open(api_json_path, 'w', encoding='utf-8') as f:
                                    json.dump(api_data, f, ensure_ascii=False, indent=2)
                            except Exception:
                                pass

                        logger.info(f"✅ AI Analysis saved to {self.ai_output_file}")
                    else:
                        logger.error(f"❌ '{model}' response content missing. Full response: {json.dumps(result_json)}")
                else:
                    logger.error(f"❌ '{model}' candidates missing. Full response: {json.dumps(result_json)}")
            else:
                logger.error(f"❌ API Error: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"❌ Failed to generate AI analysis: {e}")

    def get_market_sentiment(self, results_df: pd.DataFrame = None) -> Dict:
        """Calculate overall market sentiment from ETF flows"""
        if results_df is None:
            if os.path.exists(self.output_file):
                results_df = pd.read_csv(self.output_file)
            else:
                return None
        
        # Broad market sentiment
        broad = results_df[results_df['category'] == 'Broad Market']
        broad_score = broad['flow_score'].mean() if not broad.empty else 50
        
        # Risk-on vs Risk-off
        # Risk-on: Tech, Discretionary, Small Cap
        risk_on_tickers = ['XLK', 'XLY', 'IWM', 'ARKK', 'TQQQ']
        risk_on = results_df[results_df['ticker'].isin(risk_on_tickers)]
        risk_on_score = risk_on['flow_score'].mean() if not risk_on.empty else 50
        
        # Risk-off: Utilities, Staples, Bonds, Gold
        risk_off_tickers = ['XLU', 'XLP', 'TLT', 'GLD']
        risk_off = results_df[results_df['ticker'].isin(risk_off_tickers)]
        risk_off_score = risk_off['flow_score'].mean() if not risk_off.empty else 50
        
        # Overall sentiment
        sentiment_score = (broad_score * 0.5 + risk_on_score * 0.3 + (100 - risk_off_score) * 0.2)
        
        if sentiment_score >= 65:
            sentiment = "Risk-On (Bullish)"
        elif sentiment_score >= 55:
            sentiment = "Slightly Bullish"
        elif sentiment_score >= 45:
            sentiment = "Neutral"
        elif sentiment_score >= 35:
            sentiment = "Slightly Bearish"
        else:
            sentiment = "Risk-Off (Bearish)"
        
        return {
            'overall_score': round(sentiment_score, 1),
            'sentiment': sentiment,
            'broad_market_score': round(broad_score, 1),
            'risk_on_score': round(risk_on_score, 1),
            'risk_off_score': round(risk_off_score, 1)
        }


def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ETF Fund Flow Analysis')
    parser.add_argument('--dir', default='.', help='Data directory')
    args = parser.parse_args()
    
    analyzer = ETFFlowAnalyzer(data_dir=args.dir)
    results = analyzer.run()
    
    # Generate AI Analysis
    analyzer.generate_ai_analysis(results)
    
    # Show market sentiment
    sentiment = analyzer.get_market_sentiment(results)
    if sentiment:
        print(f"\n🎯 Market Sentiment: {sentiment['sentiment']} (Score: {sentiment['overall_score']})")
        print(f"   Broad Market: {sentiment['broad_market_score']}")
        print(f"   Risk-On Assets: {sentiment['risk_on_score']}")
        print(f"   Risk-Off Assets: {sentiment['risk_off_score']}")
    
    # Show top inflows
    print("\n📈 Top 5 Inflows:")
    top_inflows = results.nlargest(5, 'flow_score')
    for _, row in top_inflows.iterrows():
        print(f"   {row['ticker']} ({row['name']}): Score {row['flow_score']} - {row['flow_status']}")
    
    # Show top outflows
    print("\n📉 Top 5 Outflows:")
    top_outflows = results.nsmallest(5, 'flow_score')
    for _, row in top_outflows.iterrows():
        print(f"   {row['ticker']} ({row['name']}): Score {row['flow_score']} - {row['flow_status']}")


if __name__ == "__main__":
    main()
