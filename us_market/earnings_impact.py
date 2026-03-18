#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Earnings Surprise Impact Model v1.0
- Tracks post-earnings price reactions by sector
- Integrates options implied moves
- Generates positioning signals for upcoming earnings
"""

import os
import json
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EarningsImpactModel:
    """Analyze earnings surprise impact and generate positioning signals"""

    SECTOR_MAP = {
        'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'AVGO': 'Technology',
        'GOOGL': 'Technology', 'META': 'Technology', 'AMD': 'Technology', 'CRM': 'Technology',
        'ORCL': 'Technology', 'ADBE': 'Technology', 'CSCO': 'Technology', 'INTC': 'Technology',
        'JPM': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials',
        'V': 'Financials', 'MA': 'Financials', 'MS': 'Financials',
        'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'PFE': 'Healthcare',
        'ABBV': 'Healthcare', 'MRK': 'Healthcare', 'TMO': 'Healthcare',
        'AMZN': 'Consumer Disc.', 'TSLA': 'Consumer Disc.', 'HD': 'Consumer Disc.',
        'MCD': 'Consumer Disc.', 'NKE': 'Consumer Disc.', 'LOW': 'Consumer Disc.',
        'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
        'WMT': 'Consumer Staples', 'PG': 'Consumer Staples', 'KO': 'Consumer Staples',
        'PEP': 'Consumer Staples', 'COST': 'Consumer Staples',
        'CAT': 'Industrials', 'GE': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
        'NFLX': 'Comm. Services', 'DIS': 'Comm. Services', 'T': 'Comm. Services',
    }

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'earnings_impact.json')

    def get_historical_reactions(self, ticker: str, lookback_quarters: int = 8) -> List[Dict]:
        """For each past earnings date: inferred surprise direction, 1d/5d price reaction.

        Uses get_earnings_dates() (reliable) + price history instead of the
        broken earnings_history attribute.
        """
        reactions = []

        try:
            stock = yf.Ticker(ticker)

            # get_earnings_dates returns past + future dates
            try:
                earnings_dates = stock.get_earnings_dates(limit=lookback_quarters + 4)
                if earnings_dates is None or earnings_dates.empty:
                    return reactions
            except Exception:
                return reactions

            # Get 2 years of price data
            hist = stock.history(period='2y')
            if hist.empty or len(hist) < 10:
                return reactions

            trading_dates = hist.index.tz_localize(None) if hist.index.tz else hist.index

            # Only look at past earnings dates
            now = pd.Timestamp.now()
            count = 0

            for idx in earnings_dates.index:
                if count >= lookback_quarters:
                    break

                try:
                    date = pd.Timestamp(idx).tz_localize(None) if hasattr(idx, 'tz_localize') else pd.Timestamp(idx)
                    if date >= now:
                        continue  # Skip future dates

                    # Find nearest trading day on or after earnings date
                    mask = trading_dates >= date
                    if mask.sum() < 6:
                        continue

                    earnings_idx = trading_dates[mask][0]
                    pos = trading_dates.get_loc(earnings_idx)

                    if pos < 1 or pos + 5 >= len(trading_dates):
                        continue

                    # pre_price = close on the day before the earnings trading day
                    # day0_price = close on the earnings trading day (captures gap)
                    # day1_price = close on T+1
                    pre_price = float(hist['Close'].iloc[pos - 1])
                    day0_price = float(hist['Close'].iloc[pos])
                    day1_price = float(hist['Close'].iloc[pos + 1]) if pos + 1 < len(hist) else day0_price
                    day5_price = float(hist['Close'].iloc[min(pos + 5, len(hist) - 1)])

                    # Earnings-day gap (pre → close of earnings day)
                    reaction_gap = ((day0_price / pre_price) - 1) * 100
                    reaction_1d = ((day1_price / pre_price) - 1) * 100
                    reaction_5d = ((day5_price / pre_price) - 1) * 100

                    # Label: "positive reaction" vs "negative reaction"
                    # (NOT "beat"/"miss" — reaction is a proxy, not actual EPS surprise)
                    if reaction_gap > 0.5:
                        surprise_pct = round(reaction_gap * 0.5, 2)
                    elif reaction_gap < -0.5:
                        surprise_pct = round(reaction_gap * 0.5, 2)
                    else:
                        surprise_pct = 0.0

                    reactions.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'surprise_pct': surprise_pct,
                        'reaction_1d': round(reaction_1d, 2),
                        'reaction_5d': round(reaction_5d, 2),
                    })
                    count += 1

                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Error getting reactions for {ticker}: {e}")

        return reactions

    def calculate_sector_reaction_profile(self, tickers: List[str] = None) -> Dict:
        """Aggregate per sector: avg positive/negative reaction, positive reaction rate.
        Note: 'beat' here means positive price reaction, not actual EPS surprise."""
        logger.info("📊 Calculating sector reaction profiles...")

        if tickers is None:
            tickers = list(self.SECTOR_MAP.keys())[:30]

        sector_data = {}

        for ticker in tickers:
            sector = self.SECTOR_MAP.get(ticker, 'Other')
            reactions = self.get_historical_reactions(ticker, lookback_quarters=4)

            if not reactions:
                continue

            if sector not in sector_data:
                sector_data[sector] = {'beat_reactions_1d': [], 'miss_reactions_1d': [],
                                       'beat_reactions_5d': [], 'miss_reactions_5d': [],
                                       'total': 0, 'beats': 0}

            for r in reactions:
                sector_data[sector]['total'] += 1
                if r['surprise_pct'] > 0:
                    sector_data[sector]['beats'] += 1
                    sector_data[sector]['beat_reactions_1d'].append(r['reaction_1d'])
                    sector_data[sector]['beat_reactions_5d'].append(r['reaction_5d'])
                else:
                    sector_data[sector]['miss_reactions_1d'].append(r['reaction_1d'])
                    sector_data[sector]['miss_reactions_5d'].append(r['reaction_5d'])

        profiles = {}
        for sector, data in sector_data.items():
            profiles[sector] = {
                'avg_beat_reaction_1d': round(np.mean(data['beat_reactions_1d']), 2) if data['beat_reactions_1d'] else 0,
                'avg_miss_reaction_1d': round(np.mean(data['miss_reactions_1d']), 2) if data['miss_reactions_1d'] else 0,
                'avg_beat_reaction_5d': round(np.mean(data['beat_reactions_5d']), 2) if data['beat_reactions_5d'] else 0,
                'avg_miss_reaction_5d': round(np.mean(data['miss_reactions_5d']), 2) if data['miss_reactions_5d'] else 0,
                'beat_rate': round(data['beats'] / max(data['total'], 1) * 100, 1),
                'sample_size': data['total'],
            }

        return profiles

    def get_implied_move(self, ticker: str) -> Optional[Dict]:
        """ATM straddle price from yfinance options chain -> implied move %"""
        try:
            stock = yf.Ticker(ticker)
            current_price = stock.history(period='1d')['Close'].iloc[-1]

            # Get nearest expiration
            expirations = stock.options
            if not expirations:
                return None

            # Find nearest expiration that is at least 1 day away
            nearest_exp = None
            today = datetime.now().strftime('%Y-%m-%d')
            for exp in expirations:
                if exp > today:
                    nearest_exp = exp
                    break
            if nearest_exp is None:
                nearest_exp = expirations[0]
            chain = stock.option_chain(nearest_exp)

            calls = chain.calls
            puts = chain.puts

            if calls.empty or puts.empty:
                return None

            # Find ATM options (closest strike to current price)
            atm_strike = calls.iloc[(calls['strike'] - current_price).abs().argsort()[:1]]['strike'].values[0]

            atm_call = calls[calls['strike'] == atm_strike].iloc[0]
            atm_put = puts[puts['strike'] == atm_strike].iloc[0]

            # ATM straddle price: prefer bid/ask midpoint for accuracy
            call_bid = atm_call.get('bid', 0) or 0
            call_ask = atm_call.get('ask', 0) or 0
            put_bid = atm_put.get('bid', 0) or 0
            put_ask = atm_put.get('ask', 0) or 0
            # Fall back to lastPrice if bid/ask unavailable
            call_price = (call_bid + call_ask) / 2 if call_bid > 0 and call_ask > 0 else (atm_call.get('lastPrice', 0) or 0)
            put_price = (put_bid + put_ask) / 2 if put_bid > 0 and put_ask > 0 else (atm_put.get('lastPrice', 0) or 0)
            straddle_price = call_price + put_price

            implied_move_pct = (straddle_price / current_price) * 100

            return {
                'implied_move_pct': round(implied_move_pct, 2),
                'straddle_price': round(straddle_price, 2),
                'current_price': round(float(current_price), 2),
                'expiration': nearest_exp,
                'atm_strike': round(float(atm_strike), 2),
                'call_iv': round(float(atm_call.get('impliedVolatility', 0)) * 100, 1),
                'put_iv': round(float(atm_put.get('impliedVolatility', 0)) * 100, 1),
            }

        except Exception as e:
            logger.debug(f"Implied move error for {ticker}: {e}")
            return None

    def generate_positioning_signal(self, ticker: str, sector: str,
                                     reactions: List[Dict],
                                     implied_move: Optional[Dict],
                                     sector_profiles: Dict) -> Dict:
        """Combine historical + implied to produce signal"""
        # Default neutral
        signal = 'neutral'
        confidence = 50
        edge_estimate = 0

        sector_profile = sector_profiles.get(sector, {})
        beat_rate = sector_profile.get('beat_rate', 50)
        avg_beat_1d = sector_profile.get('avg_beat_reaction_1d', 0)
        avg_miss_1d = sector_profile.get('avg_miss_reaction_1d', 0)

        # Historical reaction average for this stock
        if reactions:
            avg_reaction = np.mean([r['reaction_1d'] for r in reactions])
            stock_beat_rate = len([r for r in reactions if r['surprise_pct'] > 0]) / len(reactions) * 100
        else:
            avg_reaction = 0
            stock_beat_rate = beat_rate

        # Implied move comparison
        implied_pct = implied_move.get('implied_move_pct', 0) if implied_move else 0
        historical_avg_move = np.mean([abs(r['reaction_1d']) for r in reactions]) if reactions else 0

        # Signal logic
        if stock_beat_rate >= 70 and avg_reaction > 1:
            signal = 'bullish_lean'
            confidence = min(85, int(50 + stock_beat_rate * 0.3 + avg_reaction * 2))
        elif stock_beat_rate <= 40 and avg_reaction < -1:
            signal = 'bearish_lean'
            confidence = min(85, int(50 + (100 - stock_beat_rate) * 0.3 + abs(avg_reaction) * 2))
        else:
            confidence = 50

        # Edge estimate: if implied > historical, options are overpriced
        if implied_pct > 0 and historical_avg_move > 0:
            edge_estimate = round(historical_avg_move - implied_pct, 2)

        return {
            'signal': signal,
            'confidence': min(confidence, 95),
            'edge_estimate': edge_estimate,
            'stock_beat_rate': round(stock_beat_rate, 1),
            'historical_avg_move': round(historical_avg_move, 2),
        }

    def analyze_upcoming_earnings(self) -> Dict:
        """For all tickers with earnings in next 14 days"""
        logger.info("📅 Analyzing upcoming earnings...")

        # Load tickers from picks or use default watchlist
        tickers = []
        picks_path = os.path.join(self.data_dir, 'output', 'smart_money_picks_v2.csv')
        if os.path.exists(picks_path):
            try:
                df = pd.read_csv(picks_path)
                tickers = df['ticker'].tolist()[:30]
            except Exception:
                pass

        if not tickers:
            tickers = list(self.SECTOR_MAP.keys())[:20]

        # Also load earnings analysis for upcoming dates
        earnings_path = os.path.join(self.data_dir, 'output', 'earnings_analysis.json')
        if os.path.exists(earnings_path):
            try:
                with open(earnings_path, 'r') as f:
                    earnings_data = json.load(f)
                upcoming = earnings_data.get('upcoming_earnings', [])
                for item in upcoming:
                    if item['ticker'] not in tickers:
                        tickers.append(item['ticker'])
            except Exception:
                pass

        # Get sector profiles (use a smaller sample for speed)
        sample_tickers = list(self.SECTOR_MAP.keys())[:15]
        sector_profiles = self.calculate_sector_reaction_profile(sample_tickers)

        upcoming_analyses = []

        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)

                # Check if earnings are within 14 days
                calendar = stock.calendar
                next_date_str = None

                if calendar and isinstance(calendar, dict):
                    dates = calendar.get('Earnings Date', [])
                    if dates:
                        next_date = dates[0]
                        if hasattr(next_date, 'strftime'):
                            next_date_str = next_date.strftime('%Y-%m-%d')
                            days_until = (next_date - datetime.now()).days
                        else:
                            continue
                    else:
                        continue
                else:
                    continue

                if days_until < 0 or days_until > 14:
                    continue

                sector = self.SECTOR_MAP.get(ticker, 'Other')
                reactions = self.get_historical_reactions(ticker, lookback_quarters=4)
                implied_move = self.get_implied_move(ticker)
                positioning = self.generate_positioning_signal(
                    ticker, sector, reactions, implied_move, sector_profiles
                )

                analysis = {
                    'ticker': ticker,
                    'sector': sector,
                    'earnings_date': next_date_str,
                    'days_until': days_until,
                    'signal': positioning['signal'],
                    'confidence': positioning['confidence'],
                    'edge_estimate': positioning['edge_estimate'],
                    'implied_move_pct': implied_move.get('implied_move_pct', 0) if implied_move else None,
                    'historical_avg_move': positioning['historical_avg_move'],
                    'stock_beat_rate': positioning['stock_beat_rate'],
                    'historical_reactions': reactions[:4],
                    'recommendation_ko': self._get_recommendation_ko(positioning),
                    'recommendation_en': self._get_recommendation_en(positioning),
                }

                upcoming_analyses.append(analysis)

            except Exception as e:
                logger.debug(f"Error analyzing {ticker}: {e}")
                continue

        # Sort by days until earnings
        upcoming_analyses.sort(key=lambda x: x['days_until'])

        return {
            'timestamp': datetime.now().isoformat(),
            'sector_profiles': sector_profiles,
            'upcoming_earnings': upcoming_analyses,
        }

    def _get_recommendation_ko(self, positioning: Dict) -> str:
        signal = positioning['signal']
        conf = positioning['confidence']
        if signal == 'bullish_lean':
            return f"과거 실적 서프라이즈 비율 높음 (신뢰도 {conf}%). 실적 발표 전 매수 포지션 고려."
        elif signal == 'bearish_lean':
            return f"과거 실적 미스 가능성 높음 (신뢰도 {conf}%). 실적 발표 전 리스크 관리 필요."
        return f"중립적 시그널 (신뢰도 {conf}%). 실적 발표 후 대응 권장."

    def _get_recommendation_en(self, positioning: Dict) -> str:
        signal = positioning['signal']
        conf = positioning['confidence']
        if signal == 'bullish_lean':
            return f"High historical beat rate (confidence {conf}%). Consider bullish positioning pre-earnings."
        elif signal == 'bearish_lean':
            return f"Historical miss tendency (confidence {conf}%). Risk management recommended."
        return f"Neutral signal (confidence {conf}%). Consider waiting for post-earnings reaction."

    def save_data(self):
        """Run analysis and save to output/earnings_impact.json"""
        data = self.analyze_upcoming_earnings()

        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Saved earnings impact data to {self.output_file}")
        return data


def main():
    model = EarningsImpactModel()
    data = model.save_data()

    print("\n" + "=" * 60)
    print("💥 EARNINGS IMPACT ANALYSIS")
    print("=" * 60)

    # Sector profiles
    profiles = data.get('sector_profiles', {})
    if profiles:
        print(f"\n📊 Sector Reaction Profiles:")
        print(f"{'Sector':18} {'Beat 1D':>8} {'Miss 1D':>8} {'Beat%':>7} {'N':>4}")
        print("-" * 50)
        for sector, p in sorted(profiles.items()):
            print(f"{sector:18} {p['avg_beat_reaction_1d']:>+7.1f}% {p['avg_miss_reaction_1d']:>+7.1f}% {p['beat_rate']:>6.1f}% {p['sample_size']:>4}")

    # Upcoming earnings
    upcoming = data.get('upcoming_earnings', [])
    if upcoming:
        print(f"\n📅 Upcoming Earnings ({len(upcoming)} stocks):")
        for item in upcoming[:10]:
            icon = '🟢' if item['signal'] == 'bullish_lean' else '🔴' if item['signal'] == 'bearish_lean' else '⚪'
            impl = f" | Implied: {item['implied_move_pct']:.1f}%" if item.get('implied_move_pct') else ""
            print(f"  {icon} {item['ticker']:6} | {item['earnings_date']} ({item['days_until']}d) | {item['signal']:14} | Conf: {item['confidence']}%{impl}")
    else:
        print(f"\n📅 No upcoming earnings in next 14 days for tracked stocks")


if __name__ == "__main__":
    main()
