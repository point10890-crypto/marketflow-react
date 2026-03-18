#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto Market Daily Briefing v1.0

Features:
- CoinGecko global market summary (market cap, BTC dominance, volume)
- Major coin prices & changes (BTC, ETH, SOL, BNB, XRP)
- Top movers (gainers & losers from top 100)
- Crypto Fear & Greed Index
- Binance funding rates (BTC, ETH perpetual)
- Cross-asset correlations (BTC vs SPY, GLD, DXY)
- Market gate integration

Usage:
    python3 crypto_briefing.py
"""

import os
import json
import logging
import requests
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_TIMEOUT = 5


class CryptoBriefingGenerator:
    """Comprehensive crypto market briefing generator"""

    COINGECKO_BASE = 'https://api.coingecko.com/api/v3'
    FEAR_GREED_URL = 'https://api.alternative.me/fng/'
    BINANCE_FUTURES_BASE = 'https://fapi.binance.com/fapi/v1'

    MAJOR_COIN_IDS = 'bitcoin,ethereum,solana,binancecoin,ripple'
    CORRELATION_TICKERS = ['BTC-USD', 'SPY', 'GLD', 'DX-Y.NYB']
    CORRELATION_LABELS = ['BTC', 'SPY', 'GLD', 'DXY']

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_dir = os.path.join(data_dir, 'output')
        self.output_file = os.path.join(self.output_dir, 'crypto_briefing.json')

    # ------------------------------------------------------------------
    # Data Fetchers
    # ------------------------------------------------------------------

    def fetch_market_summary(self) -> Optional[Dict]:
        """CoinGecko /global -> total market cap, BTC dominance, 24h volume"""
        logger.info("Fetching global market summary from CoinGecko...")
        try:
            resp = requests.get(
                f'{self.COINGECKO_BASE}/global',
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get('data', {})

            total_market_cap = data.get('total_market_cap', {}).get('usd', 0)
            total_volume_24h = data.get('total_volume', {}).get('usd', 0)
            btc_dominance = data.get('market_cap_percentage', {}).get('btc', 0)
            eth_dominance = data.get('market_cap_percentage', {}).get('eth', 0)
            market_cap_change_24h = data.get('market_cap_change_percentage_24h_usd', 0)
            active_cryptos = data.get('active_cryptocurrencies', 0)

            return {
                'total_market_cap': round(total_market_cap, 0),
                'total_volume_24h': round(total_volume_24h, 0),
                'btc_dominance': round(btc_dominance, 2),
                'btc_dominance_change_24h': 0,
                'total_market_cap_change_24h': round(market_cap_change_24h, 2),
                'active_cryptocurrencies': active_cryptos,
            }
        except Exception as e:
            logger.error(f"Failed to fetch market summary: {e}")
            return None

    def fetch_major_coins(self) -> Optional[List[Dict]]:
        """CoinGecko /coins/markets -> price, change, volume, market cap for major coins"""
        logger.info("Fetching major coin data from CoinGecko...")
        try:
            resp = requests.get(
                f'{self.COINGECKO_BASE}/coins/markets',
                params={
                    'vs_currency': 'usd',
                    'ids': self.MAJOR_COIN_IDS,
                    'order': 'market_cap_desc',
                },
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            coins = resp.json()

            result = []
            for coin in coins:
                result.append({
                    'id': coin.get('id', ''),
                    'symbol': coin.get('symbol', '').upper(),
                    'name': coin.get('name', ''),
                    'price_usd': coin.get('current_price', 0),
                    'change_24h_pct': round(coin.get('price_change_percentage_24h', 0) or 0, 2),
                    'change_7d_pct': round(coin.get('price_change_percentage_7d_in_currency', 0) or 0, 2),
                    'volume_24h_usd': coin.get('total_volume', 0),
                    'market_cap_usd': coin.get('market_cap', 0),
                    'ath': coin.get('ath', 0),
                    'ath_change_pct': round(coin.get('ath_change_percentage', 0) or 0, 2),
                })
            return result
        except Exception as e:
            logger.error(f"Failed to fetch major coins: {e}")
            return None

    def fetch_top_movers(self) -> Optional[Dict]:
        """CoinGecko /coins/markets top 100 -> top 5 gainers & losers by 24h change"""
        logger.info("Fetching top movers from CoinGecko...")
        try:
            resp = requests.get(
                f'{self.COINGECKO_BASE}/coins/markets',
                params={
                    'vs_currency': 'usd',
                    'order': 'market_cap_desc',
                    'per_page': 100,
                    'page': 1,
                },
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            coins = resp.json()

            # Filter out coins with None price_change_percentage_24h
            valid_coins = [
                c for c in coins
                if c.get('price_change_percentage_24h') is not None
            ]

            sorted_by_change = sorted(
                valid_coins,
                key=lambda c: c.get('price_change_percentage_24h', 0),
            )

            def _coin_summary(c):
                return {
                    'symbol': c.get('symbol', '').upper(),
                    'name': c.get('name', ''),
                    'price': c.get('current_price', 0),
                    'change_24h': round(c.get('price_change_percentage_24h', 0), 2),
                }

            top_gainers = [_coin_summary(c) for c in reversed(sorted_by_change[-5:])]
            top_losers = [_coin_summary(c) for c in sorted_by_change[:5]]

            return {
                'gainers': top_gainers,
                'losers': top_losers,
            }
        except Exception as e:
            logger.error(f"Failed to fetch top movers: {e}")
            return None

    def fetch_fear_greed(self) -> Optional[Dict]:
        """Alternative.me Fear & Greed Index -> current and previous score"""
        logger.info("Fetching Crypto Fear & Greed Index...")
        try:
            resp = requests.get(
                self.FEAR_GREED_URL,
                params={'limit': 2},
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get('data', [])

            if not data:
                return None

            current = data[0]
            previous = data[1] if len(data) > 1 else None

            current_score = int(current.get('value', 50))

            # Determine level
            if current_score >= 80:
                level = 'Extreme Greed'
            elif current_score >= 60:
                level = 'Greed'
            elif current_score >= 40:
                level = 'Neutral'
            elif current_score >= 20:
                level = 'Fear'
            else:
                level = 'Extreme Fear'

            result = {
                'score': current_score,
                'current_score': current_score,
                'current_label': current.get('value_classification', level),
                'level': level,
                'timestamp': current.get('timestamp', ''),
            }

            if previous:
                prev_score = int(previous.get('value', 50))
                result['previous'] = prev_score
                result['previous_score'] = prev_score
                result['previous_label'] = previous.get('value_classification', '')
                result['change'] = current_score - prev_score

            return result
        except Exception as e:
            logger.error(f"Failed to fetch Fear & Greed Index: {e}")
            return None

    def fetch_funding_rates(self) -> Optional[Dict]:
        """Binance Futures premiumIndex -> lastFundingRate for BTC and ETH"""
        logger.info("Fetching funding rates from Binance...")
        symbols = ['BTCUSDT', 'ETHUSDT']
        result = {}

        for symbol in symbols:
            try:
                resp = requests.get(
                    f'{self.BINANCE_FUTURES_BASE}/premiumIndex',
                    params={'symbol': symbol},
                    timeout=API_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()

                funding_rate = float(data.get('lastFundingRate', 0))
                mark_price = float(data.get('markPrice', 0))
                index_price = float(data.get('indexPrice', 0))

                # Annualized funding rate (3 funding events per day * 365)
                annualized = funding_rate * 3 * 365 * 100

                label = symbol.replace('USDT', '')
                result[label] = {
                    'symbol': symbol,
                    'rate': round(funding_rate, 6),
                    'rate_pct': round(funding_rate * 100, 4),
                    'annualized_pct': round(annualized, 2),
                    'sentiment': 'bullish' if funding_rate > 0.0001 else ('bearish' if funding_rate < -0.0001 else 'neutral'),
                }
            except Exception as e:
                logger.error(f"Failed to fetch funding rate for {symbol}: {e}")
                continue

        return result if result else None

    def calculate_correlations(self) -> Optional[Dict]:
        """yfinance 90d daily returns -> correlation matrix for BTC vs SPY, GLD, DXY"""
        logger.info("Calculating cross-asset correlations (90d)...")
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90)

            data = yf.download(
                self.CORRELATION_TICKERS,
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                progress=False,
            )['Close']

            if data.empty or len(data) < 10:
                logger.warning("Insufficient data for correlation calculation")
                return None

            # Rename columns for readability
            rename_map = dict(zip(self.CORRELATION_TICKERS, self.CORRELATION_LABELS))
            data = data.rename(columns=rename_map)

            # Daily returns
            returns = data.pct_change(fill_method=None).dropna()
            available = [c for c in self.CORRELATION_LABELS if c in returns.columns]

            if len(available) < 2:
                return None

            returns_matrix = returns[available].values
            corr_matrix = np.corrcoef(returns_matrix, rowvar=False)

            # Build output
            correlations = {}
            btc_idx = available.index('BTC') if 'BTC' in available else None

            if btc_idx is not None:
                for i, label in enumerate(available):
                    if label == 'BTC':
                        continue
                    corr_val = float(corr_matrix[btc_idx, i])
                    correlations[f'BTC_{label}'] = round(corr_val, 4)

            return {
                'period_days': 90,
                'assets': available,
                'btc_correlations': correlations,
                'matrix': {
                    'labels': available,
                    'values': [[round(float(v), 4) for v in row] for row in corr_matrix],
                },
            }
        except Exception as e:
            logger.error(f"Failed to calculate correlations: {e}")
            return None

    def load_market_gate(self) -> Optional[Dict]:
        """Load market_gate.json if it exists"""
        logger.info("Loading market gate data...")
        gate_path = os.path.join(self.output_dir, 'market_gate.json')
        if not os.path.exists(gate_path):
            logger.info("No market_gate.json found, skipping")
            return None

        try:
            with open(gate_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load market gate: {e}")
            return None

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self) -> Dict:
        """Orchestrate all data fetches, assemble briefing, save to JSON"""
        logger.info("Starting crypto briefing generation...")

        result = {
            'timestamp': datetime.now().isoformat(),
            'version': '1.0',
        }

        # 1. Global market summary
        market_summary = self.fetch_market_summary()
        result['market_summary'] = market_summary

        # 2. Major coins (convert list -> dict keyed by symbol for frontend/API)
        major_coins_list = self.fetch_major_coins()
        if major_coins_list:
            result['major_coins'] = {
                c['symbol']: {
                    'price': c['price_usd'],
                    'change_24h': c['change_24h_pct'],
                    'change_7d': c['change_7d_pct'],
                    'volume_24h': c['volume_24h_usd'],
                    'market_cap': c['market_cap_usd'],
                }
                for c in major_coins_list
            }
        else:
            result['major_coins'] = {}

        # 3. Top movers
        top_movers = self.fetch_top_movers()
        result['top_movers'] = top_movers

        # 4. Fear & Greed
        fear_greed = self.fetch_fear_greed()
        result['fear_greed'] = fear_greed

        # 5. Funding rates
        funding_rates = self.fetch_funding_rates()
        result['funding_rates'] = funding_rates

        # 6. Macro correlations (BTC vs SPY, GLD, DXY)
        correlations = self.calculate_correlations()
        if correlations and 'btc_correlations' in correlations:
            result['macro_correlations'] = {
                'btc_pairs': correlations['btc_correlations'],
            }
        else:
            result['macro_correlations'] = {'btc_pairs': {}}

        # 7. Market gate (optional, from existing output)
        market_gate = self.load_market_gate()
        result['market_gate'] = market_gate

        # 8. BTC price history for charts
        try:
            btc_hist = yf.download('BTC-USD', period='90d', progress=False)
            if not btc_hist.empty:
                if hasattr(btc_hist.columns, 'levels'):
                    btc_hist.columns = btc_hist.columns.get_level_values(0)
                close_vals = btc_hist['Close']
                result['btc_price_history'] = [
                    {'date': d.strftime('%Y-%m-%d'), 'price': float(v)}
                    for d, v in close_vals.items()
                ]
        except Exception:
            result['btc_price_history'] = []

        # Sentiment summary (frontend key: sentiment_summary)
        assessment = self._build_assessment(result)
        result['sentiment_summary'] = {
            'overall': assessment.get('overall_sentiment', 'neutral').capitalize(),
            'factors': [
                f"{d['source']}: {d['state']} ({d['direction']})"
                for d in assessment.get('signal_details', [])
            ],
        }

        # Save
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved crypto briefing to {self.output_file}")
        return result

    def _build_assessment(self, data: Dict) -> Dict:
        """Build a simple sentiment assessment from collected data"""
        signals = []

        # Fear & Greed
        fg = data.get('fear_greed')
        if fg:
            score = fg.get('current_score', 50)
            if score >= 70:
                signals.append(('fear_greed', 'extreme_greed', -1))  # contrarian
            elif score >= 55:
                signals.append(('fear_greed', 'greed', 0))
            elif score >= 40:
                signals.append(('fear_greed', 'neutral', 0))
            elif score >= 25:
                signals.append(('fear_greed', 'fear', 1))  # contrarian bullish
            else:
                signals.append(('fear_greed', 'extreme_fear', 1))

        # Funding rates
        fr = data.get('funding_rates', {})
        if fr and 'BTC' in fr:
            rate = fr['BTC'].get('rate', 0)
            if rate > 0.0005:
                signals.append(('funding', 'high_positive', -1))  # over-leveraged longs
            elif rate > 0:
                signals.append(('funding', 'positive', 0))
            elif rate < -0.0003:
                signals.append(('funding', 'negative', 1))  # shorts paying, bullish
            else:
                signals.append(('funding', 'neutral', 0))

        # BTC dominance trend
        ms = data.get('market_summary')
        if ms:
            btc_dom = ms.get('btc_dominance', 50)
            if btc_dom > 55:
                signals.append(('dominance', 'btc_high', 0))
            elif btc_dom < 40:
                signals.append(('dominance', 'alt_season', 0))

        # Market cap change
        if ms:
            cap_change = ms.get('total_market_cap_change_24h', 0)
            if cap_change > 3:
                signals.append(('momentum', 'strong_up', 1))
            elif cap_change < -3:
                signals.append(('momentum', 'strong_down', -1))

        # Aggregate
        bullish_count = sum(1 for _, _, s in signals if s > 0)
        bearish_count = sum(1 for _, _, s in signals if s < 0)

        if bullish_count > bearish_count + 1:
            overall = 'bullish'
        elif bearish_count > bullish_count + 1:
            overall = 'bearish'
        else:
            overall = 'neutral'

        return {
            'overall_sentiment': overall,
            'signal_details': [
                {'source': src, 'state': state, 'direction': 'bullish' if d > 0 else ('bearish' if d < 0 else 'neutral')}
                for src, state, d in signals
            ],
        }


if __name__ == '__main__':
    generator = CryptoBriefingGenerator(
        data_dir=os.path.dirname(os.path.abspath(__file__))
    )
    result = generator.run()

    print("\n" + "=" * 60)
    print("CRYPTO MARKET BRIEFING")
    print("=" * 60)

    ms = result.get('market_summary')
    if ms:
        print(f"\nTotal Market Cap: ${ms['total_market_cap']:,.0f}")
        print(f"24h Volume:      ${ms['total_volume_24h']:,.0f}")
        print(f"BTC Dominance:   {ms['btc_dominance']:.1f}%")
        print(f"Market Cap 24h:  {ms['total_market_cap_change_24h']:+.2f}%")

    coins = result.get('major_coins', {})
    if coins:
        print(f"\nMajor Coins:")
        for symbol, c in coins.items():
            print(f"  {symbol:5} ${c['price']:>10,.2f}  24h: {c['change_24h']:+6.2f}%  7d: {c['change_7d']:+6.2f}%")

    fg = result.get('fear_greed')
    if fg:
        print(f"\nFear & Greed:    {fg['current_score']} ({fg['level']})")
        if 'previous_score' in fg:
            print(f"  Previous:      {fg['previous_score']} (change: {fg['change']:+d})")

    fr = result.get('funding_rates')
    if fr:
        print(f"\nFunding Rates:")
        for label, info in fr.items():
            print(f"  {label}: {info['rate_pct']:+.4f}% (annualized: {info['annualized_pct']:+.2f}%) [{info['sentiment']}]")

    corr = result.get('macro_correlations', {})
    if corr:
        print(f"\nBTC Correlations (90d):")
        for pair, val in corr.get('btc_pairs', {}).items():
            print(f"  {pair}: {val:+.4f}")

    sentiment = result.get('sentiment_summary', {})
    print(f"\nOverall Sentiment: {sentiment.get('overall', 'N/A').upper()}")
