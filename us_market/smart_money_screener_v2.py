#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Smart Money Screener v2.0
Comprehensive analysis combining:
- Volume/Accumulation Analysis
- Technical Analysis (RSI, MACD, MA)
- Fundamental Analysis (P/E, P/B, Growth)
- Analyst Ratings
- Relative Strength vs S&P 500
"""

import os
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from tqdm import tqdm
import warnings
warnings.filterwarnings('ignore')
from data_fetcher import USStockDataFetcher

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EnhancedSmartMoneyScreener:
    """
    Enhanced screener with comprehensive analysis:
    1. Supply/Demand (volume analysis)
    2. Technical Analysis (RSI, MACD, MA)
    3. Fundamentals (valuation, growth)
    4. Analyst Ratings
    5. Relative Strength
    """
    
    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'smart_money_picks_v2.csv')

        # Initialize Hybrid Fetcher
        self.fetcher = USStockDataFetcher()

        # Load analysis data
        self.volume_df = None
        self.holdings_df = None
        self.etf_df = None
        self.prices_df = None

        # S&P 500 benchmark data
        self.spy_data = None

        # Cache for get_info calls (avoids duplicate API requests)
        self._info_cache: Dict[str, Dict] = {}
        
    def load_data(self) -> bool:
        """Load all analysis results"""
        try:
            # Volume Analysis
            vol_file = os.path.join(self.data_dir, 'output', 'us_volume_analysis.csv')
            if os.path.exists(vol_file):
                self.volume_df = pd.read_csv(vol_file)
                logger.info(f"✅ Loaded volume analysis: {len(self.volume_df)} stocks")
            else:
                logger.warning("⚠️ Volume analysis not found")
                return False
            
            # 13F Holdings (with timestamp validation to prevent look-ahead bias)
            holdings_file = os.path.join(self.data_dir, 'output', 'us_13f_holdings.csv')
            if os.path.exists(holdings_file):
                self.holdings_df = pd.read_csv(holdings_file)
                
                # PHASE 1: Look-ahead bias prevention
                # 13F filings are released 45 days after quarter end
                # Only use data that would have been publicly available
                if 'filing_date' in self.holdings_df.columns:
                    cutoff_date = datetime.now() - timedelta(days=1)  # Must be filed before today
                    original_count = len(self.holdings_df)
                    self.holdings_df['filing_date'] = pd.to_datetime(self.holdings_df['filing_date'], errors='coerce')
                    self.holdings_df = self.holdings_df[
                        self.holdings_df['filing_date'] <= cutoff_date
                    ]
                    filtered_count = original_count - len(self.holdings_df)
                    if filtered_count > 0:
                        logger.info(f"⏱️ Filtered {filtered_count} stale 13F records (look-ahead bias prevention)")
                
                logger.info(f"✅ Loaded 13F holdings: {len(self.holdings_df)} stocks (verified)")
            else:
                logger.warning("⚠️ 13F holdings not found")
                return False
            
            # ETF Flows
            etf_file = os.path.join(self.data_dir, 'output', 'us_etf_flows.csv')
            if os.path.exists(etf_file):
                self.etf_df = pd.read_csv(etf_file)
            
            # Load SPY for relative strength
            logger.info("📈 Loading SPY benchmark data...")
            self.spy_data = self.fetcher.get_history("SPY", period="3mo")
            
            # Load Sector Data (us_stocks_list.csv)
            stocks_file = os.path.join(self.data_dir, 'data', 'us_stocks_list.csv')
            if os.path.exists(stocks_file):
                self.stocks_df = pd.read_csv(stocks_file)
                logger.info(f"✅ Loaded sector info: {len(self.stocks_df)} stocks")
            else:
                logger.warning("⚠️ Sector info (us_stocks_list.csv) not found")
                self.stocks_df = None
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error loading data: {e}")
            return False
    
    def get_technical_analysis(self, ticker: str) -> Dict:
        """Calculate technical indicators"""
        try:
            hist = self.fetcher.get_history(ticker, period="1y")

            if len(hist) < 50:
                return self._default_technical()
            
            close = hist['Close']
            
            # RSI (14-day) - Using Wilder's Smoothing (alpha=1/14)
            delta = close.diff()
            
            # Note: Standard RSI uses Wilder's Smoothing, which is equivalent to EMA with alpha=1/N
            # pandas expanding or ewm can be used. ewm(alpha=1/14, adjust=False) matches Wilder's method.
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
            
            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            macd_histogram = macd - signal
            
            macd_current = macd.iloc[-1]
            signal_current = signal.iloc[-1]
            macd_hist_current = macd_histogram.iloc[-1]
            
            # Moving Averages
            ma20 = close.rolling(20).mean().iloc[-1]
            ma50 = close.rolling(50).mean().iloc[-1]
            ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else ma50
            current_price = close.iloc[-1]
            
            # MA Arrangement
            if current_price > ma20 > ma50:
                ma_signal = "Bullish"
            elif current_price < ma20 < ma50:
                ma_signal = "Bearish"
            else:
                ma_signal = "Neutral"
            
            # Golden/Death Cross
            ma50_prev = close.rolling(50).mean().iloc[-5]
            ma200_prev = close.rolling(200).mean().iloc[-5] if len(close) >= 200 else ma50_prev
            
            if ma50 > ma200 and ma50_prev <= ma200_prev:
                cross_signal = "Golden Cross"
            elif ma50 < ma200 and ma50_prev >= ma200_prev:
                cross_signal = "Death Cross"
            else:
                cross_signal = "None"
            
            # Technical Score (0-100)
            tech_score = 50
            
            # RSI contribution (smooth scoring, no cliff at boundaries)
            if current_rsi < 30:
                tech_score += 10 + int((30 - current_rsi) / 6)  # 10-15 scaled
            elif current_rsi <= 45:
                tech_score += 10  # Oversold-to-neutral zone
            elif current_rsi <= 60:
                tech_score += 8   # Neutral zone
            elif current_rsi <= 70:
                tech_score += 2   # Getting warm
            else:
                tech_score -= 5   # Overbought
            
            # MACD contribution
            if macd_hist_current > 0 and macd_histogram.iloc[-2] < 0:
                tech_score += 15  # Bullish crossover
            elif macd_hist_current > 0:
                tech_score += 8
            elif macd_hist_current < 0:
                tech_score -= 5
            
            # MA contribution
            if ma_signal == "Bullish":
                tech_score += 15
            elif ma_signal == "Bearish":
                tech_score -= 10
            
            if cross_signal == "Golden Cross":
                tech_score += 10
            elif cross_signal == "Death Cross":
                tech_score -= 15
            
            tech_score = max(0, min(100, tech_score))
            
            return {
                'rsi': round(current_rsi, 1),
                'macd': round(macd_current, 3),
                'macd_signal': round(signal_current, 3),
                'macd_histogram': round(macd_hist_current, 3),
                'ma20': round(ma20, 2),
                'ma50': round(ma50, 2),
                'ma_signal': ma_signal,
                'cross_signal': cross_signal,
                'technical_score': tech_score
            }
            
        except Exception as e:
            return self._default_technical()
    
    def _default_technical(self) -> Dict:
        return {
            'rsi': 50, 'macd': 0, 'macd_signal': 0, 'macd_histogram': 0,
            'ma20': 0, 'ma50': 0, 'ma_signal': 'Unknown', 'cross_signal': 'None',
            'technical_score': 50
        }
    
    def _get_info_cached(self, ticker: str) -> Dict:
        """Return cached info dict, fetch once per ticker"""
        if ticker not in self._info_cache:
            self._info_cache[ticker] = self.fetcher.get_info(ticker)
        return self._info_cache[ticker]

    def get_fundamental_analysis(self, ticker: str) -> Dict:
        """Get fundamental/valuation metrics"""
        try:
            info = self._get_info_cached(ticker)
            
            # Valuation
            pe_ratio = info.get('trailingPE', 0) or 0
            forward_pe = info.get('forwardPE', 0) or 0
            pb_ratio = info.get('priceToBook', 0) or 0
            ps_ratio = info.get('priceToSalesTrailing12Months', 0) or 0
            
            # Growth
            revenue_growth = info.get('revenueGrowth', 0) or 0
            earnings_growth = info.get('earningsGrowth', 0) or 0
            
            # Profitability
            profit_margin = info.get('profitMargins', 0) or 0
            roe = info.get('returnOnEquity', 0) or 0
            
            # Market Cap
            market_cap = info.get('marketCap', 0) or 0
            
            # Dividend
            dividend_yield = info.get('dividendYield', 0) or 0
            
            # Fundamental Score (0-100)
            fund_score = 50
            
            # P/E contribution (lower is better, but not too low)
            if 0 < pe_ratio < 15:
                fund_score += 15
            elif 15 <= pe_ratio < 25:
                fund_score += 10
            elif pe_ratio > 40:
                fund_score -= 10
            elif pe_ratio < 0:  # Negative earnings
                fund_score -= 15
            
            # Growth contribution
            if revenue_growth > 0.2:
                fund_score += 15
            elif revenue_growth > 0.1:
                fund_score += 10
            elif revenue_growth > 0:
                fund_score += 5
            elif revenue_growth < 0:
                fund_score -= 10
            
            # ROE contribution
            if roe > 0.2:
                fund_score += 10
            elif roe > 0.1:
                fund_score += 5
            elif roe < 0:
                fund_score -= 10
            
            fund_score = max(0, min(100, fund_score))
            
            # Size category
            if market_cap > 200e9:
                size = "Mega Cap"
            elif market_cap > 10e9:
                size = "Large Cap"
            elif market_cap > 2e9:
                size = "Mid Cap"
            elif market_cap > 300e6:
                size = "Small Cap"
            else:
                size = "Micro Cap"
            
            return {
                'pe_ratio': round(pe_ratio, 2) if pe_ratio else 'N/A',
                'forward_pe': round(forward_pe, 2) if forward_pe else 'N/A',
                'pb_ratio': round(pb_ratio, 2) if pb_ratio else 'N/A',
                'revenue_growth': round(revenue_growth * 100, 1) if revenue_growth else 0,
                'earnings_growth': round(earnings_growth * 100, 1) if earnings_growth else 0,
                'profit_margin': round(profit_margin * 100, 1) if profit_margin else 0,
                'roe': round(roe * 100, 1) if roe else 0,
                'market_cap_b': round(market_cap / 1e9, 1),
                'size': size,
                'dividend_yield': round(dividend_yield * 100, 2) if dividend_yield else 0,
                'fundamental_score': fund_score
            }
            
        except Exception as e:
            return self._default_fundamental()
    
    def _default_fundamental(self) -> Dict:
        return {
            'pe_ratio': 'N/A', 'forward_pe': 'N/A', 'pb_ratio': 'N/A',
            'revenue_growth': 0, 'earnings_growth': 0, 'profit_margin': 0,
            'roe': 0, 'market_cap_b': 0, 'size': 'Unknown', 'dividend_yield': 0,
            'fundamental_score': 50
        }
    
    def get_analyst_ratings(self, ticker: str) -> Dict:
        """Get analyst consensus, target price, and next events"""
        try:
            info = self._get_info_cached(ticker)
            
            # Get company name
            company_name = info.get('longName', '') or info.get('shortName', '') or ticker
            
            current_price = info.get('currentPrice', 0) or info.get('regularMarketPrice', 0) or 0
            target_price = info.get('targetMeanPrice', 0) or 0
            target_high = info.get('targetHighPrice', 0) or 0
            target_low = info.get('targetLowPrice', 0) or 0
            
            # Recommendation
            recommendation = info.get('recommendationKey', 'none')
            num_analysts = info.get('numberOfAnalystOpinions', 0) or 0
            
            # Upside potential
            if current_price > 0 and target_price > 0:
                upside = ((target_price / current_price) - 1) * 100
            else:
                upside = 0
            
            # Get next earnings date
            next_earnings_date = None
            days_to_earnings = None
            try:
                calendar = self.fetcher.get_calendar(ticker)
                if calendar and isinstance(calendar, dict):
                    dates = calendar.get('Earnings Date', [])
                    if dates:
                        next_date = dates[0]
                        next_earnings_date = next_date.strftime('%Y-%m-%d')
                        days_to_earnings = (next_date - datetime.now()).days
            except:
                pass
            
            # Analyst Score (0-100)
            analyst_score = 50
            
            # Recommendation contribution
            rec_map = {
                'strongBuy': 25,
                'buy': 20,
                'hold': 0,
                'sell': -15,
                'strongSell': -25
            }
            analyst_score += rec_map.get(recommendation, 0)
            
            # Upside contribution
            if upside > 30:
                analyst_score += 20
            elif upside > 20:
                analyst_score += 15
            elif upside > 10:
                analyst_score += 10
            elif upside > 0:
                analyst_score += 5
            elif upside < -10:
                analyst_score -= 15
            
            # Analyst coverage boost
            if num_analysts > 20:
                analyst_score += 5
            elif num_analysts > 10:
                analyst_score += 3
            
            analyst_score = max(0, min(100, analyst_score))
            
            return {
                'company_name': company_name,
                'current_price': round(current_price, 2),
                'target_price': round(target_price, 2) if target_price else 'N/A',
                'target_high': round(target_high, 2) if target_high else 'N/A',
                'target_low': round(target_low, 2) if target_low else 'N/A',
                'upside_pct': round(upside, 1),
                'recommendation': recommendation,
                'num_analysts': num_analysts,
                'analyst_score': analyst_score,
                'next_earnings_date': next_earnings_date,
                'days_to_earnings': days_to_earnings
            }
            
        except Exception as e:
            return self._default_analyst()
    
    def _default_analyst(self) -> Dict:
        return {
            'company_name': '',
            'current_price': 0, 'target_price': 'N/A', 'target_high': 'N/A',
            'target_low': 'N/A', 'upside_pct': 0, 'recommendation': 'none',
            'num_analysts': 0, 'analyst_score': 50,
            'next_earnings_date': None, 'days_to_earnings': None
        }
    
    def get_relative_strength(self, ticker: str) -> Dict:
        """Calculate relative strength vs S&P 500"""
        try:
            if self.spy_data is None or len(self.spy_data) < 20:
                return {'rs_20d': 0, 'rs_60d': 0, 'rs_score': 50}
            
            hist = self.fetcher.get_history(ticker, period="3mo")
            
            if len(hist) < 20:
                return {'rs_20d': 0, 'rs_60d': 0, 'rs_score': 50}
            
            # Calculate returns
            stock_return_20d = (hist['Close'].iloc[-1] / hist['Close'].iloc[-21] - 1) * 100 if len(hist) >= 21 else 0
            stock_return_60d = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
            
            spy_return_20d = (self.spy_data['Close'].iloc[-1] / self.spy_data['Close'].iloc[-21] - 1) * 100 if len(self.spy_data) >= 21 else 0
            spy_return_60d = (self.spy_data['Close'].iloc[-1] / self.spy_data['Close'].iloc[0] - 1) * 100
            
            rs_20d = stock_return_20d - spy_return_20d
            rs_60d = stock_return_60d - spy_return_60d
            
            # RS Score (0-100)
            rs_score = 50
            
            if rs_20d > 10:
                rs_score += 25
            elif rs_20d > 5:
                rs_score += 15
            elif rs_20d > 0:
                rs_score += 8
            elif rs_20d < -10:
                rs_score -= 20
            elif rs_20d < -5:
                rs_score -= 10
            
            if rs_60d > 15:
                rs_score += 15
            elif rs_60d > 5:
                rs_score += 8
            elif rs_60d < -15:
                rs_score -= 15
            
            rs_score = max(0, min(100, rs_score))
            
            return {
                'stock_return_20d': round(stock_return_20d, 1),
                'spy_return_20d': round(spy_return_20d, 1),
                'rs_20d': round(rs_20d, 1),
                'rs_60d': round(rs_60d, 1),
                'rs_score': rs_score
            }
            
        except Exception as e:
            return {'rs_20d': 0, 'rs_60d': 0, 'rs_score': 50}

    def calculate_swing_trend_scores(self, row: pd.Series, tech: Dict, fund: Dict, analyst: Dict, rs: Dict) -> Dict:
        """
        Phase 2: Dual Scoring Logic
        
        1. Swing Score (Short-term Momentum)
           - Technical (40%): RSI, MACD, BB
           - Volume (30%): Supply/Demand Score
           - Catalyst (20%): Analyst Revisions, Earnings
           - Fundamental (10%): Safety check
           
        2. Trend Score (Mid-term Growth)
           - Institutional (35%): Holdings pct
           - Fundamental (35%): Growth, PE
           - Technical Trend (20%): MA Alignment
           - Analyst (10%): Target Upside
        """
        # 1. Swing Score Calculation (Momentum & Volatility)
        # Drivers: Volume (40%) + Technical (30%) + Relative Strength (30%)
        # NaN-safe: pd.Series.get() returns NaN if value exists but is NaN
        def safe_val(val, default=50):
            return default if val is None or (isinstance(val, float) and np.isnan(val)) else val

        swing_vol = safe_val(row.get('score_supply_demand_score_norm', row.get('supply_demand_score', 50)))
        swing_tech = tech.get('technical_score', 50)
        swing_rs = rs.get('rs_score', 50)
        
        swing_score = (
            swing_vol * 0.40 +
            swing_tech * 0.30 +
            swing_rs * 0.30
        )
        
        # 2. Trend Score Calculation (Quality & Consistency)
        # Drivers: Institutional (35%) + Fundamental (35%) + Technical (30%)
        trend_inst = safe_val(row.get('score_inst_pct_norm', row.get('institutional_score', 50)))
        trend_fund = fund.get('fundamental_score', 50)
        trend_tech = tech.get('technical_score', 50)
        
        trend_score = (
            trend_inst * 0.35 +
            trend_fund * 0.35 +
            trend_tech * 0.30
        )
        
        return {
            'swing_score': round(swing_score, 1),
            'trend_score': round(trend_score, 1)
        }

    def determine_setup_type(self, tech: Dict, row: pd.Series) -> str:
        """
        Classify stock setup: Breakout, Pullback, Base, Parabolic, or Neutral
        """
        rsi = tech.get('rsi', 50)
        ma_signal = tech.get('ma_signal', 'Neutral') # Bullish/Bearish
        bb_width = tech.get('bb_width', 0) # Volatility needed? Assuming we have price action info
        
        # We need recent price action for precise setup classification
        # Using simplified logic based on available metrics
        
        if rsi > 80:
            return "🎢 Parabolic (Overheated)"
            
        if ma_signal == 'Bullish':
            if 40 <= rsi <= 60:
                return "📉 Pullback (Buy Dip)"
            elif rsi > 60:
                return "🚀 Breakout / Momentum"
                
        if ma_signal == 'Bearish':
            return "🐻 Downtrend"
            
        return "⚖️ Base / Neutral"
    
    def calculate_composite_score(self, row: pd.Series, tech: Dict, fund: Dict, analyst: Dict, rs: Dict) -> Tuple[float, str]:
        """
        Calculate final composite score
        
        Weights:
        - Supply/Demand (Volume): 25%
        - Institutional: 20%
        - Technical: 20%
        - Fundamental: 15%
        - Analyst: 10%
        - Relative Strength: 10%
        """
        # NaN-safe value helper
        def safe_val(val, default=50):
            return default if val is None or (isinstance(val, float) and np.isnan(val)) else val

        # Volume/Supply-Demand Score (Use Normalized fairness score if available)
        vol_score = safe_val(row.get('score_supply_demand_score_norm', row.get('supply_demand_score', 50)))

        # Institutional Score (Use Normalized fairness score if available)
        inst_score = safe_val(row.get('score_inst_pct_norm', row.get('institutional_score', 50)))
        
        # Get sub-scores
        tech_score = tech.get('technical_score', 50)
        fund_score = fund.get('fundamental_score', 50)
        analyst_score = analyst.get('analyst_score', 50)
        rs_score = rs.get('rs_score', 50)
        
        # Weighted composite
        composite = (
            vol_score * 0.25 +
            inst_score * 0.20 +
            tech_score * 0.20 +
            fund_score * 0.15 +
            analyst_score * 0.10 +
            rs_score * 0.10
        )
        
        # Determine grade
        if composite >= 80:
            grade = "🔥 S급 (즉시 매수)"
        elif composite >= 70:
            grade = "🌟 A급 (적극 매수)"
        elif composite >= 60:
            grade = "📈 B급 (매수 고려)"
        elif composite >= 50:
            grade = "📊 C급 (관망)"
        elif composite >= 40:
            grade = "⚠️ D급 (주의)"
        else:
            grade = "🚫 F급 (회피)"
        
        return round(composite, 1), grade
    
    def calculate_sector_z_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Phase 1: Calculate Z-Scores for fairness across sectors
        
        Normalizes:
        - supply_demand_score (Volume)
        - inst_pct (Institutional Ownership)
        - net_buying_amt (Institutional Flow)
        """
        if 'sector' not in df.columns:
            return df
            
        logger.info("⚖️ Calculating Sector Z-Scores for fairness...")
        
        # metrics to normalize
        metrics = ['supply_demand_score', 'inst_pct', 'net_buying_amt']
        
        for metric in metrics:
            if metric not in df.columns:
                continue
                
            # Create Z-score column
            z_col = f'z_{metric}'
            
            # Calculate mean/std per sector
            df[z_col] = df.groupby('sector')[metric].transform(
                lambda x: (x - x.mean()) / x.std()
            )
            
            # Init 0 for NaN (single stock sectors)
            df[z_col] = df[z_col].fillna(0)
            
            # Clip outliers (-3 to +3)
            df[z_col] = df[z_col].clip(-3, 3)
            
            # Map to 0-100 scale
            # Z=-3 -> 0, Z=0 -> 50, Z=+3 -> 100
            # Formula: (Z + 3) / 6 * 100
            score_col = f'score_{metric}_norm'
            df[score_col] = (df[z_col] + 3) / 6 * 100
            
        return df

    def run_screening(self, top_n: int = 50) -> pd.DataFrame:
        """Run enhanced screening"""
        logger.info("🔍 Running Enhanced Smart Money Screening...")
        
        # Merge volume and holdings data
        merged_df = pd.merge(
            self.volume_df,
            self.holdings_df,
            on='ticker',
            how='inner' # Only stocks with both volume and 13F data
        )
        
        # Merge Sector info if available
        if self.stocks_df is not None:
            merged_df = pd.merge(
                merged_df,
                self.stocks_df[['ticker', 'sector']],
                on='ticker',
                how='left'
            )
        else:
            merged_df['sector'] = 'Unknown'
        
        # Phase 1: Apply Z-Score Normalization
        merged_df = self.calculate_sector_z_scores(merged_df)


        
        # Pre-filter: Focus on accumulation candidates
        filtered = merged_df[
            merged_df['supply_demand_score'] >= 50
        ]
        
        logger.info(f"📊 Pre-filtered to {len(filtered)} candidates (from {len(merged_df)})")
        
        results = []
        
        for idx, row in tqdm(filtered.iterrows(), total=len(filtered), desc="Enhanced Screening"):
            ticker = row['ticker']
            
            # Get all analyses
            tech = self.get_technical_analysis(ticker)
            fund = self.get_fundamental_analysis(ticker)
            analyst = self.get_analyst_ratings(ticker)
            rs = self.get_relative_strength(ticker)
            
            # Calculate composite score
            composite_score, grade = self.calculate_composite_score(row, tech, fund, analyst, rs)
            
            # Phase 2: Dual Scoring & Setup
            dual_scores = self.calculate_swing_trend_scores(row, tech, fund, analyst, rs)
            setup_type = self.determine_setup_type(tech, row)
            
            # Determine Strategy Type
            s_score = dual_scores['swing_score']
            t_score = dual_scores['trend_score']
            
            if s_score >= 75 and t_score >= 75:
                strategy_type = "Hybrid 🌟"
            elif s_score > t_score:
                strategy_type = "Swing 🚀"
            else:
                strategy_type = "Trend 📈"
            
            result = {
                'ticker': ticker,
                'name': analyst.get('company_name', ticker),
                'composite_score': composite_score,
                'grade': grade,
                'strategy_type': strategy_type,
                
                # Phase 2: New Fields
                'swing_score': s_score,
                'trend_score': t_score,
                'setup_type': setup_type,
                
                # Supply/Demand
                'sd_score': row.get('supply_demand_score', 50),
                'sd_stage': row.get('supply_demand_stage', 'Unknown'),
                
                # Institutional
                'inst_score': row.get('institutional_score', 50),
                'inst_pct': row.get('institutional_pct', 0),
                'insider': row.get('insider_sentiment', 'Unknown'),
                
                # Technical
                'tech_score': tech['technical_score'],
                'rsi': tech['rsi'],
                'macd_hist': tech['macd_histogram'],
                'ma_signal': tech['ma_signal'],
                
                # Fundamental
                'fund_score': fund['fundamental_score'],
                'pe': fund['pe_ratio'],
                'revenue_growth': fund['revenue_growth'],
                'size': fund['size'],
                
                # Analyst
                'analyst_score': analyst['analyst_score'],
                'target_upside': analyst['upside_pct'],
                'recommendation': analyst['recommendation'],
                
                # Relative Strength
                'rs_score': rs['rs_score'],
                'rs_vs_spy_20d': rs.get('rs_20d', 0),
                
                # Price
                'current_price': analyst['current_price'],
                
                # Sector
                'sector': row.get('sector', 'Unknown'),

                # Next Events
                'next_earnings': analyst.get('next_earnings_date', ''),
                'days_to_earnings': analyst.get('days_to_earnings', None),
            }
            results.append(result)
        
        # Create DataFrame and sort
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values('composite_score', ascending=False)
        results_df['rank'] = range(1, len(results_df) + 1)
        
        return results_df
    
    def run(self, top_n: int = 50) -> pd.DataFrame:
        """Main execution"""
        logger.info("🚀 Starting Enhanced Smart Money Screener v2.0...")
        
        if not self.load_data():
            logger.error("❌ Failed to load data")
            return pd.DataFrame()
        
        results_df = self.run_screening(top_n)
        
        # Save results (Overwrite current top picks)
        results_df.to_csv(self.output_file, index=False)
        logger.info(f"✅ Saved to {self.output_file}")
        
        # Archive results (Append-only history)
        archive_dir = os.path.join(self.data_dir, 'archive')
        os.makedirs(archive_dir, exist_ok=True)
        
        today = datetime.now().strftime('%Y%m%d')
        archive_file = os.path.join(archive_dir, f'picks_{today}.csv')
        results_df.to_csv(archive_file, index=False)
        logger.info(f"📜 Archived to {archive_file}")
        
        # Summary
        logger.info("\n📊 Grade Distribution:")
        for grade in results_df['grade'].unique():
            count = len(results_df[results_df['grade'] == grade])
            logger.info(f"   {grade}: {count} stocks")
        
        return results_df


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Smart Money Screener v2.0')
    parser.add_argument('--dir', default='.', help='Data directory')
    parser.add_argument('--top', type=int, default=20, help='Top picks to show')
    args = parser.parse_args()
    
    screener = EnhancedSmartMoneyScreener(data_dir=args.dir)
    results = screener.run(top_n=args.top)
    
    if results.empty:
        print("❌ No results")
        return
    
    # Display top picks
    print(f"\n{'='*120}")
    print(f"🔥 TOP {args.top} ENHANCED SMART MONEY PICKS")
    print(f"{'='*120}")
    
    for _, row in results.head(args.top).iterrows():
        print(f"\n#{row['rank']} {row['ticker']} | {row['grade']} | 종합 {row['composite_score']}/100")
        print(f"   🎯 Strategy: {row['strategy_type']} (Swing {row['swing_score']} vs Trend {row['trend_score']})")
        print(f"   💰 Price: ${row['current_price']:.2f} | Target Upside: {row['target_upside']:+.1f}%")
        print(f"   📊 수급: {row['sd_score']}/100 ({row['sd_stage']})")
        print(f"   🏦 기관: {row['inst_score']}/100 (보유 {row['inst_pct']:.1f}%, Insider: {row['insider']})")
        print(f"   📈 기술: {row['tech_score']}/100 (RSI {row['rsi']}, MA: {row['ma_signal']})")
        print(f"   💵 펀더멘털: {row['fund_score']}/100 (P/E: {row['pe']}, 매출성장: {row['revenue_growth']}%)")
        print(f"   💪 상대강도: {row['rs_score']}/100 (vs SPY: {row['rs_vs_spy_20d']:+.1f}%)")
    
    # Show S-grade picks
    s_grade = results[results['grade'].str.contains('S급')]
    if not s_grade.empty:
        print(f"\n{'='*120}")
        print(f"🔥 S급 종목 ({len(s_grade)}개): {', '.join(s_grade['ticker'].tolist())}")


if __name__ == "__main__":
    main()
